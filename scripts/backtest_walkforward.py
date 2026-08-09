"""Backtest PREQUENTIAL do lol-predictor (Fase 1) — banco read-only.

Desenho (sem lookahead por construção):
- jogos (mapas) em ordem cronológica; para cada um, PREVER antes de ATUALIZAR;
- Elo por mapa, K = k_factor_base (config); semente = teams_lol.json (bandas
  do GPR) para os 30 conhecidos, default_seed_elo para o resto;
- burn-in (config backtest.burnin_days) fora da medição; métrica só conta
  jogo onde ambos os times têm >= min_team_games mapas de histórico;
- VENCEDOR (H1-LOL): Brier/log-loss/calibração (core) do modelo vs dois
  baselines — coin-flip e "banda regional" (Elo SEMENTE congelado, nunca
  atualizado). Diebold-Mariano modelo vs banda (a comparação pré-registrada);
- ABATES (H2-LOL): total do mapa ~ N(kpg_a+kpg_b, sigma_liga), médias/sigma
  EXPANDING por liga e por time, forward-only; Brier binário do Over nas
  linhas do config vs baseline "média da liga" pura. DM por linha.

Saídas: data/walkforward_summary.json + relatório no stdout. Ao final,
materializa data/ratings.json (Elo vivido), pesquisa de kills fora do serving
e diagnóstico H1 por competição. Platt e kills por time não são ativados.
"""

import argparse
import json
import statistics as st
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import NormalDist

ROOT = Path(__file__).resolve().parent.parent

from predictor_core.measurement.metrics import brier, calibration_table, diebold_mariano, log_loss  # noqa: E402

from src import db  # noqa: E402
from src.config import load_config, load_teams  # noqa: E402
from src.data.riot_provider import OracleProvider  # noqa: E402
from src.model import win_probability  # noqa: E402


def run(cfg, conn):
    bt = cfg["backtest"]
    k = float(cfg["k_factor_base"])
    seed_default = float(bt["default_seed_elo"])
    min_games = int(bt["min_team_games"])
    lines = [float(x) for x in bt["kills_lines"]]
    min_lg = int(bt["min_league_games_kills"])

    seeds = {t["name"]: float(t["initial_elo"]) for t in load_teams()}
    canonical_case = {name.casefold(): name for name in seeds}
    elo = dict(seeds)  # vivido (atualiza)
    banda = dict(seeds)  # baseline congelado
    n_games_seen = defaultdict(int)

    rows = conn.execute(
        "SELECT game_id, date, league, team_a, team_b, winner, kills_a, kills_b FROM games ORDER BY date, game_id"
    ).fetchall()
    if not rows:
        sys.exit("banco vazio — rode python -m src.ingest_oracle")
    cut = (datetime.fromisoformat(rows[0][1]) + timedelta(days=int(bt["burnin_days"]))).isoformat(sep=" ")

    # acumuladores kills forward-only
    lg_totals = defaultdict(list)  # liga -> [total kills]
    team_kills = defaultdict(list)  # time -> [kills do time]

    probs_m, probs_b, outs = [], [], []  # vencedor: modelo, banda, outcome
    measured_leagues = []
    loss_m, loss_b = [], []  # log-loss por jogo (p/ DM)
    kills_eval = {ln: {"pm": [], "pb": [], "y": []} for ln in lines}

    for gid, d, league, a, b, winner, ka, kb in rows:
        a = canonical_case.get(a.casefold(), a)
        b = canonical_case.get(b.casefold(), b)
        ea = elo.get(a, seed_default)
        eb = elo.get(b, seed_default)
        p_model = win_probability(ea, eb)
        p_banda = win_probability(banda.get(a, seed_default), banda.get(b, seed_default))
        y = 0 if winner == "a" else 1  # classe 0 = time A vence
        medir = d >= cut and n_games_seen[a] >= min_games and n_games_seen[b] >= min_games
        if medir:
            probs_m.append([p_model, 1.0 - p_model])
            probs_b.append([p_banda, 1.0 - p_banda])
            outs.append(y)
            measured_leagues.append(league)
            loss_m.append(-_ln(p_model if y == 0 else 1 - p_model))
            loss_b.append(-_ln(p_banda if y == 0 else 1 - p_banda))

        # ---- abates (prever antes de acumular) ----
        if ka is not None and kb is not None:
            total = ka + kb
            lt = lg_totals[league]
            if medir and len(lt) >= min_lg:
                mu_lg = st.mean(lt)
                sd_lg = st.stdev(lt)
                kpg_a = st.mean(team_kills[a][-40:]) if len(team_kills[a]) >= min_games else mu_lg / 2
                kpg_b = st.mean(team_kills[b][-40:]) if len(team_kills[b]) >= min_games else mu_lg / 2
                for ln in lines:
                    pm = 1.0 - NormalDist(mu=kpg_a + kpg_b, sigma=sd_lg).cdf(ln)
                    pb = 1.0 - NormalDist(mu=mu_lg, sigma=sd_lg).cdf(ln)
                    kills_eval[ln]["pm"].append(pm)
                    kills_eval[ln]["pb"].append(pb)
                    kills_eval[ln]["y"].append(1 if total > ln else 0)
            lt.append(total)
            team_kills[a].append(ka)
            team_kills[b].append(kb)

        # ---- update Elo (depois de prever) ----
        s_a = 1.0 if winner == "a" else 0.0
        delta = k * (s_a - p_model)
        elo[a] = ea + delta
        elo[b] = eb - delta
        n_games_seen[a] += 1
        n_games_seen[b] += 1

    return {
        "probs_m": probs_m,
        "probs_b": probs_b,
        "outs": outs,
        "loss_m": loss_m,
        "loss_b": loss_b,
        "kills": kills_eval,
        "elo": elo,
        "team_kills": team_kills,
        "lg_totals": lg_totals,
        "measured_leagues": measured_leagues,
        "n_total": len(rows),
    }


