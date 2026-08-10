from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from src.data.ingestion import SnapshotStore
from src.operations import ContractError, backtest, health, publish_snapshot, settle
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


def _settings(tmp_path: Path) -> Settings:
    data_root = tmp_path / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "data" / "canonical_teams.json", data_root / "canonical_teams.json")
    return Settings(
        data_root=data_root,
        project_root=ROOT,
        config_path=ROOT / "config.yaml",
        min_free_disk_mb=1,
        max_snapshot_staleness_hours=24,
    )


def _snapshot(settings: Settings) -> None:
    source = settings.data_root.parent / "source.csv"
    source.write_bytes(_csv())
    SnapshotStore(settings.data_root / "ingestion").publish(source, source="fixture")


def test_publish_snapshot_is_idempotent(tmp_path):
    settings = _settings(tmp_path)
    _snapshot(settings)
    first = publish_snapshot(settings)
    second = publish_snapshot(settings)
    assert first["status"] == "PUBLISHED"
    assert second["status"] == "SKIPPED"
    assert first["snapshot_hash"] == second["snapshot_hash"]


def test_health_reports_missing_freeze_after_snapshot_and_ratings_pass(tmp_path):
    settings = _settings(tmp_path)
    _snapshot(settings)
    settings.data_root.mkdir(parents=True, exist_ok=True)
    (settings.data_root / "ratings.json").write_text('{"T1": 1500}\n', encoding="utf-8")
    report = health(settings)
    assert report["status"] == "DEGRADED"
    assert {row["name"]: row["result"] for row in report["checks"]} == {
        "snapshot": "PASS",
        "ratings": "PASS",
        "freeze": "FAIL",
        "collection_archive": "PASS",
        "disk": "PASS",
        "locks": "PASS",
    }
    assert report["artifacts"]["snapshot"]["hash"] == hashlib.sha256(_csv()).hexdigest()


def test_health_degrades_instead_of_throwing_when_artifacts_missing(tmp_path):
    report = health(_settings(tmp_path))
    assert report["status"] == "DEGRADED"
    assert sum(row["result"] == "FAIL" for row in report["checks"]) >= 2


def test_settlement_always_publishes_a_summary_and_is_idempotent(tmp_path):
    settings = _settings(tmp_path)
    signals = settings.data_root / "shadow" / "h4_signals.jsonl"
    signals.parent.mkdir(parents=True)
    signals.write_text(
        json.dumps(
            {
                "canonical_event_id": "pandascore:1",
                "event_start_at": "2026-08-09T10:00:00+00:00",
                "settlement_status": "PENDING",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    results = tmp_path / "results.json"
    results.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "canonical_event_id": "pandascore:1",
                        "result": 1,
                        "source": "oracle-elixir",
                        "result_available_at": "2026-08-09T12:00:00+00:00",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    first = settle(settings, results, signals)
    second = settle(settings, results, signals)
    assert first["settled"] == 1 and second["settled"] == 0
    assert (settings.data_root / "settlement" / "latest.json").is_file()
    settled = json.loads(signals.read_text(encoding="utf-8"))
    assert settled["settled_at"].endswith("+00:00")


def test_backtest_uses_current_snapshot_hash_and_skips_second_run(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    _snapshot(settings)
    publish_snapshot(settings)
    seen = []

    def fake_main(arguments):
        seen.append(arguments)
        for name in ("ratings.json", "calibration.json", "walkforward_summary.json"):
            (settings.data_root / name).write_text("{}\n", encoding="utf-8")
        return 0

    monkeypatch.setattr("scripts.backtest_walkforward.main", fake_main)
    first = backtest(settings)
    second = backtest(settings)
    assert first["status"] == "SUCCEEDED" and second["status"] == "SKIPPED"
    assert len(seen) == 1
    assert Path(seen[0][1]).name == "payload.csv"


def test_backtest_requires_matching_canonical_archive(tmp_path):
    settings = _settings(tmp_path)
    _snapshot(settings)
    with pytest.raises(ContractError, match="canonical collection archive"):
        backtest(settings)


def test_unknown_identity_is_quarantined_once_and_blocks_backtest(tmp_path):
    settings = _settings(tmp_path)
    source = settings.data_root.parent / "unknown.csv"
    source.write_text(
        "gameid,league,teamname,date,result,position,side,teamkills,split,game,datacompleteness\n"
        "g1,LCK,Unknown Future Team,2026-08-08T00:00:00Z,1,team,Blue,10,Summer,1,complete\n"
        "g1,LCK,T1,2026-08-08T00:00:00Z,0,team,Red,8,Summer,1,complete\n",
        encoding="utf-8",
    )
    SnapshotStore(settings.data_root / "ingestion").publish(source, source="fixture")
    first = publish_snapshot(settings)
    second = publish_snapshot(settings)
    assert first["collection_shadow"]["status"] == "ALERT"
    quarantine = Path(second["collection_shadow"]["quarantine"])
    assert len(quarantine.read_text(encoding="utf-8").splitlines()) == 1
    with pytest.raises(ContractError, match="quarantined"):
        backtest(settings)


def test_snapshot_database_contains_only_snapshot_games(tmp_path):
    from scripts.backtest_walkforward import _snapshot_database

    snapshot_dir = tmp_path / "snapshot"
    snapshot_dir.mkdir()
    payload = snapshot_dir / "payload.csv"
    payload.write_bytes(_csv())
    conn, database = _snapshot_database(payload)
    try:
        assert conn.execute("SELECT game_id, team_a, team_b FROM games ORDER BY game_id").fetchall() == [
            ("g1", "T1", "Gen.G"),
            ("g2", "T1", "Gen.G"),
        ]
    finally:
        conn.close()
        database.unlink(missing_ok=True)
