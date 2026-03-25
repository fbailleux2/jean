"""Tests for jean.doc_generator.builder."""

from __future__ import annotations

import pytest

from jean.doc_generator.builder import DocumentBuilder, DocumentRow
from jean.models import (
    ProcessDefinition,
    ProcessInput,
    ProcessOutput,
    ProcessStep,
    ProcedureState,
)


def _make_process(**kwargs) -> ProcessDefinition:
    """Helper: build a minimal ProcessDefinition."""
    defaults = dict(
        name="Test Process",
        process_context="test-context",
        trigger="An email arrives",
        version="1.0.0",
        state=ProcedureState.DECLARED,
        steps=[],
        inputs=[],
        outputs=[],
        description="",
    )
    defaults.update(kwargs)
    return ProcessDefinition(**defaults)


def _make_step(
    sequence: int = 1,
    action: str = "Do something",
    tool: str = "SAP",
    decision: str | None = None,
    irritant_score: float = 0.0,
) -> ProcessStep:
    return ProcessStep(
        sequence=sequence,
        action=action,
        tool=tool,
        decision=decision,
        irritant_score=irritant_score,
    )


# ---------------------------------------------------------------------------
# to_markdown tests
# ---------------------------------------------------------------------------


def test_to_markdown_basic():
    """ProcessDefinition with 2 steps → markdown contains table header, both steps, process name."""
    process = _make_process(
        name="Invoice Exception Handling",
        steps=[
            _make_step(sequence=1, action="Search customer", tool="SAP"),
            _make_step(sequence=2, action="Send email", tool="Outlook"),
        ],
    )
    builder = DocumentBuilder()
    md = builder.to_markdown(process)

    assert "# Invoice Exception Handling" in md
    assert "| Étape | Action | Outil | Décision | Irritant |" in md
    assert "| 1 " in md
    assert "Search customer" in md
    assert "SAP" in md
    assert "| 2 " in md
    assert "Send email" in md
    assert "Outlook" in md


def test_to_markdown_no_steps():
    """Empty steps list → no table in output."""
    process = _make_process(steps=[])
    builder = DocumentBuilder()
    md = builder.to_markdown(process)

    assert "| Étape |" not in md
    assert "## Steps" not in md


def test_to_markdown_irritant_labels():
    """Irritant labels: score=0.8 → '⚠ high', score=0.4 → '~ medium', score=0.1 → ''."""
    process = _make_process(
        steps=[
            _make_step(sequence=1, action="High friction", tool="Tool", irritant_score=0.8),
            _make_step(sequence=2, action="Medium friction", tool="Tool", irritant_score=0.4),
            _make_step(sequence=3, action="No friction", tool="Tool", irritant_score=0.1),
        ]
    )
    builder = DocumentBuilder()
    md = builder.to_markdown(process)

    assert "⚠ high" in md
    assert "~ medium" in md
    # No friction row should not contain either label — check by splitting rows
    rows = [line for line in md.splitlines() if line.startswith("| 3 ")]
    assert len(rows) == 1
    assert "⚠ high" not in rows[0]
    assert "~ medium" not in rows[0]


def test_to_markdown_includes_trigger():
    """Trigger text appears in the output."""
    process = _make_process(trigger="Customer complaint received by email")
    builder = DocumentBuilder()
    md = builder.to_markdown(process)

    assert "Customer complaint received by email" in md
    assert "## Trigger" in md


def test_to_markdown_inputs_outputs():
    """Inputs and outputs sections are present when provided."""
    process = _make_process(
        inputs=[
            ProcessInput(name="customer_email", source="email", required=True),
            ProcessInput(name="order_id", source="erp", required=False),
        ],
        outputs=[
            ProcessOutput(name="validated_order", destination="erp"),
        ],
    )
    builder = DocumentBuilder()
    md = builder.to_markdown(process)

    assert "## Inputs" in md
    assert "customer_email" in md
    assert "*(required)*" in md
    assert "*(optional)*" in md
    assert "## Outputs" in md
    assert "validated_order" in md
    assert "erp" in md


# ---------------------------------------------------------------------------
# to_json tests
# ---------------------------------------------------------------------------


def test_to_json_structure():
    """to_json returns dict with all required keys."""
    process = _make_process(
        steps=[_make_step(sequence=1)],
    )
    builder = DocumentBuilder()
    result = builder.to_json(process)

    for key in ("process_id", "name", "version", "process_context", "trigger", "steps",
                "inputs", "outputs", "generated_by", "schema_version"):
        assert key in result, f"Missing key: {key}"

    assert result["generated_by"] == "jean-doc-generator"
    assert result["schema_version"] == "1.0"
    assert result["name"] == "Test Process"


def test_to_json_step_count():
    """Step count in JSON output matches the ProcessDefinition."""
    process = _make_process(
        steps=[
            _make_step(sequence=1),
            _make_step(sequence=2),
            _make_step(sequence=3),
        ]
    )
    builder = DocumentBuilder()
    result = builder.to_json(process)

    assert len(result["steps"]) == 3


# ---------------------------------------------------------------------------
# DocumentRow tests
# ---------------------------------------------------------------------------


def test_document_row_from_step_no_decision():
    """step.decision=None → row.decision='—'."""
    step = _make_step(sequence=1, decision=None)
    builder = DocumentBuilder()
    row = builder._step_to_row(step)

    assert row.decision == "—"
