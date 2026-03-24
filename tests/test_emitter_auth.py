"""Tests for EventEmitter API key authentication (ISC-5, ISC-6, ISC-7)."""

from __future__ import annotations

import httpx
import pytest
import respx

from jean.agent.emitter import EventEmitter
from jean.agent.buffer import LocalBuffer
from jean.models import BusinessEvent, EventType
from datetime import datetime, timezone


def _make_event(n: int = 1) -> BusinessEvent:
    return BusinessEvent(
        type=EventType.APP_FOCUS,
        app="TestApp",
        process_context="test",
        session_id="sess-1",
        workstation_id="ws-1",
        timestamp=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# ISC-5: flush_once() with key sends correct X-API-Key header
# ---------------------------------------------------------------------------


async def test_flush_sends_api_key_header(tmp_path):
    buf_path = str(tmp_path / "events.db")
    async with LocalBuffer(db_path=buf_path) as buf:
        await buf.push(_make_event())
        emitter = EventEmitter(buf, aggregator_url="http://agg-test:8100", api_key="my-secret")

        with respx.mock:
            route = respx.post("http://agg-test:8100/ingest").mock(
                return_value=httpx.Response(202, json={"accepted": 1})
            )
            sent = await emitter.flush_once()

        assert sent == 1
        assert route.calls[0].request.headers.get("x-api-key") == "my-secret"


# ---------------------------------------------------------------------------
# ISC-6: flush_once() without key sends no X-API-Key header
# ---------------------------------------------------------------------------


async def test_flush_no_key_sends_no_header(tmp_path, monkeypatch):
    monkeypatch.delenv("JEAN_API_KEY", raising=False)
    buf_path = str(tmp_path / "events.db")
    async with LocalBuffer(db_path=buf_path) as buf:
        await buf.push(_make_event())
        emitter = EventEmitter(buf, aggregator_url="http://agg-test:8100", api_key=None)

        with respx.mock:
            route = respx.post("http://agg-test:8100/ingest").mock(
                return_value=httpx.Response(202, json={"accepted": 1})
            )
            await emitter.flush_once()

        assert "x-api-key" not in route.calls[0].request.headers


# ---------------------------------------------------------------------------
# ISC-7: 401 from aggregator does not raise — logged as warning, returns 0
# ---------------------------------------------------------------------------


async def test_flush_401_returns_zero(tmp_path):
    buf_path = str(tmp_path / "events.db")
    async with LocalBuffer(db_path=buf_path) as buf:
        await buf.push(_make_event())
        emitter = EventEmitter(buf, aggregator_url="http://agg-test:8100", api_key="wrong")

        with respx.mock:
            respx.post("http://agg-test:8100/ingest").mock(
                return_value=httpx.Response(401, json={"detail": "Unauthorized"})
            )
            sent = await emitter.flush_once()

        assert sent == 0
        # Event must still be pending (not marked sent)
        assert await buf.pending_count() == 1
