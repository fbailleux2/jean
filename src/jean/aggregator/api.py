"""jean-aggregator FastAPI application.

Routes:
    POST /ingest            — receive events from jean-agent
    GET  /health            — health check
    GET  /patterns          — list detected PatternHypotheses (last run)
    POST /connectors/erp    — (mounted from erp_webhook router)

Store is selected via JEAN_STORE env var (memory | postgres).
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import Depends, FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from jean.aggregator.anonymizer import Anonymizer
from jean.aggregator.irritant_detector import IrritantDetector
from jean.aggregator.observation_generator import ObservationDispatcher, ObservationGenerator
from jean.aggregator.pattern_detector import PatternDetector
from jean.aggregator.store import AbstractStore, InMemoryStore, make_store
from jean.auth import require_auth
from jean.connectors.erp_webhook import router as erp_router
from jean.models import BusinessEvent, PatternHypothesis, SessionTrace

log = structlog.get_logger()

_anonymizer = Anonymizer()
_detector = PatternDetector(window_size=3, min_frequency=2)
_irritant_detector = IrritantDetector()
_patterns: list[PatternHypothesis] = []
_store: AbstractStore = InMemoryStore()
_obs_generator = ObservationGenerator()
_obs_dispatcher = ObservationDispatcher()


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _store
    _store = make_store()
    if hasattr(_store, "connect"):
        await _store.connect()
    log.info("jean-aggregator started", store=type(_store).__name__)
    yield
    await _store.close()


app = FastAPI(title="jean-aggregator", version="0.2.0", lifespan=_lifespan)
Instrumentator().instrument(app).expose(app)


# Mount ERP connector — protected routes
app.include_router(erp_router, prefix="/connectors", dependencies=[Depends(require_auth)])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "store": type(_store).__name__}


@app.post("/ingest", status_code=202)
async def ingest(events: list[BusinessEvent], _: None = Depends(require_auth)) -> dict:
    """Receive a batch of events from jean-agent.

    Events are anonymized before storage.
    """
    if not events:
        return {"accepted": 0}

    clean = _anonymizer.anonymize_many(events)
    await _store.save_events(clean)

    # Group events into session traces
    by_session: dict[str, list[BusinessEvent]] = {}
    for e in clean:
        by_session.setdefault(e.session_id, []).append(e)

    new_traces: list[SessionTrace] = []
    for session_id, session_events in by_session.items():
        trace = SessionTrace(
            session_id=session_id,
            workstation_id=session_events[0].workstation_id,
            process_context=session_events[0].process_context,
            events=sorted(session_events, key=lambda e: e.timestamp),
        )
        new_traces.append(trace)

    await _store.save_traces(new_traces)

    # Re-run pattern detection across all stored traces
    all_traces = await _store.load_traces()
    global _patterns
    _patterns = _detector.detect(all_traces)

    # Auto-generate FieldObservations and dispatch in the background (fire-and-forget)
    observations = _obs_generator.generate(_patterns)
    for obs in observations:
        asyncio.create_task(_obs_dispatcher.dispatch(obs))

    # Run irritant detection on the newly ingested traces
    irritant_signals = _irritant_detector.detect(new_traces)

    log.info(
        "Ingested events",
        count=len(clean),
        patterns_detected=len(_patterns),
        observations_generated=len(observations),
        irritants_detected=len(irritant_signals),
    )
    return {
        "accepted": len(clean),
        "patterns_detected": len(_patterns),
        "observations_generated": len(observations),
        "irritants_detected": len(irritant_signals),
    }


@app.get("/patterns", response_model=list[PatternHypothesis])
async def list_patterns(process_context: str | None = None) -> list[PatternHypothesis]:
    if process_context:
        return [p for p in _patterns if p.process_context == process_context]
    return _patterns
