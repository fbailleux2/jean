"""jean-agent entry point.

Starts the capture loop and the emit loop concurrently.

Usage::

    uv run jean-agent                        # default settings
    JEAN_AGGREGATOR_URL=http://host:8100 uv run jean-agent

Footprint targets (VISION.md invariants):
  - <2% CPU  (achieved via event-driven design, no polling loops)
  - <50 MB RAM (SQLite buffer + asyncio, no heavy ML dependencies)
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid

import structlog

from jean.agent.buffer import LocalBuffer
from jean.agent.capture import AnnotationCapture, AppTransitionCapture, StructuralActionCapture
from jean.agent.capture_keyboard import KeyboardCapture
from jean.agent.emitter import EventEmitter

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
)
log = structlog.get_logger()

DB_PATH = os.environ.get("JEAN_BUFFER_PATH", "jean-agent.db")
AGGREGATOR_URL = os.environ.get("JEAN_AGGREGATOR_URL", "http://localhost:8100")
PROCESS_CONTEXT = os.environ.get("JEAN_PROCESS_CONTEXT", "default")
WORKSTATION_ID = os.environ.get("JEAN_WORKSTATION_ID", str(uuid.uuid4()))


async def _capture_loop(
    buffer: LocalBuffer,
    process_context: str,
    workstation_id: str,
) -> None:
    session_id = str(uuid.uuid4())
    log.info("Starting capture session", session_id=session_id, process_context=process_context)

    # Shared queue for keyboard-hotkey events (KeyboardCapture → buffer)
    kb_queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    app_cap = AppTransitionCapture(workstation_id, process_context, session_id)
    struct_cap = StructuralActionCapture(workstation_id, process_context, session_id)
    kb_cap = KeyboardCapture(
        event_queue=kb_queue,
        workstation_id=workstation_id,
        process_context=process_context,
        session_id=session_id,
        loop=loop,
    )

    async def _drain_gen(cap: AppTransitionCapture | StructuralActionCapture) -> None:
        async for event in cap.events():
            await buffer.push(event)
            log.debug("Captured event", type=event.type, app=event.app)

    async def _drain_kb() -> None:
        kb_cap.start()
        try:
            while True:
                event = await kb_queue.get()
                await buffer.push(event)
                log.debug("Keyboard event", type=event.type, app=event.app)
        finally:
            kb_cap.stop()

    await asyncio.gather(_drain_gen(app_cap), _drain_gen(struct_cap), _drain_kb())


async def _emit_loop(buffer: LocalBuffer) -> None:
    emitter = EventEmitter(buffer, aggregator_url=AGGREGATOR_URL)
    await emitter.run()


async def _main() -> None:
    async with LocalBuffer(DB_PATH) as buffer:
        log.info(
            "jean-agent starting",
            db=DB_PATH,
            aggregator=AGGREGATOR_URL,
            workstation_id=WORKSTATION_ID,
        )
        await asyncio.gather(
            _capture_loop(buffer, PROCESS_CONTEXT, WORKSTATION_ID),
            _emit_loop(buffer),
        )


def main() -> None:
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        log.info("jean-agent stopped")
