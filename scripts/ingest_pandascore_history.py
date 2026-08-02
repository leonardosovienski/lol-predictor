import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
from src.data.pandascore_provider import PandaScoreProvider
from src.data.historical_shadow import connect,ingest,report
def main():
 p=argparse.ArgumentParser();p.add_argument('--from-date',default='2024-01-01');p.add_argument('--to-date',default='2024-12-31');p.add_argument('--max-pages',type=int);a=p.parse_args();c=connect(ROOT/'data'/'pandascore_history_shadow.db');n=ingest(c,PandaScoreProvider().iter_past(from_date=a.from_date,to_date=a.to_date,max_pages=a.max_pages));out=report(c);out['imported_this_run']=n;print(json.dumps(out,ensure_ascii=False,sort_keys=True))
if __name__=='__main__':main()
