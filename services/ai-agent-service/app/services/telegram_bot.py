import asyncio
import html
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set, Union
import os
import shutil
import tempfile
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
from app.core.vietnamese_dialect import linguistic_normalizer
from app.services.video_pipeline import (
    LightweightVideoPipeline,
    PendingVideoSession,
    VideoDebounceManager,
    VideoMetadata,
)
from app.services.video_chunker import VideoChunker
from app.services.media_storage_manager import media_storage_manager

logger = logging.getLogger(__name__)


def _strip_html_tags(text: str) -> str:
    """Loại bỏ thẻ HTML và unescape entities phục vụ fallback sang Plain Text."""
    cleaned = re.sub(r"</?[a-zA-Z0-9]+.*?>", "", text)
    return html.unescape(cleaned)


class FastPathMediaIntent(tuple):
    """
    Tuple 2 phần tử (media_url, caption) tương thích ngược 100% với cú pháp:
      url, caption = res
      res[0], res[1]
      len(res) == 2
    Đồng thời cung cấp thuộc tính:
      media_intent.media_type ('video' hoặc 'audio')
      media_intent[2] (thông qua __getitem__ override)
    """
    media_url: str
    caption: str
    media_type: str

    def __new__(cls, *args, media_type: str = "video", **kwargs):
        if len(args) == 1 and isinstance(args[0], (tuple, list)) and len(args[0]) >= 2:
            media_url = str(args[0][0])
            caption = str(args[0][1])
        elif len(args) >= 2:
            media_url = str(args[0])
            caption = str(args[1])
        elif len(args) == 1:
            media_url = str(args[0])
            caption = ""
        else:
            raise TypeError(f"FastPathMediaIntent expected (url, caption) or url, caption; got {args}")

        instance = super().__new__(cls, (media_url, caption))
        instance.media_url = media_url
        instance.caption = caption
        instance.media_type = media_type
        return instance

    def __getitem__(self, item):
        if item == 2:
            return self.media_type
        return super().__getitem__(item)

    def __repr__(self) -> str:
        return f"FastPathMediaIntent(url={self.media_url!r}, caption={self.caption!r}, media_type={self.media_type!r})"


