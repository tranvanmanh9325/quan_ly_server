"""
BrowserAgentService — Autonomous Multi-Step Browser-Use & Computer-Use Engine.

Implements the ReAct (Reasoning → Action → Observation) paradigm using Playwright Chromium.
Provides pluggable Action Primitives that the AI Agent can invoke to autonomously navigate,
search, interact with, and extract information from any website — including Facebook profile
pages, Google search, and arbitrary URLs — without any hard-coded flow.

Design decisions:
- Uses a SINGLE shared Playwright context (launched once, reused across calls) to avoid
  the ~5-second cold-start cost per invocation and to retain authenticated session cookies.
- Enforces a module-level asyncio.Lock to serialise browser access and prevent profile corruption.
- Screenshot paths are deterministic so they can be easily cleaned up between runs.
- All public methods return structured dicts so the AiAgentService can route the image
  to Telegram and surface a clean Markdown summary in one step.
"""

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, cast
from urllib.parse import quote

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
)

from app.config import settings

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

BROWSER_DATA_DIR = "/app/browser_data"
SCREENSHOT_DIR = Path("/tmp/browser_agent")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

# Viewport that mimics a standard 16:9 laptop display
VIEWPORT = {"width": 1366, "height": 768}

# Facebook People search URL template
FB_PEOPLE_SEARCH = "https://www.facebook.com/search/people/?q={query}"
FB_HOME = "https://www.facebook.com/"
GOOGLE_SEARCH = "https://www.google.com/search?q={query}&hl=vi"

# How long to wait for key UI elements to appear (ms)
DEFAULT_TIMEOUT_MS = 30_000
NAV_TIMEOUT_MS = 45_000


# ─── Helper ───────────────────────────────────────────────────────────────────

def _safe_filename(text: str) -> str:
    """Convert arbitrary text to a filesystem-safe slug."""
    slug = re.sub(r"[^\w]", "_", text.strip().lower())
    return re.sub(r"_+", "_", slug)[:80]


def _now_ms() -> int:
    return int(time.time() * 1000)


# ─── Service ──────────────────────────────────────────────────────────────────

