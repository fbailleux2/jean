"""jean-validator FastAPI application.

Provides the human validation circuit for FieldObservations generated
by jean-aggregator. In production this is integrated into FlowFabric Inbox.

For MVP this is a standalone REST API.

Routes:
    GET  /observations              — list pending (OBSERVED) observations
    POST /observations/{id}/approve — validate an observation
    POST /observations/{id}/reject  — reject an observation with reason

Truth level rule (from VISION.md §14):
  OBSERVED → VALIDATED requires explicit human approval (author + timestamp + context).
  A VALIDATED observation can never be reverted to OBSERVED via the API.

Post-approval pipeline:
  1. CorpusPipeline.run(obs) → corpus entry ID stored in obs.metadata
  2. FlowFabricBridge.notify(obs) → fire-and-forget webhook (no-op if unconfigured)
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field, field_validator

from jean.auth import require_auth
from jean.bridges.flowfabric import FlowFabricBridge
from jean.corpus_feeder.pipeline import CorpusPipeline
from jean.models import FieldObservation, ProcedureState

log = structlog.get_logger()
app = FastAPI(title="jean-validator", version="0.2.0")
Instrumentator().instrument(app).expose(app)

# In-memory store for MVP
_observations: dict[str, FieldObservation] = {}

# Singletons — injectable for tests via module-level replacement
_pipeline: CorpusPipeline = CorpusPipeline()
_bridge: FlowFabricBridge = FlowFabricBridge()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class ApproveRequest(BaseModel):
    validator_id: str = Field(description="Identifier of the human validator")

    @field_validator("validator_id")
    @classmethod
    def non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("validator_id must not be empty")
        return v.strip()


class RejectRequest(BaseModel):
    rejection_reason: str = Field(description="Why this observation is rejected")
    validator_id: str = Field(default="", description="Identifier of the human validator")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_or_404(obs_id: str) -> FieldObservation:
    obs = _observations.get(obs_id)
    if obs is None:
        raise HTTPException(status_code=404, detail=f"Observation {obs_id!r} not found")
    return obs


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "observations": len(_observations)}


@app.get("/observations", response_model=list[FieldObservation])
async def list_observations(state: str | None = None) -> list[FieldObservation]:
    """List observations, optionally filtered by state."""
    obs = list(_observations.values())
    if state:
        obs = [o for o in obs if o.state.value == state]
    return obs


@app.post("/observations/{obs_id}/approve", response_model=FieldObservation)
async def approve_observation(obs_id: str, req: ApproveRequest, _: None = Depends(require_auth)) -> FieldObservation:
    """Validate an observation — moves it to VALIDATED state.

    Post-approval:
    - Submits to CorpusPipeline → KFabric (corpus entry ID stored in metadata)
    - Notifies FlowFabric bridge (fire-and-forget, no-op if unconfigured)

    Governance rule: once VALIDATED, an observation cannot be reverted.
    """
    obs = _get_or_404(obs_id)

    if obs.state == ProcedureState.VALIDATED:
        raise HTTPException(status_code=409, detail="Observation is already VALIDATED")

    validated = obs.model_copy(
        update={
            "state": ProcedureState.VALIDATED,
            "validated_at": datetime.now(timezone.utc),
            "validated_by": req.validator_id,
        }
    )

    # Submit to corpus pipeline
    corpus_id = await _pipeline.run(validated)
    validated = validated.model_copy(
        update={"metadata": {**validated.metadata, "corpus_entry_id": corpus_id}}
    )

    _observations[obs_id] = validated

    # Fire-and-forget FlowFabric notification
    await _bridge.notify(validated)

    log.info(
        "Observation approved",
        obs_id=obs_id,
        validator_id=req.validator_id,
        corpus_entry_id=corpus_id,
    )
    return validated


@app.post("/observations/{obs_id}/reject", response_model=FieldObservation)
async def reject_observation(obs_id: str, req: RejectRequest, _: None = Depends(require_auth)) -> FieldObservation:
    """Reject an observation — keeps it OBSERVED but stores the rejection reason."""
    obs = _get_or_404(obs_id)

    if obs.state == ProcedureState.VALIDATED:
        raise HTTPException(
            status_code=409,
            detail="A VALIDATED observation cannot be rejected",
        )

    # Store rejection reason in metadata (non-PII — business reason only)
    updated_metadata = dict(obs.metadata)
    updated_metadata["rejection_reason"] = req.rejection_reason
    if req.validator_id:
        updated_metadata["rejected_by"] = req.validator_id

    rejected = obs.model_copy(
        update={
            "state": ProcedureState.OBSERVED,
            "metadata": updated_metadata,
        }
    )
    _observations[obs_id] = rejected
    log.info("Observation rejected", obs_id=obs_id, reason=req.rejection_reason)
    return rejected


# ---------------------------------------------------------------------------
# Internal: register an observation (called by aggregator or corpus-feeder)
# ---------------------------------------------------------------------------


@app.post("/observations/register", response_model=FieldObservation, status_code=201)
async def register_observation_route(obs: FieldObservation) -> FieldObservation:
    """Register a FieldObservation sent by the aggregator (auto-generated)."""
    _observations[obs.id] = obs
    log.info("Observation registered", obs_id=obs.id, process_context=obs.process_context)
    return obs


def register_observation(obs: FieldObservation) -> None:
    """Register a new FieldObservation for human review (internal helper)."""
    _observations[obs.id] = obs


def get_store() -> dict[str, FieldObservation]:
    """Expose the store for testing."""
    return _observations


def set_pipeline(pipeline: CorpusPipeline) -> None:
    """Replace the CorpusPipeline singleton (for testing)."""
    global _pipeline
    _pipeline = pipeline


def set_bridge(bridge: FlowFabricBridge) -> None:
    """Replace the FlowFabricBridge singleton (for testing)."""
    global _bridge
    _bridge = bridge


# ---------------------------------------------------------------------------
# UI — served at /ui (no build step, plain HTML+JS)
# ---------------------------------------------------------------------------


@app.get("/", include_in_schema=False)
async def root_redirect() -> RedirectResponse:
    return RedirectResponse(url="/ui/")


# Static files mounted last so they don't shadow API routes
import pathlib as _pathlib

_static_dir = _pathlib.Path(__file__).parent / "static"
_static_dir.mkdir(exist_ok=True)
app.mount("/ui", StaticFiles(directory=str(_static_dir), html=True), name="ui")
