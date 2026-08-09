"""Configuração do lol-predictor — carrega config.yaml e resolve paths.

Mesmo padrão do nba/cs-predictor: YAML na raiz é a única fonte de parâmetros;
Shared packages are installed wheels; no path injection occurs here.
"""

import json
import os
import unicodedata
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(os.environ.get("LOL_PROJECT_ROOT", Path(__file__).resolve().parent.parent)).resolve()


@lru_cache(maxsize=1)
def load_config() -> dict:
    configured = Path(os.environ.get("LOL_CONFIG_PATH", "config.yaml"))
    path = configured if configured.is_absolute() else ROOT / configured
    with path.open(encoding="utf-8") as f:
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


def clear_caches() -> None:
    for loader in (load_config, load_teams, load_rating_names):
        clear = getattr(loader, "cache_clear", None)
        if clear is not None:
            clear()


def _identity_key(value: str) -> str:
    """Chave Unicode canônica; não aproxima entidades nem remove acentos."""
    if not isinstance(value, str):
        raise ValueError(f"nome de time deve ser texto, veio {value!r}")
    return unicodedata.normalize("NFC", value).strip().casefold()


def resolve_team(name: str) -> dict:
    """Nome exato ou substring única → registro do time. Primeiro tenta os
    30 times Tier 1 (teams_lol.json, com região/initial_elo); se não achar,
    cai para os nomes extras vividos em ratings.json (Fase 1 ingeriu mais
    times do Oracle's Elixir do que o Top 30 semeado) — aí devolve só
    {"name": ...}, o Elo real é lido depois em EloModel.ratings. ValueError
    com sugestões quando ambíguo/desconhecido (contrato de erro da
    plataforma)."""
    teams = load_teams()
    low = _identity_key(name)
    if not low:
        raise ValueError("nome de time vazio")
    rating_names = load_rating_names()
    exact_teams = [t for t in teams if _identity_key(t["name"]) == low]
    exact_ratings = [n for n in rating_names if _identity_key(n) == low]
    # Duas linhas seed com o mesmo nome normalizado (inclusive em regiões
    # diferentes) são entidades indistinguíveis neste schema: nunca escolha a
    # primeira silenciosamente. O mesmo vale para duas grafias NFC/NFD no JSON.
    if len(exact_teams) > 1 or len(exact_ratings) > 1:
        details = [(t["name"], t.get("region")) for t in exact_teams]
        raise ValueError(f"identidade de time ambígua para {name!r}: teams={details}, ratings={exact_ratings}")
    if exact_teams:
        return exact_teams[0]
    if exact_ratings:
        return {"name": exact_ratings[0]}

    # Exact lived names must win before substring matching. Otherwise LOUD
    # resolves to the seeded team Cloud9 merely because it is a substring.
    hits = [t for t in teams if low in _identity_key(t["name"])]
    rhits = [n for n in rating_names if low in _identity_key(n)]
    # um hit único do Top 30 só vence se ratings.json não tiver OUTRA
    # entidade também batendo — senão é ambíguo (família LOUD/Cloud9)
    if len(hits) == 1:
        extra = [n for n in rhits if _identity_key(n) != _identity_key(hits[0]["name"])]
        if not extra:
            return hits[0]
    # 2+ times do Top 30 batendo já é ambíguo — não cair silenciosamente
    # num nome único do ratings.json (mesma família do bug LOUD/Cloud9)
    if not hits and len(rhits) == 1:
        return {"name": rhits[0]}

    sugestao = [t["name"] for t in hits] + rhits
    raise ValueError(f"time desconhecido: {name!r}" + (f" — você quis dizer {sugestao}?" if sugestao else ""))
