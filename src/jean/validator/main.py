"""jean-validator entry point."""

from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run(
        "jean.validator.api:app",
        host="0.0.0.0",
        port=8200,
        reload=False,
        log_level="info",
    )
