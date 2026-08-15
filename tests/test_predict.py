"""Serving (src/predict.py) — 3 confrontos, log isolado, PredictionPoint."""
import json
from datetime import datetime, timezone

import pytest

import src.model as model_module
from src import predict

PARES = [("T1", "Gen.G"), ("Bilibili Gaming", "G2 Esports"),
         ("Hanwha Life Esports", "JD Gaming")]


@pytest.fixture(autouse=True)
def _isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("LOL_ADHOC_LOG_PATH", str(tmp_path / "pred.jsonl"))
    monkeypatch.setenv("PREDICTOR_EVENTS_PATH", str(tmp_path / "events.jsonl"))
    # Unit tests here exercise Elo serving; freshness is covered independently.
    monkeypatch.setattr(predict, "assert_fresh_snapshot", lambda *_args, **_kwargs: {})
    # Redireciona ROOT (via model_module, mesmo padrão de
    # test_kills_uses_published_league_calibration em test_model.py) pra um
    # diretório sem data/ratings.json nem data/calibration.json: estes
    # testes têm que passar igual num checkout limpo (como o CI roda) e num
    # checkout com dado real vivido/calibrado (como uma máquina de
    # desenvolvimento que já rodou a ingestão) — nunca depender de qual dos
    # dois é o caso.
    monkeypatch.setattr(model_module, "ROOT", tmp_path)
    yield


@pytest.mark.parametrize("a,b", PARES)
def test_saida_consistente(a, b):
    r = predict.run(a, b, fmt="bo3")
    assert abs(r["prob_team_a"] + r["prob_team_b"] - 1.0) < 1e-6
    assert 15 <= r["total_abates_projetado"] <= 40
    assert 2.0 <= r["mapas_esperados"] <= 3.0


def test_carimbo_prediction_point_por_formato():
    now = datetime(2026, 7, 10, 22, 0, tzinfo=timezone.utc)
    r3 = predict.run("T1", "Gen.G", fmt="bo3", now=now)
    assert r3["matures_at"] == "2026-07-11T00:30:00+00:00"    # +2h30
    r5 = predict.run("T1", "Gen.G", fmt="bo5", now=now)
    assert r5["matures_at"] == "2026-07-11T02:00:00+00:00"    # +4h


def test_cli_json_valido(capsys):
    rc = predict.main(["T1", "Gen.G", "--format", "bo3", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert {"prob_team_a", "prob_team_b", "total_abates_projetado",
            "prob_underdog", "kills"} <= set(out)


def test_cli_market_kills_com_linha(capsys):
    # --kills-league é exigido sempre que data/calibration.json existir (gate
    # deliberado, ver test_kills_uses_published_league_calibration em
    # test_model.py) — passar explicitamente evita que este teste dependa de
    # o arquivo, gitignored e específico de cada máquina, existir ou não.
    rc = predict.main(["T1", "Gen.G", "--market", "kills",
                       "--kills-line", "26.5", "--kills-league", "LCK", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["market"] == "kills"
    assert out["kills"]["line"] == 26.5


def test_cli_time_desconhecido_sai_2():
    assert predict.main(["Timeburgo", "T1", "--json"]) == 2


def test_log_default_nao_e_o_ledger_oficial(monkeypatch):
    # sem override, o CLI ad hoc NUNCA pode apontar pro ledger versionado
    monkeypatch.delenv("LOL_ADHOC_LOG_PATH", raising=False)
    path = predict._log_path()
    assert path.name == "predictions_adhoc.jsonl"
    assert path.name != "predictions.jsonl"


def test_legacy_official_log_override_is_ignored(monkeypatch):
    monkeypatch.delenv("LOL_ADHOC_LOG_PATH", raising=False)
    monkeypatch.setenv("PREDICTIONS_LOG_PATH", str(predict.ROOT / "data" / "predictions.jsonl"))
    assert predict._log_path().name == "predictions_adhoc.jsonl"


def test_ad_hoc_log_cannot_target_official_ledger(monkeypatch):
    monkeypatch.setenv("LOL_ADHOC_LOG_PATH", str(predict.ROOT / "data" / "predictions.jsonl"))
    with pytest.raises(ValueError, match="official ledger"):
        predict._log_path()
