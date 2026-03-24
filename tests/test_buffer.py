"""Tests for LocalBuffer (jean-agent offline buffer)."""

from __future__ import annotations

import pytest

from jean.agent.buffer import LocalBuffer
from jean.models import BusinessEvent, EventType


def _make_event(session_id: str = "sess-1", app: str = "Excel") -> BusinessEvent:
    return BusinessEvent(
        type=EventType.SAVE,
        app=app,
        process_context="invoice-exception",
        session_id=session_id,
        workstation_id="ws-test",
    )


@pytest.mark.asyncio
async def test_push_and_drain(tmp_path):
    db = tmp_path / "test.db"
    async with LocalBuffer(db) as buf:
        e1 = _make_event()
        e2 = _make_event(app="SAP")
        await buf.push(e1)
        await buf.push(e2)

        pending = await buf.drain()
        assert len(pending) == 2
        assert {e.id for e in pending} == {e1.id, e2.id}


@pytest.mark.asyncio
async def test_mark_sent(tmp_path):
    db = tmp_path / "test.db"
    async with LocalBuffer(db) as buf:
        e1 = _make_event()
        await buf.push(e1)

        assert await buf.pending_count() == 1
        await buf.mark_sent([e1.id])
        assert await buf.pending_count() == 0


@pytest.mark.asyncio
async def test_drain_empty_returns_empty(tmp_path):
    db = tmp_path / "test.db"
    async with LocalBuffer(db) as buf:
        pending = await buf.drain()
        assert pending == []


@pytest.mark.asyncio
async def test_duplicate_push_ignored(tmp_path):
    db = tmp_path / "test.db"
    async with LocalBuffer(db) as buf:
        e = _make_event()
        await buf.push(e)
        await buf.push(e)  # same ID — should be ignored
        assert await buf.pending_count() == 1


@pytest.mark.asyncio
async def test_drain_respects_limit(tmp_path):
    db = tmp_path / "test.db"
    async with LocalBuffer(db) as buf:
        for _ in range(10):
            await buf.push(_make_event())
        batch = await buf.drain(limit=3)
        assert len(batch) == 3
