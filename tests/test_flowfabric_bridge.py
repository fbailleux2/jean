"""Tests for FlowFabricBridge."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import respx
from httpx import Response

from jean.bridges.flowfabric import FlowFabricBridge
from jean.models import FieldObservation, ProcedureState


def _validated_obs() -> FieldObservation:
    return FieldObservation(
        id="obs-bridge-1",
        process_context="invoice-exception",
        declared_procedure="Route > 1000 to manager",
        observed_behavior="Processed up to 5000 directly",
        gap_score=0.65,
        supporting_patterns=["p1"],
        state=ProcedureState.VALIDATED,
        validated_at=datetime.now(timezone.utc),
        validated_by="manager@co.com",
    )


@pytest.mark.asyncio
async def test_bridge_no_op_when_not_configured():
    """Bridge is silent when no webhook URL is set."""
    bridge = FlowFabricBridge(webhook_url=None)
    assert not bridge.is_configured()
    # Should not raise or make any HTTP call
    await bridge.notify(_validated_obs())


@pytest.mark.asyncio
@respx.mock
async def test_bridge_sends_correct_payload():
    url = "http://flowfabric.local/webhook/jean"
    route = respx.post(url).mock(return_value=Response(200))

    bridge = FlowFabricBridge(webhook_url=url)
    obs = _validated_obs()
    await bridge.notify(obs)

    assert route.called
    sent = route.calls[0].request
    import json
    payload = json.loads(sent.content)
    assert payload["observation_id"] == obs.id
    assert payload["process_context"] == obs.process_context
    assert payload["gap_score"] == obs.gap_score
    assert payload["validated_by"] == obs.validated_by


@pytest.mark.asyncio
@respx.mock
async def test_bridge_http_failure_does_not_raise():
    """Bridge swallows HTTP errors — fire-and-forget."""
    url = "http://flowfabric.local/webhook/jean"
    respx.post(url).mock(return_value=Response(500))

    bridge = FlowFabricBridge(webhook_url=url)
    # Should not raise despite 500
    await bridge.notify(_validated_obs())


@pytest.mark.asyncio
async def test_bridge_env_var(monkeypatch):
    monkeypatch.setenv("JEAN_FLOWFABRIC_WEBHOOK", "http://ff.local/hook")
    bridge = FlowFabricBridge()
    assert bridge.is_configured()
    assert bridge.webhook_url == "http://ff.local/hook"


@pytest.mark.asyncio
@respx.mock
async def test_approve_endpoint_includes_corpus_id(monkeypatch):
    """Integration: approve endpoint returns corpus_entry_id in metadata."""
    from fastapi.testclient import TestClient
    from jean.corpus_feeder.adapter import MockKFabricAdapter
    from jean.corpus_feeder.pipeline import CorpusPipeline
    from jean.validator import api as validator_api
    from jean.models import FieldObservation

    # Use fresh store
    validator_api.get_store().clear()

    # Inject mock pipeline and no-op bridge
    validator_api.set_pipeline(CorpusPipeline(adapter=MockKFabricAdapter()))
    validator_api.set_bridge(FlowFabricBridge(webhook_url=None))

    obs = FieldObservation(
        id="obs-int-1",
        process_context="invoice-exception",
        declared_procedure="x",
        observed_behavior="y",
        gap_score=0.5,
        supporting_patterns=["p1"],
    )
    validator_api.register_observation(obs)

    client = TestClient(validator_api.app)
    resp = client.post("/observations/obs-int-1/approve", json={"validator_id": "mgr"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "validated"
    assert "corpus_entry_id" in body["metadata"]
