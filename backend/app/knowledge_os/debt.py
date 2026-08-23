"""Knowledge debt — what the graph still owes operations (not another product)."""

from __future__ import annotations

from typing import Any

from app.knowledge.sources.web.site_graph import trust_weight

WEAK_WEIGHT = 0.55
UNTRUSTED = 0.55


def knowledge_debt(
    *,
    coverage_pct: float,
    source_reliability: float,
    conflict_count: int,
    weak_edge_count: int,
    asserted_edges: int,
    unanswered: int,
    gap_sections: int,
) -> dict[str, Any]:
    """0–100 debt (lower is healthier). Drivers are inspectable for leadership."""
    cover_gap = max(0.0, 100.0 - float(coverage_pct or 0))
    trust_gap = max(0.0, 100.0 - 100.0 * max(0.0, min(1.0, float(source_reliability or 0))))
    conflict_load = min(30.0, float(conflict_count) * 4.0)
    weak_ratio = (
        100.0 * weak_edge_count / max(asserted_edges, 1) if asserted_edges else 0.0
    )
    unanswered_load = min(25.0, float(unanswered) * 2.5)
    topic_gap = min(20.0, float(gap_sections) * 4.0)

    raw = [
        {
            "id": "topics",
            "label": "Missing topics",
            "points": round(0.08 * topic_gap, 1),
            "action": "Add or link pages in under-covered sections.",
        },
        {
            "id": "weak_edges",
            "label": "Weak edges",
            "points": round(0.16 * min(40.0, weak_ratio), 1),
            "action": "Re-evidence or lock paths that lose in Ask.",
        },
        {
            "id": "conflicts",
            "label": "Contradictions",
            "points": round(0.18 * conflict_load, 1),
            "action": "Pick a source of truth and supersede the rest.",
        },
        {
            "id": "unanswered",
            "label": "Draft questions",
            "points": round(0.12 * unanswered_load, 1),
            "action": "Accept drafts that have a verified source.",
        },
        {
            "id": "trust",
            "label": "Untrusted sources",
            "points": round(0.18 * trust_gap, 1),
            "action": "Review chronicle pages or assign an owner.",
        },
        {
            "id": "coverage",
            "label": "Coverage gaps",
            "points": round(0.28 * cover_gap, 1),
            "action": "Connect remaining pages in low-coverage domains.",
        },
    ]
    score = round(sum(float(d["points"]) for d in raw), 1)
    score = max(0.0, min(100.0, score))
    for d in raw:
        d["pct"] = round(float(d["points"]), 1)
    drivers = [
        x for x in sorted(raw, key=lambda x: -float(x["points"])) if float(x["points"]) > 0
    ][:6]
    if score < 12:
        status = "healthy"
    elif score < 28:
        status = "watch"
    else:
        status = "elevated"
    return {
        "score": score,
        "status": status,
        "coverage_pct": round(float(coverage_pct or 0), 1),
        "trust_pct": round(100.0 * max(0.0, min(1.0, float(source_reliability or 0))), 1),
        "weak_edges": weak_edge_count,
        "unanswered": unanswered,
        "drivers": drivers,
        "risk": knowledge_risk(score, drivers),
    }


def _node_name(nodes: dict[str, dict[str, Any]], nid: str) -> str:
    n = nodes.get(nid) or {}
    return str(n.get("name") or n.get("normalized_name") or nid)[:80]


def _success_for_edge(
    edge_id: str, path_stats: dict[str, tuple[int, int]]
) -> dict[str, Any]:
    wins = losses = 0
    for key, (w, l) in path_stats.items():
        parts = str(key).split("|")
        if edge_id in parts:
            wins += int(w or 0)
            losses += int(l or 0)
    n = wins + losses
    return {
        "wins": wins,
        "losses": losses,
        "asks": n,
        "success_rate": round(100.0 * wins / n, 0) if n else None,
    }


