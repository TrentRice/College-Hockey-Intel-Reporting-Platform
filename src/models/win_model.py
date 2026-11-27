"""
Win models: the home team's chance of winning a game, from each team's season so far.
Two frozen models, one per league (config/leagues.py): win_model_v1 (men's, docs/model.md)
and win_model_women_v1 (women's, docs/model_women.md). MODELS below says which inputs each
one uses; the card's name picks the right one.

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

The women's model uses shots for per game, schedule-adjusted goal differential and PDO
(docs/model_women.md); notebooks/women/09_model.ipynb checks this module against it.

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
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from psycopg.rows import dict_row

MODELS_DIR = Path(__file__).resolve().parents[2] / "models"
CARD_PATH = MODELS_DIR / "win_model_v1.json"


@dataclass(frozen=True)
class Spec:
    """What a frozen model needs from this code."""
    inputs: dict[str, str]  # card feature -> the per-team input it's the home-minus-away diff of
    reliable_games: int  # below this many games on either team, predictions are a rough guide
    rank_min_games: int  # games needed to be ranked
    complete_box_only: bool  # inputs only from games whose box score matches the score
    reliability_note: str


MODELS = {
    "win_model_v1": Spec(
        inputs={
            "diff_close_shot_share_season": "close_shot_share",
            "diff_goal_diff_pg_no_en_season": "goal_diff_per_game",
        },
        reliable_games=3,  # the training warm-up
        rank_min_games=5,  # shot share needs about 4-8 games to mean much (EDA step 4)
        complete_box_only=False,
        reliability_note="the model was trained on games where both teams had played at least {n}",
    ),
    "win_model_women_v1": Spec(
        inputs={
            "diff_shots_for_pg_season": "shots_for_per_game",
            "diff_adj_goal_diff_pg": "adj_goal_diff_per_game",
            "diff_pdo_season": "pdo",
        },
        # trained with a 3-game warm-up, but overconfident until both teams have 6 games
        # (2026-27 test, notebooks/women/09_model.ipynb)
        reliable_games=6,
        rank_min_games=6,
        complete_box_only=True,
        reliability_note="the model is overconfident until both teams have played {n}",
    ),
}
# The men's model, as before (kept for callers that predate the women's model)
INPUTS = MODELS["win_model_v1"].inputs
MIN_GAMES = MODELS["win_model_v1"].reliable_games


class ModelUnavailable(Exception):
    pass


def card_path(league) -> Path:
    """The league's frozen card (config/leagues.py)."""
    return MODELS_DIR / f"{league.model}.json"


def spec(card: dict[str, Any]) -> Spec:
    return MODELS[card["name"]]


def load_card(path: Path = CARD_PATH) -> dict[str, Any]:
    if not path.exists():
        raise ModelUnavailable(f"No model card at {path}. Run that league's notebook 09.")
    card = json.loads(path.read_text())
    if card.get("name") not in MODELS:
        raise ModelUnavailable(f"Unknown model {card.get('name')!r}: no inputs defined for it.")
    expected = set(MODELS[card["name"]].inputs)
    if set(card["features"]) != expected:
        raise ModelUnavailable(f"Card features {card['features']} don't match this code.")
    return card


# One row per D-I vs D-I game the team played before the date, with what's needed for
# close-game shots: period shots for both sides and each side's goals after periods 1 and 2.
TEAM_GAMES_SQL = """
SELECT t.result, t.goals_for, t.goals_against, t.en_goals,
       s.shots_p1, s.shots_p2, s.shots_p3,
       o.shots_p1 AS opp_p1, o.shots_p2 AS opp_p2, o.shots_p3 AS opp_p3,
       COALESCE(g.my1, 0) AS my1, COALESCE(g.my2, 0) AS my2,
       COALESCE(g.op1, 0) AS op1, COALESCE(g.op2, 0) AS op2
FROM features.team_games t
JOIN hockey.team_game_stats s ON s.game_id = t.game_id AND s.team_id = t.team_id
JOIN hockey.team_game_stats o ON o.game_id = t.game_id AND o.team_id = t.opponent_team_id
JOIN hockey.team_seasons me  ON me.team_id  = t.team_id          AND me.season  = t.season
JOIN hockey.team_seasons opp ON opp.team_id = t.opponent_team_id AND opp.season = t.season
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
        "wins": sum(r["result"] == "W" for r in rows),
        "losses": sum(r["result"] == "L" for r in rows),
        "ties": sum(r["result"] == "T" for r in rows),
    }


# ----------------------------------------------------------------------------
# Women's inputs (win_model_women_v1): built from the whole season's games, because the
# schedule-adjusted goal differential needs each opponent's record as of each game date
# ----------------------------------------------------------------------------

# Every D-I vs D-I team-game of the season before the date, complete box scores only (the
# box score and its goal list both match the official score), as in notebooks/women/01.
SEASON_GAMES_SQL = """
SELECT t.team_id, t.opponent_team_id, t.game_date, t.result,
       t.goals_for, t.goals_against, t.en_goals, t.shots_for, t.shots_against
