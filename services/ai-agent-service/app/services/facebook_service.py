import asyncio
import hashlib
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
        # Single global mutex lock for all Playwright browser operations on BROWSER_DATA_DIR.
        # This strictly prevents race conditions, browser profile corruption, and goto timeouts.
        self._browser_lock = asyncio.Lock()

    def set_ai_agent(self, ai_agent: Any) -> None:
        self.ai_agent = ai_agent

    @staticmethod
    def _normalize_vn_text(text: str) -> str:
        if not text:
            return ""
        import unicodedata
        import re
        nfkd = unicodedata.normalize("NFKD", text.lower())
        no_marks = "".join(c for c in nfkd if not unicodedata.combining(c))
        no_marks = no_marks.replace("đ", "d").replace("Đ", "D")
        cleaned = re.sub(r"[^a-z0-9\s]", " ", no_marks)
        return " ".join(cleaned.split())

    @classmethod
    def _name_match_score(cls, name1: str, name2: str) -> float:
        n1 = cls._normalize_vn_text(name1)
        n2 = cls._normalize_vn_text(name2)
        if not n1 or not n2:
            return 0.0
        if n1 == n2:
            return 1.0
        if n1 in n2 or n2 in n1:
            return 0.9
        tokens1 = set(n1.split())
        tokens2 = set(n2.split())
        if not tokens1 or not tokens2:
            return 0.0
        overlap = len(tokens1.intersection(tokens2))
        return overlap / max(len(tokens1), len(tokens2))

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
        """Returns all known thread URLs with their last message hash."""
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url, row_factory=cast(Any, dict_row)) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT thread_href, sender_name, last_msg_hash FROM facebook_known_threads ORDER BY discovered_at DESC LIMIT 20"
                    )
                    rows = await cur.fetchall()
                    return [{
                        "href": row["thread_href"],
                        "text": row["sender_name"],
                        "last_msg_hash": row["last_msg_hash"] or "",
                    } for row in rows]
        except Exception as e:
            logger.warning("[FB-Service] Error fetching known threads: %s", e)
        return []

    async def save_known_thread(self, href: str, sender_name: str, msg_hash: str = "") -> None:
        """Persists a discovered thread URL and its latest message hash.

        The msg_hash allows the scanner to detect whether new messages have arrived
        since the last scan — preventing re-replies when message content is unchanged.
        """
        if not href:
            return
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        INSERT INTO facebook_known_threads (thread_href, sender_name, last_msg_hash, last_checked_at, discovered_at)
                        VALUES (%s, %s, %s, NOW(), NOW())
                        ON CONFLICT (thread_href) DO UPDATE SET
                            sender_name = EXCLUDED.sender_name,
                            last_msg_hash = EXCLUDED.last_msg_hash,
                            last_checked_at = NOW()
                        """,
                        (href.split("?")[0], sender_name, msg_hash),
                    )
                    await conn.commit()
        except Exception as e:
            logger.warning("[FB-Service] Error saving known thread: %s", e)

    @staticmethod
    def _compute_msg_hash(messages: List[str]) -> str:
        """Computes a stable hash of message content to detect changes between scans."""
        combined = "|".join(sorted(messages))  # sorted for stability regardless of extraction order
        return hashlib.sha256(combined.encode()).hexdigest()[:16]

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
        """Handles Facebook's 6-digit E2EE PIN screen if it appears.

        Detects both standard inputs and custom React dash boxes, types 090325,
        waits for decryption, and automatically dismisses the modal.
        """
        try:
            # 1. Check if PIN screen is present by text or input elements
            has_pin_dialog = await page.evaluate("""
            () => {
                let txt = (document.body.innerText || '');
                return txt.includes('Nhập mã PIN') || txt.includes('khôi phục đoạn chat') || 
                       txt.includes('khôi phục lịch sử') || txt.includes('mã PIN') || 
                       txt.includes('Enter PIN') || txt.includes('restore your chat');
            }
            """)

            pin_inputs = await page.query_selector_all(
                "input[type='password'], input[maxlength='1'], input[inputmode='numeric']"
            )

            if not has_pin_dialog and len(pin_inputs) not in (1, 6):
                return False

            logger.info("[FB-Service] E2EE PIN screen detected. Unlocking with PIN 090325...")
            pin = "090325"

            # 2. Fill standard inputs if found
            if len(pin_inputs) == 6:
                for i, digit in enumerate(pin):
                    await pin_inputs[i].fill(digit)
                    await asyncio.sleep(0.1)
            elif len(pin_inputs) == 1:
                await pin_inputs[0].fill(pin)
                await asyncio.sleep(0.1)

            # 3. Focus on PIN dialog container and simulate sequential keyboard typing
            await page.evaluate("""
            () => {
                let dialog = Array.from(document.querySelectorAll('div, [role="dialog"], [role="alertdialog"]')).find(d => {
                    let t = (d.innerText || '');
                    return t.includes('Nhập mã PIN') || t.includes('khôi phục đoạn chat');
                });
                if (dialog) {
                    let firstBox = dialog.querySelector('input, [tabindex], div:has(> span)') || dialog;
                    if (firstBox.click) firstBox.click();
                    if (firstBox.focus) firstBox.focus();
                }
            }
            """)
            await asyncio.sleep(0.3)

            for digit in pin:
                await page.keyboard.press(digit)
                await asyncio.sleep(0.15)

            # 4. Click Submit / Tiếp tục if present
            submit_btn = await page.query_selector(
                "button[type='submit'], [aria-label*='Tiếp tục'], [aria-label*='Continue'], div[role='button']:has-text('Tiếp tục')"
            )
            if submit_btn:
                try:
                    await submit_btn.click()
                except Exception:
                    pass

            # Wait for decryption
            await asyncio.sleep(4.0)

            # 5. Dismiss any remaining modal overlay by clicking Close (X) button
            await page.evaluate("""
            () => {
                let dialogs = Array.from(document.querySelectorAll('[role="dialog"], [role="alertdialog"], div')).filter(d => {
                    let t = (d.innerText || '');
                    return t.includes('Nhập mã PIN') || t.includes('khôi phục đoạn chat');
                });
                for (let d of dialogs) {
                    let closeBtn = d.querySelector('[aria-label="Đóng"], [aria-label="Close"], [aria-label="Huỷ"], svg');
                    if (closeBtn) {
                        let clickTarget = closeBtn.closest('div[role="button"], button') || closeBtn;
                        clickTarget.click();
                        return;
                    }
                }
            }
            """)
            await asyncio.sleep(1.5)

            # 6. If confirmation modal 'Tiếp tục mà không khôi phục?' appears, click 'Không khôi phục tin nhắn'
            await page.evaluate("""
            () => {
                let btns = Array.from(document.querySelectorAll('button, div[role="button"], span'));
                for (let b of btns) {
                    let txt = (b.innerText || '').trim();
                    if (txt === 'Không khôi phục tin nhắn' || txt === 'Continue without restoring') {
                        (b.closest('div[role="button"], button') || b).click();
                        return;
                    }
                }
            }
            """)
            await asyncio.sleep(1.0)

            # 7. Final fail-safe: remove any remaining PIN modal or full-screen overlay from DOM
            await page.evaluate("""
            () => {
                let all = Array.from(document.querySelectorAll('*')).filter(el => {
                    let t = el.innerText || '';
                    return (t.includes('Nhập mã PIN') || t.includes('khôi phục đoạn chat')) && el.parentElement;
                });
                for (let el of all) {
                    let modal = el.closest('[role="dialog"], [role="alertdialog"], div[style*="position: fixed"]');
                    if (modal) {
                        modal.remove();
                    } else if (el.style.position === 'fixed') {
                        el.remove();
                    }
                }
                let backdrops = document.querySelectorAll('div[style*="position: fixed"][style*="z-index"]');
                backdrops.forEach(b => b.remove());
            }
            """)
            await asyncio.sleep(0.5)
            return True

        except Exception as e:
            logger.warning("[FB-Service] Error handling E2EE PIN screen: %s", e)
            return False

    # Facebook UI labels that are NOT person names — used to filter bad extractions
    _FB_SYSTEM_LABELS = frozenset({
        "messenger", "facebook", "th\u00f4ng b\u00e1o", "\u0111\u01b0\u1ee3c m\u00e3 h\u00f3a \u0111\u1ea7u cu\u1ed1i",
        "m\u00e3 h\u00f3a \u0111\u1ea7u cu\u1ed1i", "ng\u01b0\u1eddi d\u00f9ng facebook", "\u0111o\u1ea1n chat",
        "tin nh\u1eafn", "so\u1ea1n", "m\u1edbi", "t\u00ecm ki\u1ebfm", "nh\u1eadp",
        "cu\u1ed9c tr\u00f2 chuy\u1ec7n", "c\u00e0i \u0111\u1eb7t", "quy\u1ec1n ri\u00eang t\u01b0",
    })

    async def _extract_thread_name_from_page(self, page: Page) -> str:
        """Extracts the conversation partner's name from the page header.

        Priority:
        1. h3 containing 'Cu\u1ed9c tr\u00f2 chuy\u1ec7n v\u1edbi X' (most reliable, FB accessibility label)
        2. First <a> in [role=main] that is a valid name
        3. Any h3 not in system labels blacklist
        4. Page title fallback
        """
        import re
        try:
            name_from_dom = await page.evaluate("""
            () => {
              // Priority 1: h3 with 'Cu\u1ed9c tr\u00f2 chuy\u1ec7n v\u1edbi X' — most reliable FB accessibility label
              let h3s = Array.from(document.querySelectorAll('h3'));
              for (let h of h3s) {
                let txt = (h.innerText || '').trim();
                let m = txt.match(/Cu\u1ed9c tr\u00f2 chuy\u1ec7n v\u1edbi (.+)/);
                if (m && m[1].trim().length > 1) return m[1].trim();
              }

              // Priority 2: <a> inside [role=main] — contact link in header
              let main = document.querySelector('[role="main"]') || document.body;
              let BLACKLIST = new Set([
                'messenger','facebook','th\u00f4ng b\u00e1o','\u0111\u01b0\u1ee3c m\u00e3 h\u00f3a \u0111\u1ea7u cu\u1ed1i',
                'm\u00e3 h\u00f3a \u0111\u1ea7u cu\u1ed1i','ng\u01b0\u1eddi d\u00f9ng facebook',
                '\u0111o\u1ea1n chat','tin nh\u1eafn','so\u1ea1n','m\u1edbi','t\u00ecm ki\u1ebfm',
              ]);
              for (let a of Array.from(main.querySelectorAll('a'))) {
                let txt = (a.innerText || '').trim();
                let low = txt.toLowerCase();
                if (txt.length > 1 && txt.length < 80 && !BLACKLIST.has(low)
                    && !low.includes('m\u00e3 h\u00f3a') && !low.includes('th\u00f4ng b\u00e1o')) {
                  return txt;
                }
              }

              // Priority 3: any h3 not matching system labels
              const LABEL_FRAGMENTS = [
                'tin nh\u1eafn','so\u1ea1n','\u0111o\u1ea1n chat','messenger','m\u00e3 h\u00f3a',
                'nh\u1eadp m\u00e3','kh\u00f4i ph\u1ee5c','c\u00e0i \u0111\u1eb7t','quy\u1ec1n ri\u00eang t\u01b0',
                'c\u00f3 th\u1ec3 b\u1ea1n bi\u1ebft','t\u00ecm ki\u1ebfm','th\u00f4ng b\u00e1o',
              ];
              for (let h of h3s) {
                let txt = (h.innerText || '').trim();
                let low = txt.toLowerCase();
                if (txt.length < 2 || txt.length > 80) continue;
                if (LABEL_FRAGMENTS.some(f => low.includes(f))) continue;
                return txt;
              }
              return '';
            }
            """)
            if name_from_dom:
                name_lower = name_from_dom.lower()
                is_system = any(label in name_lower for label in self._FB_SYSTEM_LABELS)
                if not is_system and len(name_from_dom) > 1:
                    return name_from_dom

            # Fallback: page title (format varies, rarely contains name now)
            title = await page.title()
            if title and "|" in title:
                name = title.split("|")[0].strip()
                name = re.sub(r"^\(\d+\)\s*", "", name).strip()
                name_lower = name.lower()
                if name and not any(label in name_lower for label in self._FB_SYSTEM_LABELS):
                    return name
        except Exception as e:
            logger.debug("[FB-Service] Could not extract thread name: %s", e)
        return "Ng\u01b0\u1eddi d\u00f9ng Facebook"

    async def _extract_conversation_state(self, page: Page) -> Dict[str, Any]:
        """Analyzes the current chat window in depth to determine:
        - last_sender: 'us' (if account owner or bot sent the last message) or 'them' (if incoming)
        - consecutive_unreplied_count: number of consecutive messages sent by the other party since our last message
        - incoming_msgs: list of incoming message texts from the other party
        - last_msg_text: text of the very last message in the thread
        """
        default_state: Dict[str, Any] = {
            "last_sender": "none",
            "consecutive_unreplied_count": 0,
            "incoming_msgs": [],
            "last_msg_text": "",
        }
        try:
            script = """
            () => {
              let main = document.querySelector('[role="main"]') || document.querySelector('[role="region"]') || document.body;

              // 1. Primary: Facebook Messenger embeds accessibility text in <span> elements
              // Formats:
              //   - 'Nhập, Tin nhắn do Bạn gửi lúc 17:11: Chào anh Mạnh...' (Us)
              //   - 'Nhập, Tin nhắn do Trần Văn Mạnh gửi lúc 17:32: sádas' (Them)
              let allSpans = Array.from(main.querySelectorAll('span'));
              let msgNodes = [];

              for (let s of allSpans) {
                let t = (s.innerText || s.textContent || '').trim();
                let low = t.toLowerCase();
                if (!low.includes('tin nhắn do') || !low.includes('gửi lúc')) continue;

                let isUs = low.includes('do bạn gửi') || low.includes('do bạn gởi');
                let colonIdx = t.lastIndexOf(':');
                let msgText = colonIdx >= 0 ? t.substring(colonIdx + 1).trim() : '';
                if (msgText) {
                  msgNodes.push({ sender: isUs ? 'us' : 'them', text: msgText });
                }
              }

              // 2. Fallback: scan aria-labels if spans were not rendered
              if (msgNodes.length === 0) {
                let allEls = Array.from(main.querySelectorAll('[aria-label]'));
                for (let el of allEls) {
                  let lbl = (el.getAttribute('aria-label') || '').trim();
                  let low = lbl.toLowerCase();
                  if (!low.includes('tin nhắn do') || !low.includes('gửi lúc')) continue;

                  let isUs = low.includes('do bạn gửi') || low.includes('do bạn gởi');
                  let colonIdx = lbl.lastIndexOf(':');
                  let msgText = colonIdx >= 0 ? lbl.substring(colonIdx + 1).trim() : '';
                  if (msgText) {
                    msgNodes.push({ sender: isUs ? 'us' : 'them', text: msgText });
                  }
                }
              }

              if (msgNodes.length === 0) {
                return { last_sender: 'none', consecutive_unreplied_count: 0, incoming_msgs: [], last_msg_text: '' };
              }

              let lastNode = msgNodes[msgNodes.length - 1];
              let unreplied = 0;
              let incoming = [];

              // Count backwards consecutive incoming messages from the other person
              for (let i = msgNodes.length - 1; i >= 0; i--) {
                if (msgNodes[i].sender === 'us') {
                  break;
                }
                unreplied++;
                incoming.unshift(msgNodes[i].text);
              }

              return {
                last_sender: lastNode.sender,
                consecutive_unreplied_count: unreplied,
                incoming_msgs: incoming.slice(-10),
                last_msg_text: lastNode.text
              };
            }
            """
            res = await page.evaluate(script)
            if isinstance(res, dict):
                return {
                    "last_sender": str(res.get("last_sender", "none")),
                    "consecutive_unreplied_count": int(res.get("consecutive_unreplied_count", 0)),
                    "incoming_msgs": [str(s).strip() for s in res.get("incoming_msgs", []) if s],
                    "last_msg_text": str(res.get("last_msg_text", "")),
                }
        except Exception as e:
            logger.warning("[FB-Service] Error evaluating conversation state: %s", e)
        return default_state

    async def _count_unread_badge(self, page: Page) -> int:
        """Reads the unread message badge count visible in the page title or header."""
        try:
            title = await page.title()
            if title and title.startswith("("):
                count_str = title[1:title.index(")")] if ")" in title else "0"
                return int(count_str) if count_str.isdigit() else 0
        except Exception:
            pass
        return 0
    async def _send_message_in_open_chat(self, page: Page, text: str) -> bool:
        """Types and submits a reply message in the currently active chat window.

        Uses resilient JavaScript element discovery + focus to bypass overlays
        and variations in Facebook Messenger's DOM structure.
        """
        try:
            # 0. Proactively clean up any modal overlays or PIN dialogs that may have appeared late
            await page.evaluate("""
            () => {
                // Find and remove all dialogs and overlays
                let dialogs = document.querySelectorAll('[role="dialog"], [role="alertdialog"], div[aria-modal="true"]');
                dialogs.forEach(d => {
                    let txt = d.innerText || '';
                    if (txt.includes('Nhập mã PIN') || txt.includes('khôi phục') || txt.includes('PIN')) {
                        d.remove();
                    }
                });
                // Remove fixed backdrops
                let backdrops = document.querySelectorAll('div[style*="position: fixed"][style*="z-index"]');
                backdrops.forEach(b => b.remove());
            }
            """)
            await asyncio.sleep(0.5)

            # 1. Wait for and focus on the message textbox (retry for up to 10s)
            focused = False
            for _ in range(10):
                # Clean up any recurring popup during loop
                await page.evaluate("""
                () => {
                    let dialogs = document.querySelectorAll('[role="dialog"], [role="alertdialog"], div[aria-modal="true"]');
                    dialogs.forEach(d => {
                        let txt = d.innerText || '';
                        if (txt.includes('Nhập mã PIN') || txt.includes('khôi phục') || txt.includes('PIN')) {
                            d.remove();
                        }
                    });
                    let backdrops = document.querySelectorAll('div[style*="position: fixed"][style*="z-index"]');
                    backdrops.forEach(b => b.remove());
                }
                """)
                focused = await page.evaluate("""
                () => {
                    let selectors = [
                        'div[role="textbox"][contenteditable="true"]',
                        'div[aria-placeholder="Aa"]',
                        'div[data-lexical-editor="true"]',
                        '[contenteditable="true"][aria-label*="Viết cho"]',
                        '[contenteditable="true"][aria-label*="Nhập"]',
                        '[contenteditable="true"][aria-label*="Tin nhắn"]',
                        '[role="main"] [contenteditable="true"]',
                        '[contenteditable="true"]',
                    ];
                    for (let sel of selectors) {
                        let elements = document.querySelectorAll(sel);
                        for (let el of elements) {
                            if (el.closest('[role="navigation"], [role="search"], aside')) continue;
                            if (el.offsetParent !== null || el.getClientRects().length > 0) {
                                el.focus();
                                el.click();
                                return true;
                            }
                        }
                    }
                    return false;
                }
                """)
                if focused:
                    break
                await asyncio.sleep(1.0)

            if not focused:
                logger.warning("[FB-Service] Could not find or focus message input box after 10s.")
                return False

            await asyncio.sleep(0.4)

            # 2. Clear any leftover draft text
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")
            await asyncio.sleep(0.2)

            # 3. Insert message content supporting full UTF-8, Emoji and Multiline
            try:
                # Playwright's insert_text natively dispatches InputEvent with exact UTF-8 / Emoji payload
                await page.keyboard.insert_text(text)
            except Exception as insert_err:
                logger.warning("[FB-Service] insert_text failed (%s), falling back to keyboard.type", insert_err)
                await page.keyboard.type(text, delay=20)
            await asyncio.sleep(0.6)

            # 4. Press Enter to send
            await page.keyboard.press("Enter")
            await asyncio.sleep(1.5)

            await page.evaluate("""
            () => {
                let btn = document.querySelector('[aria-label="Nhấn để gửi"], [aria-label="Press Enter to send"], [aria-label="Send"], svg[aria-label="Nhấn để gửi"]');
                if (btn) {
                    let clickable = btn.closest('div[role="button"], button') || btn;
                    clickable.click();
                }
            }
            """)
            await asyncio.sleep(2.0)
            logger.info("[FB-Service] Successfully submitted message to chat window.")
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

            async with self._browser_lock:
                async with async_playwright() as p:
                    # Persistent context is critical: preserves E2EE IndexedDB keys
                    # between scan cycles so that E2EE conversations load properly.
                    ctx: BrowserContext = await p.chromium.launch_persistent_context(
                        str(browser_data_path),
                        headless=True,
                        timezone_id="Asia/Ho_Chi_Minh",
                        locale="vi-VN",
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
                        try:
                            await page.goto(
                                "https://www.facebook.com/messages/t/",
                                wait_until="domcontentloaded",
                                timeout=25000,
                            )
                        except Exception as nav_e:
                            logger.warning("[FB-Service] Inbox navigation warning: %s", nav_e)

                        await asyncio.sleep(4.0)
                        await self._handle_e2ee_pin_screen(page)

                        # ─── Thread Discovery ─────────────────────────────────────
                        # Build the thread list WITHOUT relying solely on the sidebar.
                        # db_thread_map lets us look up the last known msg hash per URL.
                        threads_to_check: List[Dict[str, str]] = []
                        seen_hrefs: set = set()
                        db_threads = await self.get_known_threads_from_db()
                        db_thread_map: Dict[str, str] = {
                            t["href"].split("?")[0]: t.get("last_msg_hash", "")
                            for t in db_threads
                        }

                        def _add_thread(href: str, text: str = "") -> None:
                            clean = href.split("?")[0]
                            if clean and clean not in seen_hrefs and (
                                "/messages/t/" in clean or "/messages/e2ee/t/" in clean
                            ):
                                seen_hrefs.add(clean)
                                threads_to_check.append({"href": clean, "text": text})

                        # 1) Capture redirect URL — most recently active thread
                        current_url = page.url
                        if "/messages/t/" in current_url or "/messages/e2ee/t/" in current_url:
                            logger.info("[FB-Service] Captured redirect thread: %s", current_url)
                            _add_thread(current_url)

                        # 2) Previously known threads from DB
                        for t in db_threads:
                            _add_thread(t["href"], t.get("text", ""))

                        # 3) Sidebar links (works when persistent context is initialized)
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
                                is_e2ee = "/messages/e2ee/t/" in t_href
                                try:
                                    await page.goto(
                                        t_href,
                                        wait_until="domcontentloaded",
                                        timeout=20000 if is_e2ee else 15000,
                                    )
                                except Exception as nav_err:
                                    logger.warning("[FB-Service] Navigation timeout for %s: %s — skipping", t_href, nav_err)
                                    continue
                                # Wait for message input box to confirm chat is loaded
                                try:
                                    await page.wait_for_selector(
                                        "[contenteditable='true'][role='textbox']",
                                        timeout=8000,
                                    )
                                except Exception:
                                    pass
                                await asyncio.sleep(3.0)

                                # Handle E2EE PIN unlock if needed
                                pin_handled = await self._handle_e2ee_pin_screen(page)
                                if pin_handled:
                                    logger.info("[FB-Service] E2EE PIN unlocked for %s", t_href)

                                # Extract contact name from DOM header
                                clean_name = await self._extract_thread_name_from_page(page)

                                # Extract conversation state (who sent the last message, unreplied count)
                                conv_state = await self._extract_conversation_state(page)
                                last_sender = conv_state["last_sender"]
                                consecutive_unreplied = conv_state["consecutive_unreplied_count"]
                                incoming_msgs = conv_state["incoming_msgs"]
                                last_msg_text = conv_state["last_msg_text"]

                                # Compute hash to detect new messages since last scan
                                current_hash = self._compute_msg_hash(incoming_msgs) if incoming_msgs else ""
                                previous_hash = db_thread_map.get(t_href, "")
                                has_new_messages = (current_hash != previous_hash) and bool(incoming_msgs)

                                # Detect unread badge from page title as supplementary signal
                                unread_count = await self._count_unread_badge(page)

                                threshold = cfg.get("threshold", 5)
                                logger.info(
                                    "[FB-Service] Thread '%s': last_sender=%s, unreplied=%d, threshold=%d, new=%s, hash=%s",
                                    clean_name, last_sender, consecutive_unreplied, threshold, has_new_messages, current_hash[:8] if current_hash else "∅",
                                )

                                # Persist thread URL with updated hash
                                await self.save_known_thread(t_href, clean_name, current_hash)

                                # ── Auto-reply decision ──────────────────────────────────────
                                # 1. If the last message in the thread was sent by 'us' (account owner or bot):
                                #    The conversation is already replied to. NEVER send away message!
                                if last_sender == "us":
                                    logger.info("[FB-Service] '%s': last message is from us; no auto-reply needed.", clean_name)
                                    await self.message_cache.add_or_update(
                                        clean_name, incoming_msgs, "", t_href, True
                                    )
                                    continue

                                # 2. If 0 messages found or E2EE locked:
                                if not incoming_msgs:
                                    logger.info("[FB-Service] '%s': 0 readable incoming msgs; skip.", clean_name)
                                    continue

                                # 3. Update cache with latest incoming messages with unreplied status (False)
                                await self.message_cache.add_or_update(
                                    clean_name, incoming_msgs, "", t_href, False
                                )

                                # 4. Check if consecutive unreplied incoming messages reached threshold
                                if consecutive_unreplied < threshold:
                                    logger.info(
                                        "[FB-Service] '%s': unreplied count (%d) < threshold (%d); skip away message.",
                                        clean_name, consecutive_unreplied, threshold,
                                    )
                                    continue

                                # 5. If threshold reached, ensure this is a new message batch (not already replied)
                                if not has_new_messages:
                                    logger.info("[FB-Service] '%s': threshold met but already replied to this hash; skip.", clean_name)
                                    continue

                                cooldown_key = t_href
                                cooldown_minutes = cfg.get("cooldown_minutes", 2)
                                in_cooldown = await self.is_sender_in_cooldown(cooldown_key, cooldown_minutes)
                                if in_cooldown:
                                    logger.info(
                                        "[FB-Service] '%s': cooldown active (%dm); skip double-send.",
                                        clean_name, cooldown_minutes,
                                    )
                                    continue

                                # All criteria strictly met: send away message ONCE
                                away_reply = (
                                    f"Chào bạn, tôi là Tiểu Bảo Bảo - trợ lí AI của anh Mạnh (Cua). "
                                    f"Anh Mạnh hiện đang vắng mặt và đã nhận được tin nhắn của bạn. "
                                    f"Tôi sẽ báo lại anh ấy ngay khi online nhé!"
                                )
                                sent = await self._send_message_in_open_chat(page, away_reply)
                                if sent:
                                    auto_replies_sent += 1
                                    await self.record_sender_cooldown(cooldown_key)
                                    await self.message_cache.add_or_update(
                                        clean_name, incoming_msgs, away_reply, t_href, True
                                    )
                                    logger.info(
                                        "[FB-Service] AUTO-REPLIED to '%s' (unreplied=%d, hash %s→%s)",
                                        clean_name, consecutive_unreplied, previous_hash or "∅", current_hash,
                                    )
                                else:
                                    logger.warning("[FB-Service] Failed to send reply to '%s'", clean_name)

                                # Update cache ONLY when there are actual incoming messages to report.
                                # Threads with 0 readable messages (E2EE locked, PIN pending, etc.)
                                # should NOT appear in Telegram summaries as phantom entries.
                                if incoming_msgs:
                                    is_system_name = any(
                                        label in clean_name.lower() for label in self._FB_SYSTEM_LABELS
                                    )
                                    # Use a cleaned name: fallback to 'Người dùng Facebook' if system label
                                    display_name = clean_name if not is_system_name else "Người dùng Facebook"
                                    await self.message_cache.add_or_update(
                                        display_name, incoming_msgs, None, t_href, False
                                    )
                                else:
                                    logger.debug(
                                        "[FB-Service] '%s': system label with no msgs — skipping cache.", clean_name
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
        """Opens a conversation and sends a direct reply message.

        Protected by the global _browser_lock to ensure only 1 Chromium instance
        runs at a time, preventing CPU overload and timeouts.
        Directly navigates to target thread URL for maximum speed.
        """
        if not recipient_name or not message:
            return "Lỗi: Thiếu tên người nhận hoặc nội dung tin nhắn."

        cfg = await self.get_config_from_db()
        cookies = self._parse_cookies(cfg.get("cookies_json", ""))
        if not cookies:
            return "Lỗi: Chưa cấu hình Cookies Facebook trên hệ thống."

        # 1. Look for thread_href in message_cache (fuzzy normalized)
        target_href = await self.message_cache.find_thread_href(recipient_name)

        # 2. If not found in cache, search in database known threads with fuzzy matching
        # Prioritize direct standard threads (/messages/t/) to avoid E2EE pending message queue
        if not target_href:
            db_threads = await self.get_known_threads_from_db()
            best_score = 0.0
            best_href = None
            for t in db_threads:
                score = self._name_match_score(recipient_name, t.get("text", ""))
                is_non_e2ee = "/messages/t/" in t["href"] and "/e2ee/" not in t["href"]
                # Give priority to standard direct delivery threads
                adjusted_score = score + (0.15 if is_non_e2ee else 0.0)
                if adjusted_score > best_score and score >= 0.4:
                    best_score = adjusted_score
                    best_href = t["href"]
            if best_href:
                target_href = best_href

        # 3. Fallback: if any thread exists in DB, prefer standard thread first
        if not target_href:
            db_threads = await self.get_known_threads_from_db()
            if db_threads:
                non_e2ee_threads = [t for t in db_threads if "/messages/t/" in t["href"] and "/e2ee/" not in t["href"]]
                target_href = non_e2ee_threads[0]["href"] if non_e2ee_threads else db_threads[0]["href"]
                logger.info("[FB-DirectReply] Fallback to primary known thread: %s", target_href)

        async def _execute_send() -> str:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
                ctx = await browser.new_context(
                    viewport={"width": 1280, "height": 850},
                    timezone_id="Asia/Ho_Chi_Minh",
                    locale="vi-VN",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
                )
                try:
                    await ctx.add_cookies(cast(Any, cookies))
                except Exception:
                    pass

                page = await ctx.new_page()
                try:
                    dest_url = target_href if target_href else "https://www.facebook.com/messages/t/"
                    logger.info("[FB-DirectReply] Navigating to: %s for '%s'...", dest_url, recipient_name)
                    try:
                        await page.goto(
                            dest_url,
                            wait_until="domcontentloaded",
                            timeout=35000,
                        )
                    except Exception as nav_e:
                        logger.warning("[FB-DirectReply] Navigation notice: %s", nav_e)

                    # Wait for React Messenger interface to fully hydrate
                    try:
                        await page.wait_for_selector('div[role="main"], div[role="textbox"], [contenteditable="true"]', timeout=20000)
                    except Exception:
                        pass

                    await asyncio.sleep(2.0)

                    # Handle PIN screen & dismiss any modal overlays
                    await self._handle_e2ee_pin_screen(page)
                    await asyncio.sleep(1.0)

                    # If on root inbox and thread was clicked, ensure open
                    if not target_href:
                        await page.evaluate("""
                        (name) => {
                            let norm = (s) => (s || '').toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g, '');
                            let target = norm(name);
                            let links = Array.from(document.querySelectorAll('a[href*="/messages/t/"], a[href*="/messages/e2ee/t/"]'));
                            for (let a of links) {
                                    let txt = norm(a.innerText || '');
                                    if (txt.includes(target) || target.includes(txt)) {
                                        a.click();
                                        return true;
                                    }
                            }
                            return false;
                        }
                        """, recipient_name)
                        await asyncio.sleep(3.0)
                        await self._handle_e2ee_pin_screen(page)

                    # Send the message
                    sent = await self._send_message_in_open_chat(page, message)
                    if sent:
                        # Wait 4 seconds to ensure WebSocket payload is acknowledged by Facebook servers
                        await asyncio.sleep(4.0)
                        # Save screenshot proof
                        try:
                            await page.screenshot(path="/tmp/last_direct_reply_proof.png")
                        except Exception:
                            pass

                        await self.message_cache.record_direct_reply(recipient_name, message)
                        actual_url = page.url.split("?")[0]
                        await self.record_sender_cooldown(actual_url)
                        logger.info("[FB-DirectReply] SENT to '%s': %s", recipient_name, message)
                        return f'Đã gửi tin nhắn cho "{recipient_name}": "{message}"'
                    else:
                        return f'Lỗi: Đã mở trang chat với "{recipient_name}" nhưng không thể gửi tin nhắn vào ô chat.'

                finally:
                    await page.close()
                    await ctx.close()
                    await browser.close()

        try:
            async with self._browser_lock:
                return await asyncio.wait_for(_execute_send(), timeout=120.0)
        except asyncio.TimeoutError:
            logger.error("[FB-DirectReply] Timeout sending to '%s'", recipient_name)
            return f'Lỗi: Hết thời gian chờ (120s) khi gửi tin nhắn cho "{recipient_name}". Vui lòng thử lại.'
        except Exception as e:
            logger.error("[FB-DirectReply] Error sending to '%s': %s", recipient_name, e)
            return f'Lỗi khi gửi tin nhắn cho "{recipient_name}": {e}'

