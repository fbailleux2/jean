"""Tests for macOS NSWorkspace thread bridge pattern (ISC-14 to ISC-19).

No pyobjc required — simulates the thread→asyncio bridge using
asyncio.get_running_loop().call_soon_threadsafe() directly.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest

from jean.models import EventType


# ---------------------------------------------------------------------------
# ISC-14, 15, 16: call_soon_threadsafe correctly bridges thread → async queue
# ---------------------------------------------------------------------------


async def test_call_soon_threadsafe_delivers_focus_event():
    """Simulate NSWorkspace thread posting an APP_FOCUS event to asyncio queue."""
    queue: asyncio.Queue[tuple[str, EventType]] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def _thread_post():
        loop.call_soon_threadsafe(queue.put_nowait, ("Excel", EventType.APP_FOCUS))

    thread = threading.Thread(target=_thread_post)
    thread.start()
    thread.join()

    event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert event == ("Excel", EventType.APP_FOCUS)


async def test_call_soon_threadsafe_delivers_blur_event():
    """Simulate NSWorkspace thread posting an APP_BLUR event to asyncio queue."""
    queue: asyncio.Queue[tuple[str, EventType]] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def _thread_post():
        loop.call_soon_threadsafe(queue.put_nowait, ("Excel", EventType.APP_BLUR))

    thread = threading.Thread(target=_thread_post)
    thread.start()
    thread.join()

    event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert event == ("Excel", EventType.APP_BLUR)


async def test_multiple_thread_events_arrive_in_order():
    """Multiple thread posts arrive in insertion order."""
    queue: asyncio.Queue[tuple[str, EventType]] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    events_to_post = [
        ("Excel", EventType.APP_FOCUS),
        ("SAP", EventType.APP_FOCUS),
        ("Excel", EventType.APP_BLUR),
    ]

    def _thread_post():
        for event in events_to_post:
            loop.call_soon_threadsafe(queue.put_nowait, event)

    thread = threading.Thread(target=_thread_post)
    thread.start()
    thread.join()

    received = []
    for _ in events_to_post:
        received.append(await asyncio.wait_for(queue.get(), timeout=1.0))

    assert received == events_to_post


# ---------------------------------------------------------------------------
# ISC-17, 18: AppTransitionCapture.events() yields from mocked thread
# ---------------------------------------------------------------------------


async def test_app_transition_capture_yields_from_mock_observe():
    """AppTransitionCapture.events() yields events from mocked observe_app_transitions."""
    from jean.agent.capture import AppTransitionCapture

    cap = AppTransitionCapture(
        workstation_id="ws-test",
        process_context="test",
        session_id="sess-thread",
    )

    async def _mock_observe() -> AsyncGenerator[tuple[str, EventType], None]:
        yield ("Excel", EventType.APP_FOCUS)
        yield ("SAP", EventType.APP_FOCUS)

    received = []
    with patch("jean.agent.capture.platform.system", return_value="Darwin"):
        with patch.object(cap, "_import_macos", return_value=_mock_observe):
            async for event in cap.events():
                received.append(event)
                if len(received) >= 2:
                    break

    assert len(received) == 2
    assert received[0].type == EventType.APP_FOCUS
    assert received[0].app == "Excel"
    assert received[1].app == "SAP"


async def test_app_transition_capture_sets_correct_metadata():
    """Events yielded by AppTransitionCapture have correct workstation/session."""
    from jean.agent.capture import AppTransitionCapture

    cap = AppTransitionCapture(
        workstation_id="ws-macos-001",
        process_context="invoice-exception",
        session_id="sess-mac",
    )

    async def _mock_observe() -> AsyncGenerator[tuple[str, EventType], None]:
        yield ("Chrome", EventType.APP_FOCUS)

    with patch("jean.agent.capture.platform.system", return_value="Darwin"):
        with patch.object(cap, "_import_macos", return_value=_mock_observe):
            async for event in cap.events():
                assert event.workstation_id == "ws-macos-001"
                assert event.process_context == "invoice-exception"
                assert event.session_id == "sess-mac"
                break


async def test_thread_bridge_with_multiple_threads():
    """Multiple concurrent threads can safely post to the same queue."""
    queue: asyncio.Queue[tuple[str, EventType]] = asyncio.Queue()
    loop = asyncio.get_running_loop()
    threads = []

    for app in ["App1", "App2", "App3"]:
        t = threading.Thread(
            target=lambda a=app: loop.call_soon_threadsafe(
                queue.put_nowait, (a, EventType.APP_FOCUS)
            )
        )
        threads.append(t)

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    events = []
    for _ in range(3):
        events.append(await asyncio.wait_for(queue.get(), timeout=1.0))

    app_names = {e[0] for e in events}
    assert app_names == {"App1", "App2", "App3"}


def test_get_running_loop_used_in_macos():
    """_macos.py source uses get_running_loop, not deprecated get_event_loop."""
    import inspect
    import jean.agent._macos as macos_mod

    source = inspect.getsource(macos_mod)
    assert "get_running_loop" in source
    assert "get_event_loop" not in source
