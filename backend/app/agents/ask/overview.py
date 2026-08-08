"""Detect document-overview / “what's in this document” questions."""

from __future__ import annotations

import re
from datetime import datetime

_OVERVIEW_RE = re.compile(
    r"("
    r"what['’]?s?\s+there\b|"
    r"what\s+is\s+there\b|"
    r"what('?s|\s+is)\s+in\s+(this|the|my)\b|"
    r"what\s+does\s+(this|the)\s+.+\s+(say|cover|contain|include)\b|"
    r"whose\s+(document|file|pdf|resume|cv)\b|"
    r"who(se|'s)?\s+(is\s+)?this\s+(document|file|pdf|resume|cv)\b|"
    r"who\s+(owns|wrote|uploaded)\s+this\b|"
    r"what\s+is\s+this\s+(document|file|pdf|resume|cv)\b|"
    r"contents?\s+of\s+(this|the)\b|"
    r"summarize\s+(this|the)\b|"
    r"\boverview\s+of\s+(this|the)\b|"
    r"tell\s+me\s+about\s+(this|the)\s+(document|file|pdf|agreement|resume|cv)\b|"
    r"what\s+do\s+we\s+know\s+about\s+(this|the)\s+(document|file|pdf)\b|"
    r"in\s+(this|the)\s+(agreement|document|pdf|contract|license|resume|cv)\b"
    r")",
    re.I,
)

_DOC_HINT_RE = re.compile(
    r"\b(agreement|contract|license|document|pdf|resume|cv|policy|specification)\b",
    re.I,
)

# Fact / comparison questions must NOT become document overviews
_FACTUAL_RE = re.compile(
    r"("
    r"\b(difference|differences|compare|comparison|versus|vs\.?)\b|"
    r"\bwhat\s+are\b|"
    r"\bwhat\s+is\s+(?!this\b)(?!there\b)|"
    r"\bhow\s+(does|do|is|are)\b|"
    r"\b(security\s+level|output\s+protection)\b|"
    r"\b(require|required|must|owns?|supersede)\b"
    r")",
    re.I,
)

_DEICTIC_RE = re.compile(
    r"\b(this|these|the)\s+(document|file|pdf|one|upload|resume|cv)\b|"
    r"\bwhose\s+(document|file|pdf|resume|cv)\b|"
    r"\bwhat\s+is\s+this\b|"
    r"\bwho(se|'s)?\s+is\s+this\b",
    re.I,
)

_STOP = {
    "what",
    "whats",
    "there",
    "this",
    "that",
    "these",
    "the",
    "and",
    "for",
    "from",
    "with",
    "about",
    "tell",
    "know",
    "does",
    "cover",
    "contain",
    "include",
    "summarize",
    "overview",
    "contents",
    "content",
    "whose",
    "who",
    "owns",
    "wrote",
}


def is_document_overview(question: str) -> bool:
    q = (question or "").strip()
    if not q:
        return False
    # Comparisons / definitions / security-level facts → quote search, not overview
    if _FACTUAL_RE.search(q):
        return False
    if _DEICTIC_RE.search(q):
        return True
    if _OVERVIEW_RE.search(q):
        return True
    # Only treat bare doc mentions as overview when they look like “what's in X”
    if re.search(
        r"^(what|whats|what's)\b.+\b(agreement|contract|license|resume|cv)\b",
        q,
        re.I,
    ):
        return True
    return False


def is_deictic_document_question(question: str) -> bool:
    """“this document / whose document” — prefer newest upload when ambiguous."""
    return bool(_DEICTIC_RE.search(question or ""))


def mentions_document(question: str) -> bool:
    return bool(_DOC_HINT_RE.search(question or ""))


def question_keywords(question: str) -> list[str]:
    words = re.findall(r"[a-z0-9]{4,}", (question or "").lower())
    return [w for w in words if w not in _STOP]


def clean_excerpt(text: str, max_len: int = 420) -> str:
    """Prefer a sentence-ish start; avoid mid-word scraps."""
    t = re.sub(r"\s+", " ", (text or "")).strip()
    if not t:
        return ""
    m = re.search(r"[A-Z][A-Za-z].{40,}", t)
    if m:
        t = t[m.start() :].strip()
    if len(t) > max_len:
        cut = t[:max_len]
        sp = cut.rfind(" ")
        if sp > max_len // 2:
            cut = cut[:sp]
        t = cut.rstrip(" ,;:") + "…"
    return t


def chunk_info_score(text: str, question: str = "") -> float:
    t = (text or "").lower()
    q = (question or "").lower()
    score = 0.0

    # Resume / CV signals
    resume_q = any(x in q for x in ("resume", "cv", "whose", "experience", "candidate"))
    for kw, w in (
        ("experience", 2.0),
        ("education", 2.0),
        ("skills", 1.5),
        ("resume", 2.0),
        ("curriculum vitae", 2.0),
        ("work history", 1.5),
        ("linkedin", 1.0),
        ("email", 0.5),
        ("phone", 0.5),
    ):
        if kw in t:
            score += w * (1.4 if resume_q else 1.0)

    # Agreement / license signals — only strong when question asks about them
    agreement_q = any(x in q for x in ("agreement", "license", "contract", "policy"))
    for kw, w in (
        ("license", 2.0),
        ("agreement", 2.0),
        ("contract", 1.8),
        ("under this", 1.5),
        ("intellectual property", 1.5),
        ("product", 1.0),
        ("rights", 1.0),
        ("specification", 0.8),
    ):
        if kw in t:
            score += w * (1.3 if agreement_q else 0.35)

    for junk in ("©", "all rights reserved", "contact us", "terms of use", "html5"):
        if junk in t:
            score -= 1.5
    return score


def _parse_created(doc: dict) -> float:
    raw = doc.get("created_at") or ""
    if not raw:
        return 0.0
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
    except Exception:  # noqa: BLE001
        return 0.0


def score_documents(docs: list[dict], question: str) -> list[tuple[float, dict]]:
    """Rank workspace documents for an overview / deictic question."""
    q = (question or "").lower()
    keywords = question_keywords(question)
    deictic = is_deictic_document_question(question)
    wants_resume = any(x in q for x in ("resume", "cv", "candidate", "experience"))
    wants_agreement = any(x in q for x in ("agreement", "contract", "license", "policy"))

    scored: list[tuple[float, dict]] = []
    newest_ts = max((_parse_created(d) for d in docs), default=0.0)

    for d in docs:
        title = (d.get("title") or "").lower()
        score = 0.0

        for k in keywords:
            if k in title:
                score += 3.0

        if wants_resume and any(x in title for x in ("resume", "cv", "curriculum")):
            score += 5.0
        if wants_agreement and any(
            x in title for x in ("agreement", "contract", "license", "policy", "specification")
        ):
            score += 5.0

        # Do NOT boost agreement docs for unrelated questions (the old bug)
        if not wants_agreement:
            for hint in ("agreement", "contract", "license", "policy"):
                if hint in title:
                    score -= 0.5

        created = _parse_created(d)
        if deictic and newest_ts and created >= newest_ts - 1:
            score += 6.0  # “this document” → latest upload
        elif deictic:
            # slight recency preference among older docs
            score += min(2.0, max(0.0, (created / newest_ts) if newest_ts else 0.0))

        # Mild recency for all overview questions
        if newest_ts and created:
            score += 0.5 * (created / newest_ts)

        scored.append((score, d))

    scored.sort(key=lambda x: (-x[0], -_parse_created(x[1])))
    return scored
