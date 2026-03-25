"""Core data models for Jean.

These models represent the lifecycle of a field observation:
  BusinessEvent → SessionTrace → PatternHypothesis → FieldObservation
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class EventType(StrEnum):
    """Structural action types that Jean captures."""

    APP_FOCUS = "app_focus"          # User switched active application
    APP_BLUR = "app_blur"            # Application lost focus
    SAVE = "save"                    # Save action (Ctrl+S, File→Save)
    SUBMIT = "submit"                # Form / workflow submission
    EXPORT = "export"                # Export / download action
    PRINT = "print"                  # Print action
    ANNOTATION = "annotation"       # Explicit operator annotation
    ERP_EVENT = "erp_event"         # Inbound event from ERP / external system
    CUSTOM = "custom"               # Any other captured action
    CLIPBOARD_COPY = "clipboard_copy"    # Ctrl+C detected
    CLIPBOARD_PASTE = "clipboard_paste"  # Ctrl+V detected — may be cross-app
    TOOL_SWITCH = "tool_switch"          # High-friction repeated transition between apps
    IRRITANT = "irritant"                # Operator-flagged irritant


class ProcedureState(StrEnum):
    """Seven states for any observed procedure (from FlowFabric VISION)."""

    DECLARED = "declared"
    OBSERVED = "observed"
    VALIDATED = "validated"
    RECOMMENDED = "recommended"
    AUTOMATABLE = "automatable"
    FORBIDDEN = "forbidden"
    TOLERATED_LOCAL_VARIANT = "tolerated_local_variant"


# ---------------------------------------------------------------------------
# BusinessEvent — the atomic unit of observation
# ---------------------------------------------------------------------------


class BusinessEvent(BaseModel):
    """A single discrete event captured in a business context.

    Jean is event-driven, not a continuous stream.  Each BusinessEvent
    represents a structural action (save, submit, app-switch…) tied to a
    specific business process context.
    """

    id: str = Field(default_factory=_uuid)
    type: EventType
    app: str = Field(description="Application name or identifier")
    timestamp: datetime = Field(default_factory=_now)
    process_context: str = Field(
        description="Business process this event belongs to (e.g. 'invoice-exception')"
    )
    session_id: str = Field(description="Identifier of the originating session trace")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Event-specific data — must NOT contain PII (anonymized by aggregator)",
    )
    workstation_id: str = Field(
        description="Pseudonymous workstation identifier (never a username)"
    )
    schema_version: str = Field(default="1.0")

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# SessionTrace — a sequence of events within one working session
# ---------------------------------------------------------------------------


class SessionTrace(BaseModel):
    """A time-bounded sequence of BusinessEvents for one operator session.

    Produced by jean-agent; ingested by jean-aggregator.
    """

    session_id: str = Field(default_factory=_uuid)
    workstation_id: str
    process_context: str
    started_at: datetime = Field(default_factory=_now)
    ended_at: datetime | None = None
    events: list[BusinessEvent] = Field(default_factory=list)
    schema_version: str = Field(default="1.0")

    @field_validator("ended_at")
    @classmethod
    def ended_after_started(cls, v: datetime | None, info: Any) -> datetime | None:
        if v is not None and "started_at" in info.data:
            if v < info.data["started_at"]:
                raise ValueError("ended_at must be after started_at")
        return v

    @property
    def duration_seconds(self) -> float | None:
        if self.ended_at is None:
            return None
        return (self.ended_at - self.started_at).total_seconds()


# ---------------------------------------------------------------------------
# PatternHypothesis — a recurring sequence detected across sessions
# ---------------------------------------------------------------------------


class PatternHypothesis(BaseModel):
    """A recurring event sequence detected by jean-aggregator.

    A PatternHypothesis is always at the OBSERVED truth level until
    a human validates it via jean-validator.
    """

    id: str = Field(default_factory=_uuid)
    pattern: list[EventType] = Field(description="Ordered sequence of event types")
    frequency: int = Field(ge=1, description="Number of times this pattern was observed")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score [0, 1]")
    source_trace_ids: list[str] = Field(
        description="Session trace IDs this pattern was extracted from"
    )
    process_context: str
    first_seen: datetime = Field(default_factory=_now)
    last_seen: datetime = Field(default_factory=_now)
    state: ProcedureState = Field(default=ProcedureState.OBSERVED)
    schema_version: str = Field(default="1.0")

    @field_validator("source_trace_ids")
    @classmethod
    def at_least_one_source(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("source_trace_ids must contain at least one trace ID")
        return v


# ---------------------------------------------------------------------------
# FieldObservation — the gap between declared and observed procedure
# ---------------------------------------------------------------------------


class FieldObservation(BaseModel):
    """The gap between what the official procedure says and what actually happens.

    This is the core product of Jean: making the invisible intelligence visible.
    """

    id: str = Field(default_factory=_uuid)
    process_context: str
    declared_procedure: str = Field(
        description="The official procedure as documented"
    )
    observed_behavior: str = Field(
        description="What actually happens in the field (human-readable summary)"
    )
    gap_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Divergence score: 0 = no gap, 1 = completely different",
    )
    supporting_patterns: list[str] = Field(
        description="PatternHypothesis IDs that support this observation"
    )
    state: ProcedureState = Field(default=ProcedureState.OBSERVED)
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Extensible metadata: rejection_reason, tags, etc.",
    )
    created_at: datetime = Field(default_factory=_now)
    validated_at: datetime | None = None
    validated_by: str | None = None
    schema_version: str = Field(default="1.0")

    def is_validated(self) -> bool:
        return self.state == ProcedureState.VALIDATED and self.validated_at is not None


class ToolTransition(BaseModel):
    """Enriched metadata for a transition between two applications.

    Attached as payload in TOOL_SWITCH BusinessEvents to capture tool-switching friction.
    """
    from_app: str
    to_app: str
    transition_count: int = Field(ge=1, description="Number of times this pair was seen in the session")
    is_cross_app_paste: bool = Field(default=False, description="True when a clipboard paste triggered this transition")
    schema_version: str = Field(default="1.0")


class IrritantSignal(BaseModel):
    """An operator-flagged irritant moment.

    Captured when the operator explicitly signals friction (hotkey) or
    when the system auto-detects high-friction patterns.
    """
    source: str = Field(description="'operator' for manual, 'auto' for system-detected")
    irritant_type: str = Field(description="e.g. 'repeated_action', 'cross_app_paste', 'manual'")
    app: str
    related_event_ids: list[str] = Field(default_factory=list)
    schema_version: str = Field(default="1.0")


class DecisionAnnotation(BaseModel):
    """An operator annotation that captures an implicit decision rule.

    Triggered when the operator uses the 'explain decision' hotkey (Ctrl+Alt+D)
    or via the FlowFabric Inbox. Stores the rule in structured form when possible.

    Example: 'if customer is VIP → move to priority queue'
    """
    text: str = Field(description="Free-form decision description from the operator")
    condition: str | None = Field(
        default=None,
        description="Extracted condition (e.g. 'customer_status=VIP'). None if not structured.",
    )
    action: str | None = Field(
        default=None,
        description="Extracted action (e.g. 'priority=high'). None if not structured.",
    )
    app: str = Field(description="Application active when annotation was made")
    related_event_id: str | None = Field(
        default=None,
        description="BusinessEvent ID this decision explains",
    )
    schema_version: str = Field(default="1.0")
