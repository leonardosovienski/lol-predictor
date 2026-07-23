"""Fail-closed archival sports collection, isolated from H4 and trading."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import resolve_team

SCHEMA = "lol-collection-only/1.0"


class CollectionError(ValueError): pass


def _time(value: Any, name: str) -> datetime:
    try: parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc: raise CollectionError(f"{name} inválido") from exc
    if parsed.tzinfo is None: raise CollectionError(f"{name} sem timezone")
    return parsed.astimezone(timezone.utc)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def _atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2); handle.write("\n")
            handle.flush(); os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


def normalize_event(raw: dict[str, Any]) -> dict[str, Any]:
    """Require source IDs: the collector never guesses a series from maps."""
    required = ("source", "source_event_id", "competition_id", "competition_name",
                "format", "scheduled_at", "team_a", "team_b", "maps")
    missing = [key for key in required if raw.get(key) in (None, "")]
    if missing: raise CollectionError(f"evento sem contrato: {missing}")
    try:
        team_a, team_b = resolve_team(raw["team_a"])["name"], resolve_team(raw["team_b"])["name"]
    except ValueError as exc: raise CollectionError(f"identidade ambígua/desconhecida: {exc}") from exc
    if team_a == team_b: raise CollectionError("times canônicos idênticos")
    scheduled = _time(raw["scheduled_at"], "scheduled_at")
    if raw["format"] not in {"bo1", "bo3", "bo5"}: raise CollectionError("formato inválido")
    if not isinstance(raw["maps"], list): raise CollectionError("maps inválido")
    maps = []
    for row in raw["maps"]:
        if not isinstance(row, dict) or not row.get("source_map_id"):
            raise CollectionError("mapa sem source_map_id")
        result = row.get("result")
        if result not in (None, "a", "b"): raise CollectionError("resultado de mapa inválido")
        maps.append({"source_map_id": str(row["source_map_id"]), "result": result,
                     "started_at": row.get("started_at"), "completed_at": row.get("completed_at")})
    if len({row["source_map_id"] for row in maps}) != len(maps): raise CollectionError("mapas duplicados")
    canonical_event_id = f"{raw['source']}:{raw['source_event_id']}"
    provenance = {key: raw.get(key) for key in ("source", "source_event_id", "competition_id", "competition_name", "scheduled_at", "format")}
    lifecycle = "RESULT_OFFICIAL" if raw.get("result") in ("a", "b") else "RESULT_PENDING"
    return {"schema_version": SCHEMA, "canonical_event_id": canonical_event_id,
            "source": raw["source"], "source_event_id": str(raw["source_event_id"]),
            "competition_id": str(raw["competition_id"]), "competition_name": raw["competition_name"],
            "region": raw.get("region"), "tournament": raw.get("tournament"), "split": raw.get("split"),
            "format": raw["format"], "team_a": team_a, "team_b": team_b,
            "scheduled_at": scheduled.isoformat(), "maps": maps, "result": raw.get("result"),
            "result_available_at": raw.get("result_available_at"), "lifecycle_status": lifecycle,
            "provenance_hash": _digest(provenance)}


def collect(root: Path, run: dict[str, Any], incoming: list[dict[str, Any]], *, now: datetime | None = None) -> dict[str, Any]:
    """Publish a complete archival snapshot, preserving the old one on error."""
    observed = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if run.get("mode") != "COLLECTION_ONLY" or not isinstance(run.get("collection_run_id"), str):
        raise CollectionError("run COLLECTION_ONLY inválido")
    accepted, rejected = [], []
    for raw in incoming:
        try: accepted.append(normalize_event(raw))
        except CollectionError as exc: rejected.append({"source_event_id": raw.get("source_event_id"), "reason": str(exc)})
    if len({row["canonical_event_id"] for row in accepted}) != len(accepted):
        raise CollectionError("evento canônico duplicado; publicação bloqueada")
    status = "NO_UPSTREAM_EVENTS" if not incoming else "COLLECTED"
    snapshot = {"schema_version": SCHEMA, "collection_run_id": run["collection_run_id"],
                "mode": "COLLECTION_ONLY", "collected_at": observed.isoformat(), "status": status,
                "events": accepted, "rejected": rejected,
                "provenance_hash": _digest({"run": run["collection_run_id"], "events": accepted})}
    _atomic(root / "current.json", snapshot)
    return snapshot


def health(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    path = root / "current.json"
    if not path.exists(): return {"status": "NO_COLLECTION_SNAPSHOT"}
    data = json.loads(path.read_text(encoding="utf-8")); observed = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age = observed - _time(data["collected_at"], "collected_at")
    future = any(_time(row["scheduled_at"], "scheduled_at") > observed for row in data.get("events", []))
    past_pending = [row["canonical_event_id"] for row in data.get("events", [])
                    if _time(row["scheduled_at"], "scheduled_at") < observed and row["lifecycle_status"] != "RESULT_OFFICIAL"]
    if future and age > timedelta(hours=48): return {"status": "STALE_EXPECTED_EVENT", "age_hours": age.total_seconds()/3600}
    if past_pending: return {"status": "PAST_EVENT_RESULT_PENDING", "events": past_pending}
    return {"status": data["status"], "age_hours": age.total_seconds()/3600}


def promote_to_trial(_observation: dict[str, Any]) -> None:
    raise CollectionError("COLLECTION_ONLY não pode promover observação para trial")
