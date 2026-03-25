"""FastAPI router for ProcessDefinition CRUD.

Routes:
    POST   /processes          — declare a new process
    GET    /processes          — list all declared processes
    GET    /processes/{id}     — get one process
    PUT    /processes/{id}     — update a process (bumps version)
    DELETE /processes/{id}     — remove a process

Mounted on jean-validator at prefix /process-mapper.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from jean.models import ProcessDefinition, ProcedureState
from jean.process_mapper.store import ProcessStore

log = structlog.get_logger()

router = APIRouter(tags=["process-mapper"])

# Singleton store — replaced in tests via dependency injection pattern
_store = ProcessStore()


def get_store() -> ProcessStore:
    """Return the module-level store (replaceable in tests)."""
    return _store


class ProcessUpdateRequest(BaseModel):
    """Payload for updating a ProcessDefinition.
    All fields are optional — only provided fields are updated.
    """
    name: str | None = None
    description: str | None = None
    trigger: str | None = None
    inputs: list | None = None
    outputs: list | None = None
    steps: list | None = None
    state: ProcedureState | None = None


def _bump_minor_version(version: str) -> str:
    """Increment the minor component of a semver string."""
    parts = version.split(".")
    try:
        parts[1] = str(int(parts[1]) + 1)
        parts[2] = "0"
    except (IndexError, ValueError):
        return version
    return ".".join(parts)


@router.post("/processes", status_code=201, response_model=ProcessDefinition)
async def create_process(process: ProcessDefinition) -> ProcessDefinition:
    """Declare a new business process."""
    store = get_store()
    store.save(process)
    log.info("Process created", id=process.id, name=process.name)
    return process


@router.get("/processes", response_model=list[ProcessDefinition])
async def list_processes() -> list[ProcessDefinition]:
    """List all declared process definitions."""
    return get_store().list_all()


@router.get("/processes/{process_id}", response_model=ProcessDefinition)
async def get_process(process_id: str) -> ProcessDefinition:
    """Get a single process definition by ID."""
    process = get_store().get(process_id)
    if not process:
        raise HTTPException(status_code=404, detail="Process not found")
    return process


@router.put("/processes/{process_id}", response_model=ProcessDefinition)
async def update_process(process_id: str, update: ProcessUpdateRequest) -> ProcessDefinition:
    """Update a process definition. Bumps minor version on each update."""
    store = get_store()
    process = store.get(process_id)
    if not process:
        raise HTTPException(status_code=404, detail="Process not found")

    data = process.model_dump()
    for field, value in update.model_dump(exclude_none=True).items():
        data[field] = value
    data["updated_at"] = datetime.now(timezone.utc)
    data["version"] = _bump_minor_version(data["version"])

    updated = ProcessDefinition.model_validate(data)
    store.save(updated)
    log.info("Process updated", id=process_id, version=updated.version)
    return updated


@router.delete("/processes/{process_id}", status_code=204)
async def delete_process(process_id: str) -> None:
    """Delete a process definition."""
    if not get_store().delete(process_id):
        raise HTTPException(status_code=404, detail="Process not found")
