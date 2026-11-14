"""Model rankings against the fixture (tests/api/fixture.sql).

Before Oct 12 each D-I team has played g1 and g2:
  Home U: 1-0-1, goal diff (4 + 3 - 1 empty-netter - 2 - 3) / 2 = +0.5,
          close-game shots 35 + 29 = 64 for, 25 + 27 = 52 against (every period was close)
  Rival:  0-1-1, goal diff (2 + 3 - 4 - 3) / 2 = -1, close-game shots 52 for, 64 against
Small State isn't D-I and is never ranked.
"""

import math

import pytest

from src.models.win_model import load_card

CARD = load_card()


def rate(share, gd):
    c, s = CARD["coefficients"], CARD["feature_scales"]
    return (c["diff_close_shot_share_season"] * share / s["diff_close_shot_share_season"]
            + c["diff_goal_diff_pg_no_en_season"] * gd / s["diff_goal_diff_pg_no_en_season"])


def ranks(client, **params):
    return client.get("/v1/rankings", params={"season": "2026-27", "as_of": "2026-10-12", **params})


def test_rankings_order_and_values(client):
    body = ranks(client, min_games=1).json()
    names = [t["team"]["name"] for t in body["teams"]]
    assert names == ["Home U", "Rival College"]
    home, rival = body["teams"]
    assert home["record"] == "1-0-1" and rival["record"] == "0-1-1"
    assert home["close_shot_share"] == pytest.approx(64 / 116)
    assert home["goal_diff_per_game"] == pytest.approx(0.5)
    r1, r2 = rate(64 / 116, 0.5), rate(52 / 116, -1)
    assert home["rating"] == pytest.approx(r1)
    avg = (r1 + r2) / 2
    assert home["beats_average"] == pytest.approx(1 / (1 + math.exp(-(r1 - avg))))
    # Not ranked a week earlier (no games yet): no movement to show
    assert home["previous_rank"] is None and home["change"] is None


def test_ratings_agree_with_neutral_site_predictions(client):
    body = ranks(client, min_games=1).json()
    home, rival = body["teams"]
    m = client.get("/v1/matchup", params={"season": "2026-27", "as_of": "2026-10-12",
                                          "home_team_id": 1, "away_team_id": 2, "neutral": True}).json()
    assert m["home_win_probability"] == pytest.approx(1 / (1 + math.exp(-(home["rating"] - rival["rating"]))))


def test_min_games_and_limit(client):
    assert ranks(client).json()["teams"] == []  # default 5 games: nobody yet
    assert ranks(client).json()["unranked"] == 2
    assert len(ranks(client, min_games=1, limit=1).json()["teams"]) == 1


def test_movement(client):
    # As of Oct 19, compared with Oct 12: same two games each, so nobody moves
    body = client.get("/v1/rankings", params={"season": "2026-27", "as_of": "2026-10-19", "min_games": 1}).json()
    assert [t["change"] for t in body["teams"]] == [0, 0]
