"""Site-agnostic URL path policy for crawl priority and Ask ranking.

No brand names — only structural path shapes common across public sites.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# Prefer for crawl + retrieve (identity / product facts)
CORE_PATH_MARKERS = (
    "/about",
    "/leader",
    "/leadership",
    "/our-team",
    "/team/",
    "/company",
    "/who-we-are",
    "/our-story",
    "/management",
    "/executives",
    "/board",
    "/what-we-do",
    "/services",
    "/solutions",
    "/offerings",
    "/capabilities",
    "/products",
    "/platform",
    "/partnerships",
    "/partners",
    "/docs",
    "/documentation",
    "/developer",
    "/developers",
    "/support/docs",
    "/help/docs",
)

# Chronological / thin content — crawl later; demote in Ask unless question asks for it.
# Prefer markers without a required trailing slash so `/insights` and `/insights/x` both match.
CHRONICLE_PATH_MARKERS = (
    "/news",
    "/newsroom",
    "/press",
    "/blog",
    "/blogs",
    "/insights",
    "/articles",
    "/stories",
    "/podcast",
    "/webinar",
    "/events",
    "/decoder",
    "/glossary",
    "/tag/",
    "/tags/",
    "/category/",
)

# Org-chart / officer pages only — NOT every /profiles/<letter>/ directory
# (alphabet people indexes burn the page budget before about/services).
PEOPLE_PATH_MARKERS = (
    "/profiles/leaders",
    "/profiles/board",
    "/about-us/leaders",
    "/about/leaders",
    "/about/team",
    "/company/leaders",
    "/company/leadership",
    "/leadership-team",
    "/leadership",
    "/our-team",
    "/management-team",
    "/board-of-directors",
    "/executives",
)

# Short structural paths to probe early on any public site (404s are fine).
# No brand names — common CMS / marketing URL shapes only.
IDENTITY_SEED_PATHS = (
    "/about",
    "/about-us",
    "/about/us",
    "/company",
    "/who-we-are",
    "/our-story",
    "/our-team",
    "/team",
    "/leadership",
    "/leadership-team",
    "/about-us/leaders",
    "/about/leaders",
    "/what-we-do",
    "/services",
    "/solutions",
    "/products",
    "/platform",
    "/docs",
    "/documentation",
)

# Alternate-locale path prefixes (xx-yy only — avoid treating /ai or /it as locales)
_LOCALE_PREFIX = re.compile(r"^/([a-z]{2}-[a-z]{2})(/|$)", re.I)

# Never crawl (long-tail that rarely helps grounded Ask)
SKIP_PATH_MARKERS = (
    "/clients/",
    "/client/",
    "/case-stud",
    "/case_stud",
    "/customer-stor",
    "/success-stor",
    "/decoder",
    "/glossary",
    "/tag/",
    "/tags/",
    "/category/",
    "/careers/jobs",
    "/job/",
    "/jobs/",
    "/events/",
    "/webinar",
    "/podcast",
    "/login",
    "/signin",
    "/sign-in",
    "/cart",
    "/checkout",
)

_CHRONICLE_Q = re.compile(
    r"\b(news|press|blog|announced|announcement|insights?\s+blog|"
    r"podcast|webinar|yesterday|last\s+week)\b",
    re.I,
)


def url_path(url_or_title: str) -> str:
    raw = (url_or_title or "").strip()
    if raw.startswith("http"):
        return (urlparse(raw).path or "/").lower()
    # crawled titles often look like www.example.com_about-us_leaders.md
    return ("/" + raw.lower().replace(".md", "").replace("_", "/")).replace("//", "/")


def path_has(path: str, markers: tuple[str, ...]) -> bool:
    return any(m in path for m in markers)


def is_chronicle_path(url_or_title: str) -> bool:
    return path_has(url_path(url_or_title), CHRONICLE_PATH_MARKERS)


def is_people_path(url_or_title: str) -> bool:
    return path_has(url_path(url_or_title), PEOPLE_PATH_MARKERS)


def is_core_path(url_or_title: str) -> bool:
    # Chronicle under /about-us/news must not count as core (/about is a prefix).
    if is_chronicle_path(url_or_title):
        return False
    return path_has(url_path(url_or_title), CORE_PATH_MARKERS)


def is_skipped_path(url_or_title: str) -> bool:
    return path_has(url_path(url_or_title), SKIP_PATH_MARKERS)


def locale_prefix(url_or_title: str) -> str | None:
    """Return leading locale segment like 'en-au' when path is locale-prefixed."""
    m = _LOCALE_PREFIX.match(url_path(url_or_title))
    return m.group(1).lower() if m else None


def is_alternate_locale(url: str, seed_url: str) -> bool:
    """True when URL is a different xx-yy locale mirror than the crawl seed."""
    seed_loc = locale_prefix(seed_url)
    url_loc = locale_prefix(url)
    if url_loc is None:
        return False
    if seed_loc is None:
        # Seed is default/unprefixed host language — skip locale mirrors
        return True
    return url_loc != seed_loc


def question_wants_chronicle(question: str) -> bool:
    return bool(_CHRONICLE_Q.search(question or ""))


def path_rank_bonus(question: str, title: str) -> float:
    """Ask re-rank: boost people/core pages; demote chronicle unless question asks for it."""
    if is_people_path(title):
        return 6.0
    if is_core_path(title):
        return 4.0
    if is_chronicle_path(title) and not question_wants_chronicle(question):
        return -5.0
    return 0.0


def filename_term_bonus(question: str, title: str, terms: list[str]) -> float:
    """Boost when question/terms overlap document title or filename-like title."""
    blob = (title or "").lower().replace("_", " ").replace("-", " ").replace(".pdf", " ")
    if not blob:
        return 0.0
    q_tokens = set(re.findall(r"[a-z0-9]{3,}", (question or "").lower()))
    q_tokens -= {
        "what",
        "how",
        "who",
        "the",
        "and",
        "for",
        "with",
        "from",
        "does",
        "are",
        "can",
        "document",
        "about",
    }
    hit = sum(1 for t in q_tokens if t in blob)
    term_hit = sum(1 for t in terms if t and t.lower() in blob)
    score = 0.0
    if hit:
        score += min(6.0, 1.5 * hit)
    if term_hit:
        score += min(8.0, 2.5 * term_hit)
    return score
