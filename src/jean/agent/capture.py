"""Event capture for jean-agent.

Two capture mechanisms:
1. AppTransitionCapture — detects application focus changes (macOS: NSWorkspace)
2. StructuralActionCapture — detects save/submit/export/print via global hotkeys

Both are implemented as async generators that yield BusinessEvents.

Platform support:
- macOS: full support via pyobjc (NSWorkspace, CGEventTap)
- Linux/Windows: stub — ERP events and manual annotations only

Usage constraint: AppTransitionCapture on macOS requires the app to have
Accessibility permissions (System Settings → Privacy & Security → Accessibility).
Document this requirement before any enterprise deployment.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

from jean.models import BusinessEvent, EventType

logger = logging.getLogger(__name__)


class BaseCapture(ABC):
    """Abstract base for all capture mechanisms."""

    def __init__(self, workstation_id: str, process_context: str, session_id: str) -> None:
        self.workstation_id = workstation_id
        self.process_context = process_context
        self.session_id = session_id

    def _make_event(
        self,
        type: EventType,
        app: str,
        payload: dict | None = None,
    ) -> BusinessEvent:
        return BusinessEvent(
            type=type,
            app=app,
            timestamp=datetime.now(timezone.utc),
            process_context=self.process_context,
            session_id=self.session_id,
            payload=payload or {},
            workstation_id=self.workstation_id,
        )

    @abstractmethod
    async def events(self) -> AsyncGenerator[BusinessEvent, None]:
        """Yield events as they occur."""
        ...


class AppTransitionCapture(BaseCapture):
    """Captures application focus changes.

    macOS implementation uses NSWorkspace notifications.
    Other platforms yield nothing and log a warning.

    Privacy guarantee: only the application name is captured, never window
    title or document name.
    """

    async def events(self) -> AsyncGenerator[BusinessEvent, None]:  # type: ignore[override]
        if platform.system() != "Darwin":
            logger.warning(
                "AppTransitionCapture: macOS only — no events on %s", platform.system()
            )
            return

        try:
            from jean.agent._macos import observe_app_transitions  # type: ignore[import]
            async for app_name, event_type in observe_app_transitions():
                yield self._make_event(event_type, app_name)
        except ImportError:
            logger.warning(
                "pyobjc not installed — AppTransitionCapture unavailable. "
                "Install with: uv sync --extra macos"
            )


class StructuralActionCapture(BaseCapture):
    """Detects structural actions: save, submit, export, print.

    This capture is ERP-event driven in the MVP.  Direct hotkey interception
    requires additional OS permissions and is deferred to a later milestone.
    """

    def __init__(
        self,
        workstation_id: str,
        process_context: str,
        session_id: str,
        *,
        event_queue: asyncio.Queue[BusinessEvent] | None = None,
    ) -> None:
        super().__init__(workstation_id, process_context, session_id)
        # External code (e.g. ERP adapter) can push events into this queue
        self.event_queue: asyncio.Queue[BusinessEvent] = event_queue or asyncio.Queue()

    async def events(self) -> AsyncGenerator[BusinessEvent, None]:  # type: ignore[override]
        """Yield events pushed into event_queue by external adapters."""
        while True:
            event = await self.event_queue.get()
            yield event

    async def inject(self, type: EventType, app: str, payload: dict | None = None) -> None:
        """Programmatically inject an event (for ERP adapters and tests)."""
        await self.event_queue.put(self._make_event(type, app, payload))


class AnnotationCapture(BaseCapture):
    """Captures explicit operator annotations entered in the FlowFabric Inbox."""

    def __init__(
        self,
        workstation_id: str,
        process_context: str,
        session_id: str,
        *,
        event_queue: asyncio.Queue[BusinessEvent] | None = None,
    ) -> None:
        super().__init__(workstation_id, process_context, session_id)
        self.event_queue: asyncio.Queue[BusinessEvent] = event_queue or asyncio.Queue()

    async def events(self) -> AsyncGenerator[BusinessEvent, None]:  # type: ignore[override]
        while True:
            event = await self.event_queue.get()
            yield event

    async def annotate(self, text: str, app: str = "FlowFabric-Inbox") -> None:
        """Record an operator annotation. Text is stored as-is — no PII filtering here."""
        await self.event_queue.put(
            self._make_event(EventType.ANNOTATION, app, {"text": text})
        )
