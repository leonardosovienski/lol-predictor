"""CI minima local do lol-predictor — 3 barreiras (Fase 0).

  1. pytest — a suite inteira tem que passar.
  2. Encoding — qualquer .ps1 do repo precisa ser ASCII puro (licao do wc).
  3. Parse dos arquivos criticos — config.yaml valido, teams_lol.json com 30
     times unicos das 4 ligas, .env.example presente, e smoke do serving:
     predict --json com probabilidades somando ~1 e abates no intervalo.

Uso:
    python scripts/ci_check.py            # tudo
    python scripts/ci_check.py --fast     # pula o pytest
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
failures: list[str] = []


def check_pytest() -> None:
    print("[1/3] pytest (suite completa)...")
    r = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q",
                        "-W", "error"],
                       cwd=ROOT, capture_output=True, text=True)
    tail = (r.stdout or "").strip().splitlines()[-1:] or ["(sem saida)"]
    print(f"      {tail[0]}")
    if r.returncode != 0:
        failures.append(f"pytest falhou (exit {r.returncode}) — rode: python -m pytest tests/")


def check_ps1_ascii() -> None:
    print("[2/3] encoding de scripts .ps1 (ASCII puro)...")
    ps1 = [p for p in ROOT.rglob("*.ps1")
           if ".venv" not in p.parts and ".git" not in p.parts]
    for p in ps1:
        try:
            p.read_bytes().decode("ascii")
        except UnicodeDecodeError as e:
            failures.append(f"{p.relative_to(ROOT)}: nao-ASCII no byte {e.start}")
    print(f"      {len(ps1)} arquivo(s) .ps1 verificados")


def check_critical_files() -> None:
    print("[3/3] parse dos arquivos criticos + smoke do serving...")
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        for key in ("game", "default_format", "default_kills_line",
                    "k_factor_base", "teams_file"):
            if key not in cfg:
                failures.append(f"config.yaml sem a chave obrigatoria '{key}'")
    except Exception as e:
        failures.append(f"config.yaml ilegivel: {e}")

    try:
        data = json.loads((ROOT / "data" / "teams_lol.json").read_text(encoding="utf-8"))
        teams = data["teams"]
        if len(teams) != 30 or len({t["name"] for t in teams}) != 30:
            failures.append(f"teams_lol.json: esperava 30 times unicos, achei {len(teams)}")
        if {t["region"] for t in teams} != {"LCK", "LPL", "LEC", "LCS"}:
            failures.append("teams_lol.json: ligas fora do esperado (LCK/LPL/LEC/LCS)")
    except Exception as e:
        failures.append(f"teams_lol.json ilegivel: {e}")

    try:
        ratings = json.loads((ROOT / "data" / "ratings.json").read_text(encoding="utf-8"))
        folded = [name.casefold() for name in ratings]
        if len(folded) != len(set(folded)):
            failures.append("ratings.json tem identidades duplicadas por capitalizacao")
    except Exception as e:
        failures.append(f"ratings.json ilegivel: {e}")

    try:
        ledger_path = ROOT / "data" / "predictions.jsonl"
        ledger = [json.loads(line) for line in ledger_path.read_text(
            encoding="utf-8").splitlines() if line.strip()]
        ids = [row["prediction_id"] for row in ledger if row.get("prediction_id")]
        lifecycle_keys = [(row.get("prediction_id"), row.get("lifecycle_status"))
                          for row in ledger if row.get("prediction_id")]
        pre = {row["prediction_id"] for row in ledger
               if row.get("lifecycle_status") == "PRE_EVENT"}
        matured = {row["prediction_id"] for row in ledger
                   if row.get("lifecycle_status") == "MATURED"}
        if len(ids) != len(pre) + len(matured):
            failures.append("prediction ledger tem lifecycle desconhecido com prediction_id")
        if len(lifecycle_keys) != len(set(lifecycle_keys)):
            failures.append("prediction ledger tem lifecycle duplicado")
        if matured - pre:
            failures.append("prediction ledger tem MATURED sem PRE_EVENT")
    except Exception as e:
        failures.append(f"prediction ledger ilegivel: {e}")

    if not (ROOT / ".env.example").exists():
        failures.append(".env.example ausente")

    env = dict(os.environ)
    tmp = Path(tempfile.gettempdir())
    env["PREDICTIONS_LOG_PATH"] = str(tmp / "lol_ci_smoke_pred.jsonl")
    env["PREDICTOR_EVENTS_PATH"] = str(tmp / "lol_ci_smoke_events.jsonl")
    # The CLI is fail-closed without a published source snapshot.  CI creates
    # a disposable, valid fixture rather than weakening that production gate.
    from src.data.ingestion import SnapshotStore
    fixture_root = Path(tempfile.mkdtemp(prefix="lol-ci-ingestion-"))
    fixture_csv = fixture_root / "oracle.csv"
    fixture_csv.write_text(
        "gameid,league,teamname,date,result\n"
        "ci-1,LCK,T1,2026-07-21,1\nci-2,LCK,Gen.G,2026-07-21,0\n",
        encoding="utf-8")
    SnapshotStore(fixture_root / "ingestion").publish(fixture_csv, source="ci-fixture")
    env["LOL_INGESTION_ROOT"] = str(fixture_root / "ingestion")
    # --kills-league é exigido sempre que data/calibration.json existir
    # localmente (gate deliberado — ver test_kills_uses_published_league_
    # calibration em tests/test_model.py); em checkout limpo o arquivo nem
    # existe e a flag é ignorada, então passá-la sempre é seguro nos dois
    # estados.
    r = subprocess.run([sys.executable, "-X", "utf8", "-m", "src.predict",
                        "T1", "Gen.G", "--format", "bo3",
                        "--kills-league", "LCK", "--json"],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    if r.returncode != 0:
        failures.append(f"predict --json saiu com exit {r.returncode}: "
                        f"{(r.stderr or '')[-200:]}")
    else:
        try:
            out = json.loads(r.stdout)
            soma = out["prob_team_a"] + out["prob_team_b"]
            if not 0.999 <= soma <= 1.001:
                failures.append(f"prob_team_a+prob_team_b = {soma:.4f} (esperado ~1)")
            if not 15 <= out["total_abates_projetado"] <= 40:
                failures.append(f"total_abates_projetado = "
                                f"{out['total_abates_projetado']} (esperado 15-40)")
            print(f"      smoke: {out['team_a']} {out['prob_team_a']:.1%} x "
                  f"{out['prob_team_b']:.1%} {out['team_b']} | "
                  f"abates {out['total_abates_projetado']}")
        except (ValueError, KeyError) as e:
            failures.append(f"predict --json nao produziu o dict esperado ({e})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="pula o pytest")
    args = ap.parse_args()

    if not args.fast:
        check_pytest()
    else:
        print("[1/3] pytest PULADO (--fast)")
    check_ps1_ascii()
    check_critical_files()

    print()
    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        print(f"\nCI: {len(failures)} falha(s) — commit bloqueado.")
        return 1
    print("CI: todas as barreiras verdes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
