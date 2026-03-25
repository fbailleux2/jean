"""Cross-platform clipboard action capture for jean-agent.

Detects Ctrl+C (copy) and Ctrl+V (paste) keyboard shortcuts to track
clipboard usage patterns and cross-application data transfers.

Privacy guarantee:
- NEVER captures clipboard content (text, images, files)
- ONLY captures which application performed copy/paste and whether
  the paste occurred in a different application than the copy (cross-app transfer)

Cross-app paste detection:
  copy in App-A → paste in App-B → emits TOOL_SWITCH event (friction signal)

Requires the [capture] optional extra:
    uv sync --extra capture
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timezone

from jean.models import BusinessEvent, EventType, IrritantSignal, ToolTransition

logger = logging.getLogger(__name__)


class ClipboardCapture:
    """Detects Ctrl+C / Ctrl+V shortcuts and tracks cross-app clipboard transfers.

    Args:
        event_queue:     asyncio.Queue to push BusinessEvents into.
        workstation_id:  Pseudonymous workstation identifier.
        process_context: Business process context label.
        session_id:      Session trace identifier.
        current_app_fn:  Callable returning the currently active app name (injected for testability).
        loop:            asyncio event loop (defaults to running loop).
    """

    def __init__(
        self,
        event_queue: asyncio.Queue[BusinessEvent],
        workstation_id: str,
        process_context: str,
        session_id: str,
        *,
        current_app_fn: Callable[[], str] | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self.event_queue = event_queue
        self.workstation_id = workstation_id
        self.process_context = process_context
        self.session_id = session_id
        self._current_app_fn = current_app_fn or (lambda: "unknown")
        self._loop = loop
        self._listener = None
        self._pressed: set[str] = set()
        self._last_copy_app: str | None = None

    def _make_event(
        self,
        event_type: EventType,
        app: str,
        payload: dict | None = None,
    ) -> BusinessEvent:
        return BusinessEvent(
            type=event_type,
            app=app,
            timestamp=datetime.now(timezone.utc),
            process_context=self.process_context,
            session_id=self.session_id,
            workstation_id=self.workstation_id,
            payload=payload or {},
        )

    def _emit(self, event: BusinessEvent) -> None:
        """Thread-safe event emission to the asyncio queue."""
        loop = self._loop
        if loop and loop.is_running():
            try:
                loop.call_soon_threadsafe(self.event_queue.put_nowait, event)
            except RuntimeError:
                logger.debug("ClipboardCapture: event dropped (loop not running)")
        else:
            logger.debug("ClipboardCapture: no running loop, event dropped")

    def _key_name(self, key: object) -> str | None:
        try:
            c = key.char  # type: ignore[union-attr]
            if c is not None:
                return c.lower()
        except AttributeError:
            pass
        name = str(key).replace("Key.", "").lower()
        for base in ("ctrl", "shift", "alt", "cmd"):
            if name.startswith(base):
                return base
        return name if name else None

    def _on_press(self, key: object) -> None:
        name = self._key_name(key)
        if name:
            self._pressed.add(name)
            self._check_clipboard_shortcuts()

    def _on_release(self, key: object) -> None:
        name = self._key_name(key)
        if name:
            self._pressed.discard(name)

    def _check_clipboard_shortcuts(self) -> None:
        current_app = self._current_app_fn()

        # Ctrl+C — copy
        if {"ctrl", "c"}.issubset(self._pressed):
            self._last_copy_app = current_app
            event = self._make_event(EventType.CLIPBOARD_COPY, current_app)
            self._emit(event)
            logger.debug("Clipboard copy detected in %s", current_app)

        # Ctrl+V — paste
        elif {"ctrl", "v"}.issubset(self._pressed):
            payload: dict = {}
            is_cross_app = (
                self._last_copy_app is not None
                and self._last_copy_app != current_app
            )

            if is_cross_app:
                transition = ToolTransition(
                    from_app=self._last_copy_app,  # type: ignore[arg-type]
                    to_app=current_app,
                    transition_count=1,
                    is_cross_app_paste=True,
                )
                payload = transition.model_dump()
                # Emit a TOOL_SWITCH friction event
                switch_event = self._make_event(EventType.TOOL_SWITCH, current_app, payload)
                self._emit(switch_event)
                logger.debug(
                    "Cross-app paste detected: %s → %s",
                    self._last_copy_app,
                    current_app,
                )

            paste_event = self._make_event(
                EventType.CLIPBOARD_PASTE,
                current_app,
                {"from_app": self._last_copy_app or "", "is_cross_app": is_cross_app},
            )
            self._emit(paste_event)

    def start(self) -> None:
        """Start the clipboard listener in a background thread.

        No-op (with warning) if pynput is not installed.
        """
        try:
            from pynput import keyboard as _kb  # type: ignore[import]
        except ImportError:
            logger.warning(
                "pynput not installed — ClipboardCapture unavailable. "
                "Install with: uv sync --extra capture"
            )
            return

        self._listener = _kb.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.start()
        logger.info("ClipboardCapture started")

    def stop(self) -> None:
        """Stop the clipboard listener."""
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
            logger.info("ClipboardCapture stopped")
