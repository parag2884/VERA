"""Passage-level trust signals computed once at ingest (any corpus).

Stored on chunk.loc['signals'] so retrieve/judge do not re-derive chrome/prose
heuristics from scratch. Web and PDF/upload chunks share the same scorer.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from app.knowledge.signals.text_terms import boilerplate_penalty, person_title_names

DocKind = Literal["press", "policy", "spotlight", "nav", "letter", "unknown"]

_DATE = re.compile(r"\b(20\d{2}|19\d{2})\b")
_SPOTLIGHT = re.compile(
    r"\b(spotlight|employee of the|team of the|"
    r"celebrat(?:e|ing)|culture\s+story|meet (?:the|our) team)\b",
    re.I,
)
_PRESS = re.compile(
    r"\b(press[-_ ]?release|newsroom|named|appoint(?:ed|s)?|"
    r"investor|earnings|media\s+release|announces)\b",
    re.I,
)
_POLICY = re.compile(
    r"\b(policy|compliance|privacy|terms|license|agreement|"
    r"specification|standard|guideline)\b",
    re.I,
)
_LETTER = re.compile(
    r"\b(letter\s+from|annual\s+letter|shareholder\s+letter|"
    r"president\s+and\s+ceo)\b",
    re.I,
)
_NAVISH = re.compile(
    r"\b(site\s*map|cookie|close menu|sign in|log in|"
    r"skip to (?:content|main)|all rights reserved)\b",
    re.I,
)


def infer_doc_kind(title: str, text: str) -> DocKind:
    blob = f"{title or ''}\n{(text or '')[:800]}"
    if _SPOTLIGHT.search(blob):
        return "spotlight"
    if _LETTER.search(blob):
        return "letter"
    if _PRESS.search(blob):
        return "press"
    if _POLICY.search(blob):
        return "policy"
    if _NAVISH.search(blob) and len((text or "").strip()) < 400:
        return "nav"
    return "unknown"


def compute_passage_signals(title: str, text: str) -> dict[str, Any]:
    """Return serializable signals for chunk.loc['signals']."""
    t = text or ""
    title = title or ""
    blob = f"{title}\n{t}"
    pen = boilerplate_penalty(blob)
    chrome_score = min(1.0, pen / 1.5)
    # Prose: longer unique-ish text with lower chrome
    words = re.findall(r"[A-Za-z]{3,}", t)
    length_factor = min(1.0, len(t) / 600.0)
    prose_score = max(0.0, min(1.0, (0.55 * length_factor + 0.45 * (1.0 - chrome_score))))
    if len(words) < 12:
        prose_score = min(prose_score, 0.25)

    people = person_title_names(blob)
    has_person_role = bool(people) or bool(
        re.search(
            r"\b(CEO|COO|CFO|CTO|President|Chairman|Chief\s+[A-Z][a-z]+)\b",
            t,
        )
    )
    has_dated_claim = bool(_DATE.search(blob))
    doc_kind = infer_doc_kind(title, t)

    # Quarantine: near-pure chrome / tiny nav shells
    quarantine = False
    if chrome_score >= 0.75 and prose_score < 0.28:
        quarantine = True
    if doc_kind == "nav" and len(t.strip()) < 280:
        quarantine = True
    if len(t.strip()) < 40:
        quarantine = True

    return {
        "prose_score": round(prose_score, 3),
        "chrome_score": round(chrome_score, 3),
        "has_person_role": has_person_role,
        "has_dated_claim": has_dated_claim,
        "doc_kind": doc_kind,
        "quarantine": quarantine,
        "person_role_count": len(people),
    }


def signals_from_chunk(chunk: dict[str, Any] | None, title: str = "", text: str = "") -> dict[str, Any]:
    """Read signals from chunk.loc or compute on the fly for legacy chunks."""
    loc = (chunk or {}).get("loc") or {}
    sig = loc.get("signals")
    if isinstance(sig, dict) and "prose_score" in sig:
        return sig
    body = text or (chunk or {}).get("text") or ""
    ttl = title or loc.get("filename") or ""
    return compute_passage_signals(ttl, body)


def summarize_passage_readiness(chunks: list[dict[str, Any]], docs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Aggregate ingest readiness stats for health / job result."""
    docs = docs or []
    titles = {d.get("id"): (d.get("title") or "") for d in docs}
    total = 0
    quarantined = 0
    chrome_heavy = 0
    with_people = 0
    kinds: dict[str, int] = {}
    for ch in chunks:
        text = ch.get("text") or ""
        if len(text.strip()) < 20:
            continue
        total += 1
        title = titles.get(ch.get("canonical_document_id"), "") or (ch.get("loc") or {}).get(
            "filename", ""
        )
        sig = signals_from_chunk(ch, title=title, text=text)
        if sig.get("quarantine"):
            quarantined += 1
        if float(sig.get("chrome_score") or 0) >= 0.55:
            chrome_heavy += 1
        if sig.get("has_person_role"):
            with_people += 1
        k = str(sig.get("doc_kind") or "unknown")
        kinds[k] = kinds.get(k, 0) + 1

    chrome_pct = round(100.0 * chrome_heavy / max(total, 1), 1)
    return {
        "chunks_scored": total,
        "quarantined": quarantined,
        "chrome_heavy_pct": chrome_pct,
        "chunks_with_person_role": with_people,
        "doc_kinds": kinds,
        "has_officer_evidence": with_people > 0,
        "has_press_or_letter": (kinds.get("press", 0) + kinds.get("letter", 0)) > 0,
    }
