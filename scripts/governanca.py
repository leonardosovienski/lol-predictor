"""Governança da Fase 1 do lol-predictor: controle positivo + pré-registro.

Ordem obrigatória (trava de poder do core): o harness prova que o CRITÉRIO DE
DECISÃO da fase (Brier menor que o baseline + Diebold-Mariano p<0,05) detecta
informação real e rejeita ruído — só então H1-LOL/H2-LOL entram no registro,
e só então o backtest pode rodar.

Braço edge: jogos sintéticos onde o resultado sai de Elos VERDADEIROS que o
modelo conhece (+100 num grupo de times) e o baseline não (Elo achatado) —
o critério tem que dar COMPROVADA. Braço ruído: modelo = baseline + jitter
sem informação — tem que dar REFUTADA.

Uso: python scripts/governanca.py
"""
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from src.model import win_probability                                  # noqa: E402
from predictor_core.measurement.metrics import brier, diebold_mariano  # noqa: E402
from predictor_core.measurement.trials import (                        # noqa: E402
    TrialRegistry, attestation_path_for)
from predictor_core.testing.harness import attest_pipeline_power       # noqa: E402

TRIALS = ROOT / "data" / "trials.json"
SEED = 13
N_GAMES = 1500


def _series(edge: bool, seed: int):
    """[(p_modelo, p_baseline, outcome, loss_m, loss_b)] sintético."""
    rng = random.Random(seed)
    elos_true = {i: 1400 + (100 if i < 10 else 0) + rng.gauss(0, 40)
                 for i in range(30)}
    out = []
    for _ in range(N_GAMES):
        a, b = rng.sample(range(30), 2)
        p_true = win_probability(elos_true[a], elos_true[b])
        y = 0 if rng.random() < p_true else 1
        p_base = 0.5                                     # baseline cego
        if edge:
            p_model = p_true                             # modelo informado
        else:
            p_model = min(0.99, max(0.01, 0.5 + rng.gauss(0, 0.05)))
        lm = -math.log(max(p_model if y == 0 else 1 - p_model, 1e-12))
        lb = -math.log(max(p_base if y == 0 else 1 - p_base, 1e-12))
        out.append((p_model, p_base, y, lm, lb))
    return out


def evaluate(series):
    """O MESMO critério da fase: Brier menor + DM p<0,05."""
    probs_m = [[p, 1 - p] for p, _pb, _y, _lm, _lb in series]
    probs_b = [[pb, 1 - pb] for _p, pb, _y, _lm, _lb in series]
    outs = [y for _p, _pb, y, _lm, _lb in series]
    bm, bb = brier(probs_m, outs), brier(probs_b, outs)
    _stat, pval = diebold_mariano([s[3] for s in series],
                                  [s[4] for s in series])[:2]
    ok = bm < bb and pval < 0.05
    return {"verdict": "COMPROVADA" if ok else "REFUTADA",
            "brier_m": round(bm, 4), "brier_b": round(bb, 4),
            "dm_p": round(pval, 5)}


def main():
    att = attestation_path_for(TRIALS)
    record = attest_pipeline_power(
        evaluate,
        lambda: _series(edge=True, seed=SEED),
        lambda: _series(edge=False, seed=SEED + 1),
        attestation_path=att,
        note=f"criterio Brier<baseline + DM p<0.05; edge=+100 Elo oculto; "
             f"ruido=jitter 5pp; {N_GAMES} jogos/braço; seed {SEED}")
    print(f"controle positivo OK — atestado em {att.name} ({record['passed_at']})")

    reg = TrialRegistry(TRIALS)
    reg.register(
        "h1-lol-elo-mapa-prequential",
        params={"model": "elo-mapa", "k": 32, "seed": "bandas-gpr-2026",
                "default_seed_elo": 1400, "burnin_days": 90,
                "min_team_games": 10,
                "baseline": "elo-semente-congelado (banda regional)",
                "leagues": ["LCK", "LPL", "LEC", "LCS", "LTA N", "LTA S",
                            "LTA", "MSI", "WLDs", "FST", "EWC"],
                "period": "2025-01..2026-07"},
        sharpe=None,
        notes="H1-LOL: Elo por mapa (prequential, prever-antes-de-atualizar) "
              "prevê o vencedor melhor que a banda regional congelada. "
              "COMPROVADA = Brier menor E Diebold-Mariano p<0.05 sobre "
              "log-loss. Métrica probabilística (sem odds na Fase 1a).",
        test_period=["2025-01-12", "2026-07-10"])
    reg.register(
        "h2-lol-kills-normal-por-liga",
        params={"model": "normal-kills", "media": "time expanding (últimos 40)",
                "sigma": "por liga expanding", "linhas": [24.5, 27.5, 30.5],
                "baseline": "média/sigma da liga pura",
                "min_league_games": 30, "period": "2025-01..2026-07"},
        sharpe=None,
        notes="H2-LOL: Normal de abates com médias POR TIME bate a média da "
              "liga pura. COMPROVADA = Brier menor com DM p<0.05 em >=2 das "
              "3 linhas.",
        test_period=["2025-01-12", "2026-07-10"])
    errs = reg.validate()
    if errs:
        sys.exit("schema de trials violado: " + "; ".join(errs))
    print(f"pré-registro OK — {len(reg.load())} tentativa(s):")
    for t in reg.load():
        print(f"  - {t['name']}")


if __name__ == "__main__":
    main()
