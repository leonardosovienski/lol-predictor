"""SQLite do domínio LoL — jogos (mapas) do Oracle's Elixir (Fase 1).

Tabela `games` no nível de MAPA (a unidade do Elo e dos totais de abates).
game_id do OE é a chave (dedupe entre re-ingestões). read_only=True monta
mode=ro + query_only (P12).
"""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    game_id     TEXT PRIMARY KEY,        -- gameid do Oracle's Elixir
    date        TEXT NOT NULL,           -- 'YYYY-MM-DD HH:MM:SS'
    league      TEXT, split TEXT,
    game        INTEGER,                 -- nº do mapa na série
    team_a      TEXT NOT NULL,           -- lado azul
    team_b      TEXT NOT NULL,           -- lado vermelho
    winner      TEXT NOT NULL,           -- 'a' | 'b'
    kills_a     INTEGER, kills_b INTEGER,
    completeness TEXT
);
CREATE INDEX IF NOT EXISTS idx_games_date ON games(date);
"""

UPSERT = (
    "INSERT OR REPLACE INTO games (game_id, date, league, split, game, "
    "team_a, team_b, winner, kills_a, kills_b, completeness) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


def connect(db_path: str, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.execute("PRAGMA query_only=ON")
        return conn
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA)
    return conn


def upsert_games(conn, rows: list[dict]) -> int:
    cur = conn.executemany(
        UPSERT,
        [
            (
                r["game_id"],
                r["date"],
                r.get("league"),
                r.get("split"),
                r.get("game"),
                r["team_a"],
                r["team_b"],
                r["winner"],
                r.get("kills_a"),
                r.get("kills_b"),
                r.get("completeness"),
            )
            for r in rows
        ],
    )
    conn.commit()
    return cur.rowcount
