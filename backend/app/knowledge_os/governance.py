"""Governance: versions, rollback, audit, policy, SLOs — same workspace graph."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.db import get_connection
from app.knowledge_os.diff import diff_payloads

LIVE = "live"
SHADOW = "shadow"
GATED = "gated"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jid() -> str:
    return str(uuid4())


async def learning_mode(store: Any, workspace_id: str) -> str:
    agent = await store.get_agent_by_workspace(workspace_id)
    settings = agent.get("settings") if agent else {}
    if isinstance(settings, str):
        try:
            settings = json.loads(settings)
        except json.JSONDecodeError:
            settings = {}
    if not isinstance(settings, dict):
        settings = {}
    mode = str(settings.get("learningMode") or LIVE).lower()
    if mode in {SHADOW, GATED, LIVE, "off"}:
        return mode
    return LIVE


async def locked_edge_ids(workspace_id: str) -> set[str]:
    conn = await get_connection()
    try:
        cur = await conn.execute(
            """SELECT target FROM kg_policies
               WHERE workspace_id = ? AND kind = 'lock_edge'""",
            (workspace_id,),
        )
        edges = {str(r["target"]) for r in await cur.fetchall()}
        cur = await conn.execute(
            """SELECT target FROM kg_policies
               WHERE workspace_id = ? AND kind = 'lock_rel'""",
            (workspace_id,),
        )
        rels = {str(r["target"] or "").upper() for r in await cur.fetchall()}
    except Exception:  # noqa: BLE001
        return set()
    finally:
        await conn.close()
    if not rels:
        return edges
    conn = await get_connection()
    try:
        cur = await conn.execute(
            """SELECT id, rel_type FROM kg_edges
               WHERE workspace_id = ? AND status = 'active'""",
            (workspace_id,),
        )
        for r in await cur.fetchall():
            if str(r["rel_type"] or "").upper() in rels:
                edges.add(str(r["id"]))
    finally:
        await conn.close()
    return edges


async def apply_learning(
    store: Any,
    workspace_id: str,
    *,
    edge_ids: list[str],
    won: bool,
) -> str:
    """Apply or shadow-record learning. Returns mode used."""
    from app.knowledge_os.learn import path_key

    mode = await learning_mode(store, workspace_id)
    ids = [e for e in edge_ids if e]
    if not ids:
        return mode
    if mode == "off":
        return mode
    locked = await locked_edge_ids(workspace_id)
    ids = [e for e in ids if e not in locked]
    if not ids:
        return mode
    delta = 0.045 if won else -0.04
    apply = mode == LIVE
    await store.bump_edge_weights(
        workspace_id,
        ids,
        delta,
        reason=f"path_{'win' if won else 'lose'}",
        apply=apply,
    )
    if apply:
        await store.record_path_outcome(workspace_id, path_key(ids), won=won)
    await store.commit()
    return mode


async def graph_census(store: Any, workspace_id: str) -> dict[str, Any]:
    cur = await store.conn.execute(
        """SELECT type, COUNT(*) AS c FROM kg_nodes
           WHERE workspace_id = ? GROUP BY type""",
        (workspace_id,),
    )
    by_type = {str(r["type"]): int(r["c"] or 0) for r in await cur.fetchall()}
    cur = await store.conn.execute(
        """SELECT rel_type, COUNT(*) AS c FROM kg_edges
           WHERE workspace_id = ? AND status = 'active' GROUP BY rel_type""",
        (workspace_id,),
    )
    by_rel = {str(r["rel_type"]): int(r["c"] or 0) for r in await cur.fetchall()}
    return {
        "topic_nodes": int(by_type.get("Topic") or 0),
        "section_nodes": int(by_type.get("Section") or 0),
        "nodes": sum(by_type.values()),
        "contradictions": int(by_rel.get("CONFLICTS_WITH") or 0),
        "edges": sum(by_rel.values()),
    }


async def capture_version(
    store: Any,
    workspace_id: str,
    *,
    label: str,
    status: str = "snapshot",
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cur = await store.conn.execute(
        """SELECT id, weight, status, rel_type FROM kg_edges WHERE workspace_id = ?""",
        (workspace_id,),
    )
    edges = [dict(r) for r in await cur.fetchall()]
    stats = await store.path_stats_map(workspace_id)
    census = await graph_census(store, workspace_id)
    merged = {**census, **(metrics or {})}
    payload = {
        "edges": [
            {
                "id": e["id"],
                "weight": float(e["weight"] or 1),
                "status": e.get("status") or "active",
                "rel_type": e.get("rel_type"),
            }
            for e in edges
        ],
        "path_stats": [
            {"key": k, "wins": w, "losses": l} for k, (w, l) in stats.items()
        ],
        "metrics": merged,
    }
    vid = _jid()
    conn = await get_connection()
    try:
        await conn.execute(
            """INSERT INTO graph_versions (
                id, workspace_id, label, status, metrics_json, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                vid,
                workspace_id,
                label[:120],
                status,
                json.dumps(merged),
                json.dumps(payload),
                _now(),
            ),
        )
        await conn.commit()
    finally:
        await conn.close()
    return {"id": vid, "label": label, "status": status, "edges": len(edges)}


