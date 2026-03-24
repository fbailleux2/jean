"""ERP Webhook Connector for jean-aggregator.

Exposes POST /erp/events — receives structured ERP events (invoices, orders,
exceptions) and maps them to BusinessEvent(type=ERP_EVENT).

Ingestion minimization policy (from VISION.md / MVP.md):
  Ingested: invoice_id, amount, status, timestamp, supplier_code
  Excluded: free-text notes, internal comments, attachments, personal data

The connector is intentionally generic (not SAP/Sage-specific).
ERP-specific adapters can inherit from this and override _map_payload().
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from jean.models import BusinessEvent, EventType

router = APIRouter(tags=["connectors"])

# ---------------------------------------------------------------------------
# ERP event schema — strict allowlist
# ---------------------------------------------------------------------------

_ALLOWED_FIELDS = frozenset(
    {"invoice_id", "amount", "status", "timestamp", "supplier_code"}
)


class ERPEventSchema(BaseModel):
    """Validated ERP event payload.

    Only the fields in _ALLOWED_FIELDS are accepted.
    Extra fields are silently dropped by Pydantic (model_config extra='ignore').
    """

    invoice_id: str = Field(description="Unique invoice identifier")
    amount: float = Field(description="Invoice amount (any currency)")
    status: str = Field(description="ERP processing status (e.g. EXCEPTION, PENDING)")
    timestamp: datetime = Field(description="Event timestamp from the ERP system")
    supplier_code: str = Field(description="Pseudonymous supplier identifier")

    model_config = {"extra": "ignore"}

    @field_validator("invoice_id", "supplier_code")
    @classmethod
    def non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v.strip()


class ERPIngestRequest(BaseModel):
    """Wrapper for a single ERP event ingest."""

    workstation_id: str = Field(
        default="erp-connector",
        description="Source system identifier (not a person)",
    )
    session_id: str = Field(
        description="Correlation ID for this ERP session / batch"
    )
    process_context: str = Field(
        default="invoice-exception",
        description="Business process this event belongs to",
    )
    event: ERPEventSchema


def _map_to_business_event(req: ERPIngestRequest) -> BusinessEvent:
    """Map an ERPIngestRequest to a BusinessEvent.

    Only the allowlisted fields are included in the payload.
    """
    return BusinessEvent(
        type=EventType.ERP_EVENT,
        app="erp-connector",
        timestamp=req.event.timestamp,
        process_context=req.process_context,
        session_id=req.session_id,
        workstation_id=req.workstation_id,
        payload={
            "invoice_id": req.event.invoice_id,
            "amount": req.event.amount,
            "status": req.event.status,
            "supplier_code": req.event.supplier_code,
        },
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


@router.post("/erp/events", status_code=201)
async def ingest_erp_event(req: ERPIngestRequest) -> dict:
    """Receive a structured ERP event and forward it to the aggregator pipeline.

    The event is converted to a BusinessEvent and returned for inspection.
    In production the aggregator's /ingest endpoint handles persistence —
    this connector just validates and maps.
    """
    event = _map_to_business_event(req)
    return {"event_id": event.id, "type": event.type, "payload": event.payload}
