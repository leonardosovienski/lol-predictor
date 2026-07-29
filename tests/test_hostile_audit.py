"""Testes hostis da auditoria final (2026-07-19).

Cobrem os bugs reais achados na auditoria de identidade/lifecycle/ratings:
KeyError com ratings_file customizado, empate persistido silenciosamente,
placar negativo, rating NaN/Inf, prediction_id desconhecido caindo em
matching por nome, e ambiguidade de substring entre teams_lol.json e
ratings.json.
"""
import json
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from src.config import clear_caches, resolve_team  # noqa: E402
from src.model import EloModel  # noqa: E402
import predict_ewc_opening as pe  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_caches(monkeypatch):
    clear_caches()
    import src.config as cfg
    monkeypatch.setattr(cfg, "load_rating_names",
                        lambda: ["LOUD", "BNK FearX", "LØS", "Dplus Kia", "Sentinels"])
    yield
    clear_caches()


# ---------- identidade ----------

def test_resolve_team_unicode_e_caixa():
    assert resolve_team("  t1  ")["name"] == "T1"
    assert resolve_team("løs")["name"] == "LØS"
    assert resolve_team("DPLUS KIA")["name"] == "Dplus Kia"


def test_resolve_team_unicode_decomposto(monkeypatch):
    import src.config as cfg
    composed = "Équipe"
    decomposed = unicodedata.normalize("NFD", composed)
    monkeypatch.setattr(cfg, "load_teams", lambda: [
        {"name": composed, "region": "LEC", "initial_elo": 1500}])
    monkeypatch.setattr(cfg, "load_rating_names", lambda: [])
    assert cfg.resolve_team(decomposed)["name"] == composed


def test_resolve_team_desconhecido_e_vazio():
    with pytest.raises(ValueError):
        resolve_team("Time Que Nao Existe FC")
    with pytest.raises(ValueError):
        resolve_team("")


def test_substring_ambigua_entre_top30_e_ratings(tmp_path, monkeypatch):
    """Um hit único no Top 30 não pode vencer silenciosamente quando
    ratings.json tem OUTRA entidade que também bate a substring."""
    import src.config as cfg
    monkeypatch.setattr(cfg, "load_teams",
                        lambda: [{"name": "Cloud9", "region": "LCS",
                                  "initial_elo": 1500}])
    monkeypatch.setattr(cfg, "load_rating_names", lambda: ["Cloud9", "LOUD"])
    # nome exato vivido sempre vence — sem ambiguidade
    assert cfg.resolve_team("LOUD")["name"] == "LOUD"
    assert cfg.resolve_team("cloud9")["name"] == "Cloud9"
    # substring que bate Cloud9 (Top 30) E LOUD (ratings) → ambíguo
    with pytest.raises(ValueError):
        cfg.resolve_team("lou")


def test_nome_igual_em_regioes_diferentes_e_ambiguo(monkeypatch):
    import src.config as cfg
    monkeypatch.setattr(cfg, "load_teams", lambda: [
        {"name": "Phoenix", "region": "LCS", "initial_elo": 1500},
        {"name": "PHOENIX", "region": "LPL", "initial_elo": 1500},
    ])
    monkeypatch.setattr(cfg, "load_rating_names", lambda: [])
    with pytest.raises(ValueError, match="ambígua"):
        cfg.resolve_team("phoenix")


# ---------- ratings / modelo ----------

def test_ratings_file_customizado_sem_time_vira_valueerror(tmp_path):
    p = tmp_path / "r.json"
    p.write_text("{}", encoding="utf-8")
    m = EloModel(ratings_file=p)
    # Sentinels só existe no ratings.json default; aqui não há rating
    with pytest.raises(ValueError, match="sem rating"):
        m.predict_match("Sentinels", "T1")


def test_rating_nao_finito_recusado(tmp_path):
    for bad in ("NaN", "Infinity", "-Infinity"):
        p = tmp_path / f"r_{bad}.json"
        p.write_text(f'{{"T1": {bad}}}', encoding="utf-8")
        with pytest.raises(ValueError, match="não finito"):
            EloModel(ratings_file=p)


def test_update_ratings_empate_recusado(tmp_path):
    p = tmp_path / "r.json"
    p.write_text("{}", encoding="utf-8")
    m = EloModel(ratings_file=p)
    before = dict(m.ratings)
    with pytest.raises(ValueError, match="empatada"):
        m.update_ratings("T1", "Gen.G", 1, 1)
    assert m.ratings == before
    assert p.read_text(encoding="utf-8") == "{}"   # nada persistido


def test_update_ratings_placar_invalido(tmp_path):
    p = tmp_path / "r.json"
    p.write_text("{}", encoding="utf-8")
    m = EloModel(ratings_file=p)
    with pytest.raises(ValueError):
        m.update_ratings("T1", "Gen.G", -1, 2)
    with pytest.raises(ValueError):
        m.update_ratings("T1", "Gen.G", 1.5, 0)
    with pytest.raises(ValueError):
        m.update_ratings("T1", "Gen.G", True, 0)
    with pytest.raises(ValueError):
        m.update_ratings("T1", "t1", 2, 1)   # mesmo time dos dois lados
    with pytest.raises(ValueError, match="incompatível"):
        m.update_ratings("T1", "Gen.G", 1, 0, format="bo3")


