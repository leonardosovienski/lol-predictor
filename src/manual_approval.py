"""Aprovação humana local para o registro de uma ordem já elegível."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def bet_fingerprint(
    *, market: str, selection: str, prob_model: float, decimal_odds: float, bankroll: float, **_: Any
) -> str:
    payload = {
        "market": market,
        "selection": selection,
        "prob_model": round(float(prob_model), 8),
        "decimal_odds": round(float(decimal_odds), 8),
        "bankroll": round(float(bankroll), 2),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def require_manual_approval(
    path: str | Path | None, *, fingerprint: str, now: datetime | None = None
) -> dict[str, Any]:
    if path is None:
        raise PermissionError("aposta real exige arquivo de aprovação manual")
    try:
        approval = json.loads(Path(path).read_text(encoding="utf-8"))
        approved_at = datetime.fromisoformat(approval["approved_at"].replace("Z", "+00:00"))
        expires_at = datetime.fromisoformat(approval["expires_at"].replace("Z", "+00:00"))
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PermissionError("arquivo de aprovação manual inválido") from exc
    current = now or datetime.now(UTC)
    if (
        approval.get("schema_version") != 1
        or approval.get("status") != "APPROVED"
        or not isinstance(approval.get("approval_id"), str)
        or not isinstance(approval.get("approved_by"), str)
        or not approval["approved_by"].strip()
        or approval.get("bet_fingerprint") != fingerprint
        or approved_at.tzinfo is None
        or expires_at.tzinfo is None
        or approved_at > current
        or expires_at <= current
    ):
        raise PermissionError("aprovação manual não é válida para esta ordem")
    return {k: approval[k] for k in ("approval_id", "approved_by", "approved_at", "expires_at")}
