"""Background care: quality maintenance, never policy changes.

Invariant (keep forever):
  Care can detect, suggest, and maintain.
  Care cannot govern.

  Allowed: contradiction detection, health recalculation, hygiene reports,
  metric refresh, CONFLICTS_WITH annotations in the night window.
  Forbidden: draft accept, version promote/rollback, policy locks,
  ingesting new knowledge, rewriting topic hierarchy or locked facts.
"""

from __future__ import annotations

import logging
from typing import Any

from app.knowledge_os import hygiene as hyg
from app.knowledge_os import operate as kop

log = logging.getLogger("vera.care")

# Never implement these in tick_workspace. Humans only.
CARE_MUST_NOT = (
    "accept_drafts",
    "promote_versions",
    "rollback_versions",
    "change_policy_locks",
    "ingest_knowledge",
    "rewrite_hierarchy",
    "rewrite_locked_facts",
)


def briefing(
    *,
    sla: dict[str, Any] | None,
    ingest_busy: bool,
    forge_busy: bool,
    node_count: int,
) -> dict[str, Any]:
    sla = sla or {}
    if ingest_busy:
        return {
            "mode": "defer",
            "headline": "Connect is weaving. Care waits so daily Ask is not interrupted.",
            "human": False,
            "cta": None,
        }
    if forge_busy:
        return {
            "mode": "defer",
            "headline": "Evaluate is scoring. Ask stays on the current graph.",
            "human": False,
            "cta": None,
        }
    if node_count <= 0:
        return {
            "mode": "human",
            "headline": "No graph yet. Connect a source — care has nothing to maintain.",
            "human": True,
            "cta": "connect",
        }
    cta = sla.get("cta")
    if sla.get("passing"):
        return {
            "mode": "ok",
            "headline": "Pack is within SLA. Care is idle.",
            "human": False,
            "cta": None,
        }
    if cta == "connect":
        return {
            "mode": "human",
            "headline": sla.get("next") or "Coverage needs new sources.",
            "human": True,
            "cta": "connect",
        }
    if cta == "playbook":
        return {
            "mode": "human",
            "headline": sla.get("next") or "Debt playbook needs a person.",
            "human": True,
            "cta": "playbook",
        }
    return {
        "mode": "auto",
        "headline": sla.get("next") or "Care will scan when the maintenance window opens.",
        "human": False,
        "cta": cta,
    }


async def workspace_busy(store: Any, workspace_id: str) -> str | None:
    job = await store.get_active_ingest_job(workspace_id)
    if job:
        return "ingest"
    try:
        from app.trust_forge.service import list_runs

        runs = await list_runs(workspace_id, limit=1)
        st = (runs[0] or {}).get("status") if runs else None
        if st in {"queued", "running"}:
            return "evaluate"
    except Exception:  # noqa: BLE001
        pass
    return None


async def tick_workspace(store: Any, workspace_id: str) -> dict[str, Any]:
    """Maintenance window: conflict scan + metric snapshot.

    Never accepts drafts, promotes versions, deletes nodes, or rewrites hierarchy.
    """
    from app.config import get_settings
    from app.knowledge_os.governance import record_metric_snapshot
    from app.knowledge_os.service import enrich_graph

    reason = await workspace_busy(store, workspace_id)
    if reason:
        return {"ok": True, "skipped": reason, "workspace_id": workspace_id}

    settings = get_settings()
    window = kop.in_maintenance_window(
        hour_utc=kop.utc_hour(),
        start_hour=int(settings.vera_care_window_utc_hour),
        duration_hours=int(settings.vera_care_window_hours),
    )
    graph = await store.get_graph(workspace_id)
    if not (graph.get("nodes") or []):
        return {"ok": True, "skipped": "empty", "workspace_id": workspace_id}

    docs = await store.list_canonical_documents(workspace_id)
    try:
        stats = await store.path_stats_map(workspace_id)
    except Exception:  # noqa: BLE001
        stats = {}
    report = hyg.scan(graph, path_stats=stats, docs=docs)

    if not window:
        return {
            "ok": True,
            "skipped": "daytime",
            "workspace_id": workspace_id,
            "hygiene": report.get("counts"),
        }

    enrich = await enrich_graph(store, workspace_id)
    await record_metric_snapshot(
        workspace_id,
        {
            "debt": None,
            "coverage": None,
            "urls": report.get("source_urls") or [],
            "hygiene": report.get("counts"),
            "origin": "care_window",
        },
    )
    log.info("care window %s enrich=%s hygiene=%s", workspace_id, enrich, report.get("counts"))
    return {
        "ok": True,
        "did": "maintenance",
        "workspace_id": workspace_id,
        **enrich,
        "hygiene": report.get("counts"),
    }


async def tick_fleet() -> dict[str, Any]:
    from app.stores.sql import WorkspaceStore

    ticks: list[dict[str, Any]] = []
    async with WorkspaceStore() as store:
        for ws in await store.list_workspaces():
            wid = str(ws.get("id") or "")
            if not wid:
                continue
            try:
                ticks.append(await tick_workspace(store, wid))
            except Exception:  # noqa: BLE001
                log.exception("care tick failed for %s", wid)
                ticks.append({"ok": False, "workspace_id": wid})
    return {"ok": True, "ticks": ticks}
