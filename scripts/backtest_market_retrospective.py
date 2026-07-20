"""H4-R: backtest exploratório de moneylines históricas do Polymarket."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sqlite3
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from src.config import load_teams  # noqa: E402
from src.data.polymarket_provider import (  # noqa: E402
    DataUnavailableError, PolymarketProvider, _array)
from src.model import series_probs, win_probability  # noqa: E402


def _key(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip().casefold()


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * q
    low, high = math.floor(index), math.ceil(index)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - index) + ordered[high] * (index - low)


def _bootstrap(rows: list[dict], field: str, iterations: int = 2000) -> list[float]:
    rng = random.Random(13)
    n = len(rows)
    stats = []
    for _ in range(iterations):
        sample = [rows[rng.randrange(n)][field] for _ in range(n)]
        stats.append(sum(sample) / n)
    return [_quantile(stats, .025), _quantile(stats, .975)]


def _games(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute(
        "SELECT date, game_id, team_a, team_b, winner FROM games "
        "ORDER BY date, game_id").fetchall()


def _model_probability(games: list[tuple], scheduled_db: str,
                       team_a: str, team_b: str, fmt: str) -> float:
    ratings = {row["name"]: float(row["initial_elo"]) for row in load_teams()}
    folded = {_key(name): name for name in ratings}
    for date, _gid, a, b, winner in games:
        if date >= scheduled_db:
            break
        elo_a, elo_b = ratings.get(a, 1400.0), ratings.get(b, 1400.0)
        delta = 32 * ((1.0 if winner == "a" else 0.0) - win_probability(elo_a, elo_b))
        ratings[a], ratings[b] = elo_a + delta, elo_b - delta
        folded.setdefault(_key(a), a)
        folded.setdefault(_key(b), b)
    a = folded.get(_key(team_a))
    b = folded.get(_key(team_b))
    if not a or not b or a == b:
        raise ValueError("identidade sem histórico inequívoco no banco")
    p_map = win_probability(ratings[a], ratings[b])
    dist = series_probs(p_map, fmt)
    return sum(p for score, p in dist.items()
               if int(score.split("-")[0]) > int(score.split("-")[1]))


def run(provider: PolymarketProvider, db_path: Path) -> dict:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        games = _games(conn)
    finally:
        conn.close()
    aliases = json.loads((ROOT / "data" / "polymarket_aliases.json").read_text(
        encoding="utf-8"))["aliases"]
    rows, exclusions = [], {}
    for event in provider.list_closed_match_events():
        market = event["moneyline"]
        try:
            outcomes = _array(market.get("outcomes"), "outcomes")
            tokens = _array(market.get("clobTokenIds"), "clobTokenIds")
            final = [float(x) for x in _array(market.get("outcomePrices"),
                                               "outcomePrices")]
            if len(outcomes) != 2 or len(tokens) != 2 or final.count(1.0) != 1:
                raise ValueError("moneyline não resolvida binariamente")
            scheduled = datetime.fromisoformat(
                event["startTime"].replace("Z", "+00:00")).astimezone(timezone.utc)
            cutoff = scheduled - timedelta(minutes=15)
            price_at, p_market = provider.price_before(tokens[0], cutoff)
            source_a, source_b = outcomes
            team_a, team_b = aliases.get(source_a, source_a), aliases.get(source_b, source_b)
            question = market.get("question") or ""
            competition = question.rsplit(" - ", 1)[-1] if " - " in question else "UNKNOWN"
            fmt = next((f"bo{x}" for x in (1, 3, 5)
                        if f"(BO{x})" in question.upper()), None)
            if not fmt:
                raise ValueError("formato ausente")
            scheduled_db = scheduled.strftime("%Y-%m-%d %H:%M:%S")
            p_model = _model_probability(games, scheduled_db, team_a, team_b, fmt)
            outcome_a = 1.0 if final[0] == 1.0 else 0.0
            brier_model = 2 * (p_model - outcome_a) ** 2
            brier_market = 2 * (p_market - outcome_a) ** 2
            edge = p_model - p_market
            roi = None
            if abs(edge) >= .05:
                choose_a = edge > 0
                chosen_p = p_market if choose_a else 1 - p_market
                won = (outcome_a == 1.0) == choose_a
                roi = (1 / chosen_p - 1) if won else -1.0
            rows.append({"event_id": str(event.get("id")), "market_id": str(market.get("id")),
                         "scheduled_at": scheduled.isoformat(), "price_at": price_at.isoformat(),
                         "team_a": team_a, "team_b": team_b, "format": fmt,
                         "competition": competition,
                         "p_model": p_model, "p_market": p_market, "outcome_a": outcome_a,
                         "brier_model": brier_model, "brier_market": brier_market,
                         "brier_diff": brier_model - brier_market, "edge": edge, "roi": roi})
        except (DataUnavailableError, KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
            reason = str(exc)
            exclusions[reason] = exclusions.get(reason, 0) + 1
    if not rows:
        raise RuntimeError("nenhum evento histórico elegível")
    signals = [row for row in rows if row["roi"] is not None]
    for row in signals:
        row["roi_value"] = row["roi"]
    mean = lambda field, data=rows: sum(row[field] for row in data) / len(data)
    competitions = sorted({row["competition"] for row in rows})
    report = {
        "classification": "H4-R exploratory retrospective; does not replace H4",
        "trial": "h4r-lol-polymarket-retrospectivo",
        "source": "Polymarket Gamma + CLOB prices-history (public read-only)",
        "database_sha256": hashlib.sha256(db_path.read_bytes()).hexdigest(),
        "events_discovered": len(rows) + sum(exclusions.values()),
        "eligible_matches": len(rows), "excluded": exclusions,
        "competitions": competitions, "competition_count": len(competitions),
        "period_start": min(row["scheduled_at"] for row in rows),
        "period_end": max(row["scheduled_at"] for row in rows),
        "brier_model": mean("brier_model"), "brier_market": mean("brier_market"),
        "paired_brier_difference": mean("brier_diff"),
        "paired_brier_difference_ci95": _bootstrap(rows, "brier_diff"),
        "shadow_signals": len(signals),
        "shadow_roi": (sum(row["roi"] for row in signals) / len(signals)) if signals else None,
        "shadow_roi_ci95": _bootstrap(signals, "roi_value") if signals else None,
        "rows": rows,
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run pre-registered H4-R LoL retrospective")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = run(PolymarketProvider(), ROOT / "data" / "lol.db")
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "rows"},
                     ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
