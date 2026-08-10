"""Sealed LoL DatasetFreeze publication and fail-closed loading."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from predictor_core.contracts.scientific import DatasetFreeze
from predictor_core.kernel.timeindex import parse_iso

FREEZE_SCHEMA = "lol-dataset-freeze/1.1"
BACKTEST_MANIFEST_SCHEMA = "lol-backtest-manifest/1.0"


class FreezeError(RuntimeError):
    """A freeze is missing, inconsistent, or tampered with."""


def snapshot_partitions(path: Path) -> dict[str, Any]:
    """Hash real IS/OOS rows; the latest observed UTC day is reserved OOS."""
    try:
        with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, UnicodeError, csv.Error) as exc:
        raise FreezeError("snapshot CSV cannot be partitioned") from exc
    dated: list[tuple[datetime, dict[str, str]]] = []
    for row in rows:
        raw = (row.get("date") or "").strip()
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise FreezeError(f"snapshot row has invalid date: {raw!r}") from exc
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        dated.append((value.astimezone(UTC), row))
    days = sorted({value.date() for value, _row in dated})
    if len(days) < 2:
        raise FreezeError("DatasetFreeze requires at least two observed days for real IS/OOS partitions")
    cutoff = datetime.combine(days[-1], datetime.min.time(), tzinfo=UTC)
    training = [row for value, row in dated if value < cutoff]
    holdout = [row for value, row in dated if value >= cutoff]
    if not training or not holdout:
        raise FreezeError("DatasetFreeze IS/OOS partition cannot be empty")

    def rows_hash(values: list[dict[str, str]]) -> str:
        return canonical_hash(values)

    start = datetime.combine(days[0], datetime.min.time(), tzinfo=UTC)
    end = datetime.combine(days[-1], datetime.max.time(), tzinfo=UTC)
    return {
        "period_start": start.isoformat().replace("+00:00", "Z"),
        "period_end": end.isoformat().replace("+00:00", "Z"),
        "oos_cutoff": cutoff.isoformat().replace("+00:00", "Z"),
        "partition_hashes": {"training": rows_hash(training), "holdout": rows_hash(holdout)},
        "row_counts": {"training": len(training), "holdout": len(holdout)},
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise FreezeError(f"cannot hash required artifact: {path}") from exc
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(raw, path)
    finally:
        if os.path.exists(raw):
            os.unlink(raw)


def _immutable_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if sha256_file(source) != sha256_file(target):
            raise FreezeError(f"immutable freeze artifact already differs: {target}")
        return
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with source.open("rb") as src, temporary.open("xb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise FreezeError(f"artifact escapes data root: {path}") from exc


def _resolve(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise FreezeError(f"freeze path escapes data root: {relative}") from exc
    return candidate


def _git_identity(project_root: Path) -> dict[str, Any]:
    result = subprocess.run(
        ["git", "-C", str(project_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    commit = result.stdout.strip() if result.returncode == 0 and len(result.stdout.strip()) == 40 else "UNAVAILABLE"
    dirty = subprocess.run(
        ["git", "-C", str(project_root), "status", "--porcelain"], capture_output=True, text=True, check=False
    )
    return {"commit": commit, "worktree_dirty": bool(dirty.stdout.strip()) if dirty.returncode == 0 else None}


def write_backtest_manifest(
    *,
    data_root: Path,
    snapshot_payload: Path,
    snapshot_metadata: Path,
    snapshot_hash: str,
    period_start: str,
    period_end: str,
    oos_cutoff: str,
    partition_hashes: dict[str, str],
    processing: dict[str, str],
) -> dict[str, Any]:
    artifacts = {}
    for label, name in {
        "ratings": "ratings.json",
        "calibration": "calibration.json",
        "summary": "walkforward_summary.json",
    }.items():
        path = data_root / name
        artifacts[label] = {"path": _relative(path, data_root), "sha256": sha256_file(path)}
    manifest = {
        "schema_version": BACKTEST_MANIFEST_SCHEMA,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "snapshot": {
            "payload_path": _relative(snapshot_payload, data_root),
            "payload_sha256": snapshot_hash,
            "metadata_path": _relative(snapshot_metadata, data_root),
            "metadata_sha256": sha256_file(snapshot_metadata),
            "period_start": period_start,
            "period_end": period_end,
            "oos_cutoff": oos_cutoff,
            "partition_hashes": partition_hashes,
            "partition_roles": {"training": "IS", "holdout": "OOS"},
        },
        "artifacts": artifacts,
        "processing": processing,
    }
    manifest["manifest_hash"] = canonical_hash(manifest)
    atomic_json(data_root / "backtest_manifest.json", manifest)
    return manifest


def _verify_backtest_manifest(data_root: Path, manifest: dict[str, Any]) -> None:
    supplied = manifest.get("manifest_hash")
    unsigned = {key: value for key, value in manifest.items() if key != "manifest_hash"}
    if manifest.get("schema_version") != BACKTEST_MANIFEST_SCHEMA or supplied != canonical_hash(unsigned):
        raise FreezeError("backtest manifest seal is invalid")
    snapshot = manifest.get("snapshot") or {}
    payload = _resolve(data_root, str(snapshot.get("payload_path", "")))
    metadata = _resolve(data_root, str(snapshot.get("metadata_path", "")))
    if sha256_file(payload) != snapshot.get("payload_sha256") or sha256_file(metadata) != snapshot.get(
        "metadata_sha256"
    ):
        raise FreezeError("backtest snapshot provenance does not match disk")
    for entry in (manifest.get("artifacts") or {}).values():
        path = _resolve(data_root, str(entry.get("path", "")))
        if sha256_file(path) != entry.get("sha256"):
            raise FreezeError(f"derived artifact hash mismatch: {path.name}")


def _dataset_freeze_from_dict(row: dict[str, Any]) -> DatasetFreeze:
    value = dict(row)
    for field in ("dataset_frozen_at", "period_start", "period_end", "oos_cutoff"):
        value[field] = parse_iso(value[field])
    for field in ("assets", "sources", "metrics", "features"):
        value[field] = tuple(value[field])
    return DatasetFreeze(**value)


def publish_freeze(*, data_root: Path, project_root: Path, config_path: Path) -> dict[str, Any]:
    backtest_path = data_root / "backtest_manifest.json"
    try:
        backtest = json.loads(backtest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FreezeError("valid backtest_manifest.json is required") from exc
    _verify_backtest_manifest(data_root, backtest)
    expected_processing = {
        "config_sha256": sha256_file(config_path),
        "model_code_sha256": sha256_file(project_root / "src" / "model.py"),
        "backtest_code_sha256": sha256_file(project_root / "scripts" / "backtest_walkforward.py"),
        "canonical_teams_sha256": sha256_file(data_root / "canonical_teams.json"),
        "collection_archive_sha256": sha256_file(data_root / "collection_archive" / "events.jsonl"),
        "collection_run_sha256": canonical_hash(
            json.loads((data_root / "collection_archive" / "latest_run.json").read_text(encoding="utf-8"))
        ),
    }
    if backtest.get("processing") != expected_processing:
        raise FreezeError("backtest was produced by different code or configuration")

    trials = data_root / "trials.json"
    charter = data_root / "data_acquisition_charter.json"
    teams = data_root / "teams_lol.json"
    aliases = data_root / "polymarket_aliases.json"
    canonical_teams = data_root / "canonical_teams.json"
    required = (trials, charter, teams, aliases, canonical_teams, config_path)
    if missing := [str(path) for path in required if not path.is_file()]:
        raise FreezeError(f"freeze inputs are missing: {missing}")
    config_hash = sha256_file(config_path)
    identity_hash = canonical_hash(
        {
            "teams": sha256_file(teams),
            "aliases": sha256_file(aliases),
            "canonical_teams": sha256_file(canonical_teams),
        }
    )
    code = _git_identity(project_root)
    source_files = [
        project_root / "src" / name
        for name in ("model.py", "services.py", "operations.py", "freeze.py", "identity.py", "collection_shadow.py")
    ]
    source_hash = canonical_hash({path.name: sha256_file(path) for path in source_files})
    identity_seed = {
        "backtest_manifest_hash": backtest["manifest_hash"],
        "config_hash": config_hash,
        "identity_hash": identity_hash,
        "source_hash": source_hash,
        "hypothesis_registry_hash": sha256_file(trials),
        "lol_predictor_version": version("lol-predictor"),
        "predictor_core_version": version("predictor-core"),
        "git_commit": code["commit"],
    }
    freeze_id = canonical_hash(identity_seed)
    freeze_root = data_root / "freezes" / freeze_id
    frozen_artifacts: dict[str, dict[str, str]] = {}
    for label, entry in backtest["artifacts"].items():
        source = _resolve(data_root, entry["path"])
        target_artifact = freeze_root / "artifacts" / source.name
        _immutable_copy(source, target_artifact)
        frozen_artifacts[label] = {
            "path": _relative(target_artifact, data_root),
            "sha256": entry["sha256"],
        }
    frozen_backtest = freeze_root / "backtest_manifest.json"
    frozen_config = freeze_root / "config.yaml"
    frozen_teams = freeze_root / "identities" / "teams_lol.json"
    frozen_aliases = freeze_root / "identities" / "polymarket_aliases.json"
    frozen_canonical = freeze_root / "identities" / "canonical_teams.json"
    frozen_trials = freeze_root / "governance" / "trials.json"
    frozen_charter = freeze_root / "governance" / "data_acquisition_charter.json"
    collection_archive = data_root / "collection_archive" / "events.jsonl"
    collection_run = data_root / "collection_archive" / "latest_run.json"
    frozen_collection_archive = freeze_root / "collection" / "events.jsonl"
    frozen_collection_run = freeze_root / "collection" / "latest_run.json"
    for source, target_artifact in (
        (backtest_path, frozen_backtest),
        (config_path, frozen_config),
        (teams, frozen_teams),
        (aliases, frozen_aliases),
        (canonical_teams, frozen_canonical),
        (trials, frozen_trials),
        (charter, frozen_charter),
        (collection_archive, frozen_collection_archive),
        (collection_run, frozen_collection_run),
    ):
        _immutable_copy(source, target_artifact)
    snapshot = backtest["snapshot"]
    feature_version = f"git:{code['commit']}:source:{source_hash}"
    core = DatasetFreeze(
        freeze_id=freeze_id,
        hypothesis_id="h1-lol-elo-mapa-prequential",
        dataset_frozen_at=datetime.now(UTC),
        period_start=parse_iso(snapshot["period_start"]),
        period_end=parse_iso(snapshot["period_end"]),
        oos_cutoff=parse_iso(snapshot["oos_cutoff"]),
        assets=("professional-lol-maps",),
        sources=("oracles-elixir",),
        metrics=("map-winner", "total-kills"),
        features=("elo-map-rating", "league-total-kills-baseline", "canonical-team-identity"),
        feature_code_version=feature_version,
        charter_hashes={"lol-oracles-elixir-v1": sha256_file(charter)},
        hypothesis_registry_hash=sha256_file(trials),
        collector_versions={"oracles-elixir": "2026.07.resilient.1"},
        schema_versions={
            "snapshot": "oracle-csv/1",
            "backtest": BACKTEST_MANIFEST_SCHEMA,
            "canonical_teams": "lol-canonical-teams/1.0",
            "collection_archive": "collection-only/1",
        },
        partition_hashes=dict(snapshot["partition_hashes"]),
        partition_roles=dict(snapshot["partition_roles"]),
        exclusion_policy={
            "oos_policy": "last observed UTC calendar day is reserved and excluded from ratings",
            "config_hash": config_hash,
            "identity_map_hash": identity_hash,
        },
    ).seal()
    unsigned = {
        "schema_version": FREEZE_SCHEMA,
        "freeze_id": freeze_id,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "generated_by": "lol-predictor publish-freeze",
        "dataset_freeze": core.to_dict(),
        "backtest_manifest": {
            "path": _relative(frozen_backtest, data_root),
            "sha256": sha256_file(frozen_backtest),
        },
        "artifacts": frozen_artifacts,
        "snapshot": snapshot,
        "collection_archive": {
            "path": _relative(frozen_collection_archive, data_root),
            "sha256": sha256_file(frozen_collection_archive),
            "run_path": _relative(frozen_collection_run, data_root),
            "run_sha256": sha256_file(frozen_collection_run),
        },
        "configuration": {
            "path": _relative(frozen_config, data_root),
            "active_path": str(config_path),
            "sha256": config_hash,
        },
        "identities": {
            "teams": {
                "path": _relative(frozen_teams, data_root),
                "active_path": _relative(teams, data_root),
                "sha256": sha256_file(teams),
            },
            "aliases": {
                "path": _relative(frozen_aliases, data_root),
                "active_path": _relative(aliases, data_root),
                "sha256": sha256_file(aliases),
            },
            "canonical_teams": {
                "path": _relative(frozen_canonical, data_root),
                "active_path": _relative(canonical_teams, data_root),
                "sha256": sha256_file(canonical_teams),
            },
            "combined_sha256": identity_hash,
        },
        "governance": {
            "trials": {"path": _relative(frozen_trials, data_root), "sha256": sha256_file(trials)},
            "charter": {"path": _relative(frozen_charter, data_root), "sha256": sha256_file(charter)},
        },
        "code": {
            "lol_predictor_version": version("lol-predictor"),
            "predictor_core_version": version("predictor-core"),
            "source_sha256": source_hash,
            **code,
        },
    }
    manifest = {**unsigned, "manifest_hash": canonical_hash(unsigned)}
    target = freeze_root / "manifest.json"
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
        # generated timestamps differ; an existing immutable identity remains authoritative.
        manifest = existing
    else:
        atomic_json(target, manifest)
    pointer = {
        "schema_version": "lol-current-freeze/1.0",
        "freeze_id": freeze_id,
        "path": _relative(target, data_root),
        "manifest_hash": manifest["manifest_hash"],
    }
    atomic_json(data_root / "current_freeze.json", pointer)
    return manifest


def load_current_freeze(data_root: Path, project_root: Path | None = None) -> tuple[dict[str, Any], dict[str, Path]]:
    try:
        pointer = json.loads((data_root / "current_freeze.json").read_text(encoding="utf-8"))
        target = _resolve(data_root, pointer["path"])
        manifest = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise FreezeError("current DatasetFreeze is unavailable") from exc
    unsigned = {key: value for key, value in manifest.items() if key != "manifest_hash"}
    if (
        pointer.get("schema_version") != "lol-current-freeze/1.0"
        or manifest.get("schema_version") != FREEZE_SCHEMA
        or manifest.get("freeze_id") != pointer.get("freeze_id")
        or manifest.get("manifest_hash") != pointer.get("manifest_hash")
        or manifest.get("manifest_hash") != canonical_hash(unsigned)
    ):
        raise FreezeError("current DatasetFreeze manifest seal is invalid")
    core = _dataset_freeze_from_dict(manifest["dataset_freeze"])
    if not core.verify() or core.freeze_id != manifest["freeze_id"]:
        raise FreezeError("predictor-core DatasetFreeze seal is invalid")
    artifacts: dict[str, Path] = {}
    for label, entry in manifest["artifacts"].items():
        path = _resolve(data_root, entry["path"])
        if sha256_file(path) != entry["sha256"]:
            raise FreezeError(f"frozen artifact hash mismatch: {label}")
        artifacts[label] = path
    payload = _resolve(data_root, manifest["snapshot"]["payload_path"])
    if sha256_file(payload) != manifest["snapshot"]["payload_sha256"]:
        raise FreezeError("frozen snapshot hash mismatch")
    artifacts["snapshot"] = payload
    metadata = _resolve(data_root, manifest["snapshot"]["metadata_path"])
    if sha256_file(metadata) != manifest["snapshot"]["metadata_sha256"]:
        raise FreezeError("frozen snapshot metadata hash mismatch")
    artifacts["snapshot_metadata"] = metadata
    backtest = _resolve(data_root, manifest["backtest_manifest"]["path"])
    if sha256_file(backtest) != manifest["backtest_manifest"]["sha256"]:
        raise FreezeError("frozen backtest manifest hash mismatch")
    artifacts["backtest_manifest"] = backtest
    collection_archive = _resolve(data_root, manifest["collection_archive"]["path"])
    collection_run = _resolve(data_root, manifest["collection_archive"]["run_path"])
    if sha256_file(collection_archive) != manifest["collection_archive"]["sha256"]:
        raise FreezeError("frozen collection archive hash mismatch")
    if sha256_file(collection_run) != manifest["collection_archive"]["run_sha256"]:
        raise FreezeError("frozen collection run hash mismatch")
    artifacts["collection_archive"] = collection_archive
    artifacts["collection_run"] = collection_run
    for label, entry in manifest["identities"].items():
        if label == "combined_sha256":
            continue
        identity_path = _resolve(data_root, entry["path"])
        if sha256_file(identity_path) != entry["sha256"]:
            raise FreezeError(f"frozen identity map hash mismatch: {label}")
        active_identity = _resolve(data_root, entry["active_path"])
        if sha256_file(active_identity) != entry["sha256"]:
            raise FreezeError(f"active identity map differs from freeze: {label}")
        artifacts[f"identity_{label}"] = identity_path
    combined = canonical_hash(
        {
            "teams": manifest["identities"]["teams"]["sha256"],
            "aliases": manifest["identities"]["aliases"]["sha256"],
            "canonical_teams": manifest["identities"]["canonical_teams"]["sha256"],
        }
    )
    if combined != manifest["identities"]["combined_sha256"]:
        raise FreezeError("combined identity map hash mismatch")
    frozen_config = _resolve(data_root, manifest["configuration"]["path"])
    if sha256_file(frozen_config) != manifest["configuration"]["sha256"]:
        raise FreezeError("frozen configuration hash mismatch")
    active_config = Path(manifest["configuration"]["active_path"])
    if not active_config.is_absolute():
        if project_root is None:
            raise FreezeError("project root is required to verify active configuration")
        active_config = project_root / active_config
    if sha256_file(active_config) != manifest["configuration"]["sha256"]:
        raise FreezeError("active configuration differs from freeze")
    artifacts["configuration"] = frozen_config
    for label, entry in manifest["governance"].items():
        governance_path = _resolve(data_root, entry["path"])
        if sha256_file(governance_path) != entry["sha256"]:
            raise FreezeError(f"frozen governance artifact mismatch: {label}")
        artifacts[f"governance_{label}"] = governance_path
    if project_root is not None:
        source_files = [
            project_root / "src" / name
            for name in ("model.py", "services.py", "operations.py", "freeze.py", "identity.py", "collection_shadow.py")
        ]
        current_source_hash = canonical_hash({path.name: sha256_file(path) for path in source_files})
        if current_source_hash != manifest["code"]["source_sha256"]:
            raise FreezeError("serving source code differs from frozen code")
    if (
        version("lol-predictor") != manifest["code"]["lol_predictor_version"]
        or version("predictor-core") != manifest["code"]["predictor_core_version"]
    ):
        raise FreezeError("installed package versions differ from frozen versions")
    return manifest, artifacts
