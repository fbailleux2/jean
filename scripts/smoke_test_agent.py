"""jean-agent smoke test — no macOS permissions required.

Injects 20 synthetic BusinessEvents directly into a StructuralActionCapture queue,
flushes into a LocalBuffer stored in a temp directory, and optionally sends to a
mock aggregator (--dry-run skips the HTTP flush).

Usage:
    uv run python scripts/smoke_test_agent.py --dry-run
    uv run python scripts/smoke_test_agent.py --aggregator-url http://localhost:8100
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

# Make src/ importable when running directly
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from jean.agent.buffer import LocalBuffer
from jean.agent.capture import StructuralActionCapture
from jean.models import EventType

# 20 synthetic events that form repeating patterns
_SYNTHETIC_EVENTS: list[tuple[EventType, str]] = [
    (EventType.APP_FOCUS, "Excel"),
    (EventType.SAVE, "Excel"),
    (EventType.APP_FOCUS, "SAP"),
    (EventType.SUBMIT, "SAP"),
    (EventType.APP_FOCUS, "Outlook"),
    (EventType.APP_FOCUS, "Excel"),
    (EventType.EXPORT, "Excel"),
    (EventType.APP_FOCUS, "SAP"),
    (EventType.SUBMIT, "SAP"),
    (EventType.APP_FOCUS, "Chrome"),
    (EventType.APP_FOCUS, "Excel"),
    (EventType.SAVE, "Excel"),
    (EventType.APP_FOCUS, "SAP"),
    (EventType.SUBMIT, "SAP"),
    (EventType.APP_FOCUS, "Outlook"),
    (EventType.APP_FOCUS, "Excel"),
    (EventType.EXPORT, "Excel"),
    (EventType.APP_FOCUS, "SAP"),
    (EventType.PRINT, "SAP"),
    (EventType.APP_FOCUS, "Outlook"),
]

assert len(_SYNTHETIC_EVENTS) == 20


async def run(dry_run: bool, aggregator_url: str) -> None:
    capture = StructuralActionCapture(
        workstation_id="smoke-workstation",
        process_context="smoke-test",
        session_id="smoke-session-001",
    )

    # Inject 20 synthetic events into the capture queue
    for event_type, app in _SYNTHETIC_EVENTS:
        await capture.inject(event_type, app)

    injected = capture.event_queue.qsize()
    print(f"[smoke] Events injected into capture queue: {injected}")

    # Drain queue into a list
    events = []
    while not capture.event_queue.empty():
        events.append(capture.event_queue.get_nowait())

    with tempfile.TemporaryDirectory() as tmpdir:
        buffer_path = str(Path(tmpdir) / "smoke.db")

        async with LocalBuffer(db_path=buffer_path) as buf:
            for event in events:
                await buf.push(event)

            buffered = await buf.pending_count()
            print(f"[smoke] Events buffered in LocalBuffer: {buffered}")

            if dry_run:
                print("[smoke] --dry-run: skipping HTTP flush to aggregator")
                patterns_flushed = 0
            else:
                import httpx

                batch = await buf.drain()
                payload = [e.model_dump(mode="json") for e in batch]
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        resp = await client.post(
                            f"{aggregator_url.rstrip('/')}/ingest",
                            json=payload,
                        )
                        resp.raise_for_status()
                        data = resp.json()
                        patterns_flushed = data.get("patterns_detected", 0)
                        await buf.mark_sent([e.id for e in batch])
                    print(f"[smoke] Flushed {len(batch)} events to {aggregator_url}")
                except Exception as exc:  # noqa: BLE001
                    print(f"[smoke] ERROR flushing to aggregator: {exc}")
                    patterns_flushed = 0

    print()
    print("═══ Smoke Test Summary ══════════════════")
    print(f"  Events injected : {injected}")
    print(f"  Events buffered : {buffered}")
    print(f"  Patterns flushed: {patterns_flushed}")
    print(f"  Mode            : {'dry-run' if dry_run else 'live'}")
    print("═════════════════════════════════════════")


def main() -> None:
    parser = argparse.ArgumentParser(description="jean-agent smoke test")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Skip HTTP flush (default: False)",
    )
    parser.add_argument(
        "--aggregator-url",
        default="http://localhost:8100",
        help="Aggregator base URL (default: http://localhost:8100)",
    )
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run, aggregator_url=args.aggregator_url))


if __name__ == "__main__":
    main()
