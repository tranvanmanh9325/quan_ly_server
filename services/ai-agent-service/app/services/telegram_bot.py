import asyncio
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx
import psycopg

from app.config import settings
from app.core.brain_core import VN_TZ
from app.core.db import get_db_connection
from app.core.http_client import http_client_manager
from app.core.ssh_client import SshClient
from app.core.telegram_formatter import TelegramFormatter
from app.services.ai_agent import AiAgentService
from app.services.media_processor import (
    ArchiveInvalidPasswordError,
    ArchivePasswordRequiredError,
    MediaProcessor,
    extract_password_from_text,
)

logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self, ai_agent: AiAgentService, ssh_client: SshClient):
        self.ai_agent = ai_agent
        self.ssh_client = ssh_client
        self.appointment_service: Optional[Any] = None
        self.memory_service: Optional[Any] = None  # AgentMemoryService — injected post-construction
        self.dream_engine: Optional[Any] = None    # SubconsciousDreamEngine — injected post-construction
        self.token = settings.TELEGRAM_BOT_TOKEN
        self.chat_id = settings.TELEGRAM_CHAT_ID
        self.polling_enabled = settings.TELEGRAM_POLLING_ENABLED
        self._running = False
        self._last_offset = 0
        # Pending encrypted archive sessions waiting for password: chat_id -> dict
        self._pending_archives: Dict[str, Dict[str, Any]] = {}
        # Reuse the singleton http_client to avoid spawning extra connection pools
        self._media = MediaProcessor(http_client=http_client_manager.get_client())
        if hasattr(self.ai_agent, "set_telegram_bot"):
            self.ai_agent.set_telegram_bot(self)

    @property
    def _http_client(self) -> httpx.AsyncClient:
        return http_client_manager.get_client()

    def set_appointment_service(self, appointment_service: Any) -> None:
        self.appointment_service = appointment_service

    def set_memory_service(self, memory_service: Any) -> None:
        """Inject memory service for /lessons and /memory_stats commands."""
        self.memory_service = memory_service

    def set_dream_engine(self, dream_engine: Any) -> None:
        """Inject SubconsciousDreamEngine for morning epiphany delivery and /dream commands."""
        self.dream_engine = dream_engine

    @property
    def api_url(self) -> str:
        return f"https://api.telegram.org/bot{self.token}"

    async def send_chat_action(self, chat_id: str, action: str = "typing") -> None:
        """Sends chat action status (e.g. 'typing') to Telegram."""
        try:
            url = f"{self.api_url}/sendChatAction"
            payload = {"chat_id": chat_id, "action": action}
            await self._http_client.post(url, json=payload, timeout=5.0)
        except Exception as e:
            logger.debug("[TelegramBot] sendChatAction (%s) error: %s", action, e)

    async def _send_typing_heartbeat(self, chat_id: str, stop_event: asyncio.Event) -> None:
        """Periodically renews the Telegram typing indicator every 4 seconds."""
        while not stop_event.is_set():
            await self.send_chat_action(chat_id, "typing")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=4.0)
            except asyncio.TimeoutError:
                pass

    async def chat_with_agent(self, chat_id: str, message: str) -> str:
        """Invokes AI Agent while maintaining an active Telegram typing indicator heartbeat."""
        stop_event = asyncio.Event()
        heartbeat_task = asyncio.create_task(self._send_typing_heartbeat(chat_id, stop_event))
        try:
            # Check for morning epiphany if within morning wake window
            morning_epiphany = None
            if self.dream_engine:
                try:
                    morning_epiphany = self.dream_engine.pop_morning_epiphany()
                except Exception as _ep_err:
                    logger.debug("[TelegramBot] Epiphany pop error: %s", _ep_err)

            reply = await self.ai_agent.chat(chat_id, message)
            if morning_epiphany:
                reply = f"{morning_epiphany}\n\n━━━━━━━━━━━━━━━━━━━━\n{reply}"
            return reply
        finally:
            stop_event.set()
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

    async def send_message(
        self,
        chat_id: str,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: str = "HTML"
    ) -> bool:
        """
        Sends formatted message to Telegram, automatically converting Markdown
        tables to Cards, sanitizing HTML, and chunking messages > 4000 chars.
        """
        res = await self.send_message_with_result(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
        return bool(res)

    async def send_message_with_result(
        self,
        chat_id: str,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: str = "HTML"
    ) -> Optional[Dict[str, Any]]:
        if not self.token or not text:
            return None

        # Convert text to Telegram HTML if parse_mode is HTML
        formatted = TelegramFormatter.format_for_telegram(text) if parse_mode == "HTML" else text
        chunks = TelegramFormatter.split_message(formatted)

        last_result: Optional[Dict[str, Any]] = None
        for idx, chunk in enumerate(chunks):
            # Only attach keyboard markup to the final chunk
            markup = reply_markup if idx == len(chunks) - 1 else None
            res = await self._send_single_chunk(chat_id, chunk, reply_markup=markup, parse_mode=parse_mode)
            if res:
                last_result = res

        return last_result

    async def _send_single_chunk(
        self,
        chat_id: str,
        text_chunk: str,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: str = "HTML"
    ) -> Optional[Dict[str, Any]]:
        try:
            url = f"{self.api_url}/sendMessage"
            payload: Dict[str, Any] = {
                "chat_id": chat_id,
                "text": text_chunk,
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

            # Fallback: if HTML parsing still fails (rare edge case), strip HTML tags and send plain text
            err_text = res.text.lower()
            if "can't parse entities" in err_text or "bad request" in err_text:
                logger.warning("[TelegramBot] Entity parsing issue (%s). Retrying without parse_mode...", res.text[:120])
                payload.pop("parse_mode", None)
                # Strip internal tags for plain text fallback
                import re
                plain_text = re.sub(r"</?[a-zA-Z0-9]+.*?>", "", text_chunk)
                payload["text"] = plain_text
                res2 = await self._http_client.post(url, json=payload)
                if res2.status_code == 200:
                    data2 = res2.json()
                    return data2.get("result")
        except Exception as e:
            logger.error("[TelegramBot] Failed sending message chunk: %s", e)
        return None

    async def edit_message_text(
        self,
        chat_id: str,
        message_id: int,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: str = "HTML"
    ) -> bool:
        if not self.token or not text:
            return False
        try:
            formatted = TelegramFormatter.format_for_telegram(text) if parse_mode == "HTML" else text
            url = f"{self.api_url}/editMessageText"
            payload: Dict[str, Any] = {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": formatted,
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
                import re
                payload["text"] = re.sub(r"</?[a-zA-Z0-9]+.*?>", "", formatted)
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

    async def send_photo_bytes(self, chat_id: str, photo_bytes: bytes, filename: str = "photo.png", caption: Optional[str] = None) -> bool:
        if not self.token or not photo_bytes:
            return False
        try:
            url = f"{self.api_url}/sendPhoto"
            files = {"photo": (filename, photo_bytes, "image/png")}
            data = {"chat_id": chat_id}
            if caption:
                data["caption"] = caption

            res = await self._http_client.post(url, data=data, files=files, timeout=40.0)
            return res.status_code == 200
        except Exception as e:
            logger.error("[TelegramBot] Failed sending photo bytes: %s", e)
            return False

    async def send_document(self, chat_id: str, file_bytes: bytes, filename: str, caption: Optional[str] = None) -> bool:
        if not self.token or not file_bytes:
            return False
        try:
            url = f"{self.api_url}/sendDocument"
            files = {"document": (filename, file_bytes, "application/octet-stream")}
            data = {"chat_id": chat_id}
            if caption:
                data["caption"] = caption

            res = await self._http_client.post(url, data=data, files=files, timeout=60.0)
            return res.status_code == 200
        except Exception as e:
            logger.error("[TelegramBot] Failed sending document bytes: %s", e)
            return False

    async def _claim_update(self, update_id: int) -> bool:
        """Ensures at-most-once processing using PostgreSQL unique index."""
        try:
            async with get_db_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "INSERT INTO processed_telegram_updates (update_id) VALUES (%s) ON CONFLICT (update_id) DO NOTHING",
                        (update_id,),
                    )
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

        # Handle Archive Password Recovery Callbacks
        elif data.startswith("crack_archive:"):
            action = data.split(":")[1]
            if action == "cancel":
                self._pending_archives.pop(chat_id, None)
                await self.edit_message_text(chat_id, message_id, "✅ Đã hủy phiên mở khóa tệp nén.", reply_markup=None)
                await self.answer_callback_query(query_id, text="Đã hủy.")
                return

            elif action == "clues":
                await self.answer_callback_query(query_id)
                await self.send_message(
                    chat_id,
                    "💡 <b>HƯỚNG DẪN DÒ PASS THEO MANH MỐI:</b>\n\n"
                    "Anh Mạnh chỉ cần nhắn các từ gợi nhớ thường dùng, ví dụ:\n"
                    "• <code>gợi ý: manh 2005 @</code>\n"
                    "• <code>anh quên pass, hình như có Kirito và số đuôi 123</code>\n\n"
                    "Em sẽ lập tức kết hợp đột biến chữ hoa/thường, năm sinh, leetspeak và ký tự đặc biệt để phá khóa cho anh ngay!"
                )
                return

            elif action == "auto":
                await self.answer_callback_query(query_id, text="⚡ Đang kích hoạt engine phá khóa...")
                await self._trigger_archive_recovery(chat_id, message_id=message_id)
                return

        await self.answer_callback_query(query_id)

    async def _trigger_archive_recovery(
        self,
        chat_id: str,
        clues: Optional[List[str]] = None,
        message_id: Optional[int] = None,
    ) -> None:
        """
        Executes high-speed multi-threaded archive recovery on the pending archive session.
        Auto-extracts and analyzes archive contents upon successful recovery.
        """
        pending = self._pending_archives.get(chat_id)
        if not pending:
            await self.send_message(
                chat_id,
                "⚠️ Không còn phiên mở khóa tệp nén nào đang chờ. Anh vui lòng gửi lại tệp nén giúp em nhé!"
            )
            return

        filename = pending["filename"]
        file_bytes = pending["file_bytes"]
        mime_type = pending["mime_type"]
        caption = pending["caption"]

        status_text = (
            f"⚡ <b>ĐANG PHÁ KHÓA TỆP NÉN 4 LUỒNG...</b>\n\n"
            f"📁 <b>Tệp:</b> <code>{filename}</code>\n"
            f"⏳ <i>Tiểu Bảo Bảo đang chạy engine song song 4 workers kiểm tra các mẫu mật khẩu tiềm năng nhất...</i>"
        )
        if message_id:
            try:
                await self.edit_message_text(chat_id, message_id, status_text, reply_markup=None)
            except Exception:
                await self.send_message(chat_id, status_text)
        else:
            await self.send_message(chat_id, status_text)

        from app.services.archive_recovery import run_archive_recovery

        try:
            rec_res = await run_archive_recovery(
                archive_path_or_bytes=file_bytes,
                clues=clues or [],
                filename=filename,
                ssh_client=self.ssh_client,
            )
        except Exception as ex_run:
            logger.error("[TelegramBot] Error running archive recovery: %s", ex_run, exc_info=True)
            rec_res = {"success": False, "found": False, "message": str(ex_run)}

        if rec_res.get("found"):
            found_pwd = rec_res.get("password") or ""
            elapsed = rec_res.get("elapsed_sec", 0.0)
            tested = rec_res.get("tested_count", 0)

            # Auto-decrypt and extract content using found password
            try:
                content = await self._media.process_archive(
                    file_bytes,
                    mime_type,
                    filename,
                    caption=caption,
                    password=found_pwd if found_pwd else None,
                )
                self._pending_archives.pop(chat_id, None)

                success_msg = (
                    f"🎉 <b>PHÁ KHÓA TỆP NÉN THÀNH CÔNG!</b>\n\n"
                    f"📁 <b>Tệp:</b> <code>{filename}</code>\n"
                    f"🔑 <b>Mật khẩu:</b> <code>{found_pwd or '(Không có mật khẩu)'}</code>\n"
                    f"⏱️ <b>Thời gian dò:</b> <code>{elapsed}s</code> (đã thử <code>{tested}</code> mật khẩu)\n\n"
                    f"🔓 <i>Tiểu Bảo Bảo đã tự động giải nén và nạp dữ liệu vào phiên làm việc!</i>"
                )
                await self.send_message(chat_id, success_msg)

                caption_part = f"\n[Yêu cầu từ anh Mạnh]: {caption}" if caption else ""
                user_input = (
                    f"[📄 TỆP ĐÍNH KÈM: {filename} (Đã giải nén thành công)]{caption_part}\n\n"
                    f"{content}"
                )
                reply = await self.chat_with_agent(chat_id, user_input)
                await self.send_message(chat_id, reply)
                return

            except Exception as ex_proc:
                logger.error("[TelegramBot] Decryption after recovery failed: %s", ex_proc, exc_info=True)
                await self.send_message(
                    chat_id,
                    f"🎉 <b>ĐÃ TÌM THẤY MẬT KHẨU:</b> <code>{found_pwd}</code>\n\n"
                    f"Tuy nhiên có lỗi khi giải nén: {ex_proc}. Anh có thể dùng mật khẩu này để mở tệp thủ công nhé!"
                )
                return

        # Not found with initial candidates
        tested = rec_res.get("tested_count", 0)
        elapsed = rec_res.get("elapsed_sec", 0.0)
        fail_msg = (
            f"⚠️ <b>CHƯA TÌM THẤY MẬT KHẨU CHO TỆP <code>{filename}</code></b>\n\n"
            f"• Đã thử nghiệm: <b>{tested}</b> mẫu mật khẩu phổ biến trong {elapsed}s.\n"
            f"• Tệp này có thể sử dụng mật khẩu cá nhân hóa riêng biệt.\n\n"
            f"💡 <b>Gợi ý:</b> Anh Mạnh hãy nhắn cho em vài manh mối gợi nhớ (ví dụ: <code>gợi ý: manh 2005 @</code> hoặc 4 số cuối điện thoại), em sẽ lập tức sinh từ điển đột biến và dò sâu hơn cho anh nhé!"
        )
        retry_kb = {
            "inline_keyboard": [
                [
                    {
                        "text": "💡 Hướng Dẫn Nhập Gợi Ý",
                        "callback_data": "crack_archive:clues",
                    },
                    {
                        "text": "❌ Hủy Bỏ",
                        "callback_data": "crack_archive:cancel",
                    },
                ]
            ]
        }
        await self.send_message(chat_id, fail_msg, reply_markup=retry_kb)

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
                "🧠 *Lệnh nhận thức & trí nhớ tự học:*\n"
                "• /brain — Xem trạng thái não bộ nhận thức, cảm xúc Russell & hóa chất thần kinh\n"
                "• /dream — Kích hoạt chu kỳ giấc mơ REM & giác ngộ tiềm thức\n"
                "• /lessons — Xem bài học đã tích lũy\n"
                "• /lesson_add <nội dung> — Thêm bài học thủ công\n"
                "• /lesson_delete <id> — Xóa một bài học\n"
                "• /memory_stats — Thống kê trí nhớ\n\n"
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
                etype = {
                    "correction": "🔧 Sửa lỗi",
                    "new_knowledge": "📖 Kiến thức",
                    "tool_failure": "🛠️ Tool Failure",
                    "manual": "✍️ Thủ công",
                }.get(l.get("event_type", ""), "📌")
                conf = int(float(l.get("confidence", 0)) * 100)
                grounded_tag = "🔍 _Web-Grounded_" if l.get("is_search_grounded") else "💭 _Introspection_"
                search_q = f"\n   🔎 Query: `{l['search_query']}`" if l.get("search_query") else ""
                lines.append(
                    f"{i}️⃣ *[ID:{l['id']}]* {etype} {grounded_tag}\n"
                    f"   Tin cậy: `{conf}%` · Dùng: `{l['usage_count']}x`{search_q}\n"
                    f"   _{l['lesson_text']}_\n"
                )
            lines.append(
                "\n🔍 = Xác thực qua tìm kiếm web (đáng tin cậy hơn)\n"
                "💭 = Phân tích nội tâm (không có web grounding)\n"
                "💡 Dùng `/lesson_delete <id>` để xóa bài học sai."
            )
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
                "🧠 *THỐNG KÊ TRÍ NHỚ TỰ HỌC — TIỂU BẢO BẢO*\n\n"
                f"📚 *Episodic Memory (Lịch sử sự kiện):*\n"
                f"   • 🔧 Lần bị sửa lỗi: `{stats.get('total_corrections', 0)}`\n"
                f"   • 📖 Kiến thức mới học: `{stats.get('total_new_knowledge', 0)}`\n"
                f"   • 🛠️ Tool failure đã gặp: `{stats.get('total_tool_failures', 0)}`\n"
                f"   • 📋 Tổng sự kiện ghi nhận: `{stats.get('total_memories', 0)}`\n\n"
                f"💡 *Procedural Memory (Bài học đã rút ra):*\n"
                f"   • ✅ Đang hoạt động: `{stats.get('active_lessons', 0)}` bài học\n"
                f"   • 🔍 Xác thực qua web search: `{stats.get('search_grounded_lessons', 0)}` bài học\n"
                f"   • 🗄️ Đã lưu trữ: `{stats.get('archived_lessons', 0)}` bài học\n"
                f"   • 🔢 Tổng lần áp dụng: `{stats.get('total_lesson_usages', 0)}`\n\n"
                f"_🔍 Web-Grounded lessons = AI học có bằng chứng thực tế từ Google/DuckDuckGo_"
            )
            await self.send_message(chat_id, msg)

        elif raw_cmd == "/brain":
            brain = getattr(self.ai_agent, "brain", None)
            if not brain:
                await self.send_message(chat_id, "⚠️ Brain Core chưa sẵn sàng.")
                return

            val, aro, quad, emotional_title, style_hint = brain.neuro.calculate_circumplex()
            cortex_count = len(brain.cortex._metadata) if hasattr(brain, "cortex") and hasattr(brain.cortex, "_metadata") else 0
            fe = brain.active_inference.last_free_energy

            lines = [
                "🧠 *TRẠNG THÁI NÃO BỘ NHẬN THỨC & CẢM XÚC — TIỂU BẢO BẢO*",
                "",
                "🎭 *Không gian Cảm xúc Russell Circumplex:*",
                f"• Tâm trạng: *{emotional_title}* (Vùng {quad})",
                f"• Tọa độ: Valence = `{val:+.2f}` | Arousal = `{aro:.2f}`",
                f"• Khuyến nghị phong thái: _{style_hint}_",
                "",
                "🧪 *Hóa chất Thần kinh Sinh học (Neurotransmitters):*",
                f"• 🌟 Dopamine (Hào hứng/Tò mò): `{brain.neuro.dopamine:.2f}`",
                f"• ⚡ Noradrenaline (Cảnh giác/Tập trung): `{brain.neuro.noradrenaline:.2f}`",
                f"• 🧘 Serotonin (Bình ổn/Điềm đạm): `{brain.neuro.serotonin:.2f}`",
                f"• ⏳ Cortisol (Áp lực/Stress): `{brain.neuro.cortisol:.2f}`",
                f"• 💕 Oxytocin (Ân cần/Gắn kết): `{brain.neuro.oxytocin:.2f}`",
                f"• ✨ Endorphins (Hài hước/Bền bỉ): `{brain.neuro.endorphins:.2f}`",
                "",
                "⚡ *Active Inference & VSA Hyperdimensional Cortex:*",
                f"• Năng lượng tự do (Free Energy): `{fe:.2f}` ({'Phản xạ nhanh' if fe < 0.6 else 'Trầm ngâm phân tích sâu'})",
                f"• Vỏ não ảo 32GB Virtual Cortex: `{cortex_count}` hypervectors ghi nhớ",
            ]

            if self.dream_engine:
                has_pending = bool(self.dream_engine.pending_morning_epiphany)
                last_sws = datetime.fromtimestamp(self.dream_engine.last_sws_time, VN_TZ).strftime("%H:%M:%S %d/%m") if self.dream_engine.last_sws_time else "Chưa chạy"
                last_rem = datetime.fromtimestamp(self.dream_engine.last_rem_time, VN_TZ).strftime("%H:%M:%S %d/%m") if self.dream_engine.last_rem_time else "Chưa chạy"
                lines.extend([
                    "",
                    "🌙 *Tiềm Thức & Giấc Mơ Ban Đêm (Dream Engine):*",
                    f"• Chu kỳ SWS gần nhất: `{last_sws}`",
                    f"• Giấc mơ REM gần nhất: `{last_rem}`",
                    f"• Giác ngộ chờ gửi buổi sáng: `{'Có (Sẵn sàng gửi)' if has_pending else 'Chưa có'}`",
                    "• Gõ `/dream` để kích hoạt mô phỏng giấc mơ sáng tạo ngay lập tức!",
                ])

            await self.send_message(chat_id, "\n".join(lines))

        elif raw_cmd == "/dream":
            if not self.dream_engine:
                await self.send_message(chat_id, "⚠️ Dream Engine chưa sẵn sàng.")
                return

            await self.send_message(chat_id, "🌙 *Tiểu Bảo Bảo đang bước vào chu kỳ giấc ngủ SWS và mô phỏng giấc mơ REM...* Vui lòng đợi trong giây lát ạ ✨")
            result = await self.dream_engine.run_full_sleep_cycle(force=True)

            sws_info = result.get("sws", {})
            rem_info = result.get("rem")

            reply_lines = [
                "✨ *CHU KỲ GIẤC MƠ TIỀM THỨC HOÀN TẤT*",
                "",
                "🌙 *1. Giai đoạn Ngủ Sâu SWS (Slow-Wave Sleep):*",
                f"• Đã nén & lưu trữ: `{sws_info.get('consolidated_vectors', 0)}` mẩu ký ức vào VSA Cortex 32GB",
                f"• Thời gian nén: `{sws_info.get('duration_ms', 0)} ms` (Zero-copy mmap)",
                f"• Mức Cortisol giảm còn: `{sws_info.get('cortisol', 0):.2f}` (giảm stress, phục hồi năng lượng)",
                "",
            ]

            if rem_info:
                reply_lines.extend([
                    "💭 *2. Giấc Mơ Đối Nghịch REM (Rapid Eye Movement):*",
                    f"💡 *Chủ đề:* {rem_info.get('topic')}",
                    f"_{rem_info.get('insight')}_",
                    "",
                    f"💌 *Lời nhắn gửi anh Mạnh:* _{rem_info.get('sisterly_note')}_",
                ])
            else:
                reply_lines.append("💭 *2. Giai đoạn REM:* Đã thả lỏng các liên kết nơ-ron.")

            await self.send_message(chat_id, "\n".join(reply_lines))

        elif raw_cmd == "/tasks":
            # Phase 5A: Prospective Memory — list pending tasks
            if not self.memory_service:
                await self.send_message(chat_id, "⚠️ Memory service chưa sẵn sàng.")
                return
            tasks = await self.memory_service.list_pending_tasks()
            if not tasks:
                await self.send_message(
                    chat_id,
                    "📋 *Danh sách việc đang chờ:*\n\n✅ Hiện không có việc nào đang chờ xử lý!"
                )
                return
            lines = ["📋 *DANH SÁCH VIỆC ĐANG CHỜ (Prospective Memory):*\n"]
            for t in tasks:
                from datetime import datetime as _dt
                ts = t["created_at"].strftime("%d/%m %H:%M") if t.get("created_at") else "?"
                lines.append(
                    f"• <b>#{t['id']}</b> [{ts}] {t['task_summary']}\n"
                    f"  _Nhắc sau mỗi {t['remind_turns']} lượt, đã qua {t['turns_elapsed']} lượt_"
                )
            lines.append("\n💡 Gõ <code>xong việc #ID</code> để đánh dấu hoàn thành")
            await self.send_message(chat_id, "\n".join(lines))

        else:
            # Route unrecognized slash command to AI Agent
            reply = await self.chat_with_agent(chat_id, command)
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

        # 2. Handle all message types (text, voice, photo, document)
        message = update.get("message") or update.get("edited_message")
        if not message:
            return

        chat = message.get("chat", {})
        chat_id = str(chat.get("id", ""))
        if not chat_id:
            return

        # Security check: reject unauthorized users before any processing
        if self.chat_id and self.chat_id != chat_id:
            logger.warning("[TelegramBot] Unauthorized message from chat_id %s", chat_id)
            await self.send_message(chat_id, "⛔ Bạn không có quyền truy cập bot này.")
            return

        # ── 2a. Voice / Audio ─────────────────────────────────────────────────
        voice = message.get("voice") or message.get("audio")
        if voice:
            file_id = voice.get("file_id", "")
            duration = voice.get("duration", 0)
            logger.info("[TelegramBot] Voice message from %s (duration=%ds)", chat_id, duration)
            try:
                audio_bytes = await self._media.download_telegram_file(file_id)
                filename = voice.get("file_name", "voice.oga")
                transcript = await self._media.transcribe_voice(audio_bytes, filename=filename, duration=duration)
                if transcript:
                    user_input = f"[🎤 Tin nhắn thoại]: {transcript}"
                    logger.info("[TelegramBot] STT transcript: '%s'", transcript[:80])
                else:
                    user_input = "[🎤 Tin nhắn thoại]: (Không nhận được nội dung âm thanh)"
                reply = await self.chat_with_agent(chat_id, user_input)
                await self.send_message(chat_id, reply)
            except Exception as err:
                logger.error("[TelegramBot] Voice processing error: %s", err, exc_info=True)
                await self.send_message(chat_id, "Xin lỗi, em không thể xử lý tin nhắn thoại lúc này. Vui lòng thử lại sau.")
            return

        # ── 2b. Photo ─────────────────────────────────────────────────────────
        photos = message.get("photo")
        if photos:
            # Telegram sends multiple resolutions; take the largest (last element)
            largest = photos[-1]
            file_id = largest.get("file_id", "")
            caption = (message.get("caption") or "").strip()
            logger.info("[TelegramBot] Photo message from %s (caption='%s')", chat_id, caption[:40])
            try:
                image_bytes = await self._media.download_telegram_file(file_id)
                vision_result = await self._media.analyze_image(image_bytes, caption=caption)
                caption_part = f" (caption: {caption})" if caption else ""
                user_input = f"[📸 Ảnh từ anh Mạnh{caption_part}]: {vision_result}"
                logger.info("[TelegramBot] Vision result: '%s'", vision_result[:80])
                reply = await self.chat_with_agent(chat_id, user_input)
                await self.send_message(chat_id, reply)
            except Exception as err:
                logger.error("[TelegramBot] Photo processing error: %s", err, exc_info=True)
                await self.send_message(chat_id, "Xin lỗi, em không thể xử lý ảnh lúc này. Vui lòng thử lại sau.")
            return

        # ── 2c. Document / File ───────────────────────────────────────────────
        document = message.get("document")
        if document:
            file_id = document.get("file_id", "")
            filename = document.get("file_name", "unknown")
            mime_type = document.get("mime_type", "")
            file_size = document.get("file_size", 0)
            caption = (message.get("caption") or "").strip()
            logger.info("[TelegramBot] Document from %s: %s (%s, %d bytes)", chat_id, filename, mime_type, file_size)
            # Telegram Bot API only allows downloading files up to 20MB
            if file_size > 20 * 1024 * 1024:
                await self.send_message(chat_id, f"⚠️ File `{filename}` quá lớn ({file_size // 1048576}MB). Giới hạn tải là 20MB.")
                return
            try:
                file_bytes = await self._media.download_telegram_file(file_id)
                ext = Path(filename).suffix.lower()
                archive_exts = {".zip", ".rar", ".tar", ".gz", ".tgz", ".bz2", ".tbz2", ".xz", ".txz", ".7z", ".jar", ".war"}
                mime_lower = (mime_type or "").lower()
                is_archive = ext in archive_exts or any(t in mime_lower for t in ("zip", "rar", "tar", "7z", "compressed", "archive", "x-rar"))

                if is_archive:
                    try:
                        content = await self._media.process_archive(file_bytes, mime_type, filename, caption=caption)
                        # Clear any previous pending archive for this chat_id upon success
                        self._pending_archives.pop(chat_id, None)
                    except ArchivePasswordRequiredError:
                        self._pending_archives[chat_id] = {
                            "file_bytes": file_bytes,
                            "filename": filename,
                            "mime_type": mime_type,
                            "caption": caption,
                            "timestamp": time.time(),
                        }
                        unlock_kb = {
                            "inline_keyboard": [
                                [
                                    {
                                        "text": "⚡ Phá Khóa Tự Động (Flash Crack)",
                                        "callback_data": "crack_archive:auto",
                                    }
                                ],
                                [
                                    {
                                        "text": "💡 Dò Mật Khẩu Theo Manh Mối",
                                        "callback_data": "crack_archive:clues",
                                    },
                                    {
                                        "text": "❌ Hủy Bỏ",
                                        "callback_data": "crack_archive:cancel",
                                    },
                                ],
                            ]
                        }
                        await self.send_message(
                            chat_id,
                            f"🔒 <b>TỆP NÉN CÓ MẬT KHẨU BẢO VỆ</b>\n\n"
                            f"📁 <b>Tệp:</b> <code>{filename}</code>\n\n"
                            f"Anh Mạnh có thể:\n"
                            f"1️⃣ Nhắn mật khẩu trực tiếp cho em (ví dụ: <code>pass: 123456</code>)\n"
                            f"2️⃣ Bấm <b>[⚡ Phá Khóa Tự Động]</b> để Tiểu Bảo Bảo chạy engine 4 luồng mở khóa siêu tốc!\n"
                            f"3️⃣ Hoặc nhắn manh mối gợi nhớ: <i>'anh quên pass rồi, gợi ý: manh 2005 @'</i> 🔓",
                            reply_markup=unlock_kb,
                        )
                        return
                    except ArchiveInvalidPasswordError:
                        self._pending_archives[chat_id] = {
                            "file_bytes": file_bytes,
                            "filename": filename,
                            "mime_type": mime_type,
                            "caption": caption,
                            "timestamp": time.time(),
                        }
                        retry_kb = {
                            "inline_keyboard": [
                                [
                                    {
                                        "text": "⚡ Phá Khóa Tự Động (Flash Crack)",
                                        "callback_data": "crack_archive:auto",
                                    }
                                ],
                                [
                                    {
                                        "text": "❌ Hủy Bỏ",
                                        "callback_data": "crack_archive:cancel",
                                    },
                                ],
                            ]
                        }
                        await self.send_message(
                            chat_id,
                            f"❌ <b>Mật khẩu mở tệp <code>{filename}</code> không chính xác!</b>\n\n"
                            f"Anh vui lòng kiểm tra lại mật khẩu đúng, hoặc bấm nút bên dưới để em tự động phá khóa giúp anh nhé!",
                            reply_markup=retry_kb,
                        )
                        return
                else:
                    content = self._media.extract_document_text(file_bytes, mime_type, filename)

                caption_part = f"\n[Yêu cầu từ anh Mạnh]: {caption}" if caption else ""
                user_input = f"[📄 TỆP ĐÍNH KÈM: {filename}]{caption_part}\n\n{content}"
                logger.info("[TelegramBot] Document extracted: %d chars", len(content))
                reply = await self.chat_with_agent(chat_id, user_input)
                await self.send_message(chat_id, reply)

                # Optional: If user explicitly requested extracting/sending child files directly
                if is_archive and any(w in caption.lower() for w in ("trích xuất ra gửi", "tách file gửi", "gửi lại file", "extract and send", "gửi từng file")):
                    try:
                        members = self._media._unpack_archive_members(file_bytes, filename, mime_type, password=extract_password_from_text(caption))
                        sent_count = 0
                        for m_name, m_size, m_data in members[:5]:  # Send up to 5 individual extracted files
                            m_ext = Path(m_name).suffix.lower()
                            if m_ext in self._media._IMAGE_EXTENSIONS:
                                await self.send_photo_bytes(chat_id, m_data, filename=m_name, caption=f"🖼️ {m_name}")
                                sent_count += 1
                            elif m_size <= 10 * 1024 * 1024:
                                await self.send_document(chat_id, m_data, filename=m_name, caption=f"📄 {m_name}")
                                sent_count += 1
                        if sent_count > 0:
                            logger.info("[TelegramBot] Auto-extracted and sent %d files from archive to %s", sent_count, chat_id)
                    except Exception as ex_send:
                        logger.warning("[TelegramBot] Failed sending extracted child files: %s", ex_send)

            except Exception as err:
                logger.error("[TelegramBot] Document processing error: %s", err, exc_info=True)
                await self.send_message(chat_id, f"Xin lỗi anh Mạnh, em không thể đọc tệp `{filename}` lúc này ({err}).")
            return

        # ── 2d. Text Message ──────────────────────────────────────────────────
        text = (message.get("text") or "").strip()
        if not text:
            return

        # Check for pending encrypted archive waiting for password (valid for 15 minutes)
        if chat_id in self._pending_archives:
            pending = self._pending_archives[chat_id]
            if time.time() - pending.get("timestamp", 0) < 900 and not text.startswith("/"):
                # Recovery intent detection: user forgot password or asks to crack/help
                recovery_match = re.search(
                    r"(quên|bẻ khóa|phá khóa|crack|dò pass|tìm pass|mở khóa giúp|không nhớ|quên mật khẩu|tool|thử pass|gợi ý|clue|manh mối)",
                    text,
                    re.IGNORECASE,
                )
                if recovery_match:
                    logger.info("[TelegramBot] User requested password recovery for %s: '%s'", pending["filename"], text)
                    clue_text = re.sub(
                        r"\b(anh|em|quên|mật|khẩu|pass|rồi|giúp|phá|khóa|bẻ|crack|dò|tìm|mở|không|nhớ|tool|hộ|cho|file|tệp|nén|gợi|ý|hình|như|có|chữ|số|là|với|nhé|ơi)\b",
                        " ",
                        text,
                        flags=re.IGNORECASE,
                    )
                    clues = [w.strip() for w in re.split(r"[\s,;:\-_/]+", clue_text) if w.strip()]
                    await self._trigger_archive_recovery(chat_id, clues=clues)
                    return

                extracted_pwd = extract_password_from_text(text) or text.strip()
                logger.info("[TelegramBot] Trying password for pending archive %s from %s", pending["filename"], chat_id)
                try:
                    content = await self._media.process_archive(
                        pending["file_bytes"],
                        pending["mime_type"],
                        pending["filename"],
                        caption=pending["caption"],
                        password=extracted_pwd,
                    )
                    # Decryption succeeded! Clear pending session
                    self._pending_archives.pop(chat_id, None)
                    caption_part = f"\n[Yêu cầu từ anh Mạnh]: {pending['caption']}" if pending["caption"] else ""
                    user_input = (
                        f"[📄 TỆP ĐÍNH KÈM: {pending['filename']} (Đã mở khóa mật khẩu thành công)]{caption_part}\n"
                        f"[Câu hỏi/Chỉ đạo từ anh Mạnh]: {text}\n\n"
                        f"{content}"
                    )
                    logger.info("[TelegramBot] Decrypted document extracted: %d chars", len(content))
                    reply = await self.chat_with_agent(chat_id, user_input)
                    await self.send_message(chat_id, f"🔓 <i>Đã mở khóa tệp <b>{pending['filename']}</b> thành công!</i>\n\n" + reply)
                    return
                except ArchiveInvalidPasswordError:
                    retry_kb = {
                        "inline_keyboard": [
                            [
                                {
                                    "text": "⚡ Phá Khóa Tự Động (Flash Crack)",
                                    "callback_data": "crack_archive:auto",
                                }
                            ],
                            [
                                {
                                    "text": "💡 Dò Mật Khẩu Theo Manh Mối",
                                    "callback_data": "crack_archive:clues",
                                },
                                {
                                    "text": "❌ Hủy Bỏ",
                                    "callback_data": "crack_archive:cancel",
                                },
                            ],
                        ]
                    }
                    await self.send_message(
                        chat_id,
                        f"❌ <b>Mật khẩu '<code>{extracted_pwd}</code>' không chính xác cho tệp <code>{pending['filename']}</code>!</b>\n\n"
                        f"Anh có thể nhập lại mật khẩu đúng, hoặc bấm nút dưới đây để em tự động phá khóa nhé!",
                        reply_markup=retry_kb,
                    )
                    return
                except Exception as ex_dec:
                    logger.warning("[TelegramBot] Decryption with provided text failed: %s, falling back to standard chat", ex_dec)
            else:
                self._pending_archives.pop(chat_id, None)

        if text.startswith("/"):
            if text == "/cancel":
                if chat_id in self._pending_archives:
                    self._pending_archives.pop(chat_id, None)
                    await self.send_message(chat_id, "✅ Đã hủy phiên chờ mở khóa tệp nén.")
                    return
            await self._handle_command(text, chat_id)
        else:
            try:
                logger.info("[TelegramBot] Received message from %s (length=%d)", chat_id, len(text))
                reply = await self.chat_with_agent(chat_id, text)
                logger.info("[TelegramBot] AI reply for %s sent successfully (length=%d)", chat_id, len(reply))
                await self.send_message(chat_id, reply)
            except Exception as err:
                logger.error("[TelegramBot] Error processing message from %s: %s", chat_id, err, exc_info=True)
                await self.send_message(chat_id, "Xin lỗi, đã xảy ra lỗi trong quá trình xử lý tin nhắn. Vui lòng thử lại sau.")


    async def _load_offset_from_db(self) -> int:
        """Recover the highest claimed update_id from DB to resume after restart."""
        try:
            async with get_db_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT MAX(update_id) FROM processed_telegram_updates")
                    row = await cur.fetchone()
                    if row and row[0]:
                        logger.info("[TelegramBot] Restored offset from DB: %d", row[0])
                        return int(row[0])
        except Exception as e:
            logger.warning("[TelegramBot] Could not load offset from DB: %s", e)
        return 0

    async def start_polling(self) -> None:
        if not self.token or not self.polling_enabled:
            logger.info("[TelegramBot] Polling disabled or token missing.")
            return

        # Seed offset from DB so we don't replay already-claimed updates after restart
        if self._last_offset == 0:
            self._last_offset = await self._load_offset_from_db()

        self._running = True
        logger.info("[TelegramBot] Starting async long-polling (resume from offset=%d)...", self._last_offset)

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
                        # Always advance offset regardless of whether we process this update —
                        # this prevents the loop from getting stuck re-fetching claimed updates
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
