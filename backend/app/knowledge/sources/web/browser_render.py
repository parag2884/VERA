"""Playwright Chromium renderer for JS-heavy public pages."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

_CONSENT_SELECTORS = (
    "#onetrust-accept-btn-handler",
    "button#onetrust-accept-btn-handler",
    "button:has-text('Accept All')",
    "button:has-text('Accept all')",
    "button:has-text('I Agree')",
    "button:has-text('Agree')",
    "button:has-text('Confirm My Choices')",
    "[aria-label='Accept cookies']",
    ".ot-sdk-container button.accept",
)


async def _dismiss_consent(page: Any) -> None:
    """Best-effort cookie / consent banner dismissal."""
    for sel in _CONSENT_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.count() == 0:
                continue
            if await loc.is_visible(timeout=800):
                await loc.click(timeout=1500)
                await page.wait_for_timeout(500)
                return
        except Exception:  # noqa: BLE001
            continue
    # Generic: click a visible button whose label looks like accept
    try:
        await page.evaluate(
            """() => {
              const buttons = Array.from(document.querySelectorAll('button, a'));
              const hit = buttons.find((b) => {
                const t = (b.innerText || b.textContent || '').trim().toLowerCase();
                return (
                  t === 'accept all' ||
                  t === 'accept' ||
                  t === 'i agree' ||
                  t === 'agree' ||
                  t === 'allow all' ||
                  t === 'confirm my choices'
                );
              });
              if (hit) hit.click();
            }"""
        )
        await page.wait_for_timeout(400)
    except Exception:  # noqa: BLE001
        pass


class BrowserRenderer:
    """One browser per crawl job; limited concurrent pages."""

    def __init__(
        self,
        *,
        timeout_ms: int = 20000,
        concurrency: int = 2,
        enabled: bool = True,
    ) -> None:
        self.timeout_ms = max(3000, int(timeout_ms))
        self.concurrency = max(1, int(concurrency))
        self.enabled = enabled
        self._browser: Any = None
        self._playwright: Any = None
        self._sem = asyncio.Semaphore(self.concurrency)
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if not self.enabled:
            return
        async with self._lock:
            if self._browser is not None:
                return
            try:
                from playwright.async_api import async_playwright
            except ImportError as exc:
                logger.error("playwright not installed: %s", exc)
                self.enabled = False
                return
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=["--disable-dev-shm-usage", "--no-sandbox"],
            )
            logger.info("Playwright Chromium started (concurrency=%s)", self.concurrency)

    async def close(self) -> None:
        async with self._lock:
            if self._browser is not None:
                try:
                    await self._browser.close()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("browser close: %s", exc)
                self._browser = None
            if self._playwright is not None:
                try:
                    await self._playwright.stop()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("playwright stop: %s", exc)
                self._playwright = None

    async def render_html(self, url: str) -> str | None:
        """Return rendered HTML, or None on failure / disabled."""
        if not self.enabled:
            return None
        await self.start()
        if self._browser is None:
            return None
        async with self._sem:
            context = None
            page = None
            try:
                context = await self._browser.new_context(
                    user_agent=(
                        "VERA-KnowledgeBot/1.0 (+public crawl; Playwright; no login)"
                    ),
                    viewport={"width": 1360, "height": 900},
                    java_script_enabled=True,
                )
                page = await context.new_page()
                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=self.timeout_ms,
                )
                try:
                    await page.wait_for_load_state(
                        "networkidle", timeout=min(15000, self.timeout_ms)
                    )
                except Exception:  # noqa: BLE001
                    pass
                await _dismiss_consent(page)
                # Lazy sections often need scroll + a short settle
                try:
                    await page.evaluate(
                        """async () => {
                          const delay = (ms) => new Promise(r => setTimeout(r, ms));
                          const h = Math.max(document.body.scrollHeight, 1200);
                          for (const y of [0, h*0.35, h*0.7, h]) {
                            window.scrollTo(0, y);
                            await delay(350);
                          }
                          window.scrollTo(0, 0);
                        }"""
                    )
                except Exception:  # noqa: BLE001
                    await page.wait_for_timeout(1200)
                await _dismiss_consent(page)
                await page.wait_for_timeout(600)
                html = await page.content()
                return html or None
            except Exception as exc:  # noqa: BLE001
                logger.warning("Playwright render failed %s: %s", url, exc)
                return None
            finally:
                if page is not None:
                    try:
                        await page.close()
                    except Exception:  # noqa: BLE001
                        pass
                if context is not None:
                    try:
                        await context.close()
                    except Exception:  # noqa: BLE001
                        pass
