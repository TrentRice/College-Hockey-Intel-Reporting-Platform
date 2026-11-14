"""
Win model v1: the home team's chance of winning a game, from each team's season so far.

  card = load_card()
  pred = predict_game(conn, card, game)   # a scheduled game: a row from `games`
  pred = predict_matchup(conn, card, season, home_id, away_id, before, neutral=False)

This applies the model frozen in notebooks/09_model.ipynb through its card
(models/win_model_v1.json): coefficients and feature scales, so every number can be
checked by hand and the API doesn't need scikit-learn. Notebook 09 asserts that this
module's features and probabilities match the notebook's exactly on every test game.

The model (see docs/eda.md):
  score = b_shots * (home - away close-game shot share) / scale
        + b_goals * (home - away goal differential per game, no empty-net goals) / scale
        + b_home  * home_ice          (1 = home game, 0 = neutral site)
  P(home win) = 1 / (1 + e^-score)

Rules, the same as training:
  * Season to date, strictly before the game's date (nothing from that day or later).
  * D-I vs D-I games only, as inputs and as games to predict.
  * The probability is for a decided game: ties (about 7% of games) were left out of
    training, so read it as "chance of winning if the game has a winner".
  * A team with fewer than 3 games is below the training warm-up: the prediction is still
    given, but flagged as unreliable. A team with no games counts as average (difference 0).
"""

from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path
from typing import Any

from psycopg.rows import dict_row

CARD_PATH = Path(__file__).resolve().parents[2] / "models" / "win_model_v1.json"
MIN_GAMES = 3  # the training warm-up

# card feature name -> the per-team input it's the home-minus-away difference of
INPUTS = {
    "diff_close_shot_share_season": "close_shot_share",
    "diff_goal_diff_pg_no_en_season": "goal_diff_per_game",
}


class ModelUnavailable(Exception):
    pass


def load_card(path: Path = CARD_PATH) -> dict[str, Any]:
    if not path.exists():
        raise ModelUnavailable(f"No model card at {path}. Run notebooks/09_model.ipynb.")
    card = json.loads(path.read_text())
    missing = set(INPUTS) - set(card["features"])
    if missing or set(card["features"]) - set(INPUTS):
        raise ModelUnavailable(f"Card features {card['features']} don't match this code.")
    return card


# One row per D-I vs D-I game the team played before the date, with what's needed for
# close-game shots: period shots for both sides and each side's goals after periods 1 and 2.
TEAM_GAMES_SQL = """
SELECT t.goals_for, t.goals_against, t.en_goals,
       s.shots_p1, s.shots_p2, s.shots_p3,
       o.shots_p1 AS opp_p1, o.shots_p2 AS opp_p2, o.shots_p3 AS opp_p3,
       COALESCE(g.my1, 0) AS my1, COALESCE(g.my2, 0) AS my2,
       COALESCE(g.op1, 0) AS op1, COALESCE(g.op2, 0) AS op2
FROM features.team_games t
JOIN hockey.team_game_stats s ON s.game_id = t.game_id AND s.team_id = t.team_id
JOIN hockey.team_game_stats o ON o.game_id = t.game_id AND o.team_id = t.opponent_team_id
JOIN hockey.teams me  ON me.team_id  = t.team_id
JOIN hockey.teams opp ON opp.team_id = t.opponent_team_id
LEFT JOIN LATERAL (
    SELECT COUNT(*) FILTER (WHERE go.team_id = t.team_id AND go.period <= 1) AS my1,
           COUNT(*) FILTER (WHERE go.team_id = t.team_id AND go.period <= 2) AS my2,
           COUNT(*) FILTER (WHERE go.team_id <> t.team_id AND go.period <= 1) AS op1,
           COUNT(*) FILTER (WHERE go.team_id <> t.team_id AND go.period <= 2) AS op2
    FROM hockey.goals go WHERE go.game_id = t.game_id
) g ON TRUE
WHERE t.team_id = %(team)s AND t.season = %(season)s AND t.game_date < %(before)s
  AND me.is_d1 AND opp.is_d1
"""


