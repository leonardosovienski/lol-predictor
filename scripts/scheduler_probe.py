"""Harmless Windows Scheduler probe; never reads or writes model data."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    working_directory_ok = Path.cwd().resolve() == ROOT.resolve()
    payload = {
        "schema_version": "lol-scheduler-probe/1.0",
        "status": "SUCCEEDED" if working_directory_ok else "FAILED",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds").replace("+00:00", "Z"),
        "working_directory": str(Path.cwd().resolve()),
        "working_directory_ok": working_directory_ok,
        "entrypoint_exists": (ROOT / "scripts" / "atualiza_semanal.py").is_file(),
        "ratings_sha256": hashlib.sha256(
            (ROOT / "data" / "ratings.json").read_bytes()).hexdigest(),
        "pid": os.getpid(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True) + "\n",
                         encoding="utf-8")
    temporary.replace(args.output)
    return 0 if working_directory_ok and payload["entrypoint_exists"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
