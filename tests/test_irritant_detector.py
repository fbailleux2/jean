"""Tests for IrritantDetector — automatic friction detection from SessionTraces."""

from __future__ import annotations

import pytest

from jean.aggregator.irritant_detector import IrritantDetector, REPEAT_THRESHOLD, CLIPBOARD_THRESHOLD
from jean.models import BusinessEvent, EventType, SessionTrace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    event_type: EventType,
    app: str = "SAP",
    payload: dict | None = None,
    session_id: str = "sess-test",
) -> BusinessEvent:
    return BusinessEvent(
        type=event_type,
        app=app,
        process_context="invoice-exception",
        session_id=session_id,
        workstation_id="ws-001",
        payload=payload or {},
    )


def _make_trace(events: list[BusinessEvent], session_id: str = "sess-test") -> SessionTrace:
    return SessionTrace(
        session_id=session_id,
        workstation_id="ws-001",
        process_context="invoice-exception",
        events=events,
    )


# ---------------------------------------------------------------------------
# test_no_irritants_below_threshold
# ---------------------------------------------------------------------------


def test_no_irritants_below_threshold():
    """Fewer than REPEAT_THRESHOLD repeated (app, event_type) pairs → no signal."""
    detector = IrritantDetector()
    events = [
        _make_event(EventType.SAVE, app="SAP")
        for _ in range(REPEAT_THRESHOLD - 1)
    ]
    trace = _make_trace(events)
    signals = detector.detect([trace])
    repeated = [s for s in signals if s.irritant_type == "repeated_action"]
    assert repeated == []


# ---------------------------------------------------------------------------
# test_repeated_action_detected
# ---------------------------------------------------------------------------


def test_repeated_action_detected():
    """Exactly REPEAT_THRESHOLD of same (app, event_type) → IrritantSignal with repeated_action."""
    detector = IrritantDetector()
    events = [
        _make_event(EventType.SAVE, app="SAP")
        for _ in range(REPEAT_THRESHOLD)
    ]
    trace = _make_trace(events)
    signals = detector.detect([trace])
    repeated = [s for s in signals if s.irritant_type == "repeated_action"]
    assert len(repeated) == 1
    sig = repeated[0]
    assert sig.source == "auto"
    assert sig.app == "SAP"
    assert len(sig.related_event_ids) == REPEAT_THRESHOLD


def test_repeated_action_detected_more_than_threshold():
    """More than REPEAT_THRESHOLD repeated actions → still exactly one signal per (app, type)."""
    detector = IrritantDetector()
    events = [
        _make_event(EventType.SAVE, app="SAP")
        for _ in range(REPEAT_THRESHOLD + 3)
    ]
    trace = _make_trace(events)
    signals = detector.detect([trace])
    repeated = [s for s in signals if s.irritant_type == "repeated_action"]
    assert len(repeated) == 1
    assert len(repeated[0].related_event_ids) == REPEAT_THRESHOLD + 3


# ---------------------------------------------------------------------------
# test_tool_switch_friction_detected
# ---------------------------------------------------------------------------


def test_tool_switch_friction_detected():
    """A TOOL_SWITCH event (not cross-app paste) → tool_switch_friction signal."""
    detector = IrritantDetector()
    events = [
        _make_event(
            EventType.TOOL_SWITCH,
            app="Excel",
            payload={"from_app": "SAP", "to_app": "Excel", "is_cross_app_paste": False},
        )
    ]
    trace = _make_trace(events)
    signals = detector.detect([trace])
    friction = [s for s in signals if s.irritant_type == "tool_switch_friction"]
    assert len(friction) == 1
    assert friction[0].source == "auto"
    assert friction[0].app == "Excel"


def test_tool_switch_cross_app_paste_not_flagged_as_friction():
    """A TOOL_SWITCH event that is a cross-app paste must NOT produce a tool_switch_friction signal."""
    detector = IrritantDetector()
    events = [
        _make_event(
            EventType.TOOL_SWITCH,
            app="Excel",
            payload={"from_app": "SAP", "to_app": "Excel", "is_cross_app_paste": True},
        )
    ]
    trace = _make_trace(events)
    signals = detector.detect([trace])
    friction = [s for s in signals if s.irritant_type == "tool_switch_friction"]
    assert friction == []


# ---------------------------------------------------------------------------
# test_clipboard_overuse_detected
# ---------------------------------------------------------------------------


def test_clipboard_overuse_detected():
    """CLIPBOARD_THRESHOLD or more cross-app pastes → cross_app_paste signal."""
    detector = IrritantDetector()
    events = [
        _make_event(EventType.CLIPBOARD_PASTE, app="Excel", payload={"is_cross_app": True})
        for _ in range(CLIPBOARD_THRESHOLD)
    ]
    trace = _make_trace(events)
    signals = detector.detect([trace])
    clipboard = [s for s in signals if s.irritant_type == "cross_app_paste"]
    assert len(clipboard) == 1
    sig = clipboard[0]
    assert sig.source == "auto"
    assert sig.app == "clipboard"
    assert len(sig.related_event_ids) == CLIPBOARD_THRESHOLD


# ---------------------------------------------------------------------------
# test_clipboard_below_threshold
# ---------------------------------------------------------------------------


