from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "backtest_walkforward_test", ROOT / "scripts" / "backtest_walkforward.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_normalizes_seed_casing_and_tracks_competition() -> None:
    module = _module()
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE games (game_id TEXT, date TEXT, league TEXT, "
        "team_a TEXT, team_b TEXT, winner TEXT, kills_a INTEGER, kills_b INTEGER)")
    conn.execute(
        "INSERT INTO games VALUES ('g1','2026-01-01 00:00:00','LCK',"
        "'BNK FEARX','T1','a',10,8)")
    cfg = {
        "k_factor_base": 32,
        "backtest": {"default_seed_elo": 1400, "min_team_games": 0,
                     "kills_lines": [24.5], "min_league_games_kills": 30,
                     "burnin_days": 0},
    }
    try:
        result = module.run(cfg, conn)
    finally:
        conn.close()
    assert result["measured_leagues"] == ["LCK"]
    assert "BNK FearX" in result["elo"]
    assert "BNK FEARX" not in result["elo"]
