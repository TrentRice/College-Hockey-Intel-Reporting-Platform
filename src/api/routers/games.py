from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query

from src.api.db import fetch_all, fetch_one, resolve_season
from src.api.models import BoxScore, GameSummary, Page
from src.api.params import Conn, PagingQ, SeasonQ, mmss, page, player_ref, team_ref

router = APIRouter(prefix="/games", tags=["games"])

GAME_COLUMNS = """
    g.game_id, g.season, g.game_date AS date,
    g.home_team_id, h.name AS home_name, g.away_team_id, a.name AS away_name,
    g.home_goals, g.away_goals, g.is_played, g.is_neutral, g.is_conference, g.ot_periods,
    g.shootout_winner_team_id, sw.name AS shootout_winner_name,
    g.game_type, g.event, g.venue
"""
GAME_JOINS = """
    FROM games g
    LEFT JOIN teams h  ON h.team_id = g.home_team_id
    LEFT JOIN teams a  ON a.team_id = g.away_team_id
    LEFT JOIN teams sw ON sw.team_id = g.shootout_winner_team_id
"""


def shape_game(r: dict) -> dict:
    r["home"] = team_ref(r.pop("home_team_id"), r.pop("home_name"))
    r["away"] = team_ref(r.pop("away_team_id"), r.pop("away_name"))
    r["shootout_winner"] = team_ref(r.pop("shootout_winner_team_id"), r.pop("shootout_winner_name"))
    return r


@router.get("", response_model=Page[GameSummary], summary="Find games")
def list_games(
    conn: Conn,
    paging: PagingQ,
    season: SeasonQ = None,
    date: Annotated[dt.date | None, Query(description="One day, e.g. 2026-11-08")] = None,
    date_from: Annotated[dt.date | None, Query(description="On or after")] = None,
    date_to: Annotated[dt.date | None, Query(description="On or before")] = None,
    team_id: Annotated[int | None, Query(ge=1, description="Games involving this team")] = None,
    played: Annotated[bool | None, Query(description="true = results, false = upcoming")] = None,
    conference_only: Annotated[bool, Query(description="Conference games only")] = False,
) -> dict:
    """Games in date order. With no season or dates, the latest season."""
    if date is not None:
        date_from = date_to = date
    if season is not None or (date_from is None and date_to is None):
        season = resolve_season(conn, season)
    rows = fetch_all(
        conn,
        f"""
        SELECT {GAME_COLUMNS}, COUNT(*) OVER () AS total
        {GAME_JOINS}
        WHERE (%(season)s::text IS NULL OR g.season = %(season)s)
          AND (%(date_from)s::date IS NULL OR g.game_date >= %(date_from)s)
          AND (%(date_to)s::date IS NULL OR g.game_date <= %(date_to)s)
          AND (%(team)s::int IS NULL OR %(team)s::int IN (g.home_team_id, g.away_team_id))
          AND (%(played)s::boolean IS NULL OR g.is_played = %(played)s)
          AND (NOT %(conf)s OR g.is_conference)
        ORDER BY g.game_date, g.game_id
        LIMIT %(limit)s OFFSET %(offset)s
        """,
        {
            "season": season,
            "date_from": date_from,
            "date_to": date_to,
            "team": team_id,
            "played": played,
            "conf": conference_only,
            "limit": paging.limit,
            "offset": paging.offset,
        },
    )
    return page([shape_game(r) for r in rows], paging)


