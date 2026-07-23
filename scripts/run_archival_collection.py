"""Run the isolated archival collection from a supplied official-sports inbox."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from src.collection_only import CollectionError, collect, health
def main(argv=None):
 p=argparse.ArgumentParser(); p.add_argument("--input",type=Path); p.add_argument("--health",action="store_true"); a=p.parse_args(argv)
 try:
  root=ROOT/"data/collection_only"; run=json.loads((ROOT/"data/collection_only_run.json").read_text(encoding="utf-8"))
  if a.health: print(json.dumps(health(root),ensure_ascii=False,sort_keys=True)); return 0
  rows=[] if a.input is None else json.loads(a.input.read_text(encoding="utf-8")).get("events",[])
  print(json.dumps(collect(root,run,rows),ensure_ascii=False,sort_keys=True))
 except (OSError,ValueError,CollectionError) as e: print(str(e),file=sys.stderr); return 2
 return 0
if __name__=="__main__": raise SystemExit(main())
