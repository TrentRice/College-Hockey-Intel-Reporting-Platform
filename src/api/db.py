"""Database access for the API: a connection pool and small query helpers.

Connections are read-only (default_transaction_read_only) and use the `hockey` schema, so
an endpoint can't change data even by mistake.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import psycopg
from fastapi import HTTPException, Request
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

CONNECTION_OPTIONS = "-c search_path=hockey -c default_transaction_read_only=on"


def make_pool(database_url: str) -> ConnectionPool:
    return ConnectionPool(
        database_url,
        min_size=1,
        max_size=5,
        open=False,
        kwargs={"row_factory": dict_row, "options": CONNECTION_OPTIONS, "autocommit": True},
    )


def get_conn(request: Request) -> Iterator[psycopg.Connection]:
    """FastAPI dependency: one pooled connection per request."""
    with request.app.state.pool.connection() as conn:
        yield conn


def fetch_all(
    conn: psycopg.Connection, sql: str, params: dict | None = None
) -> list[dict[str, Any]]:
    return conn.execute(sql, params or {}).fetchall()


def fetch_one(
    conn: psycopg.Connection, sql: str, params: dict | None = None
) -> dict[str, Any] | None:
    return conn.execute(sql, params or {}).fetchone()


def resolve_season(conn: psycopg.Connection, season: str | None) -> str:
    """None -> the latest season; an unknown season -> 404."""
    if season is None:
        row = fetch_one(conn, "SELECT MAX(season) AS season FROM seasons")
        if row is None or row["season"] is None:
            raise HTTPException(404, "No seasons loaded")
        return row["season"]
    if fetch_one(conn, "SELECT 1 FROM seasons WHERE season = %(s)s", {"s": season}) is None:
        raise HTTPException(404, f"Season {season} not found")
    return season


def require_team(conn: psycopg.Connection, team_id: int) -> dict[str, Any]:
    row = fetch_one(conn, "SELECT team_id, name FROM teams WHERE team_id = %(t)s", {"t": team_id})
    if row is None:
        raise HTTPException(404, f"Team {team_id} not found")
    return row
