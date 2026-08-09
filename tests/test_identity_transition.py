from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.holdout import collect_holdout
from src.identity import IdentityError, IdentityRegistry

ROOT = Path(__file__).resolve().parents[1]


def test_registry_resolves_oracle_id_and_rejects_fuzzy_name() -> None:
    registry = IdentityRegistry(ROOT / "data" / "canonical_teams.json")
    team = registry.resolve(provider="oracles_elixir", name="T1")
    assert team.canonical_id.startswith("lol-team-")
    assert registry.resolve(provider="oracles_elixir", provider_id=team.oracle_ids[0]) == team
    with pytest.raises(IdentityError, match="unknown"):
        registry.resolve(provider="oracles_elixir", name="T")


class _Market:
    def list_upcoming_matches(self, horizon_hours, now):
        return [
            {
                "team_a": "T1",
                "team_b": "Gen.G",
                "event_id": "42",
                "scheduled_at": "2026-08-10T12:00:00+00:00",
            }
        ]

    def fetch_match(self, team_a, team_b, observed_at, event_id):
        return {"event_id": event_id, "team_a": team_a, "team_b": team_b, "observed_at": observed_at.isoformat()}


def test_holdout_is_immutable_and_declared_ineligible_for_training(tmp_path: Path) -> None:
    now = datetime(2026, 8, 9, 12, tzinfo=UTC)
    first = collect_holdout(tmp_path, provider=_Market(), now=now)
    second = collect_holdout(tmp_path, provider=_Market(), now=now)
    assert first["capture_id"] == second["capture_id"]
    capture = json.loads(Path(first["path"]).read_text(encoding="utf-8"))
    assert capture["scientific_state"] == "COLLECTION_ONLY"
    assert capture["training_eligible"] is False
    assert not (tmp_path / "backtest_manifest.json").exists()
    assert not (tmp_path / "current_freeze.json").exists()
