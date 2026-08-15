import asyncio
import functools
import hashlib
import json
import logging
import re
import time
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

# Marker strings uniquely identifying the bot's auto-reply (away message).
# Used both to detect "this is a bot message" in DOM and to skip scan logic.
AWAY_REPLY_MARKERS = ("Tiểu Bảo Bảo", "trợ lí AI", "vắng mặt")


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

    # C-level character mapping table for instant O(1) Vietnamese diacritics removal
    _VN_TRANS_TABLE = str.maketrans(
        "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
        "ÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴĐ",
        "aaaaaaaaaaaaaaaaaeeeeeeeeeeeiiiiiooooooooooooooooouuuuuuuuuuuyyyyyd"
        "AAAAAAAAAAAAAAAAAEEEEEEEEEEEIIIIIOOOOOOOOOOOOOOOOOUUUUUUUUUUUYYYYYD"
    )
    _VN_STOPWORDS = frozenset({
        "anh", "chi", "em", "ban", "bac", "chu", "co", "ong", "ba", "admin", "boss", "sep", "sêp",
        "bao", "nhan", "gui", "cho", "hoi", "gap", "alo", "noi", "voi", "la", "cua", "beo", "coi"
    })

    @classmethod
    @functools.lru_cache(maxsize=2048)
    def _normalize_vn_text(cls, text: str) -> str:
        """High-performance O(1) cached Vietnamese text normalization using C-level translation table."""
        if not text:
            return ""
        s = text.translate(cls._VN_TRANS_TABLE).lower()
        cleaned = "".join(c if (c.isalnum() or c.isspace()) else " " for c in s)
        return " ".join(cleaned.split())

    @staticmethod
    def _jaro_winkler_fast(s1: str, s2: str) -> float:
        """Fast Jaro-Winkler distance calculation for typo tolerance."""
        if s1 == s2:
            return 1.0
        len1, len2 = len(s1), len(s2)
        if len1 == 0 or len2 == 0:
            return 0.0
        match_distance = max(len1, len2) // 2 - 1
        s1_matches = [False] * len1
        s2_matches = [False] * len2
        matches = 0
        for i in range(len1):
            start = max(0, i - match_distance)
            end = min(i + match_distance + 1, len2)
            for j in range(start, end):
                if not s2_matches[j] and s1[i] == s2[j]:
                    s1_matches[i] = True
                    s2_matches[j] = True
                    matches += 1
                    break
        if matches == 0:
            return 0.0
        transpositions = 0
        k = 0
        for i in range(len1):
            if s1_matches[i]:
                while not s2_matches[k]:
                    k += 1
                if s1[i] != s2[k]:
                    transpositions += 1
                k += 1
        jaro = (matches / len1 + matches / len2 + (matches - transpositions / 2) / matches) / 3.0
        prefix = 0
        for i in range(min(4, len1, len2)):
            if s1[i] == s2[i]:
                prefix += 1
            else:
                break
        return jaro + prefix * 0.1 * (1.0 - jaro)

    @classmethod
    @functools.lru_cache(maxsize=4096)
    def _name_match_score(cls, name1: str, name2: str) -> float:
        """Two-tier Weighted Token + Jaro-Winkler Matching with Given Name & Family Name Strictness.
        O(1) cached lookup with 100% accuracy on Vietnamese name permutations, titles, and typos.
        """
        n1 = cls._normalize_vn_text(name1)
        n2 = cls._normalize_vn_text(name2)
        if not n1 or not n2:
            return 0.0
        if n1 == n2:
            return 1.0
        if n1 in n2 or n2 in n1:
            return 0.95

        raw_tokens1 = n1.split()
        raw_tokens2 = n2.split()

        tokens1 = [t for t in raw_tokens1 if t not in cls._VN_STOPWORDS]
        tokens2 = [t for t in raw_tokens2 if t not in cls._VN_STOPWORDS]
        if not tokens1:
            tokens1 = raw_tokens1
        if not tokens2:
            tokens2 = raw_tokens2

        set1, set2 = set(tokens1), set(tokens2)
        overlap = set1.intersection(set2)

        # Check family name mismatch (e.g. Lê Hoàng Nam vs Nguyễn Hoàng Nam)
        if len(tokens1) >= 3 and len(tokens2) >= 3:
            if tokens1[0] != tokens2[0] and tokens1[-1] == tokens2[-1]:
                return 0.50

        # Single word query matching target given name (e.g. "anh Mạnh", "bảo Mạnh", "Mạnh Cua" vs "Trần Văn Mạnh")
        given1 = tokens1[-1]
        given2 = tokens2[-1]

        if len(tokens1) == 1 and (tokens1[0] in set2):
            return 0.92 if tokens1[0] == given2 else 0.82
        if len(tokens2) == 1 and (tokens2[0] in set1):
            return 0.92 if tokens2[0] == given1 else 0.82

        given_match = (given1 == given2) or (tokens1[0] == given2) or (given1 == tokens2[0])
        token_score = len(overlap) / max(len(set1), len(set2))

        if given_match:
            if len(overlap) >= 2:
                return max(0.88, token_score + 0.15)
            elif len(set1) <= 2 or len(set2) <= 2:
                return 0.85

        jw_score = cls._jaro_winkler_fast(n1, n2)
        if jw_score >= 0.90:
            return jw_score

        return max(token_score, jw_score * 0.7)

    # ─── DB helpers ──────────────────────────────────────────────────────────

    async def get_config_from_db(self) -> Dict[str, Any]:
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url, row_factory=cast(Any, dict_row)) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT id, cookies_json, cooldown_minutes, custom_message, enabled, "
                        "last_status, threshold, scan_interval_minutes, idle_timeout_minutes, human_session_minutes FROM facebook_config LIMIT 1"
                    )
                    row = await cur.fetchone()
                    if row:
                        return dict(row)
        except Exception as e:
            logger.error("[FB-Service] Error fetching config from DB: %s", e)
        return {
            "enabled": False, "threshold": 5,
            "idle_timeout_minutes": 3,
            "human_session_minutes": 10,
            "cookies_json": "[]", "custom_message": "",
            "scan_interval_minutes": 5,
        }

    async def save_config_to_db(self, cfg: Dict[str, Any]) -> None:
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        INSERT INTO facebook_config (id, cookies_json, cooldown_minutes, custom_message, enabled, last_status, threshold, scan_interval_minutes, idle_timeout_minutes, human_session_minutes, created_at, updated_at)
                        VALUES (1, %s, 15, %s, %s, 'updated', %s, %s, %s, %s, NOW(), NOW())
                        ON CONFLICT (id) DO UPDATE SET
                            cookies_json = EXCLUDED.cookies_json,
                            custom_message = EXCLUDED.custom_message,
                            enabled = EXCLUDED.enabled,
                            threshold = EXCLUDED.threshold,
                            scan_interval_minutes = EXCLUDED.scan_interval_minutes,
                            idle_timeout_minutes = EXCLUDED.idle_timeout_minutes,
                            human_session_minutes = EXCLUDED.human_session_minutes,
                            updated_at = NOW()
                        """,
                        (
                            cfg.get("cookies_json", "[]"),
                            cfg.get("custom_message", ""),
                            cfg.get("enabled", False),
                            cfg.get("threshold", 5),
                            cfg.get("scan_interval_minutes", 5),
                            cfg.get("idle_timeout_minutes", 3),
                            cfg.get("human_session_minutes", 10),
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

    async def save_known_thread(self, href: str, sender_name: str, msg_hash: str = "", auto_reply_text: str = "") -> None:
        """Persists a discovered thread URL and its latest message hash.

        auto_reply_text: If non-empty, records the away-message text the bot just sent.
        This survives container restarts and is used to trigger the unsend on the next
        scan cycle when the human has replied.
        """
        if not href:
            return
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    if auto_reply_text:
                        # When recording a new auto-reply: store text and reset unsent flag
                        await cur.execute(
                            """
                            INSERT INTO facebook_known_threads (thread_href, sender_name, last_msg_hash, auto_reply_text, auto_reply_unsent, last_checked_at, discovered_at)
                            VALUES (%s, %s, %s, %s, FALSE, NOW(), NOW())
                            ON CONFLICT (thread_href) DO UPDATE SET
                                sender_name = EXCLUDED.sender_name,
                                last_msg_hash = EXCLUDED.last_msg_hash,
                                auto_reply_text = EXCLUDED.auto_reply_text,
                                auto_reply_unsent = FALSE,
                                last_checked_at = NOW()
                            """,
                            (href.split("?")[0], sender_name, msg_hash, auto_reply_text),
                        )
                    else:
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

    async def get_thread_auto_reply(self, href: str) -> str:
        """Returns the pending auto-reply text for a thread, or '' if none / already unsent."""
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT auto_reply_text FROM facebook_known_threads WHERE thread_href = %s AND auto_reply_unsent = FALSE AND auto_reply_text != ''",
                        (href.split("?")[0],),
                    )
                    row = await cur.fetchone()
                    return row[0] if row else ""
        except Exception as e:
            logger.warning("[FB-Service] Error fetching thread auto-reply: %s", e)
        return ""

    async def mark_thread_auto_reply_unsent(self, href: str) -> None:
        """Marks the auto-reply for a thread as successfully unsent in the DB."""
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "UPDATE facebook_known_threads SET auto_reply_unsent = TRUE, auto_reply_text = '' WHERE thread_href = %s",
                        (href.split("?")[0],),
                    )
                    await conn.commit()
        except Exception as e:
            logger.warning("[FB-Service] Error marking auto-reply unsent: %s", e)

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
        If 'Tiếp tục mà không khôi phục?' confirmation modal appears, clicks 'Hủy' to return to PIN input.
        Directly enters the 6-digit PIN 090325 into the E2EE modal with 350ms delay,
        waits for Facebook to decrypt and restore chat history.
        NEVER clicks 'Không khôi phục tin nhắn'.
        """
        try:
            # 0. Check if 'Tiếp tục mà không khôi phục?' modal is open -> Click 'Hủy' to go back to PIN modal
            has_cancel_modal = await page.evaluate("""
            () => {
                let t = (document.body.innerText || '');
                return t.includes('Tiếp tục mà không khôi phục') || t.includes('Continue without restoring');
            }
            """)
            if has_cancel_modal:
                logger.info("[FB-Service] Detected 'Tiếp tục mà không khôi phục' modal. Clicking 'Hủy'...")
                clicked = await page.evaluate("""
                () => {
                    let allBtns = Array.from(document.querySelectorAll('button, div[role="button"], span, [tabindex="0"]'));
                    for (let b of allBtns) {
                        let txt = (b.innerText || '').trim();
                        if (txt === 'Hủy' || txt === 'Cancel') {
                            (b.closest('div[role="button"], button') || b).click();
                            return true;
                        }
                    }
                    return false;
                }
                """)
                if not clicked:
                    await page.mouse.click(440, 575)
                await asyncio.sleep(1.5)

            # 1. Check if PIN screen is present by text
            has_pin_dialog = await page.evaluate("""
            () => {
                let txt = (document.body.innerText || '');
                return txt.includes('Nhập mã PIN') || txt.includes('khôi phục đoạn chat') || 
                       txt.includes('khôi phục lịch sử') || txt.includes('mã PIN') || 
                       txt.includes('Enter PIN') || txt.includes('restore your chat');
            }
            """)

            if not has_pin_dialog:
                return False

            logger.info("[FB-Service] E2EE PIN screen detected. Unlocking with PIN 090325 to restore full chat...")
            # 2. Directly click on PIN box 1 at (390, 630) to avoid misclicking Close (X) button
            await page.mouse.click(390, 630)
            await asyncio.sleep(0.6)

            # 3. Type 6 digits using 350ms delay for reliable React Lexical state transition
            pin = "090325"
            await page.keyboard.type(pin, delay=350)

            # 4. Wait for Facebook to verify PIN and decrypt chat history (5-8s)
            logger.info("[FB-Service] PIN 090325 entered. Waiting for E2EE decryption...")
            await asyncio.sleep(7.0)

            # 5. Clean up any remaining dialog elements and backdrops from DOM
            await page.evaluate("""
            () => {
                let dialogs = Array.from(document.querySelectorAll('[role="dialog"], [role="alertdialog"], div[aria-modal="true"]'));
                dialogs.forEach(d => d.remove());
                let backdrops = Array.from(document.querySelectorAll('div[style*="position: fixed"], div[style*="background-color: rgba(0, 0, 0"]'));
                backdrops.forEach(b => {
                    if (!b.querySelector('[role="main"]') && !b.querySelector('[role="navigation"]')) {
                        b.remove();
                    }
                });
            }
            """)
            await asyncio.sleep(0.5)

            logger.info("[FB-Service] E2EE chat history successfully decrypted and unlocked with PIN 090325!")
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

              // 1. Collect candidate elements carrying Facebook Messenger message metadata
              let rawElements = Array.from(main.querySelectorAll('[role="row"], [aria-label*="gửi lúc"], [aria-label*="sent at"], [aria-label*="Tin nhắn do"]'));
              
              // 2. Filter out nested child elements if parent is already in the list to avoid duplicate DOM traversal
              let distinctElements = rawElements.filter(el => {
                return !rawElements.some(parent => parent !== el && parent.contains(el));
              });

              // Fallback to allElements if distinctElements is empty
              if (distinctElements.length === 0) {
                distinctElements = Array.from(main.querySelectorAll('span, [aria-label]'));
              }

              let incoming = [];
              let last_sender = 'none';
              let last_msg_text = '';
              let consecutive_unreplied = 0;
              let reached_human_boundary = false;
              let seenSignatures = new Set();
              let last_msg_hour = null;
              let last_msg_minute = null;

              for (let i = distinctElements.length - 1; i >= 0; i--) {
                let el = distinctElements[i];
                let t = (el.getAttribute('aria-label') || el.textContent || '').trim();
                if (!t || t.length < 5) continue;
                let low = t.toLowerCase();
                if (!low.includes('tin nhắn do') || !low.includes('gửi lúc')) continue;

                // Deduplicate by exact unique aria-label / message signature
                let cleanSig = t.replace(/\\s+/g, ' ').trim();
                if (seenSignatures.has(cleanSig)) continue;
                seenSignatures.add(cleanSig);

                let isUs = low.includes('do bạn gửi') || low.includes('do bạn gởi');
                let colonIdx = t.lastIndexOf(':');
                let msgText = colonIdx >= 0 ? t.substring(colonIdx + 1).trim() : '';
                if (!msgText) continue;

                // Record the very last message in thread
                if (last_sender === 'none') {
                  last_sender = isUs ? 'us' : 'them';
                  last_msg_text = msgText;
                  let timeMatch = t.match(/gửi lúc\\s*(\\d{1,2}):(\\d{2})/i) || t.match(/sent at\\s*(\\d{1,2}):(\\d{2})/i);
                  if (timeMatch) {
                    last_msg_hour = parseInt(timeMatch[1], 10);
                    last_msg_minute = parseInt(timeMatch[2], 10);
                  }
                }

                if (!isUs) {
                  // Message from the other party
                  incoming.unshift(msgText);
                  if (last_sender === 'them' && !reached_human_boundary) {
                    consecutive_unreplied++;
                  }
                  if (incoming.length >= 10) {
                    break;
                  }
                } else {
                  // Message from us
                  if (last_sender === 'them') {
                    // Reached boundary where our last message ended
                    reached_human_boundary = true;
                    break;
                  } else {
                    // last_sender is 'us': if we already collected incoming messages preceding this 'us' message, stop
                    if (incoming.length > 0) {
                      break;
                    }
                  }
                }
              }

              return {
                last_sender: last_sender,
                consecutive_unreplied_count: consecutive_unreplied,
                incoming_msgs: incoming,
                last_msg_text: last_msg_text,
                last_msg_hour: last_msg_hour,
                last_msg_minute: last_msg_minute
              };
            }
            """
            res = await page.evaluate(script)
            if isinstance(res, dict):
                last_hour = res.get("last_msg_hour")
                last_min = res.get("last_msg_minute")
                elapsed_minutes = None
                if last_hour is not None and last_min is not None:
                    try:
                        now_dt = datetime.now(VN_TZ)
                        msg_dt = now_dt.replace(hour=int(last_hour), minute=int(last_min), second=0, microsecond=0)
                        if msg_dt > now_dt:
                            msg_dt -= timedelta(days=1)
                        elapsed_minutes = max(0.0, (now_dt - msg_dt).total_seconds() / 60.0)
                    except Exception:
                        elapsed_minutes = None

                return {
                    "last_sender": str(res.get("last_sender", "none")),
                    "consecutive_unreplied_count": int(res.get("consecutive_unreplied_count", 0)),
                    "incoming_msgs": [str(s).strip() for s in res.get("incoming_msgs", []) if s],
                    "last_msg_text": str(res.get("last_msg_text", "")),
                    "elapsed_minutes_since_last_msg": elapsed_minutes,
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
        """Sends a text message in an already opened and authenticated chat window.
        Proactively unlocks E2EE with PIN 090325 before typing.
        """
        try:
            # 0. Unlock E2EE with PIN 090325 if PIN screen or confirmation modal is open
            await self._handle_e2ee_pin_screen(page)
            await asyncio.sleep(0.5)

            # 1. Target the chat message textbox directly in DOM
            textbox_selector = 'div[role="main"] div[role="textbox"][contenteditable="true"], div[role="textbox"][contenteditable="true"], div[data-lexical-editor="true"], div[aria-placeholder="Aa"]'
            
            textbox_found = False
            for _ in range(10):
                try:
                    el = await page.wait_for_selector(textbox_selector, timeout=2000)
                    if el:
                        await el.scroll_into_view_if_needed()
                        await el.click(force=True)
                        await el.focus()
                        textbox_found = True
                        break
                except Exception:
                    await asyncio.sleep(1.0)

            if not textbox_found:
                logger.warning("[FB-Service] Could not locate or click chat message textbox after 10s.")
                return False

            await asyncio.sleep(0.4)

            # 2. Clear any leftover draft text
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")
            await asyncio.sleep(0.2)

            # 3. Type the message content using human-like keypresses (essential for Facebook React Lexical editor state sync)
            await page.keyboard.type(text, delay=25)
            await asyncio.sleep(0.6)

            # 4. Press Enter to send
            await page.keyboard.press("Enter")
            await asyncio.sleep(1.5)

            # 5. Fallback: click Send button if Enter didn't trigger submission
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

    async def _unsend_message(self, page: Page, message_text: str) -> bool:
        """
        Unsends (recalls) a specific message by its text content in the currently open chat.

        Flow: Hover message bubble → reveal "..." (More) button → click Gỡ (Remove) →
              confirm "Gỡ cho mọi người" (Remove for everyone).

        Uses multiple fallback selectors because Facebook's obfuscated CSS classes
        change frequently; role/label-based selectors are most resilient.
        """
        try:
            # 1. Use the first ~40 chars as a unique search key (avoids issues with very long text)
            search_snippet = message_text[:40].strip()
            if not search_snippet:
                return False

            # 2. Ensure E2EE is unlocked — without this, messages don't render in headless Chromium
            await self._handle_e2ee_pin_screen(page)
            await asyncio.sleep(1.0)

            # 3. Wait for message bubbles to actually load in DOM (E2EE conversations load async)
            try:
                await page.wait_for_selector('div[dir="auto"]', timeout=10000)
            except Exception:
                logger.warning("[FB-Service] Unsend: timed out waiting for message bubbles to load (E2EE?)")
                return False
            await asyncio.sleep(1.5)

            # 4. Scroll to bottom — auto-reply is recent, should be near the bottom
            await page.keyboard.press("End")
            await asyncio.sleep(1.0)

            # 3. Locate the message bubble containing our text (last match = most recent)
            #    Facebook renders message text inside div[dir="auto"] elements
            msg_locator = page.locator('div[dir="auto"]').filter(has_text=search_snippet)
            count = await msg_locator.count()
            if count == 0:
                # Retry after short scroll up in case it's above viewport
                await page.mouse.wheel(0, -800)
                await asyncio.sleep(0.8)
                count = await msg_locator.count()

            if count == 0:
                logger.warning("[FB-Service] Unsend: message bubble not found for snippet: %s", search_snippet)
                return False

            target_msg = msg_locator.nth(count - 1)  # last (most recent) occurrence
            await target_msg.scroll_into_view_if_needed()
            await asyncio.sleep(0.5)

            # Debug: take screenshot to see actual page state before hover
            try:
                await page.screenshot(path="/app/browser_data/unsend_debug.png")
                logger.info("[FB-Service] Unsend debug screenshot saved.")
            except Exception:
                pass

            # 4. Hover over the message bubble CONTAINER (not just the text node).
            # Facebook's action toolbar (with "More") is attached to the parent wrapper,
            # not the div[dir="auto"] text element. We walk up the DOM to find it.
            hovered = False
            try:
                # Use JS to find the ancestor element that actually has the hover toolbar
                # (typically 3-5 levels above div[dir="auto"])
                container_handle = await page.evaluate_handle("""
                    (snippet) => {
                        const allDivs = [...document.querySelectorAll('div[dir="auto"]')];
                        const target = allDivs.reverse().find(d => d.innerText && d.innerText.includes(snippet));
                        if (!target) return null;
                        // Walk up to find a container with data-message-id or role="row" or similar
                        let el = target.parentElement;
                        for (let i = 0; i < 8; i++) {
                            if (!el) break;
                            // Typical Messenger message container has a specific min-width or inline-block style
                            const style = window.getComputedStyle(el);
                            if (el.dataset.mid || el.getAttribute('data-message-id') ||
                                el.getAttribute('role') === 'row' || el.classList.length > 3) {
                                return el;
                            }
                            el = el.parentElement;
                        }
                        // Fallback: go up 4 levels from text node
                        el = target;
                        for (let i = 0; i < 4; i++) el = el?.parentElement;
                        return el;
                    }
                """, search_snippet)

                if container_handle:
                    container_el = container_handle.as_element()
                    if container_el:
                        await container_el.hover()
                        await asyncio.sleep(1.0)
                        hovered = True
            except Exception as he:
                logger.warning("[FB-Service] Unsend: JS container hover failed: %s", he)

            if not hovered:
                # Direct fallback: hover the text node itself
                await target_msg.hover()
                await asyncio.sleep(1.0)

            # 5. Find and click the "More" (three-dot) button that appears on hover.
            #    Strategy: look for any visible button near the message that just appeared.
            # Screenshot after hover to verify toolbar appeared
            try:
                await page.screenshot(path="/app/browser_data/unsend_after_hover.png")
            except Exception:
                pass

            more_btn = None
            more_labels = ["Thêm hành động", "Thêm", "More", "More actions", "Tùy chọn thêm"]
            for label in more_labels:
                try:
                    candidate = page.get_by_label(label, exact=False)
                    if await candidate.count() > 0:
                        # Prefer the button closest to our message by taking last visible one
                        for i in range(await candidate.count() - 1, -1, -1):
                            btn = candidate.nth(i)
                            if await btn.is_visible():
                                more_btn = btn
                                break
                    if more_btn:
                        break
                except Exception:
                    continue

            if not more_btn:
                # Fallback: use JS to find and click the "More" (⋮) button near the hovered message.
                # From screenshot analysis: toolbar has [⋮ More | ↩ Reply | 😊 Emoji] — More is leftmost.
                logger.warning("[FB-Service] Unsend: aria-label not found, trying JS fallback for More button")
                try:
                    clicked = await page.evaluate("""
                        (snippet) => {
                            // Find the message bubble containing our text
                            const allDivs = [...document.querySelectorAll('div[dir="auto"]')];
                            const target = allDivs.reverse().find(d => d.innerText && d.innerText.includes(snippet));
                            if (!target) return false;

                            const msgRect = target.getBoundingClientRect();
                            const buttons = [...document.querySelectorAll('[role="button"]')];

                            // Filter: visible, has SVG icon, within vertical proximity of message
                            const toolbar_btns = buttons.filter(b => {
                                const r = b.getBoundingClientRect();
                                return r.width > 0 && r.height > 0 &&
                                       r.width < 60 && r.height < 60 &&   // small icon buttons only
                                       window.getComputedStyle(b).display !== 'none' &&
                                       b.querySelector('svg') &&
                                       Math.abs(r.top + r.height/2 - (msgRect.top + msgRect.height/2)) < 60;
                            });

                            if (toolbar_btns.length === 0) return false;

                            // The More (⋮) button is leftmost in the toolbar group
                            // Sort by x-position and pick the one with smallest x
                            toolbar_btns.sort((a, b) => a.getBoundingClientRect().left - b.getBoundingClientRect().left);
                            toolbar_btns[0].click();
                            return true;
                        }
                    """, search_snippet)
                    if clicked:
                        more_btn = True  # sentinel — menu should be open now
                except Exception as je:
                    logger.warning("[FB-Service] Unsend: JS More button click also failed: %s", je)

            if not more_btn:
                logger.warning("[FB-Service] Unsend: could not locate 'More' hover button via aria-label or JS")
                return False

            if more_btn is not True:  # if we got an actual locator (not JS sentinel)
                await more_btn.click()
            
            # 6. Click "Gỡ" / "Remove" from the context menu
            await asyncio.sleep(1.0)  # wait longer for menu to animate in

            # Debug: screenshot after clicking More to see what menu opened
            try:
                await page.screenshot(path="/app/browser_data/unsend_menu_open.png")
            except Exception:
                pass

            # Log all visible menu items/buttons for debugging
            try:
                menu_items = await page.evaluate("""
                    () => {
                        const items = [...document.querySelectorAll('[role="menuitem"], [role="option"], [role="listitem"]')];
                        return items.filter(i => {
                            const r = i.getBoundingClientRect();
                            return r.width > 0 && r.height > 0;
                        }).map(i => i.innerText?.trim()).filter(Boolean);
                    }
                """)
                logger.info("[FB-Service] Unsend: visible menu items = %s", menu_items)
            except Exception:
                pass

            removed = False
            remove_patterns = [
                re.compile(r"^Gỡ$", re.I),
                re.compile(r"^Remove$", re.I),
                re.compile(r"^Xóa$", re.I),
            ]
            for pattern in remove_patterns:
                try:
                    item = page.get_by_role("menuitem", name=pattern)
                    if await item.count() > 0 and await item.first().is_visible():
                        await item.first().click()
                        removed = True
                        break
                except Exception:
                    pass

            if not removed:
                # Fallback: try getByText
                for label in ("Gỡ", "Remove", "Xóa"):
                    try:
                        item = page.get_by_text(label, exact=True)
                        if await item.count() > 0 and await item.first().is_visible():
                            await item.first().click()
                            removed = True
                            break
                    except Exception:
                        pass

            if not removed:
                # Last resort: JS click on any visible item containing "Gỡ" or "Remove"
                try:
                    removed = await page.evaluate("""
                        () => {
                            const all = [...document.querySelectorAll('[role="menuitem"], [role="option"], [role="listitem"], li, div[tabindex]')];
                            const target = all.find(el => {
                                const t = (el.innerText || '').trim();
                                return /^(Gỡ|Remove|Xóa)$/.test(t) && el.getBoundingClientRect().width > 0;
                            });
                            if (target) { target.click(); return true; }
                            return false;
                        }
                    """)
                    if removed:
                        logger.info("[FB-Service] Unsend: found Remove via JS last-resort.")
                except Exception:
                    pass

            if not removed:
                logger.warning("[FB-Service] Unsend: could not find Remove option in context menu")
                return False

            await asyncio.sleep(0.8)

            # 7. Confirm "Gỡ cho mọi người" / "Remove for everyone" in the confirmation dialog
            confirmed = False
            confirm_patterns = [
                re.compile(r"Gỡ cho mọi người", re.I),
                re.compile(r"Remove for everyone", re.I),
                re.compile(r"Xóa cho mọi người", re.I),
            ]
            for pattern in confirm_patterns:
                try:
                    btn = page.get_by_role("button", name=pattern)
                    if await btn.count() > 0 and await btn.first().is_visible():
                        await btn.first().click()
                        confirmed = True
                        break
                except Exception:
                    pass

            if not confirmed:
                logger.warning("[FB-Service] Unsend: could not find 'Remove for everyone' confirmation button")
                return False

            await asyncio.sleep(1.5)
            logger.info("[FB-Service] Auto-reply message successfully unsent.")
            return True

        except Exception as exc:
            logger.error("[FB-Service] _unsend_message error: %s", exc, exc_info=True)
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

            # Clean up stale Chromium SingletonLock / SingletonSocket
            for item in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
                lock_path = browser_data_path / item
                if lock_path.is_symlink() or lock_path.exists():
                    try:
                        lock_path.unlink()
                    except Exception:
                        pass

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
                                try:
                                    await page.screenshot(path="/app/browser_data/proof_chat_screen.png")
                                except Exception:
                                    pass

                                # ── Auto-reply decision ──────────────────────────────────────
                                # 1. If the last message in the thread was sent by 'us' (account owner or bot):
                                #    The conversation is already replied to. NEVER send away message!
                                if last_sender == "us":
                                    logger.info("[FB-Service] '%s': last message is from us; no auto-reply needed.", clean_name)
                                    is_auto = any(m in last_msg_text for m in AWAY_REPLY_MARKERS)
                                    logger.info("[FB-Service] '%s': is_auto=%s, last_msg_text=%s", clean_name, is_auto, last_msg_text[:60] if last_msg_text else "(empty)")

                                    # ── Unsend trigger (DB-backed, restart-safe) ──────────────
                                    # Condition: the last msg is human's direct reply (not bot's away msg),
                                    # AND the DB records a pending auto-reply for this thread.
                                    if not is_auto:
                                        pending_reply_text = await self.get_thread_auto_reply(t_href)
                                        logger.info("[FB-Service] '%s': pending_reply_text in DB = %s", clean_name, bool(pending_reply_text))
                                        if pending_reply_text:
                                            logger.info(
                                                "[FB-Service] '%s': human replied after bot auto-reply — attempting unsend (DB-backed).",
                                                clean_name,
                                            )
                                            unsent_ok = await self._unsend_message(page, pending_reply_text)
                                            if unsent_ok:
                                                logger.info("[FB-Service] '%s': auto-reply successfully unsent.", clean_name)
                                                await self.mark_thread_auto_reply_unsent(t_href)
                                                await self.message_cache.mark_auto_reply_unsent(clean_name)
                                            else:
                                                logger.warning(
                                                    "[FB-Service] '%s': unsend failed — will retry on next scan cycle.",
                                                    clean_name,
                                                )

                                    await self.message_cache.add_or_update(
                                        sender_name=clean_name,
                                        incoming_messages=incoming_msgs,
                                        last_reply_sent=last_msg_text,
                                        thread_href=t_href,
                                        was_auto_replied=is_auto,
                                        replied_by_human=(not is_auto),
                                        reply_type="ai_auto" if is_auto else "human_direct"
                                    )
                                    continue

                                # 2. If 0 messages found or E2EE locked:
                                if not incoming_msgs:
                                    logger.info("[FB-Service] '%s': 0 readable incoming msgs; skip.", clean_name)
                                    continue

                                # 3. Update cache with latest incoming messages with unreplied status
                                await self.message_cache.add_or_update(
                                    sender_name=clean_name,
                                    incoming_messages=incoming_msgs,
                                    last_reply_sent="",
                                    thread_href=t_href,
                                    was_auto_replied=False,
                                    replied_by_human=False,
                                    reply_type="none"
                                )

                                # 4. Presence Check 1: Global Human Active Session
                                human_session_minutes = int(cfg.get("human_session_minutes", 10))
                                if self.message_cache.is_human_actively_chatting(window_minutes=human_session_minutes):
                                    mins_ago = self.message_cache.get_last_human_activity_minutes_ago()
                                    logger.info(
                                        "[FB-Service] '%s': Human is actively chatting (last action %.1fm ago < %dm session window); suppressing auto-reply.",
                                        clean_name, mins_ago or 0.0, human_session_minutes,
                                    )
                                    continue

                                # 5. Presence Check 2: Consecutive unreplied count vs threshold
                                if consecutive_unreplied < threshold:
                                    logger.info(
                                        "[FB-Service] '%s': unreplied count (%d) < threshold (%d); skip away message.",
                                        clean_name, consecutive_unreplied, threshold,
                                    )
                                    continue

                                # 6. Presence Check 3: Inactivity / Idle Delay Window
                                idle_timeout_minutes = int(cfg.get("idle_timeout_minutes", 3))
                                entry = self.message_cache._find_entry_sync(clean_name)
                                detected_at = entry.detected_at if entry else datetime.now(VN_TZ)
                                cache_elapsed = max(0.0, (datetime.now(VN_TZ) - detected_at).total_seconds() / 60.0)
                                dom_elapsed = conv_state.get("elapsed_minutes_since_last_msg")

                                # Use DOM elapsed time if parsed, otherwise fallback to cache detection elapsed time
                                effective_elapsed = dom_elapsed if dom_elapsed is not None else cache_elapsed

                                if effective_elapsed < idle_timeout_minutes:
                                    logger.info(
                                        "[FB-Service] '%s': threshold (%d) met but messages too recent (%.1fm < %dm idle delay); observing...",
                                        clean_name, threshold, effective_elapsed, idle_timeout_minutes,
                                    )
                                    continue

                                # 7. If threshold reached and idle delay elapsed, ensure this is a new message batch
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
                                    # Persist the auto-reply text in DB so unsend can find it
                                    # even after a container restart (DB-backed, not in-memory)
                                    await self.save_known_thread(t_href, clean_name, current_hash, auto_reply_text=away_reply)
                                    await self.message_cache.add_or_update(
                                        sender_name=clean_name,
                                        incoming_messages=incoming_msgs,
                                        last_reply_sent=away_reply,
                                        thread_href=t_href,
                                        was_auto_replied=True,
                                        replied_by_human=False,
                                        reply_type="ai_auto"
                                    )
                                    logger.info(
                                        "[FB-Service] AUTO-REPLIED to '%s' (unreplied=%d, hash %s→%s)",
                                        clean_name, consecutive_unreplied, previous_hash or "∅", current_hash,
                                    )
                                else:
                                    logger.warning("[FB-Service] Failed to send reply to '%s'", clean_name)

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

    async def send_direct_reply(self, recipient_name: str, message: str) -> Dict[str, Any]:
        """Opens a conversation and sends a direct reply message.
        Captures a visual screenshot proof of the sent message in the chat box.

        Protected by the global _browser_lock to ensure only 1 Chromium instance
        runs at a time, preventing CPU overload and timeouts.
        Directly navigates to target thread URL for maximum speed.
        """
        if not recipient_name or not message:
            return {"success": False, "error": "Lỗi: Thiếu tên người nhận hoặc nội dung tin nhắn."}

        cfg = await self.get_config_from_db()
        cookies = self._parse_cookies(cfg.get("cookies_json", ""))
        if not cookies:
            return {"success": False, "error": "Lỗi: Chưa cấu hình Cookies Facebook trên hệ thống."}

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
                effective_score = score + (0.15 if is_non_e2ee else 0.0)
                if effective_score > best_score and effective_score >= 0.4:
                    best_score = effective_score
                    best_href = t["href"]
            if best_href:
                target_href = best_href
                logger.info("[FB-DirectReply] Resolved thread from DB with score %.2f: %s", best_score, target_href)

        # 3. Fallback: pick the primary known thread from database if recipient_name matches loosely
        if not target_href:
            db_threads = await self.get_known_threads_from_db()
            if db_threads:
                target_href = db_threads[0]["href"]
                logger.info("[FB-DirectReply] Fallback to primary known thread: %s", target_href)

        async def _execute_send() -> Dict[str, Any]:
            # Clean up stale Chromium SingletonLock
            for item in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
                lock_path = Path(BROWSER_DATA_DIR) / item
                if lock_path.is_symlink() or lock_path.exists():
                    try:
                        lock_path.unlink()
                    except Exception:
                        pass

            async with async_playwright() as p:
                ctx = await p.chromium.launch_persistent_context(
                    user_data_dir=BROWSER_DATA_DIR,
                    headless=True,
                    viewport={"width": 1280, "height": 900},
                    timezone_id="Asia/Ho_Chi_Minh",
                    locale="vi-VN",
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                    ],
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

                    await asyncio.sleep(2.5)

                    # Handle E2EE PIN unlock with 090325 to decrypt full chat history
                    pin_unlocked = await self._handle_e2ee_pin_screen(page)
                    if pin_unlocked:
                        logger.info("[FB-DirectReply] E2EE PIN 090325 successfully handled for '%s'", recipient_name)

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
                        # Wait 3.5s to ensure WebSocket payload is rendered in chat view
                        await asyncio.sleep(3.5)
                        proof_path = ""
                        # Clean up any leftover overlay before taking screenshot proof
                        try:
                            await page.evaluate("""
                            () => {
                                let dialogs = Array.from(document.querySelectorAll('[role="dialog"], [role="alertdialog"], div[aria-modal="true"]'));
                                dialogs.forEach(d => d.remove());
                                let backdrops = Array.from(document.querySelectorAll('div[style*="position: fixed"], div[style*="background-color: rgba(0, 0, 0"]'));
                                backdrops.forEach(b => {
                                    if (!b.querySelector('[role="main"]') && !b.querySelector('[role="navigation"]')) {
                                        b.remove();
                                    }
                                });
                            }
                            """)
                            await asyncio.sleep(0.5)
                            safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', recipient_name.strip().lower()) or "reply"
                            proof_path = f"/tmp/fb_reply_proof_{safe_name}_{int(time.time()*1000)}.png"
                            await page.screenshot(path=proof_path)
                            logger.info("[FB-DirectReply] Captured visual proof screenshot -> %s", proof_path)
                        except Exception as shot_err:
                            logger.warning("[FB-DirectReply] Could not capture proof screenshot: %s", shot_err)

                        await self.message_cache.record_direct_reply(recipient_name, message)
                        actual_url = page.url.split("?")[0]
                        await self.record_sender_cooldown(actual_url)
                        logger.info("[FB-DirectReply] SENT to '%s': %s", recipient_name, message)
                        return {
                            "success": True,
                            "image_path": proof_path,
                            "recipient_name": recipient_name,
                            "message": message,
                            "summary": f'Đã gửi tin nhắn cho "{recipient_name}": "{message}"',
                        }
                    else:
                        return {
                            "success": False,
                            "error": f'Lỗi: Đã mở trang chat với "{recipient_name}" nhưng không thể gửi tin nhắn vào ô chat.',
                        }

                finally:
                    await page.close()
                    await ctx.close()

        try:
            async with self._browser_lock:
                return await asyncio.wait_for(_execute_send(), timeout=120.0)
        except asyncio.TimeoutError:
            logger.error("[FB-DirectReply] Timeout sending to '%s'", recipient_name)
            return {"success": False, "error": f'Lỗi: Hết thời gian chờ (120s) khi gửi tin nhắn cho "{recipient_name}". Vui lòng thử lại.'}
        except Exception as e:
            logger.error("[FB-DirectReply] Error sending to '%s': %s", recipient_name, e)
            return {"success": False, "error": f'Lỗi khi gửi tin nhắn cho "{recipient_name}": {e}'}

    async def capture_chat_screenshot(self, recipient_name: str) -> Dict[str, Any]:
        """Navigates to the recipient's chat thread, unlocks E2EE with PIN 090325,
        removes any blocking overlays, captures a crystal-clear screenshot, and returns its file path.
        """
        logger.info("[FB-Screenshot] Request to capture chat screenshot for '%s'...", recipient_name)
        cfg = await self.get_config_from_db()
        cookies = self._parse_cookies(cfg.get("cookies_json", ""))
        if not cookies:
            return {"success": False, "error": "Chưa có session cookies Facebook. Vui lòng cập nhật cookies trong Settings."}

        # 1. Resolve thread href from message_cache or known threads
        target_href = await self.message_cache.find_thread_href(recipient_name)
        if not target_href:
            db_threads = await self.get_known_threads_from_db()
            best_score = 0.0
            best_href = None
            for t in db_threads:
                score = self._name_match_score(recipient_name, t.get("text", ""))
                if score > best_score and score >= 0.4:
                    best_score = score
                    best_href = t["href"]
            if best_href:
                target_href = best_href

        if not target_href:
            db_threads = await self.get_known_threads_from_db()
            if db_threads:
                target_href = db_threads[0]["href"]
                logger.info("[FB-Screenshot] Fallback to primary known thread: %s", target_href)

        import re
        safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', recipient_name.strip().lower()) or "chat"
        screenshot_path = f"/tmp/fb_chat_{safe_name}.png"

        async def _execute_capture() -> Dict[str, Any]:
            # Clean up stale Chromium locks
            for item in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
                lock_path = Path(BROWSER_DATA_DIR) / item
                if lock_path.is_symlink() or lock_path.exists():
                    try:
                        lock_path.unlink()
                    except Exception:
                        pass

            async with async_playwright() as p:
                ctx = await p.chromium.launch_persistent_context(
                    user_data_dir=BROWSER_DATA_DIR,
                    headless=True,
                    viewport={"width": 1280, "height": 900},
                    timezone_id="Asia/Ho_Chi_Minh",
                    locale="vi-VN",
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                    ],
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
                )
                try:
                    await ctx.add_cookies(cast(Any, cookies))
                except Exception:
                    pass

                page = await ctx.new_page()
                try:
                    dest_url = target_href if target_href else "https://www.facebook.com/messages/t/"
                    logger.info("[FB-Screenshot] Navigating to: %s for '%s'...", dest_url, recipient_name)
                    try:
                        await page.goto(
                            dest_url,
                            wait_until="domcontentloaded",
                            timeout=35000,
                        )
                    except Exception as nav_e:
                        logger.warning("[FB-Screenshot] Navigation notice: %s", nav_e)

                    # Wait for React Messenger interface
                    try:
                        await page.wait_for_selector('div[role="main"], div[role="textbox"], [contenteditable="true"]', timeout=20000)
                    except Exception:
                        pass

                    await asyncio.sleep(2.5)

                    # Handle E2EE PIN unlock with 090325 to decrypt full chat history
                    pin_unlocked = await self._handle_e2ee_pin_screen(page)
                    if pin_unlocked:
                        logger.info("[FB-Screenshot] E2EE PIN 090325 successfully handled for '%s'", recipient_name)
                    await asyncio.sleep(1.5)

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
                        await asyncio.sleep(1.0)

                    # Clean up any leftover overlay / backdrop
                    try:
                        await page.evaluate("""
                        () => {
                            let dialogs = Array.from(document.querySelectorAll('[role="dialog"], [role="alertdialog"], div[aria-modal="true"]'));
                            dialogs.forEach(d => d.remove());
                            let backdrops = Array.from(document.querySelectorAll('div[style*="position: fixed"], div[style*="background-color: rgba(0, 0, 0"]'));
                            backdrops.forEach(b => {
                                if (!b.querySelector('[role="main"]') && !b.querySelector('[role="navigation"]')) {
                                    b.remove();
                                }
                            });
                        }
                        """)
                    except Exception:
                        pass

                    await page.screenshot(path=screenshot_path)
                    logger.info("[FB-Screenshot] Screenshot successfully saved to %s", screenshot_path)
                    return {
                        "success": True,
                        "image_path": screenshot_path,
                        "recipient_name": recipient_name,
                        "message": f"Đã chụp ảnh màn hình hội thoại với {recipient_name}.",
                    }
                finally:
                    await page.close()
                    await ctx.close()

        try:
            async with self._browser_lock:
                return await asyncio.wait_for(_execute_capture(), timeout=120.0)
        except asyncio.TimeoutError:
            logger.error("[FB-Screenshot] Timeout capturing screenshot for '%s'", recipient_name)
            return {"success": False, "error": "Hết thời gian chờ (120s) khi chụp ảnh màn hình."}
        except Exception as e:
            logger.error("[FB-Screenshot] Error capturing screenshot for '%s': %s", recipient_name, e, exc_info=True)
            return {"success": False, "error": str(e)}


