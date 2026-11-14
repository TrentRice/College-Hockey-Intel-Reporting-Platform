"""Model rankings: every D-I team ordered by win model v1's neutral-site rating."""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from src.api.db import resolve_season
from src.api.models import Rankings
from src.api.params import Conn, SeasonQ, team_ref
from src.models.win_model import RANK_MIN_GAMES, rank_teams

router = APIRouter(prefix="/rankings", tags=["rankings"])


@router.get("", response_model=Rankings, summary="Teams ranked by the win model")
def rankings(
    request: Request,
    conn: Conn,
    season: SeasonQ = None,
    as_of: Annotated[dt.date | None, Query(description="Use games before this date (default: today)")] = None,
    min_games: Annotated[int, Query(ge=1, le=40, description="Games needed to be ranked")] = RANK_MIN_GAMES,
    limit: Annotated[int | None, Query(ge=1, description="Top N only (default: all ranked)")] = None,
) -> dict:
    """Who the model says is best: each team's chance to beat an average team on neutral
    ice, from its season so far. Ordering agrees with every neutral-site prediction. Not
    adjusted for strength of schedule. Movement compares with the ranking a week earlier."""
    card = request.app.state.win_card
    if card is None:
        raise HTTPException(503, request.app.state.win_card_error)
    season = resolve_season(conn, season)
    before = as_of or dt.date.today()
    earlier = before - dt.timedelta(days=7)
    now = rank_teams(conn, card, season, before, min_games)
    then = rank_teams(conn, card, season, earlier, min_games)
    prev = {r["team_id"]: r["rank"] for r in then["teams"]}
    teams = []
    for r in now["teams"][:limit]:
        p = prev.get(r["team_id"])
        teams.append({
            "rank": r["rank"], "team": team_ref(r["team_id"], r["name"]),
            "beats_average": r["beats_average"], "rating": r["rating"],
            "record": f"{r['wins']}-{r['losses']}-{r['ties']}",
            "games_played": r["games_played"], "previous_rank": p,
            "change": None if p is None else p - r["rank"],
            "close_shot_share": r["close_shot_share"], "goal_diff_per_game": r["goal_diff_per_game"],
        })  # fmt: skip
    return {
        "season": season, "model": card["name"], "as_of": before, "compared_to": earlier,
        "min_games": min_games, "unranked": now["unranked"], "teams": teams,
    }
