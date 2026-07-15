from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _entrypoint():
    spec = importlib.util.spec_from_file_location("lol_operational_provenance", ROOT / "scripts" / "atualiza_semanal.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_refresh_consumer_provenance_is_additive_and_hashed() -> None:
    metadata = _entrypoint().consumer_provenance()
    assert metadata["project_name"] == "lol-predictor"
    assert metadata["artifact_kind"] == "ratings_refresh"
    assert metadata["artifact_schema_version"] == "operational-envelope/1.1"
    assert all(len(value) == 64 for value in metadata["input_hashes"].values())
    assert "tools_content_hash" not in metadata
