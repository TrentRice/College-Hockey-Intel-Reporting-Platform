"""The women's model inputs (src/models/win_model.py), on a season small enough to check by
hand. The real check is notebooks/women/09_model.ipynb (live code = frozen model on every
2026-27 test game)."""

import datetime as dt
import math

import pytest

from config import leagues
from src.models.win_model import MODELS, card_path, home_win_probability, load_card, women_inputs


def g(team, opp, day, gf, ga, sf=30, sa=30, en=0):
    return {"team_id": team, "opponent_team_id": opp, "game_date": dt.date(2026, 10, day),
            "result": "W" if gf > ga else "L" if gf < ga else "T", "goals_for": gf,
            "goals_against": ga, "en_goals": en, "shots_for": sf, "shots_against": sa}


# Team 1 beats team 2 4-1 on Oct 3 (team 2's first game), then loses to team 3 2-3 on Oct 10.
# Team 3 had beaten team 2 5-0 on Oct 4.
BY_TEAM = {
    1: [g(1, 2, 3, 4, 1, sf=40, sa=20, en=1), g(1, 3, 10, 2, 3, sf=25, sa=35)],
    2: [g(2, 1, 3, 1, 4, sf=20, sa=40), g(2, 3, 4, 0, 5)],
    3: [g(3, 2, 4, 5, 0), g(3, 1, 10, 3, 2, sf=35, sa=25)],
}


def test_women_inputs_by_hand():
    t1 = women_inputs(BY_TEAM, 1)
    assert t1["games_played"] == 2
    assert t1["shots_for_per_game"] == pytest.approx((40 + 25) / 2)
    # goal diff per game, empty-netters included: (4 - 1 + 2 - 3) / 2 = +1
    # schedule: team 2 had no games before Oct 3 -> 0; team 3 before Oct 10 was +5 per game
    assert t1["adj_goal_diff_per_game"] == pytest.approx(1 + (0 + 5) / 2)
    # PDO: shooting % without the empty-netter (6 - 1) / 65, plus save % 1 - 4 / 55
    assert t1["pdo"] == pytest.approx(5 / 65 + 1 - 4 / 55)
    assert (t1["wins"], t1["losses"], t1["ties"]) == (1, 1, 0)


def test_a_team_with_no_games_has_no_inputs():
    none = women_inputs(BY_TEAM, 99)
    assert none["games_played"] == 0
    assert none["shots_for_per_game"] is None and none["pdo"] is None


def test_women_card_and_probability():
    card = load_card(card_path(leagues.WOMEN))
    assert card["name"] == "win_model_women_v1"
    even = {k: 1.0 for k in MODELS["win_model_women_v1"].inputs.values()}
    assert home_win_probability(card, even, even, home_ice=False) == pytest.approx(0.5)
    home_edge = 1 / (1 + math.exp(-card["coefficients"]["home_ice"]))
    assert home_win_probability(card, even, even, home_ice=True) == pytest.approx(home_edge)
    # PDO's weight is negative: a higher PDO, all else equal, lowers the chance
    assert home_win_probability(card, {**even, "pdo": 1.05}, even, home_ice=False) < 0.5


def test_each_league_has_its_own_reliability_threshold():
    assert MODELS["win_model_v1"].reliable_games == 3
    assert MODELS["win_model_women_v1"].reliable_games == 6
