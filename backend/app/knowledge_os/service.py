"""Assemble the Knowledge OS dashboard and run OS-grade heals."""

from __future__ import annotations

import json
import logging
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.db import get_connection
from app.knowledge.sources.web.site_graph import trust_weight
from app.knowledge_os.conflicts import apply_conflict_edges, find_value_conflicts
from app.knowledge_os.coverage import coverage_report
from app.knowledge_os.debt import debt_drilldown, improvement_loop, knowledge_debt

log = logging.getLogger("vera.knowledge_os")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def snapshot(store: Any, workspace_id: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    docs = await store.list_canonical_documents(workspace_id)
    graph = await store.get_graph(workspace_id)
    cover = coverage_report(docs, graph)
    conflicts = find_value_conflicts(graph)
    supersedes = sum(
        1
        for e in graph.get("edges") or []
        if (e.get("rel_type") or "").upper() == "SUPERSEDES"
    )
    conflict_edges = sum(
        1
        for e in graph.get("edges") or []
        if (e.get("rel_type") or "").upper() == "CONFLICTS_WITH"
    )
    feedback = await feedback_stats(workspace_id)
    production = await production_learning(workspace_id)
    drafts = []
    try:
        drafts = await store.list_draft_goldens(workspace_id)
    except Exception:  # noqa: BLE001
        drafts = []
    draft_open = [d for d in drafts if d.get("status") == "draft"]
    trust_avg = 0.0
    if docs:
        trust_avg = round(sum(trust_weight(d.get("title") or "") for d in docs) / len(docs), 3)
    asserted = [
        e
        for e in graph.get("edges") or []
        if (e.get("edge_class") or "") == "asserted_fact" and (e.get("status") or "active") == "active"
    ]
    weak_edges = sum(1 for e in asserted if float(e.get("weight") or 1) < 0.55)
    unanswered = len(draft_open) + len((production or {}).get("weak") or [])
    path_stats: dict[str, tuple[int, int]] = {}
    try:
        path_stats = await store.path_stats_map(workspace_id)
        path_n = len(path_stats)
    except Exception:  # noqa: BLE001
        path_n = 0
    debt = knowledge_debt(
        coverage_pct=float(cover.get("overall_pct") or 0),
        source_reliability=trust_avg,
        conflict_count=len(conflicts) + conflict_edges,
        weak_edge_count=weak_edges,
        asserted_edges=len(asserted),
        unanswered=unanswered,
        gap_sections=len(cover.get("gap_sections") or []),
    )
    debt["drilldown"] = debt_drilldown(
        graph=graph,
        path_stats=path_stats,
        docs=docs,
        cover=cover,
        conflicts=conflicts,
        drafts=draft_open,
        production_weak=list((production or {}).get("weak") or []),
    )
    debt["playbook"] = improvement_loop(debt)
    try:
        from app.knowledge_os.proof import suggest_actions

        await suggest_actions(
            workspace_id, debt["playbook"], debt=float(debt.get("score") or 0)
        )
    except Exception:  # noqa: BLE001
        pass

    fitness = _fitness(
        cover_pct=float(cover.get("overall_pct") or 0),
        conflicts=len(conflicts) + conflict_edges,
        feedback=feedback,
        docs=len(docs),
    )
    versions = await _gov_versions(workspace_id)
    trends = await _gov_trends(workspace_id)
    from app.knowledge_os.proof import action_stats, build_ops_report

    astats = await action_stats(workspace_id)
    remaining = [
        str(a.get("do") or a.get("cause") or "")
        for a in (debt.get("playbook") or {}).get("actions") or []
    ]
    proof = build_ops_report(
        points=list(trends),
        current={
            "debt": debt.get("score"),
            "coverage": cover.get("overall_pct"),
            "trust": debt.get("trust_pct"),
            "risk": (debt.get("risk") or {}).get("level"),
            "created_at": _now(),
        },
        versions=versions,
        suggested=int(astats.get("suggested") or 0),
        completed=int(astats.get("completed") or 0),
        by_driver=dict(astats.get("by_driver") or {}),
        remaining=remaining,
    )
    from app.knowledge_os import control as koc

    recs = koc.gap_recommendations(cover, docs)
    gov_src = await koc.load_source_gov(workspace_id)
    sources = koc.source_rows(docs, gov_src)
    ages = [float(s["age_days"]) for s in sources if s.get("age_days") is not None]
    fresh_avg = (sum(ages) / len(ages)) if ages else None
    eq = koc.evidence_quality(
        trust_pct=float(debt.get("trust_pct") or 0),
        coverage_pct=float(cover.get("overall_pct") or 0),
        conflict_count=len(conflicts) + conflict_edges,
        freshness_avg_days=fresh_avg,
    )
    goals = await koc.load_goals(workspace_id)
    sla = koc.sla_status(
        coverage=float(cover.get("overall_pct") or 0),
        debt=float(debt.get("score") or 0),
        # Detected pairs only — do not add CONFLICTS_WITH edges or we double-count after Care.
        contradictions=len(conflicts),
        targets={
            "coverage_min": goals.get("target_coverage"),
            "debt_max": goals.get("target_debt"),
        },
    )
    accepted = len([d for d in drafts if d.get("status") == "accepted"])
    fit_pts = [float(p["fitness"]) for p in trends if p.get("fitness") is not None]
    fit_delta = round(fit_pts[-1] - fit_pts[0], 1) if len(fit_pts) >= 2 else None
    done_acts = await koc.list_done_actions(workspace_id)
    stability = None
    try:
        from app.trust_forge.service import list_runs

        runs = await list_runs(workspace_id, limit=1)
        cm = (runs[0].get("case_matrix") if runs else None) or {}
        sm = cm.get("summary") if isinstance(cm, dict) else None
        if isinstance(sm, dict):
            stability = {
                "improved": sm.get("improved"),
                "degraded": sm.get("regressed"),
                "still_fail": sm.get("still_fail"),
                "total": sm.get("total"),
            }
    except Exception:  # noqa: BLE001
        stability = None
    graph_n = len(graph.get("nodes") or [])
    graph_e = len(graph.get("edges") or [])
    ops = {
        "recommendations": recs,
        "sources": sources,
        "sla": sla,
        "goals": koc.goal_progress(
            {
                "debt": float(debt.get("score") or 0),
                "coverage": float(cover.get("overall_pct") or 0),
            },
            goals,
        ),
        "evidence_quality": eq,
        "simulation": koc.simulate_playbook(debt, recs),
        "feed": koc.change_feed(versions, done_acts),
        "attribution": koc.attribution(versions, dict(astats.get("by_driver") or {})),
        "domains": koc.domain_confidence(cover),
        "impact_debt": koc.impact_aware_debt(list(debt.get("drivers") or []), recs),
        "benchmarks": koc.list_benchmarks(),
        "learning_efficiency": koc.learning_efficiency(
            accepted_drafts=accepted, fitness_delta=fit_delta
        ),
        "explain": koc.explain(proof, debt, sla),
        "scale": koc.scale_card(
            nodes=graph_n,
            edges=graph_e,
            docs=len(docs),
            snapshot_ms=(time.perf_counter() - t0) * 1000.0,
        ),
        "stability": stability,
        "roles": {
            "analyst": "Ask",
            "knowledge_manager": "Accept drafts · mark loop actions",
            "admin": "Promote / rollback versions",
        },
    }
    from app.config import get_settings
    from app.knowledge_os import hygiene as hyg
    from app.knowledge_os import operate as kop
    from app.knowledge_os.care import briefing as care_briefing
    from app.knowledge_os.care import workspace_busy

    settings = get_settings()
    hyg_rep = hyg.scan(graph, path_stats=path_stats, docs=docs)
    prev_urls: list[str] = []
    for p in reversed(list(trends)):
        u = p.get("urls")
        if isinstance(u, list) and u:
            prev_urls = [str(x) for x in u]
            break
    src_delta = kop.source_delta(prev_urls, list(hyg_rep.get("source_urls") or []))
    window = kop.in_maintenance_window(
        hour_utc=kop.utc_hour(),
        start_hour=int(settings.vera_care_window_utc_hour),
        duration_hours=int(settings.vera_care_window_hours),
    )
    busy = await workspace_busy(store, workspace_id)
    ops["care"] = care_briefing(
        sla=sla,
        ingest_busy=busy == "ingest",
        forge_busy=busy == "evaluate",
        node_count=graph_n,
    )
    refusals = len(
        [w for w in ((production or {}).get("weak") or []) if str(w.get("decision") or "") == "refuse"]
    )
    ops["operate"] = kop.board(
        debt=debt,
        sla=sla,
        playbook=debt.get("playbook"),
        recs=recs,
        points=list(trends),
        hygiene=hyg_rep,
        sources=src_delta,
        window=window,
        busy=busy,
    )
    ops["operate"]["drift"] = kop.drift_flags(
        list(trends),
        {
            "debt": float(debt.get("score") or 0),
            "coverage": float(cover.get("overall_pct") or 0),
            "trust": float(debt.get("trust_pct") or 0),
            "contradictions": float(len(conflicts) + conflict_edges),
            "refusals": float(refusals),
        },
    )
    ops["hygiene"] = hyg_rep.get("counts")
    from app.knowledge_os.principles import public_card

    ops["principle"] = public_card()
    debt["impact"] = ops["impact_debt"]
    return {
        "workspace_id": workspace_id,
        "fitness": fitness,
        "debt": debt,
        "coverage": cover,
        "conflicts": {
            "graph_edges": conflict_edges,
            "detected": conflicts[:12],
            "count": len(conflicts),
        },
        "temporal": {"supersedes_edges": supersedes},
        "source_reliability_avg": trust_avg,
        "feedback": feedback,
        "production": production,
        "learning": {
            "paths_tracked": path_n,
            "drafts_open": len(draft_open),
            "drafts": [
                {
                    "id": d.get("id"),
                    "question": d.get("question"),
                    "fail_kind": d.get("fail_kind"),
                    "origin": d.get("origin"),
                    "status": d.get("status"),
                    "source_url": d.get("source_url"),
                }
                for d in draft_open[:12]
            ],
        },
        "proof": proof,
        "ops": ops,
        "governance": {
            "learning_mode": await _gov_mode(store, workspace_id),
            "slos": await _gov_slos(workspace_id),
            "versions": versions,
            "audit": await _gov_audit(workspace_id),
            "trends": trends,
            "debt_trend": await _gov_debt_trend(workspace_id, float(debt.get("score") or 0)),
            "policies": await _gov_policies(workspace_id),
        },
        "updated_at": _now(),
    }


async def _gov_mode(store: Any, workspace_id: str) -> str:
    from app.knowledge_os.governance import learning_mode

    return await learning_mode(store, workspace_id)


async def _gov_slos(workspace_id: str) -> dict[str, Any]:
    from app.knowledge_os.governance import compute_slos

    return await compute_slos(workspace_id)


async def _gov_versions(workspace_id: str) -> list[dict[str, Any]]:
    from app.knowledge_os.governance import list_versions

    return await list_versions(workspace_id, limit=8)


async def _gov_audit(workspace_id: str) -> list[dict[str, Any]]:
    from app.knowledge_os.governance import list_audit

    return await list_audit(workspace_id, limit=8)


async def _gov_trends(workspace_id: str) -> list[dict[str, Any]]:
    from app.knowledge_os.governance import list_metric_snapshots

    return await list_metric_snapshots(workspace_id, limit=14)


async def _gov_debt_trend(workspace_id: str, current_debt: float) -> dict[str, Any]:
    from app.knowledge_os.diff import debt_trend
    from app.knowledge_os.governance import list_metric_snapshots

    points = await list_metric_snapshots(workspace_id, limit=40)
    points = list(points) + [{"debt": current_debt, "created_at": _now()}]
    return debt_trend(points)


async def _gov_policies(workspace_id: str) -> list[dict[str, Any]]:
    from app.knowledge_os.governance import list_policies

    return await list_policies(workspace_id)


def _fitness(*, cover_pct: float, conflicts: int, feedback: dict[str, Any], docs: int) -> float:
    accept = float(feedback.get("accept_rate") or 0.5)
    conflict_pen = min(25.0, conflicts * 2.5)
    base = 0.45 * cover_pct + 0.35 * (100.0 * accept) + 0.20 * min(100.0, 40 + docs)
    return round(max(0.0, min(100.0, base - conflict_pen)), 1)


async def enrich_graph(store: Any, workspace_id: str) -> dict[str, Any]:
    """Conflict edges + light entity summaries. Workspace-scoped only."""
    graph = await store.get_graph(workspace_id)
    n_conf = await apply_conflict_edges(store, workspace_id, graph)
    n_sum = await _entity_summaries(store, workspace_id, graph)
    await store.commit()
    return {"conflicts_written": n_conf, "summaries": n_sum}


async def _entity_summaries(store: Any, workspace_id: str, graph: dict[str, Any]) -> int:
    """Compress mention neighborhoods into node props.summary (top entities)."""
    nodes = {n["id"]: n for n in graph.get("nodes") or []}
    degree: Counter[str] = Counter()
    first_chunk: dict[str, str] = {}
    for e in graph.get("edges") or []:
        if (e.get("rel_type") or "").upper() != "MENTIONS":
            continue
        dst, src = e.get("dst"), e.get("src")
        if not dst:
            continue
        degree[dst] += 1
        cid = ((nodes.get(src) or {}).get("props") or {}).get("chunk_id")
        if cid and dst not in first_chunk:
            first_chunk[dst] = str(cid)

    chunks = await store.list_chunks(workspace_id)
    by_id = {c["id"]: c.get("text") or "" for c in chunks}
    updated = 0
    for nid, _ in degree.most_common(40):
        text = (by_id.get(first_chunk.get(nid, "")) or "")[:420].strip()
        if not text:
            continue
        await store.patch_node_props(workspace_id, nid, {"summary": text})
        updated += 1
    return updated


async def feedback_stats(workspace_id: str) -> dict[str, Any]:
    conn = await get_connection()
    try:
        cur = await conn.execute(
            """SELECT rating, COUNT(*) AS c FROM answer_feedback
               WHERE workspace_id = ? GROUP BY rating""",
            (workspace_id,),
        )
        counts = {str(r["rating"]): int(r["c"]) for r in await cur.fetchall()}
    except Exception:  # noqa: BLE001
        counts = {}
    finally:
        await conn.close()
    up = int(counts.get("up") or 0)
    down = int(counts.get("down") or 0)
    total = up + down
    return {
        "up": up,
        "down": down,
        "total": total,
        "accept_rate": round(up / total, 3) if total else None,
    }


async def production_learning(workspace_id: str, *, limit: int = 12) -> dict[str, Any]:
    """Mine real Ask traffic: frequent questions and weak (refuse/low-trust) ones."""
    conn = await get_connection()
    try:
        cur = await conn.execute(
            """SELECT content FROM chat_messages
               WHERE workspace_id = ? AND role = 'user'
               ORDER BY created_at DESC LIMIT 400""",
            (workspace_id,),
        )
        questions = [str(r["content"] or "").strip() for r in await cur.fetchall() if r["content"]]
        cur = await conn.execute(
            """SELECT decision, trust_score_json, content FROM chat_messages
               WHERE workspace_id = ? AND role = 'assistant'
               ORDER BY created_at DESC LIMIT 80""",
            (workspace_id,),
        )
        weak: list[dict[str, Any]] = []
        for r in await cur.fetchall():
            decision = (r["decision"] or "").lower()
            try:
                trust = json.loads(r["trust_score_json"] or "{}")
            except Exception:  # noqa: BLE001
                trust = {}
            overall = float(trust.get("overall") or 1)
            if decision in {"refuse", "clarify"} or overall < 0.55:
                weak.append(
                    {
                        "question": (r["content"] or "")[:180],
                        "decision": decision,
                        "trust": round(overall, 2),
                    }
                )
            if len(weak) >= limit:
                break
    finally:
        await conn.close()

    freq = Counter(q.lower()[:120] for q in questions if len(q) > 8)
    frequent = [{"question": q, "count": n} for q, n in freq.most_common(8)]
    return {
        "asks_sampled": len(questions),
        "frequent": frequent,
        "weak": weak[:limit],
    }


async def record_feedback(
    workspace_id: str,
    *,
    message_id: str,
    rating: str,
    note: str = "",
) -> dict[str, Any]:
    rating = "up" if rating == "up" else "down"
    conn = await get_connection()
    try:
        await conn.execute(
            """INSERT INTO answer_feedback (id, workspace_id, message_id, rating, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (str(uuid4()), workspace_id, message_id, rating, (note or "")[:500], _now()),
        )
        await conn.commit()
    finally:
        await conn.close()
    return {"ok": True, "rating": rating}


async def conflicts_for_citations(
    store: Any, workspace_id: str, citations: list[Any]
) -> list[dict[str, Any]]:
    graph = await store.get_graph(workspace_id)
    found = find_value_conflicts(graph)
    if not found:
        return []
    titles = " ".join(
        str(getattr(c, "document", None) or (c.get("document") if isinstance(c, dict) else "") or "")
        for c in citations
    ).lower()
    if not titles.strip():
        return found[:3]
    hit = [c for c in found if (c.get("entity") or "").lower() in titles]
    return (hit or found)[:3]
