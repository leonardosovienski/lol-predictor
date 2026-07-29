"""Coleta manual read-only da fonte de mercado LoL para shadow da Fase 1b."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from predictor_core.data.contracts import DataUnavailableError  # noqa: E402
from predictor_core.kernel.jsonl_store import JsonlStore  # noqa: E402
from src.config import resolve_team  # noqa: E402
from src.data.polymarket_provider import PolymarketProvider  # noqa: E402
from src.h4_gate import H4Error, assert_h4_open  # noqa: E402
from src.model import EloModel  # noqa: E402


@contextmanager
def _output_lock(path: Path):
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b") as lock:
        lock.seek(0, os.SEEK_END)
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def append_once(path: Path, quote: dict) -> bool:
    """Append idempotente; o lock cobre leitura, dedupe e escrita."""
    with _output_lock(path):
        store = JsonlStore(path)
        if any(row.get("quote_id") == quote["quote_id"] for row in store):
            return False
        store.append(quote)
        return True


def attach_model_snapshot(quote: dict) -> dict:
    """Congela a previsão e o hash exato de ratings junto da cotação."""
    model = EloModel()
    prediction = model.predict_match(
        quote["team_a"], quote["team_b"], quote["format"])
    ratings_sha256 = hashlib.sha256(model.path.read_bytes()).hexdigest()
    return {**quote,
            "model_probability_a": prediction["prob_team_a"],
            "model_probability_b": prediction["prob_team_b"],
            "model_name": prediction["model"],
            "ratings_sha256": ratings_sha256}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect one PRE_EVENT LoL market quote")
    parser.add_argument("team_a")
    parser.add_argument("team_b")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "data" / "shadow" / "market_quotes.jsonl")
    args = parser.parse_args(argv)
    try:
        assert_h4_open(ROOT / "data" / "h4_v2_closure.json")
        team_a = resolve_team(args.team_a)["name"]
        team_b = resolve_team(args.team_b)["name"]
        if team_a == team_b:
            raise ValueError("um time não joga contra si mesmo")
        quote = attach_model_snapshot(
            PolymarketProvider().fetch_match(team_a, team_b))
        appended = append_once(args.output, quote)
    except (DataUnavailableError, H4Error, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps({**quote, "appended": appended},
                     ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