def _ln(p, eps=1e-12):
    import math

    return math.log(min(max(p, eps), 1.0))


def _snapshot_database(snapshot: Path, oos_cutoff: str | None = None):
    """Build an isolated database containing exactly one immutable snapshot."""
    handle = tempfile.NamedTemporaryFile(prefix="lol-snapshot-", suffix=".db", delete=False)
    handle.close()
    path = Path(handle.name)
    conn = db.connect(str(path))
    provider = OracleProvider(snapshot.parent, leagues=load_config().get("oracle", {}).get("leagues"))
    batch = []
    for game in provider.iter_games():
        batch.append(game)
        if len(batch) >= 500:
            db.upsert_games(conn, batch)
            batch = []
    if batch:
        db.upsert_games(conn, batch)
    if oos_cutoff is not None:
        conn.execute("DELETE FROM games WHERE date >= ?", (oos_cutoff.replace("T", " ").replace("Z", ""),))
        conn.commit()
    return conn, path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the frozen LoL walk-forward evaluation")
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--data-root", type=Path, default=ROOT / "data")
    parser.add_argument("--oos-cutoff")
    args = parser.parse_args(argv)
    cfg = load_config()
    temporary = None
    if args.snapshot is not None:
        if not args.snapshot.is_file():
            parser.error("--snapshot must point to an existing CSV")
        conn, temporary = _snapshot_database(args.snapshot, args.oos_cutoff)
    else:
        conn = db.connect(str(ROOT / cfg["database"]), read_only=True)
    try:
        r = run(cfg, conn)
    finally:
        conn.close()
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    n = len(r["outs"])
    print(f"PREQUENTIAL LoL — {r['n_total']} mapas processados, {n} na janela de medição")

    summary = {"n_mapas": r["n_total"], "n_medidos": n}

    # ---- H1-LOL: vencedor ----
    br_m = brier(r["probs_m"], r["outs"])
    br_b = brier(r["probs_b"], r["outs"])
    ll_m = log_loss(r["probs_m"], r["outs"])
    ll_b = log_loss(r["probs_b"], r["outs"])
    acc_m = st.mean(1 if (p[0] >= 0.5) == (y == 0) else 0 for p, y in zip(r["probs_m"], r["outs"]))
    dm_stat, dm_p = diebold_mariano(r["loss_m"], r["loss_b"])[:2]
    melhor = br_m < br_b
    h1_ok = melhor and dm_p < 0.05
    print(f"\nH1-LOL (vencedor): Brier modelo {br_m:.4f} vs banda {br_b:.4f} (coin-flip 0.5000)")
    print(f"  log-loss {ll_m:.4f} vs {ll_b:.4f} | acerto {acc_m:.1%} | DM stat {dm_stat:+.2f} p={dm_p:.4f}")
    print(f"  VEREDITO H1-LOL: {'COMPROVADA' if h1_ok else 'REFUTADA'} (Brier menor E DM p<0.05)")
    calib = calibration_table([p[0] for p in r["probs_m"]], [1 if y == 0 else 0 for y in r["outs"]])
    print("  calibração (P time A):")
    for c in calib:
        print(
            f"    {c['bin_lo']:.1f}-{c['bin_hi']:.1f}: n={c['n']:>4} "
            f"prev {c['mean_pred']:.2f} vs real {c['obs_freq']:.2f}"
        )
    summary["h1"] = {
        "brier_modelo": round(br_m, 4),
        "brier_banda": round(br_b, 4),
        "logloss_modelo": round(ll_m, 4),
        "logloss_banda": round(ll_b, 4),
        "acerto": round(acc_m, 4),
        "dm_stat": round(dm_stat, 3),
        "dm_p": round(dm_p, 5),
        "verdict": "COMPROVADA" if h1_ok else "REFUTADA",
        "calibracao": calib,
    }

    regional = {}
    for league in sorted(set(r["measured_leagues"])):
        idx = [i for i, value in enumerate(r["measured_leagues"]) if value == league]
        probs = [r["probs_m"][i] for i in idx]
        outcomes = [r["outs"][i] for i in idx]
        regional[league] = {
            "n": len(idx),
            "brier_multiclasse": round(brier(probs, outcomes), 4),
            "acerto": round(st.mean(1 if (p[0] >= 0.5) == (y == 0) else 0 for p, y in zip(probs, outcomes)), 4),
        }
    summary["h1"]["por_competicao"] = regional

    # ---- H2-LOL: abates ----
    print("\nH2-LOL (total de abates, Normal por time vs média da liga):")
    h2 = {}
    ok_lines = 0
    for ln, ev in r["kills"].items():
        if not ev["y"]:
            continue
        bm = brier([[p, 1 - p] for p in ev["pm"]], [0 if y else 1 for y in ev["y"]])
        bb = brier([[p, 1 - p] for p in ev["pb"]], [0 if y else 1 for y in ev["y"]])
        lm = [-_ln(p if y else 1 - p) for p, y in zip(ev["pm"], ev["y"])]
        lb = [-_ln(p if y else 1 - p) for p, y in zip(ev["pb"], ev["y"])]
        _stat, pval = diebold_mariano(lm, lb)[:2]
        win = bm < bb
        ok_lines += int(win and pval < 0.05)
        print(
            f"  linha {ln}: n={len(ev['y'])} | Brier modelo {bm:.4f} vs "
            f"liga {bb:.4f} | DM p={pval:.4f} "
            f"{'← modelo vence' if win and pval < 0.05 else ''}"
        )
        h2[str(ln)] = {
            "n": len(ev["y"]),
            "brier_modelo": round(bm, 4),
            "brier_liga": round(bb, 4),
            "dm_p": round(pval, 5),
        }
    h2_ok = ok_lines >= 2  # maioria das 3 linhas
    print(
        f"  VEREDITO H2-LOL: {'COMPROVADA' if h2_ok else 'REFUTADA'} ({ok_lines}/3 linhas com Brier menor e DM p<0.05)"
    )
    summary["h2"] = {"linhas": h2, "linhas_vencidas": ok_lines, "verdict": "COMPROVADA" if h2_ok else "REFUTADA"}

    # ---- materialização do serving (Elo vivido + stats por time/liga) ----
    data = args.data_root
    data.mkdir(parents=True, exist_ok=True)
    (data / "ratings.json").write_text(
        json.dumps({t: round(v, 1) for t, v in sorted(r["elo"].items())}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    # H2 REFUTADA (2026-07-11): média por time PERDE da média da liga — o
    # arquivo vai para *_pesquisa.json de propósito, para o serving NÃO o
    # consumir. O serving está travado no baseline agregado validado.
    stats = {t: {"kills_per_game": round(st.mean(ks[-40:]), 2)} for t, ks in r["team_kills"].items() if len(ks) >= 10}
    (data / "team_stats_pesquisa.json").write_text(
        json.dumps(dict(sorted(stats.items())), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    ligas = {
        lg: {"media_total_kills": round(st.mean(v), 2), "sigma": round(st.stdev(v), 2), "n": len(v)}
        for lg, v in r["lg_totals"].items()
        if len(v) >= 30
    }
    (data / "calibration.json").write_text(json.dumps(ligas, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"\nserving materializado: ratings.json ({len(r['elo'])} times), "
        f"calibration.json ({len(ligas)} ligas); team_stats_pesquisa.json "
        f"({len(stats)}) NÃO consumido pelo serving (H2 refutada)"
    )

    (data / "walkforward_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("artefato: walkforward_summary.json")
    return 0


if __name__ == "__main__":
    main()
