"""Tests for FlowFabric bi-directional webhook (ISC-11, ISC-12, ISC-13)."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from jean.bridges.flowfabric import FlowFabricBridge, _MAX_RETRIES
from jean.models import FieldObservation, ProcedureState
from jean.validator.api import app, get_store, register_observation, set_pipeline
from unittest.mock import AsyncMock
from jean.corpus_feeder.pipeline import CorpusPipeline


@pytest.fixture(autouse=True)
def reset():
    get_store().clear()
    mock_pipeline = AsyncMock(spec=CorpusPipeline)
    mock_pipeline.run = AsyncMock(return_value="corpus-webhook-test")
    set_pipeline(mock_pipeline)
    yield
    get_store().clear()


def _make_obs(obs_id: str = "wh-obs-1") -> FieldObservation:
    return FieldObservation(
        id=obs_id,
        process_context="invoice-exception",
        declared_procedure="Route amounts > 1000 to manager",
        observed_behavior="Operators process up to 5000 directly",
        gap_score=0.7,
        supporting_patterns=["p1"],
    )


client = TestClient(app)


# ---------------------------------------------------------------------------
# ISC-11: notify() payload contains declared_procedure and callback_url
# ---------------------------------------------------------------------------


async def test_notify_payload_contains_full_fields():
    obs = _make_obs()
    bridge = FlowFabricBridge(
        webhook_url="http://ff-test:9000/gate",
        validator_url="http://jean-validator:8200",
    )
    # Use model_copy to set validated fields
    from datetime import datetime, timezone
    validated = obs.model_copy(update={
        "state": ProcedureState.VALIDATED,
        "validated_at": datetime.now(timezone.utc),
        "validated_by": "manager",
    })

    with respx.mock:
        route = respx.post("http://ff-test:9000/gate").mock(
            return_value=httpx.Response(200)
        )
        await bridge.notify(validated)

    assert route.called
    import json
    payload = json.loads(route.calls[0].request.content)
    assert payload["declared_procedure"] == "Route amounts > 1000 to manager"
    assert payload["observed_behavior"] == "Operators process up to 5000 directly"
    assert payload["callback_url"] == "http://jean-validator:8200/webhook/flowfabric"
    assert payload["observation_id"] == obs.id


# ---------------------------------------------------------------------------
# ISC-12: notify() retries on 5xx then succeeds on 3rd attempt
# ---------------------------------------------------------------------------


async def test_notify_retries_on_5xx_then_succeeds():
    from datetime import datetime, timezone
    obs = _make_obs("retry-obs")
    bridge = FlowFabricBridge(webhook_url="http://ff-retry:9000/gate")
    validated = obs.model_copy(update={
        "state": ProcedureState.VALIDATED,
        "validated_at": datetime.now(timezone.utc),
        "validated_by": "mgr",
    })

    call_count = 0

    def _side_effect(request):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return httpx.Response(503)
        return httpx.Response(200)

    with respx.mock:
        respx.post("http://ff-retry:9000/gate").mock(side_effect=_side_effect)
        # Patch sleep to avoid real delay
        import jean.bridges.flowfabric as ff_mod
        original_sleep = ff_mod.asyncio.sleep
        ff_mod.asyncio.sleep = AsyncMock()
        try:
            await bridge.notify(validated)
        finally:
            ff_mod.asyncio.sleep = original_sleep

    assert call_count == 3


async def test_notify_stops_after_max_retries():
    """notify() stops after _MAX_RETRIES and does not raise."""
    from datetime import datetime, timezone
    obs = _make_obs("exhaust-obs")
    bridge = FlowFabricBridge(webhook_url="http://ff-exhaust:9000/gate")
    validated = obs.model_copy(update={
        "state": ProcedureState.VALIDATED,
        "validated_at": datetime.now(timezone.utc),
        "validated_by": "mgr",
    })

    call_count = 0

    def _always_fail(request):
        nonlocal call_count
        call_count += 1
        return httpx.Response(503)

    import jean.bridges.flowfabric as ff_mod
    with respx.mock:
        respx.post("http://ff-exhaust:9000/gate").mock(side_effect=_always_fail)
        ff_mod.asyncio.sleep = AsyncMock()
        try:
            await bridge.notify(validated)  # Must not raise
        finally:
            ff_mod.asyncio.sleep = AsyncMock()

    assert call_count == _MAX_RETRIES


# ---------------------------------------------------------------------------
# ISC-13: /webhook/flowfabric approve → VALIDATED + corpus_entry_id
# ---------------------------------------------------------------------------


def test_webhook_approve():
    register_observation(_make_obs("wh-1"))
    r = client.post("/webhook/flowfabric", json={
        "observation_id": "wh-1",
        "action": "approve",
        "validator_id": "flowfabric-user",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "validated"
    assert body["validated_by"] == "flowfabric-user"
    assert body["metadata"]["corpus_entry_id"] == "corpus-webhook-test"


def test_webhook_reject():
    register_observation(_make_obs("wh-2"))
    r = client.post("/webhook/flowfabric", json={
        "observation_id": "wh-2",
        "action": "reject",
        "validator_id": "flowfabric-user",
        "reason": "Not enough evidence from field",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "observed"
    assert body["metadata"]["rejection_reason"] == "Not enough evidence from field"


def test_webhook_unknown_obs_returns_404():
    r = client.post("/webhook/flowfabric", json={
        "observation_id": "nonexistent",
        "action": "approve",
    })
    assert r.status_code == 404


def test_webhook_invalid_action_returns_422():
    register_observation(_make_obs("wh-3"))
    r = client.post("/webhook/flowfabric", json={
        "observation_id": "wh-3",
        "action": "invalidaction",
    })
    assert r.status_code == 422
