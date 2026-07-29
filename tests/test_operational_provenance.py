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


def test_refresh_consumer_provenance_is_additive_and_hashed(tmp_path) -> None:
    module = _entrypoint()
    module.ROOT = tmp_path
    module._git = lambda *_args: "0" * 40
    (tmp_path / "data").mkdir()
    for name in ("ratings.json", "lol.db", "teams_lol.json"):
        (tmp_path / "data" / name).write_bytes(name.encode())
    (tmp_path / "vendor" / "predictor_core").mkdir(parents=True)
    (tmp_path / "vendor" / "predictor_core" / "VERSION").write_text("test", encoding="utf-8")
    (tmp_path / "vendor" / "predictor_core" / "CORE_MANIFEST.json").write_text("{}", encoding="utf-8")
    metadata = module.consumer_provenance()
    assert metadata["project_name"] == "lol-predictor"
    assert metadata["artifact_kind"] == "ratings_refresh"
    assert metadata["artifact_schema_version"] == "operational-envelope/1.1"
    assert all(len(value) == 64 for value in metadata["input_hashes"].values())
    assert "tools_content_hash" not in metadata
