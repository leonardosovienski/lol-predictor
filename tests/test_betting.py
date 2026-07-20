import json,pytest
from src.betting import go_gate,kelly_stake,record_bet,settle_bet

def test_paper_bet_and_idempotent_settlement(tmp_path):
    log=tmp_path/'bets.jsonl'; bet=record_bet(selection='T1',prob_model=.6,decimal_odds=2,bankroll=1000,path=log)
    assert bet['stake']==20 and bet['real'] is False
    first=settle_bet(bet,True,path=log); second=settle_bet(bet,False,path=log)
    assert first==second and first['pnl']==20

def test_real_bet_fails_closed_without_approved_sample(tmp_path):
    with pytest.raises(PermissionError):
        record_bet(selection='T1',prob_model=.6,decimal_odds=2,bankroll=1000,
                   real=True,path=tmp_path/'bets',gate_path=tmp_path/'missing')

def test_gate_requires_sample_and_calendar(tmp_path):
    gate=tmp_path/'gate.json'; gate.write_text(json.dumps({'verdict':'GO','matured_matches':50,
      'required_matured_matches':50,'calendar_days':30,'required_calendar_days':30}))
    assert go_gate(gate)['decision']=='GO'
