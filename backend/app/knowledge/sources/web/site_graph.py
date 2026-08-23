"""Website structure helpers — path hierarchy + source trust.

Used by Weaver (ingest) and Trust Forge heal. No crawl I/O.
"""

from __future__ import annotations

from urllib.parse import urlparse

from app.knowledge.sources.web.path_policy import (
    is_chronicle_path,
    is_core_path,
    is_people_path,
    url_path,
)


def looks_like_web_title(title: str) -> bool:
    t = (title or "").strip()
    if t.startswith("http://") or t.startswith("https://"):
        return True
    # Crawl filenames: www.example.com_about-us_leaders.md
    if ".md" in t.lower() and ("." in t.split("_")[0] if t else False):
        return True
    if "_http" in t.lower() or t.lower().startswith("www."):
        return True
    return False


def page_path(title_or_url: str) -> str:
    p = url_path(title_or_url)
    if not p.startswith("/"):
        p = "/" + p
    p = p.rstrip("/") or "/"
    return p


def parent_path(path: str) -> str | None:
    p = (path or "/").rstrip("/") or "/"
    if p == "/":
        return None
    parts = [x for x in p.split("/") if x]
    if len(parts) <= 1:
        return "/"
    return "/" + "/".join(parts[:-1])


def trust_weight(title_or_url: str) -> float:
    """0..1 source reliability. Policies/core pages outrank news and chrome."""
    if is_people_path(title_or_url):
        return 0.92
    if is_core_path(title_or_url):
        return 0.88
    if is_chronicle_path(title_or_url):
        return 0.42
    if looks_like_web_title(title_or_url):
        return 0.62
    return 0.78  # uploaded documents default higher than random web pages


def source_url_from_title(title: str) -> str | None:
    t = (title or "").strip()
    if t.startswith("http://") or t.startswith("https://"):
        return t.split()[0]
    return None


def slug_tokens(url_or_title: str) -> list[str]:
    raw = (url_or_title or "").strip()
    path = urlparse(raw).path if raw.startswith("http") else url_path(raw)
    segs = [s for s in path.replace("_", "/").split("/") if s and s not in {".md", "md"}]
    out: list[str] = []
    for s in segs:
        s = s.replace(".md", "").replace("-", " ").strip().lower()
        if len(s) >= 3:
            out.append(s)
    return out[-4:]
