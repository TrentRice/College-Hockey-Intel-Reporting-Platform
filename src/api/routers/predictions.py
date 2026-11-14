"""The prediction log (db/predictions.sql, written nightly by src/pipeline/predict.py)."""

from __future__ import annotations

import math
from typing import Annotated

from fastapi import APIRouter, Query, Request

from src.api.db import fetch_all, fetch_one, resolve_season
from src.api.models import LoggedPrediction, Page, PredictionSummary
from src.api.params import Conn, PagingQ, SeasonQ, team_ref

router = APIRouter(prefix="/predictions", tags=["predictions"])

MODEL_DEFAULT = "win_model_v1"
CAL_EDGES = [0.5, 0.55, 0.6, 0.65, 0.7, 0.8, 1.0]  # favorite's chance

LOG_SQL = """
SELECT p.*, h.name AS home_name, a.name AS away_name,
       COALESCE(g.is_played, FALSE) AS is_played, g.home_goals, g.away_goals,
       COUNT(*) OVER () AS total
FROM predictions.game_predictions p
LEFT JOIN games g ON g.game_id = p.game_id
LEFT JOIN teams h ON h.team_id = p.home_team_id
LEFT JOIN teams a ON a.team_id = p.away_team_id
WHERE p.season = %(season)s AND p.model = %(model)s
  AND (%(team)s::int IS NULL OR %(team)s::int IN (p.home_team_id, p.away_team_id))
  AND (%(played)s::boolean IS NULL OR COALESCE(g.is_played, FALSE) = %(played)s)
  AND (%(backfilled)s OR NOT p.backfilled)
  AND (NOT %(reliable)s OR p.reliable)
ORDER BY p.game_date DESC, p.game_id
"""


def log_exists(conn) -> bool:
    return fetch_one(conn, "SELECT to_regclass('predictions.game_predictions') AS t")["t"] is not None


def shape(r: dict) -> dict:
    p = r["home_win_probability"]
    home = team_ref(r["home_team_id"], r.pop("home_name"))
    away = team_ref(r["away_team_id"], r.pop("away_name"))
    result = None
    if r["is_played"] and r["home_goals"] is not None:
        hg, ag = r["home_goals"], r["away_goals"]
        result = "home" if hg > ag else "away" if ag > hg else "tie"
    fav_home = p >= 0.5
    return {
        "game_id": r["game_id"], "date": r["game_date"], "home": home, "away": away,
        "neutral": r["neutral"], "home_win_probability": p,
        "favorite": home if fav_home else away,
        "favorite_probability": p if fav_home else 1 - p,
        "reliable": r["reliable"], "backfilled": r["backfilled"],
        "final": r["backfilled"] or r["logged_on"] >= r["game_date"],
        "logged_at": r["updated_at"], "is_played": r["is_played"],
        "home_goals": r["home_goals"], "away_goals": r["away_goals"], "result": result,
        "correct": None if result in (None, "tie") else (result == "home") == fav_home,
    }  # fmt: skip


def query(conn, season, model, team_id, played, backfilled, reliable_only):
    if not log_exists(conn):
        return []
    return fetch_all(conn, LOG_SQL, {
        "season": season, "model": model, "team": team_id, "played": played,
        "backfilled": backfilled, "reliable": reliable_only,
    })  # fmt: skip


TeamQ = Annotated[int | None, Query(ge=1, description="Only games involving this team")]
ModelQ = Annotated[str, Query(description="Model version")]
BackfilledQ = Annotated[
    bool, Query(description="Include backfilled rows (not logged before the game)")
]
ReliableQ = Annotated[
    bool,
    Query(description="Only games where both teams had played 3+ games (the model's scope)"),
]


@router.get("", response_model=Page[LoggedPrediction], summary="The prediction log")
def prediction_log(
    conn: Conn,
    paging: PagingQ,
    season: SeasonQ = None,
    team_id: TeamQ = None,
    played: Annotated[bool | None, Query(description="true = graded, false = upcoming")] = None,
    model: ModelQ = MODEL_DEFAULT,
    backfilled: BackfilledQ = True,
    reliable_only: ReliableQ = False,
) -> dict:
    """Logged predictions, newest first, each with the result once the game is played."""
    season = resolve_season(conn, season)
    rows = query(conn, season, model, team_id, played, backfilled, reliable_only)
    total = len(rows)
    items = [shape(r) for r in rows[paging.offset : paging.offset + paging.limit]]
    return {"items": items, "total": total, "limit": paging.limit, "offset": paging.offset}


@router.get("/summary", response_model=PredictionSummary, summary="How the model has done")
def prediction_summary(
    request: Request,
    conn: Conn,
    season: SeasonQ = None,
    team_id: TeamQ = None,
    model: ModelQ = MODEL_DEFAULT,
    backfilled: BackfilledQ = True,
    reliable_only: ReliableQ = False,
) -> dict:
    """Accuracy, log loss and calibration over the decided games in the log, next to a
    home-ice-only baseline. Ties are excluded: the model predicts a decided game."""
    season = resolve_season(conn, season)
    rows = [shape(r) for r in query(conn, season, model, team_id, None, backfilled, reliable_only)]
    graded = [r for r in rows if r["result"] in ("home", "away")]
    card = request.app.state.win_card
    home_edge = None if card is None else 1 / (1 + math.exp(-card["coefficients"]["home_ice"]))

    def ll(p, won):
        p = min(max(p, 1e-15), 1 - 1e-15)
        return -math.log(p if won else 1 - p)

    n = len(graded)
    out = {
        "season": season, "model": model, "games": n,
        "logged_before": sum(not r["backfilled"] for r in graded),
        "backfilled": sum(r["backfilled"] for r in graded),
        "ties_excluded": sum(r["result"] == "tie" for r in rows),
        "upcoming_logged": sum(not r["is_played"] for r in rows),
        "correct": sum(bool(r["correct"]) for r in graded),
        "accuracy": None, "log_loss": None, "brier": None, "baseline_log_loss": None,
        "calibration": [],
    }  # fmt: skip
    if n:
        home_won = [r["result"] == "home" for r in graded]
        ps = [r["home_win_probability"] for r in graded]
        out["accuracy"] = out["correct"] / n
        out["log_loss"] = sum(ll(p, w) for p, w in zip(ps, home_won)) / n
        out["brier"] = sum((p - w) ** 2 for p, w in zip(ps, home_won)) / n
        if home_edge is not None:
            base = [0.5 if r["neutral"] else home_edge for r in graded]
            out["baseline_log_loss"] = sum(ll(p, w) for p, w in zip(base, home_won)) / n
        for lo, hi in zip(CAL_EDGES, CAL_EDGES[1:]):
            in_bin = [r for r in graded if lo <= r["favorite_probability"] < hi]
            if in_bin:
                out["calibration"].append({
                    "low": lo, "high": hi, "games": len(in_bin),
                    "predicted": sum(r["favorite_probability"] for r in in_bin) / len(in_bin),
                    "actual": sum(bool(r["correct"]) for r in in_bin) / len(in_bin),
                })  # fmt: skip
    return out
