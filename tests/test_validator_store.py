"""Tests for ObservationStore implementations (ISC-23, ISC-24, ISC-25)."""

from __future__ import annotations

import pytest

from jean.models import FieldObservation, ProcedureState
from jean.validator.store import InMemoryObservationStore, SQLiteObservationStore


def _make_obs(obs_id: str = "obs-1", process_context: str = "test") -> FieldObservation:
    return FieldObservation(
        id=obs_id,
        process_context=process_context,
        declared_procedure="Official procedure",
        observed_behavior="Actual behavior",
        gap_score=0.6,
        supporting_patterns=["p1"],
    )


# ---------------------------------------------------------------------------
# InMemoryObservationStore
# ---------------------------------------------------------------------------


async def test_inmemory_save_and_get():
    store = InMemoryObservationStore()
    obs = _make_obs("obs-1")
    await store.save(obs)
    result = await store.get("obs-1")
    assert result is not None
    assert result.id == "obs-1"


async def test_inmemory_get_missing_returns_none():
    store = InMemoryObservationStore()
    assert await store.get("nonexistent") is None


async def test_inmemory_list_all():
    store = InMemoryObservationStore()
    await store.save(_make_obs("obs-1"))
    await store.save(_make_obs("obs-2"))
    result = await store.list()
    assert len(result) == 2


async def test_inmemory_list_filtered_by_state():
    store = InMemoryObservationStore()
    await store.save(_make_obs("obs-1"))
    result = await store.list(state="observed")
    assert len(result) == 1
    result2 = await store.list(state="validated")
    assert len(result2) == 0


async def test_inmemory_update():
    store = InMemoryObservationStore()
    obs = _make_obs("obs-1")
    await store.save(obs)
    updated = obs.model_copy(update={"state": ProcedureState.VALIDATED})
    await store.update(updated)
    result = await store.get("obs-1")
    assert result.state == ProcedureState.VALIDATED


async def test_inmemory_clear():
    store = InMemoryObservationStore()
    await store.save(_make_obs("obs-1"))
    store.clear()
    assert await store.list() == []


# ---------------------------------------------------------------------------
# ISC-23: SQLiteObservationStore save + list roundtrip
# ---------------------------------------------------------------------------


async def test_sqlite_save_and_list(tmp_path):
    db = str(tmp_path / "obs.db")
    store = SQLiteObservationStore(db)
    await store.open()
    try:
        obs = _make_obs("obs-1")
        await store.save(obs)
        result = await store.list()
        assert len(result) == 1
        assert result[0].id == "obs-1"
    finally:
        await store.close()


async def test_sqlite_get_existing(tmp_path):
    db = str(tmp_path / "obs.db")
    store = SQLiteObservationStore(db)
    await store.open()
    try:
        obs = _make_obs("obs-1")
        await store.save(obs)
        result = await store.get("obs-1")
        assert result is not None
        assert result.process_context == "test"
    finally:
        await store.close()


async def test_sqlite_get_missing_returns_none(tmp_path):
    db = str(tmp_path / "obs.db")
    store = SQLiteObservationStore(db)
    await store.open()
    try:
        result = await store.get("nope")
        assert result is None
    finally:
        await store.close()


async def test_sqlite_list_filtered_by_state(tmp_path):
    db = str(tmp_path / "obs.db")
    store = SQLiteObservationStore(db)
    await store.open()
    try:
        await store.save(_make_obs("obs-1"))  # OBSERVED
        result = await store.list(state="observed")
        assert len(result) == 1
        result2 = await store.list(state="validated")
        assert len(result2) == 0
    finally:
        await store.close()


# ---------------------------------------------------------------------------
# ISC-24: SQLiteObservationStore update persists state change
# ---------------------------------------------------------------------------


async def test_sqlite_update_persists(tmp_path):
    db = str(tmp_path / "obs.db")
    store = SQLiteObservationStore(db)
    await store.open()
    try:
        obs = _make_obs("obs-1")
        await store.save(obs)
        updated = obs.model_copy(update={"state": ProcedureState.VALIDATED})
        await store.update(updated)

        result = await store.get("obs-1")
        assert result.state == ProcedureState.VALIDATED
    finally:
        await store.close()


async def test_sqlite_persists_across_reopen(tmp_path):
    """Observations survive store close/reopen (persistence test)."""
    db = str(tmp_path / "obs.db")
    store1 = SQLiteObservationStore(db)
    await store1.open()
    await store1.save(_make_obs("obs-persist"))
    await store1.close()

    store2 = SQLiteObservationStore(db)
    await store2.open()
    try:
        result = await store2.get("obs-persist")
        assert result is not None
        assert result.id == "obs-persist"
    finally:
        await store2.close()


# ---------------------------------------------------------------------------
# ISC-32: GET /patterns?process_context filter
# ---------------------------------------------------------------------------


def test_patterns_filter_by_process_context():
    from fastapi.testclient import TestClient
    from jean.aggregator.api import app, _patterns
    import jean.aggregator.api as agg

    from jean.models import PatternHypothesis, EventType

    # Inject two patterns with different process contexts
    p1 = PatternHypothesis(
        pattern=[EventType.APP_FOCUS],
        frequency=3,
        confidence=0.8,
        source_trace_ids=["t1"],
        process_context="invoice",
    )
    p2 = PatternHypothesis(
        pattern=[EventType.SAVE],
        frequency=2,
        confidence=0.7,
        source_trace_ids=["t2"],
        process_context="payroll",
    )
    original = agg._patterns[:]
    agg._patterns = [p1, p2]

    client = TestClient(app)
    try:
        r = client.get("/patterns?process_context=invoice")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["process_context"] == "invoice"

        r2 = client.get("/patterns")
        assert len(r2.json()) == 2
    finally:
        agg._patterns = original


# ---------------------------------------------------------------------------
# ISC-33: GET /observations pagination
# ---------------------------------------------------------------------------


def test_observations_pagination():
    from fastapi.testclient import TestClient
    from jean.validator.api import app, get_store, register_observation

    get_store().clear()
    for i in range(5):
        register_observation(_make_obs(f"pg-obs-{i}"))

    client = TestClient(app)
    r = client.get("/observations?limit=2&offset=1")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2

    get_store().clear()
