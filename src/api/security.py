"""API key check. When API_KEY is set, every /v1 request needs a matching X-API-Key header.

This is the second line of defence. The first is that the API only listens on 127.0.0.1, so
nothing off this machine can reach it (see docs/api.md). CHN's terms allow personal use
only, so the data must not be served to anyone else.
"""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(
    name="X-API-Key", auto_error=False, description="Your API_KEY from .env"
)


def require_api_key(request: Request, key: str | None = Security(api_key_header)) -> None:
    expected: str = request.app.state.api_key
    if not expected:
        return
    if key is None or not secrets.compare_digest(key.encode(), expected.encode()):
        raise HTTPException(
            401, "Missing or wrong X-API-Key header", headers={"WWW-Authenticate": "APIKey"}
        )
