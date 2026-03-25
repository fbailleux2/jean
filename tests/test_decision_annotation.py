"""Tests for the DecisionAnnotation model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jean.models import DecisionAnnotation


# ---------------------------------------------------------------------------
# test_valid_minimal
# ---------------------------------------------------------------------------


def test_valid_minimal():
    """Only text and app are required; model should be valid."""
    annotation = DecisionAnnotation(text="escalate to manager", app="SAP")
    assert annotation.text == "escalate to manager"
    assert annotation.app == "SAP"
    assert annotation.condition is None
    assert annotation.action is None
    assert annotation.related_event_id is None


# ---------------------------------------------------------------------------
# test_with_condition_and_action
# ---------------------------------------------------------------------------


def test_with_condition_and_action():
    """Structured rule with condition and action is stored correctly."""
    annotation = DecisionAnnotation(
        text="if customer is VIP → move to priority queue",
        condition="customer_status=VIP",
        action="priority=high",
        app="CRM",
    )
    assert annotation.condition == "customer_status=VIP"
    assert annotation.action == "priority=high"
    assert annotation.text == "if customer is VIP → move to priority queue"
    assert annotation.app == "CRM"


# ---------------------------------------------------------------------------
# test_condition_optional
# ---------------------------------------------------------------------------


def test_condition_optional():
    """condition=None is valid and does not raise."""
    annotation = DecisionAnnotation(
        text="send to compliance review",
        condition=None,
        action="route=compliance",
        app="WorkflowApp",
    )
    assert annotation.condition is None
    assert annotation.action == "route=compliance"


def test_action_optional():
    """action=None is valid and does not raise."""
    annotation = DecisionAnnotation(
        text="flag for supervisor",
        condition="amount>10000",
        action=None,
        app="ERP",
    )
    assert annotation.action is None
    assert annotation.condition == "amount>10000"


# ---------------------------------------------------------------------------
# test_schema_version_default
# ---------------------------------------------------------------------------


def test_schema_version_default():
    """schema_version defaults to '1.0' when not provided."""
    annotation = DecisionAnnotation(text="apply discount", app="POS")
    assert annotation.schema_version == "1.0"


def test_schema_version_explicit():
    """schema_version can be set explicitly."""
    annotation = DecisionAnnotation(text="apply discount", app="POS", schema_version="2.0")
    assert annotation.schema_version == "2.0"


# ---------------------------------------------------------------------------
# test_related_event_id
# ---------------------------------------------------------------------------


def test_related_event_id_can_be_set():
    """related_event_id links the annotation to a specific BusinessEvent."""
    event_id = "evt-abc-123"
    annotation = DecisionAnnotation(
        text="override credit limit",
        app="CRM",
        related_event_id=event_id,
    )
    assert annotation.related_event_id == event_id


def test_related_event_id_default_none():
    """related_event_id is None by default."""
    annotation = DecisionAnnotation(text="close ticket", app="Helpdesk")
    assert annotation.related_event_id is None


# ---------------------------------------------------------------------------
# test_missing_required_fields
# ---------------------------------------------------------------------------


def test_missing_text_raises():
    """Omitting required 'text' field must raise ValidationError."""
    with pytest.raises(ValidationError):
        DecisionAnnotation(app="SAP")  # type: ignore[call-arg]


def test_missing_app_raises():
    """Omitting required 'app' field must raise ValidationError."""
    with pytest.raises(ValidationError):
        DecisionAnnotation(text="some decision")  # type: ignore[call-arg]
