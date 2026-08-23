"""Detect contradictory numeric facts for the same entity (BFSI / ops)."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

_NUM = re.compile(
    r"(?<![A-Za-z])(?:USD|US\$|\$|€|£)?\s*(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?",
    re.I,
)


def parse_amount(text: str) -> float | None:
    m = _NUM.search(text or "")
    if not m:
        return None
    raw = m.group(1).replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


def find_value_conflicts(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """Same source entity, HAS_VALUE / DEFINED_AS targets that disagree numerically."""
    nodes = {n["id"]: n for n in graph.get("nodes") or []}
    by_src: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for e in graph.get("edges") or []:
        rel = (e.get("rel_type") or "").upper()
        if rel not in {"HAS_VALUE", "DEFINED_AS", "PROVIDES"}:
            continue
        if e.get("status") and e["status"] != "active":
            continue
        src, dst = e.get("src"), e.get("dst")
        if not src or not dst:
            continue
        dst_name = (nodes.get(dst) or {}).get("name") or ""
        amt = parse_amount(dst_name)
        if amt is None:
            continue
        by_src[src].append((dst, dst_name, e.get("id") or ""))

    found: list[dict[str, Any]] = []
    for src, vals in by_src.items():
        amounts = {parse_amount(name) for _, name, _ in vals}
        amounts.discard(None)
        if len(amounts) < 2:
            continue
        src_name = (nodes.get(src) or {}).get("name") or src
        quotes = [name for _, name, _ in vals[:4]]
        found.append(
            {
                "entity": src_name,
                "entity_id": src,
                "values": quotes,
                "amounts": sorted(float(a) for a in amounts if a is not None),
            }
        )
    return found[:40]


async def apply_conflict_edges(store: Any, workspace_id: str, graph: dict[str, Any]) -> int:
    """Write CONFLICTS_WITH between disagreeing value nodes (idempotent)."""
    created = 0
    nodes = {n["id"]: n for n in graph.get("nodes") or []}
    by_src: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for e in graph.get("edges") or []:
        if (e.get("rel_type") or "").upper() not in {"HAS_VALUE", "DEFINED_AS"}:
            continue
        dst = e.get("dst")
        src = e.get("src")
        if not src or not dst:
            continue
        name = (nodes.get(dst) or {}).get("name") or ""
        if parse_amount(name) is None:
            continue
        by_src[src].append((dst, name))

    for src, vals in by_src.items():
        unique: dict[float, str] = {}
        for dst, name in vals:
            amt = parse_amount(name)
            if amt is None:
                continue
            if amt not in unique:
                unique[amt] = dst
        ids = list(unique.values())
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                eid = await store.insert_edge(
                    workspace_id,
                    src=ids[i],
                    dst=ids[j],
                    rel_type="CONFLICTS_WITH",
                    edge_class="asserted_fact",
                    weight=0.7,
                    props={"extractor": "knowledge_os_conflict"},
                )
                if eid:
                    created += 1
    return created
