"""Web / URL SourceConnector wrapper around crawl.fetch_website."""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.knowledge.contracts import SourceAcquireResult


class WebConnector:
    kind = "web"

    async def acquire(self, **kwargs: Any) -> SourceAcquireResult:
        # Lazy import keeps registry load free of crawl deps (bs4/httpx stack)
        from app.knowledge.sources.web.crawl import fetch_website

        url = (kwargs.get("url") or "").strip()
        if not url:
            raise ValueError("url is required")
        files = await fetch_website(
            url,
            max_pages=kwargs.get("max_pages"),
            max_depth=kwargs.get("max_depth"),
            on_progress=kwargs.get("on_progress"),
        )
        return SourceAcquireResult(
            kind="web",
            files=files,
            meta={"url": url, "pages": len(files)},
        )

    def status(self) -> dict[str, Any]:
        settings = get_settings()
        return {
            "enabled": True,
            "state": "configured",
            "max_pages": settings.vera_url_max_pages,
            "max_depth": settings.vera_url_max_depth,
            "hard_max_pages": settings.vera_url_hard_max_pages,
            "mode": "public_full",
            "note": (
                "Crawls publicly reachable pages + sitemap URLs on the same host. "
                "Skips login-gated (401/403)."
            ),
        }