def debt_drilldown(
    *,
    graph: dict[str, Any],
    path_stats: dict[str, tuple[int, int]] | None,
    docs: list[dict[str, Any]],
    cover: dict[str, Any],
    conflicts: list[dict[str, Any]],
    drafts: list[dict[str, Any]],
    production_weak: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Actionable lists behind each debt driver (operator control plane)."""
    nodes = {str(n.get("id")): n for n in (graph.get("nodes") or [])}
    stats = path_stats or {}
    weak: list[dict[str, Any]] = []
    for e in graph.get("edges") or []:
        if (e.get("status") or "active") != "active":
            continue
        if (e.get("edge_class") or "") != "asserted_fact":
            continue
        w = float(e.get("weight") or 1)
        if w >= WEAK_WEIGHT:
            continue
        src = _node_name(nodes, str(e.get("src") or ""))
        dst = _node_name(nodes, str(e.get("dst") or ""))
        suc = _success_for_edge(str(e.get("id") or ""), stats)
        weak.append(
            {
                "id": e.get("id"),
                "from": src,
                "to": dst,
                "rel": e.get("rel_type") or "",
                "weight": round(w, 3),
                **suc,
            }
        )
    weak.sort(key=lambda x: (x.get("success_rate") is None, x.get("success_rate") or 0, x["weight"]))

    topics = []
    for d in cover.get("domains") or []:
        pct = float(d.get("coverage_pct") or 0)
        if pct >= 60:
            continue
        pages = int(d.get("pages") or 0)
        linked = int(d.get("linked_pages") or 0)
        unlinked = max(0, pages - linked)
        # If this section reached 100% coverage, overall would rise by this share of pages.
        overall_pages = sum(int(x.get("pages") or 0) for x in (cover.get("domains") or [])) or 1
        gain = round((100.0 - pct) * pages / overall_pages, 1)
        topics.append(
            {
                "section": d.get("section"),
                "coverage_pct": pct,
                "unlinked_pages": unlinked,
                "expected_coverage_gain": gain,
            }
        )
    topics.sort(key=lambda x: -float(x["expected_coverage_gain"]))

    untrusted = []
    for doc in docs:
        title = str(doc.get("title") or "")
        tw = trust_weight(title)
        if tw >= UNTRUSTED:
            continue
        untrusted.append(
            {
                "title": title[:160],
                "trust_pct": round(100.0 * tw, 0),
                "reason": "Chronicle or low-trust path",
            }
        )
    untrusted.sort(key=lambda x: x["trust_pct"])

    contra = []
    for c in conflicts[:12]:
        contra.append(
            {
                "entity": c.get("entity") or c.get("name") or "value",
                "detail": ", ".join(str(v) for v in (c.get("values") or c.get("amounts") or [])[:4]),
            }
        )
    for e in graph.get("edges") or []:
        if (e.get("rel_type") or "").upper() != "CONFLICTS_WITH":
            continue
        contra.append(
            {
                "entity": _node_name(nodes, str(e.get("src") or "")),
                "detail": f"conflicts with {_node_name(nodes, str(e.get('dst') or ''))}",
            }
        )

    questions = []
    for d in drafts[:12]:
        questions.append(
            {
                "id": d.get("id"),
                "question": d.get("question"),
                "fail_kind": d.get("fail_kind") or "draft",
            }
        )
    for wq in production_weak[:8]:
        questions.append(
            {
                "id": None,
                "question": wq.get("question"),
                "fail_kind": wq.get("decision") or "weak",
            }
        )

    return {
        "weak_edges": weak[:20],
        "topics": topics[:12],
        "trust": untrusted[:12],
        "conflicts": contra[:12],
        "unanswered": questions[:16],
        "coverage": topics[:12],
    }


def knowledge_risk(score: float, drivers: list[dict[str, Any]]) -> dict[str, Any]:
    """Executive band: Low / Medium / High from the same debt drivers."""
    ids = {str(d.get("id")) for d in drivers}
    hot = {"conflicts", "weak_edges", "trust", "topics"}
    if score >= 28 or (score >= 18 and ids & hot):
        level = "High"
    elif score >= 12:
        level = "Medium"
    else:
        level = "Low"
    causes = [str(d.get("label")) for d in drivers[:3]]
    return {
        "level": level,
        "score": score,
        "causes": causes,
    }


def improvement_loop(
    debt: dict[str, Any],
    drilldown: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Signature loop: debt → causes → actions → expected debt after fix."""
    dd = drilldown or debt.get("drilldown") or {}
    drivers = list(debt.get("drivers") or [])[:3]
    current = float(debt.get("score") or 0)
    remaining = current
    actions: list[dict[str, Any]] = []
    for i, d in enumerate(drivers, start=1):
        pts = float(d.get("points") or 0)
        remaining = round(max(0.0, remaining - pts), 1)
        actions.append(
            {
                "step": i,
                "driver": d.get("id"),
                "cause": d.get("label"),
                "do": _concrete_action(str(d.get("id") or ""), dd) or d.get("action"),
                "clears_points": pts,
                "expected_debt_after_this": remaining,
            }
        )
    return {
        "current_debt": current,
        "expected_debt_after_fix": remaining if actions else current,
        "actions": actions,
    }


def _concrete_action(driver: str, dd: dict[str, Any]) -> str:
    if driver == "weak_edges":
        e = (dd.get("weak_edges") or [None])[0]
        if e:
            return f"Review {e.get('from')} → {e.get('to')}"
    if driver in {"topics", "coverage"}:
        t = (dd.get("topics") or [None])[0]
        if t:
            gain = t.get("expected_coverage_gain")
            extra = f" (expected coverage +{gain}%)" if gain else ""
            return f"Link pages in {t.get('section')}{extra}"
    if driver == "conflicts":
        c = (dd.get("conflicts") or [None])[0]
        if c:
            return f"Resolve contradiction on {c.get('entity')}"
    if driver == "trust":
        s = (dd.get("trust") or [None])[0]
        if s:
            return f"Review source {(s.get('title') or '')[:80]}"
    if driver == "unanswered":
        q = (dd.get("unanswered") or [None])[0]
        if q and q.get("question"):
            return f"Accept or reject draft: {(q.get('question') or '')[:90]}"
    return ""
