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

        system_prompt = (
            "Bạn là trợ lý AI thông minh 'Tiểu Bảo Bảo' chuyên phân tích tin nhắn và trích xuất lịch hẹn / gặp mặt / gọi điện.\n"
            f"Thời gian hiện tại: {now_str} (Giờ Việt Nam).\n\n"
            "NHIỆM VỤ:\n"
            "Phân tích tin nhắn từ người gửi để xem họ có ý định ĐẶT LỊCH / HẸN GẶP / HỌP / GỌI ĐIỆN / CÀ PHÊ / ĂN UỐNG / TRAO ĐỔI CÔNG VIỆC hay không.\n\n"
            "QUY TẮC TRẢ VỀ:\n"
            "Chỉ trả về DUY NHẤT một chuỗi JSON hợp lệ với cấu trúc sau (không kèm lời dẫn hay markdown code block ngoài JSON):\n"
            "{\n"
            '  "is_appointment": true,\n'
            '  "summary": "Tóm tắt ngắn gọn mục đích cuộc hẹn (ví dụ: Cà phê bàn dự án)",\n'
            '  "proposed_time": "Thời gian được đề xuất (ví dụ: 09:00 sáng Thứ Hai 17/08/2026)",\n'
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
                max_tokens=300,
            )

            if not resp:
                logger.warning("[AppointmentService] LLM returned empty response.")
                return None

            content = resp.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            # Clean JSON formatting if wrapped in ```json
            cleaned_json = re.sub(r"^```(?:json)?\s*", "", content)
            cleaned_json = re.sub(r"\s*```$", "", cleaned_json).strip()

            parsed = json.loads(cleaned_json)
            if parsed.get("is_appointment") and parsed.get("confidence") in ["high", "medium"]:
                logger.info(
                    "[AppointmentService] Detected appointment from '%s': %s at %s",
                    sender_name, parsed.get("summary"), parsed.get("proposed_time")
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
        confidence: str = "high"
    ) -> Optional[int]:
        """Saves a detected appointment if it doesn't already exist. Returns record ID or None."""
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    # Check if this exact message hash has already been registered
                    await cur.execute(
                        "SELECT id FROM facebook_appointments WHERE msg_hash = %s LIMIT 1",
                        (msg_hash,)
                    )
                    existing = await cur.fetchone()
                    if existing:
                        logger.debug("[AppointmentService] Appointment already registered for hash %s", msg_hash[:8])
                        return None

                    # Insert new pending appointment
                    await cur.execute(
                        """
                        INSERT INTO facebook_appointments
                        (thread_href, sender_name, original_message, msg_hash, summary, proposed_time, location, confidence, status, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending', NOW(), NOW())
                        RETURNING id
                        """,
                        (thread_href, sender_name, original_message, msg_hash, summary, proposed_time, location, confidence)
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
                        SELECT id, sender_name, summary, proposed_time, location, status, original_message, created_at
                        FROM facebook_appointments
                        WHERE status IN ('confirmed', 'pending')
                        ORDER BY created_at DESC
                        LIMIT %s
                        """,
                        (limit,)
                    )
                    rows = await cur.fetchall()
                    return [dict(r) for r in rows]
        except Exception as e:
            logger.error("[AppointmentService] DB error fetching upcoming appointments: %s", e)
            return []

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
            confidence=confidence
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
