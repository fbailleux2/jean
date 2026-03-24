"""Tests for API key authentication (ISC-15 to ISC-18).

Tests cover aggregator and validator protected vs public routes.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jean.aggregator.api import app as aggregator_app
from jean.validator.api import app as validator_app, get_store, register_observation
from jean.models import FieldObservation


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_validator_store():
    get_store().clear()
    yield
    get_store().clear()


@pytest.fixture()
def aggregator_client():
    return TestClient(aggregator_app, raise_server_exceptions=True)


@pytest.fixture()
def validator_client():
    return TestClient(validator_app, raise_server_exceptions=True)


def _make_obs(obs_id: str = "auth-obs-1") -> FieldObservation:
    return FieldObservation(
        id=obs_id,
        process_context="auth-test",
        declared_procedure="Official procedure",
        observed_behavior="Actual behavior",
        gap_score=0.6,
        supporting_patterns=["p1"],
    )


def _ingest_payload():
    return [
        {
            "type": "app_focus",
            "app": "Excel",
            "process_context": "test",
            "session_id": "sess-1",
            "workstation_id": "ws-1",
            "payload": {},
            "schema_version": "1.0",
        }
    ]


# ---------------------------------------------------------------------------
# ISC-15: missing key on protected route → 401
# ---------------------------------------------------------------------------


def test_aggregator_ingest_missing_key_returns_401(aggregator_client, monkeypatch):
    monkeypatch.setenv("JEAN_API_KEY", "secret")
    r = aggregator_client.post("/ingest", json=_ingest_payload())
    assert r.status_code == 401


def test_validator_approve_missing_key_returns_401(validator_client, monkeypatch):
    monkeypatch.setenv("JEAN_API_KEY", "secret")
    register_observation(_make_obs("obs-1"))
    r = validator_client.post("/observations/obs-1/approve", json={"validator_id": "mgr"})
    assert r.status_code == 401


def test_validator_reject_missing_key_returns_401(validator_client, monkeypatch):
    monkeypatch.setenv("JEAN_API_KEY", "secret")
    register_observation(_make_obs("obs-1"))
    r = validator_client.post(
        "/observations/obs-1/reject",
        json={"rejection_reason": "test"},
    )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# ISC-16: wrong key on protected route → 403
# ---------------------------------------------------------------------------


def test_aggregator_ingest_wrong_key_returns_403(aggregator_client, monkeypatch):
    monkeypatch.setenv("JEAN_API_KEY", "secret")
    r = aggregator_client.post(
        "/ingest", json=_ingest_payload(), headers={"X-API-Key": "wrong"}
    )
    assert r.status_code == 403


def test_validator_approve_wrong_key_returns_403(validator_client, monkeypatch):
    monkeypatch.setenv("JEAN_API_KEY", "secret")
    register_observation(_make_obs("obs-1"))
    r = validator_client.post(
        "/observations/obs-1/approve",
        json={"validator_id": "mgr"},
        headers={"X-API-Key": "wrong"},
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# ISC-17: correct key on protected route → success
# ---------------------------------------------------------------------------


def test_aggregator_ingest_correct_key_succeeds(aggregator_client, monkeypatch):
    monkeypatch.setenv("JEAN_API_KEY", "secret")
    r = aggregator_client.post(
        "/ingest", json=_ingest_payload(), headers={"X-API-Key": "secret"}
    )
    assert r.status_code == 202


def test_validator_approve_correct_key_succeeds(validator_client, monkeypatch):
    monkeypatch.setenv("JEAN_API_KEY", "secret")
    register_observation(_make_obs("obs-1"))
    r = validator_client.post(
        "/observations/obs-1/approve",
        json={"validator_id": "mgr"},
        headers={"X-API-Key": "secret"},
    )
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# ISC-18: public routes accessible without key
# ---------------------------------------------------------------------------


def test_aggregator_health_public(aggregator_client, monkeypatch):
    monkeypatch.setenv("JEAN_API_KEY", "secret")
    r = aggregator_client.get("/health")
    assert r.status_code == 200


def test_aggregator_metrics_public(aggregator_client, monkeypatch):
    monkeypatch.setenv("JEAN_API_KEY", "secret")
    r = aggregator_client.get("/metrics")
    assert r.status_code == 200


def test_validator_observations_public(validator_client, monkeypatch):
    monkeypatch.setenv("JEAN_API_KEY", "secret")
    r = validator_client.get("/observations")
    assert r.status_code == 200


def test_validator_health_public(validator_client, monkeypatch):
    monkeypatch.setenv("JEAN_API_KEY", "secret")
    r = validator_client.get("/health")
    assert r.status_code == 200


def test_auth_disabled_when_env_unset(aggregator_client, monkeypatch):
    monkeypatch.delenv("JEAN_API_KEY", raising=False)
    r = aggregator_client.post("/ingest", json=_ingest_payload())
    assert r.status_code == 202
