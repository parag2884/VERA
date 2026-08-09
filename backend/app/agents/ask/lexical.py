"""Lexical chunk search for distinctive question terms (codes, phrases, …)."""

from __future__ import annotations

import re

from app.agents.ask.contracts import QuoteHit

_STOP = {
    "what",
    "whats",
    "which",
    "where",
    "when",
    "who",
    "whom",
    "whose",
    "why",
    "how",
    "can",
    "could",
    "would",
    "should",
    "does",
    "did",
    "are",
    "is",
    "the",
    "and",
    "for",
    "from",
    "with",
    "about",
    "tell",
    "me",
    "you",
    "your",
    "please",
    "difference",
    "differences",
    "between",
    "compare",
    "comparison",
    "versus",
    "them",
    "their",
    "this",
    "that",
    "these",
    "those",
    "have",
    "has",
    "any",
    "there",
    "into",
    "over",
    "under",
    "than",
    "then",
    "also",
    "just",
    "like",
    "know",
    "give",
    "show",
    "explain",
    "describe",
    "list",
    "define",
    "definition",
    "levels",
    "level",
    "document",
    "documents",
    "file",
    "files",
    "pdf",
    "name",
    "some",
    "roughly",
    "about",
    "does",
    "offer",
    "offers",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "several",
    "various",
    "main",
    "key",
    # Soft org words that match site nav on every page
    "team",
    "teams",
    "leadership",
    "leader",
    "leaders",
    "executive",
    "executives",
    "management",
}


def distinctive_terms(question: str) -> list[str]:
    """Terms worth searching literally in chunk text."""
    q = question or ""
    terms: list[str] = []

    # Product / level codes: SL2000, HDCP2, OPL270, …
    for m in re.finditer(r"\b([A-Z]{2,}\d{2,}|\d{3,}[A-Z]+|[A-Z]{3,}\d+)\b", q):
        terms.append(m.group(1))

    # Quoted phrases
    for m in re.finditer(r"[\"']([^\"']{3,80})[\"']", q):
        terms.append(m.group(1).strip())

    # Title-Case multi-word spans from the question (any domain)
    for m in re.finditer(r"\b([A-Z][a-z0-9]+(?:\s+[A-Z][a-z0-9]+){1,4})\b", q):
        terms.append(m.group(1).strip())

    # Adjacent content-word phrases (2–3 tokens) harvested from the question
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", q)
    for i in range(len(words) - 1):
        w0, w1 = words[i], words[i + 1]
        if w0.lower() in _STOP or w1.lower() in _STOP:
            continue
        terms.append(f"{w0} {w1}")
        if i + 2 < len(words):
            w2 = words[i + 2]
            if w2.lower() not in _STOP:
                terms.append(f"{w0} {w1} {w2}")

    # Remaining tokens (alnum, length >= 4), drop stopwords
    for w in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", q):
        if w.lower() in _STOP:
            continue
        terms.append(w)

    # Short uppercase tokens from the question itself (CEO, API, SLA, …)
    for w in re.findall(r"\b[A-Z]{2,4}\b", q):
        if w.lower() in _STOP:
            continue
        terms.append(w)

    # Prefer distinctive: codes and multi-word first; dedupe
    out: list[str] = []
    seen: set[str] = set()
    for t in terms:
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out[:12]


async def lexical_term_quotes(
    store,
    workspace_id: str,
    question: str,
    *,
    extra_terms: list[str] | None = None,
) -> list[QuoteHit]:
    terms = distinctive_terms(question)
    for t in extra_terms or []:
        if t and t.lower() not in {x.lower() for x in terms}:
            terms.append(t)
    if not terms:
        return []
    chunks = await store.list_chunks(workspace_id)
    docs = {d["id"]: d["title"] for d in await store.list_canonical_documents(workspace_id)}

    # Score chunks by how many distinctive terms they contain
    scored: list[tuple[float, dict, str]] = []
    for ch in chunks:
        text = ch.get("text") or ""
        if not text.strip():
            continue
        low = text.lower()
        title = (docs.get(ch.get("canonical_document_id"), "") or "").lower()
        hit_count = 0
        weight = 0.0
        first_pos = len(text)
        for t in terms:
            tl = t.lower()
            in_body = tl in low
            in_title = tl in title
            if not in_body and not in_title:
                continue
            hit_count += 1
            # Codes / multi-word phrases weigh more
            w = 3.0 if (re.search(r"\d", t) or " " in t) else 1.0
            if in_title:
                w += 1.5
            weight += w
            if in_body:
                pos = low.find(tl)
                if 0 <= pos < first_pos:
                    first_pos = pos
        if hit_count == 0:
            continue
        # Require at least one strong term when question has codes
        strong = [t for t in terms if re.search(r"\d", t) or " " in t]
        if strong and not any(t.lower() in low or t.lower() in title for t in strong):
            continue
        scored.append((weight + 0.15 * hit_count, ch, text))

    scored.sort(key=lambda x: x[0], reverse=True)
    hits: list[QuoteHit] = []
    for weight, ch, text in scored[:6]:
        # Window around best term
        low = text.lower()
        anchor = 0
        for t in terms:
            pos = low.find(t.lower())
            if pos >= 0:
                anchor = pos
                break
        start = max(0, anchor - 80)
        end = min(len(text), anchor + 320)
        quote = text[start:end].strip()
        quote = re.sub(r"\s+", " ", quote)
        if len(quote) < 40:
            continue
        hits.append(
            QuoteHit(
                chunk_id=ch["id"],
                document_title=docs.get(ch.get("canonical_document_id"), "document"),
                locator=(ch.get("loc") or {}).get("locator"),
                quote=quote[:400],
                score=min(0.98, 0.72 + 0.06 * weight),
            )
        )
    return hits
