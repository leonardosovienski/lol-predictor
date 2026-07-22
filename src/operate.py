"""Gated LoL moneyline operation; paper mode is the default."""
import argparse,json
from .betting import go_gate,record_bet
from .predict import run

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument('team_a'); p.add_argument('team_b')
    p.add_argument('--format',default='bo3',choices=['bo1','bo3','bo5']); p.add_argument('--selection',required=True); p.add_argument('--odds',type=float,required=True)
    p.add_argument('--bankroll',type=float,default=1000); p.add_argument('--event-id'); p.add_argument('--real',action='store_true'); p.add_argument('--approval-file')
    a=p.parse_args(argv); pred=run(a.team_a,a.team_b,fmt=a.format)
    if a.selection not in (a.team_a,a.team_b): p.error('--selection deve ser exatamente team_a ou team_b')
    prob=pred['prob_team_a'] if a.selection==a.team_a else pred['prob_team_b']
    bet=record_bet(selection=a.selection,prob_model=prob,decimal_odds=a.odds,
                   bankroll=a.bankroll,real=a.real,event_id=a.event_id,
                   approval_path=a.approval_file,
                   team_a=a.team_a,team_b=a.team_b,format=a.format)
    print(json.dumps({'gate':go_gate(),'bet':bet},ensure_ascii=False,indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())
