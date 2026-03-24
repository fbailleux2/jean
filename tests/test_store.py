"""Tests for AbstractStore implementations."""

from __future__ import annotations

import os

import pytest

from jean.aggregator.store import InMemoryStore, PostgresStore
from jean.models import BusinessEvent, EventType, SessionTrace


def _make_event(session_id: str = "s1", process_context: str = "invoice-exception") -> BusinessEvent:
    return BusinessEvent(
        type=EventType.SAVE,
        app="TestApp",
        process_context=process_context,
        session_id=session_id,
        workstation_id="ws-test",
    )


def _make_trace(session_id: str = "s1", process_context: str = "invoice-exception") -> SessionTrace:
    events = [_make_event(session_id, process_context)]
    return SessionTrace(
        session_id=session_id,
        workstation_id="ws-test",
        process_context=process_context,
        events=events,
    )


# ---------------------------------------------------------------------------
# InMemoryStore
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_in_memory_save_and_load_traces():
    store = InMemoryStore()
    t = _make_trace("s1")
    await store.save_traces([t])
    loaded = await store.load_traces()
    assert len(loaded) == 1
    assert loaded[0].session_id == "s1"
    await store.close()


@pytest.mark.asyncio
async def test_in_memory_save_events_counts():
    store = InMemoryStore()
    e1 = _make_event("s1")
    e2 = _make_event("s2")
    await store.save_events([e1, e2])
    assert store.event_count == 2
    await store.close()


@pytest.mark.asyncio
async def test_in_memory_filter_by_process_context():
    store = InMemoryStore()
    await store.save_traces([_make_trace("s1", "invoice-exception")])
    await store.save_traces([_make_trace("s2", "purchase-order")])
    inv = await store.load_traces(process_context="invoice-exception")
    assert len(inv) == 1
    assert inv[0].session_id == "s1"
    await store.close()


@pytest.mark.asyncio
async def test_in_memory_upsert_trace():
    store = InMemoryStore()
    t = _make_trace("s1")
    await store.save_traces([t])
    await store.save_traces([t])  # same session_id — should upsert, not duplicate
    loaded = await store.load_traces()
    assert len(loaded) == 1
    await store.close()


# ---------------------------------------------------------------------------
# PostgresStore — skipped if JEAN_PG_DSN not set
# ---------------------------------------------------------------------------

_PG_DSN = os.environ.get("JEAN_PG_DSN")
_skip_pg = pytest.mark.skipif(
    not _PG_DSN,
    reason="JEAN_PG_DSN not set — skipping PostgresStore tests",
)


@_skip_pg
@pytest.mark.asyncio
async def test_postgres_store_connect_and_save():
    store = PostgresStore(dsn=_PG_DSN)
    await store.connect()
    t = _make_trace("pg-s1")
    await store.save_traces([t])
    loaded = await store.load_traces()
    assert any(tr.session_id == "pg-s1" for tr in loaded)
    await store.close()
