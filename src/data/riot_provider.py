"""Fonte de dados de LoL competitivo — STUB da Fase 0.

Candidatas da Fase 1: Riot Games API (esports não tem endpoint público
estável; a API de match-v5 é de filas ranqueadas, não de ligas) e o dataset
Oracle's Elixir (CSV curado de partidas profissionais — a via mais provável
para o backtest). Interface com a disciplina da plataforma
(DataUnavailableError; chave via RIOT_API_KEY).
"""
import os

from predictor_core.data.contracts import DataUnavailableError


class RiotProvider:
    """Interface da fonte de LoL. Fase 0: tudo levanta DataUnavailableError —
    nenhum teste ou serving pode depender de rede sem perceber."""

    BASE_URL = "https://americas.api.riotgames.com"

    def __init__(self, api_key: str | None = None, timeout: float = 30.0):
        self.api_key = api_key or os.environ.get("RIOT_API_KEY")
        self.timeout = timeout

    def health_check(self) -> bool:
        """Fase 0: sem rede — sempre False (honesto: não há fonte ligada)."""
        return False

    def fetch_results(self, league: str, season: str) -> list[dict]:
        """Fase 1: resultados de partidas Tier 1 (LCK/LPL/LEC/LCS) para
        update_ratings e backtest — via mais provável: Oracle's Elixir."""
        raise DataUnavailableError(
            "RiotProvider é stub na Fase 0 — decidir Riot API vs Oracle's "
            "Elixir na Fase 1")

    def fetch_team_stats(self, league: str, season: str) -> dict:
        """Fase 1: médias por time (kills_per_game etc.) → data/team_stats.json."""
        raise DataUnavailableError("RiotProvider é stub na Fase 0")
