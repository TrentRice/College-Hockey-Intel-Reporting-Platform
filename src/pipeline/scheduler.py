"""
Runs the refresh once a day. This is the Docker `pipeline` service's main process.

Every CHECK_EVERY it asks ops.pipeline_runs: has today's refresh succeeded yet? It runs one
when all of these hold:
  * it's after RUN_AFTER Eastern (late West Coast games are final by then)
  * today has no successful run
  * fewer than MAX_ATTEMPTS tries today, and the last one was over RETRY_AFTER ago
  * in the off-season (OFFSEASON_MONTHS), only on Mondays: schedules change slowly then

Because it checks rather than firing at an exact time, a Mac that was asleep at 5 a.m. (or
Docker that was closed) catches up as soon as it's back. A run started by hand counts too.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from zoneinfo import ZoneInfo

import psycopg

from config.settings import settings
from src.pipeline.refresh import OPS_SQL, clear_stale_runs, refresh

log = logging.getLogger("chirp.scheduler")

EASTERN = ZoneInfo("America/New_York")
RUN_AFTER = dt.time(5, 0)
CHECK_EVERY = 15 * 60  # seconds
RETRY_AFTER = dt.timedelta(hours=1)
MAX_ATTEMPTS = 3
OFFSEASON_MONTHS = {5, 6, 7, 8}  # May-August: weekly
OFFSEASON_WEEKDAY = 0  # Monday


def should_run(now: dt.datetime, runs_today: list[tuple[dt.datetime, str]]) -> tuple[bool, str]:
    """now: aware datetime. runs_today: (started_at, status) of today's runs (Eastern).
    -> (run?, reason)"""
    local = now.astimezone(EASTERN)
    if local.month in OFFSEASON_MONTHS and local.weekday() != OFFSEASON_WEEKDAY:
        return False, "off-season: refreshes run on Mondays"
    if local.time() < RUN_AFTER:
        return False, f"waiting until {RUN_AFTER:%H:%M} Eastern"
    statuses = [s for _, s in runs_today]
    if "success" in statuses:
        return False, "today's refresh already succeeded"
    if "running" in statuses:
        return False, "a refresh is running"
    if len(runs_today) >= MAX_ATTEMPTS:
        return False, f"{MAX_ATTEMPTS} attempts today; trying again tomorrow"
    if runs_today and now - max(t for t, _ in runs_today) < RETRY_AFTER:
        return False, "last attempt was under an hour ago"
    return True, "due"


def runs_today(conn: psycopg.Connection, now: dt.datetime) -> list[tuple[dt.datetime, str]]:
    day_start = dt.datetime.combine(now.astimezone(EASTERN).date(), dt.time(), EASTERN)
    return conn.execute(
        "SELECT started_at, status FROM ops.pipeline_runs WHERE started_at >= %s ORDER BY started_at",
        (day_start,),
    ).fetchall()


def tick() -> None:
    now = dt.datetime.now(dt.UTC)
    try:
        with psycopg.connect(settings.database_url, autocommit=True, connect_timeout=5) as conn:
            conn.execute(OPS_SQL)
            if stale := clear_stale_runs(conn):
                log.warning("marked %d interrupted run(s) as failed", stale)
            run, reason = should_run(now, runs_today(conn, now))
    except psycopg.OperationalError as e:
        log.warning("database not reachable (%s); will check again", e)
        return
    if not run:
        log.debug("not running: %s", reason)
        return
    log.info("starting the daily refresh")
    outcome = refresh(trigger="scheduled")
    log.info(
        "refresh finished: %s%s",
        outcome.status,
        f" at {outcome.failed_step}" if outcome.failed_step else "",
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    log.info(
        "scheduler up: daily after %s Eastern, checking every %d min",
        RUN_AFTER.strftime("%H:%M"),
        CHECK_EVERY // 60,
    )
    while True:
        try:
            tick()
        except Exception:  # never let one bad night kill the service
            log.exception("scheduler tick failed")
        time.sleep(CHECK_EVERY)


if __name__ == "__main__":
    main()
