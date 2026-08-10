"""Shadow adapter from Oracle CSV snapshots to predictor-core collection envelopes."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from predictor_core.data.collection import CollectionArchive, ObservationEnvelope

from .data.riot_provider import OracleProvider
from .identity import IdentityError, IdentityRegistry


class _IndexedCollectionArchive(CollectionArchive):
    """Keep core transition validation while avoiding a full JSONL scan per event."""

    def __init__(self, path: Path):
        super().__init__(path)
        self._history: dict[tuple[str, str], list[ObservationEnvelope]] = {}
        for row in self._events():
            envelope = ObservationEnvelope.from_dict(row["envelope"])
            key = (envelope.collection_run_id, envelope.canonical_event_id)
            self._history.setdefault(key, []).append(envelope)

    def history(self, collection_run_id: str, canonical_event_id: str) -> list[ObservationEnvelope]:
        return list(self._history.get((collection_run_id, canonical_event_id), ()))

    def append(
        self, envelope: ObservationEnvelope, *, previous: ObservationEnvelope | None = None
    ) -> ObservationEnvelope:
        result = super().append(envelope, previous=previous)
        key = (result.collection_run_id, result.canonical_event_id)
        history = self._history.setdefault(key, [])
        if not history or history[-1] != result:
            history.append(result)
        return result


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _commit(project_root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(project_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else "UNAVAILABLE"


def archive_snapshot(*, data_root: Path, project_root: Path, payload: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    registry = IdentityRegistry(data_root / "canonical_teams.json")
    snapshot_hash = str(metadata["sha256"])
    observed_at = _utc(
        str(metadata.get("retrieved_at") or metadata.get("available_at") or datetime.now(UTC).isoformat())
    )
    run_id = f"lol-shadow-{snapshot_hash[:20]}"
    archive_path = data_root / "collection_archive" / "events.jsonl"
    archive = _IndexedCollectionArchive(archive_path)
    quarantine_path = data_root / "quarantine" / f"{run_id}.jsonl"
    quarantine_path.parent.mkdir(parents=True, exist_ok=True)
    quarantined = set()
    if quarantine_path.is_file():
        for line in quarantine_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            quarantined.add((row.get("source_record_id"), row.get("raw_sha256")))
    accepted = rejected = skipped = 0
    for game in OracleProvider(payload.parent).iter_games():
        try:
            team_a = registry.resolve(
                provider="oracles_elixir", provider_id=game.get("team_a_id"), name=game.get("team_a")
            )
            team_b = registry.resolve(
                provider="oracles_elixir", provider_id=game.get("team_b_id"), name=game.get("team_b")
            )
            if team_a.canonical_id == team_b.canonical_id:
                raise IdentityError("both participants resolve to the same canonical team")
        except IdentityError as exc:
            rejected += 1
            record = {
                "schema_version": "lol-identity-quarantine/1.0",
                "collection_run_id": run_id,
                "observed_at": observed_at.isoformat(),
                "reason": str(exc),
                "source_record_id": game.get("game_id"),
                "raw_sha256": _hash(game),
                "raw": game,
            }
            quarantine_key = (record["source_record_id"], record["raw_sha256"])
            if quarantine_key not in quarantined:
                with quarantine_path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                quarantined.add(quarantine_key)
            continue
        event_id = f"oracles-elixir:{game['game_id']}:{team_a.canonical_id}:{team_b.canonical_id}"
        if archive.history(run_id, event_id):
            skipped += 1
            continue
        result = {"winner_canonical_id": team_a.canonical_id if game["winner"] == "a" else team_b.canonical_id}
        envelope = ObservationEnvelope(
            collection_run_id=run_id,
            project="lol-predictor",
            domain="league-of-legends",
            canonical_event_id=event_id,
            observed_at=observed_at,
            scheduled_at=_utc(str(game["date"])),
            source="oracles-elixir",
            source_record_id=str(game["game_id"]),
            provenance_hash=_hash(game),
            source_snapshot_hash=snapshot_hash,
            code_commit=_commit(project_root),
            core_version=version("predictor-core"),
            participants={
                "team_a": {"canonical_id": team_a.canonical_id, "display_name": team_a.display_name},
                "team_b": {"canonical_id": team_b.canonical_id, "display_name": team_b.display_name},
            },
            competition={"league": game.get("league"), "split": game.get("split")},
            lifecycle_state="SNAPSHOT_RECORDED",
            official_result=result,
        )
        archive.append(envelope)
        accepted += 1
    report = {
        "schema_version": "lol-collection-shadow-run/1.0",
        "collection_run_id": run_id,
        "snapshot_sha256": snapshot_hash,
        "registry_version": registry.version,
        "accepted": accepted,
        "rejected": rejected,
        "skipped": skipped,
        "archive": str(archive_path),
        "quarantine": str(quarantine_path),
        "status": "ALERT" if rejected else "SHADOW_VALID",
        "completed_at": datetime.now(UTC).isoformat(),
    }
    from .freeze import atomic_json

    atomic_json(data_root / "collection_archive" / "latest_run.json", report)
    return report
