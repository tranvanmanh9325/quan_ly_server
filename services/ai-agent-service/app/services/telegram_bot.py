import asyncio
import logging
from typing import Any, Dict, Optional
import httpx
import psycopg

from app.config import settings
from app.core.ssh_client import SshClient
from app.services.ai_agent import AiAgentService

logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self, ai_agent: AiAgentService, ssh_client: SshClient):
        self.ai_agent = ai_agent
        self.ssh_client = ssh_client
        self.appointment_service: Optional[Any] = None
        self.memory_service: Optional[Any] = None  # AgentMemoryService — injected post-construction
        self.token = settings.TELEGRAM_BOT_TOKEN
        self.chat_id = settings.TELEGRAM_CHAT_ID
        self.polling_enabled = settings.TELEGRAM_POLLING_ENABLED
        self._http_client = httpx.AsyncClient(timeout=35.0)
        self._running = False
        self._last_offset = 0
        if hasattr(self.ai_agent, "set_telegram_bot"):
            self.ai_agent.set_telegram_bot(self)

    def set_appointment_service(self, appointment_service: Any) -> None:
        self.appointment_service = appointment_service

    def set_memory_service(self, memory_service: Any) -> None:
        """Inject memory service for /lessons and /memory_stats commands."""
        self.memory_service = memory_service


    @property
    def api_url(self) -> str:
        return f"https://api.telegram.org/bot{self.token}"

    async def send_message(
        self,
        chat_id: str,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: str = "Markdown"
    ) -> bool:
        res = await self.send_message_with_result(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
        return bool(res)

    async def send_message_with_result(
        self,
        chat_id: str,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: str = "Markdown"
    ) -> Optional[Dict[str, Any]]:
        if not self.token or not text:
            return None
        try:
            url = f"{self.api_url}/sendMessage"
            payload: Dict[str, Any] = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
                "link_preview_options": {"is_disabled": True},
            }
            if reply_markup:
                payload["reply_markup"] = reply_markup

            res = await self._http_client.post(url, json=payload)
            if res.status_code == 200:
                data = res.json()
                return data.get("result")

            # Fallback without parse_mode if Markdown entity formatting failed
            if "can't parse entities" in res.text.lower():
                payload.pop("parse_mode", None)
                res2 = await self._http_client.post(url, json=payload)
                if res2.status_code == 200:
                    data2 = res2.json()
                    return data2.get("result")
        except Exception as e:
            logger.error("[TelegramBot] Failed sending message: %s", e)
        return None

    async def edit_message_text(
        self,
        chat_id: str,
        message_id: int,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: str = "Markdown"
    ) -> bool:
        if not self.token or not text:
            return False
        try:
            url = f"{self.api_url}/editMessageText"
            payload: Dict[str, Any] = {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            }
            if reply_markup is not None:
                payload["reply_markup"] = reply_markup

            res = await self._http_client.post(url, json=payload)
            if res.status_code == 200:
                return True
            if "can't parse entities" in res.text.lower():
                payload.pop("parse_mode", None)
                res2 = await self._http_client.post(url, json=payload)
                return res2.status_code == 200
        except Exception as e:
            logger.error("[TelegramBot] Failed editing message text: %s", e)
        return False

    async def answer_callback_query(
        self,
        callback_query_id: str,
        text: Optional[str] = None,
        show_alert: bool = False
    ) -> bool:
        if not self.token or not callback_query_id:
            return False
        try:
            url = f"{self.api_url}/answerCallbackQuery"
            payload: Dict[str, Any] = {"callback_query_id": callback_query_id}
            if text:
                payload["text"] = text
                payload["show_alert"] = show_alert
            res = await self._http_client.post(url, json=payload)
            return res.status_code == 200
        except Exception as e:
            logger.error("[TelegramBot] Failed answering callback query: %s", e)
        return False

    async def send_photo(self, chat_id: str, photo_path: str, caption: Optional[str] = None) -> bool:
        if not self.token or not photo_path:
            return False
        try:
            from pathlib import Path
            p = Path(photo_path)
            if not p.exists():
                logger.error("[TelegramBot] Photo file does not exist: %s", photo_path)
                return False

            url = f"{self.api_url}/sendPhoto"
            with open(p, "rb") as f:
                photo_bytes = f.read()

            files = {"photo": (p.name, photo_bytes, "image/png")}
            data = {"chat_id": chat_id}
            if caption:
                data["caption"] = caption

            res = await self._http_client.post(url, data=data, files=files, timeout=40.0)
            if res.status_code == 200:
                logger.info("[TelegramBot] Photo successfully sent to %s (%s)", chat_id, photo_path)
                return True
            else:
                logger.warning("[TelegramBot] sendPhoto error %d: %s", res.status_code, res.text)
        except Exception as e:
            logger.error("[TelegramBot] Failed sending photo: %s", e, exc_info=True)
        return False

    async def _claim_update(self, update_id: int) -> bool:
        """Ensures at-most-once processing using PostgreSQL unique index."""
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "INSERT INTO processed_telegram_updates (update_id) VALUES (%s) ON CONFLICT (update_id) DO NOTHING",
                        (update_id,),
                    )
                    await conn.commit()
                    return cur.rowcount > 0
        except Exception as e:
            logger.warning("[TelegramBot] Error claiming update %d: %s", update_id, e)
            return True

    async def _handle_callback_query(self, query: Dict[str, Any]) -> None:
        query_id = query.get("id")
        if not query_id:
            return

        data = query.get("data", "")
        message = query.get("message", {})
        chat = message.get("chat", {})
        chat_id = str(chat.get("id", ""))
        message_id = message.get("message_id")

        if not data or not chat_id or not message_id:
            await self.answer_callback_query(query_id)
            return

        # Handle Appointment Confirmation
        if data.startswith("apt_confirm:"):
            try:
                apt_id = int(data.split(":")[1])
                if self.appointment_service:
                    apt = await self.appointment_service.get_appointment_by_id(apt_id)
                    if apt:
                        await self.appointment_service.update_status(apt_id, "confirmed")
                        sender = apt.get("sender_name", "Bạn bè")
                        summary = apt.get("summary", "Lịch hẹn")
                        prop_time = apt.get("proposed_time", "Chưa rõ")
                        loc = apt.get("location", "Chưa rõ")

                        updated_text = (
                            f"✅ *ĐÃ ĐẶT LỊCH HẸN THÀNH CÔNG!*\n\n"
                            f"👤 *Người hẹn:* `{sender}`\n"
                            f"⏰ *Thời gian:* *{prop_time}*\n"
                            f"📍 *Địa điểm:* {loc}\n"
                            f"📝 *Nội dung:* {summary}\n"
                            f"📅 *Trạng thái:* _Đã lưu vào danh mục lịch hẹn của Tiểu Bảo Bảo._"
                        )
                        await self.edit_message_text(chat_id, message_id, updated_text, reply_markup=None)
                        await self.answer_callback_query(query_id, text="✅ Đã lưu lịch hẹn thành công!", show_alert=True)
                        return
            except Exception as e:
                logger.error("[TelegramBot] Error confirming appointment callback: %s", e)

            await self.answer_callback_query(query_id, text="Đã xác nhận lịch hẹn.")

        # Handle Appointment Dismissal
        elif data.startswith("apt_dismiss:"):
            try:
                apt_id = int(data.split(":")[1])
                if self.appointment_service:
                    apt = await self.appointment_service.get_appointment_by_id(apt_id)
                    await self.appointment_service.update_status(apt_id, "dismissed")
                    sender = apt.get("sender_name", "Bạn bè") if apt else "Liên hệ"
                    summary = apt.get("summary", "") if apt else ""

                    dismiss_text = (
                        f"❌ *ĐÃ BỎ QUA LỊCH HẸN*\n\n"
                        f"👤 *Người gửi:* `{sender}`\n"
                        f"📝 *Nội dung:* {summary}\n"
                        f"_(Lịch hẹn này đã bị hủy bỏ và không lưu.)_"
                    )
                    await self.edit_message_text(chat_id, message_id, dismiss_text, reply_markup=None)
                    await self.answer_callback_query(query_id, text="Đã bỏ qua lịch hẹn.")
                    return
            except Exception as e:
                logger.error("[TelegramBot] Error dismissing appointment callback: %s", e)

            await self.answer_callback_query(query_id, text="Đã bỏ qua.")

        # Handle Reply on Facebook
        elif data.startswith("apt_reply:"):
            try:
                apt_id = int(data.split(":")[1])
                if self.appointment_service:
                    apt = await self.appointment_service.get_appointment_by_id(apt_id)
                    sender = apt.get("sender_name", "người này") if apt else "người này"
                    await self.answer_callback_query(query_id)
                    guide_msg = (
                        f"💬 *Để trả lời tin nhắn Facebook cho `{sender}`:*\n"
                        f"Anh hãy soạn tin nhắn theo cú pháp:\n\n"
                        f"`/reply {sender} <Nội dung phản hồi>`\n\n"
                        f"Ví dụ:\n`/reply {sender} Ok em nhé, mai hẹn gặp lúc 9h sáng!`"
                    )
                    await self.send_message(chat_id, guide_msg)
                    return
            except Exception as e:
                logger.error("[TelegramBot] Error processing apt_reply callback: %s", e)

            await self.answer_callback_query(query_id)

        # Handle Ready for Appointment
        elif data.startswith("apt_ready:"):
            try:
                apt_id = int(data.split(":")[1])
                sender = "Bạn bè"
                summary = "Cuộc hẹn"
                prop_time = "Sắp diễn ra"
                loc = "Chưa rõ địa điểm"

                if self.appointment_service:
                    apt = await self.appointment_service.get_appointment_by_id(apt_id)
                    if apt:
                        sender = apt.get("sender_name") or sender
                        summary = apt.get("summary") or summary
                        prop_time = apt.get("proposed_time") or prop_time
                        loc = apt.get("location") or loc

                ready_text = (
                    f"✅ *ĐÃ SẴN SÀNG CHO BUỔI HẸN!*\n\n"
                    f"👤 *Người hẹn:* `{sender}`\n"
                    f"⏰ *Thời gian:* *{prop_time}*\n"
                    f"📍 *Địa điểm:* {loc}\n"
                    f"📝 *Nội dung:* {summary}\n\n"
                    f"🌟 _Tiểu Bảo Bảo chúc anh có buổi gặp mặt thật thuận lợi và đạt kết quả tốt nhất!_"
                )

                # Dismiss inline keyboard buttons and update text
                await self.edit_message_text(chat_id, message_id, ready_text, reply_markup=None)
                await self.answer_callback_query(
                    query_id,
                    text="🌟 Đã ghi nhận! Chúc anh có buổi gặp mặt thành công."
                )
                return
            except Exception as e:
                logger.error("[TelegramBot] Error processing apt_ready callback: %s", e)

            await self.answer_callback_query(query_id)

    async def _handle_command(self, command: str, chat_id: str) -> None:
        parts = command.strip().split(maxsplit=1)
        raw_cmd = parts[0].split("@")[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if raw_cmd in ["/start", "/help"]:
            msg = (
                "🤖 *Tiểu Bảo Bảo — Trợ lý AI Tự Hành & Tự Học*\n\n"
                "📌 *Lệnh quản trị máy chủ:*\n"
                "• /status — Tổng quan trạng thái server\n"
                "• /cpu — Mức sử dụng CPU\n"
                "• /ram — Dung lượng RAM & Swap\n"
                "• /disk — Dung lượng ổ cứng\n"
                "• /lich — Xem danh sách lịch hẹn sắp tới\n"
                "• /ai — Xóa bộ nhớ ngữ cảnh hội thoại\n\n"
                "🧠 *Lệnh quản lý trí nhớ tự học:*\n"
                "• /lessons — Xem bài học đã tích lũy\n"
                "• /lesson\\_add \\<nội dung\\> — Thêm bài học thủ công\n"
                "• /lesson\\_delete \\<id\\> — Xóa một bài học\n"
                "• /memory\\_stats — Thống kê trí nhớ\n\n"
                "💬 *Hoặc chat tự nhiên bằng tiếng Việt!*"
            )
            await self.send_message(chat_id, msg)

        elif raw_cmd in ["/lich", "/schedule"]:
            if self.appointment_service:
                apts = await self.appointment_service.get_upcoming_appointments(limit=10)
                if not apts:
                    await self.send_message(chat_id, "📅 Hiện tại không có lịch hẹn nào đang chờ hoặc đã xác nhận.")
                    return

                lines = ["📅 *DANH SÁCH LỊCH HẸN TỪ FACEBOOK:*\n"]
                for idx, a in enumerate(apts, 1):
                    status_icon = "✅ [Đã xác nhận]" if a.get("status") == "confirmed" else "⏳ [Đang chờ xác nhận]"
                    lines.append(
                        f"*{idx}. {a.get('summary', 'Lịch hẹn')}* {status_icon}\n"
                        f"   • 👤 Người hẹn: `{a.get('sender_name', 'Ẩn danh')}`\n"
                        f"   • ⏰ Thời gian: *{a.get('proposed_time', 'Chưa rõ')}*\n"
                        f"   • 📍 Địa điểm: {a.get('location', 'Chưa rõ')}\n"
                    )
                await self.send_message(chat_id, "\n".join(lines))
            else:
                await self.send_message(chat_id, "Dịch vụ quản lý lịch hẹn chưa sẵn sàng.")

        elif raw_cmd == "/status":
            uptime = await self.ssh_client.execute_command("uptime")
            docker = await self.ssh_client.execute_command("docker ps --format 'table {{.Names}}\t{{.Status}}'")
            msg = f"📊 *Trạng Thái Máy Chủ:*\n\n⏱ `{uptime}`\n\n🐳 *Containers:*\n```{docker}```"
            await self.send_message(chat_id, msg)

        elif raw_cmd == "/cpu":
            cpu = await self.ssh_client.execute_command("top -b -n 1 | head -n 5")
            await self.send_message(chat_id, f"⚡ *CPU Status:*\n```{cpu}```")

        elif raw_cmd == "/ram":
            ram = await self.ssh_client.execute_command("free -h")
            await self.send_message(chat_id, f"💾 *Bộ Nhớ RAM & Swap:*\n```{ram}```")

        elif raw_cmd == "/disk":
            disk = await self.ssh_client.execute_command("df -hT /")
            await self.send_message(chat_id, f"💿 *Dung Lượng Ổ Đĩa:*\n```{disk}```")

        elif raw_cmd == "/ai":
            self.ai_agent.clear_history(chat_id)
            await self.send_message(chat_id, "🧹 Đã xóa lịch sử hội thoại AI. Bạn có thể bắt đầu phiên hỏi mới.")

        # ── Memory / Self-Learning Commands ───────────────────────────────────

        elif raw_cmd == "/lessons":
            if not self.memory_service:
                await self.send_message(chat_id, "⚠️ Memory service chưa sẵn sàng.")
                return
            lessons = await self.memory_service.list_lessons_for_display(limit=10)
            if not lessons:
                await self.send_message(
                    chat_id,
                    "🧠 *BÀI HỌC TỰ TÍCH LŨY*\n\n"
                    "_Chưa có bài học nào. Hãy chat và sửa lỗi cho em để em bắt đầu học nhé!_ 😊",
                )
                return
            lines = ["🧠 *BÀI HỌC ĐÃ TÍCH LŨY* (Top 10)\n"]
            for i, l in enumerate(lessons, 1):
                etype = {"correction": "🔧 Sửa lỗi", "new_knowledge": "📖 Kiến thức", "manual": "✍️ Thủ công"}.get(
                    l.get("event_type", ""), "📌"
                )
                conf = int(float(l.get("confidence", 0)) * 100)
                lines.append(
                    f"{i}️⃣ *[ID:{l['id']}]* {etype} — Tin cậy: `{conf}%` · Dùng: `{l['usage_count']}x`\n"
                    f"   _{l['lesson_text']}_\n"
                )
            lines.append("\n💡 Dùng `/lesson_delete <id>` để xóa bài học sai.")
            await self.send_message(chat_id, "\n".join(lines))

        elif raw_cmd == "/lesson_delete":
            if not self.memory_service:
                await self.send_message(chat_id, "⚠️ Memory service chưa sẵn sàng.")
                return
            if not args.strip().isdigit():
                await self.send_message(chat_id, "❌ Cú pháp: `/lesson_delete <id>`\nVí dụ: `/lesson_delete 3`")
                return
            lesson_id = int(args.strip())
            deleted = await self.memory_service.delete_lesson(lesson_id)
            if deleted:
                await self.send_message(chat_id, f"✅ Đã xóa bài học ID `{lesson_id}` thành công!")
            else:
                await self.send_message(chat_id, f"❌ Không tìm thấy bài học ID `{lesson_id}`.")

        elif raw_cmd == "/lesson_add":
            if not self.memory_service:
                await self.send_message(chat_id, "⚠️ Memory service chưa sẵn sàng.")
                return
            lesson_text = args.strip()
            if not lesson_text or len(lesson_text) < 10:
                await self.send_message(
                    chat_id,
                    "❌ Cú pháp: `/lesson_add <nội dung bài học>`\n"
                    "Ví dụ: `/lesson_add Khi tìm tên người Việt, thử cả hai thứ tự Họ Tên và Tên Họ.`",
                )
                return
            lesson_id = await self.memory_service.add_lesson_manually(lesson_text)
            if lesson_id:
                await self.send_message(
                    chat_id,
                    f"✅ *Đã thêm bài học thủ công (ID: `{lesson_id}`)*\n\n_{lesson_text}_\n\n"
                    f"🧠 Bài học này sẽ được em áp dụng từ lần chat tiếp theo!"
                )
            else:
                await self.send_message(chat_id, "❌ Có lỗi khi lưu bài học. Vui lòng thử lại.")

        elif raw_cmd == "/memory_stats":
            if not self.memory_service:
                await self.send_message(chat_id, "⚠️ Memory service chưa sẵn sàng.")
                return
            stats = await self.memory_service.get_memory_stats()
            msg = (
                "🧠 *THỐNG KÊ TRÍ NHỚ TỰ HỌC CỦA TIỂU BẢO BẢO*\n\n"
                f"📚 *Episodic Memory (Lịch sử sự kiện):*\n"
                f"   • 🔧 Lần bị sửa lỗi: `{stats.get('total_corrections', 0)}`\n"
                f"   • 📖 Kiến thức mới học được: `{stats.get('total_new_knowledge', 0)}`\n"
                f"   • 📋 Tổng sự kiện ghi nhận: `{stats.get('total_memories', 0)}`\n\n"
                f"💡 *Procedural Memory (Bài học đã rút ra):*\n"
                f"   • ✅ Đang hoạt động: `{stats.get('active_lessons', 0)}` bài học\n"
                f"   • 🗄️ Đã lưu trữ: `{stats.get('archived_lessons', 0)}` bài học\n"
                f"   • 🔢 Tổng lần bài học được áp dụng: `{stats.get('total_lesson_usages', 0)}`"
            )
            await self.send_message(chat_id, msg)

        else:
            # Route unrecognized slash command to AI Agent
            reply = await self.ai_agent.chat(chat_id, command)
            await self.send_message(chat_id, reply)


    async def _process_update(self, update: Dict[str, Any]) -> None:
        update_id = update.get("update_id")
        if not update_id or not await self._claim_update(update_id):
            return

        # 1. Handle Inline Keyboard Button Clicks
        callback_query = update.get("callback_query")
        if callback_query:
            await self._handle_callback_query(callback_query)
            return

        # 2. Handle Text Messages
        message = update.get("message") or update.get("edited_message")
        if not message:
            return

        chat = message.get("chat", {})
        chat_id = str(chat.get("id", ""))
        text = (message.get("text") or "").strip()

        if not text or not chat_id:
            return

        # Security check: If configured with a specific TELEGRAM_CHAT_ID, reject unauthorized users
        if self.chat_id and self.chat_id != chat_id:
            logger.warning("[TelegramBot] Unauthorized message from chat_id %s", chat_id)
            await self.send_message(chat_id, "⛔ Bạn không có quyền truy cập bot này.")
            return

        if text.startswith("/"):
            await self._handle_command(text, chat_id)
        else:
            try:
                logger.info("[TelegramBot] Received message from %s: '%s'", chat_id, text[:60])
                reply = await self.ai_agent.chat(chat_id, text)
                logger.info("[TelegramBot] AI reply for %s: '%s'", chat_id, reply[:60])
                await self.send_message(chat_id, reply)
            except Exception as err:
                logger.error("[TelegramBot] Error processing message from %s: %s", chat_id, err, exc_info=True)
                await self.send_message(chat_id, "Xin lỗi, đã xảy ra lỗi trong quá trình xử lý tin nhắn. Vui lòng thử lại sau.")

    async def start_polling(self) -> None:
        if not self.token or not self.polling_enabled:
            logger.info("[TelegramBot] Polling disabled or token missing.")
            return

        self._running = True
        logger.info("[TelegramBot] Starting async long-polling...")

        backoff = 2
        while self._running:
            try:
                url = f"{self.api_url}/getUpdates"
                params = {
                    "offset": self._last_offset + 1 if self._last_offset > 0 else 0,
                    "timeout": 20,
                }
                res = await self._http_client.get(url, params=params)

                if res.status_code == 200:
                    data = res.json()
                    updates = data.get("result", [])
                    for u in updates:
                        self._last_offset = max(self._last_offset, u.get("update_id", 0))
                        asyncio.create_task(self._process_update(u))
                    backoff = 2

                elif res.status_code == 409:
                    logger.warning("[TelegramBot] 409 Conflict — another polling instance active. Backing off for %ds.", backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(60, backoff * 2)

                else:
                    logger.warning("[TelegramBot] getUpdates returned %d: %s", res.status_code, res.text)
                    await asyncio.sleep(5)

            except Exception as e:
                logger.error("[TelegramBot] Polling error: %s", e)
                await asyncio.sleep(5)

    def stop(self) -> None:
        self._running = False