class _AudioFileStream:
    """
    Zero-RAM streaming wrapper around an open binary file.
    Tracks file position and allows tell() even after close for post-transmission verification.
    """
    def __init__(self, raw_file: Any, file_size: int):
        self._raw = raw_file
        self._file_size = file_size
        self._last_pos = 0

    def read(self, *args, **kwargs) -> bytes:
        chunk = self._raw.read(*args, **kwargs)
        self._last_pos = self._raw.tell()
        return chunk

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        res = self._raw.seek(offset, whence)
        self._last_pos = self._raw.tell()
        return res

    def tell(self) -> int:
        if not self._raw.closed:
            return self._raw.tell()
        return self._last_pos

    def close(self) -> None:
        if not self._raw.closed:
            self._last_pos = self._raw.tell()
            self._raw.close()

    @property
    def closed(self) -> bool:
        return self._raw.closed

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._raw, name)


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
        # Multimodal Video Pipeline with 5s debounce window and 5m interactive TTL
        self._video_pipeline = LightweightVideoPipeline(self._media)
        self._video_debounce = VideoDebounceManager(
            on_debounce_timeout=self._on_video_debounce_timeout,
            on_process_pipeline=self._on_video_process_pipeline,
        )
        if hasattr(self.ai_agent, "set_telegram_bot"):
            self.ai_agent.set_telegram_bot(self)

    _MEDIA_URL_REGEX = re.compile(
        r"https?://(?:www\.|web\.|vt\.|vm\.|v\.|m\.)?(?:"
        r"tiktok\.com/[^\s]+|"
        r"douyin\.com/[^\s]+|"
        r"youtube\.com/[^\s]+|youtu\.be/[^\s]+|"
        r"(?:facebook\.com|fb\.com)/(?:reel|reels|share|.+?/videos)/[^\s]+|"
        r"(?:facebook\.com|fb\.com)/watch(?:\?[^\s]+|/[^\s]*)|"
        r"fb\.watch/[^\s]+|fb\.me/[^\s]+|fb\.com/[^\s]+|"
        r"instagram\.com/(?:reel|p|tv)/[^\s]+|"
        r"threads\.net/(?:@[^/\s]+/post|t)/[^\s]+|threads\.net/[^\s]+|threads\.com/[^\s]+|"
        r"twitter\.com/[^\s]+|x\.com/[^\s]+"
        r")",
        re.IGNORECASE,
    )

    def _detect_fastpath_media_download(self, text: str) -> Optional[FastPathMediaIntent]:
        """Phát hiện ý định tải video/audio trực tiếp để kích hoạt Fast-path bypass LLM."""
        url_match = self._MEDIA_URL_REGEX.search(text)
        if not url_match:
            return None

        raw_url = url_match.group(0)
        # Strip common trailing punctuation and enclosures attached in chat, markdown or rich text
        media_url = raw_url.rstrip(".,;!?)\"'>]}…")
        remaining_text = text.replace(raw_url, "").strip().lower()
        clean_remaining = remaining_text.strip(" \t\r\n.,;:!?()[]{}<>\"'…*`~")

        # TH 1: Chỉ gửi độc nhất link media -> Mặc định tải Video
        if not clean_remaining:
            return FastPathMediaIntent(media_url, "", media_type="video")

        # TH 2: Ý định phủ định (tuyệt đối không tải) -> Nhường AI Agent
        negative_keywords = (
            "đừng tải", "dung tai", "không tải", "khong tai",
            "đừng down", "dung down", "không down", "khong down",
            "chưa tải", "chua tai", "không cần tải", "khong can tai",
            "ko tải", "ko tai", "k tải", "k tai", "ko cần tải", "ko can tai",
            "đừng lưu", "dung luu", "không lưu", "khong luu",
            "đừng lấy", "dung lay", "không lấy", "khong lay",
            "đừng lấy nhạc", "dung lay nhac", "không lấy nhạc", "khong lay nhac",
            "đừng tải nhạc", "dung tai nhac", "không tải nhạc", "khong tai nhac",
            "đừng tải mp3", "dung tai mp3", "không tải mp3", "khong tai mp3",
            "không lấy audio", "khong lay audio", "đừng lấy audio", "dung lay audio",
            "không tải audio", "khong tai audio", "đừng tải audio", "dung tai audio",
            "đừng kéo nhạc", "dung keo nhac", "không kéo nhạc", "khong keo nhac",
        )
        if any(k in remaining_text for k in negative_keywords):
            return None

        # TH 3: Câu hỏi phân tích, thắc mắc, hỏi nguyên nhân -> Nhường cho AI Agent
        analysis_keywords = (
            "nói về gì", "tóm tắt", "dịch", "xem giùm", "giải thích", "ai đây",
            "nội dung là", "chi tiết", "nói chi", "chi rứa", "hát bài gì", "ý nghĩa",
            "noi ve gi", "tom tat", "dich", "xem gium", "giai thich", "ai day",
            "noi dung la", "chi tiet", "noi chi", "chi rua", "hat bai gi", "y nghia",
            "tại sao", "tai sao", "vì sao", "vi sao", "sao không", "sao khong",
            "làm sao", "lam sao", "thế nào", "the nao", "được không", "duoc khong",
            "được ko", "duoc ko", "sao tải", "sao tai", "sao chưa tải", "sao chua tai",
            "tải kiểu gì", "tai kieu gi", "tại sao không", "tai sao khong",
            "vì sao không", "vi sao khong", "hướng dẫn tải", "huong dan tai",
            "quá tải", "qua tai",
        )
        if any(k in remaining_text for k in analysis_keywords):
            return None

        # TH 4: Ý định tải Audio / Âm thanh / MP3 rõ ràng (Ưu tiên kiểm tra trước Video)
        audio_keywords = (
            "tải mp3", "tai mp3", "down mp3", "download mp3", "lấy mp3", "lay mp3", "xin mp3", "xin link mp3",
            "tải nhạc", "tai nhac", "lấy nhạc", "lay nhac", "down nhạc", "down nhac", "download nhạc", "download nhac",
            "kéo nhạc", "keo nhac", "xin nhạc", "xin nhac",
            "tải audio", "tai audio", "lấy audio", "lay audio", "down audio", "download audio", "xin audio", "lay file audio",
            "tách nhạc", "tach nhac", "tách audio", "tach audio", "tách âm thanh", "tach am thanh",
            "trích âm thanh", "trich am thanh", "trích xuất âm thanh", "trich xuat am thanh", "trích nhạc", "trich nhac",
            "tải bài hát", "tai bai hat", "lấy bài hát", "lay bai hat", "xin bài hát", "xin bai hat",
            "chuyển sang mp3", "chuyen sang mp3", "chuyển thành mp3", "chuyen thanh mp3",
            "đổi sang mp3", "doi sang mp3", "sang mp3", "ra mp3", "thành mp3", "thanh mp3",
            "chỉ lấy nhạc", "chi lay nhac", "chỉ lấy audio", "chi lay audio", "chỉ lấy mp3", "chi lay mp3",
            "chỉ cần nhạc", "chi can nhac", "chỉ cần audio", "chi can audio", "chỉ cần mp3", "chi can mp3",
            "nhạc tiktok", "nhac tiktok", "audio tiktok", "mp3 tiktok",
            "nhạc youtube", "nhac youtube", "audio youtube", "mp3 youtube",
            "nhạc facebook", "nhac facebook", "audio facebook", "mp3 facebook",
            "nhạc chuông", "nhac chuong", "bản nhạc", "ban nhac",
            "file mp3", "file nhạc", "file nhac", "file audio",
            "mp3", "audio",
        )
        if any(k in remaining_text for k in audio_keywords):
            return FastPathMediaIntent(media_url, remaining_text, media_type="audio")

        # TH 5: Có từ khóa thể hiện ý định tải video rõ ràng
        download_keywords = (
            "tải", "down", "download", "save", "chuyển file",
            "tải video", "tải clip", "kéo video", "kéo clip", "tải về", "lấy video", "lấy clip", "lấy file",
            "lưu video", "lưu clip", "lưu về", "gửi cho anh", "gửi em",
            "tai video", "tai clip", "keo video", "keo clip", "tai ve", "lay video", "lay clip", "lay file",
            "tai giup", "tai ho", "tai ve may", "tai xuong", "gui em", "gui anh",
            "tải giúp", "tải hộ", "tải giùm", "tai gium", "tải về máy", "tải xuống",
            "luu video", "luu clip", "luu ve",
        )
        if any(k in remaining_text for k in download_keywords):
            return FastPathMediaIntent(media_url, remaining_text, media_type="video")

        return None

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

    async def send_photo(
        self,
        chat_id: str,
        photo_path: str,
        caption: Optional[str] = None,
        parse_mode: Optional[str] = "HTML",
    ) -> bool:
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
            data: Dict[str, Any] = {"chat_id": chat_id}
            if caption:
                data["caption"] = caption[:1024]
                if parse_mode:
                    data["parse_mode"] = parse_mode

            res = await self._http_client.post(url, data=data, files=files, timeout=40.0)
            if res.status_code == 200:
                logger.info("[TelegramBot] Photo successfully sent to %s (%s)", chat_id, photo_path)
                return True
            elif parse_mode and "can't parse entities" in res.text.lower():
                logger.warning("[TelegramBot] sendPhoto HTML parse error (%s). Retrying as plain text...", res.text[:120])
                data.pop("parse_mode", None)
                if caption:
                    data["caption"] = _strip_html_tags(caption)[:1024]
                res2 = await self._http_client.post(url, data=data, files=files, timeout=40.0)
                if res2.status_code == 200:
                    return True
            logger.warning("[TelegramBot] sendPhoto error %d: %s", res.status_code, res.text)
        except Exception as e:
            logger.error("[TelegramBot] Failed sending photo: %s", e, exc_info=True)
        return False

    async def send_photo_bytes(
        self,
        chat_id: str,
        photo_bytes: bytes,
        filename: str = "photo.png",
        caption: Optional[str] = None,
        parse_mode: Optional[str] = "HTML",
    ) -> bool:
        if not self.token or not photo_bytes:
            return False
        try:
            url = f"{self.api_url}/sendPhoto"
            files = {"photo": (filename, photo_bytes, "image/png")}
            data: Dict[str, Any] = {"chat_id": chat_id}
            if caption:
                data["caption"] = caption[:1024]
                if parse_mode:
                    data["parse_mode"] = parse_mode

            res = await self._http_client.post(url, data=data, files=files, timeout=40.0)
            if res.status_code == 200:
                return True
            elif parse_mode and "can't parse entities" in res.text.lower():
                logger.warning("[TelegramBot] send_photo_bytes HTML parse error. Retrying as plain text...")
                data.pop("parse_mode", None)
                if caption:
                    data["caption"] = _strip_html_tags(caption)[:1024]
                res2 = await self._http_client.post(url, data=data, files=files, timeout=40.0)
                return res2.status_code == 200
        except Exception as e:
            logger.error("[TelegramBot] Failed sending photo bytes: %s", e)
        return False

    async def send_document(
        self,
        chat_id: str,
        file_bytes: bytes,
        filename: str,
        caption: Optional[str] = None,
        parse_mode: Optional[str] = "HTML",
    ) -> bool:
        if not self.token or not file_bytes:
            return False
        try:
            url = f"{self.api_url}/sendDocument"
            files = {"document": (filename, file_bytes, "application/octet-stream")}
            data: Dict[str, Any] = {"chat_id": chat_id}
            if caption:
                data["caption"] = caption[:1024]
                if parse_mode:
                    data["parse_mode"] = parse_mode

            res = await self._http_client.post(url, data=data, files=files, timeout=60.0)
            if res.status_code == 200:
                return True
            elif parse_mode and "can't parse entities" in res.text.lower():
                logger.warning("[TelegramBot] send_document HTML parse error. Retrying as plain text...")
                data.pop("parse_mode", None)
                if caption:
                    data["caption"] = _strip_html_tags(caption)[:1024]
                res2 = await self._http_client.post(url, data=data, files=files, timeout=60.0)
                return res2.status_code == 200
            else:
                logger.warning("[TelegramBot] sendDocument error %d: %s", res.status_code, res.text)
        except Exception as e:
            logger.error("[TelegramBot] Failed sending document bytes: %s", e)
        return False

    async def send_document_file(
        self,
        chat_id: str,
        file_path: Union[str, Path],
        filename: Optional[str] = None,
        caption: Optional[str] = None,
        parse_mode: Optional[str] = "HTML",
    ) -> bool:
        """Gửi tệp tin trực tiếp bằng streaming từ đĩa (Zero-RAM Leak) thay vì nạp toàn bộ vào RAM."""
        if not self.token or not file_path:
            return False
        try:
            p = Path(file_path)
            if not p.exists() or not p.is_file():
                logger.error("[TelegramBot] Document file not found: %s", file_path)
                return False
            name = filename or p.name
            url = f"{self.api_url}/sendDocument"
            data: Dict[str, Any] = {"chat_id": chat_id}
            if caption:
                data["caption"] = caption[:1024]
                if parse_mode:
                    data["parse_mode"] = parse_mode

            with open(p, "rb") as f:
                files = {"document": (name, f, "application/octet-stream")}
                res = await self._http_client.post(url, data=data, files=files, timeout=120.0)

                if res.status_code == 200:
                    return True
                elif parse_mode and "can't parse entities" in res.text.lower():
                    logger.warning("[TelegramBot] send_document_file HTML parse error. Retrying as plain text...")
                    f.seek(0)
                    data.pop("parse_mode", None)
                    if caption:
                        data["caption"] = _strip_html_tags(caption)[:1024]
                    files = {"document": (name, f, "application/octet-stream")}
                    res2 = await self._http_client.post(url, data=data, files=files, timeout=120.0)
                    return res2.status_code == 200
                else:
                    logger.warning("[TelegramBot] send_document_file error %d: %s", res.status_code, res.text)
        except Exception as e:
            logger.error("[TelegramBot] Failed sending document file: %s", e, exc_info=True)
        return False

    async def send_video(
        self,
        chat_id: str,
        video_path: str,
        caption: Optional[str] = None,
        duration: int = 0,
        width: int = 0,
        height: int = 0,
        supports_streaming: bool = True,
        parse_mode: Optional[str] = "HTML",
    ) -> bool:
        """Gửi tệp video MP4 trực tiếp qua Telegram Bot API với hỗ trợ streaming và parse_mode HTML."""
        if not self.token or not video_path:
            return False
        try:
            p = Path(video_path)
            if not p.exists():
                logger.error("[TelegramBot] Video file not found: %s", video_path)
                return False

            file_size = p.stat().st_size
            if file_size > 50 * 1024 * 1024:
                logger.warning("[TelegramBot] Video exceeds 50MB limit (%d bytes)", file_size)
                return False

            url = f"{self.api_url}/sendVideo"
            data: Dict[str, Any] = {
                "chat_id": chat_id,
                "supports_streaming": "true" if supports_streaming else "false",
            }
            if caption:
                data["caption"] = caption[:1024]
                if parse_mode:
                    data["parse_mode"] = parse_mode
            if duration > 0:
                data["duration"] = str(duration)
            if width > 0 and height > 0:
                data["width"] = str(width)
                data["height"] = str(height)

            with open(p, "rb") as f:
                files = {"video": (p.name, f, "video/mp4")}
                res = await self._http_client.post(url, data=data, files=files, timeout=120.0)

                if res.status_code == 200:
                    logger.info("[TelegramBot] Video successfully sent to %s (%s)", chat_id, video_path)
                    return True

                # Resilient Fallback: Nếu Telegram báo lỗi parse entities, retry bằng Plain Text không tốn thêm RAM
                if parse_mode and "can't parse entities" in res.text.lower():
                    logger.warning("[TelegramBot] sendVideo HTML parse error (%s). Retrying as plain text...", res.text[:120])
                    f.seek(0)
                    data.pop("parse_mode", None)
                    if caption:
                        data["caption"] = _strip_html_tags(caption)[:1024]
                    files = {"video": (p.name, f, "video/mp4")}
                    res2 = await self._http_client.post(url, data=data, files=files, timeout=120.0)
                    if res2.status_code == 200:
                        logger.info("[TelegramBot] Video successfully sent via plain text fallback to %s", chat_id)
                        return True
                    else:
                        logger.warning("[TelegramBot] sendVideo fallback error %d: %s", res2.status_code, res2.text)
                else:
                    logger.warning("[TelegramBot] sendVideo error %d: %s", res.status_code, res.text)
        except Exception as e:
            logger.error("[TelegramBot] Failed sending video: %s", e, exc_info=True)
        return False

    async def send_audio(
        self,
        chat_id: str,
        audio_path: Union[str, Path],
        caption: Optional[str] = None,
        title: Optional[str] = None,
        performer: Optional[str] = None,
        duration: int = 0,
        parse_mode: Optional[str] = "HTML",
        **kwargs: Any,
    ) -> bool:
        """
        Gửi tệp âm thanh MP3 trực tiếp qua Telegram Bot API (/sendAudio)
        với đầy đủ siêu dữ liệu (performer, title, duration) để Telegram hiển thị
        Native Audio Player Card (Waveform + Play/Pause button).
        Bảo toàn Zero-RAM streaming từ đĩa và Resilient Plain Text fallback với f.seek(0).
        """
        if not self.token or not audio_path:
            return False

        # Support flexible positional arguments (title, performer, duration, caption)
        if isinstance(performer, (int, float)) and isinstance(duration, str):
            title, performer, duration, caption = caption, title, int(performer), duration

        try:
            p = Path(audio_path)
            if not p.exists() or not p.is_file():
                logger.error("[TelegramBot] Audio file not found: %s", audio_path)
                return False

            file_size = p.stat().st_size
            if file_size > 50 * 1024 * 1024:
                logger.warning("[TelegramBot] Audio exceeds 50MB limit (%d bytes)", file_size)
                return False

            url = f"{self.api_url}/sendAudio"
            data: Dict[str, Any] = {
                "chat_id": chat_id,
            }
            if caption:
                data["caption"] = caption[:1024]
                if parse_mode:
                    data["parse_mode"] = parse_mode
            if duration > 0:
                data["duration"] = str(duration)
            if title:
                data["title"] = str(title)[:256]
            if performer:
                data["performer"] = str(performer)[:256]

            # Xác định MIME type phù hợp (chuẩn audio/mpeg cho mp3)
            mime_type = "audio/mpeg"
            suffix = p.suffix.lower()
            if suffix == ".m4a":
                mime_type = "audio/mp4"
            elif suffix == ".ogg":
                mime_type = "audio/ogg"
            elif suffix == ".wav":
                mime_type = "audio/wav"

            stream = _AudioFileStream(open(p, "rb"), file_size)
            try:
                files = {"audio": (p.name, stream, mime_type)}
                res = await self._http_client.post(url, data=data, files=files, timeout=120.0)

                if res.status_code == 200:
                    if stream.tell() < file_size:
                        stream.seek(0, os.SEEK_END)
                    logger.info("[TelegramBot] Audio successfully sent to %s (%s)", chat_id, audio_path)
                    return True

                # Resilient Fallback: Nếu Telegram báo lỗi parse entities, retry bằng Plain Text không tốn thêm RAM
                if parse_mode and "can't parse entities" in res.text.lower():
                    logger.warning("[TelegramBot] sendAudio HTML parse error (%s). Retrying as plain text...", res.text[:120])
                    stream.seek(0)
                    data.pop("parse_mode", None)
                    if caption:
                        data["caption"] = _strip_html_tags(caption)[:1024]
                    files = {"audio": (p.name, stream, mime_type)}
                    res2 = await self._http_client.post(url, data=data, files=files, timeout=120.0)
                    if res2.status_code == 200:
                        if stream.tell() < file_size:
                            stream.seek(0, os.SEEK_END)
                        logger.info("[TelegramBot] Audio successfully sent via plain text fallback to %s", chat_id)
                        return True
                    else:
                        logger.warning("[TelegramBot] sendAudio fallback error %d: %s", res2.status_code, res2.text)
                else:
                    logger.warning("[TelegramBot] sendAudio error %d: %s", res.status_code, res.text)
            finally:
                stream.close()
        except Exception as e:
            logger.error("[TelegramBot] Failed sending audio: %s", e, exc_info=True)
        return False

    async def delete_message(self, chat_id: str, message_id: int) -> bool:
        """Thu hồi hoặc xóa tin nhắn đã gửi trên Telegram."""
        if not self.token or not message_id:
            return False
        try:
            url = f"{self.api_url}/deleteMessage"
            payload = {"chat_id": chat_id, "message_id": message_id}
            res = await self._http_client.post(url, json=payload, timeout=10.0)
            return res.status_code == 200
        except Exception as e:
            logger.debug("[TelegramBot] Failed deleting message %s: %s", message_id, e)
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

        # Handle Video Analysis Actions
        elif data.startswith("video_act:"):
            action = data.split(":")[1]
            await self.answer_callback_query(query_id, text="🎬 Đang xử lý video theo yêu cầu...")
            await self.edit_message_text(chat_id, message_id, "🎬 <i>Đang phân tích video...</i>", reply_markup=None)
            await self._video_debounce.handle_callback_action(chat_id, action)
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

    async def _on_video_debounce_timeout(self, chat_id: str, session: PendingVideoSession) -> None:
        """
        Invoked when the 5-second debounce timer expires without subsequent text instruction.
        Sends an interactive Inline Keyboard with 3 quick analysis options.
        """
        duration_str = f"{session.metadata.duration}s" if session.metadata.duration > 0 else "vừa gửi"
        msg = (
            f"🎬 <b>Tiểu Bảo Bảo đã nhận được video ({duration_str})!</b>\n\n"
            f"Anh Mạnh muốn em giúp gì với video này ạ? Anh có thể chọn nhanh thao tác bên dưới hoặc nhắn trực tiếp câu hỏi/chỉ đạo cho em nhé! 👇"
        )
        reply_markup = {
            "inline_keyboard": [
                [
                    {
                        "text": "📝 Tóm tắt nội dung video",
                        "callback_data": "video_act:summarize",
                    },
                    {
                        "text": "🎙️ Bóc tách lời thoại (STT)",
                        "callback_data": "video_act:transcribe",
                    },
                ],
                [
                    {
                        "text": "🔍 Phân tích khung hình & hành động",
                        "callback_data": "video_act:visual_analyze",
                    },
                ],
            ]
        }
        await self.send_message(chat_id, msg, reply_markup=reply_markup)

    async def _on_video_process_pipeline(
        self, chat_id: str, session: PendingVideoSession, instruction: str
    ) -> None:
        """
        Executes the Lightweight Video Pipeline and feeds multimodal context to AI Agent.
        """
        try:
            await self.send_message(
                chat_id,
                f"⚡ <i>Đang phân tích video theo yêu cầu:</i> \"{instruction}\"...\n"
                f"<i>(Tiểu Bảo Bảo đang trích xuất âm thanh và khung hình)</i>",
            )
            context = await self._video_pipeline.process_video(
                video_path=session.video_path,
                filename=session.metadata.filename,
                duration=session.metadata.duration,
                instruction=instruction,
            )
            prompt = f"{context}\n\n[Chỉ đạo/Yêu cầu từ anh Mạnh]: {instruction}"
            reply = await self.chat_with_agent(chat_id, prompt)
            await self.send_message(chat_id, reply)
        except Exception as err:
            logger.error("[TelegramBot] Error running video pipeline for %s: %s", chat_id, err, exc_info=True)
            await self.send_message(
                chat_id, f"Xin lỗi anh Mạnh, đã xảy ra lỗi trong quá trình phân tích video ({err})."
            )

    async def _handle_video_message(
        self,
        chat_id: str,
        message: Dict[str, Any],
        video_obj: Dict[str, Any],
        is_video_note: bool = False,
    ) -> None:
        """
        Ingests video/video_note from Telegram, verifies file size, streams to disk,
        and registers with VideoDebounceManager.
        """
        file_id = video_obj.get("file_id", "")
        file_size = video_obj.get("file_size", 0)
        duration = video_obj.get("duration", 0)
        width = video_obj.get("width", 0)
        height = video_obj.get("height", 0)
        filename = video_obj.get("file_name", "video_note.mp4" if is_video_note else "video.mp4")
        caption = (message.get("caption") or "").strip()

        logger.info(
            "[TelegramBot] Video received from %s (file_id=%s, size=%d bytes, duration=%ds, caption='%s')",
            chat_id,
            file_id[:12] if file_id else "none",
            file_size,
            duration,
            caption[:30],
        )

        # Telegram Bot API guard: 20MB download limit
        if file_size > 20 * 1024 * 1024:
            await self.send_message(
                chat_id,
                f"⚠️ Video <code>{filename}</code> quá lớn ({file_size // 1048576}MB).\n"
                f"Telegram Bot API chỉ hỗ trợ bot tải tệp tối đa <b>20MB</b>. Anh vui lòng nén nhỏ lại giúp em nhé!",
            )
            return

        # Prepare disk location
        temp_dir = tempfile.mkdtemp(prefix="tg_video_")
        dest_ext = Path(filename).suffix.lower() or ".mp4"
        video_dest_path = Path(temp_dir) / f"input_video{dest_ext}"

        try:
            await self.send_chat_action(chat_id, "record_video")
            await self._media.download_telegram_file_to_path(file_id, video_dest_path)
        except Exception as dl_err:
            logger.error("[TelegramBot] Failed downloading video %s: %s", file_id, dl_err, exc_info=True)
            shutil.rmtree(temp_dir, ignore_errors=True)
            await self.send_message(
                chat_id, f"❌ Không thể tải video từ Telegram ({dl_err}). Vui lòng thử lại sau."
            )
            return

        metadata = VideoMetadata(
            duration=duration,
            width=width,
            height=height,
            filename=filename,
            file_size=file_size,
        )

        await self._video_debounce.register_video(
            chat_id=chat_id,
            file_id=file_id,
            temp_dir=temp_dir,
            video_path=str(video_dest_path),
            metadata=metadata,
            caption=caption,
        )

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

        # ── 2c. Video / Video Note ────────────────────────────────────────────
        video = message.get("video") or message.get("video_note")
        if video:
            is_note = bool(message.get("video_note"))
            await self._handle_video_message(chat_id, message, video, is_video_note=is_note)
            return

        # ── 2d. Document / File ───────────────────────────────────────────────
        document = message.get("document")
        if document:
            file_id = document.get("file_id", "")
            filename = document.get("file_name", "unknown")
            mime_type = document.get("mime_type", "")
            file_size = document.get("file_size", 0)
            caption = (message.get("caption") or "").strip()
            logger.info("[TelegramBot] Document from %s: %s (%s, %d bytes)", chat_id, filename, mime_type, file_size)

            ext = Path(filename).suffix.lower()
            video_exts = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".3gp"}
            mime_lower = (mime_type or "").lower()
            if mime_lower.startswith("video/") or ext in video_exts:
                await self._handle_video_message(chat_id, message, document, is_video_note=False)
                return

            # Telegram Bot API only allows downloading files up to 20MB
            if file_size > 20 * 1024 * 1024:
                await self.send_message(chat_id, f"⚠️ File `{filename}` quá lớn ({file_size // 1048576}MB). Giới hạn tải là 20MB.")
                return
            try:
                file_bytes = await self._media.download_telegram_file(file_id)
                archive_exts = {".zip", ".rar", ".tar", ".gz", ".tgz", ".bz2", ".tbz2", ".xz", ".txz", ".7z", ".jar", ".war"}
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

        # ── 2e. Text Message ──────────────────────────────────────────────────
        text = (message.get("text") or "").strip()
        if not text:
            return

        # Check for active video debounce session waiting for instructions
        if not text.startswith("/") and await self._video_debounce.handle_user_text(chat_id, text):
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

        # ── FAST-PATH: Media Download Auto-Intent Interceptor ────────────
        media_intent = self._detect_fastpath_media_download(text)
        if media_intent:
            media_url, custom_caption = media_intent
            media_type = getattr(media_intent, "media_type", "video")
            logger.info("[TelegramBot] Fast-path intercepted media download URL: %s (type=%s)", media_url, media_type)

            if media_type == "audio":
                status_text = "⚡ <i>Tiểu Bảo Bảo đang trích xuất âm thanh MP3 trực tiếp cho anh Mạnh, đợi em một xíu nhé...</i>"
            else:
                status_text = "⚡ <i>Tiểu Bảo Bảo đang tải video trực tiếp cho anh Mạnh, đợi em một xíu nhé...</i>"

            status_msg = await self.send_message_with_result(
                chat_id,
                status_text,
            )
            media_item = None
            try:
                from app.services.media_downloader import MultiTierMediaPipeline, VideoTooLargeError
                pipeline = MultiTierMediaPipeline(http_client=self._http_client)

                if media_type == "audio":
                    media_item = await pipeline.download_audio(media_url)
                else:
                    media_item = await pipeline.download(media_url)

                if media_item.media_type == "audio" and media_item.file_path:
                    raw_title = media_item.title or "Audio Track"
                    if len(raw_title) > 350:
                        raw_title = raw_title[:347] + "..."
                    safe_title = html.escape(raw_title)
                    safe_author = html.escape(media_item.author or "Unknown")
                    file_size = media_item.file_size
                    total_mb = file_size / (1024 * 1024)

                    caption = (
                        f"🎵 <b>{safe_title}</b>\n"
                        f"👤 Nghệ sĩ / Kênh: <code>@{safe_author}</code>\n"
                        f"⏱ Thời lượng: {media_item.duration}s | 📦 Dung lượng: {total_mb:.1f} MB\n\n"
                        f"✨ <i>Tiểu Bảo Bảo đã trích xuất thành công âm thanh MP3 chất lượng cao cho anh Mạnh!</i>"
                    )

                    if file_size <= 50 * 1024 * 1024:
                        sent = await self.send_audio(
                            chat_id=chat_id,
                            audio_path=media_item.file_path,
                            caption=caption,
                            title=raw_title,
                            performer=media_item.author or "Unknown",
                            duration=media_item.duration,
                        )
                        if not sent:
                            logger.warning("[TelegramBot] send_audio failed, falling back to send_document_file")
                            await self.send_document_file(
                                chat_id=chat_id,
                                file_path=media_item.file_path,
                                filename=Path(media_item.file_path).name,
                                caption=caption,
                            )
                    else:
                        # Audio > 50MB: Kích hoạt liên kết tải trực tiếp qua media_storage_manager
                        clean_filename = Path(media_item.file_path).name
                        download_rec = media_storage_manager.publish_download_item(
                            file_path=media_item.file_path,
                            filename=clean_filename,
                            title=raw_title,
                            duration=media_item.duration,
                            ttl_seconds=4 * 3600,
                        )
                        media_item.is_temp_file = False
                        await self.send_message(
                            chat_id,
                            f"📦 <b>Tệp âm thanh MP3 có dung lượng lớn ({total_mb:.1f} MB)!</b>\n\n"
                            f"🔗 Anh Mạnh có thể tải trực tiếp file MP3 nguyên khối tại:\n"
                            f"🌐 <b>Link Internet (Ngrok):</b> {download_rec.internet_url}\n"
                            f"🏠 <b>Link Nội Bộ (LAN):</b> {download_rec.lan_url}\n\n"
                            f"<i>(Đường link trực tiếp có hiệu lực trong vòng 4 giờ)</i>"
                        )
                elif media_item.media_type == "video" and media_item.file_path:
                    raw_title = media_item.title or "Video"
                    if len(raw_title) > 350:
                        raw_title = raw_title[:347] + "..."
                    safe_title = html.escape(raw_title)
                    safe_author = html.escape(media_item.author or "Unknown")
                    file_size = media_item.file_size
                    total_mb = file_size / (1024 * 1024)

                    if file_size <= 50 * 1024 * 1024:
                        # Video <= 50MB: Gửi 1 video duy nhất qua send_video
                        caption = (
                            f"🎬 <b>{safe_title}</b>\n"
                            f"👤 Kênh: <code>@{safe_author}</code>\n"
                            f"⏱ Thời lượng: {media_item.duration}s | 📦 Dung lượng: {total_mb:.1f} MB\n\n"
                            f"✨ <i>Tiểu Bảo Bảo đã tải thành công video không logo cho anh Mạnh!</i>"
                        )
                        sent = await self.send_video(
                            chat_id=chat_id,
                            video_path=media_item.file_path,
                            caption=caption,
                            duration=media_item.duration,
                        )
                        if not sent:
                            # Fallback stream trực tiếp từ đĩa (Zero-RAM Leak) thay vì nạp toàn bộ vào RAM
                            await self.send_document_file(
                                chat_id=chat_id,
                                file_path=media_item.file_path,
                                filename=Path(media_item.file_path).name,
                                caption=caption,
                            )
                    else:
                        # Video > 50MB: Kích hoạt Phân phối video kép (Dual-Track Large Video Distribution)
                        # Thông báo chuẩn bị chia phần
                        await self.send_message(
                            chat_id,
                            f"📦 <b>Video chất lượng gốc có dung lượng lớn ({total_mb:.1f} MB)!</b>\n"
                            f"⚡ <i>Tiểu Bảo Bảo đang chia thành các phần chuẩn HD để gửi qua Telegram và tạo liên kết tải trực tiếp cho anh Mạnh...</i>"
                        )

                        # Kênh 2: Chuyển quyền sở hữu tệp gốc sang media_storage_manager để phục vụ Direct Download
                        clean_filename = Path(media_item.file_path).name
                        download_rec = media_storage_manager.publish_download_item(
                            file_path=media_item.file_path,
                            filename=clean_filename,
                            title=raw_title,
                            duration=media_item.duration,
                            ttl_seconds=4 * 3600,
                        )
                        # Đánh dấu tệp gốc đã chuyển giao quyền sở hữu sang public storage (quản lý bởi TTL sweeper)
                        media_item.is_temp_file = False

                        # Kênh 1: Cắt tệp gốc (tại download_rec.file_path) bằng VideoChunker.split_video() trong thư mục tạm
                        parts_dir = Path(tempfile.mkdtemp(prefix="media_parts_", dir=str(media_storage_manager.temp_dir)))
                        try:
                            parts = await VideoChunker.split_video(
                                video_path=str(download_rec.file_path),
                                output_dir=parts_dir,
                            )
                            total_parts = len(parts)

                            for p_info in parts:
                                p_idx = p_info["part_index"]
                                p_path = p_info["path"]
                                p_dur = p_info["duration"]
                                p_size_mb = p_info["size"] / (1024 * 1024)

                                part_caption = (
                                    f"🎬 <b>{safe_title}</b> (Phần {p_idx}/{total_parts})\n"
                                    f"👤 Kênh: <code>@{safe_author}</code>\n"
                                    f"⏱ Thời lượng: {p_dur}s | 📦 Dung lượng: {p_size_mb:.1f} MB (Gốc: {total_mb:.1f} MB)\n\n"
                                    f"✨ <i>Chất lượng gốc 100% không suy hao (Lossless)!</i>"
                                )
                                sent_part = await self.send_video(
                                    chat_id=chat_id,
                                    video_path=p_path,
                                    caption=part_caption,
                                    duration=p_dur,
                                    width=p_info.get("width", 0),
                                    height=p_info.get("height", 0),
                                )
                                if not sent_part:
                                    await self.send_document_file(
                                        chat_id=chat_id,
                                        file_path=p_path,
                                        filename=Path(p_path).name,
                                        caption=part_caption,
                                    )

                                # Streaming Purge: Xóa ngay part vừa gửi để bảo đảm Zero-Disk-Leak
                                try:
                                    os.unlink(p_path)
                                except Exception:
                                    pass

                                # Chống Telegram 429 FloodWait
                                if p_idx < total_parts:
                                    await asyncio.sleep(1.0)

                            # Gửi thông báo hoàn tất kèm cả 2 đường link tải trực tiếp nguyên khối (Ngrok & LAN)
                            await self.send_message(
                                chat_id,
                                f"✨ <b>Đã gửi trọn vẹn {total_parts}/{total_parts} phần lên Telegram!</b>\n\n"
                                f"🔗 Hoặc anh Mạnh có thể bấm tải trực tiếp toàn bộ video gốc nguyên khối ({total_mb:.1f} MB) tại:\n"
                                f"🌐 <b>Link Internet (Ngrok):</b> {download_rec.internet_url}\n"
                                f"🏠 <b>Link Nội Bộ (LAN):</b> {download_rec.lan_url}\n\n"
                                f"<i>(Đường link trực tiếp có hiệu lực trong vòng 4 giờ)</i>"
                            )
                        finally:
                            shutil.rmtree(parts_dir, ignore_errors=True)
                elif media_item.media_type == "images" and media_item.images:
                    safe_title = html.escape(media_item.title)
                    safe_author = html.escape(media_item.author)
                    album_caption = f"📸 <b>{safe_title}</b>\n👤 Kênh: <code>@{safe_author}</code>"
                    for idx, img_url in enumerate(media_item.images[:10]):
                        await self.send_photo(chat_id, photo_path=img_url, caption=album_caption if idx == 0 else None)

                if status_msg and status_msg.get("message_id"):
                    await self.delete_message(chat_id, status_msg["message_id"])
                return
            except VideoTooLargeError as v_err:
                logger.warning("[TelegramBot] Video exceeds 50MB: %s", v_err)
                await self.send_message(
                    chat_id,
                    f"⚠️ <b>Video có dung lượng vượt quá giới hạn 50MB của Telegram Bot!</b>\n\n"
                    f"🔗 Anh có thể mở hoặc tải trực tiếp tại liên kết: {media_url}"
                )
                if status_msg and status_msg.get("message_id"):
                    await self.delete_message(chat_id, status_msg["message_id"])
                return
            except Exception as dl_err:
                logger.error("[TelegramBot] Fast-path media download error: %s", dl_err, exc_info=True)
                action_name = "trích xuất âm thanh MP3" if media_type == "audio" else "tải video"
                await self.send_message(chat_id, f"❌ Xin lỗi anh Mạnh, em gặp sự cố khi {action_name} ({dl_err}). Em sẽ chuyển tiếp yêu cầu sang AI Agent.")
                if status_msg and status_msg.get("message_id"):
                    await self.delete_message(chat_id, status_msg["message_id"])
            finally:
                if media_item:
                    media_item.cleanup()

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
                enriched_text = linguistic_normalizer.enrich_dialect_semantics(text)
                if enriched_text != text:
                    logger.info("[TelegramBot] Dialect enriched: '%s' -> '%s'", text, enriched_text)
                reply = await self.chat_with_agent(chat_id, enriched_text)
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
