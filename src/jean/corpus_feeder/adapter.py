"""KFabricAdapter — interface and implementations for corpus feeding.

jean-corpus-feeder submits validated FieldObservations to KFabric.

Implementations:
- MockKFabricAdapter : in-memory, for development and testing (default)
- HttpKFabricAdapter : real HTTP client, configured via JEAN_KFABRIC_URL

Selection via make_adapter():
    JEAN_KFABRIC_URL set   → HttpKFabricAdapter
    JEAN_KFABRIC_URL unset → MockKFabricAdapter

KFabric ingest API contract (provisional):
    POST {base_url}/ingest
        body: FieldObservation JSON
        response: {"entry_id": "..."}
    GET  {base_url}/health
        response: {"status": "ok"}
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod

import httpx
import structlog

from jean.models import FieldObservation, ProcedureState

log = structlog.get_logger()

_KFABRIC_URL_ENV = "JEAN_KFABRIC_URL"
_DEFAULT_TIMEOUT = 10.0


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


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# MockKFabricAdapter
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# HttpKFabricAdapter
# ---------------------------------------------------------------------------


class HttpKFabricAdapter(KFabricAdapter):
    """Real HTTP client for KFabric corpus ingestion.

    Args:
        base_url: KFabric base URL (e.g. "http://kfabric:8300").
                  Reads JEAN_KFABRIC_URL env var if not provided.
        timeout:  HTTP request timeout in seconds.

    Error semantics:
        4xx → ValueError  (bad request, do not retry)
        5xx → RuntimeError (transient, caller may retry)
    """

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = (base_url or os.environ.get(_KFABRIC_URL_ENV, "")).rstrip("/")
        self.timeout = timeout
        if not self.base_url:
            raise ValueError(
                f"KFabric URL is required. "
                f"Set JEAN_KFABRIC_URL or pass base_url= to HttpKFabricAdapter."
            )

    async def submit(self, request: FeedRequest) -> str:
        """POST a validated observation to KFabric /ingest.

        Returns the corpus entry ID from the response.
        """
        payload = request.observation.model_dump(mode="json")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(f"{self.base_url}/ingest", json=payload)
            except httpx.HTTPError as exc:
                raise RuntimeError(f"KFabric unreachable: {exc}") from exc

        if 400 <= resp.status_code < 500:
            raise ValueError(
                f"KFabric rejected observation (HTTP {resp.status_code}): {resp.text}"
            )
        if resp.status_code >= 500:
            raise RuntimeError(
                f"KFabric server error (HTTP {resp.status_code}): {resp.text}"
            )

        data = resp.json()
        entry_id: str = data.get("entry_id", f"kfabric-{request.observation.id[:8]}")
        log.info(
            "HttpKFabric: observation submitted",
            entry_id=entry_id,
            observation_id=request.observation.id,
        )
        return entry_id

    async def health(self) -> bool:
        """Return True if KFabric /health responds 200."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/health")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_adapter() -> KFabricAdapter:
    """Return the configured KFabricAdapter.

    If JEAN_KFABRIC_URL is set → HttpKFabricAdapter.
    Otherwise             → MockKFabricAdapter (safe default).
    """
    url = os.environ.get(_KFABRIC_URL_ENV)
    if url:
        return HttpKFabricAdapter(base_url=url)
    return MockKFabricAdapter()
