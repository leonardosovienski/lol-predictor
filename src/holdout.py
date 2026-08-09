"""Prospective, immutable data-only holdout collection."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from predictor_core.data.contracts import DataUnavailableError

from .data.ingestion import SnapshotStore
from .data.polymarket_provider import PolymarketProvider
from .freeze import atomic_json, sha256_file


def _immutable_json(path: Path, value: dict[str, Any]) -> None:
    encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    if path.exists():
        if path.read_bytes() != encoded:
            raise ValueError(f"immutable holdout capture differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def collect_holdout(
    data_root: Path,
    *,
    horizon_hours: int = 168,
    provider: PolymarketProvider | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not 1 <= horizon_hours <= 336:
        raise ValueError("horizon-hours must be between 1 and 336")
    observed = (now or datetime.now(UTC)).astimezone(UTC)
    raw_root = data_root / "holdout" / "raw"
    sources: dict[str, Any] = {}

    payload = SnapshotStore(data_root / "ingestion").current_payload()
    if payload is not None and payload.is_file():
        digest = sha256_file(payload)
        target = raw_root / "oracles-elixir" / digest / payload.name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
            shutil.copyfile(payload, temporary)
            os.replace(temporary, target)
        sources["oracles_elixir"] = {"sha256": digest, "path": str(target)}
    else:
        sources["oracles_elixir"] = {"status": "NO_CURRENT_SNAPSHOT"}

    market = provider or PolymarketProvider()
    quotes: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    try:
        events = market.list_upcoming_matches(horizon_hours=horizon_hours, now=observed)
        for event in events:
            try:
                quotes.append(
                    market.fetch_match(
                        event["team_a"],
                        event["team_b"],
                        observed_at=observed if now is not None else None,
                        event_id=event["event_id"],
                    )
                )
            except (DataUnavailableError, ValueError) as exc:
                errors.append({"event_id": event["event_id"], "error": str(exc)})
    except DataUnavailableError as exc:
        events = []
        errors.append({"event_id": "DISCOVERY", "error": str(exc)})
    capture = {
        "schema_version": "lol-prospective-holdout/1.0",
        "scientific_state": "COLLECTION_ONLY",
        "training_eligible": False,
        "observed_at": observed.isoformat(),
        "horizon_hours": horizon_hours,
        "sources": sources,
        "events": events,
        "quotes": quotes,
        "errors": errors,
    }
    capture_id = hashlib.sha256(
        json.dumps(capture, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    capture["capture_id"] = capture_id
    target = raw_root / "polymarket" / observed.strftime("%Y/%m/%d") / f"{capture_id}.json"
    _immutable_json(target, capture)
    pointer = {
        "schema_version": "lol-holdout-pointer/1.0",
        "capture_id": capture_id,
        "captured_at": observed.isoformat(),
        "path": str(target),
        "status": "DEGRADED" if errors else "COLLECTED",
        "events": len(events),
        "quotes": len(quotes),
    }
    atomic_json(data_root / "holdout" / "latest.json", pointer)
    return {**pointer, "artifact": str(data_root / "holdout" / "latest.json")}
