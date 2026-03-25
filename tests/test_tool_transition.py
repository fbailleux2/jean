"""Tests for ToolTransition, IrritantSignal models and AppTransitionCapture friction tracking."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jean.models import EventType, IrritantSignal, ToolTransition
from jean.agent.capture import AppTransitionCapture, FRICTION_THRESHOLD


# ---------------------------------------------------------------------------
# ToolTransition model validation
# ---------------------------------------------------------------------------


def test_tool_transition_valid():
    t = ToolTransition(
        from_app="SAP",
        to_app="Excel",
        transition_count=1,
        is_cross_app_paste=False,
    )
    assert t.from_app == "SAP"
    assert t.to_app == "Excel"
    assert t.transition_count == 1
    assert t.is_cross_app_paste is False
    assert t.schema_version == "1.0"


def test_tool_transition_defaults():
    t = ToolTransition(from_app="A", to_app="B", transition_count=2)
    assert t.is_cross_app_paste is False
    assert t.schema_version == "1.0"


def test_tool_transition_transition_count_must_be_ge1():
    with pytest.raises(ValidationError):
        ToolTransition(from_app="A", to_app="B", transition_count=0)


def test_tool_transition_cross_app_paste_flag():
    t = ToolTransition(
        from_app="Browser",
        to_app="SAP",
        transition_count=1,
        is_cross_app_paste=True,
    )
    assert t.is_cross_app_paste is True


def test_tool_transition_model_dump_roundtrip():
    t = ToolTransition(from_app="A", to_app="B", transition_count=3, is_cross_app_paste=True)
    d = t.model_dump()
    assert d["from_app"] == "A"
    assert d["to_app"] == "B"
    assert d["transition_count"] == 3
    assert d["is_cross_app_paste"] is True


# ---------------------------------------------------------------------------
# IrritantSignal model validation
# ---------------------------------------------------------------------------


def test_irritant_signal_valid():
    sig = IrritantSignal(
        source="operator",
        irritant_type="manual",
        app="SAP",
    )
    assert sig.source == "operator"
    assert sig.irritant_type == "manual"
    assert sig.app == "SAP"
    assert sig.related_event_ids == []
    assert sig.schema_version == "1.0"


def test_irritant_signal_auto_source():
    sig = IrritantSignal(
        source="auto",
        irritant_type="cross_app_paste",
        app="Excel",
        related_event_ids=["evt-1", "evt-2"],
    )
    assert sig.source == "auto"
    assert len(sig.related_event_ids) == 2


def test_irritant_signal_related_event_ids_default_empty():
    sig = IrritantSignal(source="operator", irritant_type="repeated_action", app="Chrome")
    assert sig.related_event_ids == []


def test_irritant_signal_schema_version_default():
    sig = IrritantSignal(source="auto", irritant_type="manual", app="SAP")
    assert sig.schema_version == "1.0"


# ---------------------------------------------------------------------------
# AppTransitionCapture._track_transition — friction threshold logic
# ---------------------------------------------------------------------------


def _make_capture() -> AppTransitionCapture:
    return AppTransitionCapture(
        workstation_id="ws-test",
        process_context="invoice-exception",
        session_id="sess-test",
    )


def test_track_transition_no_event_below_threshold():
    """No TOOL_SWITCH event should be emitted before the threshold is reached."""
    cap = _make_capture()
    results = []
    for _ in range(FRICTION_THRESHOLD - 1):
        event = cap._track_transition("SAP")
        results.append(event)
        event2 = cap._track_transition("Excel")
        results.append(event2)

    assert all(e is None for e in results), "Should not emit before threshold"


def test_track_transition_emits_at_threshold():
    """TOOL_SWITCH event must be emitted exactly when threshold is reached."""
    cap = _make_capture()

    # Simulate back-and-forth: SAP → Excel repeated FRICTION_THRESHOLD times
    # Each "SAP → Excel" transition counts as one for the (SAP, Excel) pair
    emitted = []
    for i in range(FRICTION_THRESHOLD):
        cap._track_transition("SAP")   # SAP → last_app transition (or initial)
        event = cap._track_transition("Excel")  # Excel transition — this is the counted pair
        if event is not None:
            emitted.append(event)

    assert len(emitted) == 1, f"Expected exactly 1 friction event, got {len(emitted)}"
    friction_event = emitted[0]
    assert friction_event.type == EventType.TOOL_SWITCH


def test_track_transition_payload_contains_tool_transition_data():
    """The TOOL_SWITCH event payload must match ToolTransition fields."""
    cap = _make_capture()

    friction_event = None
    for i in range(FRICTION_THRESHOLD):
        cap._track_transition("SAP")
        result = cap._track_transition("Excel")
        if result is not None:
            friction_event = result

    assert friction_event is not None
    payload = friction_event.payload
    assert payload["from_app"] == "SAP"
    assert payload["to_app"] == "Excel"
    assert payload["transition_count"] == FRICTION_THRESHOLD
    assert payload["is_cross_app_paste"] is False
    assert payload["schema_version"] == "1.0"


def test_track_transition_no_event_after_threshold():
    """No additional TOOL_SWITCH events after the threshold event is already emitted."""
    cap = _make_capture()

    emitted = []
    for i in range(FRICTION_THRESHOLD + 3):
        cap._track_transition("SAP")
        event = cap._track_transition("Excel")
        if event is not None:
            emitted.append(event)

    # Only one event should be emitted (at exactly the threshold)
    assert len(emitted) == 1


def test_track_transition_first_app_returns_none():
    """First call with no prior app sets _last_app without emitting."""
    cap = _make_capture()
    result = cap._track_transition("SAP")
    assert result is None
    assert cap._last_app == "SAP"


def test_track_transition_same_app_returns_none():
    """Transitioning to the same app does not count or emit."""
    cap = _make_capture()
    cap._track_transition("SAP")  # set last_app

    result = cap._track_transition("SAP")  # same app
    assert result is None
    assert cap._transition_counts == {}
