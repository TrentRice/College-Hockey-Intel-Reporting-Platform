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

import psycopg
from fastapi import Depends, FastAPI
from psycopg_pool import PoolTimeout

from config import leagues
from config.settings import settings
from src.api.db import make_pool
from src.api.routers import games, leaders, meta, players, predictions, rankings, teams
from src.api.security import require_api_key
from src.models.win_model import ModelUnavailable, card_path, load_card

log = logging.getLogger("chirp.api")


def create_app(
    database_url: str | None = None,
    api_key: str | None = None,
    database_urls: dict[str, str] | None = None,
) -> FastAPI:
    """App factory. One database per league (config/leagues.py): by default the men's from
    settings and the women's on the same server. Tests pass their own database (men's only)
    or a dict of them, and a key."""
    if database_urls is None:
        base = database_url or leagues.database_url(settings.database_url, leagues.MEN)
        database_urls = {"men": base}
        if database_url is None:  # the normal setup: both leagues
            database_urls["women"] = leagues.database_url(base, leagues.WOMEN)
    key = settings.api_key if api_key is None else api_key

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        pools = {}
        for league, url in database_urls.items():
            if league != "men":  # optional: a server without the women's data still runs
                try:
                    psycopg.connect(url, connect_timeout=5).close()
                except psycopg.OperationalError as e:
                    log.warning("No %s database (%s); ?league=%s will return 503", league, e, league)
                    continue
            pool = make_pool(url)
            try:
                pool.open(wait=True, timeout=30)  # Docker may start the API before Postgres
            except PoolTimeout as e:
                raise RuntimeError("Can't reach the database. Is it running? Try `make db-up`.") from e
            pools[league] = pool
        app.state.pools = pools
        if not key:
            log.warning(
                "API_KEY is not set: the API is open to anything on this machine. Set it in .env."
            )
        yield
        for pool in pools.values():
            pool.close()

    app = FastAPI(
        title="CHIRP API",
        summary="College Hockey Intelligence & Reporting Platform",
        description="D-I men's and women's college hockey games, box scores, teams and players "
        "(?league=men or women; men's by default). Read-only. The data comes from College "
        "Hockey News.",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.api_key = key
    # Each league's frozen win model card; without one, only that league's model endpoints are off
    app.state.win_cards = {}
    for league in database_urls:
        try:
            app.state.win_cards[league] = (load_card(card_path(leagues.get(league))), None)
        except ModelUnavailable as e:
            log.warning("%s win model unavailable: %s", league, e)
            app.state.win_cards[league] = (None, str(e))

    v1 = [Depends(require_api_key)]
    app.include_router(meta.health_router)
    app.include_router(meta.router, prefix="/v1", dependencies=v1)
    for r in (
        teams.router, games.router, games.matchup_router, predictions.router,
        rankings.router, players.router, leaders.router,
    ):
        app.include_router(r, prefix="/v1", dependencies=v1)
    return app


app = create_app()
