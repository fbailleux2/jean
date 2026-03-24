"""Anonymizer — strips PII from BusinessEvents before corpus ingestion.

Rule: if a field name is in the PII_FIELDS set (or matched by the config),
its value is replaced with a redaction marker.

This is a GDPR/CNIL-compliance measure.  The field list is configurable
at deployment time via the aggregator config.
"""

from __future__ import annotations

import copy
import re

from jean.models import BusinessEvent

# Default set of payload keys that must never reach KFabric
DEFAULT_PII_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "first_name",
        "last_name",
        "email",
        "phone",
        "address",
        "username",
        "user_id",
        "employee_id",
        "ip_address",
        "mac_address",
        "ssn",
        "birthdate",
        "password",
    }
)

_REDACTED = "[REDACTED]"


def _redact_dict(data: dict, pii_fields: frozenset[str]) -> dict:
    """Recursively redact PII fields in a dict."""
    result: dict = {}
    for k, v in data.items():
        if k.lower() in pii_fields:
            result[k] = _REDACTED
        elif isinstance(v, dict):
            result[k] = _redact_dict(v, pii_fields)
        else:
            result[k] = v
    return result


class Anonymizer:
    """Strips PII from BusinessEvent payloads.

    Usage::

        anon = Anonymizer()
        clean_event = anon.anonymize(raw_event)
    """

    def __init__(self, extra_pii_fields: set[str] | None = None) -> None:
        self.pii_fields = DEFAULT_PII_FIELDS | frozenset(
            f.lower() for f in (extra_pii_fields or set())
        )

    def anonymize(self, event: BusinessEvent) -> BusinessEvent:
        """Return a new BusinessEvent with PII stripped from the payload."""
        clean_payload = _redact_dict(event.payload, self.pii_fields)
        return event.model_copy(update={"payload": clean_payload})

    def anonymize_many(self, events: list[BusinessEvent]) -> list[BusinessEvent]:
        return [self.anonymize(e) for e in events]
