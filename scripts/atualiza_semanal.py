"""Observable Task Scheduler entrypoint for the weekly LoL refresh."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import subprocess
import sys
from pathlib import Path

# `pythonw.exe` (executavel de toda tarefa agendada) nao tem console: um
# processo de console filho ganharia janela VISIVEL na tela do dono.
# Saida ja e capturada, entao a flag nao esconde nada.
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT.parent
RUNNER = WORKSPACE / "tools" / "operational_runner.py"
PAYLOAD = Path(__file__).with_name("atualiza_semanal_payload.py")
LOG_DIR = ROOT / "logs" / "operations"
_GIT_RUN = subprocess.run


def _sha256(path: Path) -> str:
    if not path.is_file():
        raise RuntimeError(f"provenance input is missing: {path.name}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    result = _GIT_RUN(["git", "-C", str(ROOT), *args], text=True,
                      capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError("project Git provenance is unavailable")
    return result.stdout.strip()


def consumer_provenance() -> dict[str, object]:
    vendor = ROOT / "vendor" / "predictor_core"
    return {
        "project_name": "lol-predictor",
        "project_commit": _git("rev-parse", "HEAD"),
        "project_branch": _git("branch", "--show-current") or None,
        "project_worktree_clean": not bool(_git("status", "--porcelain")),
        "predictor_core_version": (vendor / "VERSION").read_text(encoding="utf-8").strip(),
        "predictor_core_hash": _sha256(vendor / "CORE_MANIFEST.json"),
        "input_hashes": {
            "ratings": _sha256(ROOT / "data" / "ratings.json"),
            "calibration": _sha256(ROOT / "data" / "calibration.json"),
            "database": _sha256(ROOT / "data" / "lol.db"),
            "teams": _sha256(ROOT / "data" / "teams_lol.json"),
        },
        "artifact_schema_version": "operational-envelope/1.1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "task_name": "lol-ratings-semanal",
        "artifact_kind": "ratings_refresh",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the LoL weekly refresh with the operational envelope.")
    parser.parse_args(argv)
    if not RUNNER.is_file() or not PAYLOAD.is_file():
        print("operational entrypoint is incomplete", file=sys.stderr)
        return 3
    try:
        metadata = json.dumps(consumer_provenance(), ensure_ascii=False, sort_keys=True)
    except (OSError, RuntimeError) as exc:
        print(f"consumer provenance unavailable: {exc}", file=sys.stderr)
        return 3
    command = [
        sys.executable, str(RUNNER), "run", "--task", "lol-ratings-semanal",
        "--project", "lol-predictor", "--cwd", str(ROOT),
        "--log", str(LOG_DIR / "lol-ratings-semanal.log"),
        "--event-log", str(LOG_DIR / "events.jsonl"),
        "--heartbeat", str(LOG_DIR / "lol-ratings-semanal.heartbeat.json"),
        "--expected-artifact", str(ROOT / "data" / "ratings.json"),
        "--timeout", "9000", "--partial-exit-code", "10",
        "--consumer-provenance-json", metadata, "--",
        sys.executable, "-X", "utf8", str(PAYLOAD),
    ]
    return subprocess.run(command, cwd=ROOT, check=False,
                          creationflags=_NO_WINDOW).returncode


if __name__ == "__main__":
    raise SystemExit(main())
