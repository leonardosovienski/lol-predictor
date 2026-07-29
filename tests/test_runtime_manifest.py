from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pytest

from src.runtime_manifest import RuntimeManifestError, build_runtime_manifest, write_runtime_manifest


def _artifacts(root):
    data = root / "data"
    data.mkdir()
    values = {
        "ratings.json": b'{"T1": 1600.0}\n',
        "calibration.json": b'{"LCK": {"media_total_kills": 25.0, "sigma": 6.0}}\n',
        "lol.db": b"sqlite-fixture",
        "teams_lol.json": b'{"teams": []}\n',
    }
    for name, value in values.items():
        (data / name).write_bytes(value)
    return values


def test_manifest_hashes_all_runtime_artifacts(tmp_path):
    values = _artifacts(tmp_path)
    manifest = write_runtime_manifest(
        tmp_path, generated_at=datetime(2026, 7, 29, tzinfo=timezone.utc))
    assert manifest["generated_at_utc"] == "2026-07-29T00:00:00Z"
    assert manifest["artifacts"]["calibration"] == hashlib.sha256(
        values["calibration.json"]).hexdigest()
    persisted = json.loads((tmp_path / "data" / "runtime_artifacts.json").read_text())
    assert persisted == manifest


def test_manifest_fails_closed_when_an_artifact_is_missing(tmp_path):
    _artifacts(tmp_path)
    (tmp_path / "data" / "calibration.json").unlink()
    with pytest.raises(RuntimeManifestError, match="calibration.json"):
        build_runtime_manifest(tmp_path)
