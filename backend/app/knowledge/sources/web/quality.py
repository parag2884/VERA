"""Detect thin / SPA-shell HTML so we never ingest nav chrome as knowledge.

Chrome detection is structural + universal legal/cookie/nav phrases — not
company- or industry-specific menus.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

# Universal site chrome — safe across arbitrary websites.
_CHROME_MARKERS = (
    "site map",
    "sitemap",
    "privacy policy",
    "terms of use",
    "terms of service",
    "cookie policy",
    "cookie preferences",
    "cookie settings",
    "cookie",
    "cookies",
    "accessibility",
    "close menu",
    "sign in",
    "log in",
    "log out",
    "subscribe",
    "newsletter",
    "reject all",
    "accept all",
    "confirm my choices",
    "personalize ads",
    "targeted advertising",
    "cookie list",
    "leg.interest",
    "all rights reserved",
    "follow us",
    "skip to content",
    "skip to main",
)

# Single-line nav crumbs common on most sites (not product vocabulary).
_NAV_LINE = re.compile(
    r"^(home|about|about us|contact|contact us|careers|blog|news|newsroom|"
    r"solutions|products|services|resources|support|help|faq|"
    r"login|sign in|sign out|log in|log out|close menu|search|menu|"
    r"pricing|partners|company|investors)\s*$",
    re.I,
)


@dataclass(frozen=True)
class PageQuality:
    prose_chars: int
    unique_prose_chars: int
    link_density: float
    chrome_hits: int
    thin: bool
    chrome_heavy: bool
    reason: str


def _main_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    for sel in ("nav", "footer", "header", "[role='navigation']"):
        for el in list(root.select(sel)):
            el.decompose()
    text = root.get_text("\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text)


def unique_prose(text: str) -> str:
    """Strip chrome / menu lines so nav shells don't inflate length."""
    lines: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        # Keep markdown headings promoted from HTML <h1>–<h4>
        if line.startswith("#") or line.startswith("- "):
            lines.append(line)
            continue
        low = line.lower()
        if _NAV_LINE.match(line):
            continue
        if any(m in low for m in _CHROME_MARKERS) and len(line) < 80:
            continue
        # Drop pure Title Case short menu crumbs — keep 2–4 token person names
        words = line.split()
        alpha = [w for w in words if w.isalpha()]
        looks_like_person = 2 <= len(alpha) <= 4 and all(
            w[:1].isupper() and w[1:].islower() for w in alpha if len(w) > 1
        )
        if (
            1 <= len(words) <= 6
            and all(w[:1].isupper() for w in words if w.isalpha())
            and not looks_like_person
        ):
            if not re.search(r"[.!?]", line) and len(line) < 60:
                continue
        lines.append(line)
    return "\n".join(lines)


