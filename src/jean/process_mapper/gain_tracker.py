"""GainTracker — computes before/after metrics for a process improvement cycle.

Compares two sets of SessionTraces (before and after a process update) to measure:
- Reduction in irritant events (IRRITANT type)
- Reduction in tool-switch events (TOOL_SWITCH type)

Usage:
    tracker = GainTracker()
    metrics = tracker.compute(process, traces_before, traces_after)
"""

from __future__ import annotations

from datetime import datetime

import structlog

from jean.models import EventType, ProcessDefinition, ProcessGainMetrics, SessionTrace

log = structlog.get_logger()


def _count_event_type(traces: list[SessionTrace], event_type: EventType) -> float:
    """Return the average count of event_type per session across traces."""
    if not traces:
        return 0.0
    counts = [
        sum(1 for e in trace.events if e.type == event_type)
        for trace in traces
    ]
    return sum(counts) / len(counts)


class GainTracker:
    """Computes process improvement metrics between two time periods."""

    def compute(
        self,
        process: ProcessDefinition,
        traces_before: list[SessionTrace],
        traces_after: list[SessionTrace],
        period_start: datetime,
        period_end: datetime,
    ) -> ProcessGainMetrics:
        """Compute gain metrics comparing before and after traces."""
        irritant_before = _count_event_type(traces_before, EventType.IRRITANT)
        irritant_after = _count_event_type(traces_after, EventType.IRRITANT)
        switch_before = _count_event_type(traces_before, EventType.TOOL_SWITCH)
        switch_after = _count_event_type(traces_after, EventType.TOOL_SWITCH)

        def reduction_pct(before: float, after: float) -> float:
            if before == 0.0:
                return 0.0
            return round((before - after) / before * 100, 2)

        metrics = ProcessGainMetrics(
            process_id=process.id,
            process_context=process.process_context,
            period_start=period_start,
            period_end=period_end,
            avg_irritant_count_before=round(irritant_before, 4),
            avg_irritant_count_after=round(irritant_after, 4),
            avg_tool_switches_before=round(switch_before, 4),
            avg_tool_switches_after=round(switch_after, 4),
            irritant_reduction_pct=reduction_pct(irritant_before, irritant_after),
            tool_switch_reduction_pct=reduction_pct(switch_before, switch_after),
        )

        log.info(
            "GainTracker computed",
            process=process.name,
            irritant_reduction=metrics.irritant_reduction_pct,
            tool_switch_reduction=metrics.tool_switch_reduction_pct,
        )
        return metrics
