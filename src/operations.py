"""Canonical operational commands for the LoL domain."""

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

from .data.ingestion import ConditionalDownloader, IngestionError, SnapshotStore, assert_fresh_snapshot
from .data.polymarket_provider import PolymarketProvider
from .freeze import (
    FreezeError,
    canonical_hash,
    load_current_freeze,
    sha256_file,
    snapshot_partitions,
    write_backtest_manifest,
)
from .freeze import (
    publish_freeze as create_freeze,
)
from .h4_gate import H4Error
from .settings import Settings


class OperationalError(RuntimeError):
    """A runtime dependency or external source prevented the operation."""


class ContractError(ValueError):
    """The requested operation or its inputs violate a declared contract."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None = None) -> str:
    return (value or utc_now()).astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def structured_log(event: str, **fields: Any) -> None:
    import sys

    print(
        json.dumps({"timestamp": _iso(), "event": event, **fields}, ensure_ascii=False, sort_keys=True), file=sys.stderr
    )


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(raw, path)
    finally:
        if os.path.exists(raw):
            os.unlink(raw)


def _state_path(settings: Settings, command: str) -> Path:
    return settings.data_root / ".idem_state" / f"{command}.json"


def _write_state(settings: Settings, command: str, **value: Any) -> None:
    _atomic_json(_state_path(settings, command), {"command": command, "completed_at": _iso(), **value})


def _read_state(settings: Settings, command: str) -> dict[str, Any]:
    try:
        value = json.loads(_state_path(settings, command).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def ingest(settings: Settings, source: str, url: str | None = None) -> dict[str, Any]:
    """Fetch a source through its bounded adapter and publish an immutable snapshot."""
    if source == "riot":
        raise OperationalError("Riot esports provider is unavailable by contract")
    if source == "pandascore":
        raise ContractError("PandaScore historical ingestion requires an explicit date range and is shadow-only")
    if source not in {"oracles", "oracles_elixir"}:
        raise ContractError(f"unknown ingestion source: {source}")
    target = url or str(settings.oracle_primary_url)
    store = SnapshotStore(settings.data_root / "ingestion")
    status, metadata = ConditionalDownloader(store).fetch(target)
    digest = None if metadata is None else metadata.get("sha256")
    _write_state(settings, "ingest", source=source, source_url=target, input_hash=digest, result=status)
    return {"status": status, "source": source, "snapshot_hash": digest, "artifact": str(store.pointer)}


def publish_snapshot(settings: Settings) -> dict[str, Any]:
    """Validate the already atomically published snapshot without duplicating it."""
    root = settings.data_root / "ingestion"
    metadata = assert_fresh_snapshot(root, max_age_hours=settings.max_snapshot_staleness_hours)
    digest = str(metadata["sha256"])
    previous = _read_state(settings, "publish-snapshot")
    status = "SKIPPED" if previous.get("input_hash") == digest else "PUBLISHED"
    from .collection_shadow import archive_snapshot

    payload = SnapshotStore(root).current_payload()
    if payload is None:
        raise OperationalError("current snapshot payload is missing")
    shadow = archive_snapshot(
        data_root=settings.data_root, project_root=settings.project_root, payload=payload, metadata=metadata
    )
    _write_state(settings, "publish-snapshot", input_hash=digest, result=status)
    return {"status": status, "snapshot_hash": digest, "artifact": str(payload), "collection_shadow": shadow}


def collect_holdout(settings: Settings, horizon_hours: int = 168) -> dict[str, Any]:
    """Collect prospective inputs without exposing them to snapshot/backtest/freeze."""
    from .holdout import collect_holdout as collect

    result = collect(settings.data_root, horizon_hours=horizon_hours)
    _write_state(settings, "collect-holdout", input_hash=result["capture_id"], result=result["status"])
    return result


def _verified_collection_archive(data_root: Path, snapshot_hash: str) -> tuple[dict[str, Any], Path]:
    report_path = data_root / "collection_archive" / "latest_run.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        archive = Path(report["archive"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ContractError("canonical collection archive is required before backtest") from exc
    if not archive.is_absolute():
        archive = (Path.cwd() / archive).resolve()
    if (
        report.get("status") != "SHADOW_VALID"
        or report.get("snapshot_sha256") != snapshot_hash
        or not archive.is_file()
        or int(report.get("accepted", 0)) < 1
    ):
        raise ContractError("canonical collection archive is invalid, empty, quarantined, or stale")
    return report, archive


def backtest(settings: Settings, snapshot: Path | None = None) -> dict[str, Any]:
    root = settings.data_root / "ingestion"
    metadata = assert_fresh_snapshot(root, max_age_hours=settings.max_snapshot_staleness_hours)
    payload = snapshot or SnapshotStore(root).current_payload()
    if payload is None or not payload.is_file():
        raise OperationalError("current snapshot payload is missing")
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    if digest != metadata["sha256"]:
        raise ContractError("snapshot payload does not match current metadata")
    archive_report, archive_path = _verified_collection_archive(settings.data_root, digest)
    config_path = (
        settings.config_path if settings.config_path.is_absolute() else settings.project_root / settings.config_path
    )
    processing = {
        "config_sha256": sha256_file(config_path),
        "model_code_sha256": sha256_file(settings.project_root / "src" / "model.py"),
        "backtest_code_sha256": sha256_file(settings.project_root / "scripts" / "backtest_walkforward.py"),
        "canonical_teams_sha256": sha256_file(settings.data_root / "canonical_teams.json"),
        "collection_archive_sha256": sha256_file(archive_path),
        "collection_run_sha256": canonical_hash(archive_report),
    }
    input_hash = canonical_hash({"snapshot_sha256": digest, **processing})
    outputs = [
        settings.data_root / name
        for name in ("ratings.json", "calibration.json", "walkforward_summary.json", "backtest_manifest.json")
    ]
    previous = _read_state(settings, "backtest")
    if previous.get("input_hash") == input_hash and all(path.is_file() for path in outputs):
        return {"status": "SKIPPED", "snapshot_hash": digest, "artifacts": [str(path) for path in outputs]}

    from scripts import backtest_walkforward

    try:
        partitions = snapshot_partitions(payload)
    except FreezeError as exc:
        raise ContractError(str(exc)) from exc
    rc = backtest_walkforward.main(
        [
            "--snapshot",
            str(payload),
            "--data-root",
            str(settings.data_root),
            "--oos-cutoff",
            partitions["oos_cutoff"],
        ]
    )
    if rc not in (None, 0):
        raise OperationalError(f"backtest failed with exit code {rc}")
    derived = outputs[:3]
    if not all(path.is_file() for path in derived):
        raise OperationalError("backtest did not produce all required artifacts")
    store = SnapshotStore(root)
    metadata_path = store.current_payload().parent / "metadata.json"  # type: ignore[union-attr]
    write_backtest_manifest(
        data_root=settings.data_root,
        snapshot_payload=payload,
        snapshot_metadata=metadata_path,
        snapshot_hash=digest,
        period_start=partitions["period_start"],
        period_end=partitions["period_end"],
        oos_cutoff=partitions["oos_cutoff"],
        partition_hashes=partitions["partition_hashes"],
        processing=processing,
    )
    _write_state(
        settings,
        "backtest",
        input_hash=input_hash,
        snapshot_hash=digest,
        artifacts=[str(path) for path in outputs],
    )
    return {"status": "SUCCEEDED", "snapshot_hash": digest, "artifacts": [str(path) for path in outputs]}


def publish_freeze(settings: Settings) -> dict[str, Any]:
    config_path = settings.config_path
    if not config_path.is_absolute():
        config_path = settings.project_root / config_path
    previous = _read_state(settings, "publish-freeze")
    try:
        manifest = create_freeze(
            data_root=settings.data_root,
            project_root=settings.project_root,
            config_path=config_path,
        )
    except FreezeError as exc:
        raise ContractError(str(exc)) from exc
    status = "SKIPPED" if previous.get("input_hash") == manifest["manifest_hash"] else "PUBLISHED"
    _write_state(settings, "publish-freeze", input_hash=manifest["manifest_hash"], freeze_id=manifest["freeze_id"])
    return {
        "status": status,
        "freeze_id": manifest["freeze_id"],
        "manifest_hash": manifest["manifest_hash"],
        "artifact": str(settings.data_root / "current_freeze.json"),
    }


def settle(settings: Settings, results: Path, signals: Path | None = None) -> dict[str, Any]:
    from scripts.settle_h4_signals import settle as settle_signals

    signals = signals or settings.data_root / "shadow" / "h4_signals.jsonl"
    try:
        changed = settle_signals(signals, results)
    except (H4Error, OSError, ValueError, json.JSONDecodeError) as exc:
        raise ContractError(str(exc)) from exc
    artifact = settings.data_root / "settlement" / "latest.json"
    report = {"status": "SUCCEEDED", "settled": changed, "signals": str(signals), "processed_at": _iso()}
    _atomic_json(artifact, report)
    input_hash = hashlib.sha256(results.read_bytes()).hexdigest()
    _write_state(settings, "settle", input_hash=input_hash, settled=changed)
    return {**report, "artifact": str(artifact)}


def collect_shadow(settings: Settings, horizon_hours: int = 72, output: Path | None = None) -> dict[str, Any]:
    from scripts.collect_polymarket_upcoming import collect

    if not 1 <= horizon_hours <= 168:
        raise ContractError("horizon-hours must be between 1 and 168")
    output = output or settings.data_root / "shadow" / "h4_signals.jsonl"
    try:
        report = collect(output, horizon_hours)
    except (DataUnavailableError, H4Error, OSError, ValueError) as exc:
        raise OperationalError(str(exc)) from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    output.touch(exist_ok=True)
    _write_state(settings, "collect-shadow", result=report, artifact=str(output))
    return {"status": "SUCCEEDED", **report, "artifact": str(output)}


def health(settings: Settings, *, connectivity: bool | None = None) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    artifacts: dict[str, Any] = {}

    def check(name: str, result: str, details: Any) -> None:
        checks.append({"name": name, "result": result, "details": details, "timestamp": _iso()})

    ingestion_root = settings.data_root / "ingestion"
    try:
        metadata = assert_fresh_snapshot(ingestion_root, max_age_hours=settings.max_snapshot_staleness_hours)
        artifacts["snapshot"] = {"hash": metadata["sha256"], "staleness_hours": metadata["staleness_hours"]}
        check("snapshot", "PASS", "present, fresh and hash-verified")
    except IngestionError as exc:
        check("snapshot", "FAIL", str(exc))

    ratings = settings.data_root / "ratings.json"
    try:
        values = json.loads(ratings.read_text(encoding="utf-8"))
        if not isinstance(values, dict) or not values:
            raise ValueError("ratings must be a non-empty object")
        digest = hashlib.sha256(ratings.read_bytes()).hexdigest()
        artifacts["ratings"] = {"hash": digest, "teams": len(values)}
        check("ratings", "PASS", f"{len(values)} teams")
    except (OSError, ValueError) as exc:
        check("ratings", "FAIL", str(exc))

    try:
        freeze, _freeze_artifacts = load_current_freeze(settings.data_root, settings.project_root)
        artifacts["freeze"] = {"freeze_id": freeze["freeze_id"], "manifest_hash": freeze["manifest_hash"]}
        check("freeze", "PASS", "current freeze and every referenced artifact are verified")
    except FreezeError as exc:
        check("freeze", "FAIL", str(exc))

    archive_report = settings.data_root / "collection_archive" / "latest_run.json"
    try:
        report = json.loads(archive_report.read_text(encoding="utf-8"))
        if report.get("status") != "SHADOW_VALID" or not Path(report["archive"]).is_file():
            raise ValueError("collection archive reports quarantined events or is missing")
        artifacts["collection_archive"] = {
            "snapshot_hash": report["snapshot_sha256"],
            "accepted": report["accepted"],
        }
        check("collection_archive", "PASS", "core ObservationEnvelope shadow archive is valid")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        initialized = bool(_read_state(settings, "publish-snapshot"))
        check(
            "collection_archive",
            "WARN" if initialized else "PASS",
            str(exc) if initialized else "shadow not initialized",
        )

    settings.data_root.mkdir(parents=True, exist_ok=True)
    free_mb = shutil.disk_usage(settings.data_root).free // (1024 * 1024)
    check(
        "disk",
        "PASS" if free_mb >= settings.min_free_disk_mb else "FAIL",
        {"free_mb": free_mb, "required_mb": settings.min_free_disk_mb},
    )

    stale_locks = []
    runtime = settings.ops_runtime_root
    if runtime.exists():
        cutoff = utc_now().timestamp() - settings.max_job_timeout_seconds
        stale_locks = [str(path) for path in runtime.rglob("*.lock") if path.stat().st_mtime < cutoff]
    check("locks", "WARN" if stale_locks else "PASS", {"stale": stale_locks})

    if settings.health_check_connectivity if connectivity is None else connectivity:
        try:
            ok = PolymarketProvider(timeout=settings.health_connectivity_timeout_seconds).health_check()
            check("polymarket", "PASS" if ok else "WARN", "reachable" if ok else "unavailable")
        except Exception as exc:  # health must report, never hide all local state
            check("polymarket", "WARN", type(exc).__name__)

    degraded = any(item["result"] in {"FAIL", "WARN"} for item in checks)
    return {"status": "DEGRADED" if degraded else "HEALTHY", "checks": checks, "artifacts": artifacts}
