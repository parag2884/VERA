"""Candidate / person-name question helpers for resume lookups."""

from __future__ import annotations

import re

_CANDIDATE_Q = re.compile(
    r"("
    r"\bcandidate\b|"
    r"\bresume\b|"
    r"\bcv\b|"
    r"\bnamed\b|"
    r"\bname[sd]?\b|"
    r"is\s+there\s+(any|a)\b|"
    r"do\s+we\s+have\b|"
    r"anyone\s+named\b|"
    r"person\s+named\b"
    r")",
    re.I,
)

_STOP_NAMES = {
    "is",
    "there",
    "any",
    "a",
    "an",
    "the",
    "named",
    "name",
    "names",
    "candidate",
    "candidates",
    "resume",
    "resumes",
    "cv",
    "do",
    "we",
    "have",
    "anyone",
    "person",
    "called",
    "about",
    "what",
    "who",
    "does",
    "with",
    "from",
    "can",
    "could",
    "would",
    "should",
    "you",
    "your",
    "please",
    "how",
    "why",
    "when",
    "where",
    "which",
    "whats",
    "compare",
    "difference",
    "between",
    "versus",
    "output",
    "protection",
    "security",
    "level",
    "levels",
    "agreement",
    "contract",
    "license",
    "document",
    "policy",
}


def is_candidate_lookup(question: str) -> bool:
    q = (question or "").strip()
    if not q:
        return False
    # Never treat product / comparison questions as candidate lookup
    if re.search(
        r"\b(difference|compare|versus|vs\.?|output\s+protection|security\s+level)\b",
        q,
        re.I,
    ):
        return False
    if _CANDIDATE_Q.search(q) and extract_query_names(q):
        return True
    # Bare "Neha?" / "is Neha in the KB?" — require candidate/resume cue OR clear name ask
    names = extract_query_names(q)
    if names and re.search(r"\b(candidate|resume|cv|named|name)\b", q, re.I):
        return True
    if names and re.search(r"\b(is|are|any|have|find|show)\b.+\b(candidate|resume|cv|named)\b", q, re.I):
        return True
    return False


def extract_query_names(question: str) -> list[str]:
    """Pull likely person names from the question (Neha, Nitin Sharma, …)."""
    q = question or ""
    found: list[str] = []

    # Capitalized tokens (handles Neha, Nitin)
    for m in re.finditer(r"\b([A-Z][a-z]{1,30}(?:\s+[A-Z][a-z]{1,30}){0,2})\b", q):
        name = m.group(1).strip()
        if name.lower() in _STOP_NAMES:
            continue
        # Skip all-caps short tokens (acronyms) — not person names
        if name.isupper() and len(name) <= 6:
            continue
        found.append(name)

    # Lowercase fallback: "named neha" / "candidate nitin"
    for m in re.finditer(
        r"\b(?:named|names|name|called|candidate)\s+([a-z][a-z'-]{1,30})\b",
        q,
        re.I,
    ):
        name = m.group(1).strip()
        if name.lower() in _STOP_NAMES:
            continue
        # Title-case for matching
        found.append(name[:1].upper() + name[1:].lower())

    # Dedupe preserving order
    out: list[str] = []
    seen: set[str] = set()
    for n in found:
        key = n.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(n)
    return out
