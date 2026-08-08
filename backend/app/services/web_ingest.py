"""Fetch website pages into AcquiredFile texts (Foundry-style URL knowledge source)."""

from __future__ import annotations

import logging
import re
from collections import deque
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.agents.ingest.contracts import AcquiredFile
from app.config import get_settings

logger = logging.getLogger(__name__)

_SKIP_EXT = {
    ".pdf",
    ".zip",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".css",
    ".js",
    ".json",
    ".xml",
    ".mp4",
    ".mp3",
}


def _same_host(a: str, b: str) -> bool:
    return urlparse(a).netloc.lower() == urlparse(b).netloc.lower()


def _slug(url: str) -> str:
    p = urlparse(url)
    path = (p.path or "/").strip("/").replace("/", "_") or "index"
    path = re.sub(r"[^A-Za-z0-9._-]+", "_", path)[:80]
    return f"{p.netloc}_{path}.md"


def _extract_text(html: str, url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
        tag.decompose()
    title = (soup.title.string or "").strip() if soup.title else ""
    body = soup.get_text("\n", strip=True)
    body = re.sub(r"\n{3,}", "\n\n", body)
    header = f"# {title or url}\n\nSource: {url}\n\n"
    return header + body[:80_000]


def _page_links(html: str, base: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[str] = []
    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        if not href or href.startswith(("#", "mailto:", "javascript:")):
            continue
        abs_url = urljoin(base, href)
        parsed = urlparse(abs_url)
        if parsed.scheme not in {"http", "https"}:
            continue
        path = parsed.path.lower()
        if any(path.endswith(ext) for ext in _SKIP_EXT):
            continue
        # Drop fragments / tracking noise
        clean = parsed._replace(fragment="", query="").geturl()
        out.append(clean)
    return out


async def fetch_website(
    start_url: str,
    *,
    max_pages: int | None = None,
    max_depth: int | None = None,
) -> list[AcquiredFile]:
    settings = get_settings()
    max_pages = max_pages or settings.vera_url_max_pages
    max_depth = max_depth if max_depth is not None else settings.vera_url_max_depth
    start = start_url.strip()
    if not start.startswith(("http://", "https://")):
        start = "https://" + start

    files: list[AcquiredFile] = []
    seen: set[str] = set()
    q: deque[tuple[str, int]] = deque([(start, 0)])

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=30.0,
        headers={"User-Agent": "VERA-KnowledgeBot/1.0"},
    ) as client:
        while q and len(files) < max_pages:
            url, depth = q.popleft()
            key = urlparse(url)._replace(fragment="", query="").geturl()
            if key in seen:
                continue
            seen.add(key)
            try:
                resp = await client.get(url)
                ctype = (resp.headers.get("content-type") or "").lower()
                if resp.status_code >= 400:
                    logger.info("skip %s status=%s", url, resp.status_code)
                    continue
                # Direct document download
                if any(
                    x in ctype
                    for x in (
                        "application/pdf",
                        "application/vnd.openxmlformats",
                        "text/plain",
                    )
                ) or urlparse(url).path.lower().endswith((".pdf", ".docx", ".txt", ".md")):
                    name = urlparse(url).path.rsplit("/", 1)[-1] or "download.bin"
                    files.append(
                        AcquiredFile(
                            filename=name,
                            mime=ctype.split(";")[0] or None,
                            content=resp.content,
                            appears_at=url,
                        )
                    )
                    continue
                if "text/html" not in ctype and "application/xhtml" not in ctype:
                    continue
                text = _extract_text(resp.text, str(resp.url))
                if len(text.strip()) < 40:
                    continue
                files.append(
                    AcquiredFile(
                        filename=_slug(str(resp.url)),
                        mime="text/markdown",
                        content=text.encode("utf-8"),
                        appears_at=str(resp.url),
                    )
                )
                if depth < max_depth:
                    for link in _page_links(resp.text, str(resp.url)):
                        if _same_host(start, link) and link not in seen:
                            q.append((link, depth + 1))
            except Exception as exc:  # noqa: BLE001
                logger.warning("fetch failed %s: %s", url, exc)

    return files


def describe_web_job(url: str, count: int) -> dict[str, Any]:
    return {"source": "website", "start_url": url, "pages_acquired": count}
