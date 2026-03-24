"""jean-aggregator FastAPI application.

Exposes a single /ingest endpoint that receives batches of BusinessEvents
from jean-agent instances, anonymizes them, and stores them for pattern
detection.

Routes:
    POST /ingest        — receive events from jean-agent
    GET  /health        — health check
    GET  /patterns      — list detected PatternHypotheses (last run)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import structlog
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from jean.aggregator.anonymizer import Anonymizer
from jean.aggregator.pattern_detector import PatternDetector
from jean.models import BusinessEvent, PatternHypothesis, SessionTrace

log = structlog.get_logger()
app = FastAPI(title="jean-aggregator", version="0.1.0")

# In-memory store (replace with PostgreSQL in production)
_events: list[BusinessEvent] = []
_traces: list[SessionTrace] = []
_patterns: list[PatternHypothesis] = []

_anonymizer = Anonymizer()
_detector = PatternDetector(window_size=3, min_frequency=2)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "events_stored": len(_events)}


@app.post("/ingest", status_code=202)
async def ingest(events: list[BusinessEvent]) -> dict:
    """Receive a batch of events from jean-agent.

    Events are anonymized before being stored.
    """
    if not events:
        return {"accepted": 0}

    clean = _anonymizer.anonymize_many(events)
    _events.extend(clean)

    # Group events into session traces
    by_session: dict[str, list[BusinessEvent]] = {}
    for e in clean:
        by_session.setdefault(e.session_id, []).append(e)

    for session_id, session_events in by_session.items():
        trace = SessionTrace(
            session_id=session_id,
            workstation_id=session_events[0].workstation_id,
            process_context=session_events[0].process_context,
            events=sorted(session_events, key=lambda e: e.timestamp),
        )
        _traces.append(trace)

    # Re-run pattern detection (could be made async/background in production)
    global _patterns
    _patterns = _detector.detect(_traces)

    log.info(
        "Ingested events",
        count=len(clean),
        total_events=len(_events),
        patterns_detected=len(_patterns),
    )
    return {"accepted": len(clean), "patterns_detected": len(_patterns)}


@app.get("/patterns", response_model=list[PatternHypothesis])
async def list_patterns() -> list[PatternHypothesis]:
    """Return the latest detected PatternHypotheses."""
    return _patterns
