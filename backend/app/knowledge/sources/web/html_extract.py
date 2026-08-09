"""HTML → markdown/text extraction for web crawl (no document parsers)."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup


def extract_html_text(html: str, url: str) -> str:
    """Extract page body text with site chrome removed (nav/header/footer/cookies)."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()
    for sel in (
        "nav",
        "header",
        "footer",
        "aside",
        "[role='navigation']",
        "[role='banner']",
        "[role='contentinfo']",
        "#onetrust-consent-sdk",
        ".ot-sdk-container",
        "#cookie-banner",
        ".cookie-banner",
    ):
        for el in list(soup.select(sel)):
            el.decompose()
    title = (soup.title.string or "").strip() if soup.title else ""
    root = soup.find("main") or soup.find("article") or soup.body or soup
    body = root.get_text("\n", strip=True)
    body = re.sub(r"\n{3,}", "\n\n", body)
    header = f"# {title or url}\n\nSource: {url}\n\n"
    return header + body[:80_000]
