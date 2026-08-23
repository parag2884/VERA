"""Detect-only graph hygiene. Never deletes nodes or rewrites hierarchy."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

WEAK_WEIGHT = 0.55


def scan(
    graph: dict[str, Any],
    *,
    path_stats: dict[str, tuple[int, int]] | None = None,
    docs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    nodes = {str(n.get("id")): n for n in graph.get("nodes") or [] if n.get("id")}
    edges = [e for e in graph.get("edges") or [] if (e.get("status") or "active") == "active"]
    deg: Counter[str] = Counter()
    broken: list[dict[str, str]] = []
    for e in edges:
        src, dst = str(e.get("src") or ""), str(e.get("dst") or "")
        if src:
            deg[src] += 1
        if dst:
            deg[dst] += 1
        if src and src not in nodes:
            broken.append({"edge": str(e.get("id") or ""), "missing": src})
        if dst and dst not in nodes:
            broken.append({"edge": str(e.get("id") or ""), "missing": dst})

    unused = [
        {"id": nid, "name": str(n.get("name") or nid)[:80], "type": str(n.get("type") or "")}
        for nid, n in nodes.items()
        if deg[nid] == 0
    ]
    topics = [
        n
        for n in nodes.values()
        if str(n.get("type") or "").lower() in {"topic", "concept", "section"}
    ]
    orphans = [
        {"id": str(n.get("id")), "name": str(n.get("name") or "")[:80]}
        for n in topics
        if deg[str(n.get("id") or "")] <= 1
    ]

    by_norm: dict[str, list[str]] = defaultdict(list)
    for n in nodes.values():
        key = str(n.get("normalized_name") or n.get("name") or "").strip().lower()
        if len(key) < 3:
            continue
        by_norm[key].append(str(n.get("id")))
    duplicates = [
        {"name": k, "ids": v[:8], "count": len(v)}
        for k, v in by_norm.items()
        if len(v) > 1
    ][:20]

    weak = []
    for e in edges:
        if (e.get("edge_class") or "") != "asserted_fact":
            continue
        if float(e.get("weight") or 1) >= WEAK_WEIGHT:
            continue
        weak.append(
            {
                "id": e.get("id"),
                "from": str((nodes.get(str(e.get("src"))) or {}).get("name") or e.get("src")),
                "to": str((nodes.get(str(e.get("dst"))) or {}).get("name") or e.get("dst")),
                "weight": e.get("weight"),
            }
        )

    stale_paths = []
    for key, (wins, losses) in (path_stats or {}).items():
        w, l = int(wins or 0), int(losses or 0)
        if l >= 3 and l > w:
            stale_paths.append({"path": str(key)[:80], "wins": w, "losses": l})
    stale_paths.sort(key=lambda x: -int(x["losses"]))

    urls = [
        str(d.get("title") or "")
        for d in (docs or [])
        if str(d.get("title") or "").startswith("http")
    ]

    return {
        "orphan_topics": orphans[:20],
        "broken_links": broken[:20],
        "duplicate_entities": duplicates,
        "unused_nodes": unused[:20],
        "weak_edges": weak[:20],
        "stale_paths": stale_paths[:20],
        "source_urls": urls[:200],
        "counts": {
            "orphan_topics": len(orphans),
            "broken_links": len(broken),
            "duplicate_entities": len(duplicates),
            "unused_nodes": len(unused),
            "weak_edges": len(weak),
            "stale_paths": len(stale_paths),
            "source_urls": len(urls),
        },
    }
