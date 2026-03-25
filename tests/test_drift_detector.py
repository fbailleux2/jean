"""Tests for DriftDetector — Jaccard-based process drift computation."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from jean.models import (
    BusinessEvent,
    EventType,
    ProcessDefinition,
    ProcessStep,
    SessionTrace,
)
from jean.process_mapper.drift_detector import DEFAULT_ALERT_THRESHOLD, DriftDetector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_process(related_event_types: list[list[str]] | None = None) -> ProcessDefinition:
    """Build a minimal ProcessDefinition, optionally with step event types."""
    steps: list[ProcessStep] = []
    if related_event_types:
        for i, evt_types in enumerate(related_event_types, start=1):
            steps.append(
                ProcessStep(
                    sequence=i,
                    action=f"Step {i}",
                    tool="SAP",
                    related_event_types=evt_types,
                )
            )
    return ProcessDefinition(
        name="test-process",
        process_context="test-ctx",
        trigger="test trigger",
        steps=steps,
    )


def _make_trace(event_types: list[EventType]) -> SessionTrace:
    """Build a SessionTrace with given event types."""
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


def test_no_declared_types_no_drift():
    """Process steps with no related_event_types → drift_score = 0.0."""
    process = _make_process(related_event_types=[[]])
    traces = [_make_trace([EventType.SAVE, EventType.IRRITANT])]
    detector = DriftDetector()
    report = detector.compute(process, traces)
    assert report.drift_score == 0.0


def test_perfect_match():
    """Observed events exactly match declared → drift_score = 0.0."""
    process = _make_process(related_event_types=[[EventType.SAVE, EventType.SUBMIT]])
    traces = [_make_trace([EventType.SAVE, EventType.SUBMIT])]
    detector = DriftDetector()
    report = detector.compute(process, traces)
    assert report.drift_score == 0.0


def test_complete_mismatch():
    """No overlap between declared and observed → drift_score = 1.0."""
    process = _make_process(related_event_types=[[EventType.SAVE]])
    traces = [_make_trace([EventType.IRRITANT])]
    detector = DriftDetector()
    report = detector.compute(process, traces)
    assert report.drift_score == 1.0


def test_partial_overlap():
    """Some matching events → 0 < drift_score < 1."""
    process = _make_process(related_event_types=[[EventType.SAVE, EventType.SUBMIT]])
    # Only SAVE observed, SUBMIT not observed; also IRRITANT not in declared
    traces = [_make_trace([EventType.SAVE, EventType.IRRITANT])]
    detector = DriftDetector()
    report = detector.compute(process, traces)
    # declared={save, submit}, observed={save, irritant}
    # intersection={save}=1, union={save,submit,irritant}=3 → score=1-1/3=0.6667
    assert 0.0 < report.drift_score < 1.0


def test_alert_triggered_above_threshold():
    """drift_score > 0.5 → alert=True."""
    process = _make_process(related_event_types=[[EventType.SAVE]])
    # No overlap → score = 1.0 > 0.5
    traces = [_make_trace([EventType.IRRITANT])]
    detector = DriftDetector(alert_threshold=0.5)
    report = detector.compute(process, traces)
    assert report.alert is True
    assert report.drift_score > 0.5


def test_no_alert_below_threshold():
    """drift_score <= 0.5 → alert=False."""
    process = _make_process(related_event_types=[[EventType.SAVE, EventType.SUBMIT]])
    # Perfect match → drift = 0.0
    traces = [_make_trace([EventType.SAVE, EventType.SUBMIT])]
    detector = DriftDetector(alert_threshold=0.5)
    report = detector.compute(process, traces)
    assert report.alert is False
    assert report.drift_score <= 0.5


def test_empty_traces():
    """No traces → no observed baseline; drift_score=0.0 (cannot be measured)."""
    process = _make_process(related_event_types=[[EventType.SAVE]])
    detector = DriftDetector()
    report = detector.compute(process, traces=[])
    # No data to compare against → score=0.0, alert=False
    assert report.drift_score == 0.0
    assert report.alert is False
    assert report.session_count_analysed == 0
    assert report.observed_event_types == []


def test_drift_report_fields():
    """DriftReport contains the correct process metadata fields."""
    process = _make_process(related_event_types=[[EventType.SAVE]])
    traces = [_make_trace([EventType.SAVE])]
    detector = DriftDetector()
    report = detector.compute(process, traces)

    assert report.process_id == process.id
    assert report.process_name == process.name
    assert report.process_context == process.process_context
    assert report.declared_step_count == len(process.steps)
    assert report.session_count_analysed == 1
    assert isinstance(report.computed_at, datetime)
    assert report.schema_version == "1.0"
