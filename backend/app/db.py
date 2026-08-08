from __future__ import annotations

import re
import secrets

import aiosqlite
from pathlib import Path

from app.config import get_settings

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assistants (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    name TEXT NOT NULL,
    slug TEXT,
    description TEXT DEFAULT '',
    system_style TEXT DEFAULT '',
    theme_json TEXT DEFAULT '{}',
    settings_json TEXT DEFAULT '{}',
    embed_key TEXT,
    allowed_origins TEXT DEFAULT '*',
    published INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
);
CREATE INDEX IF NOT EXISTS idx_assistants_ws ON assistants(workspace_id);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,
    error TEXT,
    result_json TEXT DEFAULT '{}',
    events_json TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
);
CREATE INDEX IF NOT EXISTS idx_jobs_ws ON jobs(workspace_id);

CREATE TABLE IF NOT EXISTS source_instances (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    mime TEXT,
    byte_size INTEGER NOT NULL DEFAULT 0,
    binary_hash TEXT NOT NULL,
    text_hash TEXT,
    storage_path TEXT,
    appears_at TEXT,
    source_access_scope TEXT DEFAULT 'workspace',
    status TEXT NOT NULL DEFAULT 'acquired',
    decision TEXT DEFAULT 'pending',
    canonical_document_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
);
CREATE INDEX IF NOT EXISTS idx_source_ws ON source_instances(workspace_id);
CREATE INDEX IF NOT EXISTS idx_source_binhash ON source_instances(workspace_id, binary_hash);

CREATE TABLE IF NOT EXISTS canonical_documents (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    title TEXT NOT NULL,
    mime TEXT,
    text_hash TEXT NOT NULL,
    checksum TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'active',
    char_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
);
CREATE INDEX IF NOT EXISTS idx_canon_ws ON canonical_documents(workspace_id);
CREATE INDEX IF NOT EXISTS idx_canon_texthash ON canonical_documents(workspace_id, text_hash);

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    canonical_document_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    text TEXT NOT NULL,
    loc_json TEXT DEFAULT '{}',
    char_start INTEGER,
    char_end INTEGER,
    embed_key TEXT,
    token_estimate INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
    FOREIGN KEY (canonical_document_id) REFERENCES canonical_documents(id)
);
CREATE INDEX IF NOT EXISTS idx_chunks_ws ON chunks(workspace_id);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(workspace_id, canonical_document_id);

CREATE TABLE IF NOT EXISTS kg_nodes (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    props_json TEXT DEFAULT '{}',
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
);
CREATE INDEX IF NOT EXISTS idx_nodes_ws ON kg_nodes(workspace_id);
CREATE INDEX IF NOT EXISTS idx_nodes_norm ON kg_nodes(workspace_id, normalized_name);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON kg_nodes(workspace_id, type);

CREATE TABLE IF NOT EXISTS kg_edges (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    src TEXT NOT NULL,
    dst TEXT NOT NULL,
    rel_type TEXT NOT NULL,
    edge_class TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    props_json TEXT DEFAULT '{}',
    document_id TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
);
CREATE INDEX IF NOT EXISTS idx_edges_ws ON kg_edges(workspace_id);
CREATE INDEX IF NOT EXISTS idx_edges_src ON kg_edges(workspace_id, src);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON kg_edges(workspace_id, dst);
CREATE INDEX IF NOT EXISTS idx_edges_rel ON kg_edges(workspace_id, rel_type);

CREATE TABLE IF NOT EXISTS kg_edge_evidence (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    edge_id TEXT NOT NULL,
    source_chunk_id TEXT NOT NULL,
    source_span_start INTEGER NOT NULL,
    source_span_end INTEGER NOT NULL,
    quote TEXT NOT NULL,
    extractor TEXT NOT NULL,
    extractor_version TEXT NOT NULL DEFAULT 'weaver-v1',
    confidence REAL NOT NULL DEFAULT 0.5,
    valid_from TEXT,
    valid_to TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
    FOREIGN KEY (edge_id) REFERENCES kg_edges(id),
    FOREIGN KEY (source_chunk_id) REFERENCES chunks(id)
);
CREATE INDEX IF NOT EXISTS idx_edge_ev_ws ON kg_edge_evidence(workspace_id);
CREATE INDEX IF NOT EXISTS idx_edge_ev_edge ON kg_edge_evidence(workspace_id, edge_id);

