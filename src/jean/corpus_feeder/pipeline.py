"""CorpusPipeline — end-to-end flow from validated observation to KFabric.

This module wires:
  FieldObservation (VALIDATED) → FeedRequest → KFabricAdapter → corpus entry ID

Usage::

    pipeline = CorpusPipeline()
    corpus_id = await pipeline.run(validated_observation)

The adapter is injectable for testing.  Default is MockKFabricAdapter.
"""

from __future__ import annotations

import structlog

from jean.corpus_feeder.adapter import FeedRequest, KFabricAdapter, MockKFabricAdapter
from jean.models import FieldObservation, ProcedureState

log = structlog.get_logger()


class CorpusPipeline:
    """Submits a validated FieldObservation to KFabric.

    Args:
        adapter: KFabricAdapter implementation.  Defaults to MockKFabricAdapter.
    """

    def __init__(self, adapter: KFabricAdapter | None = None) -> None:
        self.adapter: KFabricAdapter = adapter or MockKFabricAdapter()

    async def run(self, observation: FieldObservation) -> str:
        """Submit observation to KFabric.

        Returns the corpus entry ID assigned by KFabric.

        Raises:
            ValueError: if the observation is not in VALIDATED state.
        """
        if observation.state != ProcedureState.VALIDATED:
            raise ValueError(
                f"CorpusPipeline only accepts VALIDATED observations. "
                f"Got: {observation.state!r} (id={observation.id!r})"
            )

        request = FeedRequest(observation)
        corpus_id = await self.adapter.submit(request)

        log.info(
            "Observation submitted to KFabric",
            observation_id=observation.id,
            corpus_entry_id=corpus_id,
            process_context=observation.process_context,
        )
        return corpus_id