def test_update_ratings_concorrente_nao_perde_update(tmp_path):
    p = tmp_path / "r.json"
    p.write_text("{}", encoding="utf-8")
    models = [EloModel(ratings_file=p), EloModel(ratings_file=p)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(models[0].update_ratings, "T1", "Gen.G", 2, 0),
            pool.submit(models[1].update_ratings, "G2 Esports", "Fnatic", 2, 1),
        ]
        for future in futures:
            future.result()
    persisted = json.loads(p.read_text(encoding="utf-8"))
    assert set(persisted) == {"T1", "Gen.G", "G2 Esports", "Fnatic"}


def test_arquivo_de_ratings_truncado_falha_alto(tmp_path):
    p = tmp_path / "r.json"
    p.write_text('{"T1": 1600', encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        EloModel(ratings_file=p)


# ---------- lifecycle / maturação ----------

def _ledger_com_pre_event(tmp_path, matures_at):
    ledger = tmp_path / "ledger.jsonl"
    row = {
        "schema_version": "lol-prediction-point/1.0",
        "prediction_id": "abc123",
        "lifecycle_status": "PRE_EVENT",
        "predicted_at": "2026-07-16T12:00:00+00:00",
        "scheduled_at": "2026-07-17T11:00:00+00:00",
        "matures_at": matures_at,
        "event": "EWC 2026", "stage": "QF",
        "team_a": "Gen.G", "team_b": "JD Gaming",
        "format": "bo3", "model": "elo",
        "ratings_sha256": "x", "value": {
            "probability_a": 0.8, "probability_b": 0.2, "favorite": "Gen.G"},
        "result": None, "brier": None, "correct": None, "limitations": [],
    }
    ledger.write_text(json.dumps(row, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    return ledger


def test_mature_prediction_id_desconhecido_recusado(tmp_path):
    ledger = _ledger_com_pre_event(tmp_path, "2026-07-17T13:30:00+00:00")
    results = {"results": [{"team_a": "Gen.G", "team_b": "JD Gaming",
                            "prediction_id": "nao-existe",
                            "winner": "Gen.G", "score": "2-0"}]}
    with pytest.raises(ValueError, match="unknown prediction_id"):
        pe.mature_results(ledger, results,
                          now=datetime(2026, 7, 18, tzinfo=timezone.utc))


def test_mature_prematura_nao_grava(tmp_path):
    ledger = _ledger_com_pre_event(tmp_path, "2026-07-17T13:30:00+00:00")
    results = {"results": [{"team_a": "Gen.G", "team_b": "JD Gaming",
                            "winner": "Gen.G", "score": "2-0"}]}
    out = pe.mature_results(
        ledger, results,
        now=datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc))
    assert out == {"registered": 0, "already_present": 0, "not_ready": 1}
    lines = ledger.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1


def test_mature_placar_e_vencedor_invalidos(tmp_path):
    ledger = _ledger_com_pre_event(tmp_path, "2026-07-17T13:30:00+00:00")
    now = datetime(2026, 7, 18, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="winner"):
        pe.mature_results(ledger, {"results": [
            {"team_a": "Gen.G", "team_b": "JD Gaming",
             "winner": "T1", "score": "2-0"}]}, now=now)
    with pytest.raises(ValueError, match="invalid"):
        pe.mature_results(ledger, {"results": [
            {"team_a": "Gen.G", "team_b": "JD Gaming",
             "winner": "Gen.G", "score": "3-0"}]}, now=now)


def test_mature_idempotente(tmp_path):
    ledger = _ledger_com_pre_event(tmp_path, "2026-07-17T13:30:00+00:00")
    now = datetime(2026, 7, 18, tzinfo=timezone.utc)
    results = {"results": [{"team_a": "Gen.G", "team_b": "JD Gaming",
                            "winner": "Gen.G", "score": "2-1"}]}
    first = pe.mature_results(ledger, results, now=now)
    second = pe.mature_results(ledger, results, now=now)
    assert first["registered"] == 1
    assert second == {"registered": 0, "already_present": 1, "not_ready": 0}


def test_mature_concorrente_nao_duplica(tmp_path):
    ledger = _ledger_com_pre_event(tmp_path, "2026-07-17T13:30:00+00:00")
    now = datetime(2026, 7, 18, tzinfo=timezone.utc)
    results = {"results": [{"team_a": "Gen.G", "team_b": "JD Gaming",
                            "winner": "Gen.G", "score": "2-1"}]}
    with ThreadPoolExecutor(max_workers=2) as pool:
        outputs = list(pool.map(
            lambda _: pe.mature_results(ledger, results, now=now), range(2)))
    assert sorted(row["registered"] for row in outputs) == [0, 1]
    records = [json.loads(line) for line in ledger.read_text(
        encoding="utf-8").splitlines()]
    assert sum(row["lifecycle_status"] == "MATURED" for row in records) == 1


def test_timestamps_invalidos_falham_antes_de_gravar(tmp_path):
    ledger = _ledger_com_pre_event(tmp_path, "sem-data")
    before = ledger.read_bytes()
    results = {"results": [{"team_a": "Gen.G", "team_b": "JD Gaming",
                            "winner": "Gen.G", "score": "2-0"}]}
    with pytest.raises(ValueError, match="invalid matures_at"):
        pe.mature_results(ledger, results,
                          now=datetime(2026, 7, 18, tzinfo=timezone.utc))
    assert ledger.read_bytes() == before
    with pytest.raises(ValueError, match="now must be timezone-aware"):
        pe.mature_results(ledger, results, now=datetime(2026, 7, 18))


def test_fixture_snapshot_ingenuo_e_rejeitado():
    fixture = {"snapshot_at": "2026-07-16T12:00:00", "matches": []}
    with pytest.raises(ValueError, match="snapshot_at must be timezone-aware"):
        pe.build(fixture)
