"""Read-only fixture runner for arbitrary LoL event matchups.

It deliberately bypasses ``src.predict`` because that serving CLI appends to
the prediction ledger.  The Elo engine itself is reused unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.config import clear_caches, load_teams, resolve_team  # noqa: E402
from src.model import EloModel  # noqa: E402

DEFAULT_FIXTURE = ROOT / "data" / "fixtures" / "ewc_opening_2026.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _team_metadata(canonical: str, db_path: Path, snapshot: datetime) -> dict[str, Any]:
    seeded = next((row for row in load_teams() if row["name"] == canonical), {})
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        games, last, league = conn.execute(
            "SELECT count(*), max(date), max(league) FROM games WHERE team_a=? OR team_b=?",
            (canonical, canonical),
        ).fetchone()
    finally:
        conn.close()
    last_at = datetime.fromisoformat(last).replace(tzinfo=timezone.utc) if last else None
    age = (snapshot - last_at).days if last_at else None
    freshness = "NOT_AVAILABLE" if not last else ("FRESH" if age <= 14 else "ACCEPTABLE" if age <= 45 else "STALE")
    quality = "NOT_AVAILABLE" if not last else ("INSUFFICIENT_HISTORY" if games < 10 else freshness)
    return {"region": seeded.get("region") or league or "NOT_AVAILABLE", "games": games, "last_observed_at": last, "rating_age_days": age, "freshness": freshness, "rating_quality": quality, "season_transition": "NOT_AVAILABLE", "roster_transition": "NOT_AVAILABLE"}


def resolve(display: str, aliases: dict[str, Any], model: EloModel, db_path: Path, snapshot: datetime) -> dict[str, Any]:
    if display in aliases:
        alias = aliases[display]
        canonical, status, source = alias["canonical"], alias["confidence"], alias["source"]
    else:
        try:
            canonical = resolve_team(display)["name"]
        except ValueError as exc:
            return {"display": display, "status": "MISSING", "reason": str(exc)}
        status = "EXACT" if canonical == display else "VERIFIED_ALIAS"
        source = "project canonical resolver (case-normalized exact name)"
    if canonical not in model.ratings:
        return {"display": display, "canonical": canonical, "status": "MISSING", "reason": "rating unavailable"}
    return {"display": display, "canonical": canonical, "stored_name": canonical, "status": status, "alias_source": source, "rating": round(float(model.ratings[canonical]), 1), **_team_metadata(canonical, db_path, snapshot)}


def _band(probability: float) -> str:
    favorite = max(probability, 1.0 - probability)
    return "muito equilibrado" if favorite < .55 else "leve vantagem" if favorite < .60 else "vantagem moderada" if favorite < .70 else "vantagem forte"


def build(fixture: dict[str, Any], ratings_path: Path | None = None, db_path: Path | None = None) -> dict[str, Any]:
    clear_caches()
    snapshot = datetime.fromisoformat(fixture["snapshot_at"])
    ratings_path = ratings_path or ROOT / "data" / "ratings.json"
    db_path = db_path or ROOT / "data" / "lol.db"
    model = EloModel(ratings_file=ratings_path)
    if model.platt is not None:
        raise RuntimeError("canonical snapshot has Platt enabled; this H1-only run is blocked")
    aliases = fixture.get("aliases", {})
    resolved = {name: resolve(name, aliases, model, db_path, snapshot) for match in fixture["matches"] for name in match}
    predictions = []
    for team_a, team_b in fixture["matches"]:
        a, b = resolved[team_a], resolved[team_b]
        if a["status"] == "MISSING" or b["status"] == "MISSING":
            predictions.append({"team_a": team_a, "team_b": team_b, "status": "BLOCKED", "reason": "identity or rating unavailable"})
            continue
        result = model.predict_match(a["canonical"], b["canonical"], fixture["format"])
        favorite = result["team_a"] if result["prob_team_a"] >= .5 else result["team_b"]
        predictions.append({"team_a": team_a, "team_b": team_b, "canonical_a": result["team_a"], "canonical_b": result["team_b"], "status": "PREDICTED", "format": fixture["format"], "rating_a": result["elo_a"], "rating_b": result["elo_b"], "rating_difference_a_minus_b": round(result["elo_a"] - result["elo_b"], 1), "probability_a": result["prob_team_a"], "probability_b": result["prob_team_b"], "favorite": favorite, "confidence_band": _band(result["prob_team_a"]), "freshness_a": a["rating_quality"], "freshness_b": b["rating_quality"], "alias_a": a["status"], "alias_b": b["status"], "limitations": ["Elo H1 only; no Platt, odds, kills, draft or manual regional adjustment.", *(["one or both teams have stale/limited game evidence"] if a["rating_quality"] in {"STALE", "INSUFFICIENT_HISTORY"} or b["rating_quality"] in {"STALE", "INSUFFICIENT_HISTORY"} else [])]})
    digest = hashlib.sha256(ratings_path.read_bytes()).hexdigest()
    return {"event": fixture["event"], "stage": fixture["stage"], "scheduled_date": fixture["scheduled_date"], "format": fixture["format"], "snapshot_at": fixture["snapshot_at"], "model": "elo-h1-map-win-probability; Platt disabled", "ratings_sha256": digest, "ratings_mtime_utc": datetime.fromtimestamp(ratings_path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"), "resolutions": list(resolved.values()), "predictions": predictions}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only canonical Elo predictions from a fixture.")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", type=Path, help="Write structured JSON outside the data snapshot.")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = build(_load(args.fixture))
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    if args.json:
        print(encoded)
    else:
        for item in report["predictions"]:
            print(f"{item['team_a']} vs {item['team_b']}: {item['status']}" + (f" — {item['favorite']} {max(item['probability_a'], item['probability_b']):.1%}" if item['status'] == 'PREDICTED' else ""))
    return 2 if args.strict and any(item["status"] != "PREDICTED" for item in report["predictions"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
