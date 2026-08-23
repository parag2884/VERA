"""Self-learning: credit/blame edges and paths; draft goldens; missing-knowledge hints."""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4
from datetime import datetime, timezone

from app.identity import normalize_entity_name
from app.knowledge.sources.web.site_graph import looks_like_web_title, slug_tokens


def path_key(edge_ids: list[str]) -> str:
    return "|".join(edge_ids[:12])


def as_of_iso(*texts: str) -> str | None:
    years: list[int] = []
    for t in texts:
        years.extend(int(y) for y in re.findall(r"\b(20\d{2})\b", t or ""))
    if not years:
        return None
    return f"{max(years)}-01-01"


def heading_topic(text: str) -> str:
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith("#"):
            title = re.sub(r"^#+\s*", "", s).strip()
            title = re.sub(r"^Source:.*$", "", title, flags=re.I).strip()
            if 3 <= len(title) <= 80 and not title.lower().startswith("http"):
                return title
    return ""


async def credit_outcome(
    store: Any,
    workspace_id: str,
    *,
    edge_ids: list[str],
    won: bool,
) -> None:
    """Move edge weights and path win-rate. Never creates edges (evidence invariant)."""
    ids = [e for e in edge_ids if e]
    if not ids:
        return
    from app.knowledge_os.governance import apply_learning

    await apply_learning(store, workspace_id, edge_ids=ids, won=won)


def missing_hints(
    question: str,
    docs: list[dict[str, Any]],
    *,
    cited_titles: list[str] | None = None,
) -> list[dict[str, str]]:
    """Suggest crawl URLs / entities when Ask refuses."""
    q = (question or "").lower()
    tokens = set(re.findall(r"[a-z0-9]{4,}", q))
    cited = " ".join(cited_titles or []).lower()
    out: list[dict[str, str]] = []
    for d in docs:
        title = d.get("title") or ""
        blob = title.lower().replace("_", " ").replace("-", " ")
        if cited and any(t in cited for t in blob.split()[:4]):
            continue
        hits = sum(1 for t in tokens if t in blob)
        if hits < 1:
            continue
        kind = "crawl_url" if looks_like_web_title(title) else "add_document"
        out.append(
            {
                "kind": kind,
                "title": title[:160],
                "detail": "Question terms overlap this page/file that was not used as evidence.",
            }
        )
        if len(out) >= 4:
            break
    if not out and tokens:
        term = max(tokens, key=len)
        out.append(
            {
                "kind": "add_entity",
                "title": term,
                "detail": "No linked page for this term — crawl a source that defines it, then re-Ask.",
            }
        )
    return out


async def propose_draft(
    store: Any,
    workspace_id: str,
    *,
    question: str,
    answer_preview: str = "",
    source_url: str | None = None,
    retrieval_ok: bool | None = None,
    fail_kind: str = "",
    origin: str = "ask",
) -> None:
    q = (question or "").strip()
    if len(q) < 12:
        return
    await store.upsert_draft_golden(
        workspace_id,
        question=q,
        answer_preview=(answer_preview or "")[:400],
        source_url=source_url,
        retrieval_ok=retrieval_ok,
        fail_kind=fail_kind,
        origin=origin,
    )
    await store.commit()


def draft_to_case(row: dict[str, Any]) -> dict[str, Any]:
    must = [p.strip() for p in (row.get("must_any") or "").split("|") if p.strip()]
    return {
        "id": f"DRAFT-{(row.get('id') or '')[:8]}",
        "question": row.get("question") or "",
        "expect_decision": "answer" if must else "either",
        "must_any": must,
        "source_url": row.get("source_url"),
        "expected_answer": row.get("answer_preview") or "",
        "notes": "human-accepted workspace golden",
    }


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid4())


def norm_q(question: str) -> str:
    return normalize_entity_name(question)[:200]
