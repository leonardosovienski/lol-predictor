from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from predictor_core.contracts.scientific import DataAcquisitionCharter

from src.data.ingestion import SnapshotStore
from src.freeze import FreezeError, load_current_freeze
from src.operations import backtest, health, publish_freeze, publish_snapshot
from src.services import PredictionRequest, PredictionService
from src.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


def _csv() -> bytes:
    return (
        "gameid,league,teamname,date,result,position,side,teamkills,split,game,datacompleteness\n"
        "g1,LCK,T1,2026-08-07T00:00:00Z,1,team,Blue,10,Summer,1,complete\n"
        "g1,LCK,Gen.G,2026-08-07T00:00:00Z,0,team,Red,8,Summer,1,complete\n"
        "g2,LCK,T1,2026-08-08T00:00:00Z,0,team,Blue,8,Summer,2,complete\n"
        "g2,LCK,Gen.G,2026-08-08T00:00:00Z,1,team,Red,10,Summer,2,complete\n"
    ).encode()


def _prepared(tmp_path: Path, monkeypatch) -> Settings:
    data_root = tmp_path / "data"
    data_root.mkdir()
    for name in (
        "trials.json",
        "data_acquisition_charter.json",
        "teams_lol.json",
        "polymarket_aliases.json",
        "canonical_teams.json",
    ):
        shutil.copy2(ROOT / "data" / name, data_root / name)
    source = tmp_path / "source.csv"
    source.write_bytes(_csv())
    SnapshotStore(data_root / "ingestion").publish(source, source="fixture")
    settings = Settings(
        data_root=data_root,
        project_root=ROOT,
        config_path=ROOT / "config.yaml",
        min_free_disk_mb=1,
        max_snapshot_staleness_hours=192,
    )

    def fake_main(_arguments):
        (data_root / "ratings.json").write_text('{"Gen.G": 1510, "T1": 1490}\n', encoding="utf-8")
        (data_root / "calibration.json").write_text("{}\n", encoding="utf-8")
        (data_root / "walkforward_summary.json").write_text('{"n_medidos": 1}\n', encoding="utf-8")
        return 0

    monkeypatch.setattr("scripts.backtest_walkforward.main", fake_main)
    publish_snapshot(settings)
    backtest(settings)
    return settings


def test_versioned_acquisition_charter_satisfies_core_contract() -> None:
    charter = DataAcquisitionCharter.from_dict(
        json.loads((ROOT / "data" / "data_acquisition_charter.json").read_text(encoding="utf-8"))
    )
    assert charter.charter_id == "lol-oracles-elixir-v1"


def test_publish_freeze_is_sealed_idempotent_and_served(tmp_path, monkeypatch):
    settings = _prepared(tmp_path, monkeypatch)
    first = publish_freeze(settings)
    second = publish_freeze(settings)
    assert first["status"] == "PUBLISHED" and second["status"] == "SKIPPED"
    manifest, artifacts = load_current_freeze(settings.data_root, ROOT)
    assert len(manifest["freeze_id"]) == 64
    assert manifest["dataset_freeze"]["manifest_hash"]
    assert artifacts["ratings"].name == "ratings.json"
    prediction = PredictionService(settings.data_root / "ingestion", project_root=ROOT).predict(
        PredictionRequest("T1", "Gen.G", "bo3")
    )
    assert prediction["freeze_id"] == manifest["freeze_id"]
    assert prediction["canonical_team_a_id"].startswith("lol-team-")
    assert prediction["canonical_team_b_id"].startswith("lol-team-")
    assert prediction["input_provenance"]["ratings_hash"] == manifest["artifacts"]["ratings"]["sha256"]
    with pytest.raises(ValueError, match="unknown team identity"):
        PredictionService(settings.data_root / "ingestion", project_root=ROOT).predict(
            PredictionRequest("T", "Gen.G", "bo3")
        )
    assert health(settings)["status"] == "HEALTHY"


def test_serving_fails_closed_when_frozen_rating_is_tampered(tmp_path, monkeypatch):
    settings = _prepared(tmp_path, monkeypatch)
    publish_freeze(settings)
    # Mutable pipeline outputs are no longer serving inputs after publication.
    (settings.data_root / "ratings.json").write_text('{"T1": 9999}\n', encoding="utf-8")
    PredictionService(settings.data_root / "ingestion", project_root=ROOT).predict(PredictionRequest("T1", "Gen.G"))
    pointer = json.loads((settings.data_root / "current_freeze.json").read_text(encoding="utf-8"))
    manifest = json.loads((settings.data_root / pointer["path"]).read_text(encoding="utf-8"))
    frozen_ratings = settings.data_root / manifest["artifacts"]["ratings"]["path"]
    frozen_ratings.write_text('{"T1": 9999}\n', encoding="utf-8")
    with pytest.raises(FreezeError, match="artifact hash mismatch"):
        PredictionService(settings.data_root / "ingestion", project_root=ROOT).predict(PredictionRequest("T1", "Gen.G"))
