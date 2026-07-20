"""Fase 1 — OracleProvider (agregação por jogo) e db do LoL."""
import csv

import pytest

from src import db
from src.data.riot_provider import OracleProvider

_HEADER = ["gameid", "datacompleteness", "league", "split", "date", "game",
           "side", "position", "teamname", "result", "teamkills"]


def _csv(tmp_path, rows, name="2025_oe.csv"):
    p = tmp_path / name
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_HEADER)
        w.writeheader()
        w.writerows(rows)
    return tmp_path


def _team_row(gid, side, team, result, kills, league="LCK"):
    return {"gameid": gid, "datacompleteness": "complete", "league": league,
            "split": "Spring", "date": "2025-02-01 08:00:00", "game": "1",
            "side": side, "position": "team", "teamname": team,
            "result": result, "teamkills": kills}


def test_merge_blue_red_e_vencedor(tmp_path):
    raw = _csv(tmp_path, [
        _team_row("g1", "Blue", "T1", "1", "18"),
        _team_row("g1", "Red", "Gen.G", "0", "9"),
        # linha de jogador no meio não pode atrapalhar
        {**_team_row("g1", "Blue", "T1", "1", "18"), "position": "mid"},
    ])
    games = list(OracleProvider(raw).iter_games())
    assert len(games) == 1
    g = games[0]
    assert g["team_a"] == "T1" and g["team_b"] == "Gen.G"
    assert g["winner"] == "a"
    assert g["kills_a"] == 18 and g["kills_b"] == 9
    assert g["league"] == "LCK"


def test_filtro_de_ligas(tmp_path):
    raw = _csv(tmp_path, [
        _team_row("g1", "Blue", "T1", "1", "18"),
        _team_row("g1", "Red", "Gen.G", "0", "9"),
        _team_row("g2", "Blue", "TimeX", "1", "20", league="LJL"),
        _team_row("g2", "Red", "TimeY", "0", "10", league="LJL"),
    ])
    games = list(OracleProvider(raw, leagues=["LCK"]).iter_games())
    assert len(games) == 1 and games[0]["league"] == "LCK"


def test_jogo_com_linha_unica_descartado(tmp_path, capsys):
    raw = _csv(tmp_path, [_team_row("g1", "Blue", "T1", "1", "18")])
    games = list(OracleProvider(raw).iter_games())
    assert games == []
    assert "descartados" in capsys.readouterr().out


def test_linha_blue_duplicada_nao_fabrica_jogo_contra_si_mesmo(tmp_path):
    raw = _csv(tmp_path, [
        _team_row("g1", "Blue", "T1", "1", "18"),
        _team_row("g1", "Blue", "T1", "1", "18"),
        _team_row("g1", "Red", "Gen.G", "0", "9"),
    ])
    games = list(OracleProvider(raw).iter_games())
    assert len(games) == 1
    assert (games[0]["team_a"], games[0]["team_b"]) == ("T1", "Gen.G")


def test_resultado_sem_vencedor_e_descartado(tmp_path, capsys):
    raw = _csv(tmp_path, [
        _team_row("g1", "Blue", "T1", "0", "9"),
        _team_row("g1", "Red", "Gen.G", "0", "9"),
    ])
    assert list(OracleProvider(raw).iter_games()) == []
    assert "resultado deve ter um vencedor" in capsys.readouterr().out


def test_mesmo_time_nos_dois_lados_e_descartado(tmp_path, capsys):
    raw = _csv(tmp_path, [
        _team_row("g1", "Blue", "T1", "1", "18"),
        _team_row("g1", "Red", "T1", "0", "9"),
    ])
    assert list(OracleProvider(raw).iter_games()) == []
    assert "identidade de times" in capsys.readouterr().out


def test_db_upsert_idempotente():
    conn = db.connect(":memory:")
    try:
        g = {"game_id": "g1", "date": "2025-02-01 08:00:00", "league": "LCK",
             "split": "Spring", "game": 1, "team_a": "T1", "team_b": "Gen.G",
             "winner": "a", "kills_a": 18, "kills_b": 9,
             "completeness": "complete"}
        db.upsert_games(conn, [g])
        db.upsert_games(conn, [dict(g, kills_a=19)])
        rows = conn.execute("SELECT kills_a FROM games").fetchall()
    finally:
        conn.close()
    assert rows == [(19,)]


def test_db_read_only(tmp_path):
    import sqlite3
    p = tmp_path / "lol.db"
    conn = db.connect(str(p))
    conn.close()
    ro = db.connect(str(p), read_only=True)
    try:
        with pytest.raises(sqlite3.OperationalError):
            ro.execute("DELETE FROM games")
    finally:
        ro.close()
