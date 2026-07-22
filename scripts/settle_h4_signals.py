"""Persist official outcomes onto an existing frozen H4 signal cohort."""
from __future__ import annotations
import argparse, json, os, tempfile, sys
from datetime import datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.h4_gate import H4Error  # noqa: E402

def _dt(value):
    value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if value.tzinfo is None: raise H4Error("timestamp de resultado sem timezone")
    return value

def settle(signals: Path, results: Path) -> int:
    supplied = json.loads(results.read_text(encoding="utf-8")).get("results", [])
    by_id = {row.get("canonical_event_id"): row for row in supplied}
    rows = [json.loads(line) for line in signals.read_text(encoding="utf-8").splitlines() if line.strip()]
    changed = 0
    for row in rows:
        result = by_id.get(row.get("canonical_event_id"))
        if result is None: continue
        if result.get("result") not in (0, 1) or result.get("source") not in {"oracle-elixir", "riot-esports"}:
            raise H4Error("resultado oficial inválido")
        available = _dt(result.get("result_available_at")); start = _dt(row["event_start_at"])
        if available < start: raise H4Error("resultado disponível antes do evento")
        if row.get("settlement_status") == "OFFICIAL":
            if row.get("result") != result["result"]: raise H4Error("correção de resultado exige nova coorte")
            continue
        row.update({"result": result["result"], "result_available_at": available.isoformat(),
                    "result_source": result["source"], "settlement_status": "OFFICIAL"}); changed += 1
    fd, name = tempfile.mkstemp(prefix=".h4-settle-", suffix=".tmp", dir=signals.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as out:
            for row in rows: out.write(json.dumps(row, ensure_ascii=False, sort_keys=True)+"\n")
            out.flush(); os.fsync(out.fileno())
        os.replace(name, signals)
    finally:
        if os.path.exists(name): os.unlink(name)
    return changed

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("--signals",type=Path,default=ROOT/"data/shadow/h4_signals.jsonl"); p.add_argument("--results",type=Path,required=True); a=p.parse_args(argv)
    try: print(json.dumps({"settled":settle(a.signals,a.results)}))
    except (H4Error,OSError,ValueError,json.JSONDecodeError) as e: print(str(e),file=sys.stderr); return 2
    return 0
if __name__=="__main__": raise SystemExit(main())
