"""FlowFabric bridge — notifies FlowFabric when a FieldObservation is validated.

This is a fire-and-forget webhook call.  Jean does not depend on FlowFabric
being available.  If the call fails, it is logged but not re-raised.

Configuration:
    JEAN_FLOWFABRIC_WEBHOOK — URL of the FlowFabric Human Gate webhook.
                               If unset, the bridge is a silent no-op.

Payload sent to FlowFabric::

    {
        "observation_id": "...",
        "process_context": "invoice-exception",
        "gap_score": 0.7,
        "validated_by": "manager@company.com",
        "validated_at": "2026-03-24T12:00:00+00:00"
    }

FlowFabric can use this to trigger a Human Gate approval or to route the
observation into its workflow orchestration engine.
"""

from __future__ import annotations

import os

import httpx
import structlog

from jean.models import FieldObservation

log = structlog.get_logger()

_ENV_VAR = "JEAN_FLOWFABRIC_WEBHOOK"
_TIMEOUT = 5.0


class FlowFabricBridge:
    """Sends a validated FieldObservation notification to FlowFabric.

    Args:
        webhook_url: FlowFabric webhook endpoint.  If None, reads from
                     the JEAN_FLOWFABRIC_WEBHOOK env var.  If still None,
                     the bridge is a no-op.
    """

    def __init__(self, webhook_url: str | None = None) -> None:
        self.webhook_url: str | None = webhook_url or os.environ.get(_ENV_VAR)

    def is_configured(self) -> bool:
        return bool(self.webhook_url)

    async def notify(self, observation: FieldObservation) -> None:
        """POST observation data to FlowFabric.

        Never raises — failures are logged and swallowed.
        """
        if not self.webhook_url:
            log.debug("FlowFabricBridge: no webhook URL configured — skipping")
            return

        payload = {
            "observation_id": observation.id,
            "process_context": observation.process_context,
            "gap_score": observation.gap_score,
            "validated_by": observation.validated_by,
            "validated_at": (
                observation.validated_at.isoformat()
                if observation.validated_at
                else None
            ),
        }

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(self.webhook_url, json=payload)
                resp.raise_for_status()
            log.info(
                "FlowFabricBridge: notification sent",
                observation_id=observation.id,
                status=resp.status_code,
            )
        except httpx.HTTPError as exc:
            log.warning(
                "FlowFabricBridge: notification failed (non-fatal)",
                observation_id=observation.id,
                error=str(exc),
            )
