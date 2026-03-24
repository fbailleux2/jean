"""AbstractStore — pluggable persistence for jean-aggregator.

Two implementations:
- InMemoryStore  : default for dev/tests (no dependencies)
- PostgresStore  : production (requires asyncpg + PostgreSQL)

Select via env var:
    JEAN_STORE=memory   → InMemoryStore (default)
    JEAN_STORE=postgres → PostgresStore (requires JEAN_PG_DSN)

Schema (PostgreSQL):

    CREATE TABLE jean_events (
        id              TEXT PRIMARY KEY,
        type            TEXT NOT NULL,
        app             TEXT NOT NULL,
        timestamp       TIMESTAMPTZ NOT NULL,
        session_id      TEXT NOT NULL,
        process_context TEXT NOT NULL,
        workstation_id  TEXT NOT NULL,
        payload         JSONB NOT NULL,
        schema_version  TEXT NOT NULL
    );

    CREATE TABLE jean_traces (
        session_id      TEXT PRIMARY KEY,
        workstation_id  TEXT NOT NULL,
        process_context TEXT NOT NULL,
        started_at      TIMESTAMPTZ NOT NULL,
        ended_at        TIMESTAMPTZ,
        events          JSONB NOT NULL,
        schema_version  TEXT NOT NULL
    );
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

import structlog

from jean.models import BusinessEvent, EventType, SessionTrace

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------


class AbstractStore(ABC):
    """Persistence interface for jean-aggregator."""

    @abstractmethod
    async def save_events(self, events: list[BusinessEvent]) -> None:
        ...

    @abstractmethod
    async def save_traces(self, traces: list[SessionTrace]) -> None:
        ...

    @abstractmethod
    async def load_traces(self, process_context: str | None = None) -> list[SessionTrace]:
        ...

    @abstractmethod
    async def close(self) -> None:
        ...


# ---------------------------------------------------------------------------
# InMemoryStore
# ---------------------------------------------------------------------------


class InMemoryStore(AbstractStore):
    """Thread-safe in-memory store for development and tests."""

    def __init__(self) -> None:
        self._events: list[BusinessEvent] = []
        self._traces: dict[str, SessionTrace] = {}

    async def save_events(self, events: list[BusinessEvent]) -> None:
        self._events.extend(events)

    async def save_traces(self, traces: list[SessionTrace]) -> None:
        for t in traces:
            self._traces[t.session_id] = t

    async def load_traces(self, process_context: str | None = None) -> list[SessionTrace]:
        traces = list(self._traces.values())
        if process_context:
            traces = [t for t in traces if t.process_context == process_context]
        return traces

    async def close(self) -> None:
        pass

    @property
    def event_count(self) -> int:
        return len(self._events)


# ---------------------------------------------------------------------------
# PostgresStore
# ---------------------------------------------------------------------------

_CREATE_EVENTS = """
CREATE TABLE IF NOT EXISTS jean_events (
    id              TEXT PRIMARY KEY,
    type            TEXT NOT NULL,
    app             TEXT NOT NULL,
    timestamp       TIMESTAMPTZ NOT NULL,
    session_id      TEXT NOT NULL,
    process_context TEXT NOT NULL,
    workstation_id  TEXT NOT NULL,
    payload         JSONB NOT NULL,
    schema_version  TEXT NOT NULL
)
"""

_CREATE_TRACES = """
CREATE TABLE IF NOT EXISTS jean_traces (
    session_id      TEXT PRIMARY KEY,
    workstation_id  TEXT NOT NULL,
    process_context TEXT NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL,
    ended_at        TIMESTAMPTZ,
    events          JSONB NOT NULL,
    schema_version  TEXT NOT NULL
)
"""


class PostgresStore(AbstractStore):
    """PostgreSQL-backed store using asyncpg.

    Usage::

        store = PostgresStore(dsn="postgresql://user:pw@localhost/jean")
        await store.connect()
        ...
        await store.close()
    """

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self._pool: Any = None  # asyncpg.Pool

    async def connect(self) -> None:
        import asyncpg  # type: ignore[import]

        self._pool = await asyncpg.create_pool(self.dsn)
        async with self._pool.acquire() as conn:
            await conn.execute(_CREATE_EVENTS)
            await conn.execute(_CREATE_TRACES)
        log.info("PostgresStore connected", dsn=self.dsn.split("@")[-1])

    async def save_events(self, events: list[BusinessEvent]) -> None:
        if not events or self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.executemany(
                """INSERT INTO jean_events
                   (id, type, app, timestamp, session_id, process_context,
                    workstation_id, payload, schema_version)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9)
                   ON CONFLICT (id) DO NOTHING""",
                [
                    (
                        e.id,
                        e.type.value,
                        e.app,
                        e.timestamp,
                        e.session_id,
                        e.process_context,
                        e.workstation_id,
                        json.dumps(e.payload),
                        e.schema_version,
                    )
                    for e in events
                ],
            )

    async def save_traces(self, traces: list[SessionTrace]) -> None:
        if not traces or self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.executemany(
                """INSERT INTO jean_traces
                   (session_id, workstation_id, process_context,
                    started_at, ended_at, events, schema_version)
                   VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7)
                   ON CONFLICT (session_id) DO UPDATE SET
                     events = EXCLUDED.events,
                     ended_at = EXCLUDED.ended_at""",
                [
                    (
                        t.session_id,
                        t.workstation_id,
                        t.process_context,
                        t.started_at,
                        t.ended_at,
                        json.dumps([e.model_dump(mode="json") for e in t.events]),
                        t.schema_version,
                    )
                    for t in traces
                ],
            )

    async def load_traces(self, process_context: str | None = None) -> list[SessionTrace]:
        if self._pool is None:
            return []
        query = "SELECT session_id, workstation_id, process_context, started_at, ended_at, events, schema_version FROM jean_traces"
        params: list[Any] = []
        if process_context:
            query += " WHERE process_context = $1"
            params.append(process_context)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        traces: list[SessionTrace] = []
        for row in rows:
            raw_events = json.loads(row["events"])
            events = [BusinessEvent.model_validate(e) for e in raw_events]
            traces.append(
                SessionTrace(
                    session_id=row["session_id"],
                    workstation_id=row["workstation_id"],
                    process_context=row["process_context"],
                    started_at=row["started_at"],
                    ended_at=row["ended_at"],
                    events=events,
                    schema_version=row["schema_version"],
                )
            )
        return traces

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_store() -> AbstractStore:
    """Build the configured store from environment variables."""
    store_type = os.environ.get("JEAN_STORE", "memory").lower()
    if store_type == "postgres":
        dsn = os.environ.get("JEAN_PG_DSN", "postgresql://jean:jean@localhost/jean")
        return PostgresStore(dsn)
    return InMemoryStore()