@router.get("/{game_id}", response_model=BoxScore, summary="Full box score")
def box_score(
    conn: Conn,
    game_id: Annotated[str, Path(description="e.g. 2026-10-02_10_4 (from the games list)")],
) -> dict:
    game = fetch_one(
        conn,
        f"""
        SELECT {GAME_COLUMNS}, g.shootout_score, g.game_note, g.attendance, g.referees,
               g.asst_referees, g.box_score_url
        {GAME_JOINS}
        WHERE g.game_id = %(g)s
        """,
        {"g": game_id},
    )
    if game is None:
        raise HTTPException(404, f"Game {game_id} not found")
    game = shape_game(game)
    p = {"g": game_id}

    stats = {
        r["team_id"]: r
        for r in fetch_all(conn, "SELECT * FROM team_game_stats WHERE game_id = %(g)s", p)
    }
    skaters = fetch_all(
        conn,
        """
        SELECT s.team_id, s.player_id, pl.name, s.position, s.goals, s.assists, s.points,
               s.plus_minus, s.shots, s.pim, s.toi_seconds, s.faceoffs_won, s.faceoffs_lost
        FROM skater_game_stats s JOIN players pl USING (player_id)
        WHERE s.game_id = %(g)s
        ORDER BY s.points DESC, s.goals DESC, pl.name
        """,
        p,
    )
    goalies = fetch_all(
        conn,
        """
        SELECT s.team_id, s.player_id, pl.name, s.is_starter, s.saves, s.shots_against,
               s.goals_against, s.toi_seconds
        FROM goalie_game_stats s JOIN players pl USING (player_id)
        WHERE s.game_id = %(g)s
        ORDER BY s.is_starter DESC, s.toi_seconds DESC
        """,
        p,
    )

    teams = []
    for side, is_home in (("away", False), ("home", True)):
        ref = game[side]
        if ref is None:
            continue  # TBD
        tid = ref["team_id"]
        st = stats.get(tid)
        teams.append(
            {
                "team": ref,
                "is_home": is_home,
                "stats": None
                if st is None
                else {
                    **st,
                    "goals_by_period": [
                        st["goals_p1"],
                        st["goals_p2"],
                        st["goals_p3"],
                        st["goals_ot"],
                    ],
                    "shots_by_period": [
                        st["shots_p1"],
                        st["shots_p2"],
                        st["shots_p3"],
                        st["shots_ot"],
                    ],
                },
                "skaters": [s for s in skaters if s["team_id"] == tid],
                "goalies": [g for g in goalies if g["team_id"] == tid],
            }
        )

    goals = fetch_all(
        conn,
        """
        SELECT g.goal_number, g.period, g.period_seconds, g.team_id, t.name AS team_name,
               g.strength, g.is_pp, g.is_sh, g.is_en, g.is_extra_attacker, g.is_penalty_shot,
               g.scorer_id, s.name AS scorer_name,
               g.assist1_id, a1.name AS assist1_name, g.assist2_id, a2.name AS assist2_name
        FROM goals g
        JOIN teams t ON t.team_id = g.team_id
        LEFT JOIN players s  ON s.player_id = g.scorer_id
        LEFT JOIN players a1 ON a1.player_id = g.assist1_id
        LEFT JOIN players a2 ON a2.player_id = g.assist2_id
        WHERE g.game_id = %(g)s ORDER BY g.goal_number
        """,
        p,
    )
    for r in goals:
        r["time"] = mmss(r.pop("period_seconds"))
        r["team"] = team_ref(r.pop("team_id"), r.pop("team_name"))
        r["scorer"] = player_ref(r.pop("scorer_id"), r.pop("scorer_name"))
        assists = [player_ref(r.pop(f"assist{i}_id"), r.pop(f"assist{i}_name")) for i in (1, 2)]
        r["assists"] = [a for a in assists if a is not None]

    penalties = fetch_all(
        conn,
        """
        SELECT p.penalty_number, p.period, p.period_seconds, p.team_id, t.name AS team_name,
               p.player_id, pl.name AS player_name, p.is_bench, p.minutes, p.infraction
        FROM penalties p
        JOIN teams t ON t.team_id = p.team_id
        LEFT JOIN players pl ON pl.player_id = p.player_id
        WHERE p.game_id = %(g)s ORDER BY p.penalty_number
        """,
        p,
    )
    for r in penalties:
        r["time"] = mmss(r.pop("period_seconds"))
        r["team"] = team_ref(r.pop("team_id"), r.pop("team_name"))
        r["player"] = player_ref(r.pop("player_id"), r.pop("player_name"))

    return {"game": game, "teams": teams, "goals": goals, "penalties": penalties}
