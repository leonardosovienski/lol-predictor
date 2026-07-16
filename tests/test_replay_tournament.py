import importlib.util
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("replay_tournament", ROOT / "scripts" / "replay_tournament.py")
replay_tournament = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay_tournament)


def _db():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE games (game_id TEXT, date TEXT, league TEXT, team_a TEXT, team_b TEXT, winner TEXT)")
    conn.executemany("INSERT INTO games VALUES (?, ?, ?, ?, ?, ?)", [
        ("before", "2025-01-01 00:00:00", "LCK", "T1", "Gen.G", "a"),
        ("event1", "2025-02-01 00:00:00", "TEST", "T1", "Gen.G", "a"),
        ("event2", "2025-02-01 01:00:00", "TEST", "Gen.G", "T1", "a"),
    ])
    return conn


def test_replay_is_frozen_during_tournament():
    report = replay_tournament.replay(_db(), {
        "league": "TEST", "start": "2025-02-01 00:00:00", "end": "2025-02-02 00:00:00",
    })
    first, second = report["forecasts"]
    assert report["maps"] == 2
    assert first["elo_a"] == second["elo_b"]
    assert first["elo_b"] == second["elo_a"]
    assert first["history_maps_a"] == 1
    assert second["history_maps_a"] == 1
    assert report["confidence_calibration"]