CREATE TABLE IF NOT EXISTS entity_aliases (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    alias TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    node_id TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
    FOREIGN KEY (node_id) REFERENCES kg_nodes(id)
);
CREATE INDEX IF NOT EXISTS idx_alias_ws ON entity_aliases(workspace_id, normalized_alias);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    assistant_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    decision TEXT,
    reason_codes_json TEXT DEFAULT '[]',
    trust_score_json TEXT DEFAULT '{}',
    trust_trail_json TEXT DEFAULT '[]',
    retrieval_mode TEXT,
    provider_mode TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
    FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
);
CREATE INDEX IF NOT EXISTS idx_msgs_ws ON chat_messages(workspace_id);

CREATE TABLE IF NOT EXISTS answer_claims (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    claim_text TEXT NOT NULL,
    support_status TEXT NOT NULL,
    trust_score REAL NOT NULL DEFAULT 0,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
    FOREIGN KEY (message_id) REFERENCES chat_messages(id)
);

CREATE TABLE IF NOT EXISTS answer_citations (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    chunk_id TEXT,
    edge_id TEXT,
    quote TEXT NOT NULL,
    locator TEXT,
    document_title TEXT,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
    FOREIGN KEY (claim_id) REFERENCES answer_claims(id)
);

CREATE TABLE IF NOT EXISTS cleanstack_reports (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    job_id TEXT,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
);

CREATE TABLE IF NOT EXISTS knowledge_health (
    workspace_id TEXT PRIMARY KEY,
    score REAL NOT NULL,
    components_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
);
"""


async def get_connection() -> aiosqlite.Connection:
    settings = get_settings()
    db_path: Path = settings.db_path
    # Longer timeout so ingest (long weave) doesn't 500 concurrent Studio calls
    conn = await aiosqlite.connect(db_path.as_posix(), timeout=60.0)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA busy_timeout=60000")
    await conn.execute("PRAGMA synchronous=NORMAL")
    return conn


_ASSISTANT_MIGRATIONS = [
    ("slug", "ALTER TABLE assistants ADD COLUMN slug TEXT"),
    ("description", "ALTER TABLE assistants ADD COLUMN description TEXT DEFAULT ''"),
    ("settings_json", "ALTER TABLE assistants ADD COLUMN settings_json TEXT DEFAULT '{}'"),
    ("embed_key", "ALTER TABLE assistants ADD COLUMN embed_key TEXT"),
    ("allowed_origins", "ALTER TABLE assistants ADD COLUMN allowed_origins TEXT DEFAULT '*'"),
    ("published", "ALTER TABLE assistants ADD COLUMN published INTEGER NOT NULL DEFAULT 0"),
]


async def _migrate_assistants(conn: aiosqlite.Connection) -> None:
    cur = await conn.execute("PRAGMA table_info(assistants)")
    cols = {row[1] for row in await cur.fetchall()}
    for name, ddl in _ASSISTANT_MIGRATIONS:
        if name not in cols:
            await conn.execute(ddl)
    await conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_assistants_embed ON assistants(embed_key)"
    )
    await conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_assistants_slug ON assistants(slug)"
    )
    # Backfill slug / embed_key for legacy rows
    cur = await conn.execute(
        "SELECT id, name, slug, embed_key FROM assistants"
    )
    rows = await cur.fetchall()

    used_slugs: set[str] = set()
    for row in rows:
        aid = row["id"]
        name = row["name"] or "agent"
        slug = row["slug"]
        embed_key = row["embed_key"]
        if not slug:
            base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "agent"
            candidate = base
            n = 2
            while candidate in used_slugs:
                candidate = f"{base}-{n}"
                n += 1
            slug = candidate
            await conn.execute(
                "UPDATE assistants SET slug = ? WHERE id = ?", (slug, aid)
            )
        used_slugs.add(slug)
        if not embed_key:
            await conn.execute(
                "UPDATE assistants SET embed_key = ? WHERE id = ?",
                (secrets.token_urlsafe(24), aid),
            )


async def init_db() -> None:
    conn = await get_connection()
    try:
        await conn.executescript(SCHEMA_SQL)
        await _migrate_assistants(conn)
        await conn.commit()
    finally:
        await conn.close()
