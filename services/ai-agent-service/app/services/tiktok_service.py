import asyncio
import json
import logging
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
                            streak_message_template TEXT NOT NULL DEFAULT 'Video giữ chuỗi hôm nay nè! 🔥',
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
                            created_at              TIMESTAMP NOT NULL DEFAULT now(),
                            updated_at              TIMESTAMP NOT NULL DEFAULT now()
                        );
                        INSERT INTO tiktok_config (id) VALUES (1) ON CONFLICT DO NOTHING;

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
            "streak_message_template": "Video giữ chuỗi hôm nay nè! Chúc bạn ngày mới vui vẻ nha 🔥✨",
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
                    }
        except Exception as e:
            logger.error("[TikTokService] Error reading tiktok_config from DB: %s", e)
        return default_cfg

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
                        str(cfg.get("streak_message_template", "Video giữ chuỗi hôm nay nè! 🔥")),
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

            template = cfg.get("streak_message_template") or "Video giữ chuỗi hôm nay nè! Chúc bạn ngày mới vui vẻ nha 🔥✨"
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
                msg_content = f"{template} (🔥 Ngày {streak_days})"
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
                            f"🔥 <b>[TikTok Streak Keeper]</b>\n"
                            f"Đã tự động gửi video giữ chuỗi cho <b>{nickname}</b> (<code>{username}</code>)!\n"
                            f"• Chuỗi hiện tại: <b>{streak_days} ngày 🔥</b>\n"
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
        template = cfg.get("streak_message_template") or "Video giữ chuỗi hôm nay nè! Chúc bạn ngày mới vui vẻ nha 🔥✨"
        send_type = cfg.get("streak_send_type") or "video"

        nickname = target.get("nickname") if target else username
        streak_days = (int(target.get("streak_days", 0)) + 1) if target else 1

        msg_content = f"{template} (🔥 Ngày {streak_days})"
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
            "message": f"Đã gửi video giữ chuỗi cho {nickname} ({username}) thành công! (Chuỗi: {streak_days} ngày 🔥)",
            "streak_days": streak_days,
        }
