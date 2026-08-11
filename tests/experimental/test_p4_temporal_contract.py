from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from scripts import predict_ewc_opening as ewc
from tests.experimental.p4_temporal_adapter import (
    ExperimentalTemporalError,
    adapt_ewc_records,
    replay_record,
    write_immutable_golden,
)

HERE = Path(__file__).parent
CASE = json.loads((HERE / "fixtures" / "lol_temporal_case.json").read_text(encoding="utf-8"))


def _dt(name: str) -> datetime:
    return datetime.fromisoformat(CASE[name].replace("Z", "+00:00"))


def _fixture() -> dict:
    return {
        "event": CASE["event"],
        "stage": CASE["stage"],
        "scheduled_date": "2026-09-01",
        "format": CASE["format"],
        "snapshot_at": CASE["predicted_at"],
        "source_ratings_mtime_utc": "2026-09-01T08:00:00Z",
        "aliases": {
            "Synthetic Alpha": {
                "canonical": "Synthetic Alpha",
                "source": "p4 synthetic fixture",
                "confidence": "VERIFIED_ALIAS",
            },
            "Synthetic Beta": {
                "canonical": "Synthetic Beta",
                "source": "p4 synthetic fixture",
                "confidence": "VERIFIED_ALIAS",
            },
        },
        "matches": [
            {
                "teams": ["Synthetic Alpha", "Synthetic Beta"],
                "scheduled_at": CASE["scheduled_at"],
            }
        ],
    }


def _canonical_pair(tmp_path: Path) -> tuple[dict, dict]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    ratings = tmp_path / "ratings.json"
    ratings.write_bytes(b'{"Synthetic Alpha":1600.0,"Synthetic Beta":1400.0}\n')
    ledger = tmp_path / "ledger.jsonl"
    report = ewc.build(_fixture(), ratings_path=ratings, db_path=tmp_path / "absent.db")
    assert ewc.register_pre_event(report, ledger, now=_dt("predicted_at")) == {
        "registered": 1,
        "already_present": 0,
    }
    pre = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    results = {
        "results": [
            {
                "prediction_id": pre["prediction_id"],
                "team_a": "Synthetic Alpha",
                "team_b": "Synthetic Beta",
                "winner": "Synthetic Alpha",
                "score": "2-1",
                "result_available_at": CASE["result_available_at"],
            }
        ]
    }
    assert ewc.mature_results(ledger, results, now=_dt("matured_at")) == {
        "registered": 1,
        "already_present": 0,
        "not_ready": 0,
    }
    records = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    return records[0], records[1]


def _adapt(pre: dict, matured: dict, **changes):
    values = {"result_available_at": _dt("result_available_at")}
    values.update(changes)
    return adapt_ewc_records(pre, matured, **values)


def test_valid_ewc_flow_matches_checked_in_golden(tmp_path: Path) -> None:
    pre, matured = _canonical_pair(tmp_path)
    record = _adapt(pre, matured)
    golden = json.loads((HERE / "golden" / "lol_temporal_expected.json").read_text(encoding="utf-8"))
    assert record.to_dict() == golden["record"]
    assert pre["value"] == golden["prediction"]
    assert matured["result"] == golden["observed"]
    assert matured["brier"] == pytest.approx(golden["record"]["metric_value"], abs=1e-12, rel=1e-12)
    assert golden["metric_rule"] == "round(2.0 * (probability_a - outcome_a) ** 2, 8)"
    replayed = replay_record(
        record, input_hash=golden["input_hash"], expected_input_hash=record.prediction_payload_hash
    )
    assert replayed == {"input_hash": golden["input_hash"], "record": golden["record"]}


def test_repeated_synthetic_flow_has_identical_hashes(tmp_path: Path) -> None:
    first_pre, first_matured = _canonical_pair(tmp_path / "first")
    second_pre, second_matured = _canonical_pair(tmp_path / "second")
    assert _adapt(first_pre, first_matured).to_dict() == _adapt(second_pre, second_matured).to_dict()


