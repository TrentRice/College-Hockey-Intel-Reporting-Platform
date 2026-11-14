"""Prediction log, against the made-up test database (tests/api/fixture.sql).

Fixture: 2026-27 games g1 (Oct 10) and g2 (Oct 11) are played; g3 is vs a non-D-I team; g4
has a TBD team; g5 is 2025-26, the model's training season. These tests add one upcoming
D-I game (g9) of their own and remove it afterwards.
"""

import datetime as dt

import psycopg
import pytest

from src.pipeline.predict import log_predictions


def D(s):
    return dt.date.fromisoformat(s)


@pytest.fixture
def db(database_url):
    with psycopg.connect(database_url) as conn:
        conn.execute("DROP SCHEMA IF EXISTS predictions CASCADE")
        conn.execute(
            "INSERT INTO hockey.games (game_id, season, game_date, home_team_id, away_team_id, "
            "is_played, is_neutral, is_conference, ot_periods) "
            "VALUES ('g9', '2026-27', '2026-10-20', 2, 1, FALSE, FALSE, TRUE, 0)"
        )
    yield database_url
    with psycopg.connect(database_url) as conn:
        conn.execute("DELETE FROM hockey.games WHERE game_id = 'g9'")
        conn.execute("DROP SCHEMA IF EXISTS predictions CASCADE")


def rows(url):
    with psycopg.connect(url) as conn:
        return {r[0]: r[1:] for r in conn.execute(
            "SELECT game_id, backfilled, logged_on, home_win_probability "
            "FROM predictions.game_predictions ORDER BY game_id")}  # fmt: skip


def test_backfill_covers_played_games_after_the_training_season_only(db):
    counts = log_predictions(db, today=D("2026-10-12"), days_ahead=7)
    logged = rows(db)
    assert set(logged) == {"g1", "g2"}  # not g5 (training season), g3 (non-D-I), g4 (TBD)
    assert all(r[0] for r in logged.values())  # both marked backfilled
    assert counts["backfilled"] == 2 and counts["logged"] == 0  # g9 is 8 days out


def test_upcoming_game_updates_until_game_day_then_locks(db):
    log_predictions(db, today=D("2026-10-15"), backfill=False)
    first = rows(db)["g9"]
    assert first[0] is False and first[1] == D("2026-10-15")

    # The day before: still refreshes
    c = log_predictions(db, today=D("2026-10-19"), backfill=False)
    assert c["updated"] == 1 and rows(db)["g9"][1] == D("2026-10-19")

    # Game day: the final pre-game prediction is written...
    c = log_predictions(db, today=D("2026-10-20"), backfill=False)
    assert c["updated"] == 1 and rows(db)["g9"][1] == D("2026-10-20")

    # ...and after that the row never changes, even if someone tampers with it
    with psycopg.connect(db) as conn:
        conn.execute("UPDATE predictions.game_predictions SET home_win_probability = 0.123 WHERE game_id = 'g9'")
    c = log_predictions(db, today=D("2026-10-20"), backfill=False)
    assert c["locked"] == 1 and rows(db)["g9"][2] == pytest.approx(0.123)


def test_already_logged_games_are_not_backfilled_again(db):
    log_predictions(db, today=D("2026-10-12"))
    again = log_predictions(db, today=D("2026-10-13"))
    assert again["backfilled"] == 0


def test_backfilled_prediction_matches_the_api(db, client):
    log_predictions(db, today=D("2026-10-12"))
    api = client.get("/v1/games/g2/prediction").json()
    assert rows(db)["g2"][2] == pytest.approx(api["home_win_probability"])