def close_shots(r: dict[str, Any]) -> tuple[int, int] | None:
    """(shots for, shots against) in periods that started tied or within one goal.

    Period 1 always counts; period 2 if the score after period 1 was within one; period 3
    if the score after period 2 was. Overtime shots never count. None if period shots are
    missing.
    """
    cols = ("shots_p1", "shots_p2", "shots_p3", "opp_p1", "opp_p2", "opp_p3")
    if any(r[c] is None for c in cols):
        return None
    p2 = abs(r["my1"] - r["op1"]) <= 1
    p3 = abs(r["my2"] - r["op2"]) <= 1
    sf = r["shots_p1"] + r["shots_p2"] * p2 + r["shots_p3"] * p3
    sa = r["opp_p1"] + r["opp_p2"] * p2 + r["opp_p3"] * p3
    return sf, sa


def team_inputs(conn, team_id: int, season: str, before: dt.date) -> dict[str, Any]:
    """A team's model inputs from its games this season before `before`."""
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            TEAM_GAMES_SQL, {"team": team_id, "season": season, "before": before}
        ).fetchall()
    n = len(rows)
    close = [c for c in (close_shots(r) for r in rows) if c is not None]
    sf, sa = sum(c[0] for c in close), sum(c[1] for c in close)
    gd = sum(r["goals_for"] - r["en_goals"] - r["goals_against"] for r in rows)
    return {
        "games_played": n,
        "close_shot_share": sf / (sf + sa) if (sf + sa) else None,
        "goal_diff_per_game": gd / n if n else None,
    }


def home_win_probability(
    card: dict[str, Any], home: dict[str, Any], away: dict[str, Any], home_ice: bool
) -> float:
    """The card's logistic model. A missing input on either side counts as no difference."""
    score = card["coefficients"]["home_ice"] * (1 if home_ice else 0)
    for feature, key in INPUTS.items():
        h, a = home.get(key), away.get(key)
        diff = 0.0 if h is None or a is None else h - a
        score += card["coefficients"][feature] * diff / card["feature_scales"][feature]
    return 1 / (1 + math.exp(-score))


def predict_matchup(
    conn, card: dict[str, Any], season: str, home_team_id: int, away_team_id: int,
    before: dt.date, neutral: bool = False,
) -> dict[str, Any]:
    """Prediction for any two teams, scheduled or not: each team's season before `before`,
    with `home_team_id` as the home side (no home edge when `neutral`)."""
    home = team_inputs(conn, home_team_id, season, before)
    away = team_inputs(conn, away_team_id, season, before)
    home_ice = not neutral
    p = home_win_probability(card, home, away, home_ice)
    # How far each factor moves the home team's chance: the probability minus what it would
    # be if that one factor were even (no difference, or a neutral site for home ice).
    factors = {"home_ice": p - home_win_probability(card, home, away, False)}
    for key in INPUTS.values():
        factors[key] = p - home_win_probability(card, home, {**away, key: home.get(key)}, home_ice)
    fewest = min(home["games_played"], away["games_played"])
    note = None
    if fewest < MIN_GAMES:
        note = (
            f"A team has played only {fewest} game(s) before this date; the model was trained "
            f"on games where both teams had played at least {MIN_GAMES}. Treat it as a rough guide."
        )
    return {
        "model": card["name"],
        "as_of": before,
        "home_win_probability": p,
        "away_win_probability": 1 - p,
        "home_ice": home_ice,
        "factors": factors,
        "home_inputs": home,
        "away_inputs": away,
        "reliable": fewest >= MIN_GAMES,
        "note": note,
    }


def predict_game(conn, card: dict[str, Any], game: dict[str, Any]) -> dict[str, Any]:
    """Prediction for one scheduled game (a `games` row with season, game_date, home/away team
    ids, is_neutral). Inputs use only games before the game's date."""
    return predict_matchup(
        conn, card, game["season"], game["home_team_id"], game["away_team_id"],
        game["game_date"], neutral=game["is_neutral"],
    )
