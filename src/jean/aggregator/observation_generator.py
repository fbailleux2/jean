"""ObservationGenerator and ObservationDispatcher for jean-aggregator.

Converts PatternHypotheses that exceed a confidence threshold into
FieldObservations, then POSTs them to jean-validator via HTTP.

Configuration:
    JEAN_VALIDATOR_URL — validator base URL (e.g. http://localhost:8200).
                         Dispatch is skipped if unset.
    JEAN_OBS_THRESHOLD — minimum confidence to trigger observation generation.
                         Default: 0.7
"""

from __future__ import annotations

import os

import httpx
import structlog

from jean.models import FieldObservation, PatternHypothesis

log = structlog.get_logger()

_DEFAULT_THRESHOLD = 0.7
_VALIDATOR_URL_ENV = "JEAN_VALIDATOR_URL"
_THRESHOLD_ENV = "JEAN_OBS_THRESHOLD"


class ObservationGenerator:
    """Converts high-confidence PatternHypotheses into FieldObservations."""

    def __init__(self, threshold: float | None = None) -> None:
        if threshold is not None:
            self.threshold = threshold
        else:
            raw = os.environ.get(_THRESHOLD_ENV)
            self.threshold = float(raw) if raw else _DEFAULT_THRESHOLD

    def generate(self, hypotheses: list[PatternHypothesis]) -> list[FieldObservation]:
        """Return FieldObservations for hypotheses above the threshold.

        Only hypotheses with confidence >= self.threshold are converted.
        """
        observations: list[FieldObservation] = []
        for hyp in hypotheses:
            if hyp.confidence < self.threshold:
                continue

            event_seq = " → ".join(e.value for e in hyp.pattern)
            obs = FieldObservation(
                process_context=hyp.process_context,
                declared_procedure="Undocumented — auto-generated",
                observed_behavior=(
                    f"Recurring sequence detected {hyp.frequency}x: {event_seq}"
                ),
                gap_score=hyp.confidence,
                supporting_patterns=[hyp.id],
            )
            observations.append(obs)
        return observations


class ObservationDispatcher:
    """POSTs FieldObservations to jean-validator (fire-and-forget)."""

    def __init__(self, validator_url: str | None = None) -> None:
        self.validator_url = validator_url or os.environ.get(_VALIDATOR_URL_ENV) or ""

    async def dispatch(self, obs: FieldObservation) -> None:
        """POST the observation to JEAN_VALIDATOR_URL/observations/register.

        Failure is logged and swallowed — never propagated to the caller.
        No dispatch if JEAN_VALIDATOR_URL is unset.
        """
        if not self.validator_url:
            return

        url = f"{self.validator_url.rstrip('/')}/observations/register"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(url, content=obs.model_dump_json(), headers={"Content-Type": "application/json"})
                resp.raise_for_status()
            log.info("Observation dispatched to validator", obs_id=obs.id, url=url)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "Failed to dispatch observation to validator",
                obs_id=obs.id,
                url=url,
                error=str(exc),
            )
