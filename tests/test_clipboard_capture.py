"""Tests for ClipboardCapture — cross-app paste detection and event emission."""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import MagicMock, patch

import pytest

from jean.agent.capture_clipboard import ClipboardCapture
from jean.models import BusinessEvent, EventType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MockKey:
    """Mimics a pynput key object for a regular character key."""

    def __init__(self, char=None, name=None):
        self.char = char
        self._name = name

    def __str__(self):
        return f"Key.{self._name}" if self._name else (self.char or "")


def _ctrl():
    return _MockKey(name="ctrl_l")


def _c():
    return _MockKey(char="c")


def _v():
    return _MockKey(char="v")


def _make_capture(
    queue: asyncio.Queue,
    loop: asyncio.AbstractEventLoop,
    current_app_fn=None,
) -> ClipboardCapture:
    return ClipboardCapture(
        event_queue=queue,
        workstation_id="ws-clip",
        process_context="invoice-exception",
        session_id="sess-clip",
        current_app_fn=current_app_fn or (lambda: "AppA"),
        loop=loop,
    )


async def _drain(queue: asyncio.Queue) -> list[BusinessEvent]:
    """Drain all currently queued events without blocking."""
    events: list[BusinessEvent] = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


# ---------------------------------------------------------------------------
# Ctrl+C → CLIPBOARD_COPY
# ---------------------------------------------------------------------------


async def test_ctrl_c_emits_clipboard_copy():
    """Ctrl+C produces a CLIPBOARD_COPY BusinessEvent."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[BusinessEvent] = asyncio.Queue()
    cap = _make_capture(queue, loop)

    cap._on_press(_ctrl())
    cap._on_press(_c())
    await asyncio.sleep(0)

    events = await _drain(queue)
    assert len(events) == 1
    assert events[0].type == EventType.CLIPBOARD_COPY
    assert events[0].app == "AppA"
    assert events[0].workstation_id == "ws-clip"


# ---------------------------------------------------------------------------
# Ctrl+V → CLIPBOARD_PASTE (same app, no TOOL_SWITCH)
# ---------------------------------------------------------------------------


async def test_ctrl_v_emits_clipboard_paste_same_app():
    """Ctrl+V produces a CLIPBOARD_PASTE event; no TOOL_SWITCH when same app."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[BusinessEvent] = asyncio.Queue()

    current_app = ["AppA"]
    cap = _make_capture(queue, loop, current_app_fn=lambda: current_app[0])

    # Copy in AppA
    cap._on_press(_ctrl())
    cap._on_press(_c())
    await asyncio.sleep(0)
    queue.get_nowait()  # consume CLIPBOARD_COPY

    # Paste in same AppA
    cap._on_release(_c())
    cap._on_press(_v())
    await asyncio.sleep(0)

    events = await _drain(queue)
    types = [e.type for e in events]
    assert EventType.CLIPBOARD_PASTE in types
    assert EventType.TOOL_SWITCH not in types

    paste_event = next(e for e in events if e.type == EventType.CLIPBOARD_PASTE)
    assert paste_event.payload["is_cross_app"] is False


# ---------------------------------------------------------------------------
# Cross-app paste → TOOL_SWITCH + CLIPBOARD_PASTE
# ---------------------------------------------------------------------------


async def test_ctrl_v_in_different_app_emits_tool_switch():
    """Paste in a different app than copy emits a TOOL_SWITCH friction event."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[BusinessEvent] = asyncio.Queue()

    current_app = ["AppA"]
    cap = _make_capture(queue, loop, current_app_fn=lambda: current_app[0])

    # Copy in AppA
    cap._on_press(_ctrl())
    cap._on_press(_c())
    await asyncio.sleep(0)
    queue.get_nowait()  # consume CLIPBOARD_COPY

    # Switch to AppB, then paste
    current_app[0] = "AppB"
    cap._on_release(_c())
    cap._on_press(_v())
    await asyncio.sleep(0)

    events = await _drain(queue)
    types = [e.type for e in events]
    assert EventType.TOOL_SWITCH in types
    assert EventType.CLIPBOARD_PASTE in types

    switch_event = next(e for e in events if e.type == EventType.TOOL_SWITCH)
    assert switch_event.payload["from_app"] == "AppA"
    assert switch_event.payload["to_app"] == "AppB"
    assert switch_event.payload["is_cross_app_paste"] is True

    paste_event = next(e for e in events if e.type == EventType.CLIPBOARD_PASTE)
    assert paste_event.payload["is_cross_app"] is True
    assert paste_event.payload["from_app"] == "AppA"


# ---------------------------------------------------------------------------
# Same-app paste does NOT emit TOOL_SWITCH
# ---------------------------------------------------------------------------


async def test_same_app_paste_does_not_emit_tool_switch():
    """Paste in the same app as copy must NOT emit TOOL_SWITCH."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[BusinessEvent] = asyncio.Queue()
    cap = _make_capture(queue, loop, current_app_fn=lambda: "SameApp")

    # Copy
    cap._on_press(_ctrl())
    cap._on_press(_c())
    await asyncio.sleep(0)
    queue.get_nowait()  # consume CLIPBOARD_COPY

    # Paste in same app
    cap._on_release(_c())
    cap._on_press(_v())
    await asyncio.sleep(0)

    events = await _drain(queue)
    assert all(e.type != EventType.TOOL_SWITCH for e in events)
    assert any(e.type == EventType.CLIPBOARD_PASTE for e in events)


# ---------------------------------------------------------------------------
# start() is a no-op when pynput is not installed
# ---------------------------------------------------------------------------


def test_start_without_pynput_is_noop(caplog):
    """ClipboardCapture.start() is a no-op with warning when pynput is missing."""
    import logging

    queue: asyncio.Queue[BusinessEvent] = asyncio.Queue()
    cap = ClipboardCapture(
        event_queue=queue,
        workstation_id="ws-clip",
        process_context="test",
        session_id="sess",
    )

    saved = sys.modules.pop("pynput", None)
    saved_kb = sys.modules.pop("pynput.keyboard", None)
    try:
        with caplog.at_level(logging.WARNING, logger="jean.agent.capture_clipboard"):
            cap.start()  # Must not raise
    finally:
        if saved is not None:
            sys.modules["pynput"] = saved
        if saved_kb is not None:
            sys.modules["pynput.keyboard"] = saved_kb

    assert cap._listener is None
