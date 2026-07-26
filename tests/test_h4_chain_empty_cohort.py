"""A cadeia h4_results -> h4_settle precisa sobreviver a coorte vazia.

Achado em 2026-07-26 disparando a `lol-ratings-semanal` de verdade, nao pela
suite: o produtor devolvia `NO_SIGNALS` e **nao escrevia o artefato**, e o
consumidor abria `--results` incondicionalmente. Resultado:
`FileNotFoundError`, exit 2, e a semanal inteira classificada FAILED em vez de
PARTIAL -- toda semana, enquanto a coorte estivesse vazia. E ela esta vazia de
forma permanente enquanto o B-12 nao for decidido.

O mesmo buraco existia no caminho normal, escondido atras de `if resultados:`:
uma rodada com sinais TODOS pendentes (serie oficial ainda nao disponivel)
tambem nao escrevia nada. Esse e o caso comum assim que a coleta comecar --
sinal capturado hoje, serie so amanha.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts.build_h4_results import main as build_main
from scripts.settle_h4_signals import main as settle_main


@pytest.fixture
def db(tmp_path: Path) -> Path:
    caminho = tmp_path / "lol.db"
    conn = sqlite3.connect(caminho)
    try:
        conn.execute("CREATE TABLE games (game_id TEXT, date TEXT, league TEXT,"
                     " split TEXT, game INT, team_a TEXT, team_b TEXT,"
                     " winner TEXT, kills_a INT, kills_b INT, completeness TEXT)")
        conn.commit()
    finally:
        conn.close()
    return caminho


def test_sem_sinais_publica_artefato_vazio_e_explicito(tmp_path: Path, db: Path) -> None:
    sinais = tmp_path / "h4_signals.jsonl"          # nao existe de proposito
    out = tmp_path / "h4_results.json"

    assert build_main(["--signals", str(sinais), "--db", str(db), "--out", str(out)]) == 0
    assert out.exists(), "artefato precisa existir mesmo sem sinal"

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["results"] == []
    assert payload["status"] == "NO_SIGNALS"
    # O carimbo e o que diferencia "0 resultados as 22:06" de "ninguem rodou".
    assert payload["generated_at_utc"].endswith("+00:00")


def test_settle_aceita_coorte_vazia_sem_derrubar_a_semanal(tmp_path: Path, db: Path) -> None:
    sinais = tmp_path / "h4_signals.jsonl"
    out = tmp_path / "h4_results.json"
    build_main(["--signals", str(sinais), "--db", str(db), "--out", str(out)])

    assert settle_main(["--signals", str(sinais), "--results", str(out)]) == 0


def test_sinais_todos_pendentes_ainda_publicam_artefato(tmp_path: Path, db: Path) -> None:
    # Sinal real cuja serie ainda nao aconteceu: `resultados` sai vazio, mas o
    # arquivo precisa existir para o settle seguinte nao morrer.
    sinais = tmp_path / "h4_signals.jsonl"
    sinais.write_text(json.dumps({
        "canonical_event_id": "evt-1", "team_a_id": "T1", "team_b_id": "Gen.G",
        "selection": "team_a", "event_start_at": "2026-07-30T15:00:00+00:00",
        "settlement_status": "PENDING",
    }, sort_keys=True) + "\n", encoding="utf-8")
    out = tmp_path / "h4_results.json"

    assert build_main(["--signals", str(sinais), "--db", str(db), "--out", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["results"] == []
    assert settle_main(["--signals", str(sinais), "--results", str(out)]) == 0


def test_results_ausente_continua_sendo_erro(tmp_path: Path) -> None:
    """O produtor nao ter rodado NAO pode virar sucesso silencioso.

    Tolerar sinais ausentes e correto (coorte vazia e estado legitimo).
    Tolerar RESULTADOS ausentes seria fail-open: apagaria a diferenca entre
    "nada a liquidar" e "a etapa anterior falhou".
    """
    sinais = tmp_path / "h4_signals.jsonl"
    sinais.write_text(json.dumps({
        "canonical_event_id": "evt-1", "team_a_id": "T1", "team_b_id": "Gen.G",
        "selection": "team_a", "event_start_at": "2026-07-30T15:00:00+00:00",
        "settlement_status": "PENDING",
    }, sort_keys=True) + "\n", encoding="utf-8")

    assert settle_main(["--signals", str(sinais),
                        "--results", str(tmp_path / "nao_existe.json")]) == 2
