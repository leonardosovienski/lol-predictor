"""Reconstrução da série a partir dos jogos do Oracle's Elixir.

O ponto delicado: os LADOS TROCAM entre jogos de uma mesma série. Contar por
coluna em vez de por nome de time inverteria o vencedor — por isso o caso de
troca de lado tem teste próprio.
"""
import sqlite3

import pytest

from scripts.build_h4_results import series_result

INICIO = "2026-07-23T15:00:00+00:00"


@pytest.fixture
def db():
    """Conexao fechada no teardown.

    Sem o close explicito o GC finaliza a conexao no meio de OUTRO teste, e o
    `-W error` do ci_check.py transforma o PytestUnraisableExceptionWarning
    resultante em falha atribuida ao teste errado."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE games (game_id TEXT, date TEXT, league TEXT, split TEXT,"
                 " game INT, team_a TEXT, team_b TEXT, winner TEXT, kills_a INT,"
                 " kills_b INT, completeness TEXT)")
    try:
        yield conn
    finally:
        conn.close()


def _jogo(conn, gid, data, a, b, vencedor, completo="complete"):
    conn.execute("INSERT INTO games VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 (gid, data, "LEC", "", 1, a, b, vencedor, 0, 0, completo))
    conn.commit()


def test_serie_simples_2x0(db):
    c = db
    _jogo(c, "g1", "2026-07-23 15:10:00", "T1", "Gen.G", "a")
    _jogo(c, "g2", "2026-07-23 16:10:00", "T1", "Gen.G", "a")
    r = series_result(c, "T1", "Gen.G", INICIO)
    assert r["winner"] == "T1" and r["games_team_a"] == 2 and r["games_team_b"] == 0


def test_lados_trocam_entre_jogos(db):
    """Bo3 com troca de lado: contar por coluna daria o vencedor errado."""
    c = db
    _jogo(c, "g1", "2026-07-23 15:10:00", "T1", "Gen.G", "a")      # T1 vence
    _jogo(c, "g2", "2026-07-23 16:10:00", "Gen.G", "T1", "a")      # Gen.G vence
    _jogo(c, "g3", "2026-07-23 17:10:00", "Gen.G", "T1", "b")      # T1 vence
    r = series_result(c, "T1", "Gen.G", INICIO)
    assert r["winner"] == "T1" and r["games_team_a"] == 2 and r["games_team_b"] == 1


def test_empate_nao_decide(db):
    c = db
    _jogo(c, "g1", "2026-07-23 15:10:00", "T1", "Gen.G", "a")
    _jogo(c, "g2", "2026-07-23 16:10:00", "T1", "Gen.G", "b")
    assert series_result(c, "T1", "Gen.G", INICIO) is None


def test_jogo_incompleto_nao_conta(db):
    c = db
    _jogo(c, "g1", "2026-07-23 15:10:00", "T1", "Gen.G", "a", completo="partial")
    assert series_result(c, "T1", "Gen.G", INICIO) is None


def test_serie_fora_da_janela_nao_casa(db):
    c = db
    _jogo(c, "g1", "2026-07-27 15:10:00", "T1", "Gen.G", "a")
    assert series_result(c, "T1", "Gen.G", INICIO) is None


def test_confronto_de_outro_par_nao_contamina(db):
    c = db
    _jogo(c, "g1", "2026-07-23 15:10:00", "T1", "Gen.G", "a")
    _jogo(c, "g2", "2026-07-23 15:20:00", "T1", "KT Rolster", "b")
    r = series_result(c, "T1", "Gen.G", INICIO)
    assert r["games_team_a"] == 1 and r["games_team_b"] == 0


def test_caixa_diferente_resolve(db):
    c = db
    _jogo(c, "g1", "2026-07-23 15:10:00", "t1", "GEN.G", "a")
    r = series_result(c, "T1", "Gen.G", INICIO)
    assert r is not None and r["winner"] == "T1"


def test_acento_nao_e_aproximado(db):
    """O lol-predictor NAO remove acento de proposito: sao entidades distintas."""
    c = db
    _jogo(c, "g1", "2026-07-23 15:10:00", "Fnatic", "Movistár", "a")
    assert series_result(c, "Fnatic", "Movistar", INICIO) is None


def test_par_degenerado_recusa(db):
    c = db
    _jogo(c, "g1", "2026-07-23 15:10:00", "T1", "T1", "a")
    assert series_result(c, "T1", "T1", INICIO) is None


def test_evidencia_lista_os_jogos(db):
    c = db
    _jogo(c, "g1", "2026-07-23 15:10:00", "T1", "Gen.G", "a")
    _jogo(c, "g2", "2026-07-23 16:10:00", "T1", "Gen.G", "a")
    assert series_result(c, "T1", "Gen.G", INICIO)["game_ids"] == ["g1", "g2"]
