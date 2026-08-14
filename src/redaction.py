"""Small, local secret-redaction helpers for operational logs."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable

_SENSITIVE_MARKERS = ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "AUTH")


def collect_sensitive_values(environ: dict[str, str] | None = None) -> set[str]:
    """Return non-empty values of conventionally sensitive environment keys."""
    values = environ if environ is not None else os.environ
    return {
        value for key, value in values.items() if value and any(marker in key.upper() for marker in _SENSITIVE_MARKERS)
    }


def safe_redact_text(text: str, sensitive_values: Iterable[str]) -> str:
    """Replace known secrets, longest-first, matched only at token boundaries.

    A boundary match (not a raw substring replace) so that a short secret
    doesn't collaterally redact unrelated digits/hashes that merely contain
    it — e.g. a 1-char env value used to turn every matching digit inside
    every date/count/hash in a log line into "[REDACTED]". A secret only
    matches where it is not itself embedded inside a longer
    letter/digit/underscore run, so it still redacts wherever the real
    value actually appears as its own token.
    """
    redacted = str(text)
    for value in sorted(set(sensitive_values), key=len, reverse=True):
        if not value:
            continue
        pattern = r"(?<![0-9A-Za-z_])" + re.escape(value) + r"(?![0-9A-Za-z_])"
        redacted = re.sub(pattern, "[REDACTED]", redacted)
    return redacted