def assess_page_quality(
    html: str,
    *,
    extracted_text: str = "",
    min_prose_chars: int = 400,
) -> PageQuality:
    """Score whether a page has real body content vs menu/SPA shell."""
    main = _main_text(html)
    body = main
    if extracted_text:
        parts = extracted_text.split("\n\n", 2)
        candidate = parts[-1] if len(parts) >= 3 else extracted_text
        if len(unique_prose(candidate)) > len(unique_prose(body)):
            if len(unique_prose(body)) < min_prose_chars:
                body = candidate

    prose = re.sub(r"\s+", " ", (body or "").strip())
    prose_chars = len(prose)
    unique = unique_prose(body)
    unique_flat = re.sub(r"\s+", " ", unique).strip()
    unique_prose_chars = len(unique_flat)

    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    links = soup.find_all("a", href=True)
    words = max(1, len(re.findall(r"[A-Za-z]{2,}", unique_flat or prose)))
    link_density = len(links) / max(words / 8.0, 1.0)

    full_low = prose.lower()
    chrome_hits = sum(1 for m in _CHROME_MARKERS if m in full_low)
    # Structural: many short Title-Case lines = menu shell
    raw_lines = [ln.strip() for ln in (body or "").splitlines() if ln.strip()]
    titleish = 0
    for ln in raw_lines[:40]:
        ws = ln.split()
        if 1 <= len(ws) <= 5 and all(w[:1].isupper() for w in ws if w.isalpha()):
            if not re.search(r"[.!?]", ln):
                titleish += 1
    menu_dense = titleish >= 8 and unique_prose_chars < min_prose_chars * 2
    chrome_heavy = (chrome_hits >= 4 and unique_prose_chars < min_prose_chars * 3) or menu_dense

    if unique_prose_chars < min_prose_chars:
        return PageQuality(
            prose_chars=prose_chars,
            unique_prose_chars=unique_prose_chars,
            link_density=link_density,
            chrome_hits=chrome_hits,
            thin=True,
            chrome_heavy=chrome_heavy,
            reason=f"unique_prose={unique_prose_chars}<{min_prose_chars}",
        )
    if link_density > 4.0 and unique_prose_chars < min_prose_chars * 2:
        return PageQuality(
            prose_chars=prose_chars,
            unique_prose_chars=unique_prose_chars,
            link_density=link_density,
            chrome_hits=chrome_hits,
            thin=True,
            chrome_heavy=True,
            reason=f"high_link_density={link_density:.1f}",
        )
    if chrome_heavy and unique_prose_chars < min_prose_chars * 2:
        return PageQuality(
            prose_chars=prose_chars,
            unique_prose_chars=unique_prose_chars,
            link_density=link_density,
            chrome_hits=chrome_hits,
            thin=True,
            chrome_heavy=True,
            reason=f"chrome_heavy hits={chrome_hits} titleish={titleish}",
        )
    sentences = len(re.findall(r"[.!?]", unique_flat))
    if sentences < 2 and unique_prose_chars < min_prose_chars * 1.5:
        return PageQuality(
            prose_chars=prose_chars,
            unique_prose_chars=unique_prose_chars,
            link_density=link_density,
            chrome_hits=chrome_hits,
            thin=True,
            chrome_heavy=chrome_heavy,
            reason="few_sentences",
        )

    return PageQuality(
        prose_chars=prose_chars,
        unique_prose_chars=unique_prose_chars,
        link_density=link_density,
        chrome_hits=chrome_hits,
        thin=False,
        chrome_heavy=chrome_heavy,
        reason="ok",
    )


def path_topic_tokens(url: str) -> list[str]:
    """Distinctive path segments that should appear in a real page body."""
    from urllib.parse import urlparse

    path = (urlparse(url).path or "").strip("/")
    if not path:
        return []
    out: list[str] = []
    for seg in path.split("/"):
        seg = seg.strip().lower()
        if not seg or seg in {"index", "home", "en", "www"}:
            continue
        seg = re.sub(r"[^a-z0-9-]+", "-", seg)
        for part in seg.split("-"):
            if len(part) >= 3 and part not in {
                "the",
                "and",
                "for",
                "our",
                "com",
                "www",
            }:
                out.append(part)
    return out[:6]


def topic_coverage_weak(url: str, unique_text: str) -> bool:
    """True when URL slug topics are barely present in unique body (SPA miss)."""
    tokens = path_topic_tokens(url)
    if not tokens:
        return False
    low = (unique_text or "").lower()
    # Person profile URLs: ignore structural segments (profiles/leaders/team).
    # Bios rarely repeat those words; the person-name slug parts matter.
    try:
        from app.knowledge.sources.web.path_policy import is_people_path

        if is_people_path(url):
            structural = {
                "profiles",
                "profile",
                "leaders",
                "leadership",
                "team",
                "board",
                "people",
                "about",
                "executives",
                "management",
            }
            name_tokens = [t for t in tokens if t not in structural]
            if not name_tokens:
                return False
            hits = sum(1 for t in name_tokens if t in low)
            need = 1 if len(name_tokens) <= 2 else max(1, len(name_tokens) // 2)
            return hits < need
    except Exception:  # noqa: BLE001
        pass
    hits = sum(1 for t in tokens if t in low)
    if len(tokens) == 1:
        return low.count(tokens[0]) < 2
    return hits < max(1, len(tokens) // 2)
