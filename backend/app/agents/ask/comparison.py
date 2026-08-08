"""Comparison-question helpers — domain-agnostic (A vs B, compare X and Y)."""

from __future__ import annotations

import re

# Explicit comparison framing (not product vocabulary)
_COMPARE_FRAME = re.compile(
    r"\b("
    r"compare|comparison|comparing|"
    r"difference|differences|differ|"
    r"versus|vs\.?|"
    r"between"
    r")\b",
    re.I,
)

# "compare A and B" / "difference between A and B" / "A vs B"
_PAIR_PATTERNS = [
    re.compile(
        r"\b(?:compare|comparing|comparison\s+of)\s+(.+?)\s+(?:and|vs\.?|versus)\s+(.+?)(?:\?|$)",
        re.I,
    ),
    re.compile(
        r"\b(?:difference|differences)\s+between\s+(.+?)\s+and\s+(.+?)(?:\?|$)",
        re.I,
    ),
    re.compile(
        r"\b(.+?)\s+(?:vs\.?|versus)\s+(.+?)(?:\?|$)",
        re.I,
    ),
]

# Product / level codes like SL3000, HDCP2, OPL270
_CODE = re.compile(r"\b([A-Za-z]{1,8}\d{2,})\b")


def is_comparison_question(question: str) -> bool:
    q = (question or "").strip()
    if not q:
        return False
    if _COMPARE_FRAME.search(q) and (
        re.search(r"\b(?:and|vs\.?|versus|between)\b", q, re.I)
        or len(_CODE.findall(q)) >= 2
    ):
        return True
    if re.search(r"\b.+\s+(?:vs\.?|versus)\s+.+", q, re.I):
        return True
    return len(_CODE.findall(q)) >= 2 and bool(
        re.search(r"\b(compare|difference|versus|vs\.?)\b", q, re.I)
    )


def extract_compare_sides(question: str) -> list[str]:
    """Return up to two comparison sides from the question text."""
    q = (question or "").strip()
    if not q:
        return []

    sides: list[str] = []
    for pat in _PAIR_PATTERNS:
        m = pat.search(q)
        if not m:
            continue
        a, b = m.group(1).strip(" \t\"'.,"), m.group(2).strip(" \t\"'.,")
        a = _clean_side(a)
        b = _clean_side(b)
        if a and b and a.lower() != b.lower():
            sides = [a, b]
            break

    # Always surface explicit alphanumeric codes (SL3000, SL2000, …)
    codes = _CODE.findall(q)
    for code in codes:
        if code.lower() not in {s.lower() for s in sides}:
            sides.append(code)

    # Prefer codes when we have 2+; otherwise keep phrase sides
    code_sides = [s for s in sides if _CODE.fullmatch(s)]
    if len(code_sides) >= 2:
        # Preserve first-seen order, unique
        out: list[str] = []
        seen: set[str] = set()
        for s in code_sides:
            k = s.lower()
            if k in seen:
                continue
            seen.add(k)
            out.append(s)
        return out[:4]

    out = []
    seen = set()
    for s in sides:
        k = s.lower()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(s)
    return out[:4]


def _clean_side(side: str) -> str:
    s = re.sub(r"\s+", " ", (side or "").strip())
    # Drop leading framing words if the pair pattern was greedy
    s = re.sub(
        r"^(?:the|a|an|compare|comparing|difference|differences|between)\s+",
        "",
        s,
        flags=re.I,
    )
    return s.strip(" \t\"'.,")
