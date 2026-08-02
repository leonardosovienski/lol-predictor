from datetime import UTC, datetime
from pathlib import Path
import pytest
from src.data.ingestion import IngestionError, SnapshotStore, assert_fresh_snapshot
from src.services import SettlementService
from src.settings import validate_env_example

def _csv(path: Path) -> None:
    path.write_text("gameid,league,teamname,date,result\ng1,LCK,A,2026-07-31,1\ng1,LCK,B,2026-07-31,0\n", encoding="utf-8")

def test_snapshot_canonical_contract(tmp_path):
    payload = tmp_path / "input.csv"
    _csv(payload)
    store = SnapshotStore(tmp_path / "store")
    metadata = store.publish(payload, source="fixture")
    assert metadata["hash"] == metadata["sha256"]
    checked = assert_fresh_snapshot(store.root, max_age_hours=192, now=datetime.now(UTC))
    assert checked["staleness_hours"] >= 0

def test_snapshot_regressive_temporal_contract_fails_closed(tmp_path):
    payload = tmp_path / "input.csv"
    _csv(payload)
    store = SnapshotStore(tmp_path / "store")
    store.publish(payload, source="fixture")
    metadata_path = next(store.snapshots.glob("*/metadata.json"))
    text = metadata_path.read_text(encoding="utf-8").replace("2026-07-31T23:59:59Z", "2099-01-01T00:00:00Z")
    metadata_path.write_text(text, encoding="utf-8")
    with pytest.raises(IngestionError): assert_fresh_snapshot(store.root, max_age_hours=192)

def test_scientific_settlement_is_fail_closed():
    with pytest.raises(ValueError): SettlementService().settle({"state": "SHADOW"}, 1)

def test_env_example_matches_schema():
    validate_env_example(Path(__file__).resolve().parents[1] / ".env.example")
