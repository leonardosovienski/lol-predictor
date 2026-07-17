"""Domain payload for weekly LoL refresh; deliberately unaware of Scheduler."""
import json
import math
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "data" / "atualiza_semanal.log"
DRIVE_IDS = {2026: "1hnpbrUpBMS1TZI7IovfpKeZfWJH1Aptm"}
WORKSPACE = ROOT.parent
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))
from tools.secret_redaction import collect_sensitive_values, safe_redact_text

SENSITIVE_VALUES = collect_sensitive_values()
PARTIAL_EXIT = 10


def log(msg: str) -> None:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    line = f"{stamp} {safe_redact_text(msg, SENSITIVE_VALUES)}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def download_csv(year: int) -> bool:
    file_id = DRIVE_IDS.get(year)
    if not file_id:
        log(f"  [download] sem id do Drive para {year}")
        return False
    url = f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t"
    destination = ROOT / "data" / "raw" / f"{year}_oe.csv"
    temporary = destination.with_suffix(".tmp")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=300) as response, open(temporary, "wb") as handle:
            handle.write(response.read())
        if temporary.stat().st_size < 1_000_000:
            log(f"  [download] arquivo suspeito ({temporary.stat().st_size} bytes)")
            temporary.unlink(missing_ok=True)
            return False
        temporary.replace(destination)
        log(f"  [download] {destination.name}: {destination.stat().st_size} bytes")
        return True
    except Exception as exc:
        log(f"  [download] FALHOU: {exc}")
        temporary.unlink(missing_ok=True)
        return False


def build_steps():
    return [
        ("ingest", [sys.executable, "-X", "utf8", "-m", "src.ingest_oracle"], 900),
        ("ratings", [sys.executable, "-X", "utf8", str(ROOT / "scripts" / "backtest_walkforward.py")], 900),
    ]


def ratings_valid(started_at: float) -> bool:
    path = ROOT / "data" / "ratings.json"
    try:
        ratings = json.loads(path.read_text(encoding="utf-8"))
        names = [name.casefold() for name in ratings] if isinstance(ratings, dict) else []
        valid = (isinstance(ratings, dict) and bool(ratings)
                 and len(names) == len(set(names))
                 and all(isinstance(value, (int, float))
                         and math.isfinite(float(value))
                         for value in ratings.values()))
        fresh = path.stat().st_mtime >= started_at
        if not valid or not fresh:
            log(f"  [ratings] artefato invalido ou sem refresh nesta execucao: valid={valid} fresh={fresh}")
        return valid and fresh
    except (OSError, ValueError, TypeError) as exc:
        log(f"  [ratings] artefato invalido: {exc}")
        return False


def main() -> int:
    started_at = datetime.now(timezone.utc).timestamp()
    log("=== atualiza_semanal: inicio ===")
    download_ok = download_csv(datetime.now(timezone.utc).year)
    steps_ok = True
    for name, command, timeout in build_steps():
        try:
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
            for line in (result.stdout or "").strip().splitlines()[-2:]:
                log(f"  [{name}] {line}")
            if result.returncode != 0:
                log(f"  [{name}] FALHOU exit {result.returncode}: {(result.stderr or '').strip()[-200:]}")
                steps_ok = False
            else:
                log(f"  [{name}] OK")
        except subprocess.TimeoutExpired:
            log(f"  [{name}] TIMEOUT ({timeout}s)")
            steps_ok = False
        except Exception as exc:
            log(f"  [{name}] EXCECAO: {exc}")
            steps_ok = False
    artifact_ok = ratings_valid(started_at)
    if steps_ok and artifact_ok and download_ok:
        exit_code = 0
    elif steps_ok and artifact_ok:
        exit_code = PARTIAL_EXIT
    else:
        exit_code = 1
    log(f"=== atualiza_semanal: fim (exit {exit_code}) ===")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
