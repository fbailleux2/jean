"""ProcessTracer — associates SessionTraces with ProcessDefinitions.

When a session's process_context matches a declared ProcessDefinition,
the tracer enriches pattern detection by aligning observed event sequences
with declared process steps.

The output is a mapping: session_id → ProcessDefinition (matched) or None.
"""

from __future__ import annotations

import structlog

from jean.models import ProcessDefinition, SessionTrace
from jean.process_mapper.store import ProcessStore

log = structlog.get_logger()


class ProcessTracer:
    """Matches SessionTraces to their ProcessDefinition.

    Args:
        store: The ProcessStore holding declared processes.
    """

    def __init__(self, store: ProcessStore) -> None:
        self._store = store

    def match(self, traces: list[SessionTrace]) -> dict[str, ProcessDefinition | None]:
        """Return a mapping of session_id → matched ProcessDefinition (or None).

        Matching is done on process_context.
        """
        result: dict[str, ProcessDefinition | None] = {}
        for trace in traces:
            matched = self._store.get_by_context(trace.process_context)
            result[trace.session_id] = matched
            if matched:
                log.debug(
                    "Session matched to process",
                    session_id=trace.session_id,
                    process=matched.name,
                )
            else:
                log.debug(
                    "No process definition for context",
                    session_id=trace.session_id,
                    context=trace.process_context,
                )
        return result
