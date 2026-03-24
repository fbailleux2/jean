"""KFabricAdapter — interface and mock implementation for corpus feeding.

jean-corpus-feeder submits validated FieldObservations to KFabric.
In the MVP, KFabric is not deployed — the MockKFabricAdapter logs the
submission and stores it in memory for inspection.

Production implementation: replace MockKFabricAdapter with an HTTP client
pointing at the real KFabric ingest API.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import structlog

from jean.models import FieldObservation, ProcedureState

log = structlog.get_logger()


class FeedRequest:
    """Validated wrapper around a FieldObservation before KFabric submission."""

    def __init__(self, observation: FieldObservation) -> None:
        if observation.state not in (
            ProcedureState.VALIDATED,
            ProcedureState.RECOMMENDED,
        ):
            raise ValueError(
                f"Only VALIDATED or RECOMMENDED observations can be fed to KFabric. "
                f"Got: {observation.state!r}"
            )
        if not observation.is_validated() and observation.state == ProcedureState.VALIDATED:
            raise ValueError(
                "VALIDATED observation must have validated_at and validated_by set."
            )
        self.observation = observation

    def __repr__(self) -> str:
        return (
            f"FeedRequest(id={self.observation.id!r}, "
            f"state={self.observation.state!r}, "
            f"gap_score={self.observation.gap_score:.2f})"
        )


class KFabricAdapter(ABC):
    """Abstract interface for KFabric corpus feeding."""

    @abstractmethod
    async def submit(self, request: FeedRequest) -> str:
        """Submit a validated observation to KFabric.

        Returns the corpus entry ID assigned by KFabric.
        """
        ...

    @abstractmethod
    async def health(self) -> bool:
        """Return True if KFabric is reachable."""
        ...


class MockKFabricAdapter(KFabricAdapter):
    """In-memory mock for development and testing."""

    def __init__(self) -> None:
        self._store: list[FieldObservation] = []

    async def submit(self, request: FeedRequest) -> str:
        self._store.append(request.observation)
        entry_id = f"kfabric-mock-{len(self._store):04d}"
        log.info(
            "MockKFabric: observation submitted",
            entry_id=entry_id,
            observation_id=request.observation.id,
            gap_score=request.observation.gap_score,
        )
        return entry_id

    async def health(self) -> bool:
        return True

    @property
    def stored(self) -> list[FieldObservation]:
        return list(self._store)
