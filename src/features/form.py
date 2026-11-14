"""
Team and player form over a team's last N games, as of a date.

  team_form(conn, team_id, season, last=5, as_of=date(2026, 11, 14))
  player_form(conn, team_id, season, last=5, as_of=...)

Rules
  * As of: only games played *before* `as_of` count (None = every played game). A report
    for Saturday's game uses as_of=Saturday, so nothing from that game or later leaks in.
  * Last N: the team's N most recent of those games. N above the games played uses them all;
    `games_used` says how many were used. None = the whole season so far.
  * Whenever the window is shorter than the season so far, the season totals come back next
    to it, so the two can be compared side by side.
  * Players are measured over the team's window. A player who missed some of those games
    shows fewer games played.

The summaries are plain functions over game rows (summarize_team, summarize_skater,
summarize_goalie), so the model can reuse them on any set of games.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Any

import psycopg
from psycopg.rows import dict_row

Row = dict[str, Any]
LIKELY_STARTER_WINDOW = 5  # games used to guess the next starting goalie


def ratio(num: float, den: float, digits: int = 3) -> float | None:
    return round(num / den, digits) if den else None


def per_game(total: float, games: int) -> float | None:
    return round(total / games, 2) if games else None


# ----------------------------------------------------------------------------
# Summaries over a set of game rows
# ----------------------------------------------------------------------------


def record(rows: list[Row]) -> str:
    w = sum(r["result"] == "W" for r in rows)
    lo = sum(r["result"] == "L" for r in rows)
    t = sum(r["result"] == "T" for r in rows)
    return f"{w}-{lo}-{t}"


def streak(rows_newest_first: list[Row]) -> str | None:
    """'W3' = won the last 3."""
    if not rows_newest_first:
        return None
    first = rows_newest_first[0]["result"]
    n = 0
    for r in rows_newest_first:
        if r["result"] != first:
            break
        n += 1
    return f"{first}{n}"


def summarize_team(rows_newest_first: list[Row]) -> Row:
    rows = rows_newest_first
    n = len(rows)

    def tot(col: str) -> float:
        return sum(r[col] or 0 for r in rows)

    gf, ga, sf, sa = tot("goals_for"), tot("goals_against"), tot("shots_for"), tot("shots_against")
    w = sum(r["result"] == "W" for r in rows)
    t = sum(r["result"] == "T" for r in rows)
    with_xg = [r for r in rows if r["xg_for"] is not None and r["xg_against"] is not None]
    xgf = sum(float(r["xg_for"]) for r in with_xg)
    xga = sum(float(r["xg_against"]) for r in with_xg)
    home = [r for r in rows if r["is_home"] and not r["is_neutral"]]
    away = [r for r in rows if not r["is_home"] and not r["is_neutral"]]
    neutral = [r for r in rows if r["is_neutral"]]
    return {
        "games": n,
        "record": record(rows),
        "win_pct": ratio(w + 0.5 * t, n),
        "streak": streak(rows),
        "home_record": record(home),
        "away_record": record(away),
        "neutral_record": record(neutral),
        "goals_for": int(gf),
        "goals_against": int(ga),
        "goals_for_per_game": per_game(gf, n),
        "goals_against_per_game": per_game(ga, n),
        "goal_diff_per_game": per_game(gf - ga, n),
        "shots_for_per_game": per_game(sf, n),
        "shots_against_per_game": per_game(sa, n),
        "shot_share": ratio(sf, sf + sa),
        "xg_share": ratio(xgf, xgf + xga),
        "xg_for_per_game": per_game(xgf, len(with_xg)),
        "xg_against_per_game": per_game(xga, len(with_xg)),
        "shooting_pct": ratio(gf, sf),
        "save_pct": ratio(sa - ga, sa),
        "pp_goals": int(tot("pp_goals")),
        "pp_opportunities": int(tot("pp_opportunities")),
        "pp_pct": ratio(tot("pp_goals"), tot("pp_opportunities")),
        "pk_pct": ratio(
            tot("times_shorthanded") - tot("pp_goals_against"), tot("times_shorthanded")
        ),
        "pp_opportunities_per_game": per_game(tot("pp_opportunities"), n),
        "times_shorthanded_per_game": per_game(tot("times_shorthanded"), n),
        "sh_goals": int(tot("sh_goals")),
        "pim_per_game": per_game(tot("pim"), n),
        "faceoff_pct": ratio(tot("faceoffs_won"), tot("faceoffs_won") + tot("faceoffs_lost")),
    }


def summarize_skater(rows: list[Row]) -> Row:
    def tot(col: str) -> int:
        return int(sum(r[col] or 0 for r in rows))

    n, goals, shots = len(rows), tot("goals"), tot("shots")
    return {
        "games": n,
        "goals": goals,
        "assists": tot("assists"),
        "points": tot("points"),
        "points_per_game": per_game(tot("points"), n),
        "pp_goals": tot("pp_goals"),
        "pp_points": tot("pp_goals") + tot("pp_assists"),
        "shots": shots,
        "shooting_pct": ratio(goals, shots),
        "plus_minus": tot("plus_minus"),
        "pim": tot("pim"),
    }


def summarize_goalie(rows: list[Row]) -> Row:
    def tot(col: str) -> int:
        return int(sum(r[col] or 0 for r in rows))

    sa, ga, toi = tot("shots_against"), tot("goals_against"), tot("toi_seconds")
    return {
        "games": len(rows),
        "starts": sum(bool(r["is_starter"]) for r in rows),
        "saves": tot("saves"),
        "shots_against": sa,
        "goals_against": ga,
        "save_pct": ratio(sa - ga, sa),
        "gaa": round(ga * 3600 / toi, 2) if toi else None,
        "toi_seconds": toi,
    }


# ----------------------------------------------------------------------------
# Fetching a team's games
# ----------------------------------------------------------------------------


def team_games(
    conn: psycopg.Connection, team_id: int, season: str, as_of: dt.date | None
) -> list[Row]:
    """The team's played games in the season before as_of, newest first."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            """
            SELECT tg.*, o.name AS opponent_name
            FROM features.team_games tg
            JOIN hockey.teams o ON o.team_id = tg.opponent_team_id
            WHERE tg.team_id = %(t)s AND tg.season = %(s)s
              AND (%(as_of)s::date IS NULL OR tg.game_date < %(as_of)s)
            ORDER BY tg.game_date DESC, tg.game_id DESC
            """,
            {"t": team_id, "s": season, "as_of": as_of},
        ).fetchall()


def window(rows_newest_first: list[Row], last: int | None) -> list[Row]:
    return rows_newest_first if last is None else rows_newest_first[:last]


def game_line(r: Row) -> Row:
    return {
        "game_id": r["game_id"],
        "date": r["game_date"],
        "opponent": {"team_id": r["opponent_team_id"], "name": r["opponent_name"]},
        "is_home": r["is_home"],
        "is_neutral": r["is_neutral"],
        "result": r["result"],
        "goals_for": r["goals_for"],
        "goals_against": r["goals_against"],
        "ot_periods": r["ot_periods"],
        "shootout_won": r["shootout_won"],
        "shots_for": r["shots_for"],
        "shots_against": r["shots_against"],
        "xg_for": float(r["xg_for"]) if r["xg_for"] is not None else None,
        "xg_against": float(r["xg_against"]) if r["xg_against"] is not None else None,
        "rest_days": r["rest_days"],
    }


# ----------------------------------------------------------------------------
# Team and player form
# ----------------------------------------------------------------------------


def team_form(
    conn: psycopg.Connection,
    team_id: int,
    season: str,
    last: int | None = None,
    as_of: dt.date | None = None,
) -> Row | None:
    """None if the team has no played games in the season before as_of."""
    season_rows = team_games(conn, team_id, season, as_of)
    if not season_rows:
        return None
    used = window(season_rows, last)
    partial = len(used) < len(season_rows)
    return {
        "games_played": len(season_rows),
        "last": last,
        "games_used": len(used),
        "window": summarize_team(used),
        "season": summarize_team(season_rows) if partial else None,
        "games": [game_line(r) for r in used],
    }


def player_rows(
    conn: psycopg.Connection, view: str, team_id: int, game_ids: list[str]
) -> list[Row]:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            f"""
            SELECT v.*, p.name
            FROM features.{view} v JOIN hockey.players p USING (player_id)
            WHERE v.team_id = %(t)s AND v.game_id = ANY(%(g)s)
            ORDER BY v.game_date DESC, v.game_id DESC
            """,
            {"t": team_id, "g": game_ids},
        ).fetchall()


def by_player(rows: list[Row]) -> dict[int, list[Row]]:
    out: dict[int, list[Row]] = defaultdict(list)
    for r in rows:
        out[r["player_id"]].append(r)
    return out


def likely_starter(goalie_rows: list[Row], recent_game_ids: list[str]) -> Row | None:
    """Most starts in the team's last few games; ties go to whoever started most recently."""
    starts = [r for r in goalie_rows if r["is_starter"] and r["game_id"] in set(recent_game_ids)]
    if not starts:
        return None
    order = {g: i for i, g in enumerate(recent_game_ids)}  # 0 = most recent
    count: dict[int, int] = defaultdict(int)
    latest: dict[int, int] = {}
    names: dict[int, str] = {}
    for r in starts:
        pid = r["player_id"]
        count[pid] += 1
        latest[pid] = min(latest.get(pid, 99), order[r["game_id"]])
        names[pid] = r["name"]
    pid = min(count, key=lambda p: (-count[p], latest[p]))
    return {
        "player_id": pid,
        "name": names[pid],
        "starts": count[pid],
        "of_last": len(recent_game_ids),
        "started_last_game": latest[pid] == 0,
    }