class BrowserAgentService:
    """
    Autonomous browser-use engine exposing high-level Action Primitives.

    The service manages a long-lived Playwright Chromium context backed by the
    same persistent user-data directory as FacebookService so it shares the
    already-authenticated Facebook session without re-login.
    """

    def __init__(self) -> None:
        # One global lock to serialise all browser operations across the event loop.
        # This prevents race conditions when multiple Telegram messages arrive simultaneously.
        self._lock = asyncio.Lock()
        self._playwright: Optional[Playwright] = None
        self._context: Optional[BrowserContext] = None

    # ──────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────────────────────

    async def _ensure_context(self) -> BrowserContext:
        """Lazily launch a persistent Playwright context, or return the running one."""
        if self._context:
            return self._context

        # Clean up any stale Chromium singleton locks left from a previous crash
        for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            lock_path = Path(BROWSER_DATA_DIR) / lock_name
            if lock_path.is_symlink() or lock_path.exists():
                try:
                    lock_path.unlink()
                except Exception:
                    pass

        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=BROWSER_DATA_DIR,
            headless=True,
            viewport=VIEWPORT,
            timezone_id="Asia/Ho_Chi_Minh",
            locale="vi-VN",
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
            ],
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/127.0.0.0 Safari/537.36"
            ),
        )
        logger.info("[BrowserAgent] Persistent Chromium context launched.")
        return self._context

    async def close(self) -> None:
        """Gracefully shut down the browser context on service shutdown."""
        try:
            if self._context:
                await self._context.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            logger.warning("[BrowserAgent] Error during close: %s", e)
        finally:
            self._context = None
            self._playwright = None

    # ──────────────────────────────────────────────────────────────────────────
    # Internal browser helpers
    # ──────────────────────────────────────────────────────────────────────────

    async def _new_page(self) -> Page:
        ctx = await self._ensure_context()
        page = await ctx.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)
        page.set_default_navigation_timeout(NAV_TIMEOUT_MS)
        return page

    async def _safe_goto(self, page: Page, url: str) -> None:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        except Exception as e:
            logger.warning("[BrowserAgent] goto notice (%s): %s", url, e)

    async def _dismiss_overlays(self, page: Page) -> None:
        """Remove modal dialogs and cookie banners that obscure page content."""
        try:
            await page.evaluate("""
            () => {
                const selectors = [
                    '[role="dialog"]',
                    '[role="alertdialog"]',
                    '[data-testid="cookie-policy-manage-dialog"]',
                    'div[aria-modal="true"]',
                ];
                selectors.forEach(sel => {
                    document.querySelectorAll(sel).forEach(el => el.remove());
                });
                // Remove fixed overlay backdrops that are NOT the main layout
                document.querySelectorAll('div[style*="position: fixed"]').forEach(el => {
                    if (!el.querySelector('[role="main"]') && !el.querySelector('[role="navigation"]')) {
                        el.style.display = 'none';
                    }
                });
            }
            """)
        except Exception:
            pass

    async def _screenshot(self, page: Page, name: str) -> str:
        """Take a full-page screenshot and return its absolute path."""
        path = str(SCREENSHOT_DIR / f"{name}_{_now_ms()}.png")
        await page.screenshot(path=path, full_page=False)
        logger.info("[BrowserAgent] Screenshot saved → %s", path)
        return path

    async def _extract_page_text(self, page: Page, max_chars: int = 4000) -> str:
        """Extract visible text from page body, truncated to max_chars."""
        try:
            text = await page.evaluate("""
            () => {
                const body = document.querySelector('[role="main"]') || document.body;
                return body ? body.innerText : '';
            }
            """)
            return (text or "")[:max_chars]
        except Exception:
            return ""

    # ──────────────────────────────────────────────────────────────────────────
    # Action Primitives (public API consumed by AiAgentService)
    # ──────────────────────────────────────────────────────────────────────────

    async def facebook_view_profile(self, name_query: str) -> Dict[str, Any]:
        """
        Autonomously searches for a Facebook user by name and navigates to their profile.

        Flow:
          1. Navigate to Facebook People Search with the given query.
          2. Wait for search results to render.
          3. Click the first result whose name best matches the query.
          4. Wait for the profile page to load; dismiss overlays.
          5. Extract bio / intro text; take screenshot.

        Returns a structured dict with:
          - success (bool)
          - image_path (str): absolute path to the screenshot PNG
          - profile_name (str): the name found on the profile page
          - profile_url (str): the URL of the profile page
          - intro_text (str): extracted bio / about section text
          - error (str): set only on failure
        """
        logger.info("[BrowserAgent] facebook_view_profile('%s')", name_query)

        async with self._lock:
            page = await self._new_page()
            try:
                # 1. Navigate to Facebook People Search
                search_url = FB_PEOPLE_SEARCH.format(query=quote(name_query))
                await self._safe_goto(page, search_url)

                # 2. Wait for search results
                try:
                    await page.wait_for_selector(
                        'div[data-pagelet="SearchResults"], div[role="feed"], a[role="link"]',
                        timeout=20000,
                    )
                except Exception:
                    pass
                await asyncio.sleep(2.5)
                await self._dismiss_overlays(page)

                # 3. Find and click the best matching result link
                profile_url = await self._click_best_search_result(page, name_query)

                # 4. If no clickable result found, try direct URL navigation via graph
                if not profile_url:
                    logger.info("[BrowserAgent] No clickable result; falling back to search result page screenshot.")
                    await self._dismiss_overlays(page)
                    img_path = await self._screenshot(page, f"fb_search_{_safe_filename(name_query)}")
                    page_text = await self._extract_page_text(page)
                    await page.close()
                    return {
                        "success": True,
                        "image_path": img_path,
                        "profile_name": name_query,
                        "profile_url": page.url,
                        "intro_text": page_text[:1500],
                        "note": "Không tìm thấy kết quả khớp chính xác; hiển thị trang tìm kiếm.",
                    }

                # 5. Wait for profile page to finish loading
                await page.wait_for_load_state("domcontentloaded")
                try:
                    await page.wait_for_selector(
                        '[data-pagelet="ProfileTilesFeed_0"], [data-pagelet="ProfileAppSection_0"], h1, [role="main"]',
                        timeout=18000,
                    )
                except Exception:
                    pass
                await asyncio.sleep(2.0)
                await self._dismiss_overlays(page)

                # 6. Scroll slightly to load bio / intro section
                await page.evaluate("window.scrollBy(0, 300)")
                await asyncio.sleep(1.0)

                # 7. Extract profile name from <h1>
                try:
                    profile_name = await page.locator("h1").first.inner_text(timeout=5000)
                except Exception:
                    profile_name = name_query

                # 8. Extract intro / about section
                intro_text = await self._extract_intro_text(page)

                # 9. Screenshot
                await self._dismiss_overlays(page)
                img_path = await self._screenshot(page, f"fb_profile_{_safe_filename(name_query)}")
                await page.close()

                return {
                    "success": True,
                    "image_path": img_path,
                    "profile_name": profile_name.strip(),
                    "profile_url": profile_url,
                    "intro_text": intro_text,
                }

            except Exception as e:
                logger.error("[BrowserAgent] facebook_view_profile error: %s", e, exc_info=True)
                try:
                    await page.close()
                except Exception:
                    pass
                return {"success": False, "error": str(e)}

    async def _click_best_search_result(self, page: Page, name_query: str) -> Optional[str]:
        """
        Evaluates search result links, scores them against name_query using token overlap,
        clicks the best match (score ≥ 0.5), and returns the resulting URL.
        """
        query_norm = re.sub(r"[^\w\s]", "", name_query.lower().strip())
        query_tokens = set(query_norm.split())

        try:
            # Collect all profile links with their visible text
            candidates: List[Dict[str, str]] = await page.evaluate("""
            () => {
                const results = [];
                const seen = new Set();
                const links = document.querySelectorAll('a[href*="/"][role="link"], a[href*="facebook.com/"]');
                for (const a of links) {
                    const href = a.href || '';
                    const text = (a.innerText || a.textContent || '').trim();
                    // Only profile links (not search/messages/settings)
                    if (
                        !href ||
                        seen.has(href) ||
                        !text ||
                        href.includes('/search/') ||
                        href.includes('/messages/') ||
                        href.includes('/settings') ||
                        href.includes('/help') ||
                        href.includes('/groups/') ||
                        href.includes('/events/') ||
                        href.includes('/pages/') ||
                        text.length > 60
                    ) continue;
                    seen.add(href);
                    results.push({ href, text });
                }
                return results.slice(0, 30);
            }
            """)

            best_score = 0.0
            best_href: Optional[str] = None

            for c in candidates:
                text_norm = re.sub(r"[^\w\s]", "", (c.get("text") or "").lower())
                text_tokens = set(text_norm.split())
                if not text_tokens:
                    continue
                overlap = len(query_tokens & text_tokens)
                score = overlap / max(len(query_tokens), len(text_tokens))
                if score > best_score:
                    best_score = score
                    best_href = c.get("href")

            if best_href and best_score >= 0.4:
                logger.info("[BrowserAgent] Best match: score=%.2f href=%s", best_score, best_href)
                await page.goto(best_href, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                return best_href

        except Exception as e:
            logger.warning("[BrowserAgent] _click_best_search_result error: %s", e)

        return None

    async def _extract_intro_text(self, page: Page) -> str:
        """Extract bio, hometown, education, work from the profile intro section."""
        try:
            intro = await page.evaluate("""
            () => {
                // Try the dedicated intro widget first
                const intro = document.querySelector('[data-pagelet="ProfileAppSection_0"]')
                           || document.querySelector('[aria-label*="Giới thiệu"]')
                           || document.querySelector('[aria-label*="Intro"]');
                if (intro) return intro.innerText;
                // Fallback: grab main content
                const main = document.querySelector('[role="main"]');
                return main ? main.innerText.slice(0, 2000) : '';
            }
            """)
            return (intro or "")[:2000]
        except Exception:
            return ""

    # ──────────────────────────────────────────────────────────────────────────

    async def browser_navigate(self, url: str) -> Dict[str, Any]:
        """
        Navigate to any URL and take a screenshot.
        Returns image_path, page_title, and extracted page text.
        """
        logger.info("[BrowserAgent] browser_navigate('%s')", url)
        async with self._lock:
            page = await self._new_page()
            try:
                await self._safe_goto(page, url)
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                await asyncio.sleep(1.5)
                await self._dismiss_overlays(page)

                title = await page.title()
                page_text = await self._extract_page_text(page, max_chars=3000)
                img_path = await self._screenshot(page, f"browse_{_safe_filename(url[:50])}")
                await page.close()

                return {
                    "success": True,
                    "image_path": img_path,
                    "page_title": title,
                    "page_text": page_text,
                    "url": url,
                }
            except Exception as e:
                logger.error("[BrowserAgent] browser_navigate error: %s", e, exc_info=True)
                try:
                    await page.close()
                except Exception:
                    pass
                return {"success": False, "error": str(e), "url": url}

    # ──────────────────────────────────────────────────────────────────────────

    async def browser_search_google(self, query: str) -> Dict[str, Any]:
        """
        Perform a Google search and return:
          - image_path: screenshot of the search results page
          - top_results: list of {title, url, snippet} for the top 5 organic results
          - page_text: raw visible text from the results page
        """
        logger.info("[BrowserAgent] browser_search_google('%s')", query)
        async with self._lock:
            page = await self._new_page()
            try:
                search_url = GOOGLE_SEARCH.format(query=quote(query))
                await self._safe_goto(page, search_url)
                try:
                    await page.wait_for_selector("#search, #rso, .g", timeout=15000)
                except Exception:
                    pass
                await asyncio.sleep(1.5)
                await self._dismiss_overlays(page)

                # Extract top organic results
                top_results: List[Dict[str, str]] = await page.evaluate("""
                () => {
                    const results = [];
                    const cards = document.querySelectorAll('.g, [data-sokoban-container]');
                    for (const card of cards) {
                        const aTag = card.querySelector('a[href]');
                        const h3 = card.querySelector('h3');
                        const snippet = card.querySelector('.VwiC3b, [data-sncf]');
                        if (aTag && h3) {
                            results.push({
                                title: h3.innerText || '',
                                url: aTag.href || '',
                                snippet: snippet ? snippet.innerText.slice(0, 200) : '',
                            });
                        }
                        if (results.length >= 5) break;
                    }
                    return results;
                }
                """)

                page_text = await self._extract_page_text(page, max_chars=3000)
                img_path = await self._screenshot(page, f"google_{_safe_filename(query)}")
                await page.close()

                return {
                    "success": True,
                    "image_path": img_path,
                    "query": query,
                    "top_results": top_results,
                    "page_text": page_text,
                }
            except Exception as e:
                logger.error("[BrowserAgent] browser_search_google error: %s", e, exc_info=True)
                try:
                    await page.close()
                except Exception:
                    pass
                return {"success": False, "error": str(e), "query": query}

    # ──────────────────────────────────────────────────────────────────────────

    async def browser_click(self, selector_or_text: str, page_ref: Optional[Page] = None) -> Dict[str, Any]:
        """
        Click an element identified by a CSS selector or visible text on the current page.
        If no page_ref is provided, opens the last known active page.
        This primitive is designed for multi-step interaction chains.
        """
        logger.info("[BrowserAgent] browser_click('%s')", selector_or_text)
        async with self._lock:
            ctx = await self._ensure_context()
            pages = ctx.pages
            page = pages[-1] if pages else await self._new_page()
            try:
                # Try CSS selector first
                try:
                    await page.click(selector_or_text, timeout=8000)
                except Exception:
                    # Fallback: click by visible text
                    await page.get_by_text(selector_or_text, exact=False).first.click(timeout=8000)

                await asyncio.sleep(1.5)
                img_path = await self._screenshot(page, f"click_{_safe_filename(selector_or_text[:30])}")
                return {"success": True, "image_path": img_path, "action": f"Đã click: {selector_or_text}"}
            except Exception as e:
                logger.error("[BrowserAgent] browser_click error: %s", e)
                return {"success": False, "error": str(e)}

    # ──────────────────────────────────────────────────────────────────────────

    async def browser_take_screenshot(self) -> Dict[str, Any]:
        """Take a screenshot of the currently open browser page."""
        logger.info("[BrowserAgent] browser_take_screenshot()")
        async with self._lock:
            ctx = await self._ensure_context()
            pages = ctx.pages
            if not pages:
                return {"success": False, "error": "Không có trang nào đang mở trong trình duyệt."}
            page = pages[-1]
            try:
                img_path = await self._screenshot(page, f"snap_{_now_ms()}")
                title = await page.title()
                return {"success": True, "image_path": img_path, "page_title": title, "url": page.url}
            except Exception as e:
                logger.error("[BrowserAgent] browser_take_screenshot error: %s", e)
                return {"success": False, "error": str(e)}
