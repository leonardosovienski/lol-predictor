"""Fail-closed contracts for the prospective pre/post-draft shadow study.

This module records observations only.  It cannot create bets, promote a
scientific gate, or authorize real-money execution.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from typing import Any

SCHEMA = "lol-draft-market-observation/1.0"
DECISION_POINTS = frozenset({"PRE_DRAFT", "POST_DRAFT", "CLOSING"})
MARKETS = frozenset({"SERIES_WINNER", "MAP_WINNER"})


class DraftShadowError(ValueError):
    pass


def _time(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise DraftShadowError(f"{field} inválido") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DraftShadowError(f"{field} sem timezone")
    return parsed.astimezone(UTC)


def _number(value: Any, field: str, *, positive: bool = False) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise DraftShadowError(f"{field} inválido") from exc
    if not math.isfinite(result) or (positive and result <= 0):
        raise DraftShadowError(f"{field} inválido")
    return result


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def normalize_observation(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate one immutable, executable-price observation.

    PRE_DRAFT requires a known draft start and must precede it. POST_DRAFT
    requires the complete ordered draft and must follow its completion.
    CLOSING is the last eligible quote before the declared market cutoff.
    """
    required = (
        "canonical_event_id", "source_event_id", "competition_id", "competition_name",
        "market", "market_id", "condition_id", "selection", "decision_point",
        "observed_at", "published_at", "scheduled_at", "market_cutoff_at",
        "team_a_id", "team_b_id", "roster_a", "roster_b", "patch",
        "best_bid", "best_ask", "best_bid_size", "best_ask_size",
        "model_probability", "settlement_policy", "source",
    )
    missing = [field for field in required if raw.get(field) in (None, "", [], {})]
    if missing:
        raise DraftShadowError(f"observação sem contrato: {missing}")
    if raw["market"] not in MARKETS:
        raise DraftShadowError("mercado inválido")
    if raw["decision_point"] not in DECISION_POINTS:
        raise DraftShadowError("momento da decisão inválido")
    if raw["team_a_id"] == raw["team_b_id"]:
        raise DraftShadowError("times canônicos idênticos")
    if raw["selection"] not in {"team_a", "team_b"}:
        raise DraftShadowError("seleção inválida")

    published = _time(raw["published_at"], "published_at")
    observed = _time(raw["observed_at"], "observed_at")
    cutoff = _time(raw["market_cutoff_at"], "market_cutoff_at")
    scheduled = _time(raw["scheduled_at"], "scheduled_at")
    if not published <= observed < cutoff <= scheduled:
        raise DraftShadowError("violação temporal do book/cutoff")

    rosters: dict[str, list[dict[str, Any]]] = {}
    for side in ("a", "b"):
        roster = raw[f"roster_{side}"]
        if not isinstance(roster, list) or len(roster) != 5:
            raise DraftShadowError(f"roster_{side} deve ter cinco titulares")
        players = []
        for player in roster:
            if not isinstance(player, dict) or not player.get("player_id") or not player.get("role"):
                raise DraftShadowError(f"roster_{side} inválido")
            known_at = _time(player.get("known_at"), f"roster_{side}.known_at")
            if known_at > observed:
                raise DraftShadowError("roster conhecido depois da decisão")
            players.append({**player, "known_at": known_at.isoformat()})
        if len({player["player_id"] for player in players}) != 5:
            raise DraftShadowError(f"roster_{side} contém jogador duplicado")
        rosters[side] = players

    point = raw["decision_point"]
    draft_started = _time(raw.get("draft_started_at"), "draft_started_at")
    if point == "PRE_DRAFT" and not observed < draft_started:
        raise DraftShadowError("PRE_DRAFT não precede o primeiro ban")
    ordered_draft = raw.get("draft_actions")
    if point in {"POST_DRAFT", "CLOSING"}:
        completed = _time(raw.get("draft_completed_at"), "draft_completed_at")
        if completed > published:
            raise DraftShadowError("book pós-draft publicado antes do draft completo")
        if not isinstance(ordered_draft, list) or not ordered_draft:
            raise DraftShadowError("draft temporal completo ausente")
        expected = list(range(1, len(ordered_draft) + 1))
        if [action.get("sequence") for action in ordered_draft if isinstance(action, dict)] != expected:
            raise DraftShadowError("ordem temporal do draft inválida")
    elif ordered_draft:
        raise DraftShadowError("PRE_DRAFT não pode carregar informação futura do draft")

    if raw["market"] == "MAP_WINNER" and raw.get("map_number") in (None, ""):
        raise DraftShadowError("MAP_WINNER exige map_number")
    bid = _number(raw["best_bid"], "best_bid")
    ask = _number(raw["best_ask"], "best_ask")
    bid_size = _number(raw["best_bid_size"], "best_bid_size", positive=True)
    ask_size = _number(raw["best_ask_size"], "best_ask_size", positive=True)
    probability = _number(raw["model_probability"], "model_probability")
    if not 0 < bid <= ask < 1 or not 0 < probability < 1:
        raise DraftShadowError("preço/probabilidade fora do intervalo")

    payload = {
        **raw,
        "schema_version": SCHEMA,
        "published_at": published.isoformat(),
        "observed_at": observed.isoformat(),
        "market_cutoff_at": cutoff.isoformat(),
        "scheduled_at": scheduled.isoformat(),
        "roster_a": rosters["a"],
        "roster_b": rosters["b"],
        "best_bid": bid,
        "best_ask": ask,
        "best_bid_size": bid_size,
        "best_ask_size": ask_size,
        "spread": ask - bid,
        "executable_decimal_odds": 1 / ask,
        "model_probability": probability,
        "mode": "SHADOW",
        "capital_authorized": False,
        "settlement_status": raw.get("settlement_status", "PENDING"),
    }
    identity = {
        key: payload[key]
        for key in ("canonical_event_id", "market", "market_id", "selection", "decision_point", "published_at")
    }
    payload["observation_id"] = _hash(identity)
    payload["content_sha256"] = _hash({key: value for key, value in payload.items() if key != "content_sha256"})
    return payload


def validate_chain(observations: list[dict[str, Any]]) -> dict[str, Any]:
    """Require comparable PRE_DRAFT, POST_DRAFT and CLOSING observations."""
    normalized = [normalize_observation(row) for row in observations]
    if len(normalized) != 3 or {row["decision_point"] for row in normalized} != DECISION_POINTS:
        raise DraftShadowError("cadeia exige PRE_DRAFT, POST_DRAFT e CLOSING")
    invariant = ("canonical_event_id", "market", "market_id", "condition_id", "selection", "settlement_policy")
    if any(any(row[field] != normalized[0][field] for field in invariant) for row in normalized[1:]):
        raise DraftShadowError("cadeia mistura evento, mercado, seleção ou settlement")
    ordered = sorted(normalized, key=lambda row: _time(row["observed_at"], "observed_at"))
    if [row["decision_point"] for row in ordered] != ["PRE_DRAFT", "POST_DRAFT", "CLOSING"]:
        raise DraftShadowError("ordem temporal da cadeia inválida")
    return {
        "schema_version": "lol-draft-market-chain/1.0",
        "mode": "SHADOW",
        "capital_authorized": False,
        "canonical_event_id": ordered[0]["canonical_event_id"],
        "observation_ids": [row["observation_id"] for row in ordered],
        "chain_sha256": _hash([row["content_sha256"] for row in ordered]),
    }
