"""Observable Task Scheduler entrypoint for the weekly LoL refresh."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT.parent
RUNNER = WORKSPACE / "tools" / "operational_runner.py"
PAYLOAD = Path(__file__).with_name("atualiza_semanal_payload.py")
LOG_DIR = ROOT / "logs" / "operations"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the LoL weekly refresh with the operational envelope.")
    parser.parse_args(argv)
    if not RUNNER.is_file() or not PAYLOAD.is_file():
        print("operational entrypoint is incomplete", file=sys.stderr)
        return 3
    command = [
        sys.executable, str(RUNNER), "run", "--task", "lol-ratings-semanal",
        "--project", "lol-predictor", "--cwd", str(ROOT),
        "--log", str(LOG_DIR / "lol-ratings-semanal.log"),
        "--event-log", str(LOG_DIR / "events.jsonl"),
        "--heartbeat", str(LOG_DIR / "lol-ratings-semanal.heartbeat.json"),
        "--expected-artifact", str(ROOT / "data" / "ratings.json"),
        "--timeout", "9000", "--partial-exit-code", "10", "--",
        sys.executable, "-X", "utf8", str(PAYLOAD),
    ]
    return subprocess.run(command, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
