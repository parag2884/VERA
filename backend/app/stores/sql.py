from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import aiosqlite

from app.db import get_connection
from app.identity import normalize_entity_name
from app.services.tokens import count_tokens


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jid() -> str:
    return str(uuid4())


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (name or "agent").lower()).strip("-")
    return base or "agent"


DEFAULT_AGENT_SETTINGS = {
    "agentName": "Public Agent",
    "greeting": (
        "Ask anything about your connected knowledge. I'll answer with a Trust Trail "
        "— or clarify / refuse when proof is missing."
    ),
    "tone": "professional",
    "verbosity": "balanced",
    "accent": "coral",
    "showTrustTrail": True,
    "showCitations": True,
    "showTrustScore": True,
    "embedStreaming": True,
    "placeholder": "Ask about your knowledge…",
}


class WorkspaceStore:
    """All queries require workspace_id — storage-layer isolation guarantee."""

    def __init__(self, conn: aiosqlite.Connection | None = None) -> None:
        self._conn = conn
        self._owns = conn is None

    async def __aenter__(self) -> WorkspaceStore:
        if self._conn is None:
            self._conn = await get_connection()
            self._owns = True
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._owns and self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Store not connected")
        return self._conn

    async def commit(self) -> None:
        await self.conn.commit()

    # --- workspaces ---
    async def create_workspace(self, name: str) -> dict[str, Any]:
        agent = await self.create_agent(name=name or "Public Agent")
        return {
            "id": agent["workspace_id"],
            "name": agent["workspace_name"],
            "created_at": agent["created_at"],
            "assistant_id": agent["id"],
        }

    async def get_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        cur = await self.conn.execute(
            "SELECT * FROM workspaces WHERE id = ?", (workspace_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def list_workspaces(self) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            "SELECT * FROM workspaces ORDER BY created_at DESC"
        )
        return [dict(r) for r in await cur.fetchall()]

    # --- agents (assistants + dedicated knowledge workspace) ---
    def _row_to_agent(self, row: aiosqlite.Row | dict[str, Any], counts: dict[str, int] | None = None) -> dict[str, Any]:
        data = dict(row)
        settings = json.loads(data.pop("settings_json", None) or "{}")
        if not settings:
            settings = {**DEFAULT_AGENT_SETTINGS, "agentName": data.get("name") or "Public Agent"}
        return {
            "id": data["id"],
            "workspace_id": data["workspace_id"],
            "workspace_name": data.get("workspace_name") or data.get("name"),
            "name": data["name"],
            "slug": data.get("slug") or _slugify(data["name"]),
            "description": data.get("description") or "",
            "settings": settings,
            "embed_key": data.get("embed_key"),
            "allowed_origins": data.get("allowed_origins") or "*",
            "published": bool(data.get("published")),
            "disabled": bool(data.get("disabled")),
            "created_at": data["created_at"],
            "counts": counts or {},
        }

    async def _unique_slug(self, name: str, exclude_id: str | None = None) -> str:
        base = _slugify(name)
        candidate = base
        n = 2
        while True:
            if exclude_id:
                cur = await self.conn.execute(
                    "SELECT id FROM assistants WHERE slug = ? AND id != ?",
                    (candidate, exclude_id),
                )
            else:
                cur = await self.conn.execute(
                    "SELECT id FROM assistants WHERE slug = ?", (candidate,)
                )
            if not await cur.fetchone():
                return candidate
            candidate = f"{base}-{n}"
            n += 1

    async def create_agent(
        self,
        name: str,
        description: str = "",
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        wid = _jid()
        aid = _jid()
        created = _now()
        agent_name = (name or "Public Agent").strip()
        slug = await self._unique_slug(agent_name)
        embed_key = secrets.token_urlsafe(24)
        settings_obj = {
            **DEFAULT_AGENT_SETTINGS,
            **(settings or {}),
            "agentName": agent_name,
        }
        await self.conn.execute(
            "INSERT INTO workspaces (id, name, created_at) VALUES (?, ?, ?)",
            (wid, agent_name, created),
        )
        await self.conn.execute(
            """INSERT INTO assistants
               (id, workspace_id, name, slug, description, settings_json,
                embed_key, allowed_origins, published, disabled, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, '*', 0, 0, ?)""",
            (
                aid,
                wid,
                agent_name,
                slug,
                description or "",
                json.dumps(settings_obj),
                embed_key,
                created,
            ),
        )
        await self.commit()
        return await self.get_agent(aid)  # type: ignore[return-value]

    async def list_agents(self) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            """SELECT a.*, w.name AS workspace_name
               FROM assistants a
               JOIN workspaces w ON w.id = a.workspace_id
               ORDER BY a.created_at DESC"""
        )
        rows = await cur.fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            counts = await self.counts(row["workspace_id"])
            out.append(self._row_to_agent(row, counts))
        return out

    async def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        cur = await self.conn.execute(
            """SELECT a.*, w.name AS workspace_name
               FROM assistants a
               JOIN workspaces w ON w.id = a.workspace_id
               WHERE a.id = ?""",
            (agent_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        counts = await self.counts(row["workspace_id"])
        return self._row_to_agent(row, counts)

    async def get_agent_by_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        cur = await self.conn.execute(
            """SELECT a.*, w.name AS workspace_name
               FROM assistants a
               JOIN workspaces w ON w.id = a.workspace_id
               WHERE a.workspace_id = ?
               ORDER BY a.created_at ASC LIMIT 1""",
            (workspace_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        counts = await self.counts(row["workspace_id"])
        return self._row_to_agent(row, counts)

    async def get_agent_by_embed_key(self, embed_key: str) -> dict[str, Any] | None:
        cur = await self.conn.execute(
            """SELECT a.*, w.name AS workspace_name
               FROM assistants a
               JOIN workspaces w ON w.id = a.workspace_id
               WHERE a.embed_key = ?""",
            (embed_key,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        return self._row_to_agent(row)

    async def update_agent(
        self,
        agent_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        settings: dict[str, Any] | None = None,
        allowed_origins: str | None = None,
        published: bool | None = None,
        disabled: bool | None = None,
        rotate_embed_key: bool = False,
    ) -> dict[str, Any] | None:
        agent = await self.get_agent(agent_id)
        if not agent:
            return None
        fields: list[str] = []
        values: list[Any] = []
        if name is not None:
            fields.append("name = ?")
            values.append(name.strip())
            slug = await self._unique_slug(name, exclude_id=agent_id)
            fields.append("slug = ?")
            values.append(slug)
            await self.conn.execute(
                "UPDATE workspaces SET name = ? WHERE id = ?",
                (name.strip(), agent["workspace_id"]),
            )
        if description is not None:
            fields.append("description = ?")
            values.append(description)
        if settings is not None:
            merged = {**agent["settings"], **settings}
            if name is not None:
                merged["agentName"] = name.strip()
            fields.append("settings_json = ?")
            values.append(json.dumps(merged))
        elif name is not None:
            merged = {**agent["settings"], "agentName": name.strip()}
            fields.append("settings_json = ?")
            values.append(json.dumps(merged))
        if allowed_origins is not None:
            fields.append("allowed_origins = ?")
            values.append(allowed_origins)
        if published is not None:
            fields.append("published = ?")
            values.append(1 if published else 0)
        if disabled is not None:
            fields.append("disabled = ?")
            values.append(1 if disabled else 0)
        if rotate_embed_key:
            fields.append("embed_key = ?")
            values.append(secrets.token_urlsafe(24))
        if fields:
            values.append(agent_id)
            await self.conn.execute(
                f"UPDATE assistants SET {', '.join(fields)} WHERE id = ?",
                values,
            )
            await self.commit()
        return await self.get_agent(agent_id)

    async def delete_agent(self, agent_id: str) -> dict[str, Any] | None:
        """Hard-delete agent row + workspace row after knowledge purge (caller clears vectors)."""
        agent = await self.get_agent(agent_id)
        if not agent:
            return None
        workspace_id = agent["workspace_id"]
        purge = await self.purge_knowledge(workspace_id)
        await self.conn.execute("DELETE FROM assistants WHERE id = ?", (agent_id,))
        await self.conn.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))
        await self.commit()
        return {
            "id": agent_id,
            "workspace_id": workspace_id,
            "name": agent.get("name"),
            "purge": purge,
        }

    # --- jobs ---
    async def create_job(self, workspace_id: str, job_type: str) -> dict[str, Any]:
        jid = _jid()
        now = _now()
        last_exc: Exception | None = None
        for attempt in range(8):
            try:
                await self.conn.execute(
                    """INSERT INTO jobs (id, workspace_id, type, status, progress, created_at, updated_at)
                       VALUES (?, ?, ?, 'queued', 0, ?, ?)""",
                    (jid, workspace_id, job_type, now, now),
                )
                await self.commit()
                return {
                    "id": jid,
                    "workspace_id": workspace_id,
                    "type": job_type,
                    "status": "queued",
                }
            except Exception as exc:  # noqa: BLE001 — retry sqlite lock races
                last_exc = exc
                msg = str(exc).lower()
                if "locked" not in msg and "busy" not in msg:
                    raise
                import asyncio

                await asyncio.sleep(0.15 * (attempt + 1))
        raise last_exc or RuntimeError("create_job failed")

    async def update_job(
        self,
        workspace_id: str,
        job_id: str,
        *,
        status: str | None = None,
        progress: float | None = None,
        error: str | None = None,
        result: dict[str, Any] | None = None,
        events: list[dict[str, Any]] | None = None,
    ) -> None:
        fields: list[str] = ["updated_at = ?"]
        values: list[Any] = [_now()]
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if progress is not None:
            fields.append("progress = ?")
            values.append(progress)
        if error is not None:
            fields.append("error = ?")
            values.append(error)
        if result is not None:
            fields.append("result_json = ?")
            values.append(json.dumps(result))
        if events is not None:
            fields.append("events_json = ?")
            values.append(json.dumps(events))
        values.extend([workspace_id, job_id])
        await self.conn.execute(
            f"UPDATE jobs SET {', '.join(fields)} WHERE workspace_id = ? AND id = ?",
            values,
        )
        await self.commit()

    async def get_job(self, workspace_id: str, job_id: str) -> dict[str, Any] | None:
        cur = await self.conn.execute(
            "SELECT * FROM jobs WHERE workspace_id = ? AND id = ?",
            (workspace_id, job_id),
        )
        row = await cur.fetchone()
        if not row:
            return None
        data = dict(row)
        data["result"] = json.loads(data.pop("result_json") or "{}")
        data["events"] = json.loads(data.pop("events_json") or "[]")
        return data

    async def get_active_ingest_job(self, workspace_id: str) -> dict[str, Any] | None:
        """Return newest queued/running ingest job, if any (blocks concurrent weaves)."""
        cur = await self.conn.execute(
            """SELECT * FROM jobs
               WHERE workspace_id = ?
               AND status IN ('queued', 'running')
               AND type LIKE 'ingest%'
               ORDER BY created_at DESC
               LIMIT 1""",
            (workspace_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        data = dict(row)
        data["result"] = json.loads(data.pop("result_json") or "{}")
        data["events"] = json.loads(data.pop("events_json") or "[]")
        return data

    # --- sources / canonical ---
    async def insert_source_instance(self, workspace_id: str, **fields: Any) -> str:
        sid = fields.get("id") or _jid()
        await self.conn.execute(
            """INSERT INTO source_instances
               (id, workspace_id, filename, mime, byte_size, binary_hash, text_hash,
                storage_path, appears_at, source_access_scope, status, decision,
                canonical_document_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                sid,
                workspace_id,
                fields["filename"],
                fields.get("mime"),
                fields.get("byte_size", 0),
                fields["binary_hash"],
                fields.get("text_hash"),
                fields.get("storage_path"),
                fields.get("appears_at"),
                fields.get("source_access_scope", "workspace"),
                fields.get("status", "acquired"),
                fields.get("decision", "pending"),
                fields.get("canonical_document_id"),
                fields.get("created_at", _now()),
            ),
        )
        return sid

    async def update_source_instance(
        self, workspace_id: str, source_id: str, **fields: Any
    ) -> None:
        allowed = {
            "text_hash",
            "status",
            "decision",
            "canonical_document_id",
            "storage_path",
            "appears_at",
        }
        sets = []
        values: list[Any] = []
        for key, value in fields.items():
            if key in allowed:
                sets.append(f"{key} = ?")
                values.append(value)
        if not sets:
            return
        values.extend([workspace_id, source_id])
        await self.conn.execute(
            f"UPDATE source_instances SET {', '.join(sets)} WHERE workspace_id = ? AND id = ?",
            values,
        )

    async def list_source_instances(self, workspace_id: str) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            "SELECT * FROM source_instances WHERE workspace_id = ? ORDER BY created_at",
            (workspace_id,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def upsert_canonical_document(self, workspace_id: str, **fields: Any) -> str:
        did = fields.get("id") or _jid()
        await self.conn.execute(
            """INSERT INTO canonical_documents
               (id, workspace_id, title, mime, text_hash, checksum, version, status, char_count, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 title=excluded.title, status=excluded.status, char_count=excluded.char_count""",
            (
                did,
                workspace_id,
                fields["title"],
                fields.get("mime"),
                fields["text_hash"],
                fields.get("checksum"),
                fields.get("version", 1),
                fields.get("status", "active"),
                fields.get("char_count", 0),
                fields.get("created_at", _now()),
            ),
        )
        return did

    async def find_canonical_by_text_hash(
        self, workspace_id: str, text_hash: str
    ) -> dict[str, Any] | None:
        cur = await self.conn.execute(
            "SELECT * FROM canonical_documents WHERE workspace_id = ? AND text_hash = ?",
            (workspace_id, text_hash),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def list_canonical_documents(self, workspace_id: str) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            """SELECT * FROM canonical_documents
               WHERE workspace_id = ? AND status = 'active'
               ORDER BY created_at DESC""",
            (workspace_id,),
        )
        return [dict(r) for r in await cur.fetchall()]

    # --- chunks ---
    async def insert_chunk(self, workspace_id: str, **fields: Any) -> str:
        cid = fields.get("id") or _jid()
        await self.conn.execute(
            """INSERT INTO chunks
               (id, workspace_id, canonical_document_id, ordinal, text, loc_json,
                char_start, char_end, embed_key, token_estimate)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                cid,
                workspace_id,
                fields["canonical_document_id"],
                fields["ordinal"],
                fields["text"],
                json.dumps(fields.get("loc") or {}),
                fields.get("char_start"),
                fields.get("char_end"),
                fields.get("embed_key"),
                fields["token_estimate"]
                if fields.get("token_estimate") is not None
                else count_tokens(fields["text"]),
            ),
        )
        return cid

    async def list_chunks(
        self, workspace_id: str, document_id: str | None = None, ids: list[str] | None = None
    ) -> list[dict[str, Any]]:
        if ids:
            placeholders = ",".join("?" * len(ids))
            cur = await self.conn.execute(
                f"SELECT * FROM chunks WHERE workspace_id = ? AND id IN ({placeholders})",
                [workspace_id, *ids],
            )
        elif document_id:
            cur = await self.conn.execute(
                "SELECT * FROM chunks WHERE workspace_id = ? AND canonical_document_id = ? ORDER BY ordinal",
                (workspace_id, document_id),
            )
        else:
            cur = await self.conn.execute(
                "SELECT * FROM chunks WHERE workspace_id = ? ORDER BY canonical_document_id, ordinal",
                (workspace_id,),
            )
        rows = await cur.fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["loc"] = json.loads(d.pop("loc_json") or "{}")
            out.append(d)
        return out

    # --- graph ---
    async def upsert_node(self, workspace_id: str, **fields: Any) -> str:
        nid = fields.get("id") or _jid()
        # Prefer existing by normalized name + type
        cur = await self.conn.execute(
            """SELECT id FROM kg_nodes
               WHERE workspace_id = ? AND normalized_name = ? AND type = ?""",
            (workspace_id, fields["normalized_name"], fields["type"]),
        )
        existing = await cur.fetchone()
        if existing:
            return str(existing["id"])
        await self.conn.execute(
            """INSERT INTO kg_nodes (id, workspace_id, type, name, normalized_name, props_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                nid,
                workspace_id,
                fields["type"],
                fields["name"],
                fields["normalized_name"],
                json.dumps(fields.get("props") or {}),
            ),
        )
        return nid

    async def insert_alias(
        self, workspace_id: str, alias: str, normalized_alias: str, node_id: str
    ) -> None:
        """Insert alias only when it relates to the node and is not a duplicate."""
        alias_s = (alias or "").strip()
        norm_a = (normalized_alias or "").strip()
        if not alias_s or not norm_a or not node_id:
            return
        cur = await self.conn.execute(
            """SELECT name, normalized_name, type FROM kg_nodes
               WHERE id = ? AND workspace_id = ? LIMIT 1""",
            (node_id, workspace_id),
        )
        node = await cur.fetchone()
        if not node:
            return
        if not _alias_fits_node(
            alias=alias_s,
            alias_norm=norm_a,
            node_name=str(node["name"] or ""),
            node_norm=str(node["normalized_name"] or ""),
            node_type=str(node["type"] or ""),
        ):
            return
        exists = await self.conn.execute(
            """SELECT 1 FROM entity_aliases
               WHERE workspace_id = ? AND node_id = ? AND normalized_alias = ?
               LIMIT 1""",
            (workspace_id, node_id, norm_a),
        )
        if await exists.fetchone():
            return
        await self.conn.execute(
            """INSERT INTO entity_aliases (id, workspace_id, alias, normalized_alias, node_id)
               VALUES (?, ?, ?, ?, ?)""",
            (_jid(), workspace_id, alias_s, norm_a, node_id),
        )

    async def _domain_aliases(self, workspace_id: str) -> dict[str, str]:
        """Aliases inferred for this agent's corpus (domainProfile) — not a global list."""
        try:
            agent = await self.get_agent_by_workspace(workspace_id)
            if not agent:
                return {}
            dp = (agent.get("settings") or {}).get("domainProfile") or {}
            raw = dp.get("aliases") or {}
            if not isinstance(raw, dict):
                return {}
            out: dict[str, str] = {}
            for k, v in raw.items():
                if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip():
                    out[" ".join(k.lower().split())] = " ".join(v.lower().split())
            return out
        except Exception:  # noqa: BLE001
            return {}

    async def resolve_entity(self, workspace_id: str, name: str) -> list[dict[str, Any]]:
        aliases = await self._domain_aliases(workspace_id)
        norm = normalize_entity_name(name, aliases=aliases or None)
        cur = await self.conn.execute(
            """SELECT n.* FROM kg_nodes n
               WHERE n.workspace_id = ? AND n.normalized_name = ?
               AND n.type NOT IN ('Document', 'Chunk', 'Section')
               UNION
               SELECT n.* FROM kg_nodes n
               JOIN entity_aliases a ON a.node_id = n.id AND a.workspace_id = n.workspace_id
               WHERE a.workspace_id = ? AND a.normalized_alias = ?
               AND n.type NOT IN ('Document', 'Chunk', 'Section')""",
            (workspace_id, norm, workspace_id, norm),
        )
        rows = [dict(r) for r in await cur.fetchall()]
        if rows:
            return rows
        # Product codes: SL3000 ↔ "security level 3000" / spaced variants via alnum
        alnum = re.sub(r"[^a-z0-9]", "", norm)
        if re.fullmatch(r"[a-z]{1,8}\d{2,}", alnum) and len(alnum) >= 4:
            cur = await self.conn.execute(
                """SELECT n.* FROM kg_nodes n
                   WHERE n.workspace_id = ?
                   AND n.type NOT IN ('Document', 'Chunk', 'Section')
                   AND (
                     lower(replace(replace(n.normalized_name, ' ', ''), '-', '')) = ?
                     OR lower(replace(replace(n.name, ' ', ''), '-', '')) = ?
                   )
                   LIMIT 8""",
                (workspace_id, alnum, alnum),
            )
            rows = [dict(r) for r in await cur.fetchall()]
        return rows

    async def resolve_entity_fuzzy(
        self, workspace_id: str, name: str, *, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Prefix / containment match for entity linking across aliases."""
        exact = await self.resolve_entity(workspace_id, name)
        if exact:
            return exact
        aliases = await self._domain_aliases(workspace_id)
        norm = normalize_entity_name(name, aliases=aliases or None)
        # Short tokens ("and", "for") must not substring-match half the graph
        if len(norm) < 4:
            return []
        # Containment (%term%) only for reasonably specific phrases
        use_contains = len(norm) >= 5
        name_contains = f"%{norm}%" if use_contains else norm  # exact-like when short
        cur = await self.conn.execute(
            """SELECT DISTINCT n.* FROM kg_nodes n
               LEFT JOIN entity_aliases a
                 ON a.node_id = n.id AND a.workspace_id = n.workspace_id
               WHERE n.workspace_id = ?
               AND n.type NOT IN ('Document', 'Chunk', 'Section')
               AND (
                 n.normalized_name LIKE ?
                 OR (? = 1 AND n.normalized_name LIKE ?)
                 OR (? LIKE '%' || n.normalized_name || '%' AND length(n.normalized_name) >= 5)
                 OR a.normalized_alias LIKE ?
                 OR (? = 1 AND a.normalized_alias LIKE ?)
               )
               LIMIT ?""",
            (
                workspace_id,
                f"{norm}%",
                1 if use_contains else 0,
                name_contains,
                norm,
                f"{norm}%",
                1 if use_contains else 0,
                name_contains,
                max(1, limit * 3),
            ),
        )
        rows = [dict(r) for r in await cur.fetchall()]
        # Rank: prefix > containment; prefer closer length
        def _score(row: dict[str, Any]) -> tuple[int, int]:
            nn = str(row.get("normalized_name") or "")
            if nn == norm:
                return (0, 0)
            if nn.startswith(norm) or norm.startswith(nn):
                return (1, abs(len(nn) - len(norm)))
            return (2, abs(len(nn) - len(norm)))

        rows.sort(key=_score)
        # Dedupe by id
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for r in rows:
            rid = r.get("id")
            if not rid or rid in seen:
                continue
            seen.add(rid)
            out.append(r)
            if len(out) >= limit:
                break
        return out

    async def insert_edge(self, workspace_id: str, **fields: Any) -> str:
        """Idempotent insert: reuse active edge with same endpoints/rel/class."""
        src = fields["src"]
        dst = fields["dst"]
        rel_type = fields["rel_type"]
        edge_class = fields["edge_class"]
        if src == dst:
            # Do not create self-loops; reuse one if a legacy row exists
            cur = await self.conn.execute(
                """SELECT id FROM kg_edges
                   WHERE workspace_id = ? AND src = ? AND dst = ? AND rel_type = ?
                   AND edge_class = ? AND status = 'active' LIMIT 1""",
                (workspace_id, src, dst, rel_type, edge_class),
            )
            row = await cur.fetchone()
            return row["id"] if row else ""
        cur = await self.conn.execute(
            """SELECT id FROM kg_edges
               WHERE workspace_id = ? AND src = ? AND dst = ? AND rel_type = ?
               AND edge_class = ? AND status = 'active' LIMIT 1""",
            (workspace_id, src, dst, rel_type, edge_class),
        )
        existing = await cur.fetchone()
        if existing:
            return existing["id"]
        eid = fields.get("id") or _jid()
        await self.conn.execute(
            """INSERT INTO kg_edges
               (id, workspace_id, src, dst, rel_type, edge_class, weight, props_json, document_id, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                eid,
                workspace_id,
                src,
                dst,
                rel_type,
                edge_class,
                fields.get("weight", 1.0),
                json.dumps(fields.get("props") or {}),
                fields.get("document_id"),
                fields.get("status", "active"),
            ),
        )
        return eid

    async def insert_edge_evidence(self, workspace_id: str, **fields: Any) -> str:
        evid = fields.get("id") or _jid()
        await self.conn.execute(
            """INSERT INTO kg_edge_evidence
               (id, workspace_id, edge_id, source_chunk_id, source_span_start, source_span_end,
                quote, extractor, extractor_version, confidence, valid_from, valid_to, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                evid,
                workspace_id,
                fields["edge_id"],
                fields["source_chunk_id"],
                fields["source_span_start"],
                fields["source_span_end"],
                fields["quote"],
                fields["extractor"],
                fields.get("extractor_version", "weaver-v1"),
                fields.get("confidence", 0.5),
                fields.get("valid_from"),
                fields.get("valid_to"),
                fields.get("status", "active"),
            ),
        )
        return evid

    async def get_graph(self, workspace_id: str) -> dict[str, Any]:
        ncur = await self.conn.execute(
            "SELECT * FROM kg_nodes WHERE workspace_id = ?", (workspace_id,)
        )
        ecur = await self.conn.execute(
            "SELECT * FROM kg_edges WHERE workspace_id = ? AND status = 'active'",
            (workspace_id,),
        )
        evcur = await self.conn.execute(
            """SELECT edge_id, COUNT(*) as c FROM kg_edge_evidence
               WHERE workspace_id = ? AND status = 'active' GROUP BY edge_id""",
            (workspace_id,),
        )
        evidence_counts = {r["edge_id"]: r["c"] for r in await evcur.fetchall()}
        nodes = []
        for r in await ncur.fetchall():
            d = dict(r)
            d["props"] = json.loads(d.pop("props_json") or "{}")
            nodes.append(d)
        edges = []
        for r in await ecur.fetchall():
            d = dict(r)
            d["props"] = json.loads(d.pop("props_json") or "{}")
            d["has_evidence"] = evidence_counts.get(d["id"], 0) > 0
            edges.append(d)
        return {"nodes": nodes, "edges": edges}

    async def get_edge_evidence(
        self, workspace_id: str, edge_ids: list[str]
    ) -> list[dict[str, Any]]:
        if not edge_ids:
            return []
        placeholders = ",".join("?" * len(edge_ids))
        cur = await self.conn.execute(
            f"""SELECT * FROM kg_edge_evidence
                WHERE workspace_id = ? AND status = 'active' AND edge_id IN ({placeholders})""",
            [workspace_id, *edge_ids],
        )
        return [dict(r) for r in await cur.fetchall()]

    async def list_asserted_edges(self, workspace_id: str) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            """SELECT e.* FROM kg_edges e
               WHERE e.workspace_id = ? AND e.edge_class = 'asserted_fact' AND e.status = 'active'
               AND EXISTS (
                 SELECT 1 FROM kg_edge_evidence ev
                 WHERE ev.workspace_id = e.workspace_id AND ev.edge_id = e.id AND ev.status = 'active'
               )""",
            (workspace_id,),
        )
        return [dict(r) for r in await cur.fetchall()]

    # --- chat persistence ---
    async def create_session(self, workspace_id: str, assistant_id: str | None = None) -> str:
        sid = _jid()
        await self.conn.execute(
            "INSERT INTO chat_sessions (id, workspace_id, assistant_id, created_at) VALUES (?, ?, ?, ?)",
            (sid, workspace_id, assistant_id, _now()),
        )
        await self.commit()
        return sid

    async def insert_message(self, workspace_id: str, **fields: Any) -> str:
        mid = fields.get("id") or _jid()
        await self.conn.execute(
            """INSERT INTO chat_messages
               (id, workspace_id, session_id, role, content, decision, reason_codes_json,
                trust_score_json, trust_trail_json, retrieval_mode, provider_mode, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                mid,
                workspace_id,
                fields["session_id"],
                fields["role"],
                fields["content"],
                fields.get("decision"),
                json.dumps(fields.get("reason_codes") or []),
                json.dumps(fields.get("trust_score") or {}),
                json.dumps(fields.get("trust_trail") or []),
                fields.get("retrieval_mode"),
                fields.get("provider_mode"),
                _now(),
            ),
        )
        return mid

    async def insert_claim(self, workspace_id: str, **fields: Any) -> str:
        cid = fields.get("id") or _jid()
        await self.conn.execute(
            """INSERT INTO answer_claims
               (id, workspace_id, message_id, claim_text, support_status, trust_score)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                cid,
                workspace_id,
                fields["message_id"],
                fields["claim_text"],
                fields["support_status"],
                fields.get("trust_score", 0.0),
            ),
        )
        return cid

    async def insert_citation(self, workspace_id: str, **fields: Any) -> str:
        cid = fields.get("id") or _jid()
        await self.conn.execute(
            """INSERT INTO answer_citations
               (id, workspace_id, claim_id, chunk_id, edge_id, quote, locator, document_title)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                cid,
                workspace_id,
                fields["claim_id"],
                fields.get("chunk_id"),
                fields.get("edge_id"),
                fields["quote"],
                fields.get("locator"),
                fields.get("document_title"),
            ),
        )
        return cid

    async def save_cleanstack_report(
        self, workspace_id: str, report: dict[str, Any], job_id: str | None = None
    ) -> str:
        rid = _jid()
        await self.conn.execute(
            """INSERT INTO cleanstack_reports (id, workspace_id, job_id, report_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (rid, workspace_id, job_id, json.dumps(report), _now()),
        )
        await self.commit()
        return rid

    async def get_latest_cleanstack_report(self, workspace_id: str) -> dict[str, Any] | None:
        cur = await self.conn.execute(
            """SELECT report_json, created_at, job_id FROM cleanstack_reports
               WHERE workspace_id = ?
               ORDER BY created_at DESC LIMIT 1""",
            (workspace_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        data = json.loads(row["report_json"] or "{}")
        data["_meta"] = {"created_at": row["created_at"], "job_id": row["job_id"]}
        return data

    async def save_health(
        self, workspace_id: str, score: float, components: dict[str, Any]
    ) -> None:
        await self.conn.execute(
            """INSERT INTO knowledge_health (workspace_id, score, components_json, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(workspace_id) DO UPDATE SET
                 score=excluded.score, components_json=excluded.components_json, updated_at=excluded.updated_at""",
            (workspace_id, score, json.dumps(components), _now()),
        )
        await self.commit()

    async def get_health(self, workspace_id: str) -> dict[str, Any] | None:
        cur = await self.conn.execute(
            "SELECT * FROM knowledge_health WHERE workspace_id = ?", (workspace_id,)
        )
        row = await cur.fetchone()
        if not row:
            return None
        return {
            "score": row["score"],
            "components": json.loads(row["components_json"] or "{}"),
            "updated_at": row["updated_at"],
        }

    async def counts(self, workspace_id: str) -> dict[str, int]:
        async def _c(table: str) -> int:
            cur = await self.conn.execute(
                f"SELECT COUNT(*) AS c FROM {table} WHERE workspace_id = ?",
                (workspace_id,),
            )
            row = await cur.fetchone()
            return int(row["c"]) if row else 0

        return {
            "sources": await _c("source_instances"),
            "documents": await _c("canonical_documents"),
            "chunks": await _c("chunks"),
            "nodes": await _c("kg_nodes"),
            "edges": await _c("kg_edges"),
            "asks": await self.count_asks(workspace_id),
        }

    async def count_asks(self, workspace_id: str) -> int:
        cur = await self.conn.execute(
            """SELECT COUNT(*) AS c FROM chat_messages
               WHERE workspace_id = ? AND role = 'user'""",
            (workspace_id,),
        )
        row = await cur.fetchone()
        return int(row["c"]) if row else 0

    async def studio_totals(self) -> dict[str, int]:
        agents = await self.list_agents()
        published = sum(1 for a in agents if a.get("published"))
        docs = sum(int((a.get("counts") or {}).get("documents") or 0) for a in agents)
        chunks = sum(int((a.get("counts") or {}).get("chunks") or 0) for a in agents)
        nodes = sum(int((a.get("counts") or {}).get("nodes") or 0) for a in agents)
        asks = sum(int((a.get("counts") or {}).get("asks") or 0) for a in agents)
        return {
            "agents": len(agents),
            "published": published,
            "documents": docs,
            "chunks": chunks,
            "nodes": nodes,
            "asks": asks,
        }

    async def studio_intelligence(self) -> dict[str, Any]:
        """Platform-wide Trust Center / AI Findings / Graph Insights (real aggregates)."""
        agents = await self.list_agents()
        totals = await self.studio_totals()

        cur = await self.conn.execute(
            """SELECT decision, retrieval_mode, trust_trail_json
               FROM chat_messages
               WHERE role = 'assistant'
               ORDER BY created_at DESC
               LIMIT 120"""
        )
        ask_rows = await cur.fetchall()
        answered = [r for r in ask_rows if (r["decision"] or "") == "answer"]
        grounded_n = 0
        for r in answered:
            mode = (r["retrieval_mode"] or "").lower()
            trail_raw = r["trust_trail_json"] or "[]"
            has_trail = False
            try:
                trail = json.loads(trail_raw)
                has_trail = isinstance(trail, list) and len(trail) > 0
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
            if "graph" in mode or has_trail:
                grounded_n += 1
        asks_sampled = len(answered)
        grounded_pct = round(100.0 * grounded_n / asks_sampled, 1) if asks_sampled else 0.0

        cur = await self.conn.execute(
            """SELECT
                 SUM(CASE WHEN lower(support_status) IN ('supported','evidence_backed','backed') THEN 1 ELSE 0 END) AS supported,
                 SUM(CASE WHEN lower(support_status) IN ('unsupported','refuted','contradicted') THEN 1 ELSE 0 END) AS unsupported,
                 COUNT(*) AS total
               FROM answer_claims"""
        )
        claim_row = await cur.fetchone()
        claims_total = int(claim_row["total"] or 0) if claim_row else 0
        claims_supported = int(claim_row["supported"] or 0) if claim_row else 0
        unsupported = int(claim_row["unsupported"] or 0) if claim_row else 0

        cur = await self.conn.execute(
            """SELECT
                 (SELECT COUNT(*) FROM kg_edges WHERE status = 'active') AS edges,
                 (SELECT COUNT(DISTINCT ee.edge_id) FROM kg_edge_evidence ee
                    JOIN kg_edges e ON e.id = ee.edge_id AND e.status = 'active') AS evidenced,
                 (SELECT COUNT(*) FROM kg_edges
                    WHERE status = 'active' AND edge_class = 'documentary') AS documentary"""
        )
        erow = await cur.fetchone()
        edges = int(erow["edges"] or 0) if erow else 0
        evidenced = max(int(erow["evidenced"] or 0), int(erow["documentary"] or 0)) if erow else 0
        evidence_pct = round(100.0 * evidenced / edges, 1) if edges else 0.0
        if claims_total > 0:
            # Prefer claim-level evidence when answers exist
            evidence_pct = round(
                0.55 * evidence_pct + 0.45 * (100.0 * claims_supported / claims_total),
                1,
            )

        cur = await self.conn.execute(
            """SELECT COUNT(*) AS c FROM kg_edges
               WHERE status = 'active'
                 AND (lower(rel_type) LIKE '%conflict%'
                      OR lower(rel_type) = 'conflicts_with')"""
        )
        conflicts = int((await cur.fetchone())["c"] or 0)

        docs = int(totals.get("documents") or 0)
        nodes = int(totals.get("nodes") or 0)
        if docs == 0 or nodes == 0:
            status = "building"
        elif conflicts > 0 or unsupported > 0 or (asks_sampled >= 3 and grounded_pct < 70):
            status = "review"
        elif asks_sampled == 0 and evidence_pct >= 50:
            status = "trusted"
        elif grounded_pct >= 70 or evidence_pct >= 75:
            status = "trusted"
        else:
            status = "review"

        cur = await self.conn.execute(
            """SELECT COUNT(*) AS c FROM kg_nodes
               WHERE type NOT IN ('Document', 'Chunk', 'Section')"""
        )
        concepts = int((await cur.fetchone())["c"] or 0)

        cur = await self.conn.execute(
            """SELECT COUNT(*) AS c FROM kg_nodes
               WHERE type NOT IN ('Document', 'Chunk', 'Section')
                 AND (
                   lower(type) LIKE '%compliance%'
                   OR lower(type) LIKE '%obligation%'
                   OR lower(type) LIKE '%rule%'
                   OR lower(type) LIKE '%policy%'
                   OR lower(name) LIKE '%compliance%'
                   OR lower(name) LIKE '%obligation%'
                 )"""
        )
        compliance_n = int((await cur.fetchone())["c"] or 0)

        cur = await self.conn.execute(
            """SELECT COUNT(*) AS c FROM kg_edges
               WHERE status = 'active'
                 AND (edge_class IN ('documentary', 'derived')
                      OR id IN (SELECT edge_id FROM kg_edge_evidence))"""
        )
        discovered_rels = int((await cur.fetchone())["c"] or 0)

        findings: list[dict[str, str]] = []
        if compliance_n:
            findings.append(
                {
                    "kind": "ok",
                    "text": f"Identified {compliance_n} compliance / obligation concepts",
                }
            )
        if concepts:
            findings.append(
                {"kind": "ok", "text": f"Extracted {concepts:,} key concepts across agents"}
            )
        if discovered_rels:
            findings.append(
                {
                    "kind": "ok",
                    "text": f"Bound {discovered_rels:,} evidence-linked relationships",
                }
            )
        if conflicts:
            findings.append(
                {
                    "kind": "warn",
                    "text": f"Detected {conflicts} conflicting statements in the graph",
                }
            )
        if unsupported:
            findings.append(
                {
                    "kind": "warn",
                    "text": f"{unsupported} unsupported claims flagged in recent answers",
                }
            )
        if not findings:
            if docs == 0:
                findings.append(
                    {"kind": "info", "text": "Connect a knowledge base to start discovering evidence"}
                )
            else:
                findings.append(
                    {
                        "kind": "info",
                        "text": "Graph is warming — Ask questions to surface trust trails",
                    }
                )

        cur = await self.conn.execute(
            """SELECT AVG(score) AS s FROM knowledge_health"""
        )
        hrow = await cur.fetchone()
        health = round(float(hrow["s"] or 0), 1) if hrow and hrow["s"] is not None else 0.0
        if health <= 0 and edges and nodes:
            # Lightweight fallback when health rows are stale/missing
            health = round(min(100.0, 40 + evidence_pct * 0.4 + min(concepts, 500) / 20), 1)

        cur = await self.conn.execute(
            """SELECT n.name AS name, COUNT(*) AS deg
               FROM kg_nodes n
               JOIN kg_edges e
                 ON e.workspace_id = n.workspace_id
                AND e.status = 'active'
                AND (e.src = n.id OR e.dst = n.id)
               WHERE n.type NOT IN ('Document', 'Chunk', 'Section')
               GROUP BY n.id
               ORDER BY deg DESC
               LIMIT 1"""
        )
        top_node = await cur.fetchone()
        most_connected = (top_node["name"] if top_node else "") or ""

        top_agent = ""
        top_asks = 0
        for a in agents:
            asks = int((a.get("counts") or {}).get("asks") or 0)
            if asks >= top_asks:
                top_asks = asks
                top_agent = a.get("name") or ""

        return {
            "trust": {
                "grounded_pct": grounded_pct,
                "evidence_coverage_pct": evidence_pct,
                "unsupported_claims": unsupported,
                "conflicts": conflicts,
                "asks_sampled": asks_sampled,
                "status": status,
            },
            "findings": findings[:5],
            "graph": {
                "health_score": health,
                "most_connected": most_connected[:80],
                "top_agent": top_agent,
                "top_agent_asks": top_asks,
                "concepts": concepts,
                "relationships": edges,
            },
        }

    async def purge_knowledge(self, workspace_id: str) -> dict[str, Any]:
        """Remove graph + corpus for a workspace. Keeps workspace/assistant rows."""
        before = await self.counts(workspace_id)
        tables = [
            "answer_citations",
            "answer_claims",
            "chat_messages",
            "chat_sessions",
            "kg_edge_evidence",
            "entity_aliases",
            "kg_edges",
            "kg_nodes",
            "chunks",
            "source_instances",
            "canonical_documents",
            "cleanstack_reports",
            "knowledge_health",
            "jobs",
        ]
        for table in tables:
            await self.conn.execute(
                f"DELETE FROM {table} WHERE workspace_id = ?",
                (workspace_id,),
            )
        await self.commit()
        after = await self.counts(workspace_id)
        return {"before": before, "after": after}

    async def hygiene_knowledge(self, workspace_id: str) -> dict[str, Any]:
        """Prune bad aliases, retype junk Person nodes, report graph health."""
        aliases_removed = await self._prune_bad_aliases(workspace_id)
        persons_fixed = await self._retype_junk_persons(workspace_id)
        await self.commit()
        cur = await self.conn.execute(
            """SELECT COUNT(*) AS c FROM entity_aliases WHERE workspace_id = ?""",
            (workspace_id,),
        )
        alias_count = int((await cur.fetchone())["c"])
        cur = await self.conn.execute(
            """SELECT COUNT(*) AS c FROM kg_nodes
               WHERE workspace_id = ? AND type NOT IN ('Document','Chunk','Section')""",
            (workspace_id,),
        )
        entity_count = int((await cur.fetchone())["c"])
        cur = await self.conn.execute(
            """SELECT COUNT(*) AS c FROM kg_nodes
               WHERE workspace_id = ?
               AND type NOT IN ('Document','Chunk','Section')
               AND (
                 name GLOB '[A-Za-z][A-Za-z]*[0-9][0-9]*'
                 OR lower(name) LIKE '%security level%'
               )""",
            (workspace_id,),
        )
        code_nodes = int((await cur.fetchone())["c"])
        return {
            "aliases_removed": aliases_removed,
            "junk_persons_retyped": persons_fixed,
            "alias_count": alias_count,
            "entity_count": entity_count,
            "code_or_level_nodes": code_nodes,
        }

    async def _prune_bad_aliases(self, workspace_id: str) -> int:
        cur = await self.conn.execute(
            """SELECT a.id, a.alias, a.normalized_alias, n.name, n.normalized_name, n.type
               FROM entity_aliases a
               JOIN kg_nodes n ON n.id = a.node_id
               WHERE a.workspace_id = ?""",
            (workspace_id,),
        )
        rows = [dict(r) for r in await cur.fetchall()]
        removed = 0
        for r in rows:
            if _alias_fits_node(
                alias=str(r.get("alias") or ""),
                alias_norm=str(r.get("normalized_alias") or ""),
                node_name=str(r.get("name") or ""),
                node_norm=str(r.get("normalized_name") or ""),
                node_type=str(r.get("type") or ""),
            ):
                continue
            await self.conn.execute(
                "DELETE FROM entity_aliases WHERE id = ?", (r["id"],)
            )
            removed += 1
        return removed

    async def _retype_junk_persons(self, workspace_id: str) -> int:
        """Single-token 'Person' nodes without email are usually weave noise."""
        cur = await self.conn.execute(
            """SELECT id, name FROM kg_nodes
               WHERE workspace_id = ? AND type = 'Person'""",
            (workspace_id,),
        )
        fixed = 0
        for r in await cur.fetchall():
            name = str(r["name"] or "").strip()
            if "@" in name:
                continue
            tokens = name.split()
            # Keep plausible people: First Last
            if len(tokens) >= 2 and all(t[:1].isupper() for t in tokens if t.isalpha()):
                continue
            # Retype junk: Android, Brand, Standard, Certificate, …
            await self.conn.execute(
                "UPDATE kg_nodes SET type = 'Concept' WHERE id = ?",
                (r["id"],),
            )
            fixed += 1
        return fixed


def _alias_fits_node(
    *,
    alias: str,
    alias_norm: str,
    node_name: str,
    node_norm: str,
    node_type: str,
) -> bool:
    """True when an alias is a reasonable alternate label for the node."""
    a = (alias_norm or alias or "").strip().lower()
    n = (node_norm or node_name or "").strip().lower()
    if not a or not n:
        return False
    if a == n:
        return True
    a_alnum = re.sub(r"[^a-z0-9]", "", a)
    n_alnum = re.sub(r"[^a-z0-9]", "", n)
    if not a_alnum or not n_alnum:
        return False
    # Product codes / short nodes: alias must contain node key
    if len(n_alnum) <= 12:
        return n_alnum in a_alnum and len(a_alnum) <= max(len(n_alnum) * 3, 24)
    # Longer names: require substantial overlap (node key inside alias or vice versa)
    if n_alnum in a_alnum:
        return len(a_alnum) <= len(n_alnum) * 2.5
    if a_alnum in n_alnum and len(a_alnum) >= 6:
        return True
    # Token overlap (at least one meaningful shared token ≥5 chars)
    a_toks = {t for t in re.findall(r"[a-z0-9]{5,}", a)}
    n_toks = {t for t in re.findall(r"[a-z0-9]{5,}", n)}
    if a_toks & n_toks:
        return True
    # Never attach long English phrases to Product unless they contain the product name
    if node_type == "Product" and len(a.split()) >= 3 and n_alnum not in a_alnum:
        return False
    return False


def _normalize(name: str) -> str:
    """Shared with GraphWeaver via app.identity."""
    return normalize_entity_name(name)
