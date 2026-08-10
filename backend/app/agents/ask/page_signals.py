"""Generic page / passage signals for Ask — no site-specific brand phrases.

Boosts and salvage use path shapes (services/solutions/about) and structural
cues (triads, headings), so the same logic works across crawled sites.
"""

from __future__ import annotations

import re

# URL/title path fragments that usually hold offerings / product pages
SERVICE_PATH_MARKERS = (
    "what-we-do",
    "what_we_do",
    "/services",
    "_services",
    "/solutions",
    "_solutions",
    "/offerings",
    "_offerings",
    "/capabilities",
    "_capabilities",
    "/products",
    "_products",
    "/platform",
    "_platform",
)

# Career / L&D pathway pages — not product transformation pathways
CAREER_PATHWAY_MARKERS = (
    "leadership-pathway",
    "leadership_pathway",
    "career-path",
    "career_path",
    "learning-path",
    "learning_path",
    "employee-development",
    "talent-development",
    "career-development",
)

# Thin content / glossary-style insight paths (any site)
INSIGHT_CHROME_MARKERS = (
    "/insights/",
    "_insights_",
    "/blog/",
    "_blog_",
    "/news/",
    "_news_",
    "/decoder",
    "_decoder",
    "/glossary",
    "_glossary",
)

# Branded triad: "Alpha. Beta. Gamma." (any three Title-case words)
_TRIAD_RE = re.compile(
    r"\b([A-Z][a-z]{2,})\.\s+([A-Z][a-z]{2,})\.\s+([A-Z][a-z]{2,})\."
)

_MD_HEADING_RE = re.compile(r"^#{1,3}\s+(.+)$", re.M)
_TITLE_CASE_SPAN_RE = re.compile(
    r"\b([A-Z][a-z0-9]+(?:\s+[A-Z][a-z0-9]+){1,4})\b"
)

_OFFERING_STOP = {
    "about us",
    "read more",
    "learn more",
    "contact us",
    "get started",
    "how we",
    "what we",
    "why we",
    "our work",
    "case study",
    "case studies",
    "privacy policy",
    "cookie policy",
    "terms of",
    "source",
    "blog",
    "news",
}


def path_blob(title: str) -> str:
    return (title or "").lower()


def is_service_page(title: str) -> bool:
    t = path_blob(title)
    return any(m in t for m in SERVICE_PATH_MARKERS)


def is_career_pathway_page(title: str) -> bool:
    t = path_blob(title)
    return any(m in t for m in CAREER_PATHWAY_MARKERS)


def is_insight_chrome_page(title: str) -> bool:
    t = path_blob(title)
    return any(m in t for m in INSIGHT_CHROME_MARKERS)


def has_transformation_triad(text: str) -> bool:
    return bool(_TRIAD_RE.search(text or ""))


def triad_span_pos(text: str) -> int:
    m = _TRIAD_RE.search(text or "")
    return m.start() if m else -1


def offering_list_density(text: str) -> float:
    """0..1 heuristic: many short Title-Case / heading-like offering labels."""
    labels = extract_offering_labels(text, limit=12)
    if len(labels) >= 4:
        return 0.9
    if len(labels) >= 2:
        return 0.55
    if labels:
        return 0.3
    return 0.0


def extract_offering_labels(
    text: str,
    title: str = "",
    *,
    limit: int = 8,
) -> list[str]:
    """Pull offering-like labels from headings / Title-Case spans — not a fixed lexicon."""
    blob = text or ""
    found: list[str] = []
    seen: set[str] = set()

    def add(label: str) -> None:
        label = re.sub(r"\s+", " ", (label or "").strip(" #-–—|:"))
        if len(label) < 4 or len(label) > 60:
            return
        key = label.lower()
        if key in seen or key in _OFFERING_STOP:
            return
        if any(key.startswith(s) for s in _OFFERING_STOP):
            return
        # Skip pure person-looking "First Last" with no service cue words
        if re.fullmatch(r"[A-Z][a-z]+\s+[A-Z][a-z]+", label) and not re.search(
            r"\b(service|platform|ai|data|cloud|software|product|experience|"
            r"engineering|advisory|modernization|capability|center|centre)\b",
            label,
            re.I,
        ):
            return
        seen.add(key)
        found.append(label)

    for m in _MD_HEADING_RE.finditer(blob):
        add(m.group(1))

    # Prefer spans on service-shaped pages or near offering cue words
    prefer = is_service_page(title) or bool(
        re.search(
            r"\b(capabilities|services|offerings?|solutions|what we do|how we help)\b",
            blob,
            re.I,
        )
    )
    if prefer:
        for m in _TITLE_CASE_SPAN_RE.finditer(blob[:2400]):
            add(m.group(1))
            if len(found) >= limit:
                break

    return found[:limit]


def service_support_hit(title: str, text: str) -> bool:
    """True when a quote looks like offerings evidence for any site."""
    if is_service_page(title):
        return True
    if offering_list_density(text) >= 0.55:
        return True
    if has_transformation_triad(text) and re.search(
        r"\b(pathway|transformation|offer|service|capabilit)\b",
        f"{title}\n{text}",
        re.I,
    ):
        return True
    return False
