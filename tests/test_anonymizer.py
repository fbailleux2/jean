"""Tests for Anonymizer (jean-aggregator PII stripping)."""

from __future__ import annotations

from jean.aggregator.anonymizer import Anonymizer, _REDACTED
from jean.models import BusinessEvent, EventType


def _make_event(payload: dict) -> BusinessEvent:
    return BusinessEvent(
        type=EventType.ERP_EVENT,
        app="SAP",
        process_context="invoice-exception",
        session_id="sess-1",
        workstation_id="ws-test",
        payload=payload,
    )


def test_no_pii_unchanged():
    anon = Anonymizer()
    event = _make_event({"invoice_id": "INV-001", "amount": 1500})
    clean = anon.anonymize(event)
    assert clean.payload == {"invoice_id": "INV-001", "amount": 1500}


def test_email_redacted():
    anon = Anonymizer()
    event = _make_event({"email": "operator@company.com", "invoice_id": "INV-001"})
    clean = anon.anonymize(event)
    assert clean.payload["email"] == _REDACTED
    assert clean.payload["invoice_id"] == "INV-001"


def test_nested_pii_redacted():
    anon = Anonymizer()
    event = _make_event({"operator": {"name": "Alice", "badge": "B-001"}})
    clean = anon.anonymize(event)
    assert clean.payload["operator"]["name"] == _REDACTED
    assert clean.payload["operator"]["badge"] == "B-001"


def test_custom_pii_fields():
    anon = Anonymizer(extra_pii_fields={"badge_number"})
    event = _make_event({"badge_number": "B-001", "amount": 200})
    clean = anon.anonymize(event)
    assert clean.payload["badge_number"] == _REDACTED
    assert clean.payload["amount"] == 200


def test_anonymize_returns_new_event():
    anon = Anonymizer()
    event = _make_event({"name": "Bob"})
    clean = anon.anonymize(event)
    assert clean is not event
    assert clean.id == event.id


def test_anonymize_many():
    anon = Anonymizer()
    events = [
        _make_event({"email": "a@b.com"}),
        _make_event({"amount": 100}),
    ]
    cleaned = anon.anonymize_many(events)
    assert cleaned[0].payload["email"] == _REDACTED
    assert cleaned[1].payload["amount"] == 100