@pytest.mark.parametrize(
    ("available", "message"),
    [
        (None, "timezone-aware"),
        (datetime(2026, 9, 1, 12, 20), "timezone-aware"),
        (_dt("scheduled_at") - timedelta(seconds=1), "at or after event_start_at"),
    ],
)
def test_invalid_result_availability_fails(tmp_path: Path, available, message: str) -> None:
    pre, matured = _canonical_pair(tmp_path)
    with pytest.raises(ExperimentalTemporalError, match=message):
        _adapt(pre, matured, result_available_at=available)


def test_late_and_naive_pre_event_registration_fail(tmp_path: Path) -> None:
    ratings = tmp_path / "ratings.json"
    ratings.write_bytes(b'{"Synthetic Alpha":1600.0,"Synthetic Beta":1400.0}\n')
    report = ewc.build(_fixture(), ratings_path=ratings, db_path=tmp_path / "absent.db")
    with pytest.raises(ValueError, match="PRE_EVENT blocked"):
        ewc.register_pre_event(report, tmp_path / "late.jsonl", now=_dt("scheduled_at"))
    with pytest.raises(ValueError, match="timezone-aware"):
        ewc.register_pre_event(report, tmp_path / "naive.jsonl", now=datetime(2026, 9, 1, 9))


def test_premature_and_inconsistent_maturity_fail(tmp_path: Path) -> None:
    pre, matured = _canonical_pair(tmp_path)
    early = copy.deepcopy(matured)
    early["matured_at"] = "2026-09-01T12:10:00Z"
    with pytest.raises(ExperimentalTemporalError, match="result_available_at"):
        _adapt(pre, early)
    before_horizon = copy.deepcopy(matured)
    before_horizon["matured_at"] = "2026-09-01T12:20:00Z"
    with pytest.raises(ExperimentalTemporalError, match="premature"):
        _adapt(pre, before_horizon)


def test_identity_retroactive_mutation_and_post_event_leak_fail(tmp_path: Path) -> None:
    pre, matured = _canonical_pair(tmp_path)
    wrong_id = copy.deepcopy(matured)
    wrong_id["prediction_id"] = "0" * 64
    with pytest.raises(ExperimentalTemporalError, match="identity"):
        _adapt(pre, wrong_id)
    changed = copy.deepcopy(matured)
    changed["value"]["probability_a"] = 0.5
    with pytest.raises(ExperimentalTemporalError, match="retroactive"):
        _adapt(pre, changed)
    leaked = copy.deepcopy(pre)
    leaked["result"] = {"winner": leaked["team_a"], "score": "2-0"}
    with pytest.raises(ExperimentalTemporalError, match="post-event"):
        _adapt(leaked, matured)


def test_result_hash_replay_input_and_golden_overwrite_fail(tmp_path: Path) -> None:
    pre, matured = _canonical_pair(tmp_path)
    record = _adapt(pre, matured)
    altered = copy.deepcopy(matured)
    altered["result"]["score"] = "2-0"
    with pytest.raises(ExperimentalTemporalError, match="result payload hash"):
        adapt_ewc_records(
            pre,
            altered,
            result_available_at=_dt("result_available_at"),
            expected_result_payload_hash=record.result_payload_hash,
        )
    with pytest.raises(ExperimentalTemporalError, match="replay input hash"):
        replay_record(record, input_hash="f" * 64, expected_input_hash=record.prediction_payload_hash)
    path = tmp_path / "golden.json"
    write_immutable_golden(path, record.to_dict())
    write_immutable_golden(path, record.to_dict())
    with pytest.raises(ExperimentalTemporalError, match="overwrite"):
        write_immutable_golden(path, {**record.to_dict(), "prediction_id": "changed"})


def test_nonfinite_metric_fails(tmp_path: Path) -> None:
    pre, matured = _canonical_pair(tmp_path)
    matured["brier"] = float("inf")
    with pytest.raises(ExperimentalTemporalError, match="finite"):
        _adapt(pre, matured)
