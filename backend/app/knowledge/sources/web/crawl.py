"""Fetch website pages into AcquiredFile texts (Foundry-style URL knowledge source).

Captures publicly reachable HTML + common documents on the same host.
Login-gated / 401-403 pages are skipped. HTML shells escalate to Playwright;
thin pages after render are never stored as knowledge.
"""

from __future__ import annotations

import heapq
import logging
import re
import xml.etree.ElementTree as ET
import inspect
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.config import get_settings
from app.knowledge.contracts import AcquiredFile
from app.knowledge.sources.web.browser_render import BrowserRenderer
from app.knowledge.sources.web.html_extract import extract_html_text
from app.knowledge.sources.web.quality import (
    assess_page_quality,
    topic_coverage_weak,
    unique_prose,
)

logger = logging.getLogger(__name__)

CrawlProgressCb = Callable[[dict[str, Any]], Awaitable[None] | None]

_SKIP_EXT = {
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
    ".mp4",
    ".mp3",
    ".woff",
    ".woff2",
    ".ttf",
    ".ico",
}

_DOC_EXT = {".pdf", ".docx", ".txt", ".md", ".pptx", ".xlsx"}


def _same_host(a: str, b: str) -> bool:
    return urlparse(a).netloc.lower().removeprefix("www.") == urlparse(b).netloc.lower().removeprefix(
        "www."
    )


def _slug(url: str) -> str:
    p = urlparse(url)
    path = (p.path or "/").strip("/").replace("/", "_") or "index"
    path = re.sub(r"[^A-Za-z0-9._-]+", "_", path)[:80]
    return f"{p.netloc}_{path}.md"


def _clean_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed._replace(fragment="", query="").geturl()


# Long-tail paths we never ingest — frees the page budget for About/Leaders/News/etc.
_SKIP_PATH_MARKERS = (
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
)


def _url_skipped(url: str) -> bool:
    """True for case studies / job boards / glossary long-tails — not crawled."""
    path = (urlparse(url).path or "/").lower()
    return any(x in path for x in _SKIP_PATH_MARKERS)


def _url_priority(url: str) -> int:
    """Lower = crawl sooner. Prefer corporate/identity pages."""
    path = (urlparse(url).path or "/").lower()
    if _url_skipped(url):
        return 999
    # Must-have for officer / company Ask (check before shallow-path heuristic)
    boost = (
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
        "/investors",
        "/press",
        "/news",
        "/what-we-do",
        "/services",
        "/solutions",
        "/offerings",
        "/capabilities",
        "/products",
        "/platform",
        "/partnerships",
        "/partners",
        "/careers",
        "/radar",
    )
    if any(x in path for x in boost):
        return 10
    if path in {"", "/"} or path.count("/") <= 1:
        return 5  # homepage / shallow roots after seed
    return 40


def _extract_text(html: str, url: str) -> str:
    return extract_html_text(html, url)


