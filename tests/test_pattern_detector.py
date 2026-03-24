"""Tests for PatternDetector (jean-aggregator)."""

from __future__ import annotations

import pytest

from jean.aggregator.pattern_detector import PatternDetector
from jean.models import BusinessEvent, EventType, SessionTrace


def _trace(events: list[EventType], session_id: str = "s") -> SessionTrace:
    evs = [
        BusinessEvent(
            type=t,
            app="TestApp",
            process_context="test",
            session_id=session_id,
            workstation_id="ws-test",
        )
        for t in events
    ]
    return SessionTrace(
        session_id=session_id,
        workstation_id="ws-test",
        process_context="test",
        events=evs,
    )


def test_no_traces_returns_empty():
    det = PatternDetector()
    assert det.detect([]) == []


def test_single_trace_no_repeat_no_patterns():
    det = PatternDetector(min_frequency=2)
    trace = _trace([EventType.APP_FOCUS, EventType.SAVE, EventType.SUBMIT], "s1")
    assert det.detect([trace]) == []


def test_repeated_pattern_detected():
    det = PatternDetector(window_size=2, min_frequency=2)
    t1 = _trace([EventType.APP_FOCUS, EventType.SAVE, EventType.SUBMIT], "s1")
    t2 = _trace([EventType.APP_FOCUS, EventType.SAVE, EventType.EXPORT], "s2")
    hypotheses = det.detect([t1, t2])
    patterns = [tuple(h.pattern) for h in hypotheses]
    assert (EventType.APP_FOCUS, EventType.SAVE) in patterns


def test_pattern_frequency_and_confidence():
    det = PatternDetector(window_size=2, min_frequency=2)
    traces = [
        _trace([EventType.APP_FOCUS, EventType.SAVE], f"s{i}") for i in range(4)
    ]
    hypotheses = det.detect(traces)
    assert hypotheses
    h = hypotheses[0]
    assert h.frequency == 4
    assert h.confidence == 1.0


def test_window_size_1():
    det = PatternDetector(window_size=1, min_frequency=2)
    t1 = _trace([EventType.SAVE], "s1")
    t2 = _trace([EventType.SAVE], "s2")
    hypotheses = det.detect([t1, t2])
    assert any(h.pattern == [EventType.SAVE] for h in hypotheses)


def test_invalid_window_size_raises():
    with pytest.raises(ValueError):
        PatternDetector(window_size=0)
