import sys
from pathlib import Path

import psycopg
import pytest

from src.pipeline import refresh as pipeline
from src.pipeline.refresh import Step, run_steps


def ok(name, gate=False):
    return Step(name, [sys.executable, "-c", f"print('{name} ran')"], gate=gate)


def fail(name, gate=False):
    return Step(name, [sys.executable, "-c", "import sys; sys.exit(3)"], gate=gate)


@pytest.fixture
def log(tmp_path):
    with (tmp_path / "run.log").open("w+") as f:
        yield f


def test_all_steps_run_in_order(log):
    out = run_steps([ok("a"), ok("b"), ok("c")], log)
    assert out.status == "success"
    assert list(out.timings) == ["a", "b", "c"]
    log.seek(0)
    text = log.read()
    assert text.index("a ran") < text.index("c ran")


def test_a_failure_stops_the_run(log):
    out = run_steps([ok("scrape"), fail("parse"), ok("load")], log)
    assert (out.status, out.failed_step) == ("failed", "parse")
    assert "load" not in out.timings


def test_the_validation_gate_blocks_the_load(log):
    out = run_steps([ok("parse"), fail("validate", gate=True), ok("load")], log)
    assert (out.status, out.failed_step) == ("blocked", "validate")
    assert "load" not in out.timings


def test_a_hung_step_times_out(log):
    slow = Step("slow", [sys.executable, "-c", "import time; time.sleep(5)"])
    out = run_steps([slow], log, timeout=0.5)
    assert (out.status, out.failed_step) == ("failed", "slow")


# ----------------------------------------------------------------------------
# Against the test database: run records and the lock
# ----------------------------------------------------------------------------


@pytest.fixture
def db(database_url, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "LOG_DIR", tmp_path / "logs")
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS ops CASCADE")
    return database_url


def last_run(url):
    with psycopg.connect(url) as conn:
        return conn.execute(
            "SELECT status, trigger, failed_step, finished_at IS NOT NULL, log_file "
            "FROM ops.pipeline_runs ORDER BY run_id DESC LIMIT 1"
        ).fetchone()


def test_a_run_is_recorded_with_its_log(db, tmp_path):
    out = pipeline.refresh("scheduled", db, steps=[ok("a"), ok("b")])
    assert out.status == "success"
    status, trigger, failed_step, finished, log_file = last_run(db)
    assert (status, trigger, failed_step, finished) == ("success", "scheduled", None, True)
    assert "b ran" in Path(log_file).read_text()


def test_a_blocked_run_is_recorded(db):
    pipeline.refresh("manual", db, steps=[fail("validate", gate=True), ok("load")])
    assert last_run(db)[:3] == ("blocked", "manual", "validate")


def test_only_one_run_at_a_time(db):
    with psycopg.connect(db, autocommit=True) as other:
        other.execute("SELECT pg_advisory_lock(%s)", (pipeline.LOCK_ID,))  # a run in progress
        out = pipeline.refresh("manual", db, steps=[ok("a")])
    assert (out.status, out.failed_step) == ("failed", "lock")


def test_health_reports_the_last_refresh(db, client):
    pipeline.refresh("scheduled", db, steps=[ok("a")])
    pipeline.refresh("manual", db, steps=[fail("validate", gate=True)])
    body = client.get("/health").json()
    assert body["last_refresh"]["status"] == "blocked"
    assert body["data_as_of"] is not None  # from the earlier successful run


def insert_running(url):
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(pipeline.OPS_SQL)
        conn.execute(
            "INSERT INTO ops.pipeline_runs (status, trigger) VALUES ('running', 'scheduled')"
        )


def test_an_interrupted_run_is_cleared(db):
    insert_running(db)  # e.g. the container was rebuilt mid-run
    with psycopg.connect(db, autocommit=True) as conn:
        assert pipeline.clear_stale_runs(conn) == 1
    assert last_run(db)[:3] == ("failed", "scheduled", "interrupted")


def test_a_live_run_is_not_cleared(db):
    insert_running(db)
    with (
        psycopg.connect(db, autocommit=True) as holder,
        psycopg.connect(db, autocommit=True) as conn,
    ):
        holder.execute("SELECT pg_advisory_lock(%s)", (pipeline.LOCK_ID,))  # really running
        assert pipeline.clear_stale_runs(conn) == 0
    assert last_run(db)[0] == "running"


def test_a_new_run_clears_old_orphans(db):
    insert_running(db)
    pipeline.refresh("manual", db, steps=[ok("a")])
    with psycopg.connect(db) as conn:
        statuses = [
            r[0] for r in conn.execute("SELECT status FROM ops.pipeline_runs ORDER BY run_id")
        ]
    assert statuses == ["failed", "success"]


def test_a_manual_load_waits_for_a_running_refresh(db, monkeypatch):
    from src.db.load import refresh_guard

    monkeypatch.delenv(pipeline.IN_PIPELINE_ENV, raising=False)
    with psycopg.connect(db, autocommit=True) as holder:
        holder.execute("SELECT pg_advisory_lock(%s)", (pipeline.LOCK_ID,))
        with pytest.raises(SystemExit, match="refresh is running"), refresh_guard(db):
            pass
    with refresh_guard(db):  # free again
        pass
