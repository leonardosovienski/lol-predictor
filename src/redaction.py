"""Small, local secret-redaction helpers for operational logs."""

from __future__ import annotations

import os
from collections.abc import Iterable

_SENSITIVE_MARKERS = ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "AUTH")


def collect_sensitive_values(environ: dict[str, str] | None = None) -> set[str]:
    """Return non-empty values of conventionally sensitive environment keys."""
    values = environ if environ is not None else os.environ
    return {
        value for key, value in values.items() if value and any(marker in key.upper() for marker in _SENSITIVE_MARKERS)
    }


def safe_redact_text(text: str, sensitive_values: Iterable[str]) -> str:
    """Replace known secrets longest-first to avoid partial-value leakage."""
    redacted = str(text)
    for value in sorted(set(sensitive_values), key=len, reverse=True):
        if value:
            redacted = redacted.replace(value, "[REDACTED]")
    return redacted