FROM features.team_games t
JOIN hockey.games g USING (game_id)
JOIN hockey.team_seasons me  ON me.team_id  = t.team_id          AND me.season  = t.season
JOIN hockey.team_seasons opp ON opp.team_id = t.opponent_team_id AND opp.season = t.season
WHERE t.season = %(season)s AND t.game_date < %(before)s
  AND me.is_d1 AND opp.is_d1
  AND g.home_goals + g.away_goals = t.goals_for + t.goals_against
  AND (SELECT count(*) FROM hockey.goals go WHERE go.game_id = t.game_id)
      = t.goals_for + t.goals_against
"""


def season_games(conn, season: str, before: dt.date) -> dict[int, list[dict[str, Any]]]:
    """Each team's qualifying games before `before`, oldest first."""
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(SEASON_GAMES_SQL, {"season": season, "before": before}).fetchall()
    by_team: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for r in sorted(rows, key=lambda r: r["game_date"]):
        by_team[r["team_id"]].append(r)
    return by_team


def _goal_diff_per_game(games: list[dict[str, Any]]) -> float | None:
    return sum(g["goals_for"] - g["goals_against"] for g in games) / len(games) if games else None


def women_inputs(by_team: dict[int, list[dict[str, Any]]], team_id: int) -> dict[str, Any]:
    """win_model_women_v1's inputs for one team, from season_games().

    - shots for per game
    - schedule-adjusted goal differential: goal differential per game (empty-net goals
      included) + the average, over the team's games, of each opponent's goal differential
      per game from its games on dates before that game (0 for an opponent with none yet)
    - PDO: shooting % without empty-net goals + save %
    """
    games = by_team.get(team_id, [])
    n = len(games)
    sf = sum(g["shots_for"] for g in games)
    sa = sum(g["shots_against"] for g in games)
    gf = sum(g["goals_for"] for g in games)
    ga = sum(g["goals_against"] for g in games)
    en = sum(g["en_goals"] for g in games)
    sos_terms = []
    for g in games:
        earlier = [o for o in by_team.get(g["opponent_team_id"], []) if o["game_date"] < g["game_date"]]
        sos_terms.append(_goal_diff_per_game(earlier) or 0.0)
    gd = (gf - ga) / n if n else None
    return {
        "games_played": n,
        "shots_for_per_game": sf / n if n else None,
        "adj_goal_diff_per_game": gd + sum(sos_terms) / n if n else None,
        "pdo": (gf - en) / sf + 1 - ga / sa if sf and sa else None,
        "goal_diff_per_game": gd,  # for display: the raw figure, not a model input here
        "wins": sum(g["result"] == "W" for g in games),
        "losses": sum(g["result"] == "L" for g in games),
        "ties": sum(g["result"] == "T" for g in games),
    }


def inputs_for(
    conn, card: dict[str, Any], team_ids: list[int], season: str, before: dt.date
) -> dict[int, dict[str, Any]]:
    """Model inputs for several teams at once, for the card's model."""
    if card["name"] == "win_model_women_v1":
        by_team = season_games(conn, season, before)
        return {t: women_inputs(by_team, t) for t in team_ids}
    return {t: team_inputs(conn, t, season, before) for t in team_ids}


