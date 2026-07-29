"""Immutable-in-content provenance record for regenerated local artifacts."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


RUNTIME_MANIFEST_SCHEMA = "lol-runtime-artifacts/1.0"
ARTIFACTS = {
    "ratings": "ratings.json",
    "calibration": "calibration.json",
    "database": "lol.db",
    "teams": "teams_lol.json",
}


class RuntimeManifestError(RuntimeError):
    """Required runtime artifacts are absent or cannot be attested."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_runtime_manifest(root: Path | str, *, generated_at: datetime | None = None) -> dict[str, object]:
    root = Path(root)
    data = root / "data"
    hashes: dict[str, str] = {}
    for label, filename in ARTIFACTS.items():
        path = data / filename
        if not path.is_file():
            raise RuntimeManifestError(f"runtime artifact is missing: {filename}")
        hashes[label] = _sha256(path)
    timestamp = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return {
        "schema_version": RUNTIME_MANIFEST_SCHEMA,
        "generated_at_utc": timestamp.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "artifacts": hashes,
    }


def write_runtime_manifest(root: Path | str, *, generated_at: datetime | None = None) -> dict[str, object]:
    root = Path(root)
    manifest = build_runtime_manifest(root, generated_at=generated_at)
    target = root / "data" / "runtime_artifacts.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_tmp = tempfile.mkstemp(prefix=".runtime-artifacts-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(raw_tmp, target)
    finally:
        if os.path.exists(raw_tmp):
            os.unlink(raw_tmp)
    return manifest
