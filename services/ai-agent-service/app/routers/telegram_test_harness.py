"""
telegram_test_harness.py — Synthetic Telegram Test Harness Router & Security Guards.

Feature F12 & F13 (Milestone 4):
1. Endpoint POST /api/internal/test-harness/telegram/inject (Approach "A").
2. 3-Layer Security Guard:
   - Layer 1: Environment Flag Gate (ENABLE_TELEGRAM_TEST_HARNESS == True) -> 403 Forbidden
   - Layer 2: Authentication (Bearer token hoặc X-Test-Harness-Key khớp TEST_HARNESS_SECRET_KEY / JWT) -> 401 Unauthorized
   - Layer 3: Client IP Whitelisting (localhost, RFC1918 private subnets 10/8, 172.16/12, 192.168/16 & anti-spoofing) -> 403 Forbidden
3. Coroutine-isolated TestHarnessTranscriptCapture using contextvars.ContextVar.
4. Local video ingestion bypass (shutil.copy2) to run 100% offline without Telegram Cloud.
"""

import asyncio
import contextvars
from datetime import datetime, timezone
import hmac
import ipaddress
import logging
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any, Dict, List, Optional

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.config import settings
from app.services.video_pipeline import PendingVideoSession, VideoMetadata

logger = logging.getLogger("telegram_test_harness")

router = APIRouter(
    prefix="/api/internal/test-harness/telegram",
    tags=["test-harness"],
)

bearer_scheme = HTTPBearer(auto_error=False)


# =============================================================================
# 1. Pydantic Models (Schemas)
# =============================================================================

class SyntheticTelegramUpdateRequest(BaseModel):
    chat_id: int = Field(
        default=0,
        description="Telegram Chat ID. Nếu bằng 0, tự động lấy giá trị từ settings.TELEGRAM_CHAT_ID hoặc bot.",
    )
    user_id: int = Field(
        default=0,
        description="Telegram User ID của người gửi. Nếu bằng 0, mặc định bằng chat_id.",
    )
    message_id: int = Field(
        default=1001,
        description="ID tin nhắn giả lập ban đầu.",
    )
    caption: Optional[str] = Field(
        default="xóa sạch text trong video giúp tôi",
        description="Chỉ đạo hoặc caption gửi kèm video.",
    )
    video_path: Optional[str] = Field(
        default=None,
        description="Đường dẫn tuyệt đối tới tệp video kiểm thử trên máy chủ (ví dụ: tests/fixtures/tmpy8evxmno.mp4).",
    )
    video_url: Optional[str] = Field(
        default=None,
        description="Đường dẫn URL tải video nếu không dùng tệp cục bộ.",
    )
    options: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Các tùy chọn kiểm thử nâng cao (timeout_sec, forward_to_telegram, bypass_size_limit, mode).",
    )


class SyntheticTelegramInjectionResponse(BaseModel):
    success: bool = Field(
        ...,
        description="Trạng thái thực thi pipeline có thành công hay không.",
    )
    error: Optional[str] = Field(
        default=None,
        description="Thông điệp lỗi chi tiết nếu xử lý thất bại.",
    )
    duration_sec: float = Field(
        ...,
        description="Tổng thời gian thực thi (giây).",
    )
    transcript: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Nhật ký các sự kiện tương tác của bot theo trình tự thời gian.",
    )
    output_video_path: Optional[str] = Field(
        default=None,
        description="Đường dẫn tuyệt đối tới tệp video kết quả đã làm sạch sau biên tập.",
    )
    caption: Optional[str] = Field(
        default=None,
        description="Caption gửi kèm video thành phẩm (chứa AI Quality Audit bảng tổng kết).",
    )
    critique: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Dữ liệu critique và AI Quality Audit nếu có.",
    )
    metrics: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Các streaming CPU metrics trích xuất được.",
    )


# =============================================================================
# 2. Multi-Layer Security Guard (3 Lớp Bảo Mật)
# =============================================================================

