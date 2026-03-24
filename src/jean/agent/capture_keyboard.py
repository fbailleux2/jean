"""Cross-platform keyboard shortcut capture for jean-agent.

Detects structural actions (save, print, export) via global keyboard hooks
using pynput (Linux/Windows). On macOS, NSWorkspace is the preferred mechanism.

Requires the [capture] optional extra:
    uv sync --extra capture

Key bindings (configurable):
    Ctrl+S       → SAVE
    Ctrl+P       → PRINT
    Ctrl+Shift+E → EXPORT

Privacy guarantee: only the hotkey combination is detected, never the key
sequence or content of what was typed.

Usage::

    capture = KeyboardCapture(
        event_queue=structural_capture.event_queue,
        workstation_id="ws-001",
        process_context="invoice-exception",
        session_id="sess-001",
    )
    capture.start()
    # ... run your app ...
    capture.stop()
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from jean.models import BusinessEvent, EventType

logger = logging.getLogger(__name__)

# Default hotkey → EventType mapping
# Key names follow pynput conventions
_DEFAULT_HOTKEYS: dict[frozenset[str], EventType] = {
    frozenset({"ctrl", "s"}): EventType.SAVE,
    frozenset({"ctrl", "p"}): EventType.PRINT,
    frozenset({"ctrl", "shift", "e"}): EventType.EXPORT,
}


class KeyboardCapture:
    """Listens for global keyboard shortcuts and pushes BusinessEvents to a queue.

    Args:
        event_queue:     asyncio.Queue shared with StructuralActionCapture.
        workstation_id:  Pseudonymous workstation identifier.
        process_context: Business process context label.
        session_id:      Session trace identifier.
        loop:            asyncio event loop (defaults to running loop).
        hotkeys:         Override the default hotkey → EventType mapping.
    """

    def __init__(
        self,
        event_queue: asyncio.Queue[BusinessEvent],
        workstation_id: str,
        process_context: str,
        session_id: str,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
        hotkeys: dict[frozenset[str], EventType] | None = None,
    ) -> None:
        self.event_queue = event_queue
        self.workstation_id = workstation_id
        self.process_context = process_context
        self.session_id = session_id
        self._loop = loop
        self._hotkeys = hotkeys or _DEFAULT_HOTKEYS
        self._listener = None
        self._pressed: set[str] = set()

    def _make_event(self, event_type: EventType) -> BusinessEvent:
        return BusinessEvent(
            type=event_type,
            app="keyboard",
            timestamp=datetime.now(timezone.utc),
            process_context=self.process_context,
            session_id=self.session_id,
            workstation_id=self.workstation_id,
        )

    def _key_name(self, key: object) -> str | None:
        """Extract a normalised key name from a pynput key object."""
        try:
            c = key.char  # type: ignore[union-attr]
            if c is not None:
                return c.lower()
            # char is None → special key, fall through
        except AttributeError:
            pass
        # Special key (Key.ctrl_l, Key.shift, ...) — normalise via str()
        name = str(key).replace("Key.", "").lower()
        for base in ("ctrl", "shift", "alt", "cmd"):
            if name.startswith(base):
                return base
        return name if name else None

    def _on_press(self, key: object) -> None:
        name = self._key_name(key)
        if name:
            self._pressed.add(name)
            self._check_hotkeys()

    def _on_release(self, key: object) -> None:
        name = self._key_name(key)
        if name:
            self._pressed.discard(name)

    def _check_hotkeys(self) -> None:
        for combo, event_type in self._hotkeys.items():
            if combo.issubset(self._pressed):
                event = self._make_event(event_type)
                loop = self._loop
                if loop and loop.is_running():
                    try:
                        running = asyncio.get_running_loop()
                        if running is loop:
                            # Called from the event-loop thread — direct put is safe and immediate
                            self.event_queue.put_nowait(event)
                        else:
                            loop.call_soon_threadsafe(self.event_queue.put_nowait, event)
                    except RuntimeError:
                        # No running loop in current thread → pynput background thread
                        loop.call_soon_threadsafe(self.event_queue.put_nowait, event)
                else:
                    logger.debug(
                        "KeyboardCapture: no running loop, event dropped: %s", event_type
                    )

    def start(self) -> None:
        """Start the keyboard listener in a background thread.

        No-op (with warning) if pynput is not installed.
        """
        try:
            from pynput import keyboard as _kb  # type: ignore[import]
        except ImportError:
            logger.warning(
                "pynput not installed — KeyboardCapture unavailable. "
                "Install with: uv sync --extra capture"
            )
            return

        self._listener = _kb.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.start()
        logger.info(
            "KeyboardCapture started (hotkeys: %s)",
            ["+".join(sorted(k)) for k in self._hotkeys],
        )

    def stop(self) -> None:
        """Stop the keyboard listener."""
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
            logger.info("KeyboardCapture stopped")