def test_clipboard_below_threshold():
    """Fewer than CLIPBOARD_THRESHOLD cross-app pastes → no signal."""
    detector = IrritantDetector()
    events = [
        _make_event(EventType.CLIPBOARD_PASTE, app="Excel", payload={"is_cross_app": True})
        for _ in range(CLIPBOARD_THRESHOLD - 1)
    ]
    trace = _make_trace(events)
    signals = detector.detect([trace])
    clipboard = [s for s in signals if s.irritant_type == "cross_app_paste"]
    assert clipboard == []


def test_non_cross_app_paste_not_counted():
    """CLIPBOARD_PASTE with is_cross_app=False must not count toward clipboard overuse."""
    detector = IrritantDetector()
    events = [
        _make_event(EventType.CLIPBOARD_PASTE, app="Excel", payload={"is_cross_app": False})
        for _ in range(CLIPBOARD_THRESHOLD + 5)
    ]
    trace = _make_trace(events)
    signals = detector.detect([trace])
    clipboard = [s for s in signals if s.irritant_type == "cross_app_paste"]
    assert clipboard == []


# ---------------------------------------------------------------------------
# test_mixed_trace
# ---------------------------------------------------------------------------


def test_mixed_trace():
    """A trace with multiple irritant types → multiple signals returned."""
    detector = IrritantDetector()
    events: list[BusinessEvent] = []

    # Repeated SAVE actions
    events.extend(
        _make_event(EventType.SAVE, app="SAP")
        for _ in range(REPEAT_THRESHOLD)
    )

    # Tool switch friction
    events.append(
        _make_event(
            EventType.TOOL_SWITCH,
            app="Excel",
            payload={"from_app": "SAP", "to_app": "Excel", "is_cross_app_paste": False},
        )
    )

    # Clipboard overuse
    events.extend(
        _make_event(EventType.CLIPBOARD_PASTE, app="Excel", payload={"is_cross_app": True})
        for _ in range(CLIPBOARD_THRESHOLD)
    )

    trace = _make_trace(events)
    signals = detector.detect([trace])

    irritant_types = {s.irritant_type for s in signals}
    assert "repeated_action" in irritant_types
    assert "tool_switch_friction" in irritant_types
    assert "cross_app_paste" in irritant_types
    assert len(signals) >= 3


# ---------------------------------------------------------------------------
# test_empty_traces
# ---------------------------------------------------------------------------


def test_empty_traces():
    """Empty trace list → empty signal list."""
    detector = IrritantDetector()
    signals = detector.detect([])
    assert signals == []


def test_trace_with_no_events():
    """A trace with no events → no signals."""
    detector = IrritantDetector()
    trace = _make_trace([])
    signals = detector.detect([trace])
    assert signals == []


# ---------------------------------------------------------------------------
# test_custom_thresholds
# ---------------------------------------------------------------------------


def test_custom_thresholds():
    """IrritantDetector(repeat_threshold=2) detects repeated actions at count=2."""
    detector = IrritantDetector(repeat_threshold=2)
    events = [
        _make_event(EventType.SAVE, app="SAP"),
        _make_event(EventType.SAVE, app="SAP"),
    ]
    trace = _make_trace(events)
    signals = detector.detect([trace])
    repeated = [s for s in signals if s.irritant_type == "repeated_action"]
    assert len(repeated) == 1


def test_custom_clipboard_threshold():
    """IrritantDetector(clipboard_threshold=2) detects clipboard overuse at count=2."""
    detector = IrritantDetector(clipboard_threshold=2)
    events = [
        _make_event(EventType.CLIPBOARD_PASTE, app="Excel", payload={"is_cross_app": True}),
        _make_event(EventType.CLIPBOARD_PASTE, app="Excel", payload={"is_cross_app": True}),
    ]
    trace = _make_trace(events)
    signals = detector.detect([trace])
    clipboard = [s for s in signals if s.irritant_type == "cross_app_paste"]
    assert len(clipboard) == 1


def test_invalid_repeat_threshold_raises():
    """repeat_threshold < 1 must raise ValueError."""
    with pytest.raises(ValueError, match="repeat_threshold"):
        IrritantDetector(repeat_threshold=0)


def test_invalid_clipboard_threshold_raises():
    """clipboard_threshold < 1 must raise ValueError."""
    with pytest.raises(ValueError, match="clipboard_threshold"):
        IrritantDetector(clipboard_threshold=0)


# ---------------------------------------------------------------------------
# Multiple traces
# ---------------------------------------------------------------------------


def test_multiple_traces_signals_aggregated():
    """Signals from multiple traces are all returned in one flat list."""
    detector = IrritantDetector()

    trace1 = _make_trace(
        [_make_event(EventType.SAVE, app="SAP", session_id="sess-1") for _ in range(REPEAT_THRESHOLD)],
        session_id="sess-1",
    )
    trace2 = _make_trace(
        [_make_event(EventType.SAVE, app="Chrome", session_id="sess-2") for _ in range(REPEAT_THRESHOLD)],
        session_id="sess-2",
    )
    signals = detector.detect([trace1, trace2])
    repeated = [s for s in signals if s.irritant_type == "repeated_action"]
    assert len(repeated) == 2
    apps = {s.app for s in repeated}
    assert "SAP" in apps
    assert "Chrome" in apps