def home_win_probability(
    card: dict[str, Any], home: dict[str, Any], away: dict[str, Any], home_ice: bool
) -> float:
    """The card's logistic model. A missing input on either side counts as no difference."""
    score = card["coefficients"]["home_ice"] * (1 if home_ice else 0)
    for feature, key in spec(card).inputs.items():
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
    both = inputs_for(conn, card, [home_team_id, away_team_id], season, before)
    home, away = both[home_team_id], both[away_team_id]
    home_ice = not neutral
    s = spec(card)
    p = home_win_probability(card, home, away, home_ice)
    # How far each factor moves the home team's chance: the probability minus what it would
    # be if that one factor were even (no difference, or a neutral site for home ice).
    factors = {"home_ice": p - home_win_probability(card, home, away, False)}
    for key in s.inputs.values():
        factors[key] = p - home_win_probability(card, home, {**away, key: home.get(key)}, home_ice)
    fewest = min(home["games_played"], away["games_played"])
    note = None
    if fewest < s.reliable_games:
        reason = s.reliability_note.format(n=s.reliable_games)
        note = (
            f"A team has played only {fewest} game(s) before this date; {reason}. "
            "Treat it as a rough guide."
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
        "reliable": fewest >= s.reliable_games,
        "note": note,
    }


def predict_game(conn, card: dict[str, Any], game: dict[str, Any]) -> dict[str, Any]:
    """Prediction for one scheduled game (a `games` row with season, game_date, home/away team
    ids, is_neutral). Inputs use only games before the game's date."""
    return predict_matchup(
        conn, card, game["season"], game["home_team_id"], game["away_team_id"],
        game["game_date"], neutral=game["is_neutral"],
    )


# ----------------------------------------------------------------------------
# Rankings: the same model, read as one rating per team
# ----------------------------------------------------------------------------
#
# At a neutral site the model's score is (home rating) - (away rating), where
#   rating = sum over inputs of coefficient * team's input / scale
# so every team has one strength number, and ordering by it agrees with every neutral-site
# head-to-head prediction. "Beats an average team" is the neutral-site chance against the
# average rating of the ranked teams.

RANK_MIN_GAMES = MODELS["win_model_v1"].rank_min_games  # the men's; each Spec has its own

D1_TEAMS_SQL = """
SELECT DISTINCT t.team_id, t.name
FROM hockey.teams t
JOIN hockey.team_seasons ts ON ts.team_id = t.team_id AND ts.season = %(season)s
JOIN features.team_games tg ON tg.team_id = t.team_id
WHERE ts.is_d1 AND tg.season = %(season)s
ORDER BY t.team_id
"""


def team_rating(card: dict[str, Any], inputs: dict[str, Any]) -> float | None:
    """A team's neutral-site strength. None if an input is missing."""
    total = 0.0
    for feature, key in spec(card).inputs.items():
        if inputs.get(key) is None:
            return None
        total += card["coefficients"][feature] * inputs[key] / card["feature_scales"][feature]
    return total


def rank_teams(
    conn, card: dict[str, Any], season: str, before: dt.date, min_games: int | None = None
) -> dict[str, Any]:
    """Every D-I team with at least `min_games` games before `before` (default: the model's
    own minimum), best first."""
    if min_games is None:
        min_games = spec(card).rank_min_games
    with conn.cursor(row_factory=dict_row) as cur:
        teams = cur.execute(D1_TEAMS_SQL, {"season": season}).fetchall()
    all_inputs = inputs_for(conn, card, [t["team_id"] for t in teams], season, before)
    rows, unranked = [], 0
    for t in teams:
        inputs = all_inputs[t["team_id"]]
        rating = team_rating(card, inputs)
        if inputs["games_played"] < min_games or rating is None:
            unranked += 1
            continue
        rows.append({"team_id": t["team_id"], "name": t["name"], "rating": rating, **inputs})
    rows.sort(key=lambda r: (-r["rating"], r["name"]))
    average = sum(r["rating"] for r in rows) / len(rows) if rows else None
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
        r["beats_average"] = 1 / (1 + math.exp(-(r["rating"] - average)))
    return {"teams": rows, "average_rating": average, "unranked": unranked}
