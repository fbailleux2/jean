"""PatternDetector — finds recurring event sequences across session traces.

Algorithm: sliding-window sequence matching.
- Extracts n-grams of EventType sequences from each session.
- Groups identical sequences across sessions.
- Any sequence seen in >= min_frequency sessions becomes a PatternHypothesis.

This is intentionally simple (no ML, no embeddings).  The goal is to surface
obvious recurring patterns for human validation, not to build a classifier.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from jean.models import EventType, PatternHypothesis, SessionTrace


class PatternDetector:
    """Detects recurring event-type sequences across multiple SessionTraces.

    Args:
        window_size: length of the sliding window (n-gram size).
        min_frequency: minimum number of sessions a pattern must appear in.
        min_confidence: minimum confidence score (frequency / total sessions).
    """

    def __init__(
        self,
        window_size: int = 3,
        min_frequency: int = 2,
        min_confidence: float = 0.1,
    ) -> None:
        if window_size < 1:
            raise ValueError("window_size must be >= 1")
        if min_frequency < 1:
            raise ValueError("min_frequency must be >= 1")
        self.window_size = window_size
        self.min_frequency = min_frequency
        self.min_confidence = min_confidence

    def _extract_ngrams(self, trace: SessionTrace) -> list[tuple[EventType, ...]]:
        types = [e.type for e in trace.events]
        if len(types) < self.window_size:
            return []
        return [
            tuple(types[i : i + self.window_size])
            for i in range(len(types) - self.window_size + 1)
        ]

    def detect(self, traces: list[SessionTrace]) -> list[PatternHypothesis]:
        """Return PatternHypothesis objects for all recurring sequences.

        A pattern must appear in at least *min_frequency* different traces.
        """
        if not traces:
            return []

        # Map pattern → set of trace IDs where it appears
        pattern_to_traces: dict[tuple[EventType, ...], set[str]] = {}

        for trace in traces:
            seen_in_trace: set[tuple[EventType, ...]] = set()
            for ngram in self._extract_ngrams(trace):
                if ngram not in seen_in_trace:
                    pattern_to_traces.setdefault(ngram, set()).add(trace.session_id)
                    seen_in_trace.add(ngram)

        total = len(traces)
        now = datetime.now(timezone.utc)
        hypotheses: list[PatternHypothesis] = []

        for pattern, trace_ids in pattern_to_traces.items():
            freq = len(trace_ids)
            conf = freq / total
            if freq >= self.min_frequency and conf >= self.min_confidence:
                # Use process_context from first matching trace
                ctx = next(
                    (t.process_context for t in traces if t.session_id in trace_ids),
                    "unknown",
                )
                hypotheses.append(
                    PatternHypothesis(
                        pattern=list(pattern),
                        frequency=freq,
                        confidence=round(conf, 4),
                        source_trace_ids=list(trace_ids),
                        process_context=ctx,
                        first_seen=now,
                        last_seen=now,
                    )
                )

        # Sort by frequency desc, confidence desc
        hypotheses.sort(key=lambda h: (-h.frequency, -h.confidence))
        return hypotheses
