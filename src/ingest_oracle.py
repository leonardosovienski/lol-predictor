"""Ingestão Oracle's Elixir → data/lol.db (Fase 1).

Lê os CSVs locais de data/raw/, filtra as ligas do config e grava a tabela
`games` (1 linha por mapa). Idempotente (game_id é PK).

Uso: python -m src.ingest_oracle
"""
import sys

from . import db
from .config import ROOT, load_config
from .data.riot_provider import OracleProvider


def run() -> None:
    cfg = load_config()
    provider = OracleProvider(ROOT / "data" / "raw",
                              leagues=cfg.get("oracle", {}).get("leagues"))
    if not provider.health_check():
        sys.exit("data/raw sem CSVs — baixe do Drive do Oracle's Elixir")
    conn = db.connect(str(ROOT / cfg.get("database", "data/lol.db")))
    batch, total = [], 0
    for g in provider.iter_games():
        batch.append(g)
        if len(batch) >= 500:
            total += db.upsert_games(conn, batch)
            batch = []
    if batch:
        total += db.upsert_games(conn, batch)
    n = conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    dmin, dmax = conn.execute("SELECT MIN(date), MAX(date) FROM games").fetchone()
    ligas = conn.execute(
        "SELECT league, COUNT(*) FROM games GROUP BY 1 ORDER BY 2 DESC").fetchall()
    print(f"games no banco: {n} ({dmin} .. {dmax})")
    print("por liga:", ", ".join(f"{lg}={c}" for lg, c in ligas))


if __name__ == "__main__":
    sys.exit(run())
