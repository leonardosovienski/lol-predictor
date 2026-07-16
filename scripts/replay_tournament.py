"""Replay temporal read-only de um torneio Tier 1 de LoL.

O runner reconstrói o Elo apenas com mapas anteriores ao início da janela e
mantém esses ratings congelados durante o torneio. Assim, cada mapa é uma
previsão que seria possível antes do evento, sem vazar resultados nem reagir
ao ruído de um bracket curto. Ele não grava ratings, calibration ou ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from src.config import load_teams  # noqa: E402
from src.model import win_probability  # noqa: E402
from predictor_core.measurement.metrics import brier, log_loss  # noqa: E402

K = 32.0
DEFAULT_SEED = 1400.0

TOURNAMENTS = {
    "msi-2026": {
        "league": "MSI", "start": "2026-06-28 00:00:00",
        "end": "2026-07-11 00:00:00",
    },
    "worlds-2025": {
        "league": "WLDs", "start": "2025-09-25 00:00:00",
        "end": "2025-11-10 00:00:00",
    },
}


def _seed_ratings() -> dict[str, float]:
    return {team["name"]: float(team["initial_elo"]) for team in load_teams()}


def _rows(conn: sqlite3.Connection, where: str, params: tuple) -> list[tuple]:
    return conn.execute(
        "SELECT game_id, date, league, team_a, team_b, winner "
        f"FROM games WHERE {where} ORDER BY date, game_id", params).fetchall()


def _reconstruct_before(conn: sqlite3.Connection, start: str) -> tuple[dict[str, float], dict[str, int]]:
    ratings = _seed_ratings()
    games = defaultdict(int)
    for _gid, _date, _league, team_a, team_b, winner in _rows(conn, "date < ?", (start,)):
        elo_a = ratings.get(team_a, DEFAULT_SEED)
        elo_b = ratings.get(team_b, DEFAULT_SEED)
        p_a = win_probability(elo_a, elo_b)
        score_a = 1.0 if winner == "a" else 0.0
        delta = K * (score_a - p_a)
        ratings[team_a] = elo_a + delta
        ratings[team_b] = elo_b - delta
        games[team_a] += 1
        games[team_b] += 1
    return ratings, games


def replay(conn: sqlite3.Connection, spec: dict[str, str]) -> dict:
    """Executa um replay congelado e retorna métricas e previsões por mapa."""
    start, end, league = spec["start"], spec["end"], spec["league"]
    ratings, history = _reconstruct_before(conn, start)
    maps = _rows(conn, "league = ? AND date >= ? AND date < ?", (league, start, end))
    if not maps:
        raise ValueError("nenhum mapa na janela solicitada")

    probs, outcomes, forecasts = [], [], []
    for gid, date, _league, team_a, team_b, winner in maps:
        elo_a = ratings.get(team_a, DEFAULT_SEED)
        elo_b = ratings.get(team_b, DEFAULT_SEED)
        p_a = win_probability(elo_a, elo_b)
        outcome = 0 if winner == "a" else 1
        favorite = team_a if p_a >= .5 else team_b
        actual = team_a if winner == "a" else team_b
        probs.append([p_a, 1.0 - p_a])
        outcomes.append(outcome)
        forecasts.append({
            "game_id": gid, "at_utc": date, "team_a": team_a, "team_b": team_b,
            "elo_a": round(elo_a, 1), "elo_b": round(elo_b, 1),
            "history_maps_a": history[team_a], "history_maps_b": history[team_b],
            "probability_a": round(p_a, 4), "probability_b": round(1.0 - p_a, 4),
            "favorite": favorite, "actual_winner": actual, "correct": favorite == actual,
        })

    accuracy = mean(row["correct"] for row in forecasts)
    return {
        "method": "frozen-pre-event Elo H1 per map; no intra-tournament update; Platt disabled",
        "league": league, "start_utc": start, "end_exclusive_utc": end,
        "pre_event_maps_used": sum(history.values()) // 2,
        "maps": len(forecasts),
        "accuracy": round(accuracy, 4),
        "brier_multiclass": round(brier(probs, outcomes), 4),
        "log_loss": round(log_loss(probs, outcomes), 4),
        "mean_probability_of_actual_winner": round(mean(
            row["probability_a"] if row["actual_winner"] == row["team_a"] else row["probability_b"]
            for row in forecasts), 4),
        "database_sha256": hashlib.sha256((ROOT / "data" / "lol.db").read_bytes()).hexdigest(),
        "limitations": [
            "Map-level replay: the database has no reliable series identifier for every event.",
            "Ratings are frozen at the tournament start; no intra-bracket reaction is simulated.",
            "No patch, draft, side, roster, odds, kills, or manual regional adjustment.",
        ],
        "forecasts": forecasts,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Tier-1 tournament Elo replay")
    parser.add_argument("tournaments", nargs="+", choices=sorted(TOURNAMENTS))
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    args = parser.parse_args(argv)
    conn = sqlite3.connect(f"file:{ROOT / 'data' / 'lol.db'}?mode=ro", uri=True)
    try:
        reports = {name: replay(conn, TOURNAMENTS[name]) for name in args.tournaments}
    finally:
        conn.close()
    for name, report in reports.items():
        print(f"{name}: {report['maps']} mapas | acerto {report['accuracy']:.1%} | "
              f"Brier {report['brier_multiclass']:.4f} | log-loss {report['log_loss']:.4f}")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(reports, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
