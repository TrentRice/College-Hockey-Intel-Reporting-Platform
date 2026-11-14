"""
The refresh pipeline: scrape -> download -> parse -> validate -> ids -> load.

  uv run python -m src.pipeline.refresh          # or: make refresh
  (the Docker `pipeline` service runs it nightly; see src/pipeline/scheduler.py)

Steps run in order as separate processes, exactly as you'd run them by hand, and the run
stops at the first failure. Validation is a gate: if it finds an unexplained mismatch the
load is skipped, so the database keeps serving the last good data (status 'blocked').

Safety
  * One run at a time, wherever it was started (Docker or your terminal): a Postgres
    advisory lock is held for the whole run.
  * Every run is recorded in ops.pipeline_runs (outside the `hockey` schema, which each
    load rebuilds), and the API's /health shows the latest one.
  * Each run writes logs/refresh/<timestamp>.log, plus that run's validation report.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import psycopg

from config.settings import settings

LOG_DIR = Path("logs/refresh")
KEEP_LOGS = 60
LOCK_ID = 7_310_001  # arbitrary, unique to this pipeline
IN_PIPELINE_ENV = "CHIRP_IN_PIPELINE"  # set for the steps, so `src.db.load` knows the lock is ours
STEP_TIMEOUT = 45 * 60  # seconds

OPS_SQL = """
CREATE SCHEMA IF NOT EXISTS ops;
CREATE TABLE IF NOT EXISTS ops.pipeline_runs (
    run_id        BIGSERIAL PRIMARY KEY,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    status        TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed', 'blocked')),
    trigger       TEXT NOT NULL CHECK (trigger IN ('manual', 'scheduled')),
    failed_step   TEXT,
    played_before INTEGER,
    played_after  INTEGER,
    log_file      TEXT,
    message       TEXT
);
"""


@dataclass
class Step:
    name: str
    args: list[str]
    gate: bool = False  # failing here means "the data isn't trustworthy", not "it broke"


def default_steps(report_path: Path) -> list[Step]:
    py = [sys.executable, "-m"]
    return [
        Step("schedules", [*py, "src.ingestion.chn_team_schedule_scraper", "--strict"]),
        # not --strict: one missing box score shouldn't stop the rest; validation catches it
        Step("boxscores", [*py, "src.ingestion.chn_boxscore_downloader"]),
        Step("parse", [*py, "src.ingestion.chn_boxscore_parser"]),
        Step(
            "validate",
            [*py, "src.evaluation.validate_chn_data", "--strict", "--report", str(report_path)],
            gate=True,
        ),
        Step("ids", [*py, "src.transform.id_mapping"]),
        Step("load", [*py, "src.db.load"]),
        # after the load: log win probabilities for the coming week (db/predictions.sql)
        Step("predict", [*py, "src.pipeline.predict"]),
    ]


@dataclass
class Outcome:
    status: str  # success | failed | blocked
    failed_step: str | None = None
    timings: dict[str, float] = field(default_factory=dict)


def run_steps(steps: list[Step], log, timeout: float = STEP_TIMEOUT) -> Outcome:
    """Run steps in order, streaming their output to `log`; stop at the first failure."""
    timings: dict[str, float] = {}
    for step in steps:
        log.write(f"\n===== {step.name}: {' '.join(step.args[1:])}\n")
        log.flush()
        start = time.monotonic()
        try:
            code = subprocess.run(
                step.args,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
                env={**os.environ, IN_PIPELINE_ENV: "1"},
            ).returncode
        except subprocess.TimeoutExpired:
            log.write(f"\n{step.name} timed out after {timeout:.0f}s\n")
            code = -1
        timings[step.name] = round(time.monotonic() - start, 1)
        log.write(f"===== {step.name}: exit {code} in {timings[step.name]}s\n")
        log.flush()
        if code != 0:
            return Outcome("blocked" if step.gate else "failed", step.name, timings)
    return Outcome("success", None, timings)


def played_games(conn: psycopg.Connection) -> int | None:
    if conn.execute("SELECT to_regclass('hockey.games')").fetchone()[0] is None:
        return None
    return conn.execute("SELECT COUNT(*) FROM hockey.games WHERE is_played").fetchone()[0]


def prune_logs(log_dir: Path, keep: int = KEEP_LOGS) -> None:
    logs = sorted(log_dir.glob("*.log"))
    for old in logs[:-keep]:
        old.unlink(missing_ok=True)
        old.with_suffix(".validation.md").unlink(missing_ok=True)


def mark_interrupted(conn: psycopg.Connection) -> int:
    """Runs left 'running' by a process that died (container rebuilt, Mac shut down). Only
    call while holding the lock: then nothing else can really be running."""
    cur = conn.execute(
        "UPDATE ops.pipeline_runs SET status = 'failed', failed_step = 'interrupted', "
        "finished_at = now(), message = 'process stopped before the run finished' "
        "WHERE status = 'running'"
    )
    return cur.rowcount


def clear_stale_runs(conn: psycopg.Connection) -> int:
    """If no refresh holds the lock, any 'running' row is an orphan: mark it failed."""
    if not conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_ID,)).fetchone()[0]:
        return 0  # a refresh really is running
    try:
        return mark_interrupted(conn)
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))


def refresh(
    trigger: str = "manual", database_url: str | None = None, steps: list[Step] | None = None
) -> Outcome:
    url = database_url or settings.database_url
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%dT%H%M%S")
    log_path = LOG_DIR / f"{stamp}.log"
    report_path = log_path.with_suffix(".validation.md")
    steps = steps or default_steps(report_path)

    # the lock connection stays open for the whole run; Postgres frees the lock if we die
    with psycopg.connect(url, autocommit=True) as lock_conn:
        lock_conn.execute(OPS_SQL)
        if not lock_conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_ID,)).fetchone()[0]:
            print("Another refresh is running; not starting a second one.")
            return Outcome("failed", "lock")
        if stale := mark_interrupted(lock_conn):
            print(f"Marked {stale} interrupted earlier run(s) as failed.")
        before = played_games(lock_conn)
        (run_id,) = lock_conn.execute(
            "INSERT INTO ops.pipeline_runs (status, trigger, played_before, log_file) "
            "VALUES ('running', %s, %s, %s) RETURNING run_id",
            (trigger, before, str(log_path)),
        ).fetchone()
        print(f"Refresh #{run_id} ({trigger}) -> {log_path}")

        outcome = Outcome("failed", "internal")
        try:
            with log_path.open("w", encoding="utf-8") as log:
                log.write(
                    f"Refresh #{run_id} ({trigger}) started {dt.datetime.now().isoformat()}\n"
                )
                outcome = run_steps(steps, log)
        finally:
            after = played_games(lock_conn)
            message = ", ".join(f"{k} {v}s" for k, v in outcome.timings.items())
            lock_conn.execute(
                "UPDATE ops.pipeline_runs SET finished_at = now(), status = %s, failed_step = %s, "
                "played_after = %s, message = %s WHERE run_id = %s",
                (outcome.status, outcome.failed_step, after, message, run_id),
            )
            lock_conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))
            prune_logs(LOG_DIR)

    new = (after or 0) - (before or 0) if outcome.status == "success" else 0
    summary = {
        "success": f"done: {new} newly played game(s) loaded",
        "blocked": "validation found unexplained mismatches; load skipped, the database keeps "
        f"the last good data. See {report_path}",
        "failed": f"failed at step '{outcome.failed_step}'. See {log_path}",
    }[outcome.status]
    print(f"Refresh #{run_id} {outcome.status}: {summary}")
    return outcome


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the full data refresh once")
    ap.add_argument("--trigger", choices=["manual", "scheduled"], default="manual")
    args = ap.parse_args()
    sys.exit(0 if refresh(args.trigger).status == "success" else 1)


if __name__ == "__main__":
    main()
