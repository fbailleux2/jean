"""jean-aggregator entry point."""

from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run(
        "jean.aggregator.api:app",
        host="0.0.0.0",
        port=8100,
        reload=False,
        log_level="info",
    )
