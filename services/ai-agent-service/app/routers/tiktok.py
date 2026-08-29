from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.tiktok_service import TikTokService
from app.services.vnc_manager import vnc_manager

router = APIRouter(prefix="/api/tiktok", tags=["TikTok"])


class StreakTargetInput(BaseModel):
    username: str
    nickname: Optional[str] = ""
    streak_days: Optional[int] = 0
    status: Optional[str] = "active"


class TikTokConfigInput(BaseModel):
    enabled: bool = False
    streakEnabled: bool = True
    streakScheduleHour: int = Field(default=9, ge=0, le=23)
    streakTargets: List[Dict[str, Any]] = []
    streakMessageTemplate: str = "Video giữ chuỗi hôm nay nè! Chúc bạn ngày mới vui vẻ nha 🔥✨"
    streakSendType: str = "video"
    threshold: int = Field(default=3, ge=1)
    scanIntervalMinutes: int = Field(default=3, ge=1)
    idleTimeoutMinutes: int = Field(default=1, ge=1, le=60)
    humanSessionMinutes: int = Field(default=5, ge=1, le=120)
    cooldownMinutes: int = Field(default=60, ge=1)
    customMessage: str = ""
    cookiesJson: str = ""


class CookieInput(BaseModel):
    cookiesJson: str


class ChatTestInput(BaseModel):
    sender_name: str = "Bạn Thân TikTok"
    message: str = "Alo Mạnh ơi, có video mới chưa gửi xem với!"


class InstantStreakInput(BaseModel):
    username: str


def get_tiktok_service(request: Request) -> TikTokService:
    return request.app.state.tiktok_service


@router.get("/config")
async def get_config(tt: TikTokService = Depends(get_tiktok_service)):
    cfg = await tt.get_config_from_db()
    replies = await tt.get_recent_replies(limit=15)
    return {
        "id": cfg.get("id", 1),
        "enabled": cfg.get("enabled", False),
        "streakEnabled": cfg.get("streak_enabled", True),
        "streak_enabled": cfg.get("streak_enabled", True),
        "streakScheduleHour": cfg.get("streak_schedule_hour", 9),
        "streak_schedule_hour": cfg.get("streak_schedule_hour", 9),
        "streakTargets": cfg.get("streak_targets", []),
        "streak_targets": cfg.get("streak_targets", []),
        "streakMessageTemplate": cfg.get("streak_message_template", ""),
        "streak_message_template": cfg.get("streak_message_template", ""),
        "streakSendType": cfg.get("streak_send_type", "video"),
        "streak_send_type": cfg.get("streak_send_type", "video"),
        "threshold": cfg.get("threshold", 3),
        "scanIntervalMinutes": cfg.get("scan_interval_minutes", 3),
        "scan_interval_minutes": cfg.get("scan_interval_minutes", 3),
        "idleTimeoutMinutes": cfg.get("idle_timeout_minutes", 1),
        "idle_timeout_minutes": cfg.get("idle_timeout_minutes", 1),
        "humanSessionMinutes": cfg.get("human_session_minutes", 5),
        "human_session_minutes": cfg.get("human_session_minutes", 5),
        "cooldownMinutes": cfg.get("cooldown_minutes", 60),
        "cooldown_minutes": cfg.get("cooldown_minutes", 60),
        "cookiesJson": cfg.get("cookies_json", ""),
        "cookies_json": cfg.get("cookies_json", ""),
        "customMessage": cfg.get("custom_message", ""),
        "custom_message": cfg.get("custom_message", ""),
        "lastStatus": cfg.get("last_status", "Tắt"),
        "last_status": cfg.get("last_status", "Tắt"),
        "lastCheckAt": cfg.get("last_check_at"),
        "lastStreakRunAt": cfg.get("last_streak_run_at"),
        "recentReplies": replies,
    }


