"""
The refresh history as a file, data/pipeline_runs.csv.

On the Mac, ops.pipeline_runs lives in the long-running database. In the cloud every
database is temporary (a fresh one per nightly job, and one per app start), so the history
travels in the data repo as a CSV: the nightly job loads it before the refresh and writes it
back after; the app loads it so /health (and the dashboard's "Data refreshed ..." line) works.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg

from src.pipeline.refresh import OPS_SQL

RUNS_FILE = Path("data/pipeline_runs.csv")
COLUMNS = [
    "started_at", "finished_at", "status", "trigger", "failed_step",
    "played_before", "played_after", "log_file", "message",
]
KEEP = 500  # rows; about a year and a half of nightly runs
EASTERN = ZoneInfo("America/New_York")


def import_runs(conn: psycopg.Connection, path: Path = RUNS_FILE) -> int:
    """Replace ops.pipeline_runs with the file's rows (in order). Returns rows loaded."""
    conn.execute(OPS_SQL)
    conn.execute("TRUNCATE ops.pipeline_runs RESTART IDENTITY")
    if not path.exists():
        return 0
    cols = ", ".join(COLUMNS)
    with conn.cursor().copy(
        f"COPY ops.pipeline_runs ({cols}) FROM STDIN WITH (FORMAT csv, HEADER)"
    ) as copy:
        copy.write(path.read_bytes())
    return conn.execute("SELECT count(*) FROM ops.pipeline_runs").fetchone()[0]


def export_runs(conn: psycopg.Connection, path: Path = RUNS_FILE, keep: int = KEEP) -> int:
    """Write ops.pipeline_runs (oldest first, the newest `keep`) to the file. Returns rows."""
    cols = ", ".join(COLUMNS)
    buf = io.BytesIO()
    with conn.cursor().copy(
        f"COPY (SELECT {cols} FROM (SELECT * FROM ops.pipeline_runs ORDER BY run_id DESC "
        f"LIMIT {int(keep)}) r ORDER BY run_id) TO STDOUT WITH (FORMAT csv, HEADER)"
    ) as copy:
        for chunk in copy:
            buf.write(chunk)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(buf.getvalue())
    tmp.replace(path)
    return max(buf.getvalue().count(b"\n") - 1, 0)


def runs_today(now: dt.datetime, path: Path = RUNS_FILE) -> list[tuple[dt.datetime, str]]:
    """(started_at, status) of the runs that started on now's Eastern date, from the file."""
    if not path.exists():
        return []
    today = now.astimezone(EASTERN).date()
    out = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            started = dt.datetime.fromisoformat(row["started_at"])
            if started.astimezone(EASTERN).date() == today:
                out.append((started, row["status"]))
    return out
