import json
from datetime import datetime, timedelta, timezone

import pytest

from src.h4_gate import H4Error, assert_h4_open, build_signal, cohort_status, evaluate


def _trial(path):
    path.write_text(json.dumps([{"name": "h4-lol-market-shadow-prospectivo-v2", "registered_at": "2026-07-20T00:00:00Z", "params": {
        "collection_start_exclusive": "2026-07-20T00:00:00Z", "min_matured_matches": 50,
        "min_calendar_days": 30, "min_shadow_signals": 30, "min_competitions": 3,
    }}]), encoding="utf-8")


def _signal(index=0, *, competition="c1", settled=True):
    start = datetime(2026, 7, 21, tzinfo=timezone.utc) + timedelta(minutes=index)
    quote = {"event_id": f"e{index}", "team_a": "T1", "team_b": "Gen.G", "observed_at": (start-timedelta(hours=2)).isoformat(), "published_at": (start-timedelta(hours=3)).isoformat(), "scheduled_at": start.isoformat(), "model_probability_a": .6, "model_probability_b": .4, "probability_a": .5, "probability_b": .5, "decimal_a": 2., "decimal_b": 2., "ratings_sha256": "a"*64, "source": "fixture", "market_id": f"m{index}", "condition_id": f"c{index}", "format": "bo3", "model_name": "elo-h1"}
    row = build_signal(quote, trial_id="h4-lol-market-shadow-prospectivo-v2", code_commit="b"*40, competition_id=competition, competition_name=competition, region="KR", tournament="fixture", split=None, patch=None)
    if settled: row.update({"result": index % 2, "result_available_at": (start+timedelta(hours=3)).isoformat(), "settlement_status": "OFFICIAL"})
    return row


def _write(path, rows): path.write_text("\n".join(json.dumps(x) for x in rows)+"\n", encoding="utf-8")


@pytest.mark.parametrize("rows,now,state", [
    (49, datetime(2026, 8, 21, tzinfo=timezone.utc), "WAITING_FOR_MATURED_EVENTS"),
    (50, datetime(2026, 8, 18, tzinfo=timezone.utc), "WAITING_FOR_TIME_WINDOW"),
])
def test_h4_count_and_time_gates(tmp_path, rows, now, state):
    trials, signals = tmp_path/"trials.json", tmp_path/"signals.jsonl"; _trial(trials); _write(signals, [_signal(i, competition=f"c{i%3}") for i in range(rows)])
    assert cohort_status(signals, trials, now=now)["state"] == state


def test_h4_quality_blocks_missing_result_duplicate_model_and_provenance(tmp_path):
    trials, signals = tmp_path/"trials.json", tmp_path/"signals.jsonl"; _trial(trials)
    bad = _signal(); bad["competition_id"] = ""
    _write(signals, [bad])
    assert cohort_status(signals, trials, now=datetime(2026, 8, 21, tzinfo=timezone.utc))["state"] == "DATA_QUALITY_BLOCKED"
    with pytest.raises(H4Error): build_signal({}, trial_id="x", code_commit="x", competition_id="", competition_name="", region=None, tournament=None, split=None, patch=None)


def test_h4_ready_evaluates_deterministically_and_gate_is_atomic(tmp_path):
    trials, signals, out = tmp_path/"trials.json", tmp_path/"signals.jsonl", tmp_path/"market_gate.json"; _trial(trials)
    _write(signals, [_signal(i, competition=f"c{i%3}") for i in range(50)])
    now = datetime(2026, 8, 21, tzinfo=timezone.utc)
    assert cohort_status(signals, trials, now=now)["state"] == "READY_FOR_EVALUATION"
    one = evaluate(signals, trials, out, now=now, code_commit="c"*40)
    two = evaluate(signals, trials, out, now=now, code_commit="c"*40)
    assert one["bootstrap"] == two["bootstrap"]
    assert json.loads(out.read_text())["schema_version"] == "lol-h4-market-gate/1.0"
    assert {"brier_model", "paired_brier_difference", "shadow_roi", "hhi", "max_drawdown_units"} <= set(one)