def get_test_harness_secret() -> str:
    """Lấy secret key cho test harness, ưu tiên TEST_HARNESS_SECRET_KEY, fallback JWT_SECRET."""
    secret = (getattr(settings, "TEST_HARNESS_SECRET_KEY", "") or "").strip()
    if not secret:
        secret = (getattr(settings, "JWT_SECRET", "") or "").strip()
    return secret or "sentinel-telegram-test-harness-default-key-32chars"


def is_ip_whitelisted(ip_str: str, allowed_cidrs: Optional[List[str]] = None) -> bool:
    """
    Kiểm tra địa chỉ IP có thuộc danh sách IP/CIDR nội bộ cho phép hay không.
    Hỗ trợ IPv4, IPv6, localhost và các dải CIDR RFC 1918.
    """
    if not ip_str:
        return False

    clean_ip = ip_str.strip().lower()
    if clean_ip in ("localhost", "127.0.0.1", "::1", "testclient"):
        return True

    try:
        ip_obj = ipaddress.ip_address(clean_ip)
    except ValueError:
        logger.warning("[TestHarnessSecurity] Invalid IP address format: %s", clean_ip)
        return False

    if ip_obj.is_loopback:
        return True

    cidrs = allowed_cidrs or getattr(
        settings,
        "TEST_HARNESS_ALLOWED_IPS",
        ["127.0.0.1", "::1", "localhost", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"],
    )

    for cidr in cidrs:
        cidr_clean = str(cidr).strip()
        if not cidr_clean or cidr_clean.lower() == "localhost":
            continue
        try:
            if "/" in cidr_clean:
                net = ipaddress.ip_network(cidr_clean, strict=False)
                if ip_obj in net:
                    return True
            else:
                target_ip = ipaddress.ip_address(cidr_clean)
                if ip_obj == target_ip:
                    return True
        except ValueError:
            continue

    return False


async def verify_layer1_env_flag() -> None:
    """Lớp 1: Kiểm tra cờ môi trường ENABLE_TELEGRAM_TEST_HARNESS."""
    is_enabled = getattr(settings, "ENABLE_TELEGRAM_TEST_HARNESS", False)
    if not is_enabled:
        logger.warning("[TestHarnessSecurity] Lớp 1 từ chối: Cờ ENABLE_TELEGRAM_TEST_HARNESS đang tắt (False).")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Telegram test harness is disabled",
        )


async def verify_layer3_ip_whitelist(request: Request) -> None:
    """
    Lớp 3: Kiểm tra Client IP Whitelist (chống truy cập từ Public Internet).
    Đồng thời kiểm tra cả X-Forwarded-For để ngăn ngừa tấn công đi xuyên qua Reverse Proxy bên ngoài.
    """
    client_host = request.client.host if request.client else "127.0.0.1"
    if not is_ip_whitelisted(client_host):
        logger.warning("[TestHarnessSecurity] Lớp 3 từ chối: Client IP '%s' không nằm trong whitelist.", client_host)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: Client IP is not in internal whitelist ('{client_host}')",
        )

    # Chống IP Spoofing qua Reverse Proxy: Kiểm tra X-Forwarded-For nếu có
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        raw_ips = [ip.strip() for ip in forwarded_for.split(",") if ip.strip()]
        for f_ip in raw_ips:
            if not is_ip_whitelisted(f_ip):
                logger.warning(
                    "[TestHarnessSecurity] Lớp 3 từ chối: Phát hiện IP ngoài '%s' trong X-Forwarded-For header.",
                    f_ip,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access denied: Untrusted forwarded client IP '{f_ip}' detected",
                )


