"""FlowFabric bridge — notifies FlowFabric when a FieldObservation is validated.

This is a best-effort webhook call with exponential backoff retry (max 3 attempts).
Jean does not hard-depend on FlowFabric being available.

Configuration:
    JEAN_FLOWFABRIC_WEBHOOK — URL of the FlowFabric Human Gate webhook.
                               If unset, the bridge is a silent no-op.
    JEAN_VALIDATOR_URL       — used to build the callback_url in the payload so
                               FlowFabric knows where to send its response.

Payload sent to FlowFabric::

    {
        "observation_id": "...",
        "process_context": "invoice-exception",
        "declared_procedure": "Route amounts > 1000 to manager",
        "observed_behavior": "Operators process up to 5000 directly",
        "gap_score": 0.7,
        "supporting_patterns": ["p1", "p2"],
        "validated_by": "manager@company.com",
        "validated_at": "2026-03-24T12:00:00+00:00",
        "callback_url": "http://jean-validator:8200/webhook/flowfabric"
    }

FlowFabric can use callback_url to POST back an approval/rejection command to Jean.
"""

from __future__ import annotations

import asyncio
import os

import httpx
import structlog

from jean.models import FieldObservation

log = structlog.get_logger()

_WEBHOOK_ENV = "JEAN_FLOWFABRIC_WEBHOOK"
_VALIDATOR_URL_ENV = "JEAN_VALIDATOR_URL"
_TIMEOUT = 5.0
_MAX_RETRIES = 3
_BACKOFF_SECONDS = [1.0, 2.0, 4.0]


class FlowFabricBridge:
    """Sends a validated FieldObservation notification to FlowFabric.

    Retries up to 3 times on 5xx or network errors, with exponential backoff.

    Args:
        webhook_url:   FlowFabric webhook endpoint.  Falls back to JEAN_FLOWFABRIC_WEBHOOK.
        validator_url: Jean validator base URL for callback_url. Falls back to JEAN_VALIDATOR_URL.
    """

    def __init__(
        self,
        webhook_url: str | None = None,
        validator_url: str | None = None,
    ) -> None:
        self.webhook_url: str | None = webhook_url or os.environ.get(_WEBHOOK_ENV)
        self.validator_url: str | None = (
            validator_url or os.environ.get(_VALIDATOR_URL_ENV) or ""
        )

    def is_configured(self) -> bool:
        return bool(self.webhook_url)

    def _build_payload(self, observation: FieldObservation) -> dict:
        callback_url = (
            f"{self.validator_url.rstrip('/')}/webhook/flowfabric"
            if self.validator_url
            else ""
        )
        return {
            "observation_id": observation.id,
            "process_context": observation.process_context,
            "declared_procedure": observation.declared_procedure,
            "observed_behavior": observation.observed_behavior,
            "gap_score": observation.gap_score,
            "supporting_patterns": observation.supporting_patterns,
            "validated_by": observation.validated_by or "",
            "validated_at": (
                observation.validated_at.isoformat()
                if observation.validated_at
                else None
            ),
            "callback_url": callback_url,
        }

    async def notify(self, observation: FieldObservation) -> None:
        """POST observation data to FlowFabric with retry.

        Never raises — all failures are logged and swallowed after max retries.
        """
        if not self.webhook_url:
            log.debug("FlowFabricBridge: no webhook URL configured — skipping")
            return

        payload = self._build_payload(observation)
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                    resp = await client.post(self.webhook_url, json=payload)
                    resp.raise_for_status()
                log.info(
                    "FlowFabricBridge: notification sent",
                    observation_id=observation.id,
                    attempt=attempt + 1,
                    status=resp.status_code,
                )
                return  # success
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500:
                    # 4xx — don't retry, log and give up
                    log.warning(
                        "FlowFabricBridge: 4xx error, not retrying",
                        observation_id=observation.id,
                        status=exc.response.status_code,
                    )
                    return
                last_exc = exc
            except httpx.HTTPError as exc:
                last_exc = exc

            if attempt < _MAX_RETRIES - 1:
                delay = _BACKOFF_SECONDS[attempt]
                log.warning(
                    "FlowFabricBridge: attempt failed, retrying",
                    observation_id=observation.id,
                    attempt=attempt + 1,
                    retry_in=delay,
                    error=str(last_exc),
                )
                await asyncio.sleep(delay)

        log.warning(
            "FlowFabricBridge: all retries exhausted (non-fatal)",
            observation_id=observation.id,
            attempts=_MAX_RETRIES,
            error=str(last_exc),
        )
