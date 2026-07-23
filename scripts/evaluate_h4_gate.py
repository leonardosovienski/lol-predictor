"""Evaluate only a complete, frozen H4 prospective-shadow cohort."""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.h4_gate import H4Error, evaluate  # noqa: E402

def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--signals", type=Path, default=ROOT / "data/shadow/h4_signals.jsonl")
    p.add_argument("--output", type=Path, default=ROOT / "data/market_gate.json")
    a = p.parse_args(argv)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    try: print(json.dumps(evaluate(a.signals, ROOT / "data/trials.json", a.output, code_commit=commit,
                                   closure_path=ROOT / "data" / "h4_v2_closure.json"), ensure_ascii=False, sort_keys=True))
    except H4Error as exc: print(str(exc), file=sys.stderr); return 2
    return 0
if __name__ == "__main__": raise SystemExit(main())
