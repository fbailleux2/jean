"""Tests for GainTracker — before/after irritant and tool-switch reduction metrics."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from jean.models import (
    BusinessEvent,
    EventType,
    ProcessDefinition,
    SessionTrace,
)
from jean.process_mapper.gain_tracker import GainTracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PERIOD_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
_PERIOD_END = datetime(2026, 3, 1, tzinfo=timezone.utc)


def _make_process() -> ProcessDefinition:
    return ProcessDefinition(
        name="test-process",
        process_context="test-ctx",
        trigger="test trigger",
    )


def _make_trace(*event_types: EventType) -> SessionTrace:
    events = [
        BusinessEvent(
            type=et,
            app="TestApp",
            process_context="test-ctx",
            session_id="sess-1",
            workstation_id="ws-1",
        )
        for et in event_types
    ]
    return SessionTrace(
        workstation_id="ws-1",
        process_context="test-ctx",
        events=events,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_no_improvement():
    """Same event counts before and after → 0% reduction in both metrics."""
    process = _make_process()
    trace = _make_trace(EventType.IRRITANT, EventType.TOOL_SWITCH)
    tracker = GainTracker()
    metrics = tracker.compute(
        process,
        traces_before=[trace],
        traces_after=[trace],
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
    )
    assert metrics.irritant_reduction_pct == 0.0
    assert metrics.tool_switch_reduction_pct == 0.0


def test_full_improvement():
    """0 irritants after improvement → 100% reduction."""
    process = _make_process()
    before = _make_trace(EventType.IRRITANT, EventType.IRRITANT)
    after = _make_trace(EventType.SAVE)
    tracker = GainTracker()
    metrics = tracker.compute(
        process,
        traces_before=[before],
        traces_after=[after],
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
    )
    assert metrics.irritant_reduction_pct == 100.0


def test_partial_improvement():
    """4 irritants before, 2 after → 50% reduction."""
    process = _make_process()
    before = _make_trace(
        EventType.IRRITANT, EventType.IRRITANT,
        EventType.IRRITANT, EventType.IRRITANT,
    )
    after = _make_trace(EventType.IRRITANT, EventType.IRRITANT)
    tracker = GainTracker()
    metrics = tracker.compute(
        process,
        traces_before=[before],
        traces_after=[after],
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
    )
    assert metrics.irritant_reduction_pct == 50.0


def test_zero_before_no_division_error():
    """before=0 irritants → reduction=0.0, no ZeroDivisionError."""
    process = _make_process()
    before = _make_trace(EventType.SAVE)
    after = _make_trace(EventType.SAVE)
    tracker = GainTracker()
    metrics = tracker.compute(
        process,
        traces_before=[before],
        traces_after=[after],
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
    )
    assert metrics.irritant_reduction_pct == 0.0
    assert metrics.tool_switch_reduction_pct == 0.0


def test_empty_traces_before_and_after():
    """Empty lists → all averages = 0.0."""
    process = _make_process()
    tracker = GainTracker()
    metrics = tracker.compute(
        process,
        traces_before=[],
        traces_after=[],
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
    )
    assert metrics.avg_irritant_count_before == 0.0
    assert metrics.avg_irritant_count_after == 0.0
    assert metrics.avg_tool_switches_before == 0.0
    assert metrics.avg_tool_switches_after == 0.0
    assert metrics.irritant_reduction_pct == 0.0
    assert metrics.tool_switch_reduction_pct == 0.0


def test_tool_switch_reduction():
    """Tool switch reduction computed correctly."""
    process = _make_process()
    before = _make_trace(
        EventType.TOOL_SWITCH, EventType.TOOL_SWITCH,
        EventType.TOOL_SWITCH, EventType.TOOL_SWITCH,
    )
    after = _make_trace(EventType.TOOL_SWITCH)
    tracker = GainTracker()
    metrics = tracker.compute(
        process,
        traces_before=[before],
        traces_after=[after],
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
    )
    assert metrics.tool_switch_reduction_pct == 75.0
