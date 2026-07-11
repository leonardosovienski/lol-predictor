"""Refresh semanal do lol-predictor — pensado para o Task Scheduler.

Sequência (idempotente):
  1. baixa o CSV do ANO CORRENTE do Oracle's Elixir (Drive público; o
     arquivo é atualizado 1x/dia — semanal é mais que suficiente e educado)
  2. python -m src.ingest_oracle          (game_id é PK — upsert)
  3. scripts/backtest_walkforward.py      (re-materializa ratings.json com
     o Elo vivido + calibration.json por liga)

IDs do Drive (descobertos 2026-07-11): 2025=1v6LRphp2kYciU4SXp0PCjEMuev1bDejc,
2026=1hnpbrUpBMS1TZI7IovfpKeZfWJH1Aptm. Se o ano virar, adicionar o novo id.

Log em data/atualiza_semanal.log.
"""
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "data" / "atualiza_semanal.log"
DRIVE_IDS = {2026: "1hnpbrUpBMS1TZI7IovfpKeZfWJH1Aptm"}


def log(msg: str) -> None:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"{stamp} {msg}", flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{stamp} {msg}\n")


def baixa_csv(ano: int) -> bool:
    fid = DRIVE_IDS.get(ano)
    if not fid:
        log(f"  [download] sem id do Drive para {ano} — atualizar DRIVE_IDS")
        return False
    url = (f"https://drive.usercontent.google.com/download?id={fid}"
           f"&export=download&confirm=t")
    destino = ROOT / "data" / "raw" / f"{ano}_oe.csv"
    tmp = destino.with_suffix(".tmp")
    try:
        with urllib.request.urlopen(url, timeout=300) as r, open(tmp, "wb") as f:
            f.write(r.read())
        if tmp.stat().st_size < 1_000_000:      # sanidade: CSV real tem MBs
            log(f"  [download] arquivo suspeito ({tmp.stat().st_size} bytes) "
                "— mantendo o anterior")
            tmp.unlink(missing_ok=True)
            return False
        tmp.replace(destino)
        log(f"  [download] {destino.name}: {destino.stat().st_size} bytes")
        return True
    except Exception as e:
        log(f"  [download] FALHOU: {e} — mantendo o CSV anterior")
        tmp.unlink(missing_ok=True)
        return False


def main() -> int:
    log("=== atualiza_semanal: inicio ===")
    pior = 0 if baixa_csv(datetime.now(timezone.utc).year) else 1
    for nome, cmd, timeout in [
            ("ingest", [sys.executable, "-X", "utf8", "-m",
                        "src.ingest_oracle"], 900),
            ("ratings", [sys.executable, "-X", "utf8",
                         str(ROOT / "scripts" / "backtest_walkforward.py")], 900)]:
        try:
            r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               timeout=timeout)
            for ln in (r.stdout or "").strip().splitlines()[-2:]:
                log(f"  [{nome}] {ln}")
            if r.returncode != 0:
                log(f"  [{nome}] FALHOU exit {r.returncode}: "
                    f"{(r.stderr or '').strip()[-200:]}")
                pior = 1
            else:
                log(f"  [{nome}] OK")
        except Exception as e:
            log(f"  [{nome}] EXCECAO: {e}")
            pior = 1
    log(f"=== atualiza_semanal: fim (exit {pior}) ===")
    return pior


if __name__ == "__main__":
    sys.exit(main())