async def restore_version(store: Any, workspace_id: str, version_id: str) -> dict[str, Any]:
    conn = await get_connection()
    try:
        cur = await conn.execute(
            """SELECT id, payload_json, label FROM graph_versions
               WHERE id = ? AND workspace_id = ?""",
            (version_id, workspace_id),
        )
        row = await cur.fetchone()
    finally:
        await conn.close()
    if not row:
        raise KeyError("version_not_found")
    payload = json.loads(row["payload_json"] or "{}")
    n = 0
    for e in payload.get("edges") or []:
        await store.conn.execute(
            """UPDATE kg_edges SET weight = ?, status = ?
               WHERE id = ? AND workspace_id = ?""",
            (
                float(e.get("weight") or 1),
                e.get("status") or "active",
                e.get("id"),
                workspace_id,
            ),
        )
        n += 1
    await store.conn.execute(
        "DELETE FROM kg_path_stats WHERE workspace_id = ?", (workspace_id,)
    )
    now = _now()
    for p in payload.get("path_stats") or []:
        await store.conn.execute(
            """INSERT INTO kg_path_stats (path_key, workspace_id, wins, losses, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                p.get("key"),
                workspace_id,
                int(p.get("wins") or 0),
                int(p.get("losses") or 0),
                now,
            ),
        )
    await store.commit()
    conn = await get_connection()
    try:
        await conn.execute(
            """UPDATE graph_versions SET status = 'rolled_back'
               WHERE workspace_id = ? AND status = 'promoted'""",
            (workspace_id,),
        )
        await conn.execute(
            "UPDATE graph_versions SET status = 'promoted' WHERE id = ? AND workspace_id = ?",
            (version_id, workspace_id),
        )
        await conn.commit()
    finally:
        await conn.close()
    await write_audit(
        workspace_id,
        entity_type="graph",
        entity_id=version_id,
        field="rollback",
        old_value="",
        new_value=row["label"] or version_id,
        reason="restore_snapshot",
    )
    return {"ok": True, "restored_edges": n, "version_id": version_id}


async def promote_version(workspace_id: str, version_id: str) -> dict[str, Any]:
    conn = await get_connection()
    try:
        cur = await conn.execute(
            "SELECT id FROM graph_versions WHERE id = ? AND workspace_id = ?",
            (version_id, workspace_id),
        )
        if not await cur.fetchone():
            raise KeyError("version_not_found")
        await conn.execute(
            """UPDATE graph_versions SET status = 'superseded'
               WHERE workspace_id = ? AND status = 'promoted'""",
            (workspace_id,),
        )
        await conn.execute(
            "UPDATE graph_versions SET status = 'promoted' WHERE id = ? AND workspace_id = ?",
            (version_id, workspace_id),
        )
        await conn.commit()
    finally:
        await conn.close()
    await write_audit(
        workspace_id,
        entity_type="graph",
        entity_id=version_id,
        field="status",
        old_value="candidate",
        new_value="promoted",
        reason="human_promote",
    )
    return {"ok": True, "status": "promoted"}


async def list_versions(workspace_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    conn = await get_connection()
    try:
        cur = await conn.execute(
            """SELECT id, label, status, metrics_json, payload_json, created_at
               FROM graph_versions WHERE workspace_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (workspace_id, limit),
        )
        raw = []
        for r in await cur.fetchall():
            try:
                metrics = json.loads(r["metrics_json"] or "{}")
            except json.JSONDecodeError:
                metrics = {}
            try:
                payload = json.loads(r["payload_json"] or "{}")
            except json.JSONDecodeError:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            inner = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
            payload["metrics"] = {**metrics, **inner}
            raw.append(
                {
                    "id": r["id"],
                    "label": r["label"],
                    "status": r["status"],
                    "metrics": metrics,
                    "created_at": r["created_at"],
                    "_payload": payload,
                }
            )
        chrono = list(reversed(raw))
        prev_payload: dict[str, Any] | None = None
        prev_id = ""
        prev_label = ""
        diffs: dict[str, dict[str, Any]] = {}
        for row in chrono:
            if prev_payload is not None:
                d = diff_payloads(prev_payload, row["_payload"])
                d["vs_id"] = prev_id
                d["vs_label"] = prev_label
                diffs[row["id"]] = d
            prev_payload = row["_payload"]
            prev_id = row["id"]
            prev_label = row["label"]
        rows = []
        for row in raw:
            item = {k: v for k, v in row.items() if k != "_payload"}
            item["vs_previous"] = diffs.get(row["id"])
            rows.append(item)
        return rows
    finally:
        await conn.close()


