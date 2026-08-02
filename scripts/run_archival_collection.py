"""Run the isolated archival collection from a supplied official-sports inbox."""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
from src.collection_only import CollectionError, collect, health

def _runtime_root() -> Path:
    configured = os.environ.get("LOL_COLLECTION_RUNTIME_ROOT")
    if configured: return Path(configured)
    local = os.environ.get("LOCALAPPDATA")
    if not local: raise CollectionError("LOCALAPPDATA ausente; runtime externo indisponível")
    return Path(local) / "predictor-tools" / "runtime" / "lol-predictor" / "lol-archival-collection" / "collection"

def _write_status(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps({"status": report["status"], "collection_run_id": report.get("collection_run_id")}, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)

def main(argv=None):
 p=argparse.ArgumentParser(); p.add_argument("--input",type=Path); p.add_argument("--health",action="store_true"); p.add_argument("--status-output",type=Path); a=p.parse_args(argv)
 try:
  root=_runtime_root(); run=json.loads((ROOT/"data/collection_only_run.json").read_text(encoding="utf-8"))
  if a.health: report=health(root)
  else:
   rows=[] if a.input is None else json.loads(a.input.read_text(encoding="utf-8")).get("events",[])
   report=collect(root,run,rows)
  if a.status_output: _write_status(a.status_output, report)
  print(json.dumps(report,ensure_ascii=False,sort_keys=True)); return 0
 except (OSError,ValueError,CollectionError) as e: print(str(e),file=sys.stderr); return 2
if __name__=="__main__": raise SystemExit(main())
