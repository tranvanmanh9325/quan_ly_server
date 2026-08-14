import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, cast
import psycopg
from psycopg.rows import dict_row
from playwright.async_api import async_playwright, BrowserContext, Page

from app.config import settings
from app.services.message_cache import FacebookMessageCache

logger = logging.getLogger(__name__)
VN_TZ = timezone(timedelta(hours=7))

# Persistent browser context directory — mounted as a Docker volume so E2EE keys
# survive container restarts. Without persistence, the sidebar never renders in
# headless mode because Facebook's E2EE requires local IndexedDB encryption keys.
BROWSER_DATA_DIR = "/app/browser_data"


class FacebookService:
    def __init__(self, message_cache: FacebookMessageCache, ai_agent_ref: Any = None):
        self.message_cache = message_cache
        self.ai_agent = ai_agent_ref
        self._is_scanning = False
        self._last_scan_status = "idle"
        self._lock = asyncio.Lock()

    def set_ai_agent(self, ai_agent: Any) -> None:
        self.ai_agent = ai_agent

    # ─── DB helpers ──────────────────────────────────────────────────────────

    async def get_config_from_db(self) -> Dict[str, Any]:
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url, row_factory=cast(Any, dict_row)) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT id, cookies_json, cooldown_minutes, custom_message, enabled, "
                        "last_status, threshold, scan_interval_minutes FROM facebook_config LIMIT 1"
                    )
                    row = await cur.fetchone()
                    if row:
                        return dict(row)
        except Exception as e:
            logger.error("[FB-Service] Error fetching config from DB: %s", e)
        return {
            "enabled": False, "threshold": 3,
            "cookies_json": "[]", "custom_message": "",
            "scan_interval_minutes": 5,
        }

    async def save_config_to_db(self, cfg: Dict[str, Any]) -> None:
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        INSERT INTO facebook_config (id, cookies_json, cooldown_minutes, custom_message, enabled, last_status, threshold, scan_interval_minutes, created_at, updated_at)
                        VALUES (1, %s, 15, %s, %s, 'updated', %s, %s, NOW(), NOW())
                        ON CONFLICT (id) DO UPDATE SET
                            cookies_json = EXCLUDED.cookies_json,
                            custom_message = EXCLUDED.custom_message,
                            enabled = EXCLUDED.enabled,
                            threshold = EXCLUDED.threshold,
                            scan_interval_minutes = EXCLUDED.scan_interval_minutes,
                            updated_at = NOW()
                        """,
                        (
                            cfg.get("cookies_json", "[]"),
                            cfg.get("custom_message", ""),
                            cfg.get("enabled", False),
                            cfg.get("threshold", 3),
                            cfg.get("scan_interval_minutes", 5),
                        ),
                    )
                    await conn.commit()
        except Exception as e:
            logger.error("[FB-Service] Error saving config to DB: %s", e)

    async def is_sender_in_cooldown(self, sender_key: str, cooldown_minutes: int = 15) -> bool:
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT replied_at FROM facebook_cooldown WHERE sender_key = %s",
                        (sender_key,),
                    )
                    row = await cur.fetchone()
                    if row:
                        replied_at = row[0]
                        if datetime.now(timezone.utc) - replied_at < timedelta(minutes=cooldown_minutes):
                            return True
        except Exception as e:
            logger.warning("[FB-Service] Cooldown check error: %s", e)
        return False

    async def record_sender_cooldown(self, sender_key: str) -> None:
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        INSERT INTO facebook_cooldown (sender_key, replied_at)
                        VALUES (%s, NOW())
                        ON CONFLICT (sender_key) DO UPDATE SET replied_at = NOW()
                        """,
                        (sender_key,),
                    )
                    await conn.commit()
        except Exception as e:
            logger.warning("[FB-Service] Cooldown record error: %s", e)

    async def get_known_threads_from_db(self) -> List[Dict[str, str]]:
        """Returns all known thread URLs stored from previous scans."""
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url, row_factory=cast(Any, dict_row)) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT thread_href, sender_name FROM facebook_known_threads ORDER BY discovered_at DESC LIMIT 20"
                    )
                    rows = await cur.fetchall()
                    return [{"href": row["thread_href"], "text": row["sender_name"]} for row in rows]
        except Exception as e:
            logger.warning("[FB-Service] Error fetching known threads: %s", e)
        return []

    async def save_known_thread(self, href: str, sender_name: str) -> None:
        """Persists a discovered thread URL so future scans can check it directly."""
        if not href:
            return
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        INSERT INTO facebook_known_threads (thread_href, sender_name, last_checked_at, discovered_at)
                        VALUES (%s, %s, NOW(), NOW())
                        ON CONFLICT (thread_href) DO UPDATE SET
                            sender_name = EXCLUDED.sender_name,
                            last_checked_at = NOW()
                        """,
                        (href.split("?")[0], sender_name),
                    )
                    await conn.commit()
        except Exception as e:
            logger.warning("[FB-Service] Error saving known thread: %s", e)

    # ─── Cookie helpers ───────────────────────────────────────────────────────

    def _parse_cookies(self, cookies_json: str) -> List[Dict[str, Any]]:
        if not cookies_json or not cookies_json.strip():
            return []
        try:
            raw = json.loads(cookies_json)
            cookies = []
            if isinstance(raw, list):
                for c in raw:
                    name = c.get("name")
                    value = c.get("value")
                    domain = c.get("domain", ".facebook.com")
                    path = c.get("path", "/")
                    if name and value:
                        raw_ss = str(c.get("sameSite", "Lax") or "Lax").lower()
                        if "strict" in raw_ss:
                            same_site = "Strict"
                        elif "none" in raw_ss or "no_restriction" in raw_ss:
                            same_site = "None"
                        else:
                            same_site = "Lax"
                        cookies.append({
                            "name": name, "value": value, "domain": domain, "path": path,
                            "secure": bool(c.get("secure", True)),
                            "httpOnly": bool(c.get("httpOnly", False)),
                            "sameSite": same_site,
                        })
            return cookies
        except Exception as e:
            logger.error("[FB-Service] Failed to parse cookies JSON: %s", e)
            return []

    # ─── Playwright helpers ───────────────────────────────────────────────────

    async def _handle_e2ee_pin_screen(self, page: Page) -> bool:
        """Handles Facebook's 6-digit E2EE PIN screen if it appears."""
        try:
            pin_inputs = await page.query_selector_all(
                "input[type='password'], input[maxlength='1'], input[inputmode='numeric']"
            )
            if len(pin_inputs) in (1, 6):
                logger.info("[FB-Service] E2EE PIN screen detected. Unlocking...")
                pin = "090305"
                if len(pin_inputs) == 6:
                    for i, digit in enumerate(pin):
                        await pin_inputs[i].fill(digit)
                        await asyncio.sleep(0.1)
                else:
                    await pin_inputs[0].fill(pin)
                await asyncio.sleep(1.0)
                submit_btn = await page.query_selector(
                    "button[type='submit'], [aria-label*='Tiếp tục'], [aria-label*='Continue']"
                )
                if submit_btn:
                    await submit_btn.click()
                    await asyncio.sleep(3.0)
                return True
        except Exception as e:
            logger.warning("[FB-Service] Error handling E2EE PIN screen: %s", e)
        return False

    async def _extract_thread_name_from_page(self, page: Page) -> str:
        """Extracts the conversation partner's name from the page title or header."""
        try:
            # Try page title (e.g. "(2) Trần Văn Mạnh | Messenger")
            title = await page.title()
            if title and "|" in title:
                name = title.split("|")[0].strip()
                # Strip unread count prefix: "(2) Trần Văn Mạnh" → "Trần Văn Mạnh"
                import re
                name = re.sub(r'^\(\d+\)\s*', '', name).strip()
                if name and name.lower() not in ("messenger", "facebook", ""):
                    return name

            # Try aria-label on conversation header
            header = await page.query_selector(
                "h1, [role='banner'] [role='link'], [aria-label*='Cuộc trò chuyện']"
            )
            if header:
                txt = await header.inner_text()
                if txt and txt.strip():
                    return txt.strip()
        except Exception as e:
            logger.debug("[FB-Service] Could not extract thread name: %s", e)
        return "Người dùng Facebook"

    async def _extract_incoming_messages(self, page: Page) -> List[str]:
        """Extracts genuine incoming messages from the open chat window.

        Uses aria-label heuristics first (most reliable), falling back to
        dir=auto text scanning if the structured approach yields nothing.
        """
        try:
            script = """
            () => {
              let main = document.querySelector('[role="main"]') || document.querySelector('[role="region"]') || document.body;
              let bubbles = Array.from(main.querySelectorAll('[aria-label]')).filter(el => {
                let lbl = (el.getAttribute('aria-label') || '').toLowerCase();
                return (lbl.startsWith('tin nhắn do ') && lbl.includes(' gửi lúc ')) || /^lúc \\d{1,2}:\\d{2},.+:/.test(lbl);
              });
              let incoming = [];
              if (bubbles.length > 0) {
                for (let b of bubbles) {
                  let lbl = (b.getAttribute('aria-label') || '').toLowerCase();
                  let isOut = lbl.startsWith('tin nhắn do bạn') || /^lúc \\d{1,2}:\\d{2}, bạn:/.test(lbl);
                  if (!isOut) {
                    let txt = (b.innerText || '').trim();
                    if (txt && !incoming.includes(txt)) incoming.push(txt);
                  }
                }
              }
              if (incoming.length === 0) {
                let chatScope = main.querySelector('[role="grid"], [role="list"], [role="log"]') || main;
                let editables = Array.from(chatScope.querySelectorAll('[contenteditable="true"]'));
                let allAuto = Array.from(chatScope.querySelectorAll('div[dir="auto"], span[dir="auto"]'));
                let rows = allAuto.filter(el => {
                  if (el.closest('[role="navigation"], [role="complementary"], aside')) return false;
                  let txt = (el.innerText || '').trim();
                  if (!txt) return false;
                  if (editables.some(ed => ed.contains(el))) return false;
                  return true;
                });
                for (let r of rows) {
                  let txt = (r.innerText || '').trim();
                  let lower = txt.toLowerCase();
                  if (lower.includes('mã hóa đầu cuối') || lower.includes('tìm hiểu thêm') || lower.includes('nếu bạn chấp nhận')) continue;
                  if (lower.includes('tiểu bảo bảo') || lower.includes('trợ lý ai của anh mạnh') || lower.includes('trợ lí của mạnh')) continue;
                  if (!incoming.includes(txt)) incoming.push(txt);
                }
              }
              return incoming.slice(-10);
            }
            """
            result = await page.evaluate(script)
            if isinstance(result, list):
                return [str(s).strip() for s in result if s and str(s).strip()]
        except Exception as e:
            logger.warning("[FB-Service] Error evaluating incoming messages: %s", e)
        return []

    async def _count_unread_badge(self, page: Page) -> int:
        """Reads the unread message badge count visible in the page title or header.

        Facebook shows 'N tin nhắn chưa đọc' or '(N) ...' in page title when there
        are unread messages. We use this as a signal instead of message count.
        """
        try:
            title = await page.title()
            # Pattern: "(5) Trần Văn Mạnh | Messenger"
            if title and title.startswith("("):
                count_str = title[1:title.index(")")] if ")" in title else "0"
                return int(count_str) if count_str.isdigit() else 0
        except Exception:
            pass
        return 0

    async def _send_message_in_open_chat(self, page: Page, text: str) -> bool:
        """Types and submits a reply message in the currently active chat window.

        Uses JavaScript focus + keyboard.type instead of click() to avoid failures
        when Facebook shows overlays (e.g. E2EE upgrade prompts) that intercept
        pointer events on the input box.
        """
        try:
            # Wait for the textbox to be present in DOM
            await page.wait_for_selector(
                "[role='main'] [contenteditable='true'][role='textbox'], "
                "[contenteditable='true'][aria-label*='Tin nhắn'], "
                "[contenteditable='true'][role='textbox']",
                timeout=8000,
            )
            # Focus via JavaScript to bypass any overlay intercepting pointer events
            focused = await page.evaluate("""
            () => {
              let box = document.querySelector("[role='main'] [contenteditable='true'][role='textbox']") ||
                        document.querySelector("[contenteditable='true'][aria-label*='Tin nh\u1eafn']") ||
                        document.querySelector("[contenteditable='true'][role='textbox']");
              if (box) { box.focus(); return true; }
              return false;
            }
            """)
            if not focused:
                return False
            await asyncio.sleep(0.3)
            await page.keyboard.type(text, delay=25)
            await asyncio.sleep(0.3)
            await page.keyboard.press("Enter")
            await asyncio.sleep(1.5)
            return True
        except Exception as e:
            logger.warning("[FB-Service] Failed to send message in chat: %s", e)
            return False

    async def _sidebar_thread_links(self, page: Page) -> List[Dict[str, str]]:
        """Attempts to extract thread links from the sidebar.

        Falls back gracefully to empty list when E2EE sidebar cannot render.
        """
        try:
            result = await page.evaluate("""
            () => {
              let links = Array.from(document.querySelectorAll('a[href*="/messages/t/"], a[href*="/messages/e2ee/t/"]'));
              let seen = new Set();
              let items = [];
              for (let a of links) {
                let href = a.href;
                if (!href || href.includes('/messages/new/')) continue;
                let cleanHref = href.split('?')[0];
                if (seen.has(cleanHref)) continue;
                seen.add(cleanHref);
                items.push({ href: cleanHref, text: (a.innerText || '').substring(0, 80) });
              }
              return items;
            }
            """)
            if isinstance(result, list):
                return result
        except Exception as e:
            logger.debug("[FB-Service] Sidebar link extraction failed: %s", e)
        return []

    # ─── Main scan cycle ──────────────────────────────────────────────────────

    async def run_scan_cycle(self) -> int:
        """Executes one complete scan cycle across all known Messenger threads.

        Strategy (fixes E2EE headless sidebar issue):
        1. Use persistent browser context so E2EE keys survive between scans.
        2. Navigate to inbox — capture the redirect URL (= most-recent thread).
        3. Discover threads from: redirect URL + DB known threads + sidebar (if available).
        4. Visit each thread directly, extract messages, auto-reply if threshold met.
        5. Persist newly discovered thread URLs to DB for future scans.
        """
        if self._is_scanning:
            logger.info("[FB-Service] Scan cycle already in progress; skipping.")
            return 0

        async with self._lock:
            self._is_scanning = True
            self._last_scan_status = "scanning"

        auto_replies_sent = 0
        try:
            cfg = await self.get_config_from_db()
            if not cfg.get("enabled", False):
                self._last_scan_status = "disabled"
                return 0

            cookies = self._parse_cookies(cfg.get("cookies_json", ""))
            if not cookies:
                logger.warning("[FB-Service] No valid cookies found. Please configure Facebook cookies.")
                self._last_scan_status = "no_cookies"
                return 0

            # Ensure persistent browser data directory exists
            browser_data_path = Path(BROWSER_DATA_DIR)
            browser_data_path.mkdir(parents=True, exist_ok=True)

            async with async_playwright() as p:
                # Persistent context is critical: preserves E2EE IndexedDB keys
                # between scan cycles so that E2EE conversations load properly.
                ctx: BrowserContext = await p.chromium.launch_persistent_context(
                    str(browser_data_path),
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        # Prevents Facebook from detecting automation and restricting rendering
                        "--disable-blink-features=AutomationControlled",
                    ],
                    viewport={"width": 1280, "height": 800},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
                )

                # Re-inject cookies on every run to keep session fresh
                try:
                    await ctx.add_cookies(cast(Any, cookies))
                except Exception as e:
                    logger.debug("[FB-Service] Cookie injection warning (non-fatal): %s", e)

                page: Page = await ctx.new_page()

                try:
                    logger.info("[FB-Service] Navigating to Messenger inbox...")
                    await page.goto(
                        "https://www.facebook.com/messages/t/",
                        wait_until="domcontentloaded",
                        timeout=25000,
                    )
                    await asyncio.sleep(5.0)
                    await self._handle_e2ee_pin_screen(page)

                    # ─── Thread Discovery ─────────────────────────────────────
                    # Build the thread list WITHOUT relying solely on the sidebar.
                    threads_to_check: List[Dict[str, str]] = []
                    seen_hrefs: set = set()

                    def _add_thread(href: str, text: str = "") -> None:
                        clean = href.split("?")[0]
                        if clean and clean not in seen_hrefs and (
                            "/messages/t/" in clean or "/messages/e2ee/t/" in clean
                        ):
                            seen_hrefs.add(clean)
                            threads_to_check.append({"href": clean, "text": text})

                    # 1) Capture redirect URL — this is the most recently active thread
                    current_url = page.url
                    if "/messages/t/" in current_url or "/messages/e2ee/t/" in current_url:
                        logger.info("[FB-Service] Captured redirect thread: %s", current_url)
                        _add_thread(current_url)

                    # 2) Previously known threads from DB (discovered in past scans)
                    db_threads = await self.get_known_threads_from_db()
                    for t in db_threads:
                        _add_thread(t["href"], t.get("text", ""))

                    # 3) Sidebar links (works when E2EE context is fully initialized)
                    sidebar_threads = await self._sidebar_thread_links(page)
                    if sidebar_threads:
                        logger.info("[FB-Service] Sidebar returned %d threads.", len(sidebar_threads))
                        for t in sidebar_threads[:5]:
                            _add_thread(t.get("href", ""), t.get("text", ""))

                    logger.info("[FB-Service] Total threads to check: %d", len(threads_to_check))

                    # ─── Process Each Thread ──────────────────────────────────
                    for item in threads_to_check[:6]:
                        t_href = item.get("href", "")
                        if not t_href:
                            continue
                        try:
                            logger.info("[FB-Service] Checking thread: %s", t_href)
                            await page.goto(t_href, wait_until="domcontentloaded", timeout=15000)
                            # Wait for message input box to confirm chat is loaded
                            try:
                                await page.wait_for_selector(
                                    "[contenteditable='true'][role='textbox']",
                                    timeout=8000,
                                )
                            except Exception:
                                pass
                            await asyncio.sleep(3.0)
                            await self._handle_e2ee_pin_screen(page)

                            # Always extract sender name from page title (most reliable source).
                            # Sidebar text may include last message preview which pollutes the name.
                            clean_name = await self._extract_thread_name_from_page(page)

                            # Persist this thread URL so we can check it next time
                            await self.save_known_thread(t_href, clean_name)

                            # Detect unread count from page title
                            unread_count = await self._count_unread_badge(page)

                            # Extract incoming messages from conversation view
                            incoming_msgs = await self._extract_incoming_messages(page)
                            threshold = cfg.get("threshold", 3)

                            logger.info(
                                "[FB-Service] Thread '%s': %d incoming msgs, %d unread badge, threshold=%d",
                                clean_name, len(incoming_msgs), unread_count, threshold,
                            )

                            # Trigger auto-reply:
                            # - Primary: ANY unread message (unread_count > 0) means someone is waiting
                            # - Fallback: enough extracted messages meet the threshold
                            # The cooldown prevents spamming the same sender.
                            should_reply = unread_count > 0 or len(incoming_msgs) >= threshold
                            if should_reply:
                                in_cooldown = await self.is_sender_in_cooldown(clean_name, cfg.get("cooldown_minutes", 15))
                                if not in_cooldown:
                                    away_reply = (
                                        f"Chào bạn, tôi là Tiểu Bảo Bảo - trợ lí AI của anh Mạnh (Cua). "
                                        f"Anh Mạnh hiện đang vắng mặt và đã nhận được tin nhắn của bạn. "
                                        f"Tôi sẽ báo lại anh ấy ngay khi online nhé!"
                                    )
                                    sent = await self._send_message_in_open_chat(page, away_reply)
                                    if sent:
                                        auto_replies_sent += 1
                                        await self.record_sender_cooldown(clean_name)
                                        await self.message_cache.add_or_update(
                                            clean_name, incoming_msgs, away_reply, t_href, True
                                        )
                                        logger.info("[FB-Service] AUTO-REPLIED to '%s'", clean_name)
                                        continue
                                else:
                                    logger.info("[FB-Service] '%s' is in cooldown; skipping reply.", clean_name)

                            # Update cache without reply
                            await self.message_cache.add_or_update(
                                clean_name, incoming_msgs, None, t_href, False
                            )

                        except Exception as thread_err:
                            logger.warning("[FB-Service] Error processing thread %s: %s", t_href, thread_err)

                    await self.message_cache.mark_scan_completed()
                    self._last_scan_status = f"success ({auto_replies_sent} replies sent)"

                finally:
                    await page.close()
                    await ctx.close()

        except Exception as e:
            logger.error("[FB-Service] Scan cycle error: %s", e, exc_info=True)
            self._last_scan_status = f"error: {e}"
        finally:
            async with self._lock:
                self._is_scanning = False

        return auto_replies_sent

    # ─── Direct reply ─────────────────────────────────────────────────────────

    async def send_direct_reply(self, recipient_name: str, message: str) -> str:
        """Opens a conversation and sends a direct reply message."""
        if not recipient_name or not message:
            return "Lỗi: Thiếu tên người nhận hoặc nội dung tin nhắn."

        cfg = await self.get_config_from_db()
        cookies = self._parse_cookies(cfg.get("cookies_json", ""))
        if not cookies:
            return "Lỗi: Chưa cấu hình Cookies Facebook trên hệ thống."

        target_href = await self.message_cache.find_thread_href(recipient_name)
        # Also check DB if cache doesn't have it
        if not target_href:
            db_threads = await self.get_known_threads_from_db()
            for t in db_threads:
                if recipient_name.lower() in t.get("text", "").lower():
                    target_href = t["href"]
                    break

        browser_data_path = Path(BROWSER_DATA_DIR)
        browser_data_path.mkdir(parents=True, exist_ok=True)

        try:
            async with async_playwright() as p:
                ctx: BrowserContext = await p.chromium.launch_persistent_context(
                    str(browser_data_path),
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
                    viewport={"width": 1280, "height": 800},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
                )
                try:
                    await ctx.add_cookies(cast(Any, cookies))
                except Exception:
                    pass

                page: Page = await ctx.new_page()
                try:
                    if target_href:
                        logger.info("[FB-DirectReply] Navigating directly to: %s", target_href)
                        await page.goto(target_href, wait_until="domcontentloaded", timeout=18000)
                    else:
                        logger.info("[FB-DirectReply] Navigating to inbox to find '%s'...", recipient_name)
                        await page.goto(
                            "https://www.facebook.com/messages/t/",
                            wait_until="domcontentloaded",
                            timeout=20000,
                        )

                    await asyncio.sleep(3.0)
                    await self._handle_e2ee_pin_screen(page)

                    sent = await self._send_message_in_open_chat(page, message)
                    if sent:
                        await self.message_cache.record_direct_reply(recipient_name, message)
                        logger.info("[FB-DirectReply] SENT to '%s': %s", recipient_name, message)
                        return f'Đã gửi tin nhắn cho "{recipient_name}": "{message}"'
                    else:
                        return f'Tìm thấy hội thoại với "{recipient_name}" nhưng không gõ được tin nhắn.'

                finally:
                    await page.close()
                    await ctx.close()

        except Exception as e:
            logger.error("[FB-DirectReply] Error sending to '%s': %s", recipient_name, e)
            return f'Lỗi khi gửi tin nhắn cho "{recipient_name}": {e}'
