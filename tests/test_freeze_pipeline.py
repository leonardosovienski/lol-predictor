from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.data.ingestion import SnapshotStore
from src.operations import backtest, publish_freeze
from src.services import PredictionRequest, PredictionService
from src.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


def _historical_csv() -> str:
    header = "gameid,league,teamname,date,result,position,side,teamkills,split,game,datacompleteness\n"
    rows = []
    start = datetime(2026, 4, 20, tzinfo=UTC)
    for index in range(110):
        day = (start + timedelta(days=index)).isoformat().replace("+00:00", "Z")
        winner_a = index % 3 != 0
        winner_kills = 11 + (index % 3)
        loser_kills = 7
        rows.extend(
            [
                f"g{index},LCK,T1,{day},{int(winner_a)},team,Blue,{winner_kills if winner_a else loser_kills},Summer,{index},complete\n",
                f"g{index},LCK,Gen.G,{day},{int(not winner_a)},team,Red,{loser_kills if winner_a else winner_kills},Summer,{index},complete\n",
            ]
        )
    return header + "".join(rows)


def test_snapshot_backtest_freeze_and_serving_without_mocks(tmp_path: Path) -> None:
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
    source = tmp_path / "history.csv"
    source.write_text(_historical_csv(), encoding="utf-8")
    SnapshotStore(data_root / "ingestion").publish(source, source="integration-fixture")
    settings = Settings(
        data_root=data_root,
        project_root=ROOT,
        config_path=ROOT / "config.yaml",
        min_free_disk_mb=1,
        max_snapshot_staleness_hours=192,
    )

    backtest_result = backtest(settings)
    freeze_result = publish_freeze(settings)
    prediction = PredictionService(data_root / "ingestion", project_root=ROOT).predict(
        PredictionRequest("T1", "Gen.G", "bo3")
    )

    assert backtest_result["status"] == "SUCCEEDED"
    assert freeze_result["status"] == "PUBLISHED"
    assert prediction["freeze_id"] == freeze_result["freeze_id"]
    assert (data_root / "current_freeze.json").is_file()
