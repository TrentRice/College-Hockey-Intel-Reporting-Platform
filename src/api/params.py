"""Parameters shared by several endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import psycopg
from fastapi import Depends, Path, Query

from src.api.db import get_conn
from src.api.models import SEASON_PATTERN

Conn = Annotated[psycopg.Connection, Depends(get_conn)]
TeamId = Annotated[int, Path(description="CHIRP team id (from GET /v1/teams)", ge=1)]
PlayerId = Annotated[int, Path(description="CHIRP player id (from GET /v1/players)", ge=1)]
SeasonQ = Annotated[
    str | None,
    Query(pattern=SEASON_PATTERN, description="e.g. 2026-27. Defaults to the latest season."),
]
ConferenceQ = Annotated[str | None, Query(description="e.g. Hockey East")]

MAX_LIMIT = 200


@dataclass
class Paging:
    limit: int
    offset: int


def paging(
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT, description="Rows per page")] = 50,
    offset: Annotated[int, Query(ge=0, description="Rows to skip")] = 0,
) -> Paging:
    return Paging(limit, offset)


PagingQ = Annotated[Paging, Depends(paging)]


def page(rows: list[dict], p: Paging) -> dict:
    """Rows carrying a `total` column (COUNT(*) OVER ()) -> a Page response."""
    total = rows[0]["total"] if rows else 0
    for r in rows:
        del r["total"]
    return {"items": rows, "total": total, "limit": p.limit, "offset": p.offset}


def mmss(seconds: int | None) -> str | None:
    return None if seconds is None else f"{seconds // 60}:{seconds % 60:02d}"


def team_ref(team_id: int | None, name: str | None) -> dict | None:
    return {"team_id": team_id, "name": name} if team_id is not None else None


def player_ref(player_id: int | None, name: str | None) -> dict | None:
    return {"player_id": player_id, "name": name} if player_id is not None else None


def result(goals_for: int | None, goals_against: int | None, is_played: bool) -> str | None:
    if not is_played or goals_for is None or goals_against is None:
        return None
    return "W" if goals_for > goals_against else "L" if goals_for < goals_against else "T"
