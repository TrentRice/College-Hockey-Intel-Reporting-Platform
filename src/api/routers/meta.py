from __future__ import annotations

from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends

from src.api.db import fetch_all, fetch_one, get_conn
from src.api.models import Health, Season

health_router = APIRouter(tags=["meta"])

Conn = Annotated[psycopg.Connection, Depends(get_conn)]
router = APIRouter(tags=["meta"])


@health_router.get(
    "/health", response_model=Health, summary="Is the API up and the database reachable?"
)
def health(conn: Conn) -> dict:
    out = {"status": "ok", "database": "ok", "data_as_of": None, "last_refresh": None}
    if fetch_one(conn, "SELECT to_regclass('ops.pipeline_runs') AS t")["t"] is None:
        return out  # no refresh has ever run against this database
    last = fetch_one(
        conn,
        """
        SELECT started_at, finished_at, status, trigger, failed_step,
               CASE WHEN status = 'success' THEN played_after - played_before END AS new_games
        FROM ops.pipeline_runs ORDER BY run_id DESC LIMIT 1
        """,
    )
    ok = fetch_one(
        conn,
        "SELECT MAX(finished_at) AS t FROM ops.pipeline_runs WHERE status = 'success'",
    )
    out["last_refresh"] = last
    out["data_as_of"] = ok["t"] if ok else None
    return out


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
