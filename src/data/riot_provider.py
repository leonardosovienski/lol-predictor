"""Fontes de dados de LoL competitivo.

FASE 1 (2026-07-11): a via escolhida é o **Oracle's Elixir** — CSVs públicos
por ano numa pasta do Google Drive (link em oracleselixir.com/tools/downloads;
IDs descobertos via navegador na criação da Fase 1). Download manual/curl para
`data/raw/<ano>_oe.csv`; `OracleProvider` lê e agrega LOCALMENTE (sem rede):
cada jogo tem 12 linhas (10 jogadores + 2 de time, position='team') — o
provider colapsa as duas linhas de time num registro de JOGO (mapa).

A Riot API segue descartada para esports (sem endpoint público estável);
`RiotProvider` permanece como stub documentado.
"""
import csv
import os
from pathlib import Path

from ..config import ROOT as _ROOT  # noqa: F401  (ativa vendor no sys.path)
from predictor_core.data.contracts import DataUnavailableError


class OracleProvider:
    """Leitor local dos CSVs do Oracle's Elixir (data/raw/*.csv)."""

    def __init__(self, raw_dir: Path | str, leagues: list[str] | None = None):
        self.raw_dir = Path(raw_dir)
        self.leagues = set(leagues) if leagues else None

    def health_check(self) -> bool:
        return any(self.raw_dir.glob("*.csv"))

    def iter_games(self):
        """Gera 1 dict por JOGO (mapa), agregando as 2 linhas position='team'.

        Campos: game_id, date (ISO com hora), league, split, game (nº na
        série), team_a/team_b (lado Blue/Red), winner ('a'|'b'),
        kills_a/kills_b (teamkills), completeness."""
        files = sorted(self.raw_dir.glob("*.csv"))
        if not files:
            raise DataUnavailableError(
                f"nenhum CSV em {self.raw_dir} — baixe do Drive do Oracle's "
                "Elixir (ver docstring do módulo)")
        pend: dict[str, dict] = {}
        for f in files:
            with open(f, encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    if row.get("position") != "team":
                        continue
                    if self.leagues and row.get("league") not in self.leagues:
                        continue
                    gid = row.get("gameid")
                    if not gid:
                        continue
                    side = {"side": row.get("side"),
                            "team": (row.get("teamname") or "").strip(),
                            "result": row.get("result"),
                            "kills": row.get("teamkills")}
                    if gid not in pend:
                        pend[gid] = {"row": row, "sides": [side]}
                    else:
                        pend[gid]["sides"].append(side)
                    labels = {item["side"] for item in pend[gid]["sides"]}
                    if {"Blue", "Red"} <= labels:
                        entry = pend.pop(gid)
                        try:
                            yield self._merge(gid, entry)
                        except DataUnavailableError as exc:
                            print(f"aviso: jogo {gid} inválido — descartado: {exc}")
        # jogos com só 1 linha de time (dado quebrado) são descartados calados?
        # Não: reporta a contagem pra ninguém achar que cobriu tudo.
        if pend:
            print(f"aviso: {len(pend)} jogo(s) com linha de time única "
                  "(dado incompleto no CSV) — descartados")

    @staticmethod
    def _merge(gid: str, entry: dict) -> dict:
        row, sides = entry["row"], entry["sides"]
        blue = next((s for s in sides if s["side"] == "Blue"), None)
        red = next((s for s in sides if s["side"] == "Red"), None)
        if blue is None or red is None:
            raise DataUnavailableError("exige exatamente os lados Blue e Red")
        if not blue["team"] or not red["team"] or blue["team"] == red["team"]:
            raise DataUnavailableError("identidade de times ausente ou duplicada")
        if {blue["result"], red["result"]} != {"0", "1"}:
            raise DataUnavailableError("resultado deve ter um vencedor e um perdedor")

        def _i(v):
            try:
                return int(float(v))
            except (TypeError, ValueError):
                return None

        return {
            "game_id": gid,
            "date": row.get("date"),
            "league": row.get("league"),
            "split": row.get("split"),
            "game": _i(row.get("game")),
            "team_a": blue["team"], "team_b": red["team"],
            "winner": "a" if blue["result"] == "1" else "b",
            "kills_a": _i(blue["kills"]), "kills_b": _i(red["kills"]),
            "completeness": row.get("datacompleteness"),
        }


class RiotProvider:
    """STUB (mantido): a Riot API não tem endpoint público estável de esports."""

    BASE_URL = "https://americas.api.riotgames.com"

    def __init__(self, api_key: str | None = None, timeout: float = 30.0):
        self.api_key = api_key or os.environ.get("RIOT_API_KEY")
        self.timeout = timeout

    def health_check(self) -> bool:
        return False

    def fetch_results(self, league: str, season: str) -> list[dict]:
        raise DataUnavailableError("use OracleProvider (CSVs locais)")

    def fetch_team_stats(self, league: str, season: str) -> dict:
        raise DataUnavailableError("use OracleProvider (CSVs locais)")
