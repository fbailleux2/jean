"""Tests for KFabric auth header (JEAN_KFABRIC_API_KEY) and validator startup health check."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from jean.corpus_feeder.adapter import HttpKFabricAdapter, make_adapter
from jean.models import FieldObservation, ProcedureState


# ---------------------------------------------------------------------------
# Fixture — minimal valid VALIDATED FieldObservation
# ---------------------------------------------------------------------------

@pytest.fixture()
def validated_obs() -> FieldObservation:
    return FieldObservation(
        process_context="invoice-exception",
        declared_procedure="Route >1000 to manager",
        observed_behavior="Operators process up to 5000 directly",
        gap_score=0.85,
        supporting_patterns=["p1", "p2"],
        state=ProcedureState.VALIDATED,
        validated_at=datetime.now(timezone.utc),
        validated_by="user@test.com",
    )


# ---------------------------------------------------------------------------
# _auth_headers
# ---------------------------------------------------------------------------

def test_auth_headers_present_when_api_key_set():
    """When api_key is provided, Authorization: Bearer header is returned."""
    adapter = HttpKFabricAdapter(base_url="http://kfabric:8300", api_key="secret-42")
    assert adapter._auth_headers() == {"Authorization": "Bearer secret-42"}


def test_auth_headers_empty_when_no_api_key():
    """Without api_key, _auth_headers returns empty dict."""
    adapter = HttpKFabricAdapter(base_url="http://kfabric:8300")
    assert adapter._auth_headers() == {}


def test_api_key_read_from_env(monkeypatch):
    """JEAN_KFABRIC_API_KEY env var is used as fallback."""
    monkeypatch.setenv("JEAN_KFABRIC_API_KEY", "env-key-99")
    adapter = HttpKFabricAdapter(base_url="http://kfabric:8300")
    assert adapter.api_key == "env-key-99"
    assert adapter._auth_headers() == {"Authorization": "Bearer env-key-99"}


def test_explicit_api_key_overrides_env(monkeypatch):
    """Constructor api_key= takes precedence over env var."""
    monkeypatch.setenv("JEAN_KFABRIC_API_KEY", "env-key")
    adapter = HttpKFabricAdapter(base_url="http://kfabric:8300", api_key="explicit-key")
    assert adapter.api_key == "explicit-key"


# ---------------------------------------------------------------------------
# submit() sends auth header
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_submit_sends_auth_header(validated_obs):
    """submit() includes Authorization header in POST /ingest request."""
    from jean.corpus_feeder.adapter import FeedRequest

    req = FeedRequest(validated_obs)
    adapter = HttpKFabricAdapter(base_url="http://kfabric:8300", api_key="tok-abc")

    with respx.mock(base_url="http://kfabric:8300") as mock:
        mock.post("/ingest").mock(
            return_value=httpx.Response(200, json={"entry_id": "kf-0001"})
        )
        entry_id = await adapter.submit(req)
        assert entry_id == "kf-0001"
        sent_headers = mock.calls[0].request.headers

    assert sent_headers.get("authorization") == "Bearer tok-abc"


@pytest.mark.asyncio
async def test_submit_no_auth_header_when_no_key(validated_obs):
    """submit() sends no Authorization header when api_key is not set."""
    from jean.corpus_feeder.adapter import FeedRequest

    req = FeedRequest(validated_obs)
    adapter = HttpKFabricAdapter(base_url="http://kfabric:8300")

    with respx.mock(base_url="http://kfabric:8300") as mock:
        mock.post("/ingest").mock(
            return_value=httpx.Response(200, json={"entry_id": "kf-0002"})
        )
        await adapter.submit(req)
        sent_headers = mock.calls[0].request.headers

    assert "authorization" not in sent_headers


# ---------------------------------------------------------------------------
# health() sends auth header
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_sends_auth_header():
    """health() includes Authorization header in GET /health request."""
    adapter = HttpKFabricAdapter(base_url="http://kfabric:8300", api_key="tok-health")

    with respx.mock(base_url="http://kfabric:8300") as mock:
        mock.get("/health").mock(return_value=httpx.Response(200, json={"status": "ok"}))
        ok = await adapter.health()
        assert ok is True
        sent_headers = mock.calls[0].request.headers

    assert sent_headers.get("authorization") == "Bearer tok-health"


@pytest.mark.asyncio
async def test_health_returns_false_on_error():
    """health() returns False when KFabric is unreachable."""
    adapter = HttpKFabricAdapter(base_url="http://kfabric-unreachable:9999")

    with respx.mock(base_url="http://kfabric-unreachable:9999") as mock:
        mock.get("/health").mock(side_effect=httpx.ConnectError("refused"))
        ok = await adapter.health()

    assert ok is False


# ---------------------------------------------------------------------------
# make_adapter with JEAN_KFABRIC_API_KEY
# ---------------------------------------------------------------------------

def test_make_adapter_passes_api_key_to_http_adapter(monkeypatch):
    """make_adapter() creates HttpKFabricAdapter with api_key when both env vars set."""
    monkeypatch.setenv("JEAN_KFABRIC_URL", "http://kfabric:8300")
    monkeypatch.setenv("JEAN_KFABRIC_API_KEY", "prod-key")
    adapter = make_adapter()
    assert isinstance(adapter, HttpKFabricAdapter)
    assert adapter.api_key == "prod-key"


# ---------------------------------------------------------------------------
# Validator startup health check — verify adapter.health() is called
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_validator_lifespan_calls_kfabric_health(monkeypatch):
    """Validator lifespan calls KFabric health() during startup."""
    monkeypatch.delenv("JEAN_KFABRIC_URL", raising=False)
    monkeypatch.delenv("JEAN_KFABRIC_API_KEY", raising=False)
    monkeypatch.delenv("JEAN_OBS_STORE_PATH", raising=False)

    from jean.corpus_feeder.adapter import MockKFabricAdapter

    mock_adapter = MockKFabricAdapter()
    health_calls: list[bool] = []

    original_health = mock_adapter.health

    async def _tracked_health() -> bool:
        result = await original_health()
        health_calls.append(result)
        return result

    mock_adapter.health = _tracked_health  # type: ignore[method-assign]

    with patch("jean.validator.api.make_adapter", return_value=mock_adapter):
        from jean.validator import api as val_api

        lifespan_gen = val_api._lifespan(val_api.app)
        await lifespan_gen.__aenter__()
        await lifespan_gen.__aexit__(None, None, None)

    assert len(health_calls) == 1
    assert health_calls[0] is True  # MockKFabricAdapter always healthy