def player_form(
    conn: psycopg.Connection,
    team_id: int,
    season: str,
    last: int | None = None,
    as_of: dt.date | None = None,
) -> Row | None:
    season_rows = team_games(conn, team_id, season, as_of)
    if not season_rows:
        return None
    used = window(season_rows, last)
    partial = len(used) < len(season_rows)
    season_ids = [r["game_id"] for r in season_rows]
    window_ids = {r["game_id"] for r in used}

    def lines(view: str, summarize) -> list[Row]:
        rows = player_rows(conn, view, team_id, season_ids)
        out = []
        for pid, games in by_player(rows).items():
            recent = [g for g in games if g["game_id"] in window_ids]
            line = {
                "player_id": pid,
                "name": games[0]["name"],
                "window": summarize(recent),
                "season": summarize(games) if partial else None,
            }
            if view == "skater_games":
                line["position"] = games[0]["position"]
            out.append(line)
        return out

    skaters = sorted(
        lines("skater_games", summarize_skater),
        key=lambda s: (-s["window"]["points"], -s["window"]["goals"], s["name"]),
    )
    goalie_lines = lines("goalie_games", summarize_goalie)
    goalies = sorted(goalie_lines, key=lambda g: (-g["window"]["toi_seconds"], g["name"]))
    recent_ids = season_ids[:LIKELY_STARTER_WINDOW]
    return {
        "games_played": len(season_rows),
        "last": last,
        "games_used": len(used),
        "skaters": skaters,
        "goalies": goalies,
        "likely_starter": likely_starter(
            player_rows(conn, "goalie_games", team_id, recent_ids), recent_ids
        ),
    }
