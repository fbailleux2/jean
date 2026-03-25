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


FRICTION_THRESHOLD = 3  # back-and-forth count before signalling friction


class AppTransitionCapture(BaseCapture):
    """Captures application focus changes.

    macOS implementation uses NSWorkspace notifications.
    Other platforms yield nothing and log a warning.

    Privacy guarantee: only the application name is captured, never window
    title or document name.

    Friction detection: when the same (from_app → to_app) pair is repeated
    more than FRICTION_THRESHOLD times in a session, a TOOL_SWITCH event is
    emitted to signal potential process friction.
    """

    def __init__(self, workstation_id: str, process_context: str, session_id: str) -> None:
        super().__init__(workstation_id, process_context, session_id)
        self._transition_counts: dict[tuple[str, str], int] = {}
        self._last_app: str | None = None

    def _track_transition(self, to_app: str) -> BusinessEvent | None:
        """Track the (from → to) pair and return a TOOL_SWITCH event if friction threshold exceeded."""
        from jean.models import ToolTransition

        if self._last_app is None or self._last_app == to_app:
            self._last_app = to_app
            return None

        pair = (self._last_app, to_app)
        self._transition_counts[pair] = self._transition_counts.get(pair, 0) + 1
        count = self._transition_counts[pair]
        self._last_app = to_app

        if count == FRICTION_THRESHOLD:
            transition = ToolTransition(
                from_app=pair[0],
                to_app=pair[1],
                transition_count=count,
                is_cross_app_paste=False,
            )
            return self._make_event(
                EventType.TOOL_SWITCH,
                to_app,
                transition.model_dump(),
            )
        return None

    def _import_macos(self):  # type: ignore[return]
        """Import the macOS capture module. Separated for testability."""
        from jean.agent._macos import observe_app_transitions  # type: ignore[import]
        return observe_app_transitions

    async def events(self) -> AsyncGenerator[BusinessEvent, None]:  # type: ignore[override]
        sys_platform = platform.system()

        if sys_platform == "Darwin":
            try:
                observe_app_transitions = self._import_macos()
                async for app_name, event_type in observe_app_transitions():
                    yield self._make_event(event_type, app_name)
                    friction_event = self._track_transition(app_name)
                    if friction_event:
                        yield friction_event
            except ImportError:
                logger.warning(
                    "pyobjc not installed — AppTransitionCapture unavailable. "
                    "Install with: uv sync --extra macos"
                )

        elif sys_platform == "Linux":
            try:
                from jean.agent._linux import observe_app_transitions as _linux_obs
                async for app_name, event_type in _linux_obs():
                    yield self._make_event(event_type, app_name)
                    friction_event = self._track_transition(app_name)
                    if friction_event:
                        yield friction_event
            except ImportError as exc:
                logger.warning("Linux capture unavailable: %s", exc)

        elif sys_platform == "Windows":
            try:
                from jean.agent._windows import observe_app_transitions as _win_obs
                async for app_name, event_type in _win_obs():
                    yield self._make_event(event_type, app_name)
                    friction_event = self._track_transition(app_name)
                    if friction_event:
                        yield friction_event
            except (ImportError, OSError) as exc:
                logger.warning("Windows capture unavailable: %s", exc)

        else:
            logger.warning(
                "AppTransitionCapture: unsupported platform %s — no events", sys_platform
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
