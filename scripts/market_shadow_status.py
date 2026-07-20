"""Status do pré-registro H4 sem calcular resultado antes da maturação."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def status(quotes_path: Path, trials_path: Path,
           now: datetime | None = None) -> dict:
    observed_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    trials = json.loads(trials_path.read_text(encoding="utf-8"))
    trial = next(row for row in trials
                 if row["name"] == "h4-lol-market-shadow-prospectivo")
    params = trial["params"]
    start = datetime.fromisoformat(
        params["collection_start_exclusive"].replace("Z", "+00:00"))
    cutoff = timedelta(minutes=params["closing_cutoff_minutes_before_start"])
    rows = []
    if quotes_path.exists():
        rows = [json.loads(line) for line in quotes_path.read_text(
            encoding="utf-8").splitlines() if line.strip()]
    eligible = []
    for row in rows:
        try:
            observed = datetime.fromisoformat(row["observed_at"])
            published = datetime.fromisoformat(row["published_at"])
            scheduled = datetime.fromisoformat(row["scheduled_at"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (observed > start and published <= observed < scheduled - cutoff):
            continue
        if row.get("max_spread", float("inf")) > params["max_spread"]:
            continue
        if row.get("liquidity", 0) < params["min_liquidity"]:
            continue
        if not all(key in row for key in (
                "model_probability_a", "model_probability_b", "ratings_sha256")):
            continue
        eligible.append(row)
    latest = {}
    for row in eligible:
        key = row["condition_id"]
        if key not in latest or row["observed_at"] > latest[key]["observed_at"]:
            latest[key] = row
    selected = list(latest.values())
    matured = sum(datetime.fromisoformat(row["scheduled_at"]) < observed_now
                  for row in selected)
    return {
        "trial": trial["name"], "registered_at": trial["registered_at"],
        "raw_quotes": len(rows), "eligible_quotes": len(eligible),
        "eligible_matches": len(selected), "matured_matches": matured,
        "pending_matches": len(selected) - matured,
        "required_matured_matches": params["min_matured_matches"],
        "required_calendar_days": params["min_calendar_days"],
        "decision_ready": matured >= params["min_matured_matches"],
        "verdict": "PENDING_SAMPLE" if matured < params["min_matured_matches"]
                   else "READY_FOR_BLINDED_EVALUATION",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show H4 LoL market shadow status")
    parser.add_argument("--quotes", type=Path,
                        default=ROOT / "data" / "shadow" / "market_quotes.jsonl")
    args = parser.parse_args(argv)
    print(json.dumps(status(args.quotes, ROOT / "data" / "trials.json"),
                     ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
