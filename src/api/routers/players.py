from __future__ import annotations

from typing import Annotated, Literal

import psycopg
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from src.api.db import fetch_all, fetch_one
from src.api.models import Page, PlayerDetail, PlayerGame, PlayerSummary
from src.api.params import Conn, PagingQ, PlayerId, SeasonQ, page, result, team_ref

router = APIRouter(prefix="/players", tags=["players"])

MERGE_REDIRECT_LIMIT = 10
SKATER_TOTALS = ("games", "goals", "assists", "points", "plus_minus", "shots", "pim",
                 "faceoffs_won", "faceoffs_lost")  # fmt: skip
GOALIE_TOTALS = ("games", "starts", "saves", "shots_against", "goals_against", "save_pct",
                 "gaa", "toi_seconds")  # fmt: skip


def current_id(conn: psycopg.Connection, player_id: int) -> int:
    """Follow player_id_merges: an id retired when two ids proved to be one player."""
    for _ in range(MERGE_REDIRECT_LIMIT):
        row = fetch_one(
            conn,
            "SELECT new_player_id FROM player_id_merges WHERE old_player_id = %(p)s",
            {"p": player_id},
        )
        if row is None:
            return player_id
        player_id = row["new_player_id"]
    raise HTTPException(500, "player_id_merges has a cycle")


def redirect_if_merged(conn: psycopg.Connection, request: Request, player_id: int, route: str):
    new = current_id(conn, player_id)
    if new == player_id:
        return None
    url = request.url_for(route, player_id=new).include_query_params(**request.query_params)
    return RedirectResponse(str(url), status_code=308)


@router.get("", response_model=Page[PlayerSummary], summary="Find players")
def list_players(
    conn: Conn,
    paging: PagingQ,
    search: Annotated[
        str | None,
        Query(min_length=2, description="Part of a name; any spelling, accents optional"),
    ] = None,
    season: SeasonQ = None,
    team_id: Annotated[int | None, Query(ge=1, description="Played for this team")] = None,
    position: Annotated[Literal["F", "D", "G"] | None, Query()] = None,
) -> dict:
    """Players matching every filter given, by name. `season` and `team_id` together mean
    'on that team that season'."""
    rows = fetch_all(
        conn,
        """
        WITH latest AS (
            SELECT DISTINCT ON (ps.player_id) ps.player_id, ps.team_id, t.name AS team_name
            FROM player_seasons ps JOIN teams t USING (team_id)
            ORDER BY ps.player_id, ps.season DESC, ps.games DESC
        ), span AS (
            SELECT player_id, MIN(season) AS first_season, MAX(season) AS last_season
            FROM player_seasons GROUP BY player_id
        )
        SELECT p.player_id, p.name, p.position, p.chn_player_id, l.team_id, l.team_name,
               s.first_season, s.last_season, COUNT(*) OVER () AS total
        FROM players p JOIN latest l USING (player_id) JOIN span s USING (player_id)
        WHERE (%(search)s::text IS NULL OR EXISTS (
                  SELECT 1 FROM player_names n WHERE n.player_id = p.player_id
                  AND public.unaccent(n.name) ILIKE '%%' || public.unaccent(%(search)s::text) || '%%'))
          AND (%(position)s::text IS NULL OR p.position = %(position)s)
          AND ((%(season)s::text IS NULL AND %(team)s::int IS NULL) OR EXISTS (
                  SELECT 1 FROM player_seasons x WHERE x.player_id = p.player_id
                  AND (%(season)s::text IS NULL OR x.season = %(season)s)
                  AND (%(team)s::int IS NULL OR x.team_id = %(team)s::int)))
        ORDER BY p.name, p.player_id
        LIMIT %(limit)s OFFSET %(offset)s
        """,
        {
            "search": search,
            "position": position,
            "season": season,
            "team": team_id,
            "limit": paging.limit,
            "offset": paging.offset,
        },
    )
    for r in rows:
        r["team"] = team_ref(r.pop("team_id"), r.pop("team_name"))
    return page(rows, paging)


@router.get(
    "/{player_id}",
    response_model=PlayerDetail,
    summary="Player profile with season-by-season stats",
    responses={308: {"description": "This id was merged into another; follow the redirect"}},
)
def get_player(conn: Conn, request: Request, player_id: PlayerId):
    if (moved := redirect_if_merged(conn, request, player_id, "get_player")) is not None:
        return moved
    player = fetch_one(
        conn,
        "SELECT player_id, name, position, chn_player_id FROM players WHERE player_id = %(p)s",
        {"p": player_id},
    )
    if player is None:
        raise HTTPException(404, f"Player {player_id} not found")
    p = {"p": player_id}
    player["names"] = [
        r["name"]
        for r in fetch_all(
            conn, "SELECT DISTINCT name FROM player_names WHERE player_id = %(p)s ORDER BY name", p
        )
    ]
    rows = fetch_all(
        conn,
        f"""
        SELECT ps.season, ps.team_id, t.name AS team_name, ps.position, ps.name, ps.link,
               sk.games AS sk_games, {", ".join(f"sk.{c} AS sk_{c}" for c in SKATER_TOTALS[1:])},
               gl.games AS gl_games, {", ".join(f"gl.{c} AS gl_{c}" for c in GOALIE_TOTALS[1:])}
        FROM player_seasons ps
        JOIN teams t USING (team_id)
        LEFT JOIN skater_season_totals sk USING (player_id, season, team_id)
        LEFT JOIN goalie_season_totals gl USING (player_id, season, team_id)
        WHERE ps.player_id = %(p)s
        ORDER BY ps.season, ps.team_id
        """,
        p,
    )
    seasons = []
    for r in rows:
        seasons.append(
            {
                "season": r["season"],
                "team": team_ref(r["team_id"], r["team_name"]),
                "position": r["position"],
                "name": r["name"],
                "link": r["link"],
                "skater": {c: r[f"sk_{c}"] for c in SKATER_TOTALS} if r["sk_games"] else None,
                "goalie": {c: r[f"gl_{c}"] for c in GOALIE_TOTALS} if r["gl_games"] else None,
            }
        )
    player["seasons"] = seasons
    return player


@router.get(
    "/{player_id}/games",
    response_model=list[PlayerGame],
    summary="Game log",
    responses={308: {"description": "This id was merged into another; follow the redirect"}},
)
def player_games(conn: Conn, request: Request, player_id: PlayerId, season: SeasonQ = None):
    """Every game the player dressed for, oldest first. All seasons unless `season` is given."""
    if (moved := redirect_if_merged(conn, request, player_id, "player_games")) is not None:
        return moved
    if fetch_one(conn, "SELECT 1 FROM players WHERE player_id = %(p)s", {"p": player_id}) is None:
        raise HTTPException(404, f"Player {player_id} not found")
    common = """
        g.game_id, g.game_date AS date, g.season, s.team_id, t.name AS team_name,
        (g.home_team_id IS NOT DISTINCT FROM s.team_id) AS is_home,
        CASE WHEN g.home_team_id IS NOT DISTINCT FROM s.team_id
             THEN g.away_team_id ELSE g.home_team_id END AS opp_id,
        CASE WHEN g.home_team_id IS NOT DISTINCT FROM s.team_id
             THEN g.home_goals ELSE g.away_goals END AS gf,
        CASE WHEN g.home_team_id IS NOT DISTINCT FROM s.team_id
             THEN g.away_goals ELSE g.home_goals END AS ga,
        g.is_played
    """
    where = "WHERE s.player_id = %(p)s AND (%(season)s::text IS NULL OR g.season = %(season)s)"
    params = {"p": player_id, "season": season}
    skater = fetch_all(
        conn,
        f"""SELECT {common}, s.goals, s.assists, s.points, s.plus_minus, s.shots, s.pim,
                   s.toi_seconds
            FROM skater_game_stats s JOIN games g USING (game_id) JOIN teams t USING (team_id)
            {where}""",
        params,
    )
    goalie = fetch_all(
        conn,
        f"""SELECT {common}, s.is_starter, s.saves, s.shots_against, s.goals_against,
                   s.toi_seconds
            FROM goalie_game_stats s JOIN games g USING (game_id) JOIN teams t USING (team_id)
            {where}""",
        params,
    )
    names = {r["team_id"]: r["name"] for r in fetch_all(conn, "SELECT team_id, name FROM teams")}
    games: dict[str, dict] = {}
    for role, rows, cols in (
        (
            "skater",
            skater,
            ("goals", "assists", "points", "plus_minus", "shots", "pim", "toi_seconds"),
        ),
        (
            "goalie",
            goalie,
            ("is_starter", "saves", "shots_against", "goals_against", "toi_seconds"),
        ),
    ):
        for r in rows:
            g = games.setdefault(
                r["game_id"],
                {
                    "game_id": r["game_id"],
                    "date": r["date"],
                    "season": r["season"],
                    "team": team_ref(r["team_id"], r["team_name"]),
                    "opponent": team_ref(r["opp_id"], names.get(r["opp_id"])),
                    "is_home": r["is_home"],
                    "result": result(r["gf"], r["ga"], r["is_played"]),
                    "skater": None,
                    "goalie": None,
                },
            )
            g[role] = {c: r[c] for c in cols}
    return sorted(games.values(), key=lambda g: (g["date"], g["game_id"]))
