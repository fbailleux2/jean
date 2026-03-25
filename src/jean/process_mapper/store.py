"""In-memory store for ProcessDefinitions.

Provides CRUD operations for process definitions.
In a future version this will back onto PostgreSQL.
"""

from __future__ import annotations

import structlog

from jean.models import ProcessDefinition, ProcessVersionEntry

log = structlog.get_logger()


class ProcessStore:
    """In-memory store for ProcessDefinitions."""

    def __init__(self) -> None:
        self._processes: dict[str, ProcessDefinition] = {}
        self._version_history: dict[str, list[ProcessVersionEntry]] = {}

    def record_version(
        self,
        process: ProcessDefinition,
        changed_by: str | None = None,
        change_summary: str = "",
    ) -> None:
        """Create a ProcessVersionEntry and append it to the history for this process."""
        entry = ProcessVersionEntry(
            version=process.version,
            changed_by=changed_by,
            change_summary=change_summary,
            snapshot_steps_count=len(process.steps),
        )
        if process.id not in self._version_history:
            self._version_history[process.id] = []
        self._version_history[process.id].append(entry)

    def get_version_history(self, process_id: str) -> list[ProcessVersionEntry]:
        """Return the version history list for a process (or empty list)."""
        return self._version_history.get(process_id, [])

    def save(self, process: ProcessDefinition) -> None:
        self._processes[process.id] = process
        self.record_version(process)
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