async def write_audit(
    workspace_id: str,
    *,
    entity_type: str,
    entity_id: str,
    field: str,
    old_value: str,
    new_value: str,
    reason: str,
    applied: int = 1,
) -> None:
    conn = await get_connection()
    try:
        await conn.execute(
            """INSERT INTO kg_audit (
                id, workspace_id, entity_type, entity_id, field,
                old_value, new_value, reason, applied, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                _jid(),
                workspace_id,
                entity_type,
                entity_id,
                field,
                (old_value or "")[:200],
                (new_value or "")[:200],
                (reason or "")[:160],
                applied,
                _now(),
            ),
        )
        await conn.commit()
    except Exception:  # noqa: BLE001
        pass
    finally:
        await conn.close()


async def list_audit(workspace_id: str, *, limit: int = 30) -> list[dict[str, Any]]:
    conn = await get_connection()
    try:
        cur = await conn.execute(
            """SELECT * FROM kg_audit WHERE workspace_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (workspace_id, limit),
        )
        return [dict(r) for r in await cur.fetchall()]
    except Exception:  # noqa: BLE001
        return []
    finally:
        await conn.close()


async def record_metric_snapshot(
    workspace_id: str, metrics: dict[str, Any]
) -> None:
    conn = await get_connection()
    try:
        await conn.execute(
            """INSERT INTO knowledge_metric_snapshots (id, workspace_id, metrics_json, created_at)
               VALUES (?, ?, ?, ?)""",
            (_jid(), workspace_id, json.dumps(metrics), _now()),
        )
        await conn.commit()
    except Exception:  # noqa: BLE001
        pass
    finally:
        await conn.close()


async def list_metric_snapshots(
    workspace_id: str, *, limit: int = 14
) -> list[dict[str, Any]]:
    conn = await get_connection()
    try:
        cur = await conn.execute(
            """SELECT metrics_json, created_at FROM knowledge_metric_snapshots
               WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?""",
            (workspace_id, limit),
        )
        out = []
        for r in await cur.fetchall():
            try:
                m = json.loads(r["metrics_json"] or "{}")
            except json.JSONDecodeError:
                m = {}
            m["created_at"] = r["created_at"]
            out.append(m)
        return list(reversed(out))
    except Exception:  # noqa: BLE001
        return []
    finally:
        await conn.close()


async def compute_slos(workspace_id: str) -> dict[str, Any]:
    conn = await get_connection()
    try:
        cur = await conn.execute(
            """SELECT decision, trust_score_json FROM chat_messages
               WHERE workspace_id = ? AND role = 'assistant'
               ORDER BY created_at DESC LIMIT 200""",
            (workspace_id,),
        )
        rows = await cur.fetchall()
    except Exception:  # noqa: BLE001
        rows = []
    finally:
        await conn.close()
    n = len(rows)
    if not n:
        return {
            "asks": 0,
            "refusal_rate": None,
            "avg_trust": None,
            "answer_rate": None,
        }
    refuse = sum(1 for r in rows if (r["decision"] or "").lower() == "refuse")
    answer = sum(1 for r in rows if (r["decision"] or "").lower() == "answer")
    trusts: list[float] = []
    for r in rows:
        try:
            t = json.loads(r["trust_score_json"] or "{}")
            trusts.append(float(t.get("overall") or 0))
        except Exception:  # noqa: BLE001
            pass
    return {
        "asks": n,
        "refusal_rate": round(refuse / n, 4),
        "answer_rate": round(answer / n, 4),
        "avg_trust": round(sum(trusts) / max(len(trusts), 1), 3) if trusts else None,
    }


async def add_policy(
    workspace_id: str, *, kind: str, target: str, note: str = ""
) -> dict[str, Any]:
    kind = kind if kind in {"lock_edge", "lock_rel", "authoritative_source"} else "lock_rel"
    conn = await get_connection()
    try:
        pid = _jid()
        await conn.execute(
            """INSERT INTO kg_policies (id, workspace_id, kind, target, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (pid, workspace_id, kind, target[:200], note[:300], _now()),
        )
        await conn.commit()
    finally:
        await conn.close()
    return {"id": pid, "kind": kind, "target": target}


async def list_policies(workspace_id: str) -> list[dict[str, Any]]:
    conn = await get_connection()
    try:
        cur = await conn.execute(
            """SELECT id, kind, target, note, created_at FROM kg_policies
               WHERE workspace_id = ? ORDER BY created_at DESC LIMIT 50""",
            (workspace_id,),
        )
        return [dict(r) for r in await cur.fetchall()]
    except Exception:  # noqa: BLE001
        return []
    finally:
        await conn.close()
