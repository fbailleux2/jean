"""ObservationStore — pluggable persistence for jean-validator.

Two implementations:
- InMemoryObservationStore: dict-backed, default in tests
- SQLiteObservationStore:   aiosqlite-backed, production

Selected by JEAN_OBS_STORE_PATH env var:
  unset  → InMemoryObservationStore
  set    → SQLiteObservationStore(path)
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path

import aiosqlite

from jean.models import FieldObservation

_STORE_PATH_ENV = "JEAN_OBS_STORE_PATH"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS observations (
    id      TEXT PRIMARY KEY,
    state   TEXT NOT NULL,
    data    TEXT NOT NULL
)
"""


class ObservationStore(ABC):
    """Abstract interface for observation persistence."""

    @abstractmethod
    async def save(self, obs: FieldObservation) -> None: ...

    @abstractmethod
    async def get(self, obs_id: str) -> FieldObservation | None: ...

    @abstractmethod
    async def list(self, state: str | None = None) -> list[FieldObservation]: ...

    @abstractmethod
    async def update(self, obs: FieldObservation) -> None: ...

    @abstractmethod
    def clear(self) -> None:
        """Remove all observations (used in tests)."""
        ...

    async def open(self) -> None:
        """Called at startup to open connections. No-op for in-memory."""

    async def close(self) -> None:
        """Called at shutdown to close connections. No-op for in-memory."""


class InMemoryObservationStore(ObservationStore):
    """Dict-backed store — default for tests and dev."""

    def __init__(self) -> None:
        self._data: dict[str, FieldObservation] = {}

    async def save(self, obs: FieldObservation) -> None:
        self._data[obs.id] = obs

    async def get(self, obs_id: str) -> FieldObservation | None:
        return self._data.get(obs_id)

    async def list(self, state: str | None = None) -> list[FieldObservation]:
        items = list(self._data.values())
        if state:
            items = [o for o in items if o.state.value == state]
        return items

    async def update(self, obs: FieldObservation) -> None:
        self._data[obs.id] = obs

    def clear(self) -> None:
        self._data.clear()

    # Expose raw dict for legacy test compatibility
    def raw(self) -> dict[str, FieldObservation]:
        return self._data


class SQLiteObservationStore(ObservationStore):
    """aiosqlite-backed store for production."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._conn: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self._conn = await aiosqlite.connect(self.db_path)
        await self._conn.execute(_CREATE_TABLE)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    def _assert_open(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("SQLiteObservationStore is not open — call open() first")
        return self._conn

    async def save(self, obs: FieldObservation) -> None:
        conn = self._assert_open()
        await conn.execute(
            "INSERT OR REPLACE INTO observations (id, state, data) VALUES (?, ?, ?)",
            (obs.id, obs.state.value, obs.model_dump_json()),
        )
        await conn.commit()

    async def get(self, obs_id: str) -> FieldObservation | None:
        conn = self._assert_open()
        async with conn.execute(
            "SELECT data FROM observations WHERE id = ?", (obs_id,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return FieldObservation.model_validate_json(row[0])

    async def list(self, state: str | None = None) -> list[FieldObservation]:
        conn = self._assert_open()
        if state:
            async with conn.execute(
                "SELECT data FROM observations WHERE state = ? ORDER BY rowid ASC",
                (state,),
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with conn.execute(
                "SELECT data FROM observations ORDER BY rowid ASC"
            ) as cur:
                rows = await cur.fetchall()
        return [FieldObservation.model_validate_json(r[0]) for r in rows]

    async def update(self, obs: FieldObservation) -> None:
        conn = self._assert_open()
        await conn.execute(
            "UPDATE observations SET state = ?, data = ? WHERE id = ?",
            (obs.state.value, obs.model_dump_json(), obs.id),
        )
        await conn.commit()

    def clear(self) -> None:
        raise NotImplementedError(
            "clear() is not supported on SQLiteObservationStore — use a temp path in tests"
        )


def make_obs_store() -> ObservationStore:
    """Factory: returns SQLiteObservationStore or InMemoryObservationStore."""
    path = os.environ.get(_STORE_PATH_ENV)
    if path:
        return SQLiteObservationStore(path)
    return InMemoryObservationStore()
