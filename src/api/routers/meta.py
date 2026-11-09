from __future__ import annotations

from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends

from src.api.db import fetch_all, get_conn
from src.api.models import Health, Season

health_router = APIRouter(tags=["meta"])

Conn = Annotated[psycopg.Connection, Depends(get_conn)]
router = APIRouter(tags=["meta"])


@health_router.get(
    "/health", response_model=Health, summary="Is the API up and the database reachable?"
)
def health(conn: Conn) -> Health:
    conn.execute("SELECT 1")
    return Health(status="ok", database="ok")


@router.get("/seasons", response_model=list[Season], summary="Seasons in the database")
def seasons(conn: Conn) -> list[dict]:
    return fetch_all(
        conn,
        """
        SELECT s.season, s.start_year,
               COUNT(g.game_id)::int                  AS games,
               COUNT(g.game_id) FILTER (WHERE g.is_played)::int AS played
        FROM seasons s LEFT JOIN games g USING (season)
        GROUP BY s.season, s.start_year
        ORDER BY s.season
        """,
    )
