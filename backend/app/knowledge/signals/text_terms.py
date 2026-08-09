"""Shared text heuristics for ingest signals and Ask relevance.

Lives outside agents.ask so ingest cannot import Ask.
"""

from __future__ import annotations

import re

_BOILERPLATE_PATTERNS = (
    re.compile(r"\bsite\s*map\b", re.I),
    re.compile(r"\bprivacy\s*policy\b.{0,80}\bterms\b", re.I),
    re.compile(r"\bcookie\s*(policy|preferences|settings|list)\b", re.I),
    re.compile(r"\baccessibility\b.{0,40}\b(statement|center|policy)\b", re.I),
    re.compile(r"\bsubscribe\b.{0,40}\bnewsletter\b", re.I),
    re.compile(r"\b(skip to (content|main)|all rights reserved|follow us)\b", re.I),
    re.compile(r"\b(accept all|reject all|confirm my choices)\b", re.I),
    re.compile(r"(?:\|?\s*[A-Z][A-Za-z &/-]{2,28}\s*){6,}"),
)

_ORG_TITLE = (
    r"(?:Executive\s+Vice\s+President|Vice\s+President|"
    r"Chief\s+Executive\s+Officer|Chief\s+Operating\s+Officer|"
    r"Chief\s+Financial\s+Officer|Chief\s+Information\s+Officer|"
    r"Chief\s+[A-Z][A-Za-z]+(?:\s+(?:and|&)\s+[A-Z][A-Za-z]+)*"
    r"(?:\s+[A-Z][A-Za-z]+){0,3}\s+Officer|"
    r"Managing\s+Director|President(?:\s+and\s+CEO)?|Chairman|Chairwoman|Chair|"
    r"CEO|COO|CFO|CTO|CIO|CHRO|CMO|CLO|EVP|SVP)"
)
_PERSON_NAME = (
    r"([A-Z][a-z]+(?:[ \t]+[A-Z]\.?)?(?:[ \t]+[A-Z][A-Za-z'’-]+)+)"
)
_NAME_TITLE_GAP = r"(?:[ \t]*[,–—\-][ \t]*|[ \t]+|[ \t]*\n[ \t]*)"
_PERSON_THEN_TITLE = re.compile(
    rf"\b{_PERSON_NAME}\b{_NAME_TITLE_GAP}{_ORG_TITLE}\b"
)
_TITLE_THEN_PERSON = re.compile(
    rf"\b{_ORG_TITLE}\b(?:[ \t]+|[ \t]*\n[ \t]*){_PERSON_NAME}\b"
)
_NAME_BLOCKLIST = frozenset(
    {
        "president",
        "chairman",
        "chairwoman",
        "chief",
        "executive",
        "operating",
        "financial",
        "information",
        "officer",
        "vice",
        "managing",
        "director",
        "partner",
        "board",
        "company",
        "senior",
        "global",
        "recognized",
    }
)


def boilerplate_penalty(text: str) -> float:
    """Demote nav/chrome / sitemap-ish passages. Higher = worse."""
    t = text or ""
    if len(t.strip()) < 20:
        return 0.4
    pen = 0.0
    for pat in _BOILERPLATE_PATTERNS:
        if pat.search(t):
            pen += 0.35
    words = re.findall(r"[A-Za-z]{3,}", t)
    if len(words) >= 8:
        titleish = sum(1 for w in words if w[0].isupper() and w[1:].islower())
        if titleish / len(words) >= 0.72 and len(t) < 280:
            pen += 0.4
    if t.count("|") >= 3 or t.count("\n") >= 8 and len(t) < 400:
        pen += 0.2
    return min(1.5, pen)


def person_title_names(blob: str) -> list[str]:
    """Distinct person names that appear next to an org role title."""
    names: list[str] = []
    seen: set[str] = set()
    for pat in (_PERSON_THEN_TITLE, _TITLE_THEN_PERSON):
        for m in pat.finditer(blob or ""):
            name = (m.group(1) or "").strip()
            key = name.lower()
            if len(name) < 5 or key in seen:
                continue
            parts = key.split()
            if any(p in _NAME_BLOCKLIST for p in parts):
                continue
            seen.add(key)
            names.append(name)
    return names
