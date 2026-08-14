from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import settings
from app.services.facebook_service import FacebookService
from app.services.ai_agent import AiAgentService

router = APIRouter(prefix="/api/facebook", tags=["Facebook"])


class FacebookConfigInput(BaseModel):
    enabled: bool = False
    threshold: int = Field(default=3, ge=1)
    scanIntervalMinutes: int = Field(default=5, ge=1)
    customMessage: str = ""
    cookiesJson: str = ""


class CookieInput(BaseModel):
    cookiesJson: str


class ChatTestInput(BaseModel):
    message: str = "Trần Văn Mạnh nhắn tôi gì?"
    chat_id: Optional[str] = None


def get_fb_service(request: Request) -> FacebookService:
    return request.app.state.fb_service


def get_ai_agent(request: Request) -> AiAgentService:
    return request.app.state.ai_agent


@router.get("/config")
async def get_config(fb: FacebookService = Depends(get_fb_service)):
    cfg = await fb.get_config_from_db()
    return cfg


@router.post("/config")
async def update_config(
    input_data: FacebookConfigInput, fb: FacebookService = Depends(get_fb_service)
):
    cfg = await fb.get_config_from_db()
    cfg["enabled"] = input_data.enabled
    cfg["threshold"] = max(1, input_data.threshold)
    cfg["scan_interval_minutes"] = max(1, input_data.scanIntervalMinutes)
    if input_data.customMessage:
        cfg["custom_message"] = input_data.customMessage
    if input_data.cookiesJson:
        cfg["cookies_json"] = input_data.cookiesJson

    await fb.save_config_to_db(cfg)
    return cfg


@router.post("/cookies")
async def update_cookies(
    input_data: CookieInput, fb: FacebookService = Depends(get_fb_service)
):
    cfg = await fb.get_config_from_db()
    cfg["cookies_json"] = input_data.cookiesJson
    await fb.save_config_to_db(cfg)
    return {"message": "Đã cập nhật Cookies Facebook thành công!"}


@router.post("/trigger")
async def trigger_manual_scan(fb: FacebookService = Depends(get_fb_service)):
    if fb._is_scanning:
        return {"status": "running", "message": "Quét tin nhắn đang được thực hiện."}
    import asyncio
    asyncio.create_task(fb.run_scan_cycle())
    return {"status": "started", "message": "Đã kích hoạt quét tin nhắn Facebook trong nền."}


@router.get("/scan-status")
async def get_scan_status(fb: FacebookService = Depends(get_fb_service)):
    return {
        "status": fb._last_scan_status,
        "is_scanning": fb._is_scanning,
    }


@router.post("/test-ai-chat")
async def test_ai_chat(
    input_data: ChatTestInput, ai: AiAgentService = Depends(get_ai_agent)
):
    import uuid
    session_id = input_data.chat_id or f"test-{uuid.uuid4().hex[:8]}"
    reply = await ai.chat(session_id, input_data.message)
    return {
        "chat_id": session_id,
        "message": input_data.message,
        "reply": reply,
    }


# ─── Legacy VNC session endpoints (replaced by direct cookie paste) ───────────
# The old Java metrics-service ran Playwright+noVNC inside the container.
# The new Python ai-agent-service uses Playwright headless directly.
# These stubs preserve frontend compatibility while clearly communicating the change.

@router.post("/launch-browser")
async def launch_browser():
    """
    VNC interactive browser login was removed when migrating to Python.
    Cookies are now managed by pasting the JSON directly in the Settings page.
    """
    return {
        "status": "not_supported",
        "message": (
            "Tính năng trình duyệt tương tác VNC đã được loại bỏ trong phiên bản Python. "
            "Vui lòng đăng nhập Facebook trên máy tính, xuất Cookies bằng extension "
            "'Cookie-Editor', rồi dán JSON vào ô 'Facebook Cookies' trong phần Cài đặt."
        ),
    }


@router.get("/vnc-ready")
async def vnc_ready():
    """VNC is no longer used; always returns false so frontend polling stops gracefully."""
    return {"ready": False}


@router.post("/save-browser-session")
async def save_browser_session():
    """VNC session saving is no longer applicable in the Python agent."""
    return {
        "status": "not_supported",
        "message": (
            "Tính năng lưu phiên trình duyệt VNC đã được loại bỏ. "
            "Hãy dán JSON Cookies trực tiếp vào trường 'Facebook Cookies' trong Cài đặt."
        ),
    }
