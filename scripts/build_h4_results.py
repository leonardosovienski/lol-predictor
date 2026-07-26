"""Produz o arquivo de resultados oficiais que `settle_h4_signals.py` consome.

Era o elo faltante do B-3: `settle_h4_signals.py` existia e era testado, mas
exigia um `--results` que nenhum código produzia. Sem isto a coorte H4 coleta
sinal e nunca liquida — o mesmo defeito que manteve o cs-predictor em 0/50 até
2026-07-25.

A fonte é o Oracle's Elixir já ingerido em `data/lol.db` (tabela `games`), que
guarda JOGOS individuais. O sinal H4 é sobre a SÉRIE, então a série é
reconstruída contando vitórias por NOME DE TIME — não por coluna, porque os lados
trocam entre jogos de uma mesma série.

Identidade segue `config._identity_key` (NFC + casefold, SEM remover acento — o
lol-predictor é deliberadamente mais estrito que os outros domínios aqui).
Ambiguidade e empate viram ausência: `settle` deixa o sinal PENDING, que é o
estado correto. Este script nunca inventa resultado.

Uso:
    python scripts/build_h4_results.py --out data/shadow/h4_results.json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import _identity_key  # noqa: E402

RESULT_SOURCE = "oracle-elixir"          # settle_h4_signals só aceita este ou riot-esports
JANELA = timedelta(hours=36)             # fuso + série que vira o dia


def _dt(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def series_result(conn: sqlite3.Connection, team_a: str, team_b: str,
                  event_start_at: str) -> dict | None:
    """Vencedor da série entre os dois times perto do horário do evento.

    Conta vitórias por nome de time (os lados trocam entre jogos). Só jogos
    `complete` contam. Empate ou par não encontrado devolve None — nunca escolhe."""
    inicio = _dt(event_start_at)
    if inicio is None:
        return None
    ka, kb = _identity_key(team_a), _identity_key(team_b)
    if ka == kb:
        return None
    vitorias: dict[str, int] = {ka: 0, kb: 0}
    ids: list[str] = []
    for game_id, data, ta, tb, vencedor, completo in conn.execute(
            "SELECT game_id, date, team_a, team_b, winner, completeness FROM games"):
        if completo != "complete" or vencedor not in ("a", "b"):
            continue
        kta, ktb = _identity_key(ta), _identity_key(tb)
        if {kta, ktb} != {ka, kb}:
            continue
        quando = _dt(str(data).replace(" ", "T"))
        if quando is None or abs(quando - inicio) > JANELA:
            continue
        vencedor_key = kta if vencedor == "a" else ktb
        vitorias[vencedor_key] += 1
        ids.append(game_id)
    if not ids or vitorias[ka] == vitorias[kb]:
        return None
    ganhador = team_a if vitorias[ka] > vitorias[kb] else team_b
    return {"winner": ganhador, "games_team_a": vitorias[ka],
            "games_team_b": vitorias[kb], "game_ids": sorted(ids)}


def _write(out: Path, payload: dict) -> None:
    """Publica o artefato de resultados. Sempre, inclusive vazio."""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2,
                              sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--signals", type=Path, default=ROOT / "data/shadow/h4_signals.jsonl")
    ap.add_argument("--db", type=Path, default=ROOT / "data/lol.db")
    ap.add_argument("--out", type=Path, default=ROOT / "data/shadow/h4_results.json")
    args = ap.parse_args(argv)

    if not args.signals.exists():
        # Escreve o artefato MESMO sem sinal. O settle_h4_signals.py abre este
        # arquivo incondicionalmente; sem isto ele morria com FileNotFoundError
        # (exit 2) e derrubava a semanal inteira para FAILED toda vez que a
        # coorte estivesse vazia -- que e o estado permanente enquanto o B-12
        # nao for decidido. Descoberto em 2026-07-26 rodando a tarefa de
        # verdade, nao pela suite.
        #
        # Artefato vazio E EXPLICITO e melhor que ausencia: "0 resultados as
        # 22:06" e um fato auditavel; arquivo faltando e ambiguo entre "nada a
        # liquidar" e "o produtor nao rodou".
        _write(args.out, {"status": "NO_SIGNALS", "results": [],
                          "generated_at_utc": datetime.now(timezone.utc)
                          .isoformat(timespec="seconds")})
        print(json.dumps({"status": "NO_SIGNALS", "signals": str(args.signals),
                          "results": 0, "out": str(args.out)}))
        return 0
    linhas = [json.loads(x) for x in args.signals.read_text(encoding="utf-8").splitlines() if x.strip()]
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    resultados, pendentes = [], 0
    try:
        for row in linhas:
            if row.get("settlement_status") == "OFFICIAL":
                continue
            achado = series_result(conn, row["team_a_id"], row["team_b_id"],
                                   row["event_start_at"])
            if achado is None:
                pendentes += 1
                continue
            escolhido = row["team_a_id"] if row["selection"] == "team_a" else row["team_b_id"]
            venceu = _identity_key(achado["winner"]) == _identity_key(escolhido)
            resultados.append({
                "canonical_event_id": row["canonical_event_id"],
                "result": int(venceu),                 # 1 = o lado SELECIONADO venceu
                "source": RESULT_SOURCE,
                "result_available_at": agora,          # quando ficou disponivel PARA NOS
                "series": {k: achado[k] for k in ("winner", "games_team_a", "games_team_b")},
                "evidence_game_ids": achado["game_ids"]})
    finally:
        conn.close()

    # Sem `if resultados:` -- o artefato sai SEMPRE. Com o guard, uma rodada em
    # que todos os sinais estivessem pendentes (nenhuma serie oficial ainda)
    # nao escrevia nada, e o settle seguinte morria em FileNotFoundError. E o
    # caso comum assim que a coleta comecar: sinal capturado hoje, serie so
    # amanha.
    _write(args.out, {"results": resultados, "status": "OK",
                      "generated_at_utc": agora})
    print(json.dumps({"status": "OK", "sinais": len(linhas), "resultados": len(resultados),
                      "sem_serie_oficial": pendentes, "out": str(args.out)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
