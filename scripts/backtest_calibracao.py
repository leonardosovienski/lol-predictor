"""Tentativa N+1: Elo + Platt scaling prequential (LoL, calibração).

Igual ao cs-predictor, mas no nível do MAPA (a unidade medida pelo backtest
da Fase 1). Motivação: subconfiança leve no favorito (faixa 0,2-0,3 prevista
→ 0,34 real) — espera-se a>1 (afiar), o inverso do CS.

Governança: registra `h3-lol-elo-platt-prequential` ANTES do veredito.
COMPROVADA = Brier menor + DM p<0,05. Se comprovada, materializa
data/calibration_platt.json (o serving calibra p_map antes da combinatória
de série — consistente com a unidade medida).
"""
import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

from src import db                                     # noqa: E402
from src.calibration import PlattCalibrator            # noqa: E402
from src.config import load_config                     # noqa: E402
from predictor_core.measurement.metrics import (       # noqa: E402
    brier, calibration_table, diebold_mariano)
from predictor_core.measurement.trials import TrialRegistry   # noqa: E402

from backtest_walkforward import run as run_prequential, _ln   # noqa: E402

MIN_FIT = 300
REFIT_EVERY = 200


def calibrated_stream(probs_m, outs):
    cal = PlattCalibrator()
    fitted = False
    out, hist_p, hist_y = [], [], []
    for pv, y in zip(probs_m, outs):
        p = pv[0]
        y_bin = 1 if y == 0 else 0
        out.append(cal.apply(p) if fitted else p)
        hist_p.append(p)
        hist_y.append(y_bin)
        if len(hist_p) >= MIN_FIT and (len(hist_p) % REFIT_EVERY == 0
                                       or not fitted):
            cal = PlattCalibrator().fit(hist_p, hist_y)
            fitted = True
    return out


def main():
    cfg = load_config()
    reg = TrialRegistry(ROOT / "data" / "trials.json")
    nome = "h3-lol-elo-platt-prequential"
    params = {"model": "elo-mapa+platt", "nivel": "mapa",
              "platt": {"min_fit": MIN_FIT, "refit_every": REFIT_EVERY,
                        "janela": "expanding forward-only"},
              "base": "h1-lol-elo-mapa-prequential (mesmo Elo, mesma passada)",
              "period": "2025-01..2026-07"}
    if nome not in {t["name"] for t in reg.load()}:
        reg.register(nome, params=params, sharpe=None,
                     notes="N+1: Platt sobre a prob de MAPA do Elo (motivado "
                           "pela subconfiança no favorito do relatório da "
                           "Fase 1 — espera-se a>1). COMPROVADA = Brier menor "
                           "+ DM p<0.05.",
                     test_period=["2025-01-12", "2026-07-10"])
        print(f"trial {nome} pré-registrada")

    conn = db.connect(str(ROOT / cfg["database"]), read_only=True)
    try:
        r = run_prequential(cfg, conn)
    finally:
        conn.close()
    outs = r["outs"]
    raw = [p[0] for p in r["probs_m"]]
    cal = calibrated_stream(r["probs_m"], outs)
    n = len(outs)

    br_raw = brier(r["probs_m"], outs)
    br_cal = brier([[p, 1 - p] for p in cal], outs)
    loss_cal = [-_ln(p if y == 0 else 1 - p) for p, y in zip(cal, outs)]
    dm_stat, dm_p = diebold_mariano(loss_cal, r["loss_m"])[:2]
    ok = br_cal < br_raw and dm_p < 0.05
    print(f"\nH3-LOL (Platt prequential, mapa): n={n}")
    print(f"  Brier cru {br_raw:.4f} → calibrado {br_cal:.4f} | "
          f"DM stat {dm_stat:+.2f} p={dm_p:.5f}")
    print(f"  VEREDITO: {'COMPROVADA' if ok else 'REFUTADA'}")
    tab = calibration_table(cal, [1 if y == 0 else 0 for y in outs])
    for c in tab:
        print(f"    {c['bin_lo']:.1f}-{c['bin_hi']:.1f}: n={c['n']:>4} "
              f"prev {c['mean_pred']:.2f} vs real {c['obs_freq']:.2f}")

    t = next(t for t in reg.load() if t["name"] == nome)
    reg.register(nome, params=t["params"], sharpe=None,
                 notes=t["notes"] + f" | RESULTADO 2026-07-11: "
                 f"{'COMPROVADA' if ok else 'REFUTADA'} — Brier {br_raw:.4f} "
                 f"-> {br_cal:.4f}, DM p={dm_p:.5f}, n={n}.",
                 test_period=t.get("test_period"))

    if ok:
        full = PlattCalibrator().fit(raw, [1 if y == 0 else 0 for y in outs])
        full.save(ROOT / "data" / "calibration_platt.json",
                  meta={"fitted_on": n, "nivel": "mapa",
                        "brier_raw": round(br_raw, 4),
                        "brier_cal": round(br_cal, 4), "trial": nome})
        print(f"\nserving: calibration_platt.json materializado "
              f"(a={full.a:.4f}, b={full.b:.4f})")
    (ROOT / "data" / "calibracao_summary.json").write_text(
        json.dumps({"n": n, "brier_raw": round(br_raw, 4),
                    "brier_cal": round(br_cal, 4), "dm_p": round(dm_p, 6),
                    "verdict": "COMPROVADA" if ok else "REFUTADA",
                    "calibracao_pos": tab}, ensure_ascii=False, indent=2)
        + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
