"""Tests for cross-platform keyboard capture (ISC-33, ISC-34)."""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import MagicMock, patch

import pytest

from jean.agent.capture_keyboard import KeyboardCapture, _DEFAULT_HOTKEYS
from jean.models import BusinessEvent, EventType


class _MockKey:
    """Mimics a pynput key object."""
    def __init__(self, char=None, name=None):
        self.char = char
        self._name = name

    def __str__(self):
        return f"Key.{self._name}" if self._name else (self.char or "")


def _ctrl():  return _MockKey(name="ctrl_l")
def _shift(): return _MockKey(name="shift")
def _s():     return _MockKey(char="s")
def _p():     return _MockKey(char="p")
def _e():     return _MockKey(char="e")


def _make_capture(queue: asyncio.Queue, loop) -> KeyboardCapture:
    return KeyboardCapture(
        event_queue=queue,
        workstation_id="ws-keyboard",
        process_context="invoice-exception",
        session_id="sess-kb",
        loop=loop,
    )


# ---------------------------------------------------------------------------
# ISC-33: mock pynput Listener, verify SAVE/PRINT/EXPORT pushed to queue
# ---------------------------------------------------------------------------


async def test_ctrl_s_pushes_save_event():
    """Ctrl+S produces a SAVE BusinessEvent."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[BusinessEvent] = asyncio.Queue()
    cap = _make_capture(queue, loop)

    cap._on_press(_ctrl())
    cap._on_press(_s())
    # call_soon_threadsafe schedules on the running loop; yield to let it run
    await asyncio.sleep(0)

    assert not queue.empty()
    event = queue.get_nowait()
    assert event.type == EventType.SAVE
    assert event.workstation_id == "ws-keyboard"


async def test_ctrl_p_pushes_print_event():
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[BusinessEvent] = asyncio.Queue()
    cap = _make_capture(queue, loop)

    cap._on_press(_ctrl())
    cap._on_press(_p())
    await asyncio.sleep(0)

    assert not queue.empty()
    event = queue.get_nowait()
    assert event.type == EventType.PRINT


async def test_ctrl_shift_e_pushes_export_event():
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[BusinessEvent] = asyncio.Queue()
    cap = _make_capture(queue, loop)

    cap._on_press(_ctrl())
    cap._on_press(_shift())
    cap._on_press(_e())
    await asyncio.sleep(0)

    assert not queue.empty()
    event = queue.get_nowait()
    assert event.type == EventType.EXPORT


async def test_key_release_clears_pressed_set():
    """Releasing a key removes it from _pressed."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[BusinessEvent] = asyncio.Queue()
    cap = _make_capture(queue, loop)

    cap._on_press(_ctrl())
    cap._on_press(_s())
    await asyncio.sleep(0)
    queue.get_nowait()  # consume SAVE

    cap._on_release(_s())
    cap._on_release(_ctrl())
    assert "s" not in cap._pressed

    # Press s again without ctrl — should NOT trigger SAVE
    cap._on_press(_s())
    await asyncio.sleep(0)
    assert queue.empty()


def test_start_and_stop_with_pynput():
    """start() and stop() invoke pynput.keyboard.Listener when available."""
    queue: asyncio.Queue[BusinessEvent] = asyncio.Queue()
    cap = KeyboardCapture(
        event_queue=queue,
        workstation_id="ws-kb",
        process_context="test",
        session_id="sess",
    )

    mock_listener = MagicMock()
    mock_listener_class = MagicMock(return_value=mock_listener)
    mock_keyboard = MagicMock()
    mock_keyboard.Listener = mock_listener_class
    mock_pynput = MagicMock()
    mock_pynput.keyboard = mock_keyboard

    with patch.dict(sys.modules, {
        "pynput": mock_pynput,
        "pynput.keyboard": mock_keyboard,
    }):
        cap.start()

    mock_listener.start.assert_called_once()
    cap.stop()
    mock_listener.stop.assert_called_once()


# ---------------------------------------------------------------------------
# ISC-34: pynput ImportError → graceful warning, no crash
# ---------------------------------------------------------------------------


def test_start_without_pynput_logs_warning_and_no_crash(caplog):
    """KeyboardCapture.start() is a no-op with warning if pynput is missing."""
    import logging
    queue: asyncio.Queue[BusinessEvent] = asyncio.Queue()
    cap = KeyboardCapture(
        event_queue=queue,
        workstation_id="ws-kb",
        process_context="test",
        session_id="sess",
    )

    # Simulate pynput not installed by removing it from sys.modules
    saved = sys.modules.pop("pynput", None)
    saved_kb = sys.modules.pop("pynput.keyboard", None)
    try:
        with caplog.at_level(logging.WARNING, logger="jean.agent.capture_keyboard"):
            cap.start()  # Must not raise
    finally:
        if saved is not None:
            sys.modules["pynput"] = saved
        if saved_kb is not None:
            sys.modules["pynput.keyboard"] = saved_kb

    assert cap._listener is None
