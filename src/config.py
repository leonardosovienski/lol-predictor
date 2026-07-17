"""Configuração do lol-predictor — carrega config.yaml e resolve paths.

Mesmo padrão do nba/cs-predictor: YAML na raiz é a única fonte de parâmetros;
vendor/ entra no sys.path aqui.
"""
import json
import sys
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
_VENDOR = ROOT / "vendor"
if str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))


@lru_cache(maxsize=1)
def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def load_teams() -> list[dict]:
    """Times Tier 1 de data/teams_lol.json (nome, liga, Elo semente)."""
    cfg = load_config()
    path = ROOT / cfg.get("teams_file", "data/teams_lol.json")
    return json.loads(path.read_text(encoding="utf-8"))["teams"]


@lru_cache(maxsize=1)
def load_rating_names() -> list[str]:
    """Nomes extras de times presentes em ratings.json (Fase 1 ingeriu mais
    times do que os 30 de teams_lol.json) — só para resolve_team encontrar
    o time; o Elo em si continua vindo de EloModel.ratings."""
    cfg = load_config()
    path = ROOT / cfg.get("ratings_file", "data/ratings.json")
    if not path.exists():
        return []
    return list(json.loads(path.read_text(encoding="utf-8")).keys())


@lru_cache(maxsize=1)
def load_team_stats() -> dict:
    """Médias por time ({nome: {kills_per_game}}), materializadas na Fase 1.
    Ausente → dict vazio → média da liga (model.py)."""
    cfg = load_config()
    path = ROOT / cfg.get("team_stats_file", "data/team_stats.json")
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def clear_caches() -> None:
    load_config.cache_clear()
    load_teams.cache_clear()
    load_rating_names.cache_clear()
    load_team_stats.cache_clear()


def resolve_team(name: str) -> dict:
    """Nome exato ou substring única → registro do time. Primeiro tenta os
    30 times Tier 1 (teams_lol.json, com região/initial_elo); se não achar,
    cai para os nomes extras vividos em ratings.json (Fase 1 ingeriu mais
    times do Oracle's Elixir do que o Top 30 semeado) — aí devolve só
    {"name": ...}, o Elo real é lido depois em EloModel.ratings. ValueError
    com sugestões quando ambíguo/desconhecido (contrato de erro da
    plataforma)."""
    teams = load_teams()
    low = name.strip().lower()
    for t in teams:
        if t["name"].lower() == low:
            return t
    rating_names = load_rating_names()
    for n in rating_names:
        if n.lower() == low:
            canonical = next(
                (t for t in teams if t["name"].casefold() == n.casefold()),
                None,
            )
            return canonical or {"name": n}

    # Exact lived names must win before substring matching. Otherwise LOUD
    # resolves to the seeded team Cloud9 merely because it is a substring.
    hits = [t for t in teams if low in t["name"].lower()]
    if len(hits) == 1:
        return hits[0]
    rhits = [n for n in rating_names if low in n.lower()]
    if len(rhits) == 1:
        return {"name": rhits[0]}

    sugestao = [t["name"] for t in hits] + rhits
    raise ValueError(f"time desconhecido: {name!r}"
                     + (f" — você quis dizer {sugestao}?" if sugestao else ""))
