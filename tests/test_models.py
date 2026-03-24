"""Tests for Jean core data models."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from jean.models import (
    BusinessEvent,
    EventType,
    FieldObservation,
    PatternHypothesis,
    ProcedureState,
    SessionTrace,
)


# ---------------------------------------------------------------------------
# BusinessEvent
# ---------------------------------------------------------------------------


def test_business_event_defaults():
    event = BusinessEvent(
        type=EventType.SAVE,
        app="Excel",
        process_context="invoice-exception",
        session_id="sess-1",
        workstation_id="ws-abc",
    )
    assert event.type == EventType.SAVE
    assert event.app == "Excel"
    assert event.id  # UUID generated
    assert event.timestamp.tzinfo is not None  # timezone-aware


def test_business_event_is_frozen():
    event = BusinessEvent(
        type=EventType.SAVE,
        app="Excel",
        process_context="invoice-exception",
        session_id="sess-1",
        workstation_id="ws-abc",
    )
    with pytest.raises(Exception):
        event.app = "Word"  # type: ignore


def test_business_event_payload_defaults_empty():
    event = BusinessEvent(
        type=EventType.APP_FOCUS,
        app="SAP",
        process_context="purchase-order",
        session_id="sess-2",
        workstation_id="ws-xyz",
    )
    assert event.payload == {}


# ---------------------------------------------------------------------------
# SessionTrace
# ---------------------------------------------------------------------------


def test_session_trace_duration():
    t0 = datetime(2026, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 1, 9, 30, 0, tzinfo=timezone.utc)
    trace = SessionTrace(
        workstation_id="ws-1",
        process_context="invoice-exception",
        started_at=t0,
        ended_at=t1,
    )
    assert trace.duration_seconds == 1800.0


def test_session_trace_duration_none_when_open():
    trace = SessionTrace(
        workstation_id="ws-1",
        process_context="invoice-exception",
    )
    assert trace.duration_seconds is None


def test_session_trace_ended_before_started_raises():
    t0 = datetime(2026, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(ValidationError):
        SessionTrace(
            workstation_id="ws-1",
            process_context="invoice-exception",
            started_at=t0,
            ended_at=t1,
        )


# ---------------------------------------------------------------------------
# PatternHypothesis
# ---------------------------------------------------------------------------


def test_pattern_hypothesis_requires_source_traces():
    with pytest.raises(ValidationError):
        PatternHypothesis(
            pattern=[EventType.APP_FOCUS, EventType.SAVE],
            frequency=3,
            confidence=0.75,
            source_trace_ids=[],  # empty — must raise
            process_context="invoice-exception",
        )


def test_pattern_hypothesis_confidence_bounds():
    with pytest.raises(ValidationError):
        PatternHypothesis(
            pattern=[EventType.SAVE],
            frequency=1,
            confidence=1.5,  # > 1.0
            source_trace_ids=["t1"],
            process_context="test",
        )

    with pytest.raises(ValidationError):
        PatternHypothesis(
            pattern=[EventType.SAVE],
            frequency=1,
            confidence=-0.1,  # < 0.0
            source_trace_ids=["t1"],
            process_context="test",
        )


def test_pattern_hypothesis_default_state():
    h = PatternHypothesis(
        pattern=[EventType.APP_FOCUS, EventType.SAVE, EventType.SUBMIT],
        frequency=5,
        confidence=0.8,
        source_trace_ids=["t1", "t2", "t3"],
        process_context="invoice-exception",
    )
    assert h.state == ProcedureState.OBSERVED


# ---------------------------------------------------------------------------
# FieldObservation
# ---------------------------------------------------------------------------


def test_field_observation_is_validated_false_by_default():
    obs = FieldObservation(
        process_context="invoice-exception",
        declared_procedure="Route to manager for amounts > 1000",
        observed_behavior="Operators process directly up to 5000",
        gap_score=0.7,
        supporting_patterns=["p1", "p2"],
    )
    assert not obs.is_validated()


def test_field_observation_is_validated_true():
    from datetime import datetime, timezone

    obs = FieldObservation(
        process_context="invoice-exception",
        declared_procedure="Route to manager for amounts > 1000",
        observed_behavior="Operators process directly up to 5000",
        gap_score=0.7,
        supporting_patterns=["p1"],
        state=ProcedureState.VALIDATED,
        validated_at=datetime.now(timezone.utc),
        validated_by="manager@example.com",
    )
    assert obs.is_validated()


def test_field_observation_gap_score_bounds():
    with pytest.raises(ValidationError):
        FieldObservation(
            process_context="test",
            declared_procedure="x",
            observed_behavior="y",
            gap_score=1.5,
            supporting_patterns=["p1"],
        )
