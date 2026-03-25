"""Tests for jean.doc_generator.rule_extractor."""

from __future__ import annotations

import pytest

from jean.doc_generator.rule_extractor import BusinessRuleExtractor
from jean.models import DecisionAnnotation, EventType, PatternHypothesis


def _make_annotation(
    text: str,
    condition: str | None = None,
    action: str | None = None,
    app: str = "SAP",
) -> DecisionAnnotation:
    return DecisionAnnotation(text=text, condition=condition, action=action, app=app)


def _make_pattern(
    confidence: float = 0.8,
    frequency: int = 5,
    process_context: str = "invoice-handling",
    pattern: list[EventType] | None = None,
    source_trace_ids: list[str] | None = None,
) -> PatternHypothesis:
    return PatternHypothesis(
        pattern=pattern or [EventType.APP_FOCUS, EventType.SAVE],
        frequency=frequency,
        confidence=confidence,
        source_trace_ids=source_trace_ids or ["trace-001"],
        process_context=process_context,
    )


# ---------------------------------------------------------------------------
# from_annotations tests
# ---------------------------------------------------------------------------


def test_from_annotations_structured():
    """Annotation with condition+action already set → rule with confidence=0.9."""
    ann = _make_annotation(
        text="if customer is VIP → move to priority queue",
        condition="customer_status=VIP",
        action="priority=high",
    )
    extractor = BusinessRuleExtractor()
    rules = extractor.from_annotations([ann])

    assert len(rules) == 1
    rule = rules[0]
    assert rule["confidence"] == 0.9
    assert rule["condition"] == "customer_status=VIP"
    assert rule["action"] == "priority=high"
    assert rule["source"] == "decision_annotation"


def test_from_annotations_if_then_french():
    """French 'si X → Y' text is parsed into condition and action."""
    ann = _make_annotation(text="si client VIP → priorité haute")
    extractor = BusinessRuleExtractor()
    rules = extractor.from_annotations([ann])

    assert len(rules) == 1
    rule = rules[0]
    assert rule["confidence"] == 0.7
    assert rule["condition"] == "client VIP"
    assert rule["action"] == "priorité haute"


def test_from_annotations_if_then_english():
    """English 'if X then Y' text is parsed correctly."""
    ann = _make_annotation(text="if stock < 5 then alert")
    extractor = BusinessRuleExtractor()
    rules = extractor.from_annotations([ann])

    assert len(rules) == 1
    rule = rules[0]
    assert rule["confidence"] == 0.7
    assert rule["condition"] == "stock < 5"
    assert rule["action"] == "alert"


def test_from_annotations_unstructured():
    """Text with no if/then pattern → action=text, confidence=0.4."""
    ann = _make_annotation(text="Something happens here without a clear rule")
    extractor = BusinessRuleExtractor()
    rules = extractor.from_annotations([ann])

    assert len(rules) == 1
    rule = rules[0]
    assert rule["confidence"] == 0.4
    assert rule["condition"] is None
    assert rule["action"] == ann.text


# ---------------------------------------------------------------------------
# from_patterns tests
# ---------------------------------------------------------------------------


def test_from_patterns_filtered_by_confidence():
    """Pattern below min_confidence is not included in the output."""
    low_confidence_pattern = _make_pattern(confidence=0.3)
    extractor = BusinessRuleExtractor(min_pattern_confidence=0.6)
    rules = extractor.from_patterns([low_confidence_pattern])

    assert rules == []


def test_from_patterns_above_confidence():
    """Pattern above threshold → rule with source='pattern_hypothesis'."""
    pattern = _make_pattern(confidence=0.85, process_context="order-processing")
    extractor = BusinessRuleExtractor(min_pattern_confidence=0.6)
    rules = extractor.from_patterns([pattern])

    assert len(rules) == 1
    rule = rules[0]
    assert rule["source"] == "pattern_hypothesis"
    assert rule["confidence"] == 0.85
    assert "order-processing" in rule["condition"]
    assert rule["frequency"] == 5


# ---------------------------------------------------------------------------
# extract_all tests
# ---------------------------------------------------------------------------


def test_extract_all_sorted_by_confidence():
    """Mixed sources → output sorted descending by confidence."""
    annotations = [
        _make_annotation(text="unstructured text here"),  # confidence=0.4
        _make_annotation(
            text="si x → y",
            condition="x",
            action="y",
        ),  # confidence=0.9
    ]
    patterns = [
        _make_pattern(confidence=0.75),
    ]
    extractor = BusinessRuleExtractor(min_pattern_confidence=0.6)
    rules = extractor.extract_all(annotations, patterns)

    assert len(rules) == 3
    confidences = [r["confidence"] for r in rules]
    assert confidences == sorted(confidences, reverse=True)
    assert confidences[0] == 0.9


def test_extract_all_empty():
    """Empty inputs → empty list."""
    extractor = BusinessRuleExtractor()
    rules = extractor.extract_all([], [])
    assert rules == []
