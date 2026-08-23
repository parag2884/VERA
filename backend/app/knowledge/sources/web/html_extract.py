"""HTML → markdown/text extraction for web crawl (no document parsers)."""

from __future__ import annotations

import re
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

from app.knowledge.sources.web.quality import unique_prose

_PROFILE_HREF = re.compile(
    r"/(profiles?|leaders?|leadership|our-team|team|executives|board)(/|$)",
    re.I,
)


def _slug_to_name(href: str) -> str:
    path = unquote(urlparse(href).path or "").rstrip("/")
    slug = path.rsplit("/", 1)[-1] if path else ""
    if not slug or slug.lower() in {"leaders", "leadership", "team", "profiles", "board"}:
        return ""
    return re.sub(r"[-_]+", " ", slug).strip().title()


def _img_label(img: Tag | None) -> str:
    if img is None:
        return ""
    for key in ("alt", "title", "aria-label"):
        val = (img.get(key) or "").strip()
        if val and len(val) >= 2:
            return val
    return ""


def _harvest_people_lines(soup: BeautifulSoup) -> list[str]:
    """Recover person names hidden in noscript/img alt on org-chart grids.

    Many public sites put roster names only in image alt text (often inside
    <noscript>); get_text() then keeps job titles but drops the people.
    """
    lines: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "").strip()
        if not href or not _PROFILE_HREF.search(href):
            continue
        name = ""
        for img in a.find_all("img"):
            name = _img_label(img)
            if name:
                break
        if not name:
            # noscript may contain raw HTML the parser left as a string
            for ns in a.find_all("noscript"):
                raw = ns.decode_contents() if hasattr(ns, "decode_contents") else str(ns)
                nested = BeautifulSoup(raw, "html.parser")
                for img in nested.find_all("img"):
                    name = _img_label(img)
                    if name:
                        break
                if name:
                    break
        if not name:
            name = (a.get("aria-label") or a.get("title") or "").strip()
        if not name:
            name = _slug_to_name(href)
        if not name:
            continue
        # Reject locale/nav chrome mistaken for people (aria-labels, menu links)
        nl = name.lower()
        if (
            len(name) > 60
            or "," in name
            or any(
                bad in nl
                for bad in (
                    "navigation",
                    "language",
                    "cookie",
                    "menu",
                    "skip to",
                    "united states",
                    "worldwide",
                    "english",
                    "chinese",
                    "deutsch",
                    "español",
                    "português",
                )
            )
            or not re.search(r"[A-Za-z]{2,}", name)
        ):
            continue
        role = ""
        # Scope to this card only — walking up to the grid makes every person
        # inherit the first "Chief …" title on the page.
        card = a.find("li") or a.find(class_=re.compile(r"(card|profile|person)", re.I))
        blob_root: Tag = card if isinstance(card, Tag) else a
        text = " ".join(list(blob_root.stripped_strings)[:12])
        text = re.sub(r"\s+", " ", text).strip()
        # Drop pronoun crumbs that sit next to titles on some sites
        text = re.sub(r"\bPronouns?\b.*$", "", text, flags=re.I).strip()
        m = re.search(
            r"\b("
            r"Chief(?:\s+[A-Za-z][A-Za-z /&-]{1,50})?(?:\s+Officer)?|"
            r"Global Head[A-Za-z /&-]{0,60}|"
            r"Regional Managing Director[A-Za-z /&-]{0,40}|"
            r"Board Member|Chair(?:man|person)?"
            r")\b",
            text,
            re.I,
        )
        if m:
            role = re.sub(r"\s+", " ", m.group(0)).strip(" -|/")
            role = re.sub(r"\bPronouns?\b", "", role, flags=re.I).strip()
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        if role and role.lower() not in name.lower() and len(role) >= 4:
            lines.append(f"{name} serves as {role}.")
        else:
            lines.append(f"{name} is listed among the organization's leaders.")
    return lines


def _promote_headings_and_lists(root: Tag) -> None:
    """Keep page hierarchy in the text we embed and weave (not a flat blob)."""
    for h in list(root.find_all(["h1", "h2", "h3", "h4"])):
        if not isinstance(h, Tag):
            continue
        level = min(3, int(h.name[1]))
        text = h.get_text(" ", strip=True)
        if text:
            h.replace_with(NavigableString(f"\n{'#' * level} {text}\n"))
        else:
            h.decompose()
    for li in list(root.find_all("li")):
        if not isinstance(li, Tag):
            continue
        text = li.get_text(" ", strip=True)
        if text:
            li.replace_with(NavigableString(f"\n- {text}"))
        else:
            li.decompose()


def extract_html_text(html: str, url: str) -> str:
    """Extract page body text with site chrome removed (nav/header/footer/cookies)."""
    soup = BeautifulSoup(html, "html.parser")
    people_lines = _harvest_people_lines(soup)
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "form"]):
        tag.decompose()
    for sel in (
        "nav",
        "header",
        "footer",
        "aside",
        "[role='navigation']",
        "[role='banner']",
        "[role='contentinfo']",
        "[role='complementary']",
        "#onetrust-consent-sdk",
        ".ot-sdk-container",
        "#cookie-banner",
        ".cookie-banner",
        ".cookie-consent",
        ".cookies",
        ".newsletter",
        ".subscribe",
        ".social-share",
        ".share-buttons",
        ".breadcrumb",
        ".breadcrumbs",
        "[aria-label='breadcrumb']",
        ".menu",
        ".site-menu",
        ".mobile-menu",
    ):
        for el in list(soup.select(sel)):
            el.decompose()
    title = (soup.title.string or "").strip() if soup.title else ""
    root = soup.find("main") or soup.find("article") or soup.body or soup
    if isinstance(root, Tag):
        _promote_headings_and_lists(root)
    body = root.get_text("\n", strip=True)
    body = unique_prose(body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    # Drop leftover chrome crumbs that survived selectors
    body = re.sub(
        r"(?im)^(back|close|news archive|menu|skip to (content|main)|accept all|reject all)\s*$",
        "",
        body,
    )
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    if people_lines:
        body = (body + "\n\n" if body else "") + "\n".join(people_lines)
    header = f"# {title or url}\n\nSource: {url}\n\n"
    return header + body[:80_000]
