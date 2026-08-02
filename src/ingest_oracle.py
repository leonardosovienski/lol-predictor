"""Ingestão Oracle's Elixir → data/lol.db (Fase 1).

Lê os CSVs locais de data/raw/, filtra as ligas do config e grava a tabela
`games` (1 linha por mapa). Idempotente (game_id é PK).

Uso: python -m src.ingest_oracle
"""

import sys

from . import db
from .config import ROOT, load_config
from .data.ingestion import SnapshotStore, assert_fresh_snapshot
from .data.riot_provider import OracleProvider


def run() -> None:
    cfg = load_config()
    ingestion = cfg.get("ingestion", {})
    snapshot_root = ROOT / ingestion.get("snapshot_dir", "data/ingestion")
    # The ratings refresh must never silently consume a raw cache whose
    # provenance/freshness is unknown. Historical raw files remain only an
    # input to local replay and are not the weekly serving source.
    assert_fresh_snapshot(snapshot_root, max_age_hours=int(ingestion.get("max_staleness_hours", 192)))
    payload = SnapshotStore(snapshot_root).current_payload()
    if payload is None:  # guarded above; helps static readers and error clarity
        raise RuntimeError("snapshot Oracle ativo ausente")
    provider = OracleProvider(payload.parent, leagues=cfg.get("oracle", {}).get("leagues"))
    if not provider.health_check():
        sys.exit("data/raw sem CSVs — baixe do Drive do Oracle's Elixir")
    conn = db.connect(str(ROOT / cfg.get("database", "data/lol.db")))
    try:
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
        ligas = conn.execute("SELECT league, COUNT(*) FROM games GROUP BY 1 ORDER BY 2 DESC").fetchall()
    finally:
        conn.close()
    print(f"games no banco: {n} ({dmin} .. {dmax})")
    print("por liga:", ", ".join(f"{lg}={c}" for lg, c in ligas))


if __name__ == "__main__":
    sys.exit(run())
