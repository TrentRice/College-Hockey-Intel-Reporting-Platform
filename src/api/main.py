"""
CHIRP API: read-only access to the hockey database.

Run locally (database up via `make db-up`):
  make serve        -> http://127.0.0.1:8000/docs

Private by design: it listens on 127.0.0.1 only, and when API_KEY is set every /v1 request
needs a matching X-API-Key header. College Hockey News allows personal, non-commercial use
only, so this must never be exposed to anyone else (see docs/api.md).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from psycopg_pool import PoolTimeout

from config.settings import settings
from src.api.db import make_pool
from src.api.routers import games, leaders, meta, players, teams
from src.api.security import require_api_key

log = logging.getLogger("chirp.api")


def create_app(database_url: str | None = None, api_key: str | None = None) -> FastAPI:
    """App factory; tests pass their own database and key."""
    url = database_url or settings.database_url
    key = settings.api_key if api_key is None else api_key

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        pool = make_pool(url)
        try:
            pool.open(wait=True, timeout=5)
        except PoolTimeout as e:
            raise RuntimeError("Can't reach the database. Is it running? Try `make db-up`.") from e
        app.state.pool = pool
        if not key:
            log.warning(
                "API_KEY is not set: the API is open to anything on this machine. Set it in .env."
            )
        yield
        pool.close()

    app = FastAPI(
        title="CHIRP API",
        summary="College Hockey Intelligence & Reporting Platform",
        description="D-I men's college hockey games, box scores, teams and players. "
        "Read-only. Personal use only: the data comes from College Hockey News.",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.api_key = key

    v1 = [Depends(require_api_key)]
    app.include_router(meta.health_router)
    app.include_router(meta.router, prefix="/v1", dependencies=v1)
    for r in (teams.router, games.router, players.router, leaders.router):
        app.include_router(r, prefix="/v1", dependencies=v1)
    return app


app = create_app()
