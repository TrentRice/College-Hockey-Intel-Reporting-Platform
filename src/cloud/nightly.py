"""
The nightly refresh in GitHub Actions (the private data repo's workflow, docs/cloud.md).

  python -m src.cloud.nightly                          # men's, if due (the Mac scheduler's rules)
  CHIRP_LEAGUE=women python -m src.cloud.nightly       # women's
  python -m src.cloud.nightly --force                  # run now

Each league is its own run, with its own files (config/leagues.py: data/ and data/women/),
database, history and logs; the workflow runs the men's, then the women's.

The job's database is new and empty each time, so before the refresh this loads what the
data repo remembers (the run history and the newest prediction-log backup), and afterwards
writes the history back and copies the run's log into data/logs/. The workflow then commits
data/: everything after a successful run, only the history and logs otherwise, so the app
never serves data that failed validation.

Exit code: 0 if the refresh succeeded or wasn't due, 1 otherwise (so the Actions run shows red
and GitHub emails you).
"""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
import sys
from pathlib import Path

import psycopg

from config import leagues
from config.settings import settings
from src.cloud.runs import RUNS_FILE, export_runs, import_runs, runs_today
from src.pipeline.backup import BACKUP_DIR, backups, restore_predictions
from src.pipeline.refresh import KEEP_LOGS, LOG_DIR, refresh
from src.pipeline.scheduler import should_run

# Where the run's log is kept in the data repo: logs/refresh/ (men's), women/logs/refresh/
DATA_LOG_DIR = leagues.current().data / "logs" / "refresh"


def copy_logs(src: Path = LOG_DIR, dst: Path = DATA_LOG_DIR, keep: int = KEEP_LOGS) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.glob("*"):
        shutil.copy2(f, dst / f.name)
    logs = sorted(dst.glob("*.log"))
    for old in logs[:-keep]:
        old.unlink(missing_ok=True)
        old.with_suffix(".validation.md").unlink(missing_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Nightly refresh for GitHub Actions")
    ap.add_argument("--force", action="store_true", help="run even if not due")
    args = ap.parse_args()

    now = dt.datetime.now(dt.UTC)
    due, reason = should_run(now, runs_today(now, RUNS_FILE))
    if not due and not args.force:
        print(f"Not due: {reason}")
        sys.exit(0)

    url = settings.database_url
    with psycopg.connect(url, autocommit=True) as conn:
        print(f"Run history: {import_runs(conn, RUNS_FILE)} earlier runs")
    if found := backups(BACKUP_DIR):
        total, _ = restore_predictions(url, found[-1])
        print(f"Prediction log: {total} rows from {found[-1].name}")

    outcome = refresh("manual" if args.force else "scheduled", database_url=url)

    with psycopg.connect(url, autocommit=True) as conn:
        export_runs(conn, RUNS_FILE)
    copy_logs(LOG_DIR, DATA_LOG_DIR)
    sys.exit(0 if outcome.status == "success" else 1)


if __name__ == "__main__":
    main()
