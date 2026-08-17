import json
from datetime import datetime, timezone

from src.draft_coverage import audit_draft_coverage, publish_audit


class _Market:
    def list_upcoming_matches(self, **_kwargs):
        return [{"event_id": "m1", "team_a": "T1", "team_b": "Gen.G", "scheduled_at": "2026-08-20T12:00:00Z"}]


class _Panda:
    token = "fixture"

    def list_upcoming(self, **_kwargs):
        return [{"source_event_id": "p1", "team_a": "Gen.G", "team_b": "T1", "scheduled_at": "2026-08-20T12:00:00Z"}]


def _registry(path):
    path.write_text(json.dumps({"teams": [{"providers": {"oracles_elixir": {"ids": ["oe:1"]}, "pandascore": {"ids": []}}}]}), encoding="utf-8")


def _aliases(path):
    path.write_text(json.dumps({"aliases": {}}), encoding="utf-8")


def test_audit_measures_overlap_but_keeps_draft_blocked(tmp_path):
    registry, aliases = tmp_path / "teams.json", tmp_path / "aliases.json"
    _registry(registry); _aliases(aliases)
    report = audit_draft_coverage(
        observed_at=datetime(2026, 8, 17, tzinfo=timezone.utc), polymarket=_Market(), pandascore=_Panda(),
        registry_path=registry, aliases_path=aliases, resolver=lambda name, _aliases: name,
    )
    assert report["canonical_overlap_events"] == 1
    assert report["continuity_decision"] == "BLOCKED"
    assert "DRAFT_TIMELINE_UNPROVEN" in report["blockers"]
    assert report["capital_authorized"] is False


def test_missing_pandascore_token_is_explicit_not_zero_coverage(tmp_path):
    registry, aliases = tmp_path / "teams.json", tmp_path / "aliases.json"
    _registry(registry); _aliases(aliases)

    class NoToken:
        token = None

    report = audit_draft_coverage(
        polymarket=_Market(), pandascore=NoToken(), registry_path=registry, aliases_path=aliases,
        resolver=lambda name, _aliases: name,
    )
    assert report["sources"]["pandascore"]["status"] == "BLOCKED_CREDENTIAL"
    assert report["sources"]["pandascore"]["events"] is None


def test_publish_is_atomic_and_machine_readable(tmp_path):
    registry, aliases, output = tmp_path / "teams.json", tmp_path / "aliases.json", tmp_path / "report.json"
    _registry(registry); _aliases(aliases)
    expected = publish_audit(
        output, polymarket=_Market(), pandascore=_Panda(), registry_path=registry, aliases_path=aliases,
        resolver=lambda name, _aliases: name,
    )
    assert json.loads(output.read_text(encoding="utf-8")) == expected
