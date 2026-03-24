"""End-to-end integration test for the full Jean pipeline (ISC-1 to ISC-12).

Flow:
  LocalBuffer (agent) → aggregator /ingest → PatternDetector → ObservationGenerator
  → validator /observations/register → /observations/{id}/approve → CorpusPipeline

All components run in-process. No external services required.
CorpusPipeline is mocked to avoid requiring a real KFabric instance.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import jean.aggregator.api as agg_module
from jean.aggregator.api import app as aggregator_app
from jean.aggregator.store import InMemoryStore
from jean.agent.buffer import LocalBuffer
from jean.models import BusinessEvent, EventType, FieldObservation
from jean.validator.api import app as validator_app, get_store, set_pipeline
from jean.validator.store import InMemoryObservationStore
from jean.corpus_feeder.pipeline import CorpusPipeline


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_aggregator_state():
    """Reset aggregator module-level state before each integration test."""
    agg_module._store = InMemoryStore()
    agg_module._patterns = []
    yield
    agg_module._store = InMemoryStore()
    agg_module._patterns = []


@pytest.fixture(autouse=True)
def reset_validator_state():
    """Reset validator store and mock the pipeline before each test."""
    # Use a fresh InMemoryObservationStore
    from jean.validator import api as val_module
    val_module._store = InMemoryObservationStore()

    # Mock the CorpusPipeline to return a deterministic corpus ID
    mock_pipeline = AsyncMock(spec=CorpusPipeline)
    mock_pipeline.run = AsyncMock(return_value="corpus-entry-integration-test")
    set_pipeline(mock_pipeline)

    yield

    val_module._store = InMemoryObservationStore()


@pytest.fixture()
def aggregator_client():
    return TestClient(aggregator_app, raise_server_exceptions=True)


@pytest.fixture()
def validator_client():
    return TestClient(validator_app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_events(session_id: str, count: int = 6) -> list[dict[str, Any]]:
    """Create a repeating APP_FOCUS → SAVE → SUBMIT sequence."""
    pattern = [EventType.APP_FOCUS, EventType.SAVE, EventType.SUBMIT]
    events = []
    for i in range(count):
        events.append({
            "type": pattern[i % 3].value,
            "app": ["Excel", "Excel", "SAP"][i % 3],
            "process_context": "invoice-exception",
            "session_id": session_id,
            "workstation_id": "ws-integration-001",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {},
            "schema_version": "1.0",
        })
    return events


# ---------------------------------------------------------------------------
# ISC-4: Push 12+ events into LocalBuffer
# ---------------------------------------------------------------------------


async def test_localbuffer_stores_events(tmp_path):
    """Agent LocalBuffer accepts and stores events offline."""
    buf_path = str(tmp_path / "integration.db")
    async with LocalBuffer(db_path=buf_path) as buf:
        for raw in _make_events("sess-integration-1", count=12):
            event = BusinessEvent(
                type=raw["type"],
                app=raw["app"],
                process_context=raw["process_context"],
                session_id=raw["session_id"],
                workstation_id=raw["workstation_id"],
            )
            await buf.push(event)

        count = await buf.pending_count()
        assert count == 12


# ---------------------------------------------------------------------------
# ISC-5, ISC-6: Buffer flushed to aggregator; patterns detected
# ---------------------------------------------------------------------------


def test_ingest_creates_patterns(aggregator_client):
    """Sending repeating events from multiple sessions generates PatternHypotheses."""
    # Two separate sessions with the same APP_FOCUS → SAVE → SUBMIT pattern
    for session_id in ["sess-A", "sess-B", "sess-C"]:
        r = aggregator_client.post("/ingest", json=_make_events(session_id, count=6))
        assert r.status_code == 202

    r = aggregator_client.get("/patterns")
    assert r.status_code == 200
    patterns = r.json()
    assert len(patterns) >= 1
    # Verify the detected pattern involves our event types
    event_types_in_patterns = {e for p in patterns for e in p["pattern"]}
    assert "app_focus" in event_types_in_patterns or "save" in event_types_in_patterns


# ---------------------------------------------------------------------------
# ISC-7: ObservationGenerator produces observations from patterns
# ---------------------------------------------------------------------------


def test_observation_generator_produces_observations(aggregator_client):
    """ObservationGenerator converts high-confidence patterns to FieldObservations."""
    from jean.aggregator.observation_generator import ObservationGenerator
    from jean.models import PatternHypothesis

    # Inject events from 3 sessions to get confidence = 1.0
    for session_id in ["sess-A", "sess-B", "sess-C"]:
        aggregator_client.post("/ingest", json=_make_events(session_id, count=6))

    patterns = [p for p in agg_module._patterns]
    assert len(patterns) >= 1

    # Generator with threshold 0.5 should produce at least 1 observation
    gen = ObservationGenerator(threshold=0.5)
    observations = gen.generate(patterns)
    assert len(observations) >= 1

    obs = observations[0]
    assert isinstance(obs, FieldObservation)
    assert obs.declared_procedure == "Undocumented — auto-generated"
    assert obs.gap_score >= 0.5


# ---------------------------------------------------------------------------
# ISC-8, ISC-9: Observations registered with validator
# ---------------------------------------------------------------------------


def test_observation_registered_in_validator(aggregator_client, validator_client):
    """ObservationGenerator output can be registered with the validator."""
    from jean.aggregator.observation_generator import ObservationGenerator

    for session_id in ["sess-A", "sess-B", "sess-C"]:
        aggregator_client.post("/ingest", json=_make_events(session_id, count=6))

    gen = ObservationGenerator(threshold=0.5)
    observations = gen.generate(agg_module._patterns)
    assert len(observations) >= 1

    obs = observations[0]
    r = validator_client.post(
        "/observations/register",
        content=obs.model_dump_json(),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 201
    assert r.json()["id"] == obs.id

    r2 = validator_client.get("/observations")
    assert r2.status_code == 200
    registered_ids = [o["id"] for o in r2.json()]
    assert obs.id in registered_ids


# ---------------------------------------------------------------------------
# ISC-10, ISC-11: Approve observation → VALIDATED + corpus_entry_id
# ---------------------------------------------------------------------------


def test_approve_observation_validates_and_stores_corpus_id(
    aggregator_client, validator_client
):
    """Full pipeline: ingest → patterns → obs → register → approve → corpus ID."""
    from jean.aggregator.observation_generator import ObservationGenerator

    for session_id in ["sess-A", "sess-B", "sess-C"]:
        aggregator_client.post("/ingest", json=_make_events(session_id, count=6))

    gen = ObservationGenerator(threshold=0.5)
    obs = gen.generate(agg_module._patterns)[0]

    validator_client.post(
        "/observations/register",
        content=obs.model_dump_json(),
        headers={"Content-Type": "application/json"},
    )

    r = validator_client.post(
        f"/observations/{obs.id}/approve",
        json={"validator_id": "integration-tester"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "validated"
    assert body["validated_by"] == "integration-tester"
    assert body["validated_at"] is not None
    assert body["metadata"].get("corpus_entry_id") == "corpus-entry-integration-test"


# ---------------------------------------------------------------------------
# ISC-12: Full pipeline produces no errors
# ---------------------------------------------------------------------------


def test_full_pipeline_no_errors(aggregator_client, validator_client):
    """Complete flow from ingest to approval runs without unhandled exceptions."""
    from jean.aggregator.observation_generator import ObservationGenerator

    # Agent: ingest events
    for session_id in ["sess-X", "sess-Y", "sess-Z"]:
        r = aggregator_client.post("/ingest", json=_make_events(session_id, count=6))
        assert r.status_code == 202
        assert r.json()["accepted"] > 0

    # Aggregator: patterns available
    patterns_resp = aggregator_client.get("/patterns")
    assert patterns_resp.status_code == 200
    patterns = patterns_resp.json()
    assert len(patterns) > 0

    # ObservationGenerator: generate observations
    gen = ObservationGenerator(threshold=0.5)
    obs_list = gen.generate(agg_module._patterns)
    assert len(obs_list) > 0

    # Validator: register + approve all
    for obs in obs_list:
        r = validator_client.post(
            "/observations/register",
            content=obs.model_dump_json(),
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 201

    r = validator_client.get("/observations")
    assert len(r.json()) == len(obs_list)

    obs_id = obs_list[0].id
    r = validator_client.post(
        f"/observations/{obs_id}/approve",
        json={"validator_id": "qa-bot"},
    )
    assert r.status_code == 200
    assert r.json()["state"] == "validated"


def test_process_context_filter_in_patterns(aggregator_client):
    """GET /patterns?process_context only returns patterns for that context."""
    for session_id in ["sess-1", "sess-2", "sess-3"]:
        aggregator_client.post("/ingest", json=_make_events(session_id, count=6))

    r = aggregator_client.get("/patterns?process_context=invoice-exception")
    assert r.status_code == 200
    for p in r.json():
        assert p["process_context"] == "invoice-exception"
