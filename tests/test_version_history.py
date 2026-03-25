"""Tests for ProcessStore version history tracking."""

from __future__ import annotations

import pytest

from jean.models import ProcessDefinition, ProcessVersionEntry
from jean.process_mapper.store import ProcessStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_process(version: str = "1.0.0") -> ProcessDefinition:
    return ProcessDefinition(
        name="test-process",
        process_context="test-ctx",
        trigger="test trigger",
        version=version,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_first_save_creates_history_entry():
    """Saving a process for the first time creates exactly one history entry."""
    store = ProcessStore()
    process = _make_process()
    store.save(process)
    history = store.get_version_history(process.id)
    assert len(history) == 1
    assert isinstance(history[0], ProcessVersionEntry)


def test_second_save_appends_history():
    """Saving a process twice results in two history entries."""
    store = ProcessStore()
    process = _make_process()
    store.save(process)
    store.save(process)
    history = store.get_version_history(process.id)
    assert len(history) == 2


def test_version_recorded_in_entry():
    """The version in the history entry matches the process version at save time."""
    store = ProcessStore()
    process = _make_process(version="2.3.0")
    store.save(process)
    entry = store.get_version_history(process.id)[0]
    assert entry.version == "2.3.0"


def test_get_history_nonexistent():
    """get_version_history for an unknown process_id returns an empty list."""
    store = ProcessStore()
    result = store.get_version_history("nonexistent-id")
    assert result == []


def test_history_entries_are_ordered():
    """Multiple saves produce entries in insertion order (oldest first)."""
    store = ProcessStore()
    # Simulate three saves with different versions by creating new objects
    p1 = ProcessDefinition(
        name="proc",
        process_context="ctx",
        trigger="t",
        version="1.0.0",
    )
    store.save(p1)

    # Rebuild same id with bumped version
    data = p1.model_dump()
    data["version"] = "1.1.0"
    p2 = ProcessDefinition.model_validate(data)
    store.save(p2)

    data["version"] = "1.2.0"
    p3 = ProcessDefinition.model_validate(data)
    store.save(p3)

    history = store.get_version_history(p1.id)
    assert len(history) == 3
    versions = [e.version for e in history]
    assert versions == ["1.0.0", "1.1.0", "1.2.0"]
