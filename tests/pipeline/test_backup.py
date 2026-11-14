"""Prediction log backups, against the test database (tests/api/fixture.sql)."""

import datetime as dt

import psycopg
import pytest

from src.pipeline.backup import backup_predictions, backups, restore_predictions
from src.pipeline.predict import log_predictions


@pytest.fixture
def logged(database_url):
    with psycopg.connect(database_url) as conn:
        conn.execute("DROP SCHEMA IF EXISTS predictions CASCADE")
    log_predictions(database_url, today=dt.date(2026, 10, 15))  # backfills g1 and g2
    yield database_url
    with psycopg.connect(database_url) as conn:
        conn.execute("DROP SCHEMA IF EXISTS predictions CASCADE")


def table(url):
    with psycopg.connect(url) as conn:
        return conn.execute("SELECT * FROM predictions.game_predictions ORDER BY game_id").fetchall()


def test_backup_and_restore_after_a_wipe(logged, tmp_path):
    before = table(logged)
    path, rows = backup_predictions(logged, tmp_path, today=dt.date(2026, 10, 15))
    assert path.name == "predictions_2026-10-15.csv.gz" and rows == len(before) == 2
    with psycopg.connect(logged) as conn:  # what `make db-reset` does to the log
        conn.execute("DROP SCHEMA predictions CASCADE")
    assert restore_predictions(logged, path) == (2, 2)
    assert table(logged) == before  # every column, timestamps included


def test_restore_never_overwrites_and_is_repeatable(logged, tmp_path):
    path, _ = backup_predictions(logged, tmp_path)
    with psycopg.connect(logged) as conn:
        conn.execute("UPDATE predictions.game_predictions SET home_win_probability = 0.42")
    assert restore_predictions(logged, path) == (2, 0)
    assert {r[7] for r in table(logged)} == {0.42}  # the log's own rows win


def test_keeps_the_newest_backups(logged, tmp_path):
    for d in range(1, 6):
        backup_predictions(logged, tmp_path, keep=3, today=dt.date(2026, 10, d))
    assert [p.name for p in backups(tmp_path)] == [
        "predictions_2026-10-03.csv.gz", "predictions_2026-10-04.csv.gz", "predictions_2026-10-05.csv.gz",
    ]


def test_nothing_to_back_up_before_the_first_log(database_url, tmp_path):
    with psycopg.connect(database_url) as conn:
        conn.execute("DROP SCHEMA IF EXISTS predictions CASCADE")
    assert backup_predictions(database_url, tmp_path) == (None, 0)
    assert backups(tmp_path) == []
