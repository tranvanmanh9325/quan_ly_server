import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
import psycopg
from psycopg.rows import dict_row
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from app.config import settings
from app.services.message_cache import FacebookMessageCache

logger = logging.getLogger(__name__)
VN_TZ = timezone(timedelta(hours=7))


class FacebookService:
    def __init__(self, message_cache: FacebookMessageCache, ai_agent_ref: Any = None):
        self.message_cache = message_cache
        self.ai_agent = ai_agent_ref  # Set after initialization to avoid circular reference
        self._is_scanning = False
        self._last_scan_status = "idle"
        self._lock = asyncio.Lock()

    def set_ai_agent(self, ai_agent: Any) -> None:
        self.ai_agent = ai_agent

    async def get_config_from_db(self) -> Dict[str, Any]:
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url, row_factory=dict_row) as conn:
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
            "enabled": False,
            "threshold": 3,
            "cookies_json": "[]",
            "custom_message": "",
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
                        raw_same_site = str(c.get("sameSite", "Lax") or "Lax").lower()
                        if "strict" in raw_same_site:
                            same_site = "Strict"
                        elif "none" in raw_same_site or "no_restriction" in raw_same_site:
                            same_site = "None"
                        else:
                            same_site = "Lax"

                        cookies.append({
                            "name": name,
                            "value": value,
                            "domain": domain,
                            "path": path,
                            "secure": bool(c.get("secure", True)),
                            "httpOnly": bool(c.get("httpOnly", False)),
                            "sameSite": same_site,
                        })
            return cookies
        except Exception as e:
            logger.error("[FB-Service] Failed to parse cookies JSON: %s", e)
            return []

    async def _handle_e2ee_pin_screen(self, page: Page) -> bool:
        """Handles Facebook's 6-digit end-to-end encryption PIN screen if it appears."""
        try:
            pin_inputs = await page.query_selector_all("input[type='password'], input[maxlength='1'], input[inputmode='numeric']")
            if len(pin_inputs) == 6 or len(pin_inputs) == 1:
                logger.info("[FB-Service] E2EE PIN screen detected. Unlocking...")
                pin = "090305"
                if len(pin_inputs) == 6:
                    for i, digit in enumerate(pin):
                        await pin_inputs[i].fill(digit)
                        await asyncio.sleep(0.1)
                else:
                    await pin_inputs[0].fill(pin)

                await asyncio.sleep(1.0)
                submit_btn = await page.query_selector("button[type='submit'], [aria-label*='Tiếp tục'], [aria-label*='Continue']")
                if submit_btn:
                    await submit_btn.click()
                    await asyncio.sleep(3.0)
                return True
        except Exception as e:
            logger.warning("[FB-Service] Error handling E2EE PIN screen: %s", e)
        return False

    async def _extract_incoming_messages(self, page: Page) -> List[str]:
        """Extracts genuine incoming messages sent by the contact, filtering out outgoing messages and bot prefixes."""
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

    async def _send_message_in_open_chat(self, page: Page, text: str) -> bool:
        """Types and submits a reply message in the currently active chat window."""
        try:
            input_box = await page.wait_for_selector(
                "[role='main'] [contenteditable='true'][role='textbox'], [contenteditable='true'][aria-label*='Tin nhắn'], [contenteditable='true'][role='textbox']",
                timeout=8000,
            )
            if not input_box:
                return False

            await input_box.click()
            await asyncio.sleep(0.3)
            # Fill or type text into message box
            await page.keyboard.type(text, delay=25)
            await asyncio.sleep(0.3)
            await page.keyboard.press("Enter")
            await asyncio.sleep(1.0)
            return True
        except Exception as e:
            logger.warning("[FB-Service] Failed to send message in chat: %s", e)
            return False

    async def run_scan_cycle(self) -> int:
        """Executes one scan cycle: checks active threads, extracts incoming messages, sends auto-replies if threshold met."""
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

            async with async_playwright() as p:
                browser: Browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
                context: BrowserContext = await browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
                )
                await context.add_cookies(cookies)
                page: Page = await context.new_page()

                try:
                    logger.info("[FB-Service] Navigating to Messenger inbox...")
                    await page.goto("https://www.facebook.com/messages/t/", wait_until="domcontentloaded", timeout=25000)
                    await asyncio.sleep(3.0)
                    await self._handle_e2ee_pin_screen(page)

                    # Extract threads from sidebar
                    thread_links = await page.evaluate("""
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

                    logger.info("[FB-Service] Discovered %d threads in sidebar.", len(thread_links or []))

                    for item in (thread_links or [])[:5]:
                        t_href = item.get("href")
                        t_text = item.get("text", "")

                        if not t_href:
                            continue

                        # Extract name
                        clean_name = t_text.split("\n")[0].strip()
                        if "Bạn:" in clean_name or "bạn:" in clean_name:
                            clean_name = clean_name.split("Bạn:")[0].split("bạn:")[0].strip()

                        if not clean_name:
                            clean_name = "Người dùng Facebook"

                        # Navigate to thread
                        try:
                            await page.goto(t_href, wait_until="domcontentloaded", timeout=15000)
                            await asyncio.sleep(2.0)
                            await self._handle_e2ee_pin_screen(page)

                            # Extract incoming messages
                            incoming_msgs = await self._extract_incoming_messages(page)
                            threshold = cfg.get("threshold", 3)

                            # Check if threshold met and not in cooldown
                            if len(incoming_msgs) >= threshold:
                                in_cooldown = await self.is_sender_in_cooldown(clean_name, cfg.get("cooldown_minutes", 15))
                                if not in_cooldown:
                                    # Generate away message
                                    away_reply = (
                                        f"Chào bạn, tôi là Tiểu Bảo Bảo - trợ lí AI của anh Mạnh (Cua). "
                                        f"Anh Mạnh hiện đang vắng mặt và đã nhận được {len(incoming_msgs)} tin nhắn của bạn. "
                                        f"Tôi sẽ báo lại anh ấy ngay khi online nhé!"
                                    )
                                    sent = await self._send_message_in_open_chat(page, away_reply)
                                    if sent:
                                        auto_replies_sent += 1
                                        await self.record_sender_cooldown(clean_name)
                                        await self.message_cache.add_or_update(
                                            clean_name, incoming_msgs, away_reply, t_href, True
                                        )
                                        logger.info("[FB-Service] AUTO-REPLIED to '%s': %s", clean_name, away_reply)
                                        continue

                            # Update cache without reply
                            await self.message_cache.add_or_update(
                                clean_name, incoming_msgs, None, t_href, False
                            )

                        except Exception as thread_err:
                            logger.warning("[FB-Service] Error inspecting thread %s: %s", t_href, thread_err)

                    await self.message_cache.mark_scan_completed()
                    self._last_scan_status = f"success ({auto_replies_sent} replies sent)"

                finally:
                    await context.close()
                    await browser.close()

        except Exception as e:
            logger.error("[FB-Service] Scan cycle error: %s", e, exc_info=True)
            self._last_scan_status = f"error: {e}"
        finally:
            async with self._lock:
                self._is_scanning = False

        return auto_replies_sent

    async def send_direct_reply(self, recipient_name: str, message: str) -> str:
        """Opens a conversation and sends a direct reply message."""
        if not recipient_name or not message:
            return "Lỗi: Thiếu tên người nhận hoặc nội dung tin nhắn."

        cfg = await self.get_config_from_db()
        cookies = self._parse_cookies(cfg.get("cookies_json", ""))
        if not cookies:
            return "Lỗi: Chưa cấu hình Cookies Facebook trên hệ thống."

        target_href = await self.message_cache.find_thread_href(recipient_name)

        try:
            async with async_playwright() as p:
                browser: Browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
                context: BrowserContext = await browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
                )
                await context.add_cookies(cookies)
                page: Page = await context.new_page()

                try:
                    if target_href:
                        logger.info("[FB-DirectReply] Navigating directly to cached thread: %s", target_href)
                        await page.goto(target_href, wait_until="domcontentloaded", timeout=18000)
                    else:
                        logger.info("[FB-DirectReply] Navigating to inbox to find '%s'...", recipient_name)
                        await page.goto("https://www.facebook.com/messages/t/", wait_until="domcontentloaded", timeout=20000)

                    await asyncio.sleep(2.0)
                    await self._handle_e2ee_pin_screen(page)

                    sent = await self._send_message_in_open_chat(page, message)
                    if sent:
                        await self.message_cache.record_direct_reply(recipient_name, message)
                        logger.info("[FB-DirectReply] SENT to '%s': %s", recipient_name, message)
                        return f'Đã gửi tin nhắn cho "{recipient_name}": "{message}"'
                    else:
                        return f'Tìm thấy hội thoại với "{recipient_name}" nhưng không gõ được tin nhắn.'

                finally:
                    await context.close()
                    await browser.close()

        except Exception as e:
            logger.error("[FB-DirectReply] Error sending to '%s': %s", recipient_name, e)
            return f'Lỗi khi gửi tin nhắn cho "{recipient_name}": {e}'
