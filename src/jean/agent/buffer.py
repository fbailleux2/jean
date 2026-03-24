"""LocalBuffer — offline-first SQLite buffer for jean-agent.

Events captured on the workstation are stored locally and flushed
asynchronously to jean-aggregator when the network is available.

Design constraints (from VISION.md):
- Offline-first: never lose an event if aggregator is unreachable
- Light footprint: async SQLite via aiosqlite
- No PII stored locally beyond what is captured structurally
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from jean.models import BusinessEvent

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS events (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,
    app         TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    process_context TEXT NOT NULL,
    workstation_id  TEXT NOT NULL,
    payload     TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    sent        INTEGER NOT NULL DEFAULT 0
)
"""


class LocalBuffer:
    """Async SQLite buffer for BusinessEvents.

    Usage::

        async with LocalBuffer("/tmp/jean-agent.db") as buf:
            await buf.push(event)
            pending = await buf.drain()
            await buf.mark_sent([e.id for e in pending])
    """

    def __init__(self, db_path: str | Path = "jean-agent.db") -> None:
        self.db_path = Path(db_path)
        self._conn: aiosqlite.Connection | None = None

    async def __aenter__(self) -> "LocalBuffer":
        self._conn = await aiosqlite.connect(self.db_path)
        await self._conn.execute(_CREATE_TABLE)
        await self._conn.commit()
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    def _assert_open(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("LocalBuffer is not open — use 'async with LocalBuffer(...)'")
        return self._conn

    async def push(self, event: BusinessEvent) -> None:
        """Store one event in the local buffer."""
        conn = self._assert_open()
        await conn.execute(
            """INSERT OR IGNORE INTO events
               (id, type, app, timestamp, session_id, process_context,
                workstation_id, payload, schema_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event.id,
                event.type.value,
                event.app,
                event.timestamp.isoformat(),
                event.session_id,
                event.process_context,
                event.workstation_id,
                json.dumps(event.payload),
                event.schema_version,
            ),
        )
        await conn.commit()
        logger.debug("Buffered event %s (%s)", event.id, event.type)

    async def drain(self, limit: int = 500) -> list[BusinessEvent]:
        """Return up to *limit* unsent events, oldest first."""
        conn = self._assert_open()
        async with conn.execute(
            "SELECT id, type, app, timestamp, session_id, process_context, "
            "workstation_id, payload, schema_version "
            "FROM events WHERE sent = 0 ORDER BY timestamp ASC LIMIT ?",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()

        events: list[BusinessEvent] = []
        for row in rows:
            (
                eid, etype, app, ts, session_id,
                process_context, workstation_id, payload_json, schema_version,
            ) = row
            events.append(
                BusinessEvent(
                    id=eid,
                    type=etype,
                    app=app,
                    timestamp=datetime.fromisoformat(ts),
                    session_id=session_id,
                    process_context=process_context,
                    workstation_id=workstation_id,
                    payload=json.loads(payload_json),
                    schema_version=schema_version,
                )
            )
        return events

    async def mark_sent(self, event_ids: list[str]) -> None:
        """Mark events as successfully delivered to the aggregator."""
        if not event_ids:
            return
        conn = self._assert_open()
        placeholders = ",".join("?" * len(event_ids))
        await conn.execute(
            f"UPDATE events SET sent = 1 WHERE id IN ({placeholders})",
            event_ids,
        )
        await conn.commit()
        logger.debug("Marked %d events as sent", len(event_ids))

    async def pending_count(self) -> int:
        """Return the number of events not yet sent."""
        conn = self._assert_open()
        async with conn.execute("SELECT COUNT(*) FROM events WHERE sent = 0") as cur:
            row = await cur.fetchone()
        return row[0] if row else 0
