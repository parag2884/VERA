"""Shared entity identity — structural only, no product/domain vocabulary."""

from __future__ import annotations

import re


def alnum_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def normalize_entity_name(
    name: str, *, aliases: dict[str, str] | None = None
) -> str:
    """Normalize labels for merge / resolve.

    Rules are structural (case, punctuation, whitespace). Optional `aliases`
    come from the agent's inferred domainProfile — never a fixed industry list.
    """
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", (name or "").strip())
    s = re.sub(r"[_\-/]+", " ", s)
    n = " ".join(s.lower().split())
    n = re.sub(r"\s*\([^)]*\)\s*", " ", n).strip()
    n = re.sub(r"\s+", " ", n)
    if not n:
        return ""
    # Optional domain-supplied aliases (short → canonical), applied after normalize
    if aliases:
        if n in aliases:
            return aliases[n]
        # Also allow alias keys that themselves need light normalize
        for src, dst in aliases.items():
            if normalize_entity_name(src) == n and dst:
                return " ".join(str(dst).lower().split())
    return n
