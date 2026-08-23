"""Knowledge coverage by corpus section (website path or document family)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.knowledge.sources.web.site_graph import looks_like_web_title, page_path


def section_for_title(title: str) -> str:
    if looks_like_web_title(title):
        parts = [p for p in page_path(title).strip("/").split("/") if p]
        if not parts:
            return "site-home"
        if parts[0] in {"news", "press", "blog", "insights", "articles"}:
            return "chronicle"
        if parts[0] in {"about", "about-us", "company", "who-we-are"}:
            return "identity"
        if parts[0] in {"services", "solutions", "what-we-do", "offerings", "products"}:
            return "offerings"
        if "leader" in parts[0] or "team" in parts[0]:
            return "people"
        return parts[0][:40]
    low = (title or "").lower()
    if low.endswith(".pdf") or "policy" in low or "sop" in low:
        return "controlled-docs"
    return "documents"


def coverage_report(
    docs: list[dict[str, Any]],
    graph: dict[str, Any],
) -> dict[str, Any]:
    """Estimate what the graph knows vs what was ingested, by section."""
    defined: dict[str, set[str]] = defaultdict(set)
    for e in graph.get("edges") or []:
        if e.get("rel_type") != "DEFINED_IN":
            continue
        doc_id = e.get("document_id")
        if doc_id:
            defined[str(doc_id)].add(e.get("src") or "")

    buckets: dict[str, dict[str, Any]] = {}
    for d in docs:
        sec = section_for_title(d.get("title") or "")
        b = buckets.setdefault(
            sec, {"section": sec, "pages": 0, "linked_pages": 0, "entities": 0}
        )
        b["pages"] += 1
        ents = defined.get(d["id"]) or set()
        if ents:
            b["linked_pages"] += 1
            b["entities"] += len(ents)

    domains = []
    for sec, b in sorted(buckets.items(), key=lambda x: -x[1]["pages"]):
        pages = max(int(b["pages"]), 1)
        pct = round(100.0 * int(b["linked_pages"]) / pages, 1)
        b["coverage_pct"] = pct
        domains.append(b)

    overall_pages = sum(int(b["pages"]) for b in domains) or 1
    overall = round(
        sum(float(b["coverage_pct"]) * int(b["pages"]) for b in domains) / overall_pages,
        1,
    )
    return {
        "overall_pct": overall,
        "domains": domains[:16],
        "gap_sections": [b["section"] for b in domains if float(b["coverage_pct"]) < 60][:8],
    }
