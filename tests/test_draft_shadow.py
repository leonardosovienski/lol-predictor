from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from src.draft_shadow import DraftShadowError, normalize_observation, validate_chain

BASE = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)


def _roster(prefix):
    return [
        {"player_id": f"{prefix}-{role}", "role": role, "known_at": (BASE - timedelta(hours=2)).isoformat()}
        for role in ("top", "jungle", "mid", "bot", "support")
    ]


def _raw(point="PRE_DRAFT"):
    observed = {"PRE_DRAFT": BASE, "POST_DRAFT": BASE + timedelta(minutes=15),
                "CLOSING": BASE + timedelta(minutes=20)}[point]
    row = {
        "canonical_event_id": "pandascore:1", "source_event_id": "1",
        "competition_id": "lck", "competition_name": "LCK", "market": "SERIES_WINNER",
        "market_id": "m1", "condition_id": "c1", "selection": "team_a",
        "decision_point": point, "observed_at": observed.isoformat(),
        "published_at": observed.isoformat(), "scheduled_at": (BASE + timedelta(minutes=30)).isoformat(),
        "market_cutoff_at": (BASE + timedelta(minutes=25)).isoformat(),
        "draft_started_at": (BASE + timedelta(minutes=5)).isoformat(),
        "team_a_id": "lol:a", "team_b_id": "lol:b", "roster_a": _roster("a"),
        "roster_b": _roster("b"), "substitutes_a": [], "substitutes_b": [], "patch": "26.16",
        "best_bid": .52, "best_ask": .54, "best_bid_size": 100, "best_ask_size": 80,
        "model_probability": .58, "settlement_policy": "official-series-winner-v1",
        "source": "polymarket-clob",
    }
    if point != "PRE_DRAFT":
        row["draft_completed_at"] = (BASE + timedelta(minutes=14)).isoformat()
        row["draft_actions"] = [
            {"sequence": 1, "kind": "BAN", "team": "a", "champion": "Aurora"},
            {"sequence": 2, "kind": "PICK", "team": "b", "champion": "Vi"},
        ]
    return row


def test_observation_uses_executable_ask_and_is_permanently_shadow():
    row = normalize_observation(_raw())
    assert row["spread"] == pytest.approx(.02)
    assert row["executable_decimal_odds"] == pytest.approx(1 / .54)
    assert row["mode"] == "SHADOW" and row["capital_authorized"] is False
    assert len(row["observation_id"]) == len(row["content_sha256"]) == 64


def test_pre_draft_rejects_future_draft_information():
    row = _raw()
    row["draft_actions"] = [{"sequence": 1}]
    with pytest.raises(DraftShadowError, match="informação futura"):
        normalize_observation(row)


def test_roster_must_be_known_at_decision_time():
    row = _raw()
    row["roster_a"][0]["known_at"] = (BASE + timedelta(seconds=1)).isoformat()
    with pytest.raises(DraftShadowError, match="depois da decisão"):
        normalize_observation(row)


def test_complete_chain_is_comparable_and_ordered():
    chain = validate_chain([_raw("CLOSING"), _raw("PRE_DRAFT"), _raw("POST_DRAFT")])
    assert chain["mode"] == "SHADOW" and chain["capital_authorized"] is False
    assert len(chain["observation_ids"]) == 3


def test_chain_rejects_market_drift():
    closing = deepcopy(_raw("CLOSING"))
    closing["market_id"] = "other"
    with pytest.raises(DraftShadowError, match="mistura"):
        validate_chain([_raw("PRE_DRAFT"), _raw("POST_DRAFT"), closing])
