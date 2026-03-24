"""API key authentication for Jean services.

Usage in FastAPI routes::

    from jean.auth import require_auth

    @app.post("/ingest")
    async def ingest(events: list[BusinessEvent], _: None = Depends(require_auth)):
        ...

Configuration:
    JEAN_API_KEY — expected API key value.
                   If unset, authentication is disabled (all requests pass).
                   Set to a strong random value in production.

Header: X-API-Key

Error responses:
    401 Unauthorized — header missing
    403 Forbidden    — header present but value incorrect
"""

from __future__ import annotations

import os

from fastapi import Header, HTTPException

_ENV_VAR = "JEAN_API_KEY"


async def require_auth(x_api_key: str | None = Header(default=None)) -> None:
    """FastAPI dependency — validates the X-API-Key header.

    No-op when JEAN_API_KEY env var is unset (auth disabled).
    """
    expected = os.environ.get(_ENV_VAR)
    if not expected:
        return  # auth disabled

    if x_api_key is None:
        raise HTTPException(status_code=401, detail="X-API-Key header is required")

    if x_api_key != expected:
        raise HTTPException(status_code=403, detail="Invalid API key")
