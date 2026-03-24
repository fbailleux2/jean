"""KFabric Mock Service — realistic stub for development and integration testing.

Implements the KFabric corpus ingestion API contract:

    POST /ingest              — accept a FieldObservation, return {entry_id}
    GET  /health              — health check
    GET  /entries             — list all submitted entries (summaries)
    GET  /entries/{entry_id}  — retrieve a specific entry by ID

Entry IDs are deterministic: kf-{obs_id[:8]}-{sequence_number}

All data is in-memory; no persistence. Restart clears all entries.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="kfabric-mock", version="1.0.0")

# In-memory store: entry_id → {entry_id, observation_id, process_context, gap_score, payload}
_entries: dict[str, dict[str, Any]] = {}
_sequence: int = 0


class IngestRequest(BaseModel):
    """Minimal validation — accepts any JSON body that has an id field."""
    model_config = {"extra": "allow"}
    id: str


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "entries": len(_entries)}


@app.post("/ingest", status_code=201)
async def ingest(body: IngestRequest) -> dict:
    """Accept a FieldObservation and store it. Returns a corpus entry ID."""
    global _sequence
    _sequence += 1
    entry_id = f"kf-{body.id[:8]}-{_sequence:04d}"
    _entries[entry_id] = {
        "entry_id": entry_id,
        "observation_id": body.id,
        "process_context": getattr(body, "process_context", "unknown"),
        "gap_score": getattr(body, "gap_score", 0.0),
        "seq": _sequence,
    }
    return {"entry_id": entry_id, "status": "accepted"}


@app.get("/entries")
async def list_entries() -> list[dict]:
    """Return summaries of all submitted entries."""
    return list(_entries.values())


@app.get("/entries/{entry_id}")
async def get_entry(entry_id: str) -> dict:
    """Return a specific entry by ID."""
    entry = _entries.get(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Entry {entry_id!r} not found")
    return entry
