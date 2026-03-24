"""Tests for CorpusPipeline."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from jean.corpus_feeder.adapter import MockKFabricAdapter
from jean.corpus_feeder.pipeline import CorpusPipeline
from jean.models import FieldObservation, ProcedureState


def _validated_obs(obs_id: str = "obs-1") -> FieldObservation:
    return FieldObservation(
        id=obs_id,
        process_context="invoice-exception",
        declared_procedure="Route > 1000 to manager",
        observed_behavior="Processed up to 5000 directly",
        gap_score=0.7,
        supporting_patterns=["p1"],
        state=ProcedureState.VALIDATED,
        validated_at=datetime.now(timezone.utc),
        validated_by="manager@co.com",
    )


def _observed_obs() -> FieldObservation:
    return FieldObservation(
        process_context="invoice-exception",
        declared_procedure="Route > 1000 to manager",
        observed_behavior="Processed up to 5000 directly",
        gap_score=0.7,
        supporting_patterns=["p1"],
    )


@pytest.mark.asyncio
async def test_pipeline_rejects_non_validated():
    pipeline = CorpusPipeline()
    with pytest.raises(ValueError, match="VALIDATED"):
        await pipeline.run(_observed_obs())


@pytest.mark.asyncio
async def test_pipeline_calls_adapter_submit():
    adapter = MockKFabricAdapter()
    pipeline = CorpusPipeline(adapter=adapter)
    obs = _validated_obs()
    corpus_id = await pipeline.run(obs)
    assert corpus_id.startswith("kfabric-mock-")
    assert len(adapter.stored) == 1
    assert adapter.stored[0].id == obs.id


@pytest.mark.asyncio
async def test_pipeline_returns_corpus_id():
    adapter = MockKFabricAdapter()
    pipeline = CorpusPipeline(adapter=adapter)
    corpus_id = await pipeline.run(_validated_obs())
    assert corpus_id == "kfabric-mock-0001"


@pytest.mark.asyncio
async def test_pipeline_sequential_ids():
    adapter = MockKFabricAdapter()
    pipeline = CorpusPipeline(adapter=adapter)
    id1 = await pipeline.run(_validated_obs("obs-1"))
    id2 = await pipeline.run(_validated_obs("obs-2"))
    assert id1 != id2
    assert len(adapter.stored) == 2