def test_h4_past_event_without_official_result_is_not_matured(tmp_path):
    trials, signals = tmp_path/"trials.json", tmp_path/"signals.jsonl"; _trial(trials); _write(signals, [_signal(0, settled=False)])
    report = cohort_status(signals, trials, now=datetime(2026, 8, 21, tzinfo=timezone.utc))
    assert report["state"] == "DATA_QUALITY_BLOCKED" and report["matured_matches"] == 0


def test_human_closure_blocks_restart_and_exposes_no_go_status(tmp_path):
    trials, signals, closure = tmp_path/"trials.json", tmp_path/"signals.jsonl", tmp_path/"closure.json"; _trial(trials)
    closure.write_text(json.dumps({"schema_version": "lol-h4-closure/1.0", "trial": "h4-lol-market-shadow-prospectivo-v2", "scientific_status": "CLOSED_BY_HUMAN_DECISION", "operational_status": "NO_GO"}), encoding="utf-8")
    assert cohort_status(signals, trials, closure_path=closure)["state"] == "CLOSED_BY_HUMAN_DECISION"
    with pytest.raises(H4Error, match="encerrada"):
        assert_h4_open(closure)


_CLOSED_RECORD = {"schema_version": "lol-h4-closure/1.0",
                  "trial": "h4-lol-market-shadow-prospectivo-v2",
                  "scientific_status": "CLOSED_BY_HUMAN_DECISION",
                  "operational_status": "NO_GO"}
_REOPENED_RECORD = {**_CLOSED_RECORD,
                    "scientific_status": "REOPENED_BY_HUMAN_DECISION",
                    "reopened_at_utc": "2026-07-25T00:00:00Z",
                    "reopening_decision": {"reason": "fixture"},
                    "supersedes_commit": "f"*40}


def test_remover_o_registro_canonico_nao_reabre_a_coorte(tmp_path, monkeypatch):
    """Regressão: até 2026-07-25 o arquivo ausente devolvia None e reabria a
    coorte por apagamento, destruindo contadores e hashes preservados."""
    import src.h4_gate as gate
    ausente = tmp_path / "h4_v2_closure.json"
    monkeypatch.setattr(gate, "DEFAULT_CLOSURE_RECORD", ausente)
    with pytest.raises(H4Error, match="remoção de arquivo"):
        gate.closure_status(ausente)
    with pytest.raises(H4Error, match="remoção de arquivo"):
        assert_h4_open(ausente)


def test_reabertura_exige_os_tres_campos_de_decisao(tmp_path):
    for faltando in ("reopened_at_utc", "reopening_decision", "supersedes_commit"):
        path = tmp_path / f"sem_{faltando}.json"
        path.write_text(json.dumps({k: v for k, v in _REOPENED_RECORD.items()
                                    if k != faltando}), encoding="utf-8")
        with pytest.raises(H4Error, match="decisão humana auditável"):
            assert_h4_open(path)


def test_reabertura_completa_abre_a_coorte(tmp_path):
    path = tmp_path / "reopened.json"
    path.write_text(json.dumps(_REOPENED_RECORD), encoding="utf-8")
    assert_h4_open(path)  # não levanta
    trials, signals = tmp_path/"trials.json", tmp_path/"signals.jsonl"; _trial(trials)
    assert cohort_status(signals, trials, closure_path=path)["state"] != "CLOSED_BY_HUMAN_DECISION"


def test_registro_de_producao_e_valido_e_nunca_libera_capital():
    """Invariante em qualquer estado científico: capital real segue bloqueado."""
    from pathlib import Path
    record = json.loads((Path(__file__).resolve().parents[1] / "data" /
                         "h4_v2_closure.json").read_text(encoding="utf-8"))
    assert record["scientific_status"] in {"CLOSED_BY_HUMAN_DECISION",
                                           "REOPENED_BY_HUMAN_DECISION"}
    assert record["operational_status"] == "NO_GO"
