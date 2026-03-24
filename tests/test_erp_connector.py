"""Tests for ERP webhook connector."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jean.connectors.erp_webhook import ERPEventSchema, ERPIngestRequest, _map_to_business_event
from jean.models import EventType


# We test the router directly via the aggregator app
from jean.aggregator.api import app

client = TestClient(app)


def _valid_payload() -> dict:
    return {
        "session_id": "erp-batch-001",
        "process_context": "invoice-exception",
        "event": {
            "invoice_id": "INV-001",
            "amount": 1500.0,
            "status": "EXCEPTION",
            "timestamp": "2026-03-24T10:00:00+00:00",
            "supplier_code": "SUP-042",
        },
    }


def test_valid_erp_event_returns_201():
    resp = client.post("/connectors/erp/events", json=_valid_payload())
    assert resp.status_code == 201


def test_valid_erp_event_maps_to_erp_event_type():
    resp = client.post("/connectors/erp/events", json=_valid_payload())
    assert resp.json()["type"] == EventType.ERP_EVENT


def test_valid_erp_event_payload_contains_allowlisted_fields():
    resp = client.post("/connectors/erp/events", json=_valid_payload())
    payload = resp.json()["payload"]
    assert "invoice_id" in payload
    assert "amount" in payload
    assert "status" in payload
    assert "supplier_code" in payload


def test_extra_fields_excluded():
    data = _valid_payload()
    data["event"]["operator_name"] = "Alice"  # PII — should be dropped
    data["event"]["internal_note"] = "urgent"  # excluded field
    resp = client.post("/connectors/erp/events", json=data)
    assert resp.status_code == 201
    payload = resp.json()["payload"]
    assert "operator_name" not in payload
    assert "internal_note" not in payload


def test_missing_required_field_returns_422():
    data = _valid_payload()
    del data["event"]["invoice_id"]
    resp = client.post("/connectors/erp/events", json=data)
    assert resp.status_code == 422


def test_empty_invoice_id_returns_422():
    data = _valid_payload()
    data["event"]["invoice_id"] = "   "
    resp = client.post("/connectors/erp/events", json=data)
    assert resp.status_code == 422


def test_map_to_business_event_type():
    req = ERPIngestRequest(
        session_id="s1",
        process_context="invoice-exception",
        event=ERPEventSchema(
            invoice_id="INV-001",
            amount=500.0,
            status="PENDING",
            timestamp="2026-01-01T00:00:00+00:00",
            supplier_code="SUP-001",
        ),
    )
    event = _map_to_business_event(req)
    assert event.type == EventType.ERP_EVENT
    assert event.payload["invoice_id"] == "INV-001"
