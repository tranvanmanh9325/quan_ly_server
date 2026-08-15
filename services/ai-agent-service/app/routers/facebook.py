from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import settings
from app.services.facebook_service import FacebookService
from app.services.ai_agent import AiAgentService

router = APIRouter(prefix="/api/facebook", tags=["Facebook"])


class FacebookConfigInput(BaseModel):
    enabled: bool = False
    threshold: int = Field(default=5, ge=1)
    scanIntervalMinutes: int = Field(default=5, ge=1)
    idleTimeoutMinutes: int = Field(default=3, ge=1, le=60)
    humanSessionMinutes: int = Field(default=10, ge=1, le=120)
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
    cookies = cfg.get("cookies_json", "")
    enabled = bool(cfg.get("enabled", False))
    threshold = int(cfg.get("threshold", 5))
    scan_interval = int(cfg.get("scan_interval_minutes", 5))
    idle_timeout = int(cfg.get("idle_timeout_minutes", 3))
    human_session = int(cfg.get("human_session_minutes", 10))
    custom_msg = cfg.get("custom_message", "")
    last_status = cfg.get("last_status", "Tắt")
    return {
        "id": cfg.get("id", 1),
        "enabled": enabled,
        "threshold": threshold,
        "scanIntervalMinutes": scan_interval,
        "scan_interval_minutes": scan_interval,
        "idleTimeoutMinutes": idle_timeout,
        "idle_timeout_minutes": idle_timeout,
        "humanSessionMinutes": human_session,
        "human_session_minutes": human_session,
        "cookiesJson": cookies,
        "cookies_json": cookies,
        "customMessage": custom_msg,
        "custom_message": custom_msg,
        "lastStatus": last_status,
        "last_status": last_status,
    }


@router.post("/config")
async def update_config(
    input_data: FacebookConfigInput, fb: FacebookService = Depends(get_fb_service)
):
    cfg = await fb.get_config_from_db()
    cfg["enabled"] = input_data.enabled
    cfg["threshold"] = max(1, input_data.threshold)
    cfg["scan_interval_minutes"] = max(1, input_data.scanIntervalMinutes)
    cfg["idle_timeout_minutes"] = max(1, input_data.idleTimeoutMinutes)
    cfg["human_session_minutes"] = max(1, input_data.humanSessionMinutes)
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


from app.services.vnc_manager import vnc_manager

# ─── Live VNC Server Browser Endpoints ────────────────────────────────────────

@router.post("/launch-browser")
async def launch_browser():
    """Starts the headful Chromium VNC session on display :99 & websockify:6080."""
    result = await vnc_manager.start_session()
    return result


@router.get("/vnc-ready")
async def vnc_ready():
    """Returns whether the VNC websockify gateway and browser are listening and ready."""
    is_ready = await vnc_manager.check_ready()
    return {"ready": is_ready}


@router.post("/save-browser-session")
async def save_browser_session(fb: FacebookService = Depends(get_fb_service)):
    """Extracts session cookies from the live VNC browser and saves to DB."""
    result = await vnc_manager.save_session()
    if result.get("status") == "success":
        # Reload configuration in facebook_service
        try:
            await fb.load_configuration()
        except Exception:
            pass
    return result


@router.post("/close-browser-session")
async def close_browser_session():
    """Safely terminates the VNC browser session."""
    await vnc_manager.close_session()
    return {"status": "success", "message": "Đã đóng trình duyệt Server."}


@router.post("/vnc-heartbeat")
async def vnc_heartbeat():
    """Resets idle watchdog timer while the user is actively viewing/using the VNC modal."""
    vnc_manager.touch()
    return {"status": "ok"}