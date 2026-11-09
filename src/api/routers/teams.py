from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from src.api.db import fetch_all, fetch_one, require_team, resolve_season
from src.api.models import (
    Roster,
    TeamDetail,
    TeamGame,
    TeamRef,
    TeamSeasonStats,
    TeamSummary,
)
from src.api.params import ConferenceQ, Conn, SeasonQ, TeamId, result, team_ref

router = APIRouter(prefix="/teams", tags=["teams"])


@router.get("", response_model=list[TeamSummary], summary="List teams")
def list_teams(
    conn: Conn,
    season: SeasonQ = None,
    conference: ConferenceQ = None,
    search: Annotated[
        str | None, Query(min_length=2, description="Part of a team name or alias")
    ] = None,
    d1_only: Annotated[bool, Query(description="Leave out non-D1 opponents")] = False,
) -> list[dict]:
    """Teams that played or were scheduled in the season, with that season's conference."""
    season = resolve_season(conn, season)
    return fetch_all(
        conn,
        """
        SELECT t.team_id, t.name, t.is_d1, t.chn_team_id, ts.conference
        FROM teams t JOIN team_seasons ts ON ts.team_id = t.team_id AND ts.season = %(season)s
        WHERE (%(conference)s::text IS NULL OR ts.conference ILIKE %(conference)s)
          AND (NOT %(d1_only)s OR t.is_d1)
          AND (%(search)s::text IS NULL OR EXISTS (
                SELECT 1 FROM team_aliases a
                WHERE a.team_id = t.team_id AND a.alias ILIKE '%%' || %(search)s || '%%'))
        ORDER BY t.name
        """,
        {"season": season, "conference": conference, "search": search, "d1_only": d1_only},
    )


@router.get("/{team_id}", response_model=TeamDetail, summary="One team")
def get_team(conn: Conn, team_id: TeamId) -> dict:
    team = fetch_one(
        conn,
        "SELECT team_id, name, is_d1, chn_team_id FROM teams WHERE team_id = %(t)s",
        {"t": team_id},
    )
    if team is None:
        raise HTTPException(404, f"Team {team_id} not found")
    p = {"t": team_id}
    team["aliases"] = [
        r["alias"]
        for r in fetch_all(
            conn, "SELECT alias FROM team_aliases WHERE team_id = %(t)s ORDER BY alias", p
        )
    ]
    team["seasons"] = fetch_all(
        conn, "SELECT season, conference FROM team_seasons WHERE team_id = %(t)s ORDER BY season", p
    )
    return team


@router.get("/{team_id}/games", response_model=list[TeamGame], summary="Schedule and results")
def team_games(
    conn: Conn,
    team_id: TeamId,
    season: SeasonQ = None,
    played: Annotated[
        bool | None, Query(description="true = results only, false = upcoming only")
    ] = None,
) -> list[dict]:
    require_team(conn, team_id)
    season = resolve_season(conn, season)
    rows = fetch_all(
        conn,
        """
        SELECT g.game_id, g.game_date AS date, g.season,
               (g.home_team_id IS NOT DISTINCT FROM %(t)s)                                     AS is_home,
               CASE WHEN g.home_team_id IS NOT DISTINCT FROM %(t)s THEN g.away_team_id ELSE g.home_team_id END AS opp_id,
               opp.name                                                      AS opp_name,
               g.is_neutral, g.is_conference, g.is_played,
               CASE WHEN g.home_team_id IS NOT DISTINCT FROM %(t)s THEN g.home_goals ELSE g.away_goals END AS goals_for,
               CASE WHEN g.home_team_id IS NOT DISTINCT FROM %(t)s THEN g.away_goals ELSE g.home_goals END AS goals_against,
               g.ot_periods,
               CASE WHEN g.shootout_winner_team_id IS NULL THEN NULL
                    ELSE g.shootout_winner_team_id = %(t)s END               AS shootout_won,
               s.shots AS shots_for, s.shots_against,
               g.game_type, g.event, g.venue
        FROM games g
        LEFT JOIN teams opp
               ON opp.team_id = CASE WHEN g.home_team_id IS NOT DISTINCT FROM %(t)s THEN g.away_team_id ELSE g.home_team_id END
        LEFT JOIN team_game_stats s ON s.game_id = g.game_id AND s.team_id = %(t)s
        WHERE %(t)s IN (g.home_team_id, g.away_team_id) AND g.season = %(season)s
          AND (%(played)s::boolean IS NULL OR g.is_played = %(played)s)
        ORDER BY g.game_date, g.game_id
        """,
        {"t": team_id, "season": season, "played": played},
    )
    for r in rows:
        r["opponent"] = team_ref(r.pop("opp_id"), r.pop("opp_name"))
        r["result"] = result(r["goals_for"], r["goals_against"], r["is_played"])
    return rows


@router.get("/{team_id}/season-stats", response_model=TeamSeasonStats, summary="Season totals")
def team_season_stats(conn: Conn, team_id: TeamId, season: SeasonQ = None) -> dict:
    team = require_team(conn, team_id)
    season = resolve_season(conn, season)
    row = fetch_one(
        conn,
        """
        SELECT season, games, wins, losses, ties, goals_for, goals_against,
               shots_for, shots_against, pp_pct, pk_pct, faceoff_pct
        FROM team_season_totals WHERE team_id = %(t)s AND season = %(season)s
        """,
        {"t": team_id, "season": season},
    )
    if row is None:
        raise HTTPException(404, f"No games played by team {team_id} in {season}")
    row["team"] = TeamRef(**team)
    row["record"] = f"{row['wins']}-{row['losses']}-{row['ties']}"
    row["goal_diff"] = row["goals_for"] - row["goals_against"]
    return row


@router.get("/{team_id}/roster", response_model=Roster, summary="Skater and goalie season totals")
def team_roster(conn: Conn, team_id: TeamId, season: SeasonQ = None) -> dict:
    team = require_team(conn, team_id)
    season = resolve_season(conn, season)
    p = {"t": team_id, "season": season}
    skaters = fetch_all(
        conn,
        """
        SELECT s.player_id, p.name, NULLIF(ps.position, 'G') AS position, s.games, s.goals,
               s.assists, s.points, s.plus_minus, s.shots, s.pim, s.faceoffs_won, s.faceoffs_lost
        FROM skater_season_totals s
        JOIN players p USING (player_id)
        LEFT JOIN player_seasons ps USING (player_id, season, team_id)
        WHERE s.team_id = %(t)s AND s.season = %(season)s
        ORDER BY s.points DESC, s.goals DESC, p.name
        """,
        p,
    )
    goalies = fetch_all(
        conn,
        """
        SELECT g.player_id, p.name, g.games, g.starts, g.saves, g.shots_against,
               g.goals_against, g.save_pct, g.gaa, g.toi_seconds
        FROM goalie_season_totals g JOIN players p USING (player_id)
        WHERE g.team_id = %(t)s AND g.season = %(season)s
        ORDER BY g.toi_seconds DESC
        """,
        p,
    )
    return {"team": team, "season": season, "skaters": skaters, "goalies": goalies}
