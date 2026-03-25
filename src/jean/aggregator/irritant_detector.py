"""Automatic irritant detection for jean-aggregator.

Analyses SessionTraces to surface friction patterns:
1. Repeated actions — same (app, event_type) seen more than REPEAT_THRESHOLD times
2. Rapid tool-switching — TOOL_SWITCH events with transition_count >= FRICTION_THRESHOLD
3. Excessive clipboard transfers — more than CLIPBOARD_THRESHOLD cross-app pastes in a session

Each detected irritant produces an IrritantSignal model, returned as a list.
These signals are stored alongside SessionTraces and inform the pattern detector.

Design principle: no ML, no heuristics beyond simple counting.
"""

from __future__ import annotations

import structlog

from jean.models import BusinessEvent, EventType, IrritantSignal, SessionTrace

log = structlog.get_logger()

REPEAT_THRESHOLD = 5        # same (app, event_type) in one session
FRICTION_THRESHOLD = 3      # transition_count value at which TOOL_SWITCH fires (matches capture.py)
CLIPBOARD_THRESHOLD = 3     # cross-app pastes in one session


class IrritantDetector:
    """Detects friction signals from a list of SessionTraces.

    Args:
        repeat_threshold:    Min repeated (app, event_type) count to flag.
        clipboard_threshold: Min cross-app paste count to flag.
    """

    def __init__(
        self,
        repeat_threshold: int = REPEAT_THRESHOLD,
        clipboard_threshold: int = CLIPBOARD_THRESHOLD,
    ) -> None:
        if repeat_threshold < 1:
            raise ValueError("repeat_threshold must be >= 1")
        if clipboard_threshold < 1:
            raise ValueError("clipboard_threshold must be >= 1")
        self.repeat_threshold = repeat_threshold
        self.clipboard_threshold = clipboard_threshold

    def detect(self, traces: list[SessionTrace]) -> list[IrritantSignal]:
        """Return a flat list of IrritantSignals detected across all traces."""
        signals: list[IrritantSignal] = []
        for trace in traces:
            signals.extend(self._detect_repeated_actions(trace))
            signals.extend(self._detect_tool_switch_friction(trace))
            signals.extend(self._detect_clipboard_overuse(trace))
        log.debug("IrritantDetector", traces=len(traces), signals=len(signals))
        return signals

    def _detect_repeated_actions(self, trace: SessionTrace) -> list[IrritantSignal]:
        """Flag (app, event_type) pairs that appear more than repeat_threshold times."""
        counts: dict[tuple[str, str], list[str]] = {}
        for event in trace.events:
            key = (event.app, event.type.value)
            counts.setdefault(key, []).append(event.id)

        signals = []
        for (app, event_type), event_ids in counts.items():
            if len(event_ids) >= self.repeat_threshold:
                signals.append(
                    IrritantSignal(
                        source="auto",
                        irritant_type="repeated_action",
                        app=app,
                        related_event_ids=event_ids,
                    )
                )
                log.info(
                    "Repeated action detected",
                    app=app,
                    event_type=event_type,
                    count=len(event_ids),
                    session_id=trace.session_id,
                )
        return signals

    def _detect_tool_switch_friction(self, trace: SessionTrace) -> list[IrritantSignal]:
        """Flag TOOL_SWITCH events already emitted by AppTransitionCapture."""
        signals = []
        for event in trace.events:
            if event.type == EventType.TOOL_SWITCH and not event.payload.get("is_cross_app_paste"):
                signals.append(
                    IrritantSignal(
                        source="auto",
                        irritant_type="tool_switch_friction",
                        app=event.app,
                        related_event_ids=[event.id],
                    )
                )
        return signals

    def _detect_clipboard_overuse(self, trace: SessionTrace) -> list[IrritantSignal]:
        """Flag sessions with excessive cross-app clipboard transfers."""
        cross_app_pastes = [
            e for e in trace.events
            if e.type == EventType.CLIPBOARD_PASTE and e.payload.get("is_cross_app")
        ]
        if len(cross_app_pastes) >= self.clipboard_threshold:
            return [
                IrritantSignal(
                    source="auto",
                    irritant_type="cross_app_paste",
                    app="clipboard",
                    related_event_ids=[e.id for e in cross_app_pastes],
                )
            ]
        return []
