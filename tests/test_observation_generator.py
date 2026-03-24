"""Tests for ObservationGenerator and ObservationDispatcher (ISC-30 to ISC-33)."""

from __future__ import annotations

import json

import httpx
import respx

from jean.aggregator.observation_generator import ObservationDispatcher, ObservationGenerator
from jean.models import EventType, FieldObservation, PatternHypothesis


def _make_hyp(confidence: float = 0.8, process_context: str = "test-proc") -> PatternHypothesis:
    return PatternHypothesis(
        pattern=[EventType.APP_FOCUS, EventType.SAVE, EventType.SUBMIT],
        frequency=3,
        confidence=confidence,
        source_trace_ids=["trace-1"],
        process_context=process_context,
    )


# ---------------------------------------------------------------------------
# ISC-30: hypotheses below threshold produce no observations
# ---------------------------------------------------------------------------


def test_below_threshold_no_observation():
    gen = ObservationGenerator(threshold=0.7)
    hyp = _make_hyp(confidence=0.5)
    result = gen.generate([hyp])
    assert result == []


def test_exactly_at_threshold_produces_observation():
    gen = ObservationGenerator(threshold=0.7)
    hyp = _make_hyp(confidence=0.7)
    result = gen.generate([hyp])
    assert len(result) == 1


def test_multiple_mixed_threshold():
    gen = ObservationGenerator(threshold=0.7)
    hypotheses = [
        _make_hyp(confidence=0.5),
        _make_hyp(confidence=0.8),
        _make_hyp(confidence=0.6),
        _make_hyp(confidence=0.9),
    ]
    result = gen.generate(hypotheses)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# ISC-31: hypotheses above threshold produce FieldObservation with correct fields
# ---------------------------------------------------------------------------


def test_observation_fields_correct():
    gen = ObservationGenerator(threshold=0.7)
    hyp = _make_hyp(confidence=0.85, process_context="invoice-exception")
    result = gen.generate([hyp])

    assert len(result) == 1
    obs = result[0]

    assert isinstance(obs, FieldObservation)
    assert obs.process_context == "invoice-exception"
    assert obs.declared_procedure == "Undocumented — auto-generated"
    assert "app_focus" in obs.observed_behavior
    assert obs.gap_score == 0.85
    assert hyp.id in obs.supporting_patterns


def test_observed_behavior_contains_event_sequence():
    gen = ObservationGenerator(threshold=0.5)
    hyp = _make_hyp(confidence=0.9)
    obs = gen.generate([hyp])[0]
    # event sequence is app_focus → save → submit
    assert "app_focus" in obs.observed_behavior
    assert "save" in obs.observed_behavior
    assert "submit" in obs.observed_behavior


# ---------------------------------------------------------------------------
# ISC-32: dispatch POSTs correct payload (respx mock)
# ---------------------------------------------------------------------------


async def test_dispatch_posts_correct_payload():
    obs = FieldObservation(
        process_context="test",
        declared_procedure="Undocumented — auto-generated",
        observed_behavior="Sequence detected",
        gap_score=0.8,
        supporting_patterns=["p1"],
    )
    dispatcher = ObservationDispatcher(validator_url="http://validator-test:8200")

    with respx.mock:
        route = respx.post("http://validator-test:8200/observations/register").mock(
            return_value=httpx.Response(201, json=obs.model_dump(mode="json"))
        )
        await dispatcher.dispatch(obs)

    assert route.called
    payload = route.calls[0].request.content
    parsed = json.loads(payload)
    assert parsed["id"] == obs.id
    assert parsed["process_context"] == "test"


# ---------------------------------------------------------------------------
# ISC-33: dispatch failure does not raise
# ---------------------------------------------------------------------------


async def test_dispatch_failure_does_not_raise():
    obs = FieldObservation(
        process_context="test",
        declared_procedure="Undocumented — auto-generated",
        observed_behavior="Sequence",
        gap_score=0.75,
        supporting_patterns=["p1"],
    )
    dispatcher = ObservationDispatcher(validator_url="http://unreachable-validator:9999")

    with respx.mock:
        respx.post("http://unreachable-validator:9999/observations/register").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        # Must not raise
        await dispatcher.dispatch(obs)


async def test_dispatch_skipped_when_no_url():
    obs = FieldObservation(
        process_context="test",
        declared_procedure="Undocumented — auto-generated",
        observed_behavior="Sequence",
        gap_score=0.75,
        supporting_patterns=["p1"],
    )
    dispatcher = ObservationDispatcher(validator_url="")
    # Must not raise, no HTTP call made
    await dispatcher.dispatch(obs)
