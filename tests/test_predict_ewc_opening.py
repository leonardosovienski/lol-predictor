from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module():
    spec = importlib.util.spec_from_file_location("ewc_predict_test", ROOT / "scripts" / "predict_ewc_opening.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture(matches=None):
    return {"event": "test", "stage": "opening", "scheduled_date": "2026-07-15", "format": "bo1", "snapshot_at": "2026-07-15T00:00:00+00:00", "aliases": {"AL": {"canonical": "Anyone's Legend", "source": "fixture", "confidence": "VERIFIED_ALIAS"}}, "matches": matches or [["T1", "Gen.G"], ["AL", "G2 Esports"]]}


def test_exact_and_verified_alias_are_explicit() -> None:
    mod = load_module()
    report = mod.build(fixture())
    states = {row["display"]: row["status"] for row in report["resolutions"]}
    assert states["T1"] == "EXACT" and states["AL"] == "VERIFIED_ALIAS"


def test_missing_team_blocks_only_affected_match() -> None:
    mod = load_module()
    report = mod.build(fixture([["T1", "Unknown Team"], ["Gen.G", "G2 Esports"]]))
    assert [row["status"] for row in report["predictions"]] == ["BLOCKED", "PREDICTED"]


def test_bo1_probabilities_sum_to_one_and_order_reverses() -> None:
    mod = load_module()
    left = mod.build(fixture([["T1", "Gen.G"]]))["predictions"][0]
    right = mod.build(fixture([["Gen.G", "T1"]]))["predictions"][0]
    assert left["format"] == "bo1"
    assert round(left["probability_a"] + left["probability_b"], 6) == 1
    assert left["probability_a"] == right["probability_b"]


def test_stale_rating_evidence_is_flagged() -> None:
    mod = load_module()
    report = mod.build(fixture([["Team Secret", "T1"]]))
    row = next(item for item in report["resolutions"] if item["display"] == "Team Secret")
    assert row["freshness"] == "STALE" and row["rating_quality"] == "INSUFFICIENT_HISTORY"


def test_json_is_deterministic_and_has_no_data_write(tmp_path: Path) -> None:
    mod = load_module()
    ratings = ROOT / "data" / "ratings.json"
    db = ROOT / "data" / "lol.db"
    before = ratings.read_bytes(), db.read_bytes()
    first = json.dumps(mod.build(fixture(), ratings, db), sort_keys=True)
    second = json.dumps(mod.build(fixture(), ratings, db), sort_keys=True)
    assert first == second and before == (ratings.read_bytes(), db.read_bytes())


def test_strict_returns_nonzero_when_fixture_is_unresolvable(tmp_path: Path, monkeypatch) -> None:
    mod = load_module()
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(fixture([["Unknown Team", "T1"]])), encoding="utf-8")
    assert mod.main(["--fixture", str(path), "--strict"]) == 2


def test_output_is_explicit_and_does_not_touch_data(tmp_path: Path) -> None:
    mod = load_module()
    output = tmp_path / "report.json"
    assert mod.main(["--json", "--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["format"] == "bo1"


def test_scheduled_fixture_has_maturation_and_acceptable_warning() -> None:
    mod = load_module()
    scheduled = fixture([["Gen.G", "JD Gaming"]])
    scheduled["matches"] = [{"teams": ["Gen.G", "JD Gaming"],
                              "scheduled_at": "2026-07-17T08:00:00-03:00"}]
    row = mod.build(scheduled)["predictions"][0]
    assert row["matures_at"] == "2026-07-17T09:00:00-03:00"
    assert any("acceptable but aging" in item for item in row["limitations"])


def test_pre_event_registration_is_idempotent(tmp_path: Path) -> None:
    mod = load_module()
    scheduled = fixture([["T1", "Gen.G"]])
    scheduled["matches"] = [{"teams": ["T1", "Gen.G"],
                              "scheduled_at": "2026-07-17T08:00:00-03:00"}]
    report = mod.build(scheduled)
    ledger = tmp_path / "predictions.jsonl"
    now = datetime(2026, 7, 16, 20, 0, tzinfo=timezone.utc)
    assert mod.register_pre_event(report, ledger, now) == {"registered": 1, "already_present": 0}
    assert mod.register_pre_event(report, ledger, now) == {"registered": 0, "already_present": 1}
    record = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    assert record["lifecycle_status"] == "PRE_EVENT" and record["result"] is None


def test_maturation_waits_then_records_result_brier_and_correct(tmp_path: Path) -> None:
    mod = load_module()
    scheduled = fixture([["T1", "Gen.G"]])
    scheduled["matches"] = [{"teams": ["T1", "Gen.G"],
                              "scheduled_at": "2026-07-17T08:00:00-03:00"}]
    ledger = tmp_path / "predictions.jsonl"
    mod.register_pre_event(mod.build(scheduled), ledger,
                           datetime(2026, 7, 16, 20, 0, tzinfo=timezone.utc))
    results = {"results": [{"team_a": "T1", "team_b": "Gen.G",
                             "winner": "Gen.G", "score": "0-1"}]}
    before = datetime(2026, 7, 17, 11, 30, tzinfo=timezone.utc)
    assert mod.mature_results(ledger, results, before)["not_ready"] == 1
    after = datetime(2026, 7, 17, 12, 1, tzinfo=timezone.utc)
    assert mod.mature_results(ledger, results, after) == {
        "registered": 1, "already_present": 0, "not_ready": 0}
    assert mod.mature_results(ledger, results, after) == {
        "registered": 0, "already_present": 1, "not_ready": 0}
    matured = json.loads(ledger.read_text(encoding="utf-8").splitlines()[-1])
    assert matured["lifecycle_status"] == "MATURED"
    assert matured["result"] == {"winner": "Gen.G", "score": "0-1"}
    assert matured["correct"] is False
    assert matured["brier"] == round(2 * matured["value"]["probability_a"] ** 2, 8)
