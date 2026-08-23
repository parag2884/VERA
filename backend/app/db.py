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
    disabled INTEGER NOT NULL DEFAULT 0,
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

CREATE TABLE IF NOT EXISTS trust_forge_runs (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    suite_path TEXT NOT NULL,
    threshold REAL NOT NULL DEFAULT 95,
    max_generations INTEGER NOT NULL DEFAULT 8,
    stall_generations INTEGER NOT NULL DEFAULT 3,
    status TEXT NOT NULL,
    best_fitness REAL NOT NULL DEFAULT 0,
    generation INTEGER NOT NULL DEFAULT 0,
    stop_reason TEXT,
    error TEXT,
    progress_json TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
    FOREIGN KEY (agent_id) REFERENCES assistants(id)
);
CREATE INDEX IF NOT EXISTS idx_trust_forge_ws ON trust_forge_runs(workspace_id);
CREATE INDEX IF NOT EXISTS idx_trust_forge_status ON trust_forge_runs(workspace_id, status);

CREATE TABLE IF NOT EXISTS trust_forge_generations (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    gen INTEGER NOT NULL,
    fitness REAL NOT NULL,
    passed INTEGER NOT NULL,
    failed INTEGER NOT NULL,
    total INTEGER NOT NULL,
    hygiene_report_json TEXT DEFAULT '{}',
    case_results_json TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES trust_forge_runs(id),
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
);
CREATE INDEX IF NOT EXISTS idx_trust_forge_gens ON trust_forge_generations(run_id);

CREATE TABLE IF NOT EXISTS answer_feedback (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    rating TEXT NOT NULL,
    note TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
);
CREATE INDEX IF NOT EXISTS idx_feedback_ws ON answer_feedback(workspace_id);

CREATE TABLE IF NOT EXISTS kg_path_stats (
    path_key TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (workspace_id, path_key)
);

CREATE TABLE IF NOT EXISTS draft_goldens (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    question TEXT NOT NULL,
    question_norm TEXT NOT NULL,
    answer_preview TEXT DEFAULT '',
    source_url TEXT,
    retrieval_ok INTEGER,
    fail_kind TEXT DEFAULT '',
    origin TEXT DEFAULT 'ask',
    must_any TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
);
CREATE INDEX IF NOT EXISTS idx_drafts_ws ON draft_goldens(workspace_id, status);

CREATE TABLE IF NOT EXISTS graph_versions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    label TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'snapshot',
    metrics_json TEXT DEFAULT '{}',
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
);
CREATE INDEX IF NOT EXISTS idx_gver_ws ON graph_versions(workspace_id, created_at);

CREATE TABLE IF NOT EXISTS kg_audit (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    field TEXT NOT NULL,
    old_value TEXT DEFAULT '',
    new_value TEXT DEFAULT '',
    reason TEXT DEFAULT '',
    applied INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
);
CREATE INDEX IF NOT EXISTS idx_audit_ws ON kg_audit(workspace_id, created_at);

CREATE TABLE IF NOT EXISTS knowledge_metric_snapshots (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
);
CREATE INDEX IF NOT EXISTS idx_kms_ws ON knowledge_metric_snapshots(workspace_id, created_at);

CREATE TABLE IF NOT EXISTS knowledge_ops_actions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    driver TEXT NOT NULL,
    label TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    debt_at TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    completed_at TEXT DEFAULT '',
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
);
CREATE INDEX IF NOT EXISTS idx_kact_ws ON knowledge_ops_actions(workspace_id, status);

CREATE TABLE IF NOT EXISTS knowledge_source_gov (
    workspace_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    owner TEXT DEFAULT '',
    reviewer TEXT DEFAULT '',
    reviewed_at TEXT,
    PRIMARY KEY (workspace_id, document_id)
);

CREATE TABLE IF NOT EXISTS knowledge_goals (
    workspace_id TEXT PRIMARY KEY,
    target_debt REAL NOT NULL DEFAULT 10,
    target_coverage REAL NOT NULL DEFAULT 90,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kg_policies (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    target TEXT NOT NULL,
    note TEXT DEFAULT '',
    created_at TEXT NOT NULL,
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
    ("disabled", "ALTER TABLE assistants ADD COLUMN disabled INTEGER NOT NULL DEFAULT 0"),
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


async def _migrate_trust_forge(conn: aiosqlite.Connection) -> None:
    cur = await conn.execute("PRAGMA table_info(trust_forge_runs)")
    cols = {row[1] for row in await cur.fetchall()}
    if cols and "progress_json" not in cols:
        await conn.execute(
            "ALTER TABLE trust_forge_runs ADD COLUMN progress_json TEXT DEFAULT '{}'"
        )


async def init_db() -> None:
    conn = await get_connection()
    try:
        await conn.executescript(SCHEMA_SQL)
        await _migrate_assistants(conn)
        await _migrate_trust_forge(conn)
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS answer_feedback (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                rating TEXT NOT NULL,
                note TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )"""
        )
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS kg_path_stats (
                path_key TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                wins INTEGER NOT NULL DEFAULT 0,
                losses INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (workspace_id, path_key)
            )"""
        )
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS draft_goldens (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                question TEXT NOT NULL,
                question_norm TEXT NOT NULL,
                answer_preview TEXT DEFAULT '',
                source_url TEXT,
                retrieval_ok INTEGER,
                fail_kind TEXT DEFAULT '',
                origin TEXT DEFAULT 'ask',
                must_any TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL
            )"""
        )
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS graph_versions (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                label TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'snapshot',
                metrics_json TEXT DEFAULT '{}',
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS kg_audit (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                field TEXT NOT NULL,
                old_value TEXT DEFAULT '',
                new_value TEXT DEFAULT '',
                reason TEXT DEFAULT '',
                applied INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )"""
        )
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS knowledge_metric_snapshots (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS knowledge_ops_actions (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                driver TEXT NOT NULL,
                label TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'open',
                debt_at TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                completed_at TEXT DEFAULT ''
            )"""
        )
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS knowledge_source_gov (
                workspace_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                owner TEXT DEFAULT '',
                reviewer TEXT DEFAULT '',
                reviewed_at TEXT,
                PRIMARY KEY (workspace_id, document_id)
            )"""
        )
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS knowledge_goals (
                workspace_id TEXT PRIMARY KEY,
                target_debt REAL NOT NULL DEFAULT 10,
                target_coverage REAL NOT NULL DEFAULT 90,
                updated_at TEXT NOT NULL
            )"""
        )
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS kg_policies (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                target TEXT NOT NULL,
                note TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )"""
        )
        await conn.commit()
    finally:
        await conn.close()
