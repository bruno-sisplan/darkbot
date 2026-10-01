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
    ai_label      INTEGER,       -- selo "gerado por IA" do YouTube: 1 sim, 0 não, NULL ainda não verificado
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

-- Pesquisas de mercado: parte de um vídeo (sugeridos) ou de palavras-chave (busca).
CREATE TABLE IF NOT EXISTS research (
    id           INTEGER PRIMARY KEY,
    kind         TEXT,          -- 'video' ou 'keyword'
    seed         TEXT,          -- id do vídeo ou as palavras-chave
    label        TEXT,          -- nome para mostrar (título do vídeo semente ou as palavras)
    keywords     TEXT,          -- JSON: buscas usadas
    status       TEXT,
    videos_found INTEGER DEFAULT 0,
    error        TEXT,
    created_at   TEXT,
    finished_at  TEXT
);

CREATE TABLE IF NOT EXISTS research_videos (
    research_id INTEGER REFERENCES research(id) ON DELETE CASCADE,
    video_id    TEXT,
    via         TEXT,           -- 'semente', 'sugerido', 'busca:recente', 'busca:top-mes', 'busca:top-ano'
    depth       INTEGER,
    keyword     TEXT,
    position    INTEGER,
    PRIMARY KEY (research_id, video_id)
);

-- Comentários mais relevantes dos vídeos analisados (o que o público pede). Guardados para gerar títulos/roteiros.
CREATE TABLE IF NOT EXISTS comments (
    comment_id   TEXT PRIMARY KEY,
    video_id     TEXT,
    text         TEXT,
    likes        INTEGER,
    replies      INTEGER,
    published_at TEXT
);

-- Método Malandro: em que línguas ninguém fez este vídeo ainda (resultado completo em JSON, um por vídeo).
CREATE TABLE IF NOT EXISTS malandro (
    video_id   TEXT PRIMARY KEY,
    result     TEXT,
    created_at TEXT
);

-- Registro de gastos com IA (cada chamada). Separado do cache: apagar uma análise não "devolve" o gasto.
CREATE TABLE IF NOT EXISTS ai_usage (
    id            INTEGER PRIMARY KEY,
    kind          TEXT,
    model         TEXT,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    cost_usd      REAL,
    created_at    TEXT
);

-- Resultados da IA. Uma análise por (tipo, alvo): nunca repete o que já foi feito.
CREATE TABLE IF NOT EXISTS ai_results (
    kind          TEXT,          -- ex.: 'niche:v1'
    target        TEXT,          -- ex.: 'profile:3', 'chrome:Profile 1:email'
    model         TEXT,
    result        TEXT,          -- JSON
    input_tokens  INTEGER,
    output_tokens INTEGER,
    cost_usd      REAL,
    created_at    TEXT,
    PRIMARY KEY (kind, target)
);

CREATE INDEX IF NOT EXISTS idx_sightings_video ON sightings(video_id);
CREATE INDEX IF NOT EXISTS idx_runs_profile ON runs(profile_id);
CREATE INDEX IF NOT EXISTS idx_videos_channel ON videos(channel_id);
CREATE INDEX IF NOT EXISTS idx_research_videos_video ON research_videos(video_id);
CREATE INDEX IF NOT EXISTS idx_comments_video ON comments(video_id);
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


# Colunas adicionadas depois da primeira versão (bancos antigos ganham na abertura).
_MIGRATIONS = [
    ("videos", "ai_label", "INTEGER"),
    ("videos", "comments_fetched_at", "TEXT"),
    ("channels", "dark", "INTEGER"),      # classificação da IA: 1 canal dark (sem rosto), 0 não
    ("channels", "format", "TEXT"),       # narracao, musica, compilacao, reupload, animacao, com_rosto, oficial, outro
    ("channels", "theme", "TEXT"),
    ("profiles", "niche_auto", "INTEGER"),  # 1 = nicho preenchido pela IA (some se a coleta de origem for apagada)
    ("channels", "description", "TEXT"),   # descrição do canal (ajuda a IA a separar dark de youtuber pessoal)
    ("channels", "dark_conf", "TEXT"),     # confiança da IA: alta, media, baixa
    ("channels", "dark_manual", "INTEGER"),  # correção do editor: 1 é dark, 0 não é (vence a IA)
    ("channels", "class_v", "INTEGER"),    # versão do classificador que classificou o canal
    ("videos", "hidden", "INTEGER"),       # 1 = ocultado pelo editor
    ("videos", "title_pt", "TEXT"),        # título traduzido (vídeos em outros idiomas)
    ("videos", "description", "TEXT"),     # descrição do vídeo (para análise e para o gerador de descrição)
    ("videos", "tags", "TEXT"),            # JSON com as tags do vídeo
    ("runs", "source", "TEXT"),            # 'home' (página inicial) ou 'history' (histórico do YouTube)
    ("research", "langs", "TEXT"),         # JSON: idiomas pesquisados
    ("research", "profile_id", "INTEGER"),  # pesquisa a partir do histórico de um perfil
    ("research", "topic", "TEXT"),         # JSON: o que a IA entendeu do vídeo-semente (tema, formato, ângulo...)
    ("research_videos", "relevance", "INTEGER"),  # nota do juiz de relevância: 3 direto, 2 tema, 1 tangente
    ("runs", "research_id", "INTEGER"),    # coleta criada a partir de uma pesquisa ("Enviar para Descobertas")
    ("research", "max_age_days", "INTEGER"),  # período da pesquisa: só vídeos publicados nos últimos N dias (NULL = qualquer)
]


