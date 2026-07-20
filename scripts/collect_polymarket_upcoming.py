"""Coleta automática das moneylines LoL conhecidas nas próximas 72 horas."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from predictor_core.data.contracts import DataUnavailableError  # noqa: E402
from src.config import resolve_team  # noqa: E402
from src.data.polymarket_provider import PolymarketProvider  # noqa: E402
from scripts.collect_polymarket_shadow import append_once, attach_model_snapshot  # noqa: E402


def resolve_market_team(display: str) -> str:
    aliases_path = ROOT / "data" / "polymarket_aliases.json"
    aliases = json.loads(aliases_path.read_text(encoding="utf-8"))["aliases"]
    target = aliases.get(display, display)
    return resolve_team(target)["name"]


def collect(output: Path, horizon_hours: int = 72) -> dict:
    provider = PolymarketProvider()
    discovered = provider.list_upcoming_matches(horizon_hours=horizon_hours)
    appended = duplicates = skipped_identity = unavailable = 0
    errors = []
    for match in discovered:
        try:
            team_a = resolve_market_team(match["team_a"])
            team_b = resolve_market_team(match["team_b"])
        except ValueError as exc:
            skipped_identity += 1
            errors.append({"event_id": match["event_id"], "kind": "identity",
                           "error": str(exc)})
            continue
        try:
            quote = provider.fetch_match(
                match["team_a"], match["team_b"], event_id=match["event_id"])
            quote = {**quote,
                     "source_team_a": match["team_a"],
                     "source_team_b": match["team_b"],
                     "team_a": team_a, "team_b": team_b}
            quote = attach_model_snapshot(quote)
            if append_once(output, quote):
                appended += 1
            else:
                duplicates += 1
        except DataUnavailableError as exc:
            unavailable += 1
            errors.append({"event_id": match["event_id"], "kind": "market",
                           "error": str(exc)})
    return {"discovered": len(discovered), "appended": appended,
            "duplicates": duplicates, "skipped_identity": skipped_identity,
            "unavailable": unavailable, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect upcoming LoL shadow quotes")
    parser.add_argument("--horizon-hours", type=int, default=72)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "data" / "shadow" / "market_quotes.jsonl")
    args = parser.parse_args(argv)
    if not 1 <= args.horizon_hours <= 168:
        print("horizon-hours deve estar entre 1 e 168", file=sys.stderr)
        return 2
    try:
        report = collect(args.output, args.horizon_hours)
    except (DataUnavailableError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