def _page_links(html: str, base: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[str] = []
    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        if not href or href.startswith(("#", "mailto:", "javascript:", "tel:")):
            continue
        abs_url = urljoin(base, href)
        parsed = urlparse(abs_url)
        if parsed.scheme not in {"http", "https"}:
            continue
        path = parsed.path.lower()
        if any(path.endswith(ext) for ext in _SKIP_EXT):
            continue
        out.append(_clean_url(abs_url))
    return out


def _parse_sitemap_urls(xml_text: str) -> list[str]:
    urls: list[str] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return urls
    for el in root.iter():
        tag = el.tag.split("}")[-1].lower()
        if tag == "loc" and el.text:
            urls.append(el.text.strip())
    return urls


async def _seed_from_sitemaps(client: httpx.AsyncClient, start: str) -> list[str]:
    """Discover public URLs from robots.txt + common sitemap paths."""
    parsed = urlparse(start)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    candidates = [
        f"{origin}/sitemap.xml",
        f"{origin}/sitemap_index.xml",
        f"{origin}/sitemap-index.xml",
    ]
    try:
        robots = await client.get(f"{origin}/robots.txt")
        if robots.status_code < 400:
            for line in robots.text.splitlines():
                if line.lower().startswith("sitemap:"):
                    sm = line.split(":", 1)[1].strip()
                    if sm:
                        candidates.append(sm)
    except Exception as exc:  # noqa: BLE001
        logger.info("robots.txt skip %s: %s", origin, exc)

    seeded: list[str] = []
    seen_sm: set[str] = set()
    for sm_url in candidates:
        if sm_url in seen_sm:
            continue
        seen_sm.add(sm_url)
        try:
            resp = await client.get(sm_url)
            if resp.status_code >= 400:
                continue
            ctype = (resp.headers.get("content-type") or "").lower()
            if "xml" not in ctype and "html" in ctype:
                continue
            locs = _parse_sitemap_urls(resp.text)
            for loc in locs:
                if loc.endswith(".xml") and _same_host(start, loc) and loc not in seen_sm:
                    seen_sm.add(loc)
                    try:
                        nested = await client.get(loc)
                        if nested.status_code < 400:
                            locs.extend(_parse_sitemap_urls(nested.text))
                    except Exception:  # noqa: BLE001
                        pass
            for loc in locs:
                if loc.endswith(".xml"):
                    continue
                if _same_host(start, loc):
                    seeded.append(_clean_url(loc))
        except Exception as exc:  # noqa: BLE001
            logger.info("sitemap skip %s: %s", sm_url, exc)
    return seeded


async def fetch_website(
    start_url: str,
    *,
    max_pages: int | None = None,
    max_depth: int | None = None,
    on_progress: CrawlProgressCb | None = None,
) -> list[AcquiredFile]:
    settings = get_settings()
    hard = max(1, int(settings.vera_url_hard_max_pages))
    max_pages = min(max(1, max_pages or settings.vera_url_max_pages), hard)
    max_depth = max(0, max_depth if max_depth is not None else settings.vera_url_max_depth)
    min_prose = max(120, int(settings.vera_crawl_min_prose_chars))
    start = start_url.strip()
    if not start.startswith(("http://", "https://")):
        start = "https://" + start
    start = _clean_url(start)

    files: list[AcquiredFile] = []
    seen: set[str] = set()
    # Priority queue: (priority, seq, url, depth) — lower priority first
    heap: list[tuple[int, int, str, int]] = []
    seq = 0

    def _enqueue(url: str, depth: int, *, force_pri: int | None = None) -> None:
        nonlocal seq
        key = _clean_url(url)
        if key in seen or _url_skipped(key):
            return
        pri = force_pri if force_pri is not None else _url_priority(key)
        heapq.heappush(heap, (pri, seq, key, depth))
        seq += 1

    _enqueue(start, 0, force_pri=0)
    checked = 0
    rendered_js = 0
    skipped_thin = 0

    renderer = BrowserRenderer(
        timeout_ms=settings.vera_crawl_js_timeout_ms,
        concurrency=settings.vera_crawl_js_concurrency,
        enabled=bool(settings.vera_crawl_js_enabled),
    )

    async def _emit(current_url: str = "") -> None:
        if not on_progress:
            return
        payload = {
            "pages": len(files),
            "max_pages": max_pages,
            "checked": checked,
            "queued": len(heap),
            "url": current_url,
            "start_url": start,
            "rendered_js": rendered_js,
            "skipped_thin": skipped_thin,
        }
        result = on_progress(payload)
        if inspect.isawaitable(result):
            await result

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=45.0,
            headers={"User-Agent": "VERA-KnowledgeBot/1.0 (+public crawl; no login)"},
        ) as client:
            await _emit(start)
            for sm_url in await _seed_from_sitemaps(client, start):
                _enqueue(sm_url, 0)
            await _emit(start)

            while heap and len(files) < max_pages:
                _pri, _seq, url, depth = heapq.heappop(heap)
                key = _clean_url(url)
                if key in seen or _url_skipped(key):
                    continue
                seen.add(key)
                checked += 1
                try:
                    resp = await client.get(url)
                    ctype = (resp.headers.get("content-type") or "").lower()
                    if resp.status_code in {401, 403, 404, 407, 429}:
                        logger.info("skip %s status=%s", url, resp.status_code)
                        if checked % 5 == 0 or len(files) % 3 == 0:
                            await _emit(url)
                        continue
                    if resp.status_code >= 400:
                        logger.info("skip %s status=%s", url, resp.status_code)
                        continue

                    path_l = urlparse(url).path.lower()
                    is_doc = any(
                        x in ctype
                        for x in (
                            "application/pdf",
                            "application/vnd.openxmlformats",
                            "text/plain",
                        )
                    ) or any(path_l.endswith(ext) for ext in _DOC_EXT)

                    if is_doc:
                        name = urlparse(url).path.rsplit("/", 1)[-1] or "download.bin"
                        files.append(
                            AcquiredFile(
                                filename=name,
                                mime=ctype.split(";")[0] or None,
                                content=resp.content,
                                appears_at=str(resp.url),
                                source_kind="web",
                            )
                        )
                        await _emit(str(resp.url))
                        continue

                    if "text/html" not in ctype and "application/xhtml" not in ctype:
                        continue

                    final_url = str(resp.url)
                    html = resp.text
                    text = _extract_text(html, final_url)
                    quality = assess_page_quality(
                        html, extracted_text=text, min_prose_chars=min_prose
                    )
                    unique_body = unique_prose(
                        text.split("\n\n", 2)[-1] if "\n\n" in text else text
                    )
                    is_seed = _clean_url(final_url).rstrip("/") == start.rstrip("/")
                    weak_topic = topic_coverage_weak(final_url, unique_body)
                    need_js = (
                        quality.thin
                        or quality.chrome_heavy
                        or weak_topic
                        or is_seed  # always render the crawl seed for trust
                    )

                    if need_js and renderer.enabled:
                        logger.info(
                            "escalate to Playwright %s (thin=%s chrome=%s weak_topic=%s seed=%s %s)",
                            final_url,
                            quality.thin,
                            quality.chrome_heavy,
                            weak_topic,
                            is_seed,
                            quality.reason,
                        )
                        rendered = await renderer.render_html(final_url)
                        if rendered:
                            rendered_js += 1
                            r_text = _extract_text(rendered, final_url)
                            r_quality = assess_page_quality(
                                rendered, extracted_text=r_text, min_prose_chars=min_prose
                            )
                            r_unique = unique_prose(
                                r_text.split("\n\n", 2)[-1] if "\n\n" in r_text else r_text
                            )
                            prefer_rendered = (
                                r_quality.unique_prose_chars > quality.unique_prose_chars
                                or (
                                    topic_coverage_weak(final_url, unique_body)
                                    and not topic_coverage_weak(final_url, r_unique)
                                )
                            )
                            if (
                                prefer_rendered
                                or r_quality.unique_prose_chars >= quality.unique_prose_chars
                            ):
                                html = rendered
                                text = r_text
                                quality = r_quality
                                unique_body = r_unique

                    still_weak = topic_coverage_weak(final_url, unique_body)
                    # Trust rule: never store seed/topic pages that still lack path topics
                    # after JS (cookie shells, empty SPAs).
                    if (
                        quality.thin
                        or len(text.strip()) < 40
                        or (still_weak and (is_seed or need_js))
                    ):
                        skipped_thin += 1
                        logger.warning(
                            "skip thin page (not ingested) %s unique=%s reason=%s weak_topic=%s",
                            final_url,
                            quality.unique_prose_chars,
                            quality.reason,
                            still_weak,
                        )
                        # Still discover links from best HTML we have
                        if depth < max_depth:
                            for link in _page_links(html, final_url):
                                if _same_host(start, link):
                                    _enqueue(link, depth + 1)
                        await _emit(final_url)
                        continue

                    files.append(
                        AcquiredFile(
                            filename=_slug(final_url),
                            mime="text/markdown",
                            content=text.encode("utf-8"),
                            appears_at=final_url,
                            source_kind="web",
                        )
                    )
                    if depth < max_depth:
                        for link in _page_links(html, final_url):
                            if _same_host(start, link):
                                _enqueue(link, depth + 1)
                    await _emit(final_url)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("fetch failed %s: %s", url, exc)
                    await _emit(url)

            await _emit(start)
    finally:
        await renderer.close()

    logger.info(
        "crawl done start=%s acquired=%s rendered_js=%s skipped_thin=%s checked=%s",
        start,
        len(files),
        rendered_js,
        skipped_thin,
        checked,
    )
    return files


def describe_web_job(url: str, count: int) -> dict[str, Any]:
    return {"source": "website", "start_url": url, "pages_acquired": count}
