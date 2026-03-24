"""Tests for macOS AppTransitionCapture.

Since pyobjc is optional and requires macOS runtime, these tests mock
the _macos module and verify the fallback behaviour.
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jean.models import EventType


@pytest.mark.asyncio
async def test_app_transition_capture_fallback_when_no_pyobjc():
    """AppTransitionCapture yields nothing if pyobjc is not installed."""
    from jean.agent.capture import AppTransitionCapture

    cap = AppTransitionCapture(
        workstation_id="ws-test",
        process_context="test",
        session_id="sess-test",
    )

    # Patch the macos import to raise ImportError
    with patch("jean.agent.capture.platform.system", return_value="Darwin"):
        with patch(
            "jean.agent.capture.AppTransitionCapture._import_macos",
            side_effect=ImportError("no pyobjc"),
        ):
            events = []
            # Run for a short time — should yield nothing
            async def _collect():
                async for e in cap.events():
                    events.append(e)
                    if len(events) > 0:
                        break

            try:
                await asyncio.wait_for(_collect(), timeout=0.1)
            except (asyncio.TimeoutError, StopAsyncIteration):
                pass

    assert events == []


@pytest.mark.asyncio
async def test_structural_action_capture_inject():
    """StructuralActionCapture yields events injected via inject()."""
    from jean.agent.capture import StructuralActionCapture

    cap = StructuralActionCapture(
        workstation_id="ws-test",
        process_context="test",
        session_id="sess-test",
    )

    await cap.inject(EventType.SAVE, "Excel")

    events = []
    async for e in cap.events():
        events.append(e)
        break  # get just one

    assert len(events) == 1
    assert events[0].type == EventType.SAVE
    assert events[0].app == "Excel"


@pytest.mark.asyncio
async def test_annotation_capture():
    """AnnotationCapture yields annotation events."""
    from jean.agent.capture import AnnotationCapture

    cap = AnnotationCapture(
        workstation_id="ws-test",
        process_context="test",
        session_id="sess-test",
    )

    await cap.annotate("Invoice approved per supplier agreement", "FlowFabric-Inbox")

    events = []
    async for e in cap.events():
        events.append(e)
        break

    assert events[0].type == EventType.ANNOTATION
    assert events[0].payload["text"] == "Invoice approved per supplier agreement"
