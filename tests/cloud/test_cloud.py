"""The cloud pieces (docs/cloud.md): the data download filter, the run history file and the
nightly job's helpers. The full app is checked by starting it for real; see docs/cloud.md."""

import datetime as dt
import io
import tarfile

import psycopg
import pytest

from src.cloud import nightly
from src.cloud.backend import extract, wanted
from src.cloud.runs import COLUMNS, export_runs, import_runs, runs_today
from src.pipeline.refresh import Outcome

# ---------------------------------------------------------------------------- download


def test_only_what_the_app_needs_is_extracted():
    assert wanted("TrentRice-CHIRP-data-abc123/processed/chn/box_games_2026_27.csv")
    assert wanted("x-abc/processed/ids/players.csv") == "processed/ids/players.csv"
    assert wanted("x-abc/backups/predictions_2026-11-20.csv.gz")
    assert wanted("x-abc/pipeline_runs.csv") == "pipeline_runs.csv"
    assert wanted("x-abc/raw/chn/boxscores/2026_27/123.html") is None  # raw pages stay behind
    assert wanted("x-abc/logs/refresh/2026-11-20T060000.log") is None
    assert wanted("x-abc/.github/workflows/refresh.yml") is None


def make_tar(path, members: dict[str, bytes]):
    with tarfile.open(path, "w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def test_extract_keeps_wanted_files_only(tmp_path):
    archive = tmp_path / "a.tar.gz"
    make_tar(archive, {
        "r-1/processed/chn/a.csv": b"x\n1\n",
        "r-1/raw/chn/b.html": b"<html>",
        "r-1/pipeline_runs.csv": b"h\n",
    })
    extract(archive, tmp_path / "out")
    files = sorted(p.relative_to(tmp_path / "out").as_posix()
                   for p in (tmp_path / "out").rglob("*") if p.is_file())
    assert files == ["pipeline_runs.csv", "processed/chn/a.csv"]


def test_extract_refuses_paths_outside_the_folder(tmp_path):
    archive = tmp_path / "a.tar.gz"
    make_tar(archive, {"r-1/processed/chn/../../../../evil.csv": b"x"})
    with pytest.raises(ValueError, match="unsafe path"):
        extract(archive, tmp_path / "out")
    assert not (tmp_path / "evil.csv").exists()


# ---------------------------------------------------------------------------- run history


@pytest.fixture
def ops(database_url):
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS ops CASCADE")
        yield conn
        conn.execute("DROP SCHEMA IF EXISTS ops CASCADE")


def test_history_round_trips_through_the_file(ops, tmp_path):
    path = tmp_path / "pipeline_runs.csv"
    assert import_runs(ops, path) == 0  # no file yet: an empty table
    ops.execute(
        "INSERT INTO ops.pipeline_runs (started_at, finished_at, status, trigger, played_before, "
        "played_after, message) VALUES "
        "('2026-11-20 11:01+00', '2026-11-20 11:09+00', 'success', 'scheduled', 10, 14, 'ok'), "
        "('2026-11-21 11:02+00', NULL, 'failed', 'scheduled', 14, NULL, NULL)"
    )
    assert export_runs(ops, path) == 2
    assert path.read_text().splitlines()[0] == ",".join(COLUMNS)

    assert import_runs(ops, path) == 2  # replaces, doesn't append
    rows = ops.execute(
        "SELECT run_id, status, played_after, finished_at IS NULL FROM ops.pipeline_runs "
        "ORDER BY run_id"
    ).fetchall()
    assert rows == [(1, "success", 14, False), (2, "failed", None, True)]


def test_export_keeps_the_newest_runs(ops, tmp_path):
    import_runs(ops, tmp_path / "none.csv")
    for day in range(1, 6):
        ops.execute("INSERT INTO ops.pipeline_runs (started_at, status, trigger) "
                    f"VALUES ('2026-11-0{day} 11:00+00', 'success', 'scheduled')")
    path = tmp_path / "runs.csv"
    assert export_runs(ops, path, keep=3) == 3
    assert [line[:10] for line in path.read_text().splitlines()[1:]] == [
        "2026-11-03", "2026-11-04", "2026-11-05",
    ]


def test_runs_today_uses_the_eastern_date(tmp_path):
    path = tmp_path / "runs.csv"
    path.write_text(
        ",".join(COLUMNS) + "\n"
        "2026-11-20 03:30:00+00,,success,scheduled,,,,,\n"  # Nov 19, 10:30 p.m. Eastern
        "2026-11-20 11:00:00.123+00,,failed,scheduled,,,,,\n"  # Nov 20, 6 a.m. Eastern
    )
    now = dt.datetime(2026, 11, 20, 15, 0, tzinfo=dt.UTC)
    assert runs_today(now, path) == [
        (dt.datetime(2026, 11, 20, 11, 0, 0, 123000, tzinfo=dt.UTC), "failed")
    ]
    assert runs_today(now, tmp_path / "missing.csv") == []


# ---------------------------------------------------------------------------- nightly job


def test_copy_logs_keeps_the_newest(tmp_path):
    src, dst = tmp_path / "logs", tmp_path / "data_logs"
    src.mkdir()
    for d in range(1, 5):
        (src / f"2026-11-0{d}T060000.log").write_text("log")
        (src / f"2026-11-0{d}T060000.validation.md").write_text("report")
    nightly.copy_logs(src, dst, keep=2)
    assert sorted(p.name for p in dst.iterdir()) == [
        "2026-11-03T060000.log", "2026-11-03T060000.validation.md",
        "2026-11-04T060000.log", "2026-11-04T060000.validation.md",
    ]


@pytest.fixture
def job(database_url, tmp_path, monkeypatch):
    """The nightly job with its files in tmp_path and the refresh itself replaced."""
    monkeypatch.setattr(nightly.settings, "database_url", database_url)
    monkeypatch.setattr(nightly, "RUNS_FILE", tmp_path / "pipeline_runs.csv")
    monkeypatch.setattr(nightly, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(nightly, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(nightly, "DATA_LOG_DIR", tmp_path / "data_logs")
    calls = []

    def fake_refresh(trigger, database_url):
        calls.append(trigger)
        with psycopg.connect(database_url, autocommit=True) as conn:
            conn.execute("INSERT INTO ops.pipeline_runs (status, trigger) VALUES (%s, %s)",
                         (job.status, trigger))
        (tmp_path / "logs").mkdir(exist_ok=True)
        (tmp_path / "logs" / "run.log").write_text("log")
        return Outcome(job.status)

    monkeypatch.setattr(nightly, "refresh", fake_refresh)
    monkeypatch.setattr(nightly, "should_run", lambda now, runs: (not runs, "already ran"))
    job.status, job.calls, job.tmp = "success", calls, tmp_path
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS ops CASCADE")
    yield job
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS ops CASCADE")


def run_job(monkeypatch, *args):
    monkeypatch.setattr("sys.argv", ["nightly", *args])
    with pytest.raises(SystemExit) as e:
        nightly.main()
    return e.value.code


def test_nightly_records_the_run_and_skips_when_done(job, monkeypatch):
    assert run_job(monkeypatch) == 0
    assert job.calls == ["scheduled"]
    lines = (job.tmp / "pipeline_runs.csv").read_text().splitlines()
    assert len(lines) == 2 and ",success,scheduled," in lines[1]
    assert (job.tmp / "data_logs" / "run.log").exists()

    assert run_job(monkeypatch) == 0  # today's run is in the file now: not due
    assert job.calls == ["scheduled"]
    assert run_job(monkeypatch, "--force") == 0  # unless forced
    assert job.calls == ["scheduled", "manual"]
    assert len((job.tmp / "pipeline_runs.csv").read_text().splitlines()) == 3  # history kept


def test_nightly_exits_1_when_the_refresh_fails(job, monkeypatch):
    job.status = "blocked"
    assert run_job(monkeypatch) == 1
    assert ",blocked,scheduled," in (job.tmp / "pipeline_runs.csv").read_text()
