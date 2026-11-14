"""Talks to the CHIRP API. The dashboard never touches the database directly."""

from __future__ import annotations

import datetime as dt
import os
from typing import Any

import requests

from config.settings import settings

API_URL = os.environ.get("CHIRP_API_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = 15


class ApiError(Exception):
    pass


def get(path: str, **params: Any) -> Any:
    params = {k: v for k, v in params.items() if v is not None}
    for k, v in params.items():
        if isinstance(v, dt.date):
            params[k] = v.isoformat()
    try:
        r = requests.get(
            f"{API_URL}{path}",
            params=params,
            headers={"X-API-Key": settings.api_key},
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        raise ApiError(
            f"Can't reach the API at {API_URL} ({type(e).__name__}). Is it running? Try `make up`."
        ) from e
    if r.status_code == 401:
        raise ApiError("The API rejected the key. Check API_KEY in .env.")
    if r.status_code == 404:
        return None
    if not r.ok:
        raise ApiError(f"API error {r.status_code} on {path}: {r.text[:200]}")
    return r.json()


def health() -> dict:
    return get("/health")


def seasons() -> list[dict]:
    return get("/v1/seasons")


def teams(season: str) -> list[dict]:
    return get("/v1/teams", season=season, d1_only=True)


def schedule(team_id: int, season: str) -> list[dict]:
    return get(f"/v1/teams/{team_id}/games", season=season) or []


def team_form(team_id: int, season: str, last: int | None, as_of: dt.date | None) -> dict | None:
    return get(f"/v1/teams/{team_id}/form", season=season, last=last, as_of=as_of)


def player_form(team_id: int, season: str, last: int | None, as_of: dt.date | None) -> dict | None:
    return get(f"/v1/teams/{team_id}/player-form", season=season, last=last, as_of=as_of)
