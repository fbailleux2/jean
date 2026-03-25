"""In-memory store for ProcessDefinitions.

Provides CRUD operations for process definitions.
In a future version this will back onto PostgreSQL.
"""

from __future__ import annotations

import structlog

from jean.models import ProcessDefinition

log = structlog.get_logger()


class ProcessStore:
    """In-memory store for ProcessDefinitions."""

    def __init__(self) -> None:
        self._processes: dict[str, ProcessDefinition] = {}

    def save(self, process: ProcessDefinition) -> None:
        self._processes[process.id] = process
        log.info("ProcessDefinition saved", id=process.id, name=process.name, version=process.version)

    def get(self, process_id: str) -> ProcessDefinition | None:
        return self._processes.get(process_id)

    def get_by_context(self, process_context: str) -> ProcessDefinition | None:
        """Return the first ProcessDefinition matching a process_context."""
        for p in self._processes.values():
            if p.process_context == process_context:
                return p
        return None

    def list_all(self) -> list[ProcessDefinition]:
        return list(self._processes.values())

    def delete(self, process_id: str) -> bool:
        if process_id in self._processes:
            del self._processes[process_id]
            return True
        return False

    @property
    def count(self) -> int:
        return len(self._processes)
