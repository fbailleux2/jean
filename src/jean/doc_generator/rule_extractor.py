"""BusinessRuleExtractor — extracts structured if/then rules from observations.

Sources:
1. DecisionAnnotation objects — operator-provided implicit rules
2. PatternHypotheses — recurring sequences that imply a rule

Output: list of BusinessRule dicts (machine-readable, KFabric-compatible).

Design: no ML, pure structural extraction with confidence scores.
"""

from __future__ import annotations

import re
import structlog

from jean.models import DecisionAnnotation, PatternHypothesis

log = structlog.get_logger()

# Simple regex patterns for "if X → Y" / "if X then Y" structures
_IF_THEN_PATTERNS = [
    re.compile(r"si\s+(.+?)\s*[→>]\s*(.+)", re.IGNORECASE),
    re.compile(r"if\s+(.+?)\s*[→>]\s*(.+)", re.IGNORECASE),
    re.compile(r"si\s+(.+?)\s+alors\s+(.+)", re.IGNORECASE),
    re.compile(r"if\s+(.+?)\s+then\s+(.+)", re.IGNORECASE),
]


def _extract_condition_action(text: str) -> tuple[str, str] | None:
    """Try to extract (condition, action) from free text. Returns None if not parseable."""
    for pattern in _IF_THEN_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).strip(), match.group(2).strip()
    return None


class BusinessRuleExtractor:
    """Extracts business rules from DecisionAnnotations and PatternHypotheses.

    Args:
        min_pattern_confidence: Minimum PatternHypothesis confidence to generate a rule.
    """

    def __init__(self, min_pattern_confidence: float = 0.6) -> None:
        self.min_pattern_confidence = min_pattern_confidence

    def from_annotations(self, annotations: list[DecisionAnnotation]) -> list[dict]:
        """Extract rules from operator decision annotations."""
        rules = []
        for ann in annotations:
            # Use pre-structured fields if available
            if ann.condition and ann.action:
                rules.append({
                    "source": "decision_annotation",
                    "condition": ann.condition,
                    "action": ann.action,
                    "confidence": 0.9,
                    "raw_text": ann.text,
                    "app": ann.app,
                })
                continue

            # Try to parse from free text
            parsed = _extract_condition_action(ann.text)
            if parsed:
                condition, action = parsed
                rules.append({
                    "source": "decision_annotation",
                    "condition": condition,
                    "action": action,
                    "confidence": 0.7,
                    "raw_text": ann.text,
                    "app": ann.app,
                })
            else:
                # Unstructured annotation — store as-is with low confidence
                rules.append({
                    "source": "decision_annotation",
                    "condition": None,
                    "action": ann.text,
                    "confidence": 0.4,
                    "raw_text": ann.text,
                    "app": ann.app,
                })

        log.debug("Rules from annotations", count=len(rules))
        return rules

    def from_patterns(self, patterns: list[PatternHypothesis]) -> list[dict]:
        """Extract implicit rules from recurring PatternHypotheses."""
        rules = []
        for pattern in patterns:
            if pattern.confidence < self.min_pattern_confidence:
                continue
            event_sequence = " → ".join(str(p) for p in pattern.pattern)
            rules.append({
                "source": "pattern_hypothesis",
                "condition": f"context={pattern.process_context}",
                "action": f"sequence: {event_sequence}",
                "confidence": pattern.confidence,
                "frequency": pattern.frequency,
                "pattern_id": pattern.id,
            })

        log.debug("Rules from patterns", count=len(rules))
        return rules

    def extract_all(
        self,
        annotations: list[DecisionAnnotation],
        patterns: list[PatternHypothesis],
    ) -> list[dict]:
        """Extract and merge rules from all sources, sorted by confidence descending."""
        rules = self.from_annotations(annotations) + self.from_patterns(patterns)
        return sorted(rules, key=lambda r: r["confidence"], reverse=True)
