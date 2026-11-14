"""Win probability endpoint, against the made-up fixture (tests/api/fixture.sql).

Before g2 (2026-10-11, Rival College at home vs Home U), each team has played only g1:
  Home U won 4-2 with 1 empty-net goal (35-25 shots); every period of g1 started within a
  goal, so all its shots count as close-game shots.
  -> Home U: close share 35/60, goal diff (4 - 1 - 2) / 1 = +1
  -> Rival:  close share 25/60, goal diff (2 - 0 - 4) / 1 = -2
"""

import math

import pytest

from src.models.win_model import close_shots, home_win_probability, load_card

CARD = load_card()


def expected(home_share, home_gd, away_share, away_gd, home_ice=True):
    c, s = CARD["coefficients"], CARD["feature_scales"]
    z = (
        c["diff_close_shot_share_season"] * (home_share - away_share) / s["diff_close_shot_share_season"]
        + c["diff_goal_diff_pg_no_en_season"] * (home_gd - away_gd) / s["diff_goal_diff_pg_no_en_season"]
        + c["home_ice"] * home_ice
    )
    return 1 / (1 + math.exp(-z))


def test_prediction_uses_games_before_the_date(client):
    r = client.get("/v1/games/g2/prediction")
    assert r.status_code == 200
    body = r.json()
    assert body["model"] == "win_model_v1"
    assert body["as_of"] == "2026-10-11"
    assert body["home"]["team"]["name"] == "Rival College"
    assert body["home"]["games_played"] == 1 and body["away"]["games_played"] == 1
    assert body["home"]["close_shot_share"] == pytest.approx(25 / 60)
    assert body["away"]["close_shot_share"] == pytest.approx(35 / 60)
    assert body["home"]["goal_diff_per_game"] == pytest.approx(-2)
    assert body["away"]["goal_diff_per_game"] == pytest.approx(1)
    p = expected(25 / 60, -2, 35 / 60, 1)
    assert body["home_win_probability"] == pytest.approx(p)
    assert body["away_win_probability"] == pytest.approx(1 - p)
    assert body["home_ice"] is True
    f = body["factors"]
    assert f["home_ice"] > 0  # home edge helps the home team
    assert f["close_shot_share"] < 0 and f["goal_diff_per_game"] < 0  # Rival trails on both
    assert body["reliable"] is False and "only 1 game" in body["note"]


def test_first_game_is_the_home_edge_only(client):
    body = client.get("/v1/games/g1/prediction").json()
    assert body["home"]["games_played"] == 0 and body["home"]["close_shot_share"] is None
    assert body["home_win_probability"] == pytest.approx(expected(0, 0, 0, 0))


@pytest.mark.parametrize(
    "game_id, status",
    [("g3", 422), ("g4", 422), ("nope", 404)],  # vs non-D-I, TBD opponent, unknown
)
def test_unpredictable_games(client, game_id, status):
    assert client.get(f"/v1/games/{game_id}/prediction").status_code == status


def test_neutral_site_evenly_matched_is_a_coin_flip():
    even = {"close_shot_share": 0.5, "goal_diff_per_game": 0.0}
    assert home_win_probability(CARD, even, even, home_ice=False) == pytest.approx(0.5)
    assert home_win_probability(CARD, even, even, home_ice=True) > 0.5


def test_close_shots_rule():
    row = dict(shots_p1=10, shots_p2=10, shots_p3=10, opp_p1=8, opp_p2=8, opp_p3=8)
    assert close_shots({**row, "my1": 1, "op1": 0, "my2": 1, "op2": 1}) == (30, 24)  # all close
    assert close_shots({**row, "my1": 2, "op1": 0, "my2": 2, "op2": 1}) == (20, 16)  # p2 not close
    assert close_shots({**row, "my1": 0, "op1": 0, "my2": 3, "op2": 0}) == (20, 16)  # p3 not close
    assert close_shots({**row, "shots_p3": None, "my1": 0, "op1": 0, "my2": 0, "op2": 0}) is None


def matchup(client, **params):
    return client.get("/v1/matchup", params={"season": "2026-27", "as_of": "2026-10-11", **params})


def test_matchup_any_two_teams(client):
    # Home U hosting Rival College, using the games before Oct 11 (just g1 for each)
    body = matchup(client, home_team_id=1, away_team_id=2).json()
    assert body["home"]["team"]["name"] == "Home U" and body["neutral_site"] is False
    assert body["home"]["close_shot_share"] == pytest.approx(35 / 60)
    assert body["home_win_probability"] == pytest.approx(expected(35 / 60, 1, 25 / 60, -2))


def test_matchup_neutral_site_and_swap_are_consistent(client):
    a = matchup(client, home_team_id=1, away_team_id=2, neutral=True).json()
    b = matchup(client, home_team_id=2, away_team_id=1, neutral=True).json()
    assert a["home_win_probability"] == pytest.approx(expected(35 / 60, 1, 25 / 60, -2, home_ice=False))
    assert a["home_win_probability"] == pytest.approx(b["away_win_probability"])  # order doesn't matter
    assert a["factors"]["home_ice"] == 0


@pytest.mark.parametrize(
    "params, status",
    [({"home_team_id": 1, "away_team_id": 1}, 422),   # same team
     ({"home_team_id": 1, "away_team_id": 3}, 422),   # non-D-I
     ({"home_team_id": 1, "away_team_id": 99}, 404)],  # unknown
)
def test_matchup_errors(client, params, status):
    assert matchup(client, **params).status_code == status
