"""
Backups of the prediction log, the one thing in the database that can't be rebuilt.

  uv run python -m src.pipeline.backup                     # or `make backup`; nightly too
  uv run python -m src.pipeline.backup --restore [FILE]    # or `make restore-predictions`

Everything else in Postgres can be reloaded from College Hockey News, but a prediction
logged *before* a game can't be recreated afterwards. `make db-reset` deletes the database
volume, so it takes a backup first.

  * Backup: the whole `predictions.game_predictions` table as a gzipped CSV,
    data/backups/predictions_<Eastern date>.csv.gz (a second run the same day replaces that
    day's file). The newest KEEP files are kept. data/ is gitignored (CHN-derived data).
  * Restore: adds the rows from a backup that aren't in the log yet. It never overwrites a row
    that's already there, so it's safe to run at any time, and twice.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import io
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg

from config.settings import settings
from src.db.load import refresh_guard

ROOT = Path(__file__).resolve().parents[2]
BACKUP_DIR = ROOT / "data" / "backups"
PREDICTIONS_SQL = ROOT / "db" / "predictions.sql"
TABLE = "predictions.game_predictions"
KEEP = 30
EASTERN = ZoneInfo("America/New_York")


def backups(out_dir: Path = BACKUP_DIR) -> list[Path]:
    """Backup files, oldest first."""
    return sorted(out_dir.glob("predictions_*.csv.gz"))


def backup_predictions(
    database_url: str, out_dir: Path = BACKUP_DIR, keep: int = KEEP, today: dt.date | None = None
) -> tuple[Path | None, int]:
    """Write today's backup and prune old ones. Returns (file, rows); (None, 0) if no log yet."""
    today = today or dt.datetime.now(EASTERN).date()
    with psycopg.connect(database_url) as conn:
        if conn.execute("SELECT to_regclass(%s)", (TABLE,)).fetchone()[0] is None:
            return None, 0
        buf = io.BytesIO()
        with conn.cursor().copy(
            f"COPY (SELECT * FROM {TABLE} ORDER BY game_id, model) TO STDOUT WITH (FORMAT csv, HEADER)"
        ) as copy:
            for chunk in copy:
                buf.write(chunk)
    data = buf.getvalue()
    rows = max(data.count(b"\n") - 1, 0)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"predictions_{today.isoformat()}.csv.gz"
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(gzip.compress(data))
    tmp.replace(path)  # never leave a half-written backup
    for old in backups(out_dir)[:-keep]:
        old.unlink()
    return path, rows


def restore_predictions(database_url: str, path: Path) -> tuple[int, int]:
    """Add a backup's rows that aren't in the log. Returns (rows in file, rows added)."""
    text = gzip.decompress(path.read_bytes()).decode()
    header = next(csv.reader(io.StringIO(text)))
    cols = ", ".join(header)
    with psycopg.connect(database_url) as conn:
        conn.execute(PREDICTIONS_SQL.read_text())
        conn.execute(f"CREATE TEMP TABLE restore (LIKE {TABLE}) ON COMMIT DROP")
        with conn.cursor().copy(f"COPY restore ({cols}) FROM STDIN WITH (FORMAT csv, HEADER)") as copy:
            copy.write(text)
        total = conn.execute("SELECT count(*) FROM restore").fetchone()[0]
        added = conn.execute(
            f"INSERT INTO {TABLE} ({cols}) SELECT {cols} FROM restore "
            "ON CONFLICT (game_id, model) DO NOTHING"
        ).rowcount
        conn.commit()
    return total, added


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--restore", nargs="?", const="latest", metavar="FILE",
        help="Restore a backup (default: the newest in data/backups)",
    )
    args = ap.parse_args()
    if args.restore is None:
        path, rows = backup_predictions(settings.database_url)
        if path is None:
            print("No prediction log yet; nothing to back up.")
        else:
            print(f"Backed up {rows} predictions to {path.relative_to(ROOT)} "
                  f"({len(backups())} backups kept)")
        return
    path = backups()[-1] if args.restore == "latest" and backups() else Path(args.restore)
    if not path.exists():
        raise SystemExit(f"No backup at {path}. Backups live in {BACKUP_DIR.relative_to(ROOT)}/.")
    with refresh_guard(settings.database_url):
        total, added = restore_predictions(settings.database_url, path)
    print(f"Restored from {path.name}: {added} of {total} predictions added "
          f"({total - added} were already in the log)")


if __name__ == "__main__":
    main()
