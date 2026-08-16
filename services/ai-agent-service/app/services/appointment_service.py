import asyncio
from datetime import datetime, timezone, timedelta
import hashlib
import json
import logging
import re
from typing import Any, Dict, List, Optional

import psycopg
from psycopg.rows import dict_row

from app.config import settings
from app.core.llm_router import LlmRouter

logger = logging.getLogger(__name__)

VN_TZ = timezone(timedelta(hours=7))


class AppointmentService:
    """
    Intelligent Appointment & Scheduling Detection Service.
    Analyzes incoming Facebook Messenger threads using a two-tier hybrid model:
    - Tier 1: Fast heuristic keyword filter (0 LLM tokens, O(1) latency).
    - Tier 2: LLM Structured Extraction (via Groq/OpenRouter Multi-Key Pool).
    Also includes a background reminder dispatcher to proactively alert the owner
    1 hour (60 minutes) prior to scheduled appointment deadlines.
    """

    # Fast heuristic keywords for scheduling and meeting intent in Vietnamese
    APPOINTMENT_KEYWORDS = [
        "hẹn", "lịch", "gặp", "call", "họp", "cà phê", "cafe", "ăn trưa", "ăn tối",
        "nhậu", "mai", "mốt", "chiều nay", "tối nay", "sáng mai", "chiều mai", "tối mai",
        "thứ 2", "thứ 3", "thứ 4", "thứ 5", "thứ 6", "thứ 7", "chủ nhật", "tuần sau",
        "ngày mai", "hôm sau", "mấy giờ", "lúc", "giờ", "rảnh không", "rảnh k", "rảnh ko",
        "free ko", "free k", "free không", "slot", "meeting", "meet", "zoom", "trao đổi",
        "ghé qua", "qua em", "qua anh", "qua nhà", "bàn việc", "nói chuyện", "tiện không"
    ]

    def __init__(self, llm_router: LlmRouter):
        self.llm_router = llm_router

    def _fast_keyword_filter(self, text: str) -> bool:
        """Fast O(N) substring / token check for scheduling intents."""
        if not text:
            return False
        normalized = text.lower()
        return any(kw in normalized for kw in self.APPOINTMENT_KEYWORDS)

    @staticmethod
    def compute_message_hash(messages: List[str]) -> str:
        """Computes a stable SHA256 hash for incoming messages to prevent duplicate prompts."""
        raw = "||".join(m.strip() for m in messages if m.strip())
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _parse_scheduled_datetime(
        self,
        proposed_time_str: str,
        scheduled_iso: Optional[str] = None
    ) -> Optional[datetime]:
        """
        Parses ISO format or falls back to intelligent Vietnamese time expressions.
        Guarantees timezone-aware datetime in Asia/Ho_Chi_Minh (+07:00).
        """
        now_vn = datetime.now(VN_TZ)

        # 1. Try ISO string from LLM
        if scheduled_iso:
            try:
                dt = datetime.fromisoformat(scheduled_iso.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=VN_TZ)
                return dt.astimezone(VN_TZ)
            except Exception:
                pass

        # 2. Fallback heuristic parser for Vietnamese time strings
        if not proposed_time_str:
            return None

        clean = proposed_time_str.lower()
        target_date = now_vn.date()

        # Day offset detection
        if "ngày mai" in clean or "sáng mai" in clean or "chiều mai" in clean or "tối mai" in clean or "mai" in clean:
            target_date = target_date + timedelta(days=1)
        elif "ngày mốt" in clean or "mốt" in clean:
            target_date = target_date + timedelta(days=2)
        elif "hôm nay" in clean or "chiều nay" in clean or "tối nay" in clean:
            target_date = target_date

        # Specific day of week (thứ 2, thứ 3, ...)
        dow_match = re.search(r"thứ\s*([2-7]|hai|ba|tư|bốn|năm|sáu|bảy)|chủ\s*nhật", clean)
        if dow_match:
            dow_map = {
                "2": 0, "hai": 0, "3": 1, "ba": 1, "4": 2, "tư": 2, "bốn": 2,
                "5": 3, "năm": 3, "6": 4, "sáu": 4, "7": 5, "bảy": 5, "chủ nhật": 6
            }
            token = dow_match.group(0).replace("thứ", "").strip()
            target_dow = dow_map.get(token, -1)
            if target_dow >= 0:
                current_dow = now_vn.weekday()
                days_ahead = (target_dow - current_dow) % 7
                if days_ahead == 0 and "tuần sau" in clean:
                    days_ahead = 7
                elif days_ahead == 0 and ("sáng" in clean or "chiều" in clean or "tối" in clean):
                    pass
                elif days_ahead == 0:
                    days_ahead = 7
                target_date = now_vn.date() + timedelta(days=days_ahead)

        # Explicit DD/MM/YYYY match
        date_match = re.search(r"(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{4}))?", clean)
        if date_match:
            try:
                day = int(date_match.group(1))
                month = int(date_match.group(2))
                year = int(date_match.group(3)) if date_match.group(3) else now_vn.year
                target_date = datetime(year, month, day).date()
            except Exception:
                pass

        # Time of day (HH:MM or Xh, XhY)
        hour = 9
        minute = 0

        time_match = re.search(r"(\d{1,2})(?::(\d{2})|h(\d{2})?|g(\d{2})?)", clean)
        if time_match:
            try:
                hour = int(time_match.group(1))
                min_part = time_match.group(2) or time_match.group(3) or time_match.group(4)
                minute = int(min_part) if min_part else 0
                if "chiều" in clean and hour < 12:
                    hour += 12
                elif "tối" in clean and hour < 12:
                    hour += 12
            except Exception:
                pass
        elif "sáng" in clean:
            hour, minute = 9, 0
        elif "chiều" in clean:
            hour, minute = 14, 30
        elif "tối" in clean:
            hour, minute = 19, 30

        try:
            return datetime(
                target_date.year, target_date.month, target_date.day,
                hour, minute, 0, tzinfo=VN_TZ
            )
        except Exception:
            return None

    async def extract_appointment_intent(
        self,
        sender_name: str,
        incoming_messages: List[str]
    ) -> Optional[Dict[str, Any]]:
        """
        Analyzes conversation messages to detect and extract appointment parameters.
        Returns a structured dictionary if an appointment is detected, or None.
        """
        if not incoming_messages:
            return None

        full_text = "\n".join(f"- {m}" for m in incoming_messages[-5:])
        if not self._fast_keyword_filter(full_text):
            logger.debug("[AppointmentService] No appointment keywords found; skipping LLM extraction.")
            return None

        now_vn = datetime.now(VN_TZ)
        now_str = now_vn.strftime("%H:%M, %A ngày %d/%m/%Y")
        now_iso = now_vn.isoformat()

        system_prompt = (
            "Bạn là trợ lý AI thông minh 'Tiểu Bảo Bảo' chuyên phân tích tin nhắn và trích xuất lịch hẹn / gặp mặt / gọi điện.\n"
            f"Thời gian hiện tại: {now_str} (ISO: {now_iso}, Múi giờ Việt Nam +07:00).\n\n"
            "NHIỆM VỤ:\n"
            "Phân tích tin nhắn từ người gửi để xem họ có ý định ĐẶT LỊCH / HẸN GẶP / HỌP / GỌI ĐIỆN / CÀ PHÊ / ĂN UỐNG / TRAO ĐỔI CÔNG VIỆC hay không.\n\n"
            "QUY TẮC TRẢ VỀ:\n"
            "Chỉ trả về DUY NHẤT một chuỗi JSON hợp lệ với cấu trúc sau (không kèm lời dẫn hay markdown code block ngoài JSON):\n"
            "{\n"
            '  "is_appointment": true,\n'
            '  "summary": "Tóm tắt ngắn gọn mục đích cuộc hẹn (ví dụ: Cà phê bàn dự án)",\n'
            '  "proposed_time": "Thời gian hiển thị (ví dụ: 09:00 sáng Thứ Hai 17/08/2026)",\n'
            '  "scheduled_iso": "Thời gian theo chuẩn ISO 8601 múi giờ +07:00 (ví dụ: 2026-08-17T09:00:00+07:00)",\n'
            '  "location": "Địa điểm hoặc hình thức hẹn (ví dụ: Quán Highlands Coffee hoặc Google Meet hoặc Chưa rõ)",\n'
            '  "confidence": "high"\n'
            "}\n"
            "Nếu tin nhắn KHÔNG phải là lời hẹn (chỉ là câu hỏi thăm, nhắn tin bình thường, phàn nàn...), trả về: {\"is_appointment\": false}"
        )

        user_content = f"Người gửi: {sender_name}\nNội dung các tin nhắn gần nhất:\n{full_text}"

        try:
            resp = await self.llm_router.complete(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.1,
                max_tokens=350,
            )

            if not resp:
                logger.warning("[AppointmentService] LLM returned empty response.")
                return None

            content = resp.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            cleaned_json = re.sub(r"^```(?:json)?\s*", "", content)
            cleaned_json = re.sub(r"\s*```$", "", cleaned_json).strip()

            parsed = json.loads(cleaned_json)
            if parsed.get("is_appointment") and parsed.get("confidence") in ["high", "medium"]:
                prop_time = parsed.get("proposed_time", "")
                sched_iso = parsed.get("scheduled_iso")
                dt = self._parse_scheduled_datetime(prop_time, sched_iso)
                parsed["scheduled_at"] = dt

                logger.info(
                    "[AppointmentService] Detected appointment from '%s': %s at %s (Scheduled At: %s)",
                    sender_name, parsed.get("summary"), prop_time, dt
                )
                return parsed

        except Exception as e:
            logger.warning("[AppointmentService] Error extracting appointment intent via LLM: %s", e)

        return None

    async def save_if_new(
        self,
        thread_href: str,
        sender_name: str,
        original_message: str,
        msg_hash: str,
        summary: str,
        proposed_time: str,
        location: str = "",
        confidence: str = "high",
        scheduled_at: Optional[datetime] = None
    ) -> Optional[int]:
        """Saves a detected appointment if it doesn't already exist. Returns record ID or None."""
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT id FROM facebook_appointments WHERE msg_hash = %s LIMIT 1",
                        (msg_hash,)
                    )
                    existing = await cur.fetchone()
                    if existing:
                        logger.debug("[AppointmentService] Appointment already registered for hash %s", msg_hash[:8])
                        return None

                    await cur.execute(
                        """
                        INSERT INTO facebook_appointments
                        (thread_href, sender_name, original_message, msg_hash, summary, proposed_time, location, confidence, status, scheduled_at, reminder_sent, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s, FALSE, NOW(), NOW())
                        RETURNING id
                        """,
                        (thread_href, sender_name, original_message, msg_hash, summary, proposed_time, location, confidence, scheduled_at)
                    )
                    row = await cur.fetchone()
                    await conn.commit()
                    return row[0] if row else None
        except Exception as e:
            logger.error("[AppointmentService] DB error saving appointment: %s", e)
            return None

    async def update_status(
        self,
        appointment_id: int,
        status: str,
        telegram_message_id: Optional[int] = None
    ) -> bool:
        """Updates the status and optional telegram message ID of an appointment."""
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    if telegram_message_id:
                        await cur.execute(
                            "UPDATE facebook_appointments SET status = %s, telegram_message_id = %s, updated_at = NOW() WHERE id = %s",
                            (status, telegram_message_id, appointment_id)
                        )
                    else:
                        await cur.execute(
                            "UPDATE facebook_appointments SET status = %s, updated_at = NOW() WHERE id = %s",
                            (status, appointment_id)
                        )
                    await conn.commit()
                    return cur.rowcount > 0
        except Exception as e:
            logger.error("[AppointmentService] DB error updating appointment #%d: %s", appointment_id, e)
            return False

    async def get_appointment_by_id(self, appointment_id: int) -> Optional[Dict[str, Any]]:
        """Fetches single appointment record by ID."""
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url, row_factory=dict_row) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT * FROM facebook_appointments WHERE id = %s LIMIT 1",
                        (appointment_id,)
                    )
                    row = await cur.fetchone()
                    return dict(row) if row else None
        except Exception as e:
            logger.error("[AppointmentService] DB error fetching appointment #%d: %s", appointment_id, e)
            return None

    async def get_upcoming_appointments(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Retrieves list of upcoming and confirmed/pending appointments."""
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url, row_factory=dict_row) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        SELECT id, sender_name, summary, proposed_time, location, status, original_message, scheduled_at, reminder_sent, created_at
                        FROM facebook_appointments
                        WHERE status IN ('confirmed', 'pending')
                        ORDER BY COALESCE(scheduled_at, created_at) ASC, created_at DESC
                        LIMIT %s
                        """,
                        (limit,)
                    )
                    rows = await cur.fetchall()
                    return [dict(r) for r in rows]
        except Exception as e:
            logger.error("[AppointmentService] DB error fetching upcoming appointments: %s", e)
            return []

    async def check_and_dispatch_reminders(self, telegram_bot: Any) -> int:
        """
        Background Dispatcher:
        Scans confirmed appointments and triggers proactive 1-hour reminders.
        Condition: status = 'confirmed', reminder_sent = FALSE, and scheduled_at is within 60 minutes.
        """
        if not telegram_bot or not telegram_bot.chat_id:
            return 0

        dispatched_count = 0
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url, row_factory=dict_row) as conn:
                async with conn.cursor() as cur:
                    # Select confirmed appointments due within next 60 minutes (and not older than 30 mins in past)
                    await cur.execute(
                        """
                        SELECT id, thread_href, sender_name, summary, proposed_time, location, scheduled_at
                        FROM facebook_appointments
                        WHERE status = 'confirmed'
                          AND reminder_sent = FALSE
                          AND scheduled_at IS NOT NULL
                          AND scheduled_at <= (NOW() + INTERVAL '60 minutes')
                          AND scheduled_at >= (NOW() - INTERVAL '30 minutes')
                        ORDER BY scheduled_at ASC
                        """
                    )
                    rows = await cur.fetchall()
                    if not rows:
                        return 0

                    for apt in rows:
                        apt_id = apt["id"]
                        sender = apt["sender_name"] or "Liên hệ"
                        summary = apt["summary"] or "Lịch hẹn"
                        prop_time = apt["proposed_time"] or "Sắp diễn ra"
                        loc = apt["location"] or "Chưa rõ địa điểm"

                        reminder_text = (
                            f"⏰ *[TIỂU BẢO BẢO] NHẮC NHỞ: ANH CÓ LỊCH HẸN SAU 1 TIẾNG NỮA!*\n\n"
                            f"👤 *Người hẹn:* `{sender}`\n"
                            f"⏰ *Thời gian:* *{prop_time}*\n"
                            f"📍 *Địa điểm:* {loc}\n"
                            f"📝 *Nội dung:* {summary}\n\n"
                            f"👉 *Anh nhớ sắp xếp thời gian và chuẩn bị xuất phát nhé!*"
                        )

                        reply_markup = {
                            "inline_keyboard": [
                                [
                                    {"text": f"💬 Nhắn tin cho {sender}", "callback_data": f"apt_reply:{apt_id}"},
                                    {"text": "✅ Đã chuẩn bị xong", "callback_data": f"apt_ready:{apt_id}"}
                                ]
                            ]
                        }

                        sent = await telegram_bot.send_message(
                            chat_id=telegram_bot.chat_id,
                            text=reminder_text,
                            reply_markup=reply_markup
                        )

                        if sent:
                            dispatched_count += 1
                            await cur.execute(
                                "UPDATE facebook_appointments SET reminder_sent = TRUE, reminder_sent_at = NOW(), updated_at = NOW() WHERE id = %s",
                                (apt_id,)
                            )
                            await conn.commit()
                            logger.info(
                                "[AppointmentService] Proactive 1-hour reminder dispatched for appointment #%d ('%s')",
                                apt_id, sender
                            )

        except Exception as e:
            logger.error("[AppointmentService] Error dispatching appointment reminders: %s", e)

        return dispatched_count

    async def process_thread_and_notify(
        self,
        thread_href: str,
        sender_name: str,
        incoming_messages: List[str],
        telegram_bot: Any
    ) -> Optional[int]:
        """
        Full orchestration pipeline:
        1. Analyzes incoming messages for scheduling intent.
        2. Persists new appointments into DB in 'pending' state.
        3. Dispatches interactive Telegram message with Inline Keyboard.
        4. Updates appointment record with telegram_message_id for instant callback updates.
        """
        if not incoming_messages or not telegram_bot:
            return None

        msg_hash = self.compute_message_hash(incoming_messages)
        intent = await self.extract_appointment_intent(sender_name, incoming_messages)
        if not intent:
            return None

        summary = intent.get("summary", "Lịch hẹn mới")
        proposed_time = intent.get("proposed_time", "Chưa xác định")
        location = intent.get("location", "Chưa rõ")
        confidence = intent.get("confidence", "high")
        scheduled_at = intent.get("scheduled_at")
        last_msg = incoming_messages[-1] if incoming_messages else ""

        # Check DB to prevent double prompting
        apt_id = await self.save_if_new(
            thread_href=thread_href,
            sender_name=sender_name,
            original_message=last_msg,
            msg_hash=msg_hash,
            summary=summary,
            proposed_time=proposed_time,
            location=location,
            confidence=confidence,
            scheduled_at=scheduled_at
        )

        if not apt_id:
            logger.debug("[AppointmentService] Appointment already prompted for '%s'", sender_name)
            return None

        # Build Interactive Telegram Notification
        tg_text = (
            f"📅 *[TIỂU BẢO BẢO] PHÁT HIỆN LỜI HẸN TỪ FACEBOOK*\n\n"
            f"👤 *Người gửi:* `{sender_name}`\n"
            f"💬 *Tin nhắn:* \"_{last_msg}_\"\n"
            f"⏰ *Thời gian đề xuất:* *{proposed_time}*\n"
            f"📍 *Địa điểm:* {location}\n"
            f"📝 *Nội dung:* {summary}\n\n"
            f"👉 *Anh có muốn đặt/lưu lịch hẹn này không?*"
        )

        # Inline Keyboard Buttons
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "✅ Đặt lịch ngay", "callback_data": f"apt_confirm:{apt_id}"},
                    {"text": "❌ Bỏ qua", "callback_data": f"apt_dismiss:{apt_id}"}
                ],
                [
                    {"text": f"💬 Trả lời {sender_name}", "callback_data": f"apt_reply:{apt_id}"}
                ]
            ]
        }

        # Send to Telegram
        chat_id = telegram_bot.chat_id
        if chat_id:
            msg_result = await telegram_bot.send_message_with_result(
                chat_id=chat_id,
                text=tg_text,
                reply_markup=reply_markup
            )
            if msg_result and isinstance(msg_result, dict):
                sent_msg_id = msg_result.get("message_id")
                if sent_msg_id:
                    await self.update_status(apt_id, "pending", telegram_message_id=sent_msg_id)

        logger.info("[AppointmentService] Successfully sent appointment prompt #%d to Telegram", apt_id)
        return apt_id
