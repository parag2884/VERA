"""Candidate / person-name question helpers for resume lookups."""

from __future__ import annotations

import re

_CANDIDATE_Q = re.compile(
    r"("
    r"\bcandidate\b|"
    r"\bresume\b|"
    r"\bcv\b|"
    r"\bnamed\b|"
    # "name Neha" / "names Nitin" — not "Name some capabilities…"
    r"\bnames?\s+[A-Z][a-z]|"
    r"is\s+there\s+(any|a)\b|"
    r"do\s+we\s+have\b|"
    r"anyone\s+named\b|"
    r"person\s+named\b"
    r")",
    re.I,
)

# "Name some capabilities / services / offerings" is a define/list ask, not a resume lookup
_LIST_NAME_ASK = re.compile(
    r"\bname\s+(some|a\s+few|the|any|our|their)\b|"
    r"\b(capabilities|services|offerings?|features|products|pathways)\b",
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
    "agreement",
    "contract",
    "license",
    "document",
    "policy",
    "level",
    "levels",
}


def is_candidate_lookup(question: str) -> bool:
    q = (question or "").strip()
    if not q:
        return False
    # Never treat comparison questions as candidate lookup
    if re.search(r"\b(difference|compare|versus|vs\.?|between)\b", q, re.I):
        return False
    # "Name some capabilities…" / offerings lists are define-shape, not people
    if _LIST_NAME_ASK.search(q):
        return False
    if _CANDIDATE_Q.search(q) and extract_query_names(q):
        return True
    # Bare "Neha?" / "is Neha in the KB?" — require candidate/resume cue OR clear name ask
    names = extract_query_names(q)
    if names and re.search(r"\b(candidate|resume|cv|named)\b", q, re.I):
        return True
    if names and re.search(
        r"\bnames?\s+[A-Z][a-z]",
        q,
    ):
        return True
    if names and re.search(
        r"\b(is|are|any|have|find|show)\b.+\b(candidate|resume|cv|named)\b", q, re.I
    ):
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
