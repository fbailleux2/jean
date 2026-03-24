"""Tests for KFabric mock service and HttpKFabricAdapter retry (ISC-23, ISC-24)."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

# Import the mock service app
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "kfabric-mock"))
from app import app as kfabric_app, _entries  # noqa: E402

from jean.corpus_feeder.adapter import HttpKFabricAdapter, FeedRequest
from jean.models import FieldObservation, ProcedureState
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch


# ---------------------------------------------------------------------------
# ISC-23: KFabric mock POST /ingest + GET /entries roundtrip
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_kfabric_state():
    """Reset kfabric-mock in-memory state before each test."""
    import app as kfabric_module  # type: ignore[import]
    kfabric_module._entries.clear()
    kfabric_module._sequence = 0
    yield
    kfabric_module._entries.clear()
    kfabric_module._sequence = 0


def _make_validated_obs() -> FieldObservation:
    return FieldObservation(
        process_context="invoice-exception",
        declared_procedure="Official procedure",
        observed_behavior="Field behavior",
        gap_score=0.75,
        supporting_patterns=["p1"],
        state=ProcedureState.VALIDATED,
        validated_at=datetime.now(timezone.utc),
        validated_by="test-validator",
    )


def test_kfabric_mock_health():
    client = TestClient(kfabric_app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_kfabric_mock_ingest_returns_entry_id():
    client = TestClient(kfabric_app)
    obs = _make_validated_obs()
    r = client.post("/ingest", json=obs.model_dump(mode="json"))
    assert r.status_code == 201
    body = r.json()
    assert "entry_id" in body
    assert body["entry_id"].startswith("kf-")
    assert body["status"] == "accepted"


def test_kfabric_mock_entries_list():
    client = TestClient(kfabric_app)
    obs = _make_validated_obs()
    ingest_r = client.post("/ingest", json=obs.model_dump(mode="json"))
    entry_id = ingest_r.json()["entry_id"]

    r = client.get("/entries")
    assert r.status_code == 200
    ids = [e["entry_id"] for e in r.json()]
    assert entry_id in ids


def test_kfabric_mock_get_entry():
    client = TestClient(kfabric_app)
    obs = _make_validated_obs()
    entry_id = client.post("/ingest", json=obs.model_dump(mode="json")).json()["entry_id"]

    r = client.get(f"/entries/{entry_id}")
    assert r.status_code == 200
    assert r.json()["entry_id"] == entry_id


def test_kfabric_mock_get_entry_404():
    client = TestClient(kfabric_app)
    r = client.get("/entries/nonexistent")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# ISC-24: HttpKFabricAdapter retries on 5xx (respx mock)
# ---------------------------------------------------------------------------


async def test_http_kfabric_adapter_retries_on_5xx():
    """submit() retries up to 3 times on 5xx errors, then succeeds."""
    obs = _make_validated_obs()
    req = FeedRequest(obs)
    adapter = HttpKFabricAdapter(base_url="http://kfabric-retry:8300")

    call_count = 0

    def _side_effect(request):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return httpx.Response(500, json={"error": "server error"})
        return httpx.Response(201, json={"entry_id": "kf-success-0001", "status": "accepted"})

    import jean.corpus_feeder.adapter as adapter_mod
    with respx.mock:
        respx.post("http://kfabric-retry:8300/ingest").mock(side_effect=_side_effect)
        adapter_mod.asyncio.sleep = AsyncMock()
        try:
            entry_id = await adapter.submit(req)
        finally:
            import asyncio
            adapter_mod.asyncio.sleep = asyncio.sleep

    assert entry_id == "kf-success-0001"
    assert call_count == 3


async def test_http_kfabric_adapter_raises_after_max_retries():
    """submit() raises RuntimeError after exhausting all retries."""
    obs = _make_validated_obs()
    req = FeedRequest(obs)
    adapter = HttpKFabricAdapter(base_url="http://kfabric-fail:8300")

    import jean.corpus_feeder.adapter as adapter_mod
    with respx.mock:
        respx.post("http://kfabric-fail:8300/ingest").mock(
            return_value=httpx.Response(503, json={"error": "unavailable"})
        )
        adapter_mod.asyncio.sleep = AsyncMock()
        try:
            with pytest.raises(RuntimeError, match="KFabric unreachable"):
                await adapter.submit(req)
        finally:
            import asyncio
            adapter_mod.asyncio.sleep = asyncio.sleep


async def test_http_kfabric_adapter_no_retry_on_4xx():
    """submit() raises ValueError immediately on 4xx (no retry)."""
    obs = _make_validated_obs()
    req = FeedRequest(obs)
    adapter = HttpKFabricAdapter(base_url="http://kfabric-4xx:8300")

    call_count = 0

    def _4xx(request):
        nonlocal call_count
        call_count += 1
        return httpx.Response(400, json={"error": "bad request"})

    with respx.mock:
        respx.post("http://kfabric-4xx:8300/ingest").mock(side_effect=_4xx)
        with pytest.raises(ValueError):
            await adapter.submit(req)

    assert call_count == 1  # No retry on 4xx
