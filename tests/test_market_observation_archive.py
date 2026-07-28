"""A observacao bruta e arquivada mesmo quando o sinal e inelegivel.

Achado em 2026-07-28: `build_signal` levanta `H4Error` quando falta competicao
(B-12), o `except` do coletor captura, e a gravacao vinha DEPOIS — entao a
cotacao era buscada do Polymarket e jogada fora. A tarefa rodava de 30 em 30
minutos com exit 0 enquanto nada era gravado desde 22/07. Seis dias de dado
real perdidos, irrecuperaveis, sem nenhum sinal de alarme.

Observar e julgar sao coisas diferentes. O arquivo bruto nao alimenta gate,
contador nem criterio — e registro de auditoria. Estes testes garantem que ele
sobrevive a inelegibilidade E que continua sem contaminar a coorte.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import collect_polymarket_upcoming as coletor
from src.h4_gate import H4Error


def _quote(event_id: str = "evt-1") -> dict:
    return {"schema_version": "lol-market-quote/1.0",
            "quote_id": f"q-{event_id}", "source": "polymarket-clob",
            "event_id": event_id, "team_a": "T1", "team_b": "Gen.G",
            "format": "bo3", "scheduled_at": "2026-07-30T15:00:00+00:00",
            "observed_at": "2026-07-28T03:00:00+00:00",
            "probability_a": 0.5, "probability_b": 0.5, "read_only": True}


class _Provider:
    def __init__(self, matches): self._matches = matches
    def list_upcoming_matches(self, horizon_hours=72): return self._matches
    def fetch_match(self, team_a, team_b, event_id=None): return _quote(event_id)


@pytest.fixture
def coletor_falso(monkeypatch, tmp_path):
    partidas = [{"team_a": "T1", "team_b": "Gen.G", "event_id": "evt-1",
                 "competition_id": None, "scheduled_at": "2026-07-30T15:00:00+00:00"}]
    monkeypatch.setattr(coletor, "assert_h4_open", lambda *_: None)
    monkeypatch.setattr(coletor, "PolymarketProvider", lambda: _Provider(partidas))
    monkeypatch.setattr(coletor, "resolve_market_team", lambda nome: nome)
    monkeypatch.setattr(coletor, "attach_model_snapshot", lambda q: q)
    monkeypatch.setattr(coletor, "_commit", lambda: "0" * 40)
    return tmp_path


def test_observacao_sobrevive_a_sinal_inelegivel(coletor_falso: Path, monkeypatch) -> None:
    # Exatamente o estado do B-12: a fonte nao traz competicao, entao o sinal e
    # recusado -- corretamente. A observacao NAO pode morrer junto.
    def recusa(*_a, **_k):
        raise H4Error("competicao ausente")
    monkeypatch.setattr(coletor, "build_signal", recusa)

    saida = coletor_falso / "h4_signals.jsonl"
    arquivo = coletor_falso / "market_observations.jsonl"
    relatorio = coletor.collect(saida, 72, archive=arquivo)

    assert relatorio["appended"] == 0, "sinal inelegivel nao pode entrar na coorte"
    assert relatorio["unavailable"] == 1
    assert relatorio["archived"] == 1, "a observacao bruta precisa sobreviver"
    assert not saida.exists(), "a coorte nao pode ser tocada por sinal recusado"

    linhas = [json.loads(x) for x in arquivo.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(linhas) == 1 and linhas[0]["event_id"] == "evt-1"


def test_arquivo_e_idempotente_entre_execucoes(coletor_falso: Path, monkeypatch) -> None:
    # A tarefa roda de 30 em 30 min sobre a mesma janela de 72h: reobservar o
    # mesmo quote_id nao pode inflar o arquivo.
    monkeypatch.setattr(coletor, "build_signal",
                        lambda *a, **k: (_ for _ in ()).throw(H4Error("x")))
    saida = coletor_falso / "h4_signals.jsonl"
    arquivo = coletor_falso / "market_observations.jsonl"

    assert coletor.collect(saida, 72, archive=arquivo)["archived"] == 1
    assert coletor.collect(saida, 72, archive=arquivo)["archived"] == 0

    linhas = [x for x in arquivo.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(linhas) == 1


def test_sinal_elegivel_alimenta_coorte_E_arquivo(coletor_falso: Path, monkeypatch) -> None:
    monkeypatch.setattr(coletor, "build_signal",
                        lambda quote, **k: {**quote, "signal_id": "sig-1"})
    saida = coletor_falso / "h4_signals.jsonl"
    arquivo = coletor_falso / "market_observations.jsonl"

    relatorio = coletor.collect(saida, 72, archive=arquivo)
    assert relatorio["appended"] == 1 and relatorio["archived"] == 1
    assert saida.exists() and arquivo.exists()
