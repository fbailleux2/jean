"""Tests for process_mapper models, store, and tracer."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jean.models import (
    ProcessDefinition,
    ProcessInput,
    ProcessOutput,
    ProcessStep,
    ProcedureState,
    SessionTrace,
)
from jean.process_mapper.api import _bump_minor_version
from jean.process_mapper.store import ProcessStore
from jean.process_mapper.tracer import ProcessTracer


# ---------------------------------------------------------------------------
# ProcessStore tests
# ---------------------------------------------------------------------------


def _make_process(name: str = "test-process", context: str = "invoice-handling") -> ProcessDefinition:
    return ProcessDefinition(
        name=name,
        process_context=context,
        trigger="incoming customer email",
    )


def test_create_and_retrieve() -> None:
    store = ProcessStore()
    proc = _make_process()
    store.save(proc)
    retrieved = store.get(proc.id)
    assert retrieved is not None
    assert retrieved.id == proc.id
    assert retrieved.name == proc.name


def test_get_by_context() -> None:
    store = ProcessStore()
    proc = _make_process(context="invoice-exception")
    store.save(proc)
    found = store.get_by_context("invoice-exception")
    assert found is not None
    assert found.id == proc.id


def test_get_by_context_missing() -> None:
    store = ProcessStore()
    assert store.get_by_context("nonexistent-context") is None


def test_list_all() -> None:
    store = ProcessStore()
    p1 = _make_process(name="proc-a", context="ctx-a")
    p2 = _make_process(name="proc-b", context="ctx-b")
    p3 = _make_process(name="proc-c", context="ctx-c")
    store.save(p1)
    store.save(p2)
    store.save(p3)
    all_procs = store.list_all()
    assert len(all_procs) == 3
    ids = {p.id for p in all_procs}
    assert p1.id in ids
    assert p2.id in ids
    assert p3.id in ids


def test_delete() -> None:
    store = ProcessStore()
    proc = _make_process()
    store.save(proc)
    assert store.count == 1

    result = store.delete(proc.id)
    assert result is True
    assert store.count == 0
    assert store.get(proc.id) is None


def test_delete_nonexistent() -> None:
    store = ProcessStore()
    result = store.delete("nonexistent-id")
    assert result is False


# ---------------------------------------------------------------------------
# ProcessTracer tests
# ---------------------------------------------------------------------------


def _make_session(process_context: str) -> SessionTrace:
    return SessionTrace(
        workstation_id="ws-001",
        process_context=process_context,
    )


def test_process_tracer_match() -> None:
    store = ProcessStore()
    proc = _make_process(context="invoice-handling")
    store.save(proc)

    tracer = ProcessTracer(store)
    session = _make_session("invoice-handling")
    result = tracer.match([session])

    assert session.session_id in result
    matched = result[session.session_id]
    assert matched is not None
    assert matched.id == proc.id


def test_process_tracer_no_match() -> None:
    store = ProcessStore()
    tracer = ProcessTracer(store)
    session = _make_session("unknown-context")
    result = tracer.match([session])

    assert session.session_id in result
    assert result[session.session_id] is None


# ---------------------------------------------------------------------------
# ProcessDefinition model tests
# ---------------------------------------------------------------------------


def test_process_definition_valid() -> None:
    proc = ProcessDefinition(
        name="invoice-exception-handling",
        process_context="invoice-exception",
        trigger="incoming customer email",
        description="Handles invoice exceptions from customers",
        inputs=[
            ProcessInput(name="customer_email", source="email"),
            ProcessInput(name="invoice_file", source="file", required=False),
        ],
        outputs=[
            ProcessOutput(name="validated_order", destination="erp"),
        ],
        steps=[
            ProcessStep(
                sequence=1,
                action="Open email",
                tool="Outlook",
                decision=None,
                irritant_score=0.1,
            ),
            ProcessStep(
                sequence=2,
                action="Search for customer in ERP",
                tool="SAP",
                decision="if client absent → create",
                irritant_score=0.5,
                related_event_types=["erp_event"],
            ),
        ],
        state=ProcedureState.DECLARED,
        version="1.0.0",
    )
    assert proc.name == "invoice-exception-handling"
    assert len(proc.steps) == 2
    assert len(proc.inputs) == 2
    assert len(proc.outputs) == 1


def test_process_definition_steps_ordering_enforced() -> None:
    with pytest.raises((ValueError, ValidationError)):
        ProcessDefinition(
            name="test",
            process_context="ctx",
            trigger="start",
            steps=[
                ProcessStep(sequence=2, action="Second", tool="App"),
                ProcessStep(sequence=1, action="First", tool="App"),
            ],
        )


def test_process_step_irritant_score_bounds() -> None:
    with pytest.raises(ValidationError):
        ProcessStep(
            sequence=1,
            action="Do something",
            tool="App",
            irritant_score=1.5,
        )


def test_process_step_irritant_score_zero() -> None:
    step = ProcessStep(sequence=1, action="Do something", tool="App", irritant_score=0.0)
    assert step.irritant_score == 0.0


def test_process_step_irritant_score_one() -> None:
    step = ProcessStep(sequence=1, action="Do something", tool="App", irritant_score=1.0)
    assert step.irritant_score == 1.0


def test_process_input_output_models() -> None:
    inp = ProcessInput(name="customer_email", source="email")
    assert inp.name == "customer_email"
    assert inp.source == "email"
    assert inp.required is True
    assert inp.schema_version == "1.0"

    out = ProcessOutput(name="validated_order", destination="erp")
    assert out.name == "validated_order"
    assert out.destination == "erp"
    assert out.schema_version == "1.0"

    inp_optional = ProcessInput(name="attachment", source="file", required=False)
    assert inp_optional.required is False


# ---------------------------------------------------------------------------
# Version bumping utility
# ---------------------------------------------------------------------------


def test_bump_minor_version_basic() -> None:
    assert _bump_minor_version("1.0.0") == "1.1.0"


def test_bump_minor_version_nonzero() -> None:
    assert _bump_minor_version("2.3.4") == "2.4.0"


def test_bump_minor_version_large() -> None:
    assert _bump_minor_version("0.9.99") == "0.10.0"
