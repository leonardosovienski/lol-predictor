"""Read-only fixture runner for arbitrary LoL event matchups.

It deliberately bypasses ``src.predict`` because that serving CLI appends to
the prediction ledger.  The Elo engine itself is reused unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.config import clear_caches, load_teams, resolve_team  # noqa: E402
from src.model import EloModel, FORMAT_HOURS  # noqa: E402
from predictor_core.data.contracts import PredictionPoint  # noqa: E402
from predictor_core.kernel.jsonl_store import JsonlStore  # noqa: E402

DEFAULT_FIXTURE = ROOT / "data" / "fixtures" / "ewc_opening_2026.json"
_LEDGER_LOCK = threading.Lock()


@contextmanager
def _ledger_file_lock(path: Path):
    """Protege o ciclo read/dedupe/append sem alterar o core compartilhado."""
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b") as lock:
        lock.seek(0, os.SEEK_END)
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _aware_datetime(value: str, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid {field}: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed


def _require_aware(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _match_entries(fixture: dict[str, Any]) -> list[dict[str, Any]]:
    entries = []
    for raw in fixture["matches"]:
        if isinstance(raw, dict):
            teams = raw.get("teams")
            scheduled_at = raw.get("scheduled_at")
        else:
            teams = raw
            scheduled_at = None
        if not isinstance(teams, list) or len(teams) != 2 or not all(isinstance(team, str) for team in teams):
            raise ValueError("each fixture match must contain exactly two team names")
        if scheduled_at is not None:
            _aware_datetime(scheduled_at, "scheduled_at")
        entries.append({"team_a": teams[0], "team_b": teams[1], "scheduled_at": scheduled_at})
    return entries


def _team_metadata(canonical: str, db_path: Path, snapshot: datetime) -> dict[str, Any]:
    seeded = next((row for row in load_teams() if row["name"] == canonical), {})
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        games, last, league = conn.execute(
            "SELECT count(*), max(date), max(league) FROM games "
            "WHERE team_a=? COLLATE NOCASE OR team_b=? COLLATE NOCASE",
            (canonical, canonical),
        ).fetchone()
    finally:
        conn.close()
    last_at = datetime.fromisoformat(last).replace(tzinfo=timezone.utc) if last else None
    age = (snapshot - last_at).days if last_at else None
    freshness = "NOT_AVAILABLE" if not last else ("FRESH" if age <= 14 else "ACCEPTABLE" if age <= 45 else "STALE")
    quality = "NOT_AVAILABLE" if not last else ("INSUFFICIENT_HISTORY" if games < 10 else freshness)
    return {"region": seeded.get("region") or "NOT_AVAILABLE",
            "last_observed_competition": league or "NOT_AVAILABLE",
            "games": games, "last_observed_at": last, "rating_age_days": age,
            "freshness": freshness, "rating_quality": quality,
            "season_transition": "NOT_AVAILABLE",
            "roster_transition": "NOT_AVAILABLE"}


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
    snapshot = _aware_datetime(fixture["snapshot_at"], "snapshot_at")
    ratings_path = ratings_path or ROOT / fixture.get(
        "ratings_path", "data/ratings.json")
    db_path = db_path or ROOT / "data" / "lol.db"
    model = EloModel(ratings_file=ratings_path)
    if model.platt is not None:
        raise RuntimeError("canonical snapshot has Platt enabled; this H1-only run is blocked")
    aliases = fixture.get("aliases", {})
    entries = _match_entries(fixture)
    resolved = {name: resolve(name, aliases, model, db_path, snapshot)
                for entry in entries for name in (entry["team_a"], entry["team_b"])}
    predictions = []
    for entry in entries:
        team_a, team_b = entry["team_a"], entry["team_b"]
        a, b = resolved[team_a], resolved[team_b]
        if a["status"] == "MISSING" or b["status"] == "MISSING":
            predictions.append({"team_a": team_a, "team_b": team_b, "status": "BLOCKED", "reason": "identity or rating unavailable"})
            continue
        result = model.predict_match(a["canonical"], b["canonical"], fixture["format"])
        favorite = result["team_a"] if result["prob_team_a"] >= .5 else result["team_b"]
        scheduled_at = entry["scheduled_at"]
        matures_at = None
        if scheduled_at:
            scheduled = _aware_datetime(scheduled_at, "scheduled_at")
            matures_at = (scheduled + timedelta(hours=FORMAT_HOURS[fixture["format"]])).isoformat(timespec="seconds")
        qualities = {a["rating_quality"], b["rating_quality"]}
        limitations = ["Elo H1 only; no Platt, odds, kills, patch, side, draft, roster or manual regional adjustment."]
        if qualities & {"STALE", "INSUFFICIENT_HISTORY", "NOT_AVAILABLE"}:
            limitations.append("one or both teams have stale/limited game evidence")
        elif "ACCEPTABLE" in qualities:
            limitations.append("one or both teams have acceptable but aging game evidence")
        predictions.append({"team_a": team_a, "team_b": team_b, "canonical_a": result["team_a"], "canonical_b": result["team_b"], "status": "PREDICTED", "format": fixture["format"], "scheduled_at": scheduled_at, "matures_at": matures_at, "rating_a": result["elo_a"], "rating_b": result["elo_b"], "rating_difference_a_minus_b": round(result["elo_a"] - result["elo_b"], 1), "probability_a": result["prob_team_a"], "probability_b": result["prob_team_b"], "favorite": favorite, "confidence_band": _band(result["prob_team_a"]), "freshness_a": a["rating_quality"], "freshness_b": b["rating_quality"], "alias_a": a["status"], "alias_b": b["status"], "limitations": limitations})
    artifact_digest = hashlib.sha256(ratings_path.read_bytes()).hexdigest()
    digest = fixture.get("source_ratings_sha256", artifact_digest)
    ratings_mtime = fixture.get(
        "source_ratings_mtime_utc",
        datetime.fromtimestamp(ratings_path.stat().st_mtime, timezone.utc).isoformat(
            timespec="seconds"))
    return {"event": fixture["event"], "stage": fixture["stage"], "scheduled_date": fixture["scheduled_date"], "format": fixture["format"], "snapshot_at": fixture["snapshot_at"], "model": "elo-h1-map-win-probability; Platt disabled", "ratings_sha256": digest, "ratings_artifact_sha256": artifact_digest, "ratings_mtime_utc": ratings_mtime, "resolutions": list(resolved.values()), "predictions": predictions}


def _register_pre_event_unlocked(report: dict[str, Any], ledger_path: Path, now: datetime | None = None) -> dict[str, int]:
    """Append idempotent PRE_EVENT records for scheduled, resolvable matches."""
    emitted_at = _require_aware(now or datetime.now(timezone.utc), "now")
    store = JsonlStore(ledger_path)
    ledger = list(store)
    existing = {row.get("prediction_id") for row in ledger if row.get("prediction_id")}
    existing_matches = {
        (row.get("event"), row.get("stage"), row.get("scheduled_at"),
         row.get("team_a"), row.get("team_b"))
        for row in ledger if row.get("lifecycle_status") == "PRE_EVENT"
    }
    registered = skipped = 0
    pending = []
    for prediction in report["predictions"]:
        if prediction["status"] != "PREDICTED" or not prediction.get("scheduled_at"):
            continue
        key = "|".join((report["event"], report["stage"], prediction["scheduled_at"],
                        prediction["canonical_a"], prediction["canonical_b"],
                        report["model"], report["ratings_sha256"]))
        prediction_id = hashlib.sha256(key.encode("utf-8")).hexdigest()
        match_key = (report["event"], report["stage"],
                     prediction["scheduled_at"], prediction["canonical_a"],
                     prediction["canonical_b"])
        if prediction_id in existing or match_key in existing_matches:
            skipped += 1
            continue
        scheduled_at = _aware_datetime(prediction["scheduled_at"], "scheduled_at")
        if emitted_at >= scheduled_at:
            raise ValueError(
                f"PRE_EVENT blocked at/after scheduled_at for "
                f"{prediction['canonical_a']} vs {prediction['canonical_b']}")
        pending.append((prediction, prediction_id))

    for prediction, prediction_id in pending:
        matures_at = _aware_datetime(prediction["matures_at"], "matures_at")
        if matures_at <= scheduled_at:
            raise ValueError("matures_at must be after scheduled_at")
        point = PredictionPoint(
            predicted_at=emitted_at,
            matures_at=matures_at,
            value={"probability_a": prediction["probability_a"],
                   "probability_b": prediction["probability_b"],
                   "favorite": prediction["favorite"]},
            metadata={"event": report["event"], "stage": report["stage"],
                      "team_a": prediction["canonical_a"],
                      "team_b": prediction["canonical_b"],
                      "format": prediction["format"], "model": report["model"]})
        store.append({
            "schema_version": "lol-prediction-point/1.0",
            "prediction_id": prediction_id,
            "lifecycle_status": "PRE_EVENT",
            "predicted_at": point.predicted_at.isoformat(timespec="seconds"),
            "scheduled_at": prediction["scheduled_at"],
            "matures_at": point.matures_at.isoformat(timespec="seconds"),
            "event": report["event"], "stage": report["stage"],
            "team_a": prediction["canonical_a"], "team_b": prediction["canonical_b"],
            "format": prediction["format"], "model": report["model"],
            "ratings_sha256": report["ratings_sha256"],
            "value": point.value, "result": None, "brier": None, "correct": None,
            "limitations": prediction["limitations"],
        })
        existing.add(prediction_id)
        registered += 1
    return {"registered": registered, "already_present": skipped}


def register_pre_event(report: dict[str, Any], ledger_path: Path,
                       now: datetime | None = None) -> dict[str, int]:
    with _LEDGER_LOCK, _ledger_file_lock(ledger_path):
        return _register_pre_event_unlocked(report, ledger_path, now)


def _mature_results_unlocked(ledger_path: Path, results: dict[str, Any], now: datetime | None = None) -> dict[str, int]:
    """Append idempotent MATURED records after the declared prediction horizon."""
    observed_at = _require_aware(now or datetime.now(timezone.utc), "now")
    store = JsonlStore(ledger_path)
    records = list(store)
    pre_events = {row["prediction_id"]: row for row in records
                  if row.get("lifecycle_status") == "PRE_EVENT"}
    matured = {row["prediction_id"] for row in records
               if row.get("lifecycle_status") == "MATURED"}
    by_teams: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in pre_events.values():
        by_teams.setdefault((row["team_a"], row["team_b"]), []).append(row)
    registered = already_present = not_ready = 0
    for result in results.get("results", []):
        key = (result.get("team_a"), result.get("team_b"))
        requested_id = result.get("prediction_id")
        if requested_id is not None and requested_id not in pre_events:
            raise ValueError(
                f"unknown prediction_id {requested_id!r} for {key[0]} vs "
                f"{key[1]}; refusing to fall back to team-name matching")
        candidates = ([pre_events[requested_id]] if requested_id is not None
                      else list(by_teams.get(key, [])))
        if not candidates:
            raise ValueError(f"no PRE_EVENT record for {key[0]} vs {key[1]}")
        if len(candidates) != 1:
            raise ValueError(
                f"ambiguous PRE_EVENT records for {key[0]} vs {key[1]}; "
                "provide prediction_id")
        pre_event = candidates[0]
        if (pre_event["team_a"], pre_event["team_b"]) != key:
            raise ValueError(
                f"result teams {key} do not match PRE_EVENT "
                f"{(pre_event['team_a'], pre_event['team_b'])} for "
                f"prediction_id {pre_event['prediction_id']}")
        prediction_id = pre_event["prediction_id"]
        if prediction_id in matured:
            already_present += 1
            continue
        matures_at = _aware_datetime(pre_event.get("matures_at"), "matures_at")
        scheduled_at = _aware_datetime(pre_event.get("scheduled_at"), "scheduled_at")
        if matures_at <= scheduled_at:
            raise ValueError("matures_at must be after scheduled_at")
        if observed_at < matures_at:
            not_ready += 1
            continue
        winner = result.get("winner")
        if winner not in key:
            raise ValueError(f"winner must be one of the PRE_EVENT teams for {key[0]} vs {key[1]}")
        score = result.get("score")
        wins = {"bo1": 1, "bo3": 2, "bo5": 3}[pre_event["format"]]
        valid_scores = ({f"{wins}-{loss}" for loss in range(wins)}
                        if winner == key[0]
                        else {f"{loss}-{wins}" for loss in range(wins)})
        if score not in valid_scores:
            raise ValueError(
                f"invalid {pre_event['format']} score for winner {winner}: {score!r}")
        outcome_a = 1.0 if winner == key[0] else 0.0
        probability_a = float(pre_event["value"]["probability_a"])
        brier = round(2.0 * (probability_a - outcome_a) ** 2, 8)
        correct = pre_event["value"]["favorite"] == winner
        store.append({
            **pre_event,
            "lifecycle_status": "MATURED",
            "matured_at": observed_at.isoformat(timespec="seconds"),
            "result": {"winner": winner, "score": score},
            "brier": brier,
            "correct": correct,
        })
        matured.add(prediction_id)
        registered += 1
    return {"registered": registered, "already_present": already_present,
            "not_ready": not_ready}


def mature_results(ledger_path: Path, results: dict[str, Any],
                   now: datetime | None = None) -> dict[str, int]:
    with _LEDGER_LOCK, _ledger_file_lock(ledger_path):
        return _mature_results_unlocked(ledger_path, results, now)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only canonical Elo predictions from a fixture.")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", type=Path, help="Write structured JSON outside the data snapshot.")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--register-ledger", action="store_true",
                        help="Explicitly append scheduled PRE_EVENT records to the prediction ledger")
    parser.add_argument("--ledger", type=Path, default=Path(os.environ.get(
                        "PREDICTIONS_LOG_PATH", ROOT / "data" / "predictions.jsonl")))
    parser.add_argument("--mature-results", type=Path,
                        help="Append MATURED records from a results JSON after matures_at")
    args = parser.parse_args(argv)
    try:
        report = build(_load(args.fixture))
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.register_ledger:
        try:
            report["registration"] = register_pre_event(report, args.ledger)
        except (OSError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.mature_results:
        try:
            report["maturation"] = mature_results(args.ledger, _load(args.mature_results))
        except (OSError, ValueError, KeyError, TypeError) as exc:
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
