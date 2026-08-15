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

BROWSER_DATA_DIR = "/app/browser_data"       # Shared (FacebookService)
BROWSER_AGENT_DATA_DIR = "/app/browser_agent_data"  # Exclusive to BrowserAgentService
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
        """Lazily launch a persistent Playwright context, or return the running one.

        BrowserAgentService uses its own dedicated user-data directory
        (browser_agent_data) so it never conflicts with the FacebookService
        context that operates on browser_data. On first launch, it copies
        the Cookies file from the main browser_data so it inherits the
        Facebook session without re-login.
        """
        if self._context:
            return self._context

        agent_dir = Path(BROWSER_AGENT_DATA_DIR)
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Inherit the Facebook session cookie from the main browser_data so
        # we don't need to log in again.
        self._sync_cookies_from_main(agent_dir)

        # Clean up any stale Chromium singleton locks
        for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            lock_path = agent_dir / lock_name
            if lock_path.is_symlink() or lock_path.exists():
                try:
                    lock_path.unlink()
                except Exception:
                    pass

        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=BROWSER_AGENT_DATA_DIR,
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
        logger.info("[BrowserAgent] Dedicated Chromium context launched (dir=%s).", BROWSER_AGENT_DATA_DIR)
        return self._context

    def _sync_cookies_from_main(self, agent_dir: Path) -> None:
        """Copy Chromium profile data (Cookies, Local Storage) from the main
        browser_data directory to the agent-exclusive directory so that the
        Facebook authenticated session is shared without sharing the file lock.
        This is a best-effort operation — failures are silently ignored.
        """
        import shutil
        main_dir = Path(BROWSER_DATA_DIR)
        default_src = main_dir / "Default"
        default_dst = agent_dir / "Default"
        default_dst.mkdir(parents=True, exist_ok=True)

        for filename in ("Cookies", "Local Storage", "IndexedDB", "Session Storage"):
            src = default_src / filename
            dst = default_dst / filename
            if not src.exists():
                continue
            try:
                if src.is_dir():
                    if dst.exists():
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
                logger.debug("[BrowserAgent] Synced %s → %s", src, dst)
            except Exception as e:
                logger.warning("[BrowserAgent] Cookie sync warn (%s): %s", filename, e)


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

    async def facebook_view_profile(self, name_query: str, profile_url: Optional[str] = None) -> Dict[str, Any]:
        """
        Autonomously navigates to a Facebook user's profile.

        Resolution order (highest precision first):
          1. If `profile_url` is provided (derived from thread_href user_id), navigate
             directly — this guarantees the exact correct person from Messenger.
          2. Otherwise fall back to Facebook People Search + token-scored link picking.

        Flow (case 2 only):
          1. Navigate to Facebook People Search with the query.
          2. Wait dynamically for profile links to appear.
          3. Score each candidate by token overlap with the query.
          4. Navigate directly to the best-match URL (no DOM click).
          5. Wait for the profile React SPA to hydrate (up to 10 s).
          6. Dismiss overlays, scroll to load intro, extract text, screenshot.
        """
        logger.info(
            "[BrowserAgent] facebook_view_profile('%s', profile_url=%s)",
            name_query,
            profile_url or "none",
        )

        async with self._lock:
            page = await self._new_page()
            try:
                if profile_url:
                    # ── Direct navigation from thread_href user_id ────────────
                    logger.info("[BrowserAgent] Direct profile URL: %s", profile_url)
                    try:
                        await page.goto(profile_url, wait_until="commit", timeout=NAV_TIMEOUT_MS)
                    except Exception as e:
                        logger.warning("[BrowserAgent] Direct goto notice: %s", e)
                    await asyncio.sleep(10)
                    await self._dismiss_overlays(page)
                    try:
                        await page.evaluate("window.scrollBy(0, 350)")
                    except Exception:
                        pass
                    await asyncio.sleep(1.5)

                    try:
                        profile_name = await page.locator("h1").first.inner_text(timeout=5000)
                    except Exception:
                        profile_name = name_query

                    intro_text = await self._extract_intro_text(page)
                    await self._dismiss_overlays(page)
                    img_path = await self._screenshot(page, f"fb_profile_{_safe_filename(name_query)}")
                    final_url = page.url
                    await page.close()
                    return {
                        "success": True,
                        "image_path": img_path,
                        "profile_name": profile_name.strip(),
                        "profile_url": final_url,
                        "intro_text": intro_text,
                        "source": "direct",
                    }

                # ── Fallback: People Search ────────────────────────────────────
                search_url = FB_PEOPLE_SEARCH.format(query=quote(name_query))
                try:
                    await page.goto(search_url, wait_until="commit", timeout=NAV_TIMEOUT_MS)
                except Exception as e:
                    logger.warning("[BrowserAgent] Search goto notice: %s", e)

                # ── Wait dynamically for profile links to appear ───────────────
                try:
                    await page.wait_for_function(
                        """() => {
                            const links = document.querySelectorAll('a[href]');
                            for (const a of links) {
                                const href = a.href || '';
                                if (href.includes('facebook.com/') && !href.includes('/search/')) return true;
                            }
                            return false;
                        }""",
                        timeout=20000,
                    )
                    await asyncio.sleep(2)
                except Exception:
                    await asyncio.sleep(8)

                logger.info("[BrowserAgent] Search page URL: %s", page.url)
                await self._dismiss_overlays(page)

                profile_href = await self._resolve_best_profile_href(page, name_query)

                if not profile_href:
                    logger.info("[BrowserAgent] No matching profile found; returning search page.")
                    intro_text = await self._extract_page_text(page, max_chars=1500)
                    img_path = await self._screenshot(page, f"fb_search_{_safe_filename(name_query)}")
                    await page.close()
                    return {
                        "success": True,
                        "image_path": img_path,
                        "profile_name": name_query,
                        "profile_url": page.url,
                        "intro_text": intro_text,
                        "note": "Không tìm thấy kết quả khớp chính xác — hiển thị trang kết quả tìm kiếm.",
                    }

                logger.info("[BrowserAgent] Navigating to profile: %s", profile_href)
                try:
                    await page.goto(profile_href, wait_until="commit", timeout=NAV_TIMEOUT_MS)
                except Exception as e:
                    logger.warning("[BrowserAgent] Profile goto notice: %s", e)

                await asyncio.sleep(10)
                await self._dismiss_overlays(page)
                try:
                    await page.evaluate("window.scrollBy(0, 350)")
                except Exception:
                    pass
                await asyncio.sleep(1.5)

                # ── Step 7: Extract name & intro ─────────────────────────────
                try:
                    profile_name = await page.locator("h1").first.inner_text(timeout=5000)
                except Exception:
                    profile_name = name_query

                intro_text = await self._extract_intro_text(page)

                # ── Step 8: Screenshot ────────────────────────────────────────
                await self._dismiss_overlays(page)
                img_path = await self._screenshot(page, f"fb_profile_{_safe_filename(name_query)}")
                final_url = page.url
                await page.close()

                return {
                    "success": True,
                    "image_path": img_path,
                    "profile_name": profile_name.strip(),
                    "profile_url": final_url,
                    "intro_text": intro_text,
                }

            except Exception as e:
                logger.error("[BrowserAgent] facebook_view_profile error: %s", e, exc_info=True)
                try:
                    await page.close()
                except Exception:
                    pass
                return {"success": False, "error": str(e)}


    async def _resolve_best_profile_href(self, page: Page, name_query: str) -> Optional[str]:
        """
        Extracts all profile hrefs from the current search-results page using JS,
        scores each against name_query via Vietnamese-aware token overlap,
        and returns the href of the best match (score ≥ 0.4) — WITHOUT clicking
        any DOM element (avoids race conditions with React re-renders).
        """
        # Normalise the query: strip diacritics via simple replacement, lowercase, split tokens
        import unicodedata
        def _norm(s: str) -> str:
            return unicodedata.normalize("NFD", s.lower())

        query_norm = _norm(name_query)
        query_tokens = set(t for t in re.sub(r"[^\w\s]", " ", query_norm).split() if len(t) > 1)

        try:
            candidates: List[Dict[str, str]] = await page.evaluate("""
            () => {
                const SKIP = new Set([
                    '/search/', '/messages/', '/settings', '/help', '/groups/',
                    '/events/', '/pages/', '/hashtag/', '/reels/', '/reel/',
                    'facebook.com/friends', 'watch', 'marketplace',
                ]);
                const results = [];
                const seen = new Set();
                const links = document.querySelectorAll('a[href]');
                for (const a of links) {
                    const href = (a.href || '').split('?')[0];
                    const text = (a.innerText || a.textContent || '').trim();
                    if (!href || seen.has(href) || !text || text.length > 80) continue;
                    const skip = [...SKIP].some(s => href.includes(s));
                    if (skip) continue;
                    // Must look like a profile URL: facebook.com/<slug> or profile.php?id=
                    const isProfile = (href.indexOf('profile.php') !== -1) ||
                        (href.indexOf('facebook.com/') !== -1 && !href.split('facebook.com/')[1].includes('/'));
                    if (!isProfile) continue;
                    seen.add(href);
                    results.push({ href, text });
                }
                return results.slice(0, 40);
            }
            """)

            logger.info(
                "[BrowserAgent] Profile resolve: candidates=%d query_tokens=%s",
                len(candidates),
                query_tokens,
            )

            best_score = 0.0
            best_href: Optional[str] = None

            for c in candidates:
                text_norm = _norm(c.get("text") or "")
                text_tokens = set(t for t in re.sub(r"[^\w\s]", " ", text_norm).split() if len(t) > 1)
                if not text_tokens:
                    continue
                overlap = len(query_tokens & text_tokens)
                if not overlap:
                    continue
                score = overlap / max(len(query_tokens), len(text_tokens))
                logger.info("[BrowserAgent]  candidate sc=%.2f text=%s", score, c.get("text", "")[:40])
                if score > best_score:
                    best_score = score
                    best_href = c.get("href")

            logger.info(
                "[BrowserAgent] Profile resolve: best_score=%.2f href=%s",
                best_score,
                best_href or "none",
            )
            return best_href if best_score >= 0.4 else None

        except Exception as e:
            logger.warning("[BrowserAgent] _resolve_best_profile_href error: %s", e)
            return None


    async def _extract_intro_text(self, page: Page) -> str:
        """Extract bio, hometown, education, work from the profile intro section.
        Uses multiple fallback selectors to be robust across FB UI versions.
        """
        try:
            intro = await page.evaluate("""
            () => {
                // Priority 1: Dedicated intro widget (pagelet)
                const candidates = [
                    document.querySelector('[data-pagelet="ProfileAppSection_0"]'),
                    document.querySelector('[data-pagelet="ProfileTilesFeed_0"]'),
                    document.querySelector('[aria-label*="\u0067i\u1edbi thi\u1ec7u"]'),  // Vietnamese "giới thiệu"
                    document.querySelector('[aria-label*="Intro"]'),
                    document.querySelector('[role="main"]'),
                    document.body,
                ];
                for (const el of candidates) {
                    if (el && el.innerText && el.innerText.trim().length > 20) {
                        return el.innerText.slice(0, 2000);
                    }
                }
                return '';
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
                try:
                    await page.goto(url, wait_until="commit", timeout=NAV_TIMEOUT_MS)
                except Exception as e:
                    logger.warning("[BrowserAgent] navigate notice: %s", e)
                # Wait for JS-heavy SPAs to render
                await asyncio.sleep(4)
                await self._dismiss_overlays(page)

                title = await page.title()
                page_text = await self._extract_page_text(page, max_chars=3000)
                img_path = await self._screenshot(page, f"browse_{_safe_filename(url[:50])}")
                final_url = page.url
                await page.close()

                return {
                    "success": True,
                    "image_path": img_path,
                    "page_title": title,
                    "page_text": page_text,
                    "url": final_url,
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
