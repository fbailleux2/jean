"""DriftDetector — measures divergence between declared process and observed reality.

Algorithm:
1. Collect all unique EventType values from recent SessionTraces for the process context.
2. Collect all event_types declared in ProcessDefinition.steps[].related_event_types.
3. Compute Jaccard distance: 1 - |intersection| / |union|
   (0.0 = identical, 1.0 = completely different)
4. If no declared event types → drift_score = 0.0 (no baseline to compare against)
5. Alert if drift_score > alert_threshold

Design: simple set comparison, no ML, fully deterministic.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog

from jean.models import DriftReport, ProcessDefinition, SessionTrace

log = structlog.get_logger()

DEFAULT_ALERT_THRESHOLD = 0.5


class DriftDetector:
    """Computes drift between declared ProcessDefinition and recent SessionTraces.

    Args:
        alert_threshold: drift_score above this triggers alert=True in DriftReport.
    """

    def __init__(self, alert_threshold: float = DEFAULT_ALERT_THRESHOLD) -> None:
        self.alert_threshold = alert_threshold

    def compute(
        self,
        process: ProcessDefinition,
        traces: list[SessionTrace],
    ) -> DriftReport:
        """Compute a DriftReport for the given process and its matching traces."""
        # Declared event types from steps
        declared: set[str] = set()
        for step in process.steps:
            declared.update(step.related_event_types)

        # Observed event types from traces
        observed: set[str] = set()
        for trace in traces:
            for event in trace.events:
                observed.add(event.type.value)

        # Jaccard distance
        if not declared:
            drift_score = 0.0
        else:
            union = declared | observed
            intersection = declared & observed
            drift_score = 1.0 - (len(intersection) / len(union)) if union else 0.0

        drift_score = round(min(max(drift_score, 0.0), 1.0), 4)
        alert = drift_score > self.alert_threshold

        if alert:
            log.warning(
                "Process drift alert",
                process_id=process.id,
                process_name=process.name,
                drift_score=drift_score,
                threshold=self.alert_threshold,
            )

        return DriftReport(
            process_id=process.id,
            process_name=process.name,
            process_context=process.process_context,
            declared_step_count=len(process.steps),
            observed_event_types=sorted(observed),
            declared_event_types=sorted(declared),
            drift_score=drift_score,
            session_count_analysed=len(traces),
            computed_at=datetime.now(timezone.utc),
            alert=alert,
        )
