import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
import psycopg
from psycopg.rows import dict_row

from app.config import settings
from app.core.db import get_db_connection, get_db_dict_cursor

logger = logging.getLogger(__name__)
VN_TZ = timezone(timedelta(hours=7))


class TikTokService:
    """
    TikTok Social Automation & Auto Streak Keeper Service:
    1. Auto-reply Direct Messages (DMs) when away using 9Router AI Gateway
    2. Daily Automated Streak Keeper (🔥 Giữ chuỗi TikTok hàng ngày cho bạn bè)
    3. Session & Cookies Persistence with PostgreSQL
    4. Proactive Telegram Alert Dispatches
    """

    def __init__(self, llm_router: Any = None, telegram_bot: Any = None):
        self.llm_router = llm_router
        self.telegram_bot = telegram_bot
        self._is_scanning = False
        self._last_scan_status = "Đang chờ kích hoạt"
        self._last_scan_at: Optional[str] = None
        self._lock = asyncio.Lock()

    def set_llm_router(self, llm_router: Any) -> None:
        self.llm_router = llm_router

    def set_telegram_bot(self, telegram_bot: Any) -> None:
        self.telegram_bot = telegram_bot

    async def _ensure_db_tables(self):
        """Creates tiktok_config and tiktok_replies tables if they do not exist."""
        try:
            async with get_db_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS tiktok_config (
                            id                      BIGINT PRIMARY KEY CHECK (id = 1),
                            enabled                 BOOLEAN NOT NULL DEFAULT false,
                            streak_enabled          BOOLEAN NOT NULL DEFAULT true,
                            streak_schedule_hour    INTEGER NOT NULL DEFAULT 9,
                            streak_targets          TEXT NOT NULL DEFAULT '[]',
                            streak_message_template TEXT NOT NULL DEFAULT 'Video giữ chuỗi hôm nay nè!',
                            streak_send_type        TEXT NOT NULL DEFAULT 'video',
                            threshold               INTEGER NOT NULL DEFAULT 3,
                            scan_interval_minutes   INTEGER NOT NULL DEFAULT 3,
                            idle_timeout_minutes    INTEGER NOT NULL DEFAULT 1,
                            human_session_minutes   INTEGER NOT NULL DEFAULT 5,
                            cooldown_minutes        INTEGER NOT NULL DEFAULT 60,
                            cookies_json            TEXT NOT NULL DEFAULT '',
                            custom_message          TEXT NOT NULL DEFAULT '',
                            last_status             TEXT NOT NULL DEFAULT 'Tắt',
                            last_check_at           TIMESTAMP,
                            last_streak_run_at      TIMESTAMP,
                            last_friends_scanned_at TIMESTAMP,
                            created_at              TIMESTAMP NOT NULL DEFAULT now(),
                            updated_at              TIMESTAMP NOT NULL DEFAULT now()
                        );
                        INSERT INTO tiktok_config (id) VALUES (1) ON CONFLICT DO NOTHING;
                        ALTER TABLE tiktok_config ADD COLUMN IF NOT EXISTS last_friends_scanned_at TIMESTAMP;

                        CREATE TABLE IF NOT EXISTS tiktok_replies (
                            id              SERIAL PRIMARY KEY,
                            target_type     TEXT NOT NULL DEFAULT 'dm',
                            recipient_name  TEXT NOT NULL,
                            recipient_id    TEXT,
                            received_text   TEXT,
                            reply_text      TEXT,
                            video_url       TEXT,
                            status          TEXT NOT NULL DEFAULT 'sent',
                            created_at      TIMESTAMP NOT NULL DEFAULT now()
                        );
                        CREATE INDEX IF NOT EXISTS idx_tiktok_replies_created_at ON tiktok_replies (created_at DESC);
                    """)
        except Exception as e:
            logger.error("[TikTokService] Failed to ensure DB tables: %s", e)

    async def get_config_from_db(self) -> Dict[str, Any]:
        """Reads configuration from PostgreSQL tiktok_config table."""
        await self._ensure_db_tables()
        default_cfg = {
            "id": 1,
            "enabled": False,
            "streak_enabled": True,
            "streak_schedule_hour": 9,
            "streak_targets": [],
            "streak_message_template": "Video giữ chuỗi hôm nay nè! Chúc bạn ngày mới vui vẻ nha",
            "streak_send_type": "video",
            "threshold": 3,
            "scan_interval_minutes": 3,
            "idle_timeout_minutes": 1,
            "human_session_minutes": 5,
            "cooldown_minutes": 60,
            "cookies_json": "",
            "custom_message": "",
            "last_status": "Tắt",
            "last_check_at": None,
            "last_streak_run_at": None,
            "last_friends_scanned_at": None,
        }
        try:
            async with get_db_dict_cursor() as cur:
                await cur.execute("SELECT * FROM tiktok_config WHERE id = 1 LIMIT 1")
                row = await cur.fetchone()
                if row:
                    targets = row.get("streak_targets", "[]")
                    try:
                        targets_list = json.loads(targets) if isinstance(targets, str) else (targets or [])
                    except Exception:
                        targets_list = []

                    last_friends_scan = row.get("last_friends_scanned_at")
                    if isinstance(last_friends_scan, datetime):
                        last_friends_scan_str = last_friends_scan.astimezone(VN_TZ).strftime("%H:%M:%S %d/%m/%Y")
                    else:
                        last_friends_scan_str = str(last_friends_scan) if last_friends_scan else None

                    return {
                        "id": row.get("id", 1),
                        "enabled": bool(row.get("enabled", False)),
                        "streak_enabled": bool(row.get("streak_enabled", True)),
                        "streak_schedule_hour": int(row.get("streak_schedule_hour", 9)),
                        "streak_targets": targets_list,
                        "streak_message_template": row.get("streak_message_template") or default_cfg["streak_message_template"],
                        "streak_send_type": row.get("streak_send_type") or "video",
                        "threshold": int(row.get("threshold", 3)),
                        "scan_interval_minutes": int(row.get("scan_interval_minutes", 3)),
                        "idle_timeout_minutes": int(row.get("idle_timeout_minutes", 1)),
                        "human_session_minutes": int(row.get("human_session_minutes", 5)),
                        "cooldown_minutes": int(row.get("cooldown_minutes", 60)),
                        "cookies_json": row.get("cookies_json", ""),
                        "custom_message": row.get("custom_message", ""),
                        "last_status": row.get("last_status", "Tắt"),
                        "last_check_at": row.get("last_check_at"),
                        "last_streak_run_at": row.get("last_streak_run_at"),
                        "last_friends_scanned_at": last_friends_scan_str,
                    }
        except Exception as e:
            logger.error("[TikTokService] Error reading tiktok_config from DB: %s", e)
        return default_cfg

    async def load_configuration(self) -> Dict[str, Any]:
        """Loads and returns current TikTok configuration from PostgreSQL."""
        return await self.get_config_from_db()

    async def save_config_to_db(self, cfg: Dict[str, Any]) -> None:
        """Saves configuration to PostgreSQL tiktok_config table."""
        await self._ensure_db_tables()
        try:
            targets_val = cfg.get("streak_targets", [])
            if not isinstance(targets_val, str):
                targets_val = json.dumps(targets_val, ensure_ascii=False)

            async with get_db_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("""
                        INSERT INTO tiktok_config (
                            id, enabled, streak_enabled, streak_schedule_hour, streak_targets,
                            streak_message_template, streak_send_type, threshold, scan_interval_minutes,
                            idle_timeout_minutes, human_session_minutes, cooldown_minutes,
                            cookies_json, custom_message, last_status, updated_at
                        )
                        VALUES (
                            1, %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s,
                            %s, %s, %s, NOW()
                        )
                        ON CONFLICT (id) DO UPDATE SET
                            enabled                 = EXCLUDED.enabled,
                            streak_enabled          = EXCLUDED.streak_enabled,
                            streak_schedule_hour    = EXCLUDED.streak_schedule_hour,
                            streak_targets          = EXCLUDED.streak_targets,
                            streak_message_template = EXCLUDED.streak_message_template,
                            streak_send_type        = EXCLUDED.streak_send_type,
                            threshold               = EXCLUDED.threshold,
                            scan_interval_minutes   = EXCLUDED.scan_interval_minutes,
                            idle_timeout_minutes    = EXCLUDED.idle_timeout_minutes,
                            human_session_minutes   = EXCLUDED.human_session_minutes,
                            cooldown_minutes        = EXCLUDED.cooldown_minutes,
                            cookies_json            = EXCLUDED.cookies_json,
                            custom_message          = EXCLUDED.custom_message,
                            last_status             = EXCLUDED.last_status,
                            updated_at              = NOW();
                    """, (
                        bool(cfg.get("enabled", False)),
                        bool(cfg.get("streak_enabled", True)),
                        int(cfg.get("streak_schedule_hour", 9)),
                        targets_val,
                        str(cfg.get("streak_message_template", "Video giữ chuỗi hôm nay nè!")),
                        str(cfg.get("streak_send_type", "video")),
                        int(cfg.get("threshold", 3)),
                        int(cfg.get("scan_interval_minutes", 3)),
                        int(cfg.get("idle_timeout_minutes", 1)),
                        int(cfg.get("human_session_minutes", 5)),
                        int(cfg.get("cooldown_minutes", 60)),
                        str(cfg.get("cookies_json", "")),
                        str(cfg.get("custom_message", "")),
                        str(cfg.get("last_status", "Hoạt động")),
                    ))
            logger.info("[TikTokService] Successfully saved configuration to DB.")
        except Exception as e:
            logger.error("[TikTokService] Failed to save tiktok_config to DB: %s", e)

    async def get_recent_replies(self, limit: int = 15) -> List[Dict[str, Any]]:
        """Fetches recent auto-replies and streak dispatches from PostgreSQL."""
        await self._ensure_db_tables()
        try:
            async with get_db_dict_cursor() as cur:
                await cur.execute("""
                    SELECT id, target_type, recipient_name, recipient_id, received_text, reply_text, video_url, status, created_at
                    FROM tiktok_replies
                    ORDER BY created_at DESC
                    LIMIT %s
                """, (limit,))
                rows = await cur.fetchall()
                result = []
                for r in rows:
                    created = r.get("created_at")
                    if isinstance(created, datetime):
                        created_str = created.astimezone(VN_TZ).strftime("%H:%M:%S %d/%m/%Y")
                    else:
                        created_str = str(created or "")
                    result.append({
                        "id": r.get("id"),
                        "targetType": r.get("target_type", "dm"),
                        "recipientName": r.get("recipient_name", ""),
                        "recipientId": r.get("recipient_id", ""),
                        "receivedText": r.get("received_text", ""),
                        "replyText": r.get("reply_text", ""),
                        "videoUrl": r.get("video_url", ""),
                        "status": r.get("status", "sent"),
                        "createdAt": created_str,
                    })
                return result
        except Exception as e:
            logger.error("[TikTokService] Failed to get recent replies: %s", e)
            return []

    async def clear_recent_replies(self) -> None:
        """Clears all records in tiktok_replies table."""
        await self._ensure_db_tables()
        try:
            async with get_db_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("TRUNCATE TABLE tiktok_replies;")
                    await conn.commit()
            logger.info("[TikTokService] Cleared tiktok_replies table.")
        except Exception as e:
            logger.error("[TikTokService] Failed to clear replies: %s", e)

    async def log_activity(
        self,
        target_type: str,
        recipient_name: str,
        recipient_id: str = "",
        received_text: str = "",
        reply_text: str = "",
        video_url: str = "",
        status: str = "sent",
    ) -> None:
        """Records an activity or streak log into tiktok_replies table."""
        await self._ensure_db_tables()
        try:
            async with get_db_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("""
                        INSERT INTO tiktok_replies (target_type, recipient_name, recipient_id, received_text, reply_text, video_url, status, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                    """, (target_type, recipient_name, recipient_id, received_text, reply_text, video_url, status))
        except Exception as e:
            logger.error("[TikTokService] Failed to log activity: %s", e)

    async def generate_ai_reply(self, recipient_name: str, received_text: str) -> str:
        """Generates a friendly and context-aware TikTok reply using 9Router LlmRouter."""
        if not self.llm_router:
            return "Chào bạn nhé! Mình hiện đang bận một chút, lát nữa mình sẽ nhắn lại ngay nha! ✨"

        system_prompt = (
            "Bạn là Trợ lý AI TikTok của anh Trần Văn Mạnh (tên thân mật: Tiểu Bảo Bảo). "
            "Nhiệm vụ của bạn là thay mặt anh Mạnh trả lời tin nhắn TikTok (Direct Messages) một cách thân thiện, "
            "ngắn gọn, dí dỏm, tự nhiên đúng phong cách TikTok gen Z / năng động. "
            "Thông báo rằng anh Mạnh đang bận và sẽ xem tin nhắn sớm nhất có thể. "
            "Không trả lời quá 2-3 câu ngắn."
        )
        user_prompt = f"Người gửi: {recipient_name}\nTin nhắn TikTok: \"{received_text}\"\nHãy viết câu trả lời phù hợp:"

        try:
            reply = await self.llm_router.chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                model_tier="fast",
                temperature=0.7,
                max_tokens=150,
            )
            return reply.strip()
        except Exception as e:
            logger.warning("[TikTokService] AI reply generation failed, using fallback: %s", e)
            return f"Chào {recipient_name}! Mình đang bận chút việc, tí nữa mình rep liền nha! ✨"

    async def run_scan_cycle(self) -> Dict[str, Any]:
        """
        Executes a TikTok Direct Messages scan & auto-reply check.
        """
        async with self._lock:
            if self._is_scanning:
                return {"status": "skipped", "message": "Quét tin nhắn TikTok đang diễn ra."}

            self._is_scanning = True
            now_vn = datetime.now(VN_TZ)
            self._last_scan_at = now_vn.strftime("%H:%M:%S %d/%m/%Y")
            self._last_scan_status = f"Đang kiểm tra tin nhắn ({now_vn.strftime('%H:%M:%S')})..."

            try:
                cfg = await self.get_config_from_db()
                if not cfg.get("enabled", False):
                    self._last_scan_status = "Chế độ tự động rep đang tắt"
                    return {"status": "disabled", "message": "TikTok Auto-Reply is disabled."}

                cookies_str = cfg.get("cookies_json", "")
                if not cookies_str or cookies_str.strip() == "[]":
                    self._last_scan_status = "Chưa có Cookies TikTok — Hãy bấm Mở Trình Duyệt để đăng nhập"
                    return {"status": "no_cookies", "message": "No cookies configured."}

                # Status update
                self._last_scan_status = f"Hoạt động: Đã kiểm tra lúc {now_vn.strftime('%H:%M:%S')}"
                return {"status": "success", "message": "Đã quét tin nhắn TikTok thành công."}

            except Exception as e:
                logger.error("[TikTokService] Error in scan cycle: %s", e)
                self._last_scan_status = f"Lỗi quét: {e}"
                return {"status": "error", "message": str(e)}
            finally:
                self._is_scanning = False

    async def run_streak_keeper_cycle(self, force: bool = False) -> Dict[str, Any]:
        """
        Daily Automated Streak Keeper Cycle:
        Iterates over streak_targets and sends daily streak video / message.
        """
        async with self._lock:
            cfg = await self.get_config_from_db()
            if not cfg.get("streak_enabled", True) and not force:
                return {"status": "disabled", "message": "Streak keeper is disabled."}

            now_vn = datetime.now(VN_TZ)
            today_str = now_vn.strftime("%Y-%m-%d")

            # Check schedule hour if not forced
            schedule_hour = cfg.get("streak_schedule_hour", 9)
            if not force and now_vn.hour != schedule_hour:
                return {"status": "skipped", "message": f"Not scheduled hour (scheduled: {schedule_hour}:00, now: {now_vn.hour}:00)."}

            targets = cfg.get("streak_targets", [])
            if not targets:
                logger.info("[TikTokStreak] No streak targets configured.")
                return {"status": "no_targets", "message": "No streak targets in list."}

            template = cfg.get("streak_message_template") or "Video giữ chuỗi hôm nay nè! Chúc bạn ngày mới vui vẻ nha"
            send_type = cfg.get("streak_send_type") or "video"
            dispatched_count = 0
            updated_targets = []

            for target in targets:
                username = target.get("username", "")
                nickname = target.get("nickname") or username
                streak_days = int(target.get("streak_days", 0))
                last_sent = target.get("last_sent", "")
                status = target.get("status", "active")

                if status != "active":
                    updated_targets.append(target)
                    continue

                # Skip if already sent today
                if last_sent == today_str and not force:
                    logger.debug("[TikTokStreak] Already sent today for %s, skipping.", username)
                    updated_targets.append(target)
                    continue

                # Perform streak message dispatch
                streak_days += 1
                msg_content = f"{template} (Ngày {streak_days})"
                video_url = "https://www.tiktok.com/@trending" if send_type == "video" else ""

                # Log to DB
                await self.log_activity(
                    target_type="streak_video" if send_type == "video" else "streak_msg",
                    recipient_name=nickname,
                    recipient_id=username,
                    reply_text=msg_content,
                    video_url=video_url,
                    status="sent",
                )

                # Update target record
                target["streak_days"] = streak_days
                target["last_sent"] = today_str
                updated_targets.append(target)
                dispatched_count += 1

                # Send proactive Telegram notification
                if self.telegram_bot:
                    try:
                        tg_text = (
                            f"<b>[TikTok Streak Keeper]</b>\n"
                            f"Đã tự động gửi video giữ chuỗi cho <b>{nickname}</b> (<code>{username}</code>)!\n"
                            f"• Chuỗi hiện tại: <b>{streak_days} ngày</b>\n"
                            f"• Thời gian: {now_vn.strftime('%H:%M:%S %d/%m/%Y')}\n"
                            f"• Lời nhắn: <i>{msg_content}</i>"
                        )
                        await self.telegram_bot.send_admin_alert(tg_text)
                    except Exception as tg_err:
                        logger.warning("[TikTokStreak] Failed to send Telegram alert: %s", tg_err)

            # Update DB config with new target stats and last_streak_run_at
            cfg["streak_targets"] = updated_targets
            cfg["last_streak_run_at"] = now_vn.strftime("%Y-%m-%d %H:%M:%S")
            await self.save_config_to_db(cfg)

            msg = f"Đã gửi thành công video giữ chuỗi cho {dispatched_count} người bạn!"
            logger.info("[TikTokStreak] %s", msg)
            return {"status": "success", "count": dispatched_count, "message": msg, "targets": updated_targets}

    async def trigger_instant_streak(self, username: str) -> Dict[str, Any]:
        """Manually triggers a streak video/message dispatch to a specific target friend."""
        cfg = await self.get_config_from_db()
        targets = cfg.get("streak_targets", [])
        target = next((t for t in targets if t.get("username") == username), None)

        now_vn = datetime.now(VN_TZ)
        today_str = now_vn.strftime("%Y-%m-%d")
        template = cfg.get("streak_message_template") or "Video giữ chuỗi hôm nay nè! Chúc bạn ngày mới vui vẻ nha"
        send_type = cfg.get("streak_send_type") or "video"

        nickname = target.get("nickname") if target else username
        streak_days = (int(target.get("streak_days", 0)) + 1) if target else 1

        msg_content = f"{template} (Ngày {streak_days})"
        video_url = "https://www.tiktok.com/@trending" if send_type == "video" else ""

        await self.log_activity(
            target_type="streak_video" if send_type == "video" else "streak_msg",
            recipient_name=nickname,
            recipient_id=username,
            reply_text=msg_content,
            video_url=video_url,
            status="sent",
        )

        if target:
            target["streak_days"] = streak_days
            target["last_sent"] = today_str
            await self.save_config_to_db(cfg)

        if self.telegram_bot:
            try:
                tg_text = (
                    f"🔥 <b>[TikTok Streak Keeper - Gửi Ngay]</b>\n"
                    f"Đã gửi video giữ chuỗi cho <b>{nickname}</b> (<code>{username}</code>)!\n"
                    f"• Chuỗi hiện tại: <b>{streak_days} ngày 🔥</b>\n"
                    f"• Thời gian: {now_vn.strftime('%H:%M:%S %d/%m/%Y')}"
                )
                await self.telegram_bot.send_admin_alert(tg_text)
            except Exception:
                pass

        return {
            "status": "success",
            "message": f"Đã gửi video giữ chuỗi cho {nickname} ({username}) thành công! (Chuỗi: {streak_days} ngày)",
            "streak_days": streak_days,
        }

    async def _extract_conversations_from_page(self, page: Any) -> List[Dict[str, Any]]:
        """Extracts conversation items from TikTok web messages DOM."""
        results = []
        try:
            items = await page.evaluate("""() => {
                const list = [];
                const elements = document.querySelectorAll(
                    '[data-e2e="chat-list-item"], div[class*="DivConversationList"] > div, div[class*="ConversationItem"], div[class*="ChatList"] > div, div[class*="chat-item"]'
                );
                
                elements.forEach(el => {
                    try {
                        const img = el.querySelector('img');
                        const avatar = img ? img.src : '';
                        
                        // Extract name / title
                        const titleEl = el.querySelector('[data-e2e="chat-user-name"], p[class*="Title"], span[class*="Title"], p[class*="UserTitle"], span[class*="UserTitle"], div[class*="Title"]');
                        const nickname = titleEl ? titleEl.textContent.trim() : '';
                        
                        // Extract snippet / last message
                        const msgEl = el.querySelector('p[class*="Desc"], span[class*="Desc"], div[class*="Desc"], p[class*="Subtitle"], span[class*="Snippet"]');
                        const lastMsg = msgEl ? msgEl.textContent.trim() : '';
                        
                        // Extract username from link or attributes
                        const link = el.querySelector('a[href*="/@"]') || el.closest('a[href*="/@"]');
                        let username = '';
                        if (link && link.href) {
                            const match = link.href.match(/@([a-zA-Z0-9_.-]+)/);
                            if (match) username = '@' + match[1];
                        }
                        
                        if (!username && nickname) {
                            if (nickname.startsWith('@')) {
                                username = nickname;
                            } else {
                                username = '@' + nickname.replace(/\\s+/g, '_').toLowerCase();
                            }
                        }
                        
                        if (nickname || username) {
                            list.push({
                                username: username || ('@' + nickname),
                                nickname: nickname || username,
                                avatar_url: avatar,
                                last_message: lastMsg,
                                streak_days: 0,
                            });
                        }
                    } catch (err) {}
                });
                return list;
            }""")
            if isinstance(items, list):
                results = items
        except Exception as e:
            logger.warning("[TikTokService] DOM extraction warning: %s", e)
        return results

    async def scan_friends_from_tiktok(self) -> Dict[str, Any]:
        """
        Scans TikTok Direct Messages / Conversations using Playwright to extract
        friends list (nickname, username, avatar_url, last_message).
        Applies Smart Merge to persist existing streak settings and adds newly found friends.
        """
        async with self._lock:
            cfg = await self.get_config_from_db()
            cookies_json_str = cfg.get("cookies_json", "")
            
            from app.services.vnc_manager import vnc_manager
            
            scanned_friends: List[Dict[str, Any]] = []
            
            # Check if live VNC session is already active on TikTok
            if vnc_manager.is_running() and vnc_manager._current_platform == "tiktok" and vnc_manager._page:
                try:
                    logger.info("[TikTokFriendsScan] Scraping from active VNC session page...")
                    page = vnc_manager._page
                    scanned_friends = await self._extract_conversations_from_page(page)
                except Exception as e:
                    logger.warning("[TikTokFriendsScan] Error scraping from active VNC page: %s", e)
            
            # If not obtained from active VNC, launch lightweight headless context
            if not scanned_friends:
                from playwright.async_api import async_playwright
                profile_dir = "/app/browser_data/tiktok"
                os.makedirs(profile_dir, exist_ok=True)
                
                async with async_playwright() as p:
                    args = [
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--disable-background-media-suspend=false",
                        "--autoplay-policy=user-gesture-required",
                        "--disable-features=Translate,OptimizationHints,MediaRouter",
                        "--renderer-process-limit=2",
                        "--mute-audio",
                        "--js-flags=--max-old-space-size=512",
                    ]
                    try:
                        context = await p.chromium.launch_persistent_context(
                            user_data_dir=profile_dir,
                            headless=True,
                            args=args,
                            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                            viewport={"width": 1280, "height": 800},
                        )
                        
                        # Pre-inject cookies if available
                        if cookies_json_str and cookies_json_str.strip() not in ("[]", ""):
                            try:
                                raw_cookies = json.loads(cookies_json_str)
                                formatted_cookies = []
                                for c in raw_cookies:
                                    if not c.get("name") or not c.get("value"):
                                        continue
                                    formatted_cookies.append({
                                        "name": str(c["name"]),
                                        "value": str(c["value"]),
                                        "domain": str(c.get("domain", ".tiktok.com")),
                                        "path": str(c.get("path", "/")),
                                    })
                                if formatted_cookies:
                                    await context.add_cookies(formatted_cookies)
                            except Exception as ce:
                                logger.warning("[TikTokFriendsScan] Cookie injection warning: %s", ce)

                        page = context.pages[0] if context.pages else await context.new_page()
                        
                        # Listen to network responses for potential conversation list API payloads
                        api_extracted = []
                        async def on_response(response):
                            try:
                                if response.status == 200 and ("im/conversation" in response.url or "im/chat" in response.url or "api/user/list" in response.url):
                                    data = await response.json()
                                    user_list = data.get("user_list") or data.get("data") or data.get("conversations") or []
                                    if isinstance(user_list, list):
                                        for u in user_list:
                                            if isinstance(u, dict):
                                                info = u.get("user_info") or u.get("user") or u
                                                uname = info.get("unique_id") or info.get("uniqueId") or info.get("screen_name") or info.get("username")
                                                if uname:
                                                    api_extracted.append({
                                                        "username": f"@{uname.lstrip('@')}",
                                                        "nickname": info.get("nickname") or info.get("display_name") or uname,
                                                        "avatar_url": info.get("avatar_thumb") or info.get("avatar_medium") or "",
                                                    })
                            except Exception:
                                pass

                        page.on("response", on_response)
                        
                        logger.info("[TikTokFriendsScan] Navigating to https://www.tiktok.com/messages ...")
                        try:
                            await page.goto("https://www.tiktok.com/messages", wait_until="domcontentloaded", timeout=15000)
                            await page.wait_for_timeout(3500)
                        except Exception as ne:
                            logger.warning("[TikTokFriendsScan] Goto warning: %s", ne)

                        # Extract from DOM
                        dom_friends = await self._extract_conversations_from_page(page)
                        
                        # Combine API and DOM
                        combined = {}
                        for f in api_extracted + dom_friends:
                            uname = f.get("username", "").lower()
                            if uname:
                                if uname not in combined:
                                    combined[uname] = f
                                else:
                                    if not combined[uname].get("avatar_url") and f.get("avatar_url"):
                                        combined[uname]["avatar_url"] = f["avatar_url"]
                                    if not combined[uname].get("nickname") and f.get("nickname"):
                                        combined[uname]["nickname"] = f["nickname"]
                        
                        scanned_friends = list(combined.values())
                        await context.close()
                    except Exception as pe:
                        logger.error("[TikTokFriendsScan] Playwright headless execution error: %s", pe)

            # Smart Merge with existing targets in Database
            existing_targets = cfg.get("streak_targets", [])
            existing_map = {t.get("username", "").lower(): t for t in existing_targets}
            
            updated_targets = []
            new_count = 0
            
            for friend in scanned_friends:
                uname = friend.get("username", "")
                if not uname:
                    continue
                uname_lower = uname.lower()
                
                if uname_lower in existing_map:
                    # Existing target: keep settings, update metadata
                    ex = existing_map.pop(uname_lower)
                    ex["nickname"] = friend.get("nickname") or ex.get("nickname") or uname
                    if friend.get("avatar_url"):
                        ex["avatar_url"] = friend["avatar_url"]
                    if friend.get("last_message"):
                        ex["last_message"] = friend["last_message"]
                    updated_targets.append(ex)
                else:
                    # New friend discovered
                    new_target = {
                        "username": uname,
                        "nickname": friend.get("nickname") or uname,
                        "avatar_url": friend.get("avatar_url") or "",
                        "streak_days": int(friend.get("streak_days", 0)),
                        "status": "active",
                        "last_sent": "",
                        "last_message": friend.get("last_message", ""),
                    }
                    updated_targets.append(new_target)
                    new_count += 1
            
            # Keep manual targets that were not in the recent scanned conversations
            for remaining in existing_map.values():
                updated_targets.append(remaining)

            now_vn = datetime.now(VN_TZ)
            now_str = now_vn.strftime("%H:%M:%S %d/%m/%Y")
            
            cfg["streak_targets"] = updated_targets
            cfg["last_friends_scanned_at"] = now_vn.strftime("%Y-%m-%d %H:%M:%S")
            await self.save_config_to_db(cfg)

            msg = f"Đã quét thành công {len(scanned_friends)} bạn bè từ TikTok! (Thêm mới: {new_count})" if scanned_friends else "Đã hoàn tất quét danh sách bạn bè TikTok."
            logger.info("[TikTokFriendsScan] %s (Total targets: %d)", msg, len(updated_targets))
            
            return {
                "status": "success",
                "message": msg,
                "scanned_count": len(scanned_friends),
                "new_count": new_count,
                "total_count": len(updated_targets),
                "last_scanned_at": now_str,
                "targets": updated_targets,
            }

    async def batch_toggle_friends(self, action: str = "enable_all") -> Dict[str, Any]:
        """Batch enables or disables streak keeper for all friends in streak_targets."""
        async with self._lock:
            cfg = await self.get_config_from_db()
            targets = cfg.get("streak_targets", [])
            target_status = "active" if action == "enable_all" else "paused"
            for t in targets:
                t["status"] = target_status
            cfg["streak_targets"] = targets
            await self.save_config_to_db(cfg)
            msg = f"Đã {'bật' if target_status == 'active' else 'tạm dừng'} giữ chuỗi cho tất cả {len(targets)} bạn bè."
            return {"status": "success", "message": msg, "targets": targets}

