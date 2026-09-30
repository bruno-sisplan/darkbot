"""Banco local (SQLite). Toda leitura/escrita passa por aqui para facilitar a troca por Supabase depois."""
import sqlite3
from contextlib import contextmanager

from .paths import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'nicho',   -- 'nicho' ou 'coringa'
    niche       TEXT,
    source      TEXT,                            -- 'import:<perfil do chrome>' ou 'novo'
    dir         TEXT NOT NULL,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    last_run_at TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY,
    profile_id   INTEGER REFERENCES profiles(id) ON DELETE CASCADE,
    started_at   TEXT,
    finished_at  TEXT,
    status       TEXT,
    logged_in    INTEGER,
    videos_found INTEGER DEFAULT 0,
    error        TEXT
);

CREATE TABLE IF NOT EXISTS videos (
    video_id      TEXT PRIMARY KEY,
    title         TEXT,
    channel_id    TEXT,
    channel_title TEXT,
    published_at  TEXT,
    duration_s    INTEGER,
    views         INTEGER,
    likes         INTEGER,
    comments      INTEGER,
    is_short      INTEGER DEFAULT 0,
    lang          TEXT,
    first_seen_at TEXT,
    updated_at    TEXT
);

CREATE TABLE IF NOT EXISTS channels (
    channel_id   TEXT PRIMARY KEY,
    title        TEXT,
    handle       TEXT,
    subs         INTEGER,
    video_count  INTEGER,
    total_views  INTEGER,
    published_at TEXT,
    thumbnail    TEXT,
    country      TEXT,
    updated_at   TEXT
);

-- Cada vez que um vídeo aparece numa coleta (quantas vezes o algoritmo empurrou).
CREATE TABLE IF NOT EXISTS sightings (
    run_id   INTEGER REFERENCES runs(id) ON DELETE CASCADE,
    video_id TEXT,
    position INTEGER,
    surface  TEXT,          -- 'home' ou 'shorts'
    PRIMARY KEY (run_id, video_id)
);

-- Histórico de views para medir crescimento entre coletas.
CREATE TABLE IF NOT EXISTS video_stats (
    video_id    TEXT,
    captured_at TEXT,
    views       INTEGER,
    PRIMARY KEY (video_id, captured_at)
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_sightings_video ON sightings(video_id);
CREATE INDEX IF NOT EXISTS idx_runs_profile ON runs(profile_id);
CREATE INDEX IF NOT EXISTS idx_videos_channel ON videos(channel_id);
"""


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


@contextmanager
def tx():
    con = connect()
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init() -> None:
    with tx() as con:
        con.executescript(SCHEMA)


def rows(sql: str, params=()) -> list[dict]:
    with tx() as con:
        return [dict(r) for r in con.execute(sql, params).fetchall()]


def row(sql: str, params=()) -> dict | None:
    with tx() as con:
        r = con.execute(sql, params).fetchone()
        return dict(r) if r else None


def get_setting(key: str, default: str | None = None) -> str | None:
    r = row("SELECT value FROM settings WHERE key = ?", (key,))
    return r["value"] if r else default


def set_setting(key: str, value: str) -> None:
    with tx() as con:
        con.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