@router.post("/config")
async def update_config(
    input_data: TikTokConfigInput, tt: TikTokService = Depends(get_tiktok_service)
):
    cfg = await tt.get_config_from_db()
    cfg["enabled"] = input_data.enabled
    cfg["streak_enabled"] = input_data.streakEnabled
    cfg["streak_schedule_hour"] = input_data.streakScheduleHour
    cfg["streak_targets"] = input_data.streakTargets
    cfg["streak_message_template"] = input_data.streakMessageTemplate
    cfg["streak_send_type"] = input_data.streakSendType
    cfg["threshold"] = max(1, input_data.threshold)
    cfg["scan_interval_minutes"] = max(1, input_data.scanIntervalMinutes)
    cfg["idle_timeout_minutes"] = max(1, input_data.idleTimeoutMinutes)
    cfg["human_session_minutes"] = max(1, input_data.humanSessionMinutes)
    cfg["cooldown_minutes"] = max(1, input_data.cooldownMinutes)
    if input_data.customMessage is not None:
        cfg["custom_message"] = input_data.customMessage
    if input_data.cookiesJson:
        cfg["cookies_json"] = input_data.cookiesJson

    await tt.save_config_to_db(cfg)
    return {"status": "success", "message": "Đã lưu cấu hình TikTok Agent thành công!", "config": cfg}


@router.post("/cookies")
async def update_cookies(
    input_data: CookieInput, tt: TikTokService = Depends(get_tiktok_service)
):
    cfg = await tt.get_config_from_db()
    cfg["cookies_json"] = input_data.cookiesJson
    await tt.save_config_to_db(cfg)
    return {"status": "success", "message": "Đã cập nhật Cookies TikTok thành công!"}


@router.post("/trigger-scan")
async def trigger_manual_scan(tt: TikTokService = Depends(get_tiktok_service)):
    res = await tt.run_scan_cycle()
    return res


@router.post("/trigger-streak")
async def trigger_manual_streak(
    input_data: Optional[InstantStreakInput] = None,
    tt: TikTokService = Depends(get_tiktok_service)
):
    if input_data and input_data.username:
        res = await tt.trigger_instant_streak(input_data.username)
        return res
    res = await tt.run_streak_keeper_cycle(force=True)
    return res


@router.get("/scan-status")
async def get_scan_status(tt: TikTokService = Depends(get_tiktok_service)):
    replies = await tt.get_recent_replies(limit=15)
    return {
        "status": tt._last_scan_status,
        "is_scanning": tt._is_scanning,
        "last_scan_at": tt._last_scan_at,
        "recentReplies": replies,
    }


@router.post("/test-ai-chat")
async def test_ai_chat(
    input_data: ChatTestInput, tt: TikTokService = Depends(get_tiktok_service)
):
    reply = await tt.generate_ai_reply(input_data.sender_name, input_data.message)
    return {
        "sender_name": input_data.sender_name,
        "message": input_data.message,
        "reply": reply,
    }


@router.post("/clear-logs")
async def clear_logs(tt: TikTokService = Depends(get_tiktok_service)):
    await tt.clear_recent_replies()
    return {"status": "success", "message": "Đã dọn sạch nhật ký hoạt động TikTok."}


# ─── Live VNC Server Browser Endpoints for TikTok ────────────────────────────

@router.post("/launch-browser")
async def launch_browser():
    """Starts the headful Chromium VNC session on display :99 pointing to TikTok Messages."""
    result = await vnc_manager.start_session(
        target_url="https://www.tiktok.com/messages",
        platform="tiktok"
    )
    return result


@router.get("/vnc-ready")
async def vnc_ready():
    """Returns whether the VNC websockify gateway and browser are listening and ready."""
    is_ready = await vnc_manager.check_ready()
    return {"ready": is_ready}


@router.post("/save-browser-session")
async def save_browser_session():
    """Extracts session cookies from the live VNC browser and saves to tiktok_config."""
    result = await vnc_manager.save_session(platform="tiktok")
    return result


@router.post("/close-browser-session")
async def close_browser_session():
    """Safely terminates the VNC browser session."""
    await vnc_manager.close_session()
    return {"status": "success", "message": "Đã đóng trình duyệt Server."}


@router.post("/vnc-heartbeat")
async def vnc_heartbeat():
    """Keeps the VNC session alive while the user is actively viewing the modal."""
    vnc_manager.touch()
    return {"status": "ok"}
