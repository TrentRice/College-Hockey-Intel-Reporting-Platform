"""Prediction log endpoints. The log is written by the real pipeline step against the test
database (tests/api/fixture.sql) plus one upcoming D-I game (g9) added here.

Logged: g1 (Oct 10, Home U 4-2 Rival, backfilled), g2 (Oct 11, 3-3 tie, backfilled) and g9
(Oct 20, upcoming). g1 is both teams' first game, so its prediction is the home edge alone.
"""

import datetime as dt
import math

import psycopg
import pytest

from src.models.win_model import load_card
from src.pipeline.predict import log_predictions

HOME_EDGE = 1 / (1 + math.exp(-load_card()["coefficients"]["home_ice"]))


@pytest.fixture
def logged(database_url):
    with psycopg.connect(database_url) as conn:
        conn.execute("DROP SCHEMA IF EXISTS predictions CASCADE")
        conn.execute(
            "INSERT INTO hockey.games (game_id, season, game_date, home_team_id, away_team_id, "
            "is_played, is_neutral, is_conference, ot_periods) "
            "VALUES ('g9', '2026-27', '2026-10-20', 2, 1, FALSE, FALSE, TRUE, 0)"
        )
    log_predictions(database_url, today=dt.date(2026, 10, 15))
    yield
    with psycopg.connect(database_url) as conn:
        conn.execute("DELETE FROM hockey.games WHERE game_id = 'g9'")
        conn.execute("DROP SCHEMA IF EXISTS predictions CASCADE")


def log(client, **params):
    return client.get("/v1/predictions", params={"season": "2026-27", **params}).json()


def test_log_with_results(client, logged):
    body = log(client)
    assert body["total"] == 3
    by_id = {r["game_id"]: r for r in body["items"]}
    assert [r["game_id"] for r in body["items"]] == ["g9", "g2", "g1"]  # newest first
    g1 = by_id["g1"]
    assert g1["home_win_probability"] == pytest.approx(HOME_EDGE)  # first game: home edge only
    assert g1["favorite"]["name"] == "Home U" and g1["result"] == "home" and g1["correct"] is True
    assert g1["backfilled"] is True and g1["final"] is True
    assert by_id["g2"]["result"] == "tie" and by_id["g2"]["correct"] is None
    g9 = by_id["g9"]
    assert g9["is_played"] is False and g9["result"] is None and g9["final"] is False


def test_log_filters(client, logged):
    assert [r["game_id"] for r in log(client, played=False)["items"]] == ["g9"]
    assert [r["game_id"] for r in log(client, backfilled=False)["items"]] == ["g9"]
    assert log(client, team_id=1)["total"] == 3
    assert log(client, limit=1, offset=1)["items"][0]["game_id"] == "g2"


def test_summary(client, logged):
    s = client.get("/v1/predictions/summary", params={"season": "2026-27"}).json()
    assert (s["games"], s["correct"], s["ties_excluded"], s["upcoming_logged"]) == (1, 1, 1, 1)
    assert (s["logged_before"], s["backfilled"]) == (0, 1)
    assert s["accuracy"] == 1.0
    assert s["log_loss"] == pytest.approx(-math.log(HOME_EDGE))
    assert s["baseline_log_loss"] == pytest.approx(-math.log(HOME_EDGE))  # even teams: same
    assert s["calibration"][0]["games"] == 1


def test_no_log_yet(client, database_url):
    with psycopg.connect(database_url) as conn:
        conn.execute("DROP SCHEMA IF EXISTS predictions CASCADE")
    assert log(client)["total"] == 0
    s = client.get("/v1/predictions/summary", params={"season": "2026-27"}).json()
    assert s["games"] == 0 and s["accuracy"] is None and s["calibration"] == []


def test_reliable_only(client, logged):
    # g1 and g2 were both teams' first and second games: below the 3-game warm-up
    assert log(client, reliable_only=True, played=True)["total"] == 0
    s = client.get("/v1/predictions/summary", params={"season": "2026-27", "reliable_only": True}).json()
    assert s["games"] == 0
