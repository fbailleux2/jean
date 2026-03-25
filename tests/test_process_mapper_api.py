"""REST API tests for process_mapper endpoints using FastAPI TestClient."""

from __future__ import annotations

import pytest
import jean.process_mapper.api as api_module
from fastapi.testclient import TestClient
from fastapi import FastAPI

from jean.models import ProcessDefinition
from jean.process_mapper.api import router as process_router
from jean.process_mapper.store import ProcessStore


@pytest.fixture()
def client() -> TestClient:
    """Return a TestClient with a fresh ProcessStore for each test."""
    fresh_store = ProcessStore()
    api_module._store = fresh_store

    app = FastAPI()
    app.include_router(process_router)
    return TestClient(app)


def _process_payload(
    name: str = "invoice-exception-handling",
    context: str = "invoice-exception",
) -> dict:
    return {
        "name": name,
        "process_context": context,
        "trigger": "incoming customer email",
        "description": "Handles invoice exceptions",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_create_process_201(client: TestClient) -> None:
    payload = _process_payload()
    resp = client.post("/processes", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == payload["name"]
    assert data["process_context"] == payload["process_context"]
    assert "id" in data
    assert data["version"] == "1.0.0"


def test_list_processes_empty(client: TestClient) -> None:
    resp = client.get("/processes")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_process_404(client: TestClient) -> None:
    resp = client.get("/processes/nonexistent-id")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Process not found"


def test_get_process_found(client: TestClient) -> None:
    payload = _process_payload()
    create_resp = client.post("/processes", json=payload)
    assert create_resp.status_code == 201
    process_id = create_resp.json()["id"]

    get_resp = client.get(f"/processes/{process_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == process_id
    assert get_resp.json()["name"] == payload["name"]


def test_update_process_bumps_version(client: TestClient) -> None:
    payload = _process_payload()
    create_resp = client.post("/processes", json=payload)
    assert create_resp.status_code == 201
    process_id = create_resp.json()["id"]

    update_resp = client.put(
        f"/processes/{process_id}",
        json={"description": "Updated description"},
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert updated["description"] == "Updated description"
    assert updated["version"] == "1.1.0"


def test_update_process_404(client: TestClient) -> None:
    resp = client.put("/processes/nonexistent-id", json={"description": "test"})
    assert resp.status_code == 404


def test_delete_process_204(client: TestClient) -> None:
    payload = _process_payload()
    create_resp = client.post("/processes", json=payload)
    assert create_resp.status_code == 201
    process_id = create_resp.json()["id"]

    delete_resp = client.delete(f"/processes/{process_id}")
    assert delete_resp.status_code == 204

    get_resp = client.get(f"/processes/{process_id}")
    assert get_resp.status_code == 404


def test_delete_nonexistent_404(client: TestClient) -> None:
    resp = client.delete("/processes/nonexistent-id")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Process not found"