async def verify_layer2_authentication(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    x_test_harness_key: Optional[str] = Header(None, alias="X-Test-Harness-Key"),
) -> str:
    """
    Lớp 2: Xác thực danh tính qua JWT Token hoặc Shared Secret Key.
    Hỗ trợ:
      1. Header Authorization: Bearer <token_or_secret>
      2. Header X-Test-Harness-Key: <secret>
    """
    secret = get_test_harness_secret()
    token = credentials.credentials if credentials else None
    if not token and x_test_harness_key:
        token = x_test_harness_key.strip()

    if not token:
        logger.warning("[TestHarnessSecurity] Lớp 2 từ chối: Thiếu credentials xác thực.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Missing test harness credentials",
            headers={"WWW-Authenticate": 'Bearer error="missing_token"'},
        )

    # 1. So sánh Shared Secret Key an toàn (Timing-Attack safe)
    if hmac.compare_digest(token, secret):
        return "shared-secret-authenticated"

    # 2. Giải mã và xác thực JWT Token (PyJWT HMAC SHA-256)
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"verify_exp": True},
        )
        return str(payload.get("sub", "jwt-authenticated"))
    except jwt.ExpiredSignatureError:
        logger.warning("[TestHarnessSecurity] Lớp 2 từ chối: JWT token đã hết hạn.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Token has expired",
            headers={"WWW-Authenticate": 'Bearer error="token_expired"'},
        )
    except jwt.InvalidTokenError as exc:
        logger.warning("[TestHarnessSecurity] Lớp 2 từ chối: JWT token không hợp lệ (%s).", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Unauthorized: Invalid token ({exc})",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )


async def verify_test_harness_guard(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    x_test_harness_key: Optional[str] = Header(None, alias="X-Test-Harness-Key"),
) -> str:
    """
    FastAPI Composite Dependency kết hợp tuần tự cả 3 lớp bảo mật:
      Lớp 1: Cờ môi trường -> Lớp 3: IP Whitelist -> Lớp 2: Authentication
    """
    await verify_layer1_env_flag()
    await verify_layer3_ip_whitelist(request)
    return await verify_layer2_authentication(credentials, x_test_harness_key)


# =============================================================================
# 3. Coroutine-Isolated TestHarnessTranscriptCapture (ContextVar Interceptor)
# =============================================================================

_active_capture_context: contextvars.ContextVar[Optional["TestHarnessTranscriptCapture"]] = (
    contextvars.ContextVar("_active_capture_context", default=None)
)


class MockTelegramMessageDict(dict):
    """
    Dictionary đại diện cho đối tượng Message của Telegram API.
    Đồng thời luôn đánh giá là truthy (bool == True) để tương thích cả 2 cách dùng:
    isinstance(res, dict) hoặc bool(res).
    """
    def __bool__(self) -> bool:
        return True


class TestHarnessTranscriptCapture:
    """
    Async Context Manager cô lập từng coroutine (qua ContextVar) để:
    1. Intercept các outbound API calls của bot: send_message, edit_message_text,
       delete_message, send_video, send_video_file, send_chat_action.
    2. Bắt giữ chuỗi sự kiện đầy đủ thành transcript.
    3. Mock trả về dictionary chứa message_id tăng dần (1001, 1002...) để bot
       handler lấy được status_msg_id và thực hiện auto-cleanup chính xác.
    4. Intercept download_telegram_file_to_path để copy trực tiếp tệp video cục bộ.
    5. Lưu giữ đường dẫn video kết quả để caller có thể kiểm tra.
    """

    def __init__(
        self,
        bot: Any,
        local_video_path: Optional[str] = None,
        forward_to_telegram: bool = False,
    ):
        self.bot = bot
        self.local_video_path = local_video_path
        self.forward_to_telegram = forward_to_telegram
        self.events: List[Dict[str, Any]] = []
        self._next_message_id = 1000
        self._token: Optional[contextvars.Token] = None
        self._lock = asyncio.Lock()
        self._is_active = False
        self.output_video_path: Optional[str] = None
        self.final_caption: Optional[str] = None

    async def __aenter__(self) -> "TestHarnessTranscriptCapture":
        self._token = _active_capture_context.set(self)
        self._is_active = True
        self._ensure_bot_proxy_installed()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self._is_active = False
        if self._token is not None:
            _active_capture_context.reset(self._token)

    def _ensure_bot_proxy_installed(self) -> None:
        """Gắn bộ proxy thông minh vào bot instance (chỉ cài đặt 1 lần)."""
        if getattr(self.bot, "_harness_proxy_installed", False):
            return

        original_methods = {
            "send_message": getattr(self.bot, "send_message", None),
            "send_message_with_result": getattr(self.bot, "send_message_with_result", None),
            "edit_message_text": getattr(self.bot, "edit_message_text", None),
            "delete_message": getattr(self.bot, "delete_message", None),
            "send_video": getattr(self.bot, "send_video", None),
            "send_video_file": getattr(self.bot, "send_video_file", None),
            "send_chat_action": getattr(self.bot, "send_chat_action", None),
        }
        self.bot._original_telegram_methods = original_methods

        # Proxy wrappers kiểm tra ContextVar của từng coroutine task
        async def proxy_send_message(chat_id: Any, text: str, reply_markup=None, parse_mode="HTML", **kwargs):
            session = _active_capture_context.get()
            if session is not None and session._is_active:
                return await session.handle_send_message(chat_id, text, reply_markup, parse_mode, **kwargs)
            orig = original_methods["send_message"]
            return await orig(chat_id, text, reply_markup, parse_mode, **kwargs) if orig else True

        async def proxy_send_message_with_result(chat_id: Any, text: str, reply_markup=None, parse_mode="HTML", **kwargs):
            session = _active_capture_context.get()
            if session is not None and session._is_active:
                return await session.handle_send_message_with_result(chat_id, text, reply_markup, parse_mode, **kwargs)
            orig = original_methods["send_message_with_result"]
            return await orig(chat_id, text, reply_markup, parse_mode, **kwargs) if orig else {"message_id": 1001}

        async def proxy_edit_message_text(chat_id: Any, message_id: int, text: str, reply_markup=None, parse_mode="HTML", **kwargs):
            session = _active_capture_context.get()
            if session is not None and session._is_active:
                return await session.handle_edit_message_text(chat_id, message_id, text, reply_markup, parse_mode, **kwargs)
            orig = original_methods["edit_message_text"]
            return await orig(chat_id, message_id, text, reply_markup, parse_mode, **kwargs) if orig else True

        async def proxy_delete_message(chat_id: Any, message_id: int, **kwargs):
            session = _active_capture_context.get()
            if session is not None and session._is_active:
                return await session.handle_delete_message(chat_id, message_id, **kwargs)
            orig = original_methods["delete_message"]
            return await orig(chat_id, message_id, **kwargs) if orig else True

        async def proxy_send_video(chat_id: Any, video_path: str, caption=None, duration=0, width=0, height=0, supports_streaming=True, parse_mode="HTML", **kwargs):
            session = _active_capture_context.get()
            if session is not None and session._is_active:
                return await session.handle_send_video(chat_id, video_path, caption, duration, width, height, supports_streaming, parse_mode, **kwargs)
            orig = original_methods["send_video"]
            return await orig(chat_id, video_path, caption, duration, width, height, supports_streaming, parse_mode, **kwargs) if orig else True

        async def proxy_send_video_file(chat_id: Any, video_path: str, caption=None, duration=0, width=0, height=0, title=None, supports_streaming=True, cleanup_after_send=True, **kwargs):
            session = _active_capture_context.get()
            if session is not None and session._is_active:
                # Trong test harness không unlink file ngay để caller có thể inspect
                return await session.handle_send_video_file(chat_id, video_path, caption, duration, width, height, title, supports_streaming, cleanup_after_send=False, **kwargs)
            orig = original_methods["send_video_file"]
            if orig:
                return await orig(chat_id, video_path, caption, duration, width, height, title, supports_streaming, cleanup_after_send, **kwargs)
            return await proxy_send_video(chat_id, video_path, caption, duration, width, height, supports_streaming)

        async def proxy_send_chat_action(chat_id: Any, action="typing", **kwargs):
            session = _active_capture_context.get()
            if session is not None and session._is_active:
                return await session.handle_send_chat_action(chat_id, action, **kwargs)
            orig = original_methods["send_chat_action"]
            return await orig(chat_id, action, **kwargs) if orig else None

        # Gắn vào bot instance
        self.bot.send_message = proxy_send_message
        self.bot.send_message_with_result = proxy_send_message_with_result
        self.bot.edit_message_text = proxy_edit_message_text
        self.bot.delete_message = proxy_delete_message
        self.bot.send_video = proxy_send_video
        if hasattr(self.bot, "send_video_file"):
            self.bot.send_video_file = proxy_send_video_file
        if hasattr(self.bot, "send_chat_action"):
            self.bot.send_chat_action = proxy_send_chat_action

        # Mock download_telegram_file_to_path nếu bot._media tồn tại
        if hasattr(self.bot, "_media") and hasattr(self.bot._media, "download_telegram_file_to_path"):
            orig_download = self.bot._media.download_telegram_file_to_path
            self.bot._original_download_method = orig_download

            async def proxy_download_file(file_id: str, dest_path: Path):
                session = _active_capture_context.get()
                if session is not None and session._is_active:
                    return await session.handle_download_file(file_id, dest_path)
                return await orig_download(file_id, dest_path)

            self.bot._media.download_telegram_file_to_path = proxy_download_file

        self.bot._harness_proxy_installed = True

    # ── Handlers ghi nhận sự kiện ──

    async def _record_event(
        self,
        action: str,
        chat_id: Any,
        message_id: Optional[int] = None,
        text: Optional[str] = None,
        caption: Optional[str] = None,
        file_path: Optional[str] = None,
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        now = time.time()
        iso = datetime.now(timezone.utc).isoformat()
        ev = {
            "timestamp": now,
            "timestamp_iso": iso,
            "action": action,
            "chat_id": str(chat_id),
            "message_id": message_id,
            "text": text,
            "caption": caption,
            "file_path": file_path,
            "extra_params": extra_params or {},
        }
        async with self._lock:
            self.events.append(ev)
        return ev

    async def handle_download_file(self, file_id: str, dest_path: Path) -> None:
        """Local Video Ingestion Bypass: Copy trực tiếp từ local_video_path thay vì tải qua internet."""
        await self._record_event(
            action="download_file_intercepted",
            chat_id="internal",
            file_path=str(dest_path),
            extra_params={"file_id": file_id, "source_path": self.local_video_path},
        )
        if self.local_video_path and os.path.exists(self.local_video_path):
            os.makedirs(dest_path.parent, exist_ok=True)
            shutil.copy2(self.local_video_path, dest_path)
        else:
            raise FileNotFoundError(f"Local test video not found: {self.local_video_path}")

    async def handle_send_message(self, chat_id: Any, text: str, reply_markup=None, parse_mode="HTML", **kwargs) -> MockTelegramMessageDict:
        async with self._lock:
            self._next_message_id += 1
            msg_id = self._next_message_id

        await self._record_event(
            action="send_message",
            chat_id=chat_id,
            message_id=msg_id,
            text=text,
            extra_params={"parse_mode": parse_mode, "has_reply_markup": bool(reply_markup)},
        )
        if self.forward_to_telegram:
            orig = getattr(self.bot, "_original_telegram_methods", {}).get("send_message")
            if orig:
                try:
                    await orig(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode, **kwargs)
                except Exception as exc:
                    logger.debug("[Harness] Forward send_message failed: %s", exc)

        return MockTelegramMessageDict({
            "message_id": msg_id,
            "date": int(time.time()),
            "chat": {"id": int(chat_id) if str(chat_id).isdigit() else 123456789, "type": "private"},
            "text": text,
        })

    async def handle_send_message_with_result(self, chat_id: Any, text: str, reply_markup=None, parse_mode="HTML", **kwargs) -> MockTelegramMessageDict:
        return await self.handle_send_message(chat_id, text, reply_markup, parse_mode, **kwargs)

    async def handle_edit_message_text(self, chat_id: Any, message_id: int, text: str, reply_markup=None, parse_mode="HTML", **kwargs) -> bool:
        await self._record_event(
            action="edit_message_text",
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            extra_params={"parse_mode": parse_mode, "has_reply_markup": bool(reply_markup)},
        )
        if self.forward_to_telegram:
            orig = getattr(self.bot, "_original_telegram_methods", {}).get("edit_message_text")
            if orig:
                try:
                    await orig(chat_id, message_id, text, reply_markup=reply_markup, parse_mode=parse_mode, **kwargs)
                except Exception as exc:
                    logger.debug("[Harness] Forward edit_message_text failed: %s", exc)
        return True

    async def handle_delete_message(self, chat_id: Any, message_id: int, **kwargs) -> bool:
        await self._record_event(
            action="delete_message",
            chat_id=chat_id,
            message_id=message_id,
        )
        if self.forward_to_telegram:
            orig = getattr(self.bot, "_original_telegram_methods", {}).get("delete_message")
            if orig:
                try:
                    await orig(chat_id, message_id, **kwargs)
                except Exception as exc:
                    logger.debug("[Harness] Forward delete_message failed: %s", exc)
        return True

    async def handle_send_video(self, chat_id: Any, video_path: str, caption=None, duration=0, width=0, height=0, supports_streaming=True, parse_mode="HTML", **kwargs) -> bool:
        async with self._lock:
            self._next_message_id += 1
            msg_id = self._next_message_id

        self.output_video_path = str(video_path)
        self.final_caption = caption

        await self._record_event(
            action="send_video",
            chat_id=chat_id,
            message_id=msg_id,
            caption=caption,
            file_path=str(video_path),
            extra_params={
                "duration": duration,
                "width": width,
                "height": height,
                "supports_streaming": supports_streaming,
                "parse_mode": parse_mode,
            },
        )
        if self.forward_to_telegram:
            orig = getattr(self.bot, "_original_telegram_methods", {}).get("send_video")
            if orig:
                try:
                    await orig(chat_id, video_path, caption=caption, duration=duration, width=width, height=height, supports_streaming=supports_streaming, parse_mode=parse_mode, **kwargs)
                except Exception as exc:
                    logger.debug("[Harness] Forward send_video failed: %s", exc)
        return True

    async def handle_send_video_file(self, chat_id: Any, video_path: str, caption=None, duration=0, width=0, height=0, title=None, supports_streaming=True, cleanup_after_send=False, **kwargs) -> bool:
        async with self._lock:
            self._next_message_id += 1
            msg_id = self._next_message_id

        self.output_video_path = str(video_path)
        self.final_caption = caption

        await self._record_event(
            action="send_video_file",
            chat_id=chat_id,
            message_id=msg_id,
            caption=caption,
            file_path=str(video_path),
            extra_params={
                "duration": duration,
                "width": width,
                "height": height,
                "title": title,
                "supports_streaming": supports_streaming,
                "cleanup_after_send": cleanup_after_send,
            },
        )
        if self.forward_to_telegram:
            orig = getattr(self.bot, "_original_telegram_methods", {}).get("send_video_file")
            if orig:
                try:
                    return await orig(chat_id, video_path, caption=caption, duration=duration, width=width, height=height, title=title, supports_streaming=supports_streaming, cleanup_after_send=cleanup_after_send, **kwargs)
                except Exception as exc:
                    logger.debug("[Harness] Forward send_video_file failed: %s", exc)
        return True

    async def handle_send_chat_action(self, chat_id: Any, action="typing", **kwargs) -> None:
        await self._record_event(
            action="send_chat_action",
            chat_id=chat_id,
            extra_params={"action": action},
        )
        return None

    def get_transcript(self) -> List[Dict[str, Any]]:
        return list(self.events)


# =============================================================================
# 4. Injection Endpoint (Feature F12 - Approach "A")
# =============================================================================

@router.post(
    "/inject",
    response_model=SyntheticTelegramInjectionResponse,
    dependencies=[Depends(verify_test_harness_guard)],
    summary="Tiêm cập nhật Telegram giả lập vào Production Handler của Bot",
)
async def inject_synthetic_telegram_update(
    request: Request,
    req_body: SyntheticTelegramUpdateRequest,
) -> SyntheticTelegramInjectionResponse:
    start_time = time.time()
    bot = getattr(request.app.state, "telegram_bot", None)

    if bot is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram Bot instance is not initialized on this server",
        )

    # 1. Xác định Chat ID & User ID
    chat_id = req_body.chat_id
    if not chat_id:
        chat_id_str = getattr(bot, "chat_id", None) or getattr(settings, "TELEGRAM_CHAT_ID", None)
        try:
            chat_id = int(chat_id_str) if chat_id_str else 999999999
        except (ValueError, TypeError):
            chat_id = 999999999

    user_id = req_body.user_id or chat_id
    caption = req_body.caption or "xóa sạch text trong video giúp tôi"
    options = req_body.options or {}
    timeout_sec = float(options.get("timeout_sec", 600.0))
    forward_to_telegram = bool(options.get("forward_to_telegram", False))

    # 2. Xác thực tệp video đầu vào
    resolved_video_path = req_body.video_path
    if resolved_video_path and not os.path.exists(resolved_video_path):
        duration_sec = time.time() - start_time
        return SyntheticTelegramInjectionResponse(
            success=False,
            error=f"Video path not found on server: {resolved_video_path}",
            duration_sec=duration_sec,
            transcript=[],
            output_video_path=None,
        )

    # Tạo thư mục tạm cho phiên xử lý
    session_temp_dir = tempfile.mkdtemp(prefix="harness_session_")
    session_video_path = resolved_video_path or os.path.join(session_temp_dir, "input_video.mp4")

    # Metadata mặc định nếu không có ffprobe
    file_size = os.path.getsize(session_video_path) if os.path.exists(session_video_path) else 1024 * 1024 * 10
    metadata = VideoMetadata(
        filename=Path(session_video_path).name,
        duration=65,
        width=576,
        height=1024,
        file_size=file_size,
    )

    session = PendingVideoSession(
        chat_id=str(chat_id),
        file_id=f"harness_vid_{int(time.time())}",
        temp_dir=session_temp_dir,
        video_path=session_video_path,
        metadata=metadata,
        instruction=caption,
    )

    capture = TestHarnessTranscriptCapture(
        bot=bot,
        local_video_path=resolved_video_path,
        forward_to_telegram=forward_to_telegram,
    )

    try:
        async with capture:
            # Chạy handler sản xuất với timeout bảo vệ
            await asyncio.wait_for(
                bot._on_video_process_pipeline(
                    chat_id=str(chat_id),
                    session=session,
                    instruction=caption,
                ),
                timeout=timeout_sec,
            )

        duration_sec = time.time() - start_time
        transcript = capture.get_transcript()
        output_path = capture.output_video_path
        final_caption = capture.final_caption

        # Kiểm tra xem có video thành phẩm được gửi không
        has_sent_video = any(ev["action"] in ("send_video", "send_video_file") for ev in transcript)

        return SyntheticTelegramInjectionResponse(
            success=has_sent_video,
            error=None if has_sent_video else "Pipeline completed but no output video was sent",
            duration_sec=duration_sec,
            transcript=transcript,
            output_video_path=output_path,
            caption=final_caption,
        )

    except asyncio.TimeoutError:
        duration_sec = time.time() - start_time
        return SyntheticTelegramInjectionResponse(
            success=False,
            error=f"Pipeline execution timed out after {timeout_sec:.1f}s",
            duration_sec=duration_sec,
            transcript=capture.get_transcript(),
            output_video_path=None,
        )
    except Exception as exc:
        duration_sec = time.time() - start_time
        logger.error("[TelegramTestHarness] Injection execution failed: %s", exc, exc_info=True)
        return SyntheticTelegramInjectionResponse(
            success=False,
            error=f"Pipeline exception: {str(exc)}",
            duration_sec=duration_sec,
            transcript=capture.get_transcript(),
            output_video_path=None,
        )
    finally:
        # Dọn dẹp session temp dir nếu không giữ lại video
        if os.path.exists(session_temp_dir):
            try:
                shutil.rmtree(session_temp_dir, ignore_errors=True)
            except Exception:
                pass
