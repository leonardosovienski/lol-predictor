"""Status do pré-registro H4 sem calcular resultado antes da maturação."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(ROOT))
from src.h4_gate import cohort_status  # noqa: E402


def status(quotes_path: Path, trials_path: Path,
           now: datetime | None = None) -> dict:
    return cohort_status(quotes_path, trials_path, now=now,
                         closure_path=ROOT / "data" / "h4_v2_closure.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show H4 LoL market shadow status")
    parser.add_argument("--quotes", type=Path,
                        default=ROOT / "data" / "shadow" / "h4_signals.jsonl")
    args = parser.parse_args(argv)
    print(json.dumps(status(args.quotes, ROOT / "data" / "trials.json"),
                     ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
