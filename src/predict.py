"""Serving de previsão de partidas de LoL — Fase 0.

Uso:
    python -m src.predict T1 Gen.G --format bo3 --json
    python -m src.predict T1 Gen.G --market kills
    python -m src.predict "Bilibili Gaming" "G2 Esports" --format bo5

Contratos do core desde o dia zero (padrão da plataforma): PredictionPoint,
emit_event (domínio "lol") e log append-only com override por env.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import ROOT, load_config           # injeta vendor/ no sys.path
from .model import FORMAT_HOURS, EloModel

from predictor_core.data.contracts import PredictionPoint
from predictor_core.kernel.obs import emit_event

_DOMAIN = "lol"


def _log_path() -> Path:
    # Ad hoc do CLI NUNCA escreve em data/predictions.jsonl: aquele ledger é
    # o protocolo oficial versionado (hash congelado na governança).
    return Path(os.environ.get("PREDICTIONS_LOG_PATH",
                               ROOT / "data" / "predictions_adhoc.jsonl"))


def run(team_a: str, team_b: str, *, fmt: str = "bo3",
        market: str = "winner", kills_line: float | None = None,
        now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    model = EloModel()
    r = model.predict_match(team_a, team_b, fmt)
    kills = model.predict_kills_total(team_a, team_b, kills_line)
    r["total_abates_projetado"] = kills["total_projetado"]
    r["kills"] = kills
    r["market"] = market

    point = PredictionPoint(
        predicted_at=now,
        matures_at=now + timedelta(hours=FORMAT_HOURS[fmt]),
        value={"prob_team_a": r["prob_team_a"], "format": fmt,
               "total_abates_projetado": r["total_abates_projetado"]},
        metadata={"team_a": r["team_a"], "team_b": r["team_b"],
                  "market": market, "model": r["model"]})
    r["predicted_at"] = point.predicted_at.isoformat(timespec="seconds")
    r["matures_at"] = point.matures_at.isoformat(timespec="seconds")

    log = _log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

    try:
        emit_event(_DOMAIN, "prediction",
                   metrics={"prob_team_a": r["prob_team_a"],
                            "total_abates_projetado": r["total_abates_projetado"]},
                   metadata={"team_a": r["team_a"], "team_b": r["team_b"],
                             "format": fmt, "market": market,
                             "model": r["model"]})
    except Exception:
        pass    # telemetria nunca derruba o serving
    return r


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Previsão de partida de LoL (Elo, Fase 0)")
    ap.add_argument("team_a")
    ap.add_argument("team_b")
    ap.add_argument("--format", default=None, choices=["bo1", "bo3", "bo5"],
                    help="formato da série (default: config default_format)")
    ap.add_argument("--market", default="winner", choices=["winner", "kills"],
                    help="mercado a exibir (winner = moneyline; kills = totais)")
    ap.add_argument("--kills-line", type=float, default=None,
                    help="linha de abates (default: config default_kills_line)")
    ap.add_argument("--json", action="store_true", help="saída estruturada")
    args = ap.parse_args(argv)

    cfg = load_config()
    fmt = args.format or cfg.get("default_format", "bo3")
    try:
        r = run(args.team_a, args.team_b, fmt=fmt, market=args.market,
                kills_line=args.kills_line)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0
    print(f"{cfg['game']} {fmt.upper()} — {r['team_a']} vs {r['team_b']}")
    print(f"  Elo: {r['elo_a']:.0f} x {r['elo_b']:.0f} "
          f"(P mapa {r['p_map_a']:.1%})")
    print(f"  série: {r['team_a']} {r['prob_team_a']:.1%} | "
          f"{r['team_b']} {r['prob_team_b']:.1%} | "
          f"zebra {r['underdog']} {r['prob_underdog']:.1%} | "
          f"mapas esperados {r['mapas_esperados']:.2f}")
    k = r["kills"]
    print(f"  abates (mapa 1, linha {k['line']}): total projetado "
          f"{k['total_projetado']:.1f} | Over {k['over_prob']:.1%} | "
          f"Under {k['under_prob']:.1%}  (σ={k['kills_std']:.0f})")
    print("  [Fase 0: Elo por bandas de liga + média de abates da liga — "
          "sem histórico ainda]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
