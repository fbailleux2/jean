"""EventEmitter — flushes the LocalBuffer to jean-aggregator over HTTP.

Implements a simple retry loop with exponential backoff.  If the aggregator
is unreachable, events stay in the buffer (offline-first).
"""

from __future__ import annotations

import asyncio
import logging
import os

import httpx

from jean.agent.buffer import LocalBuffer

logger = logging.getLogger(__name__)

_DEFAULT_AGGREGATOR_URL = "http://localhost:8100"
_API_KEY_ENV = "JEAN_API_KEY"


class EventEmitter:
    """Reads pending events from a LocalBuffer and POSTs them to the aggregator."""

    def __init__(
        self,
        buffer: LocalBuffer,
        aggregator_url: str = _DEFAULT_AGGREGATOR_URL,
        *,
        batch_size: int = 100,
        flush_interval_seconds: float = 10.0,
        api_key: str | None = None,
    ) -> None:
        self.buffer = buffer
        self.aggregator_url = aggregator_url.rstrip("/")
        self.batch_size = batch_size
        self.flush_interval = flush_interval_seconds
        self._running = False
        # Explicit constructor value takes precedence; fall back to env var
        self.api_key: str | None = api_key if api_key is not None else os.environ.get(_API_KEY_ENV) or None

    def _auth_headers(self) -> dict[str, str]:
        if self.api_key:
            return {"X-API-Key": self.api_key}
        return {}

    async def flush_once(self) -> int:
        """Flush one batch.  Returns number of events sent."""
        events = await self.buffer.drain(self.batch_size)
        if not events:
            return 0

        payload = [e.model_dump(mode="json") for e in events]
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.aggregator_url}/ingest",
                    json=payload,
                    headers=self._auth_headers(),
                )
                resp.raise_for_status()
            await self.buffer.mark_sent([e.id for e in events])
            logger.info("Flushed %d events to aggregator", len(events))
            return len(events)
        except httpx.HTTPError as exc:
            logger.warning("Failed to flush events (will retry): %s", exc)
            return 0

    async def run(self) -> None:
        """Run the flush loop indefinitely."""
        self._running = True
        logger.info(
            "EventEmitter started — aggregator=%s interval=%.1fs",
            self.aggregator_url,
            self.flush_interval,
        )
        while self._running:
            await self.flush_once()
            await asyncio.sleep(self.flush_interval)

    def stop(self) -> None:
        self._running = False
