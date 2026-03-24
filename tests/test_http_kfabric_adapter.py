"""Tests for HttpKFabricAdapter."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import respx
from httpx import Response

from jean.corpus_feeder.adapter import (
    FeedRequest,
    HttpKFabricAdapter,
    MockKFabricAdapter,
    make_adapter,
)
from jean.models import FieldObservation, ProcedureState


def _validated_obs(obs_id: str = "obs-http-1") -> FieldObservation:
    return FieldObservation(
        id=obs_id,
        process_context="invoice-exception",
        declared_procedure="Route > 1000 to manager",
        observed_behavior="Processed up to 5000 directly",
        gap_score=0.7,
        supporting_patterns=["p1"],
        state=ProcedureState.VALIDATED,
        validated_at=datetime.now(timezone.utc),
        validated_by="manager@co.com",
    )


@pytest.mark.asyncio
@respx.mock
async def test_submit_sends_correct_payload():
    url = "http://kfabric.local"
    route = respx.post(f"{url}/ingest").mock(
        return_value=Response(201, json={"entry_id": "kf-001"})
    )

    adapter = HttpKFabricAdapter(base_url=url)
    req = FeedRequest(_validated_obs())
    entry_id = await adapter.submit(req)

    assert route.called
    assert entry_id == "kf-001"


@pytest.mark.asyncio
@respx.mock
async def test_submit_4xx_raises_value_error():
    url = "http://kfabric.local"
    respx.post(f"{url}/ingest").mock(return_value=Response(422, text="Unprocessable"))

    adapter = HttpKFabricAdapter(base_url=url)
    with pytest.raises(ValueError, match="rejected"):
        await adapter.submit(FeedRequest(_validated_obs()))


@pytest.mark.asyncio
@respx.mock
async def test_submit_5xx_raises_runtime_error():
    url = "http://kfabric.local"
    respx.post(f"{url}/ingest").mock(return_value=Response(500, text="Internal error"))

    adapter = HttpKFabricAdapter(base_url=url)
    with pytest.raises(RuntimeError, match="server error"):
        await adapter.submit(FeedRequest(_validated_obs()))


@pytest.mark.asyncio
@respx.mock
async def test_health_returns_true_on_200():
    url = "http://kfabric.local"
    respx.get(f"{url}/health").mock(return_value=Response(200, json={"status": "ok"}))

    adapter = HttpKFabricAdapter(base_url=url)
    assert await adapter.health() is True


@pytest.mark.asyncio
@respx.mock
async def test_health_returns_false_on_error():
    url = "http://kfabric.local"
    respx.get(f"{url}/health").mock(return_value=Response(503))

    adapter = HttpKFabricAdapter(base_url=url)
    assert await adapter.health() is False


def test_http_adapter_requires_url():
    import os
    old = os.environ.pop("JEAN_KFABRIC_URL", None)
    try:
        with pytest.raises(ValueError, match="URL is required"):
            HttpKFabricAdapter()
    finally:
        if old:
            os.environ["JEAN_KFABRIC_URL"] = old


def test_make_adapter_returns_mock_by_default(monkeypatch):
    monkeypatch.delenv("JEAN_KFABRIC_URL", raising=False)
    adapter = make_adapter()
    assert isinstance(adapter, MockKFabricAdapter)


def test_make_adapter_returns_http_when_url_set(monkeypatch):
    monkeypatch.setenv("JEAN_KFABRIC_URL", "http://kfabric.local")
    adapter = make_adapter()
    assert isinstance(adapter, HttpKFabricAdapter)
    assert adapter.base_url == "http://kfabric.local"