def init() -> None:
    with tx() as con:
        con.executescript(SCHEMA)
        for table, col, decl in _MIGRATIONS:
            cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
            if col not in cols:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        # Chaves que antes ficavam no código (app/secrets.py): vão para o banco uma vez e passam a ser
        # editadas na aba Configurações.
        try:
            import importlib
            # Import dinâmico de propósito: o empacotador do .exe não enxerga (chave nunca vai junto no .exe).
            _old_keys = importlib.import_module(f"{__package__}.secrets")
            for name, setting in (("YOUTUBE_API_KEY", "youtube_api_key"), ("ANTHROPIC_API_KEY", "anthropic_api_key"),
                                  ("OPENAI_API_KEY", "openai_api_key")):
                val = getattr(_old_keys, name, "")
                if val and not con.execute("SELECT value FROM settings WHERE key=? AND value<>''", (setting,)).fetchone():
                    con.execute("INSERT INTO settings(key, value) VALUES(?, ?) "
                                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (setting, val))
        except ImportError:
            pass
        # Bancos anteriores ao registro de gastos: o histórico começa com o que já estava no cache.
        if not con.execute("SELECT 1 FROM ai_usage LIMIT 1").fetchone():
            con.execute("""INSERT INTO ai_usage(kind, model, input_tokens, output_tokens, cost_usd, created_at)
                           SELECT kind, model, input_tokens, output_tokens, cost_usd, created_at FROM ai_results""")


def recover_interrupted() -> None:
    """Ao abrir o app: coleta/pesquisa que ficou 'rodando' foi interrompida pelo fechamento. Marca, sem apagar nada."""
    msg = "Interrompida: o app foi fechado durante a tarefa."
    with tx() as con:
        con.execute("UPDATE runs SET status='error', error=? WHERE status='running'", (msg,))
        con.execute("""UPDATE research SET status = CASE WHEN EXISTS
                         (SELECT 1 FROM research_videos rv WHERE rv.research_id = research.id) THEN 'cancelled' ELSE 'error' END,
                       error = ?, videos_found = (SELECT COUNT(*) FROM research_videos rv WHERE rv.research_id = research.id)
                       WHERE status='running'""", (msg,))


def purge_orphans(con: sqlite3.Connection) -> dict:
    """Apaga o que não pertence mais a nenhuma coleta nem pesquisa (vídeos, números, comentários, canais, análises).

    Chamado depois de excluir uma coleta ou pesquisa: o que só existia nela some; o que aparece em outra fica.
    """
    orphan = """video_id NOT IN (SELECT video_id FROM sightings)
                AND video_id NOT IN (SELECT video_id FROM research_videos)"""
    gone = [r[0] for r in con.execute(f"SELECT video_id FROM videos WHERE {orphan}")]
    con.execute(f"DELETE FROM videos WHERE {orphan}")
    con.execute("DELETE FROM video_stats WHERE video_id NOT IN (SELECT video_id FROM videos)")
    con.execute("DELETE FROM comments WHERE video_id NOT IN (SELECT video_id FROM videos)")
    ch = con.execute("""DELETE FROM channels WHERE channel_id NOT IN
                        (SELECT channel_id FROM videos WHERE channel_id IS NOT NULL)""").rowcount
    con.executemany("DELETE FROM ai_results WHERE target = ?", [(f"video:{v}",) for v in gone])
    return {"videos": len(gone), "channels": ch}


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
