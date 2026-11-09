from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from src.api.db import fetch_all, resolve_season
from src.api.models import GoalieLeader, Page, SkaterLeader
from src.api.params import ConferenceQ, Conn, PagingQ, SeasonQ, page, team_ref

router = APIRouter(prefix="/leaders", tags=["leaders"])

# NCAA standard: a goalie qualifies for save % / GAA leaders by playing a third of the
# team's minutes.
GOALIE_MIN_SHARE = 1 / 3


class SkaterStat(str, Enum):
    points = "points"
    goals = "goals"
    assists = "assists"
    points_per_game = "points_per_game"
    plus_minus = "plus_minus"
    shots = "shots"
    pim = "pim"


class GoalieStat(str, Enum):
    save_pct = "save_pct"
    gaa = "gaa"
    saves = "saves"
    starts = "starts"


# whitelisted SQL for each sort: (expression, direction). Never user text in the SQL.
SKATER_SORT = {s: (s.value, "DESC") for s in SkaterStat}
GOALIE_SORT = {s: (s.value, "ASC" if s is GoalieStat.gaa else "DESC") for s in GoalieStat}


@router.get("/skaters", response_model=Page[SkaterLeader], summary="Skater leaders")
def skater_leaders(
    conn: Conn,
    paging: PagingQ,
    stat: SkaterStat = SkaterStat.points,
    season: SeasonQ = None,
    position: Annotated[Literal["F", "D"] | None, Query()] = None,
    conference: ConferenceQ = None,
    min_games: Annotated[int, Query(ge=0, description="Games played at least")] = 1,
) -> dict:
    """Ranked by `stat`; ties share a rank. A player traded mid-season is listed per team."""
    season = resolve_season(conn, season)
    col, direction = SKATER_SORT[stat]
    rows = fetch_all(
        conn,
        f"""
        WITH t AS (
            SELECT s.*, p.name, NULLIF(ps.position, 'G') AS position, tm.name AS team_name,
                   ROUND(s.points::numeric / NULLIF(s.games, 0), 2) AS points_per_game
            FROM skater_season_totals s
            JOIN players p USING (player_id)
            JOIN teams tm USING (team_id)
            LEFT JOIN player_seasons ps USING (player_id, season, team_id)
            LEFT JOIN team_seasons ts USING (team_id, season)
            WHERE s.season = %(season)s AND s.games >= %(min_games)s
              AND (%(position)s::text IS NULL OR ps.position = %(position)s)
              AND (%(conf)s::text IS NULL OR ts.conference ILIKE %(conf)s)
        )
        SELECT RANK() OVER (ORDER BY {col} {direction}) AS rank, player_id, name, position,
               team_id, team_name, games, goals, assists, points, plus_minus, shots, pim,
               faceoffs_won, faceoffs_lost, points_per_game, COUNT(*) OVER () AS total
        FROM t WHERE {col} IS NOT NULL
        ORDER BY {col} {direction}, name
        LIMIT %(limit)s OFFSET %(offset)s
        """,
        {
            "season": season,
            "min_games": min_games,
            "position": position,
            "conf": conference,
            "limit": paging.limit,
            "offset": paging.offset,
        },
    )
    for r in rows:
        r["team"] = team_ref(r.pop("team_id"), r.pop("team_name"))
    return page(rows, paging)


@router.get("/goalies", response_model=Page[GoalieLeader], summary="Goalie leaders")
def goalie_leaders(
    conn: Conn,
    paging: PagingQ,
    stat: GoalieStat = GoalieStat.save_pct,
    season: SeasonQ = None,
    conference: ConferenceQ = None,
    qualified: Annotated[
        bool, Query(description="Only goalies with a third of their team's minutes (NCAA rule)")
    ] = True,
) -> dict:
    """Ranked by `stat` (GAA lowest first); ties share a rank."""
    season = resolve_season(conn, season)
    col, direction = GOALIE_SORT[stat]
    rows = fetch_all(
        conn,
        f"""
        WITH t AS (
            SELECT g.*, p.name, tm.name AS team_name
            FROM goalie_season_totals g
            JOIN players p USING (player_id)
            JOIN teams tm USING (team_id)
            JOIN team_season_totals tt USING (season, team_id)
            LEFT JOIN team_seasons ts USING (team_id, season)
            WHERE g.season = %(season)s
              AND (NOT %(qualified)s OR g.toi_seconds >= %(share)s * tt.games * 3600)
              AND (%(conf)s::text IS NULL OR ts.conference ILIKE %(conf)s)
        )
        SELECT RANK() OVER (ORDER BY {col} {direction}) AS rank, player_id, name, team_id,
               team_name, games, starts, saves, shots_against, goals_against, save_pct, gaa,
               toi_seconds, COUNT(*) OVER () AS total
        FROM t WHERE {col} IS NOT NULL
        ORDER BY {col} {direction}, name
        LIMIT %(limit)s OFFSET %(offset)s
        """,
        {
            "season": season,
            "qualified": qualified,
            "share": GOALIE_MIN_SHARE,
            "conf": conference,
            "limit": paging.limit,
            "offset": paging.offset,
        },
    )
    for r in rows:
        r["team"] = team_ref(r.pop("team_id"), r.pop("team_name"))
    return page(rows, paging)
