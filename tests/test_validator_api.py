"""Tests for jean-validator API."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from jean.models import FieldObservation, ProcedureState
from jean.validator.api import app, get_store, register_observation

client = TestClient(app)


def _make_obs(obs_id: str = "obs-1") -> FieldObservation:
    return FieldObservation(
        id=obs_id,
        process_context="invoice-exception",
        declared_procedure="Route amounts > 1000 to manager",
        observed_behavior="Operators process up to 5000 directly",
        gap_score=0.7,
        supporting_patterns=["p1"],
    )


def setup_function():
    """Clear store before each test."""
    get_store().clear()


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_list_observations_empty():
    r = client.get("/observations")
    assert r.status_code == 200
    assert r.json() == []


def test_list_observations_returns_registered():
    register_observation(_make_obs("obs-1"))
    r = client.get("/observations")
    assert len(r.json()) == 1


def test_list_observations_filter_by_state():
    register_observation(_make_obs("obs-1"))  # OBSERVED by default
    r = client.get("/observations?state=observed")
    assert len(r.json()) == 1
    r2 = client.get("/observations?state=validated")
    assert len(r2.json()) == 0


def test_approve_sets_validated_state():
    register_observation(_make_obs("obs-1"))
    r = client.post("/observations/obs-1/approve", json={"validator_id": "manager@co.com"})
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "validated"
    assert body["validated_by"] == "manager@co.com"
    assert body["validated_at"] is not None


def test_approve_with_empty_validator_id_returns_422():
    register_observation(_make_obs("obs-1"))
    r = client.post("/observations/obs-1/approve", json={"validator_id": "  "})
    assert r.status_code == 422


def test_approve_unknown_id_returns_404():
    r = client.post("/observations/nonexistent/approve", json={"validator_id": "mgr"})
    assert r.status_code == 404


def test_approve_already_validated_returns_409():
    register_observation(_make_obs("obs-1"))
    client.post("/observations/obs-1/approve", json={"validator_id": "mgr"})
    r = client.post("/observations/obs-1/approve", json={"validator_id": "mgr"})
    assert r.status_code == 409


def test_reject_stores_reason():
    register_observation(_make_obs("obs-1"))
    r = client.post(
        "/observations/obs-1/reject",
        json={"rejection_reason": "Not enough evidence", "validator_id": "analyst"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "observed"  # stays OBSERVED
    assert body["metadata"]["rejection_reason"] == "Not enough evidence"


def test_reject_validated_returns_409():
    register_observation(_make_obs("obs-1"))
    client.post("/observations/obs-1/approve", json={"validator_id": "mgr"})
    r = client.post(
        "/observations/obs-1/reject",
        json={"rejection_reason": "Too late"},
    )
    assert r.status_code == 409
