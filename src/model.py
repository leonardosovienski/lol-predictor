"""Modelo Elo de LoL — Fase 0 (esqueleto).

LoL é um MOBA com draft, matchups e objetivos, mas a força relativa das
equipes é o preditor mais robusto para começar:

    P(A vence um MAPA) = 1 / (1 + 10^((elo_B − elo_A)/400))

Rating por MAPA; série (BO1/BO3/BO5) pela combinatória exata com mapas
i.i.d. — simplificação declarada da Fase 0 (draft, early game e patch são
extensões da Fase 1+). K por formato: BO1=32, BO3=40, BO5=48.

Totais de abates: total por mapa ≈ Normal(kpg_a + kpg_b, kills_std) — mesma
lógica do nba-predictor (TCL de muitos eventos de abate). Fase 0 usa a média
da liga (config model.league_avg_total_kills) até `data/team_stats.json`
materializar médias reais por time.
"""
import json
from pathlib import Path
from statistics import NormalDist

from .config import ROOT, load_config, load_team_stats, load_teams, resolve_team

K_FACTORS = {"bo1": 32, "bo3": 40, "bo5": 48}
# duração típica de parede de relógio por formato (matures_at do serving)
FORMAT_HOURS = {"bo1": 1.0, "bo3": 2.5, "bo5": 4.0}


def win_probability(elo_a: float, elo_b: float) -> float:
    """P(A vence um mapa) — logística clássica do Elo."""
    return 1.0 / (1.0 + 10.0 ** ((elo_b - elo_a) / 400.0))


def series_probs(p: float, fmt: str) -> dict:
    """Distribuição exata do placar da série dado p = P(A vence um mapa)."""
    q = 1.0 - p
    if fmt == "bo1":
        return {"1-0": p, "0-1": q}
    if fmt == "bo3":
        return {"2-0": p * p, "2-1": 2 * p * p * q,
                "1-2": 2 * q * q * p, "0-2": q * q}
    if fmt == "bo5":
        return {"3-0": p ** 3, "3-1": 3 * p ** 3 * q,
                "3-2": 6 * p ** 3 * q * q,
                "2-3": 6 * q ** 3 * p * p, "1-3": 3 * q ** 3 * p,
                "0-3": q ** 3}
    raise ValueError(f"formato desconhecido: {fmt!r} (use bo1/bo3/bo5)")


class EloModel:
    """Ratings Elo dos times Tier 1 (semente = bandas por liga do GPR).

    `ratings_file` (data/ratings.json), quando existir, sobrepõe as sementes —
    é onde update_ratings persiste a evolução após partidas reais."""

    def __init__(self, ratings_file: Path | str | None = None):
        cfg = load_config()
        self.ratings = {t["name"]: float(t["initial_elo"]) for t in load_teams()}
        self.path = Path(ratings_file) if ratings_file else (
            ROOT / cfg.get("ratings_file", "data/ratings.json"))
        if self.path.exists():
            self.ratings.update(json.loads(self.path.read_text(encoding="utf-8")))

    def _elo(self, name: str) -> tuple[str, float]:
        official = resolve_team(name)["name"]
        return official, self.ratings[official]

    def predict_match(self, team_a: str, team_b: str, format: str = "bo3") -> dict:
        fmt = format.lower()
        if fmt not in K_FACTORS:
            raise ValueError(f"formato desconhecido: {format!r} (use bo1/bo3/bo5)")
        a, elo_a = self._elo(team_a)
        b, elo_b = self._elo(team_b)
        if a == b:
            raise ValueError("um time não joga contra si mesmo")
        p_map = win_probability(elo_a, elo_b)
        dist = series_probs(p_map, fmt)
        prob_a = sum(pr for placar, pr in dist.items()
                     if int(placar.split("-")[0]) > int(placar.split("-")[1]))
        mapas = sum((int(s.split("-")[0]) + int(s.split("-")[1])) * pr
                    for s, pr in dist.items())
        return {"team_a": a, "team_b": b, "format": fmt,
                "elo_a": round(elo_a, 1), "elo_b": round(elo_b, 1),
                "p_map_a": round(p_map, 4),
                "prob_team_a": round(prob_a, 4),
                "prob_team_b": round(1.0 - prob_a, 4),
                # zebra explícita: o lado de menor probabilidade (aposta de valor
                # em odds infladas é hipótese da Fase 1, aqui é só leitura)
                "prob_underdog": round(min(prob_a, 1.0 - prob_a), 4),
                "underdog": b if prob_a >= 0.5 else a,
                "mapas_esperados": round(mapas, 2),
                "score_probs": {s: round(pr, 4) for s, pr in dist.items()},
                "model": "elo-fase0"}

    def predict_kills_total(self, team_a: str, team_b: str,
                            line: float | None = None) -> dict:
        """Total de abates de UM MAPA ≈ Normal(kpg_a + kpg_b, kills_std).

        Fase 0: sem histórico, cada time contribui metade da média da liga
        (config); `data/team_stats.json` ({nome: {kills_per_game}}) passa a
        diferenciar quando a Fase 1 materializar."""
        cfg = load_config()
        mc = cfg["model"]
        line = float(cfg["default_kills_line"]) if line is None else float(line)
        half = float(mc["league_avg_total_kills"]) / 2.0
        std = float(mc["kills_std"])
        a = resolve_team(team_a)["name"]
        b = resolve_team(team_b)["name"]
        stats = load_team_stats()
        kpg_a = float(stats.get(a, {}).get("kills_per_game", half))
        kpg_b = float(stats.get(b, {}).get("kills_per_game", half))
        total = kpg_a + kpg_b
        p_over = 1.0 - NormalDist(mu=total, sigma=std).cdf(line)
        return {"team_a": a, "team_b": b, "line": line,
                "total_projetado": round(total, 1),
                "kpg_a": round(kpg_a, 1), "kpg_b": round(kpg_b, 1),
                "over_prob": round(p_over, 4),
                "under_prob": round(1.0 - p_over, 4),
                "kills_std": std, "model": "kills-normal-fase0"}

    def update_ratings(self, team_a: str, team_b: str,
                       result_a: int, result_b: int) -> dict:
        """Atualiza o Elo após partida real. K pelo formato inferido do placar
        (soma ≤1 → BO1; ≤3 → BO3; senão BO5). Persiste em ratings_file."""
        a, elo_a = self._elo(team_a)
        b, elo_b = self._elo(team_b)
        total = result_a + result_b
        fmt = "bo1" if total <= 1 else ("bo3" if total <= 3 else "bo5")
        k = K_FACTORS[fmt]
        s_a = 1.0 if result_a > result_b else 0.0
        e_a = win_probability(elo_a, elo_b)
        delta = k * (s_a - e_a)
        self.ratings[a] = elo_a + delta
        self.ratings[b] = elo_b - delta
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.ratings, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        return {"team_a": a, "team_b": b, "format": fmt, "k": k,
                "delta": round(delta, 2),
                "elo_a": round(self.ratings[a], 1),
                "elo_b": round(self.ratings[b], 1)}
