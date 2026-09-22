"""
Agent Tool Registry & Execution Subsystem (Gorilla RAT Scoped Tools)
Tách rời toàn bộ định nghĩa Schema công cụ và Logic Dispatcher thực thi.
"""
import asyncio
from datetime import datetime, timezone, timedelta
import html
import json
import logging
import os
from pathlib import Path
import re
import shlex
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Set, Tuple

from app.config import settings
from app.core.ssh_client import SshClient
from app.services.message_cache import FacebookMessageCache
from app.services.video_chunker import VideoChunker
from app.services.media_storage_manager import media_storage_manager

logger = logging.getLogger(__name__)
VN_TZ = timezone(timedelta(hours=7))

DIRECT_RETURN_TOOLS = frozenset({
    "facebook_send_reply",
    "facebook_capture_screenshot",
    "facebook_view_profile",
    "server_capture_screenshot",
    "browser_take_screenshot",
    "download_media_video",
    "download_media_audio",
})

SCREENSHOT_TOOLS = frozenset({
    "browser_navigate",
    "browser_search_google",
    "browser_click",
    "browser_type",
    "browser_scroll",
    "browser_go_back",
    "browser_go_forward",
    "browser_press_key",
    "browser_hover",
    "browser_select_option",
    "browser_execute_js",
    "browser_fill_form",
})

_SPINAL_VETO_PATTERNS = (
    # 1. Lethal deletions & bulk file wiping
    re.compile(r"\brm\s+.*(?:-[a-zA-Z0-9_-]*[rR]|--recursive\b).*(?:-[a-zA-Z0-9_-]*[fF]|--force\b).*([/~]|\*|\.)", re.IGNORECASE),
    re.compile(r"\brm\s+.*(?:-[a-zA-Z0-9_-]*[fF]|--force\b).*(?:-[a-zA-Z0-9_-]*[rR]|--recursive\b).*([/~]|\*|\.)", re.IGNORECASE),
    re.compile(r"\brm\s+-[rfRF]{1,4}\s+([/~]|\*|\.)", re.IGNORECASE),
    re.compile(r"\brm\s+.*--recursive\s+([/~]|\*|\.)", re.IGNORECASE),
    re.compile(r"\brm\s+.*--no-preserve-root\b", re.IGNORECASE),
    re.compile(r"\bfind\s+.*-(?:delete|exec\s+(?:rm|unlink|shred)\b)", re.IGNORECASE),
    re.compile(r"\btruncate\b[^\n;&|]*(?:-s\s*0\b|--size\s*0\b|\b\S*log\b|\.log\b)", re.IGNORECASE),
    # 2. SSH keys, authentication & daemon disruption
    re.compile(r"\b(?:rm|unlink|shred)\s+.*(?:\.ssh\b|authorized_keys\b|sshd?_config\b)", re.IGNORECASE),
    re.compile(r">\s*.*(?:\.ssh/authorized_keys\b|sshd?_config\b)", re.IGNORECASE),
    re.compile(r"\bsystemctl\s+(?:stop|disable|mask)\s+sshd?\b", re.IGNORECASE),
    # 3. Disk & filesystem raw destruction
    re.compile(r"\bmkfs(\.\w+)?\b", re.IGNORECASE),
    re.compile(r"\bdd\s+if=.*of=/dev/(sd|nvme|vd)", re.IGNORECASE),
    re.compile(r">\s*/dev/(sd|nvme|vd)", re.IGNORECASE),
    # 4. Database destruction (DROP & TRUNCATE)
    re.compile(r"\bdrop\s+(?:database|schema|table)\b", re.IGNORECASE),
    re.compile(r"\btruncate\s+(?:table\s+(?:only\s+)?|only\s+|[a-zA-Z0-9_\"']+\s*(?:;|,|\bcascade\b|$))", re.IGNORECASE),
    # 5. Container mass purge & destruction
    re.compile(r"\bdocker\s+(?:system\s+)?prune\s+.*(?:-[a-zA-Z0-9_-]*a|--all\b)", re.IGNORECASE),
    re.compile(r"\bdocker\s+rm\s+.*-[a-zA-Z0-9_-]*f.*(?:\$\(|`)\s*docker\s+(?:container\s+)?(?:ps|ls)\b", re.IGNORECASE),
    re.compile(r"\bdocker\s+kill\s+.*(?:\$\(|`)\s*docker\s+(?:container\s+)?(?:ps|ls)\b", re.IGNORECASE),
    # 6. Network & firewall blackout
    re.compile(r"\biptables\s+.*(?:-[fFX]|--flush)\b", re.IGNORECASE),
    re.compile(r"\bufw\s+.*(?:reset|disable)\b", re.IGNORECASE),
    re.compile(r"\bip\s+(?:-[a-zA-Z0-9_-]+\s+)*link\s+set\s+.*down\b", re.IGNORECASE),
    # 7. Reckless permissions & ownership changes
    re.compile(r"\bchmod\s+.*(?:-[a-zA-Z0-9_-]*[rR]|--recursive\b).*(?:777|0777|a\+rwx)\b", re.IGNORECASE),
    re.compile(r"\bchmod\s+.*(?:777|0777|a\+rwx).*(?:-[a-zA-Z0-9_-]*[rR]|--recursive\b)", re.IGNORECASE),
    re.compile(r"\bchown\s+.*(?:-[a-zA-Z0-9_-]*[rR]|--recursive\b)", re.IGNORECASE),
    # 8. Stress exhaustion & fork bombs
    re.compile(r"(?:^|[;&|`$()]\s*|\b(?:sudo|nohup|exec|env)\b[^\n;&|]*)\bstress(?:-ng)?\b", re.IGNORECASE),
    re.compile(r":\(\)\{\s*:\|:&\s*\};:", re.IGNORECASE),
)

def evaluate_spinal_safety_veto(command: str, confirm_token: Optional[str] = None) -> Optional[str]:
    """
    Biological Spinal Reflex Circuit Breaker: Intercepts lethal system commands at code level.
    Triggers neurochemical alarm and halts execution unless explicit confirmation token is given.
    """
    if confirm_token == "CONFIRM_DANGEROUS_ACTION":
        return None
    for pattern in _SPINAL_VETO_PATTERNS:
        if pattern.search(command):
            try:
                from app.core.brain_core import ArtificialBrain
                brain = ArtificialBrain.get_instance()
                brain.neuro.stimulate("noradrenaline", 0.35)
                brain.neuro.stimulate("cortisol", 0.30)
                brain.neuro.stimulate("dopamine", -0.20)
            except Exception:
                pass
            return (
                f"🛑 [PHẢN XẠ TỦY SỐNG BẢO VỆ SERVER - SPINAL SAFETY VETO]: Lệnh `{command}` "
                f"đã bị chặn ngay lập tức ở tầng vi mạch an toàn! Thao tác này có nguy cơ phá hủy hệ thống hoặc tê liệt máy chủ. "
                f"Em nhất quyết không tự ý thực thi nếu không có xác nhận bảo mật tường minh từ anh Mạnh kèm mã `confirm=\"CONFIRM_DANGEROUS_ACTION\"`!"
            )
    return None


# ── Action Risk Tri-Tier (M4 Autonomous Action Gating) ──
ACTION_TIER_1_SAFE = "TIER_1_SAFE"
ACTION_TIER_2_REVERSIBLE = "TIER_2_REVERSIBLE"
ACTION_TIER_3_LETHAL = "TIER_3_LETHAL"

_SAFE_DIAGNOSTIC_COMMAND_PATTERN = re.compile(
    r"^(?:sudo\s+)?(?:free|df|uptime|top|htop|ps|docker\s+(?:ps|stats|logs|images|version|info)|"
    r"netstat|ss|ip\s+(?:addr|a|route|link)|ifconfig|journalctl|cat|ls|head|tail|grep|zgrep|"
    r"awk|cut|sort|uniq|wc|tr|column|"
    r"systemctl\s+status|service\s+\S+\s+status|uname|whoami|w|last|date|vmstat|iostat|sensors|dmesg|"
    r"which|whereis|file|du(?!\s+.*-(?:delete))|cat\s+/proc/|cat\s+/etc/|crontab\s+-l)\b",
    re.IGNORECASE
)

_REVERSIBLE_OPERATIONAL_PATTERN = re.compile(
    r"^(?:sudo\s+)?(?:docker\s+(?:restart|start|stop)\s+[a-zA-Z0-9_-]+$|"
    r"systemctl\s+(?:restart|reload)\s+[a-zA-Z0-9_-]+$|"
    r"touch\s+|mkdir\s+|cp\s+|mv\s+.*_bak\b)",
    re.IGNORECASE
)

_REDIRECTION_WRITE_PATTERN = re.compile(r"(?:>>?|\|\s*(?:sudo\s+)?tee\b)")


def classify_command_risk(command: str) -> str:
    """
    Phân loại rủi ro của lệnh bash theo Action Risk Tri-Tier:
    - ACTION_TIER_3_LETHAL: Khớp Spinal Safety Veto (hủy diệt, không đảo ngược).
    - ACTION_TIER_1_SAFE: Lệnh chẩn đoán, đọc dữ liệu, an toàn tuyệt đối (100% các nhánh đều đọc an toàn).
    - ACTION_TIER_2_REVERSIBLE: Thao tác có thể khôi phục (restart container, tạo file tạm, backup) hoặc chứa lệnh ghi đĩa/nhánh không thuần đọc.
    """
    cmd = command.strip()
    # 1. Kiểm tra Spinal Safety Veto (Tier 3) trên toàn bộ chuỗi trước
    for pattern in _SPINAL_VETO_PATTERNS:
        if pattern.search(cmd):
            return ACTION_TIER_3_LETHAL

    # 2. Kiểm tra toán tử ghi đĩa (>, >>, | tee) -> Không thể là Tier 1 Safe, nâng lên Tier 2
    if _REDIRECTION_WRITE_PATTERN.search(cmd):
        return ACTION_TIER_2_REVERSIBLE

    # 3. Phân tách chuỗi lệnh gộp (||, &&, |, ;) lên TRƯỚC
    parts = [p.strip() for p in re.split(r"(?:\|\||&&|[|;])", cmd) if p.strip()]

    # 4. Chỉ cấp Tier 1 khi có ít nhất 1 lệnh và 100% các nhánh đều là chẩn đoán đọc an toàn
    if parts and all(_SAFE_DIAGNOSTIC_COMMAND_PATTERN.search(p) for p in parts):
        return ACTION_TIER_1_SAFE

    return ACTION_TIER_2_REVERSIBLE


def classify_action_risk(tool_name: str, tool_args: Optional[Dict[str, Any]] = None) -> str:
    """
    Phân loại rủi ro của một Tool Call theo Action Risk Tri-Tier:
    - Tier 1: Safe Read-Only / Diagnostic / Utility
    - Tier 2: Reversible Changes / Low-Risk Operational
    - Tier 3: Lethal / Destructive
    """
    if tool_name == "run_command":
        cmd = (tool_args or {}).get("command", "")
        return classify_command_risk(cmd)

    tier1_tools = {
        "get_weather",
        "get_server_location",
        "get_server_active_sessions",
        "server_capture_screenshot",
        "download_media_video",
        "download_media_audio",
        "read_archive_file",
        "browser_search_google",
        "browser_navigate",
        "browser_take_screenshot",
        "browser_get_text",
        "facebook_get_messages",
        "facebook_capture_screenshot",
        "facebook_view_profile",
        "get_appointments",
        "messenger_list_groups",
        "messenger_get_group_members",
        "remember_for_later",
        "complete_task",
    }
    if tool_name in tier1_tools:
        return ACTION_TIER_1_SAFE

    tier2_tools = {
        "extract_archive_file",
        "recover_archive_password",
        "facebook_send_reply",
        "browser_click",
        "browser_type",
        "browser_scroll",
        "browser_press_key",
        "browser_hover",
        "browser_select_option",
        "browser_fill_form",
        "browser_wait_for",
        "browser_execute_js",
    }
    if tool_name in tier2_tools:
        return ACTION_TIER_2_REVERSIBLE

    return ACTION_TIER_1_SAFE


def infer_default_diagnostic_command(query: str) -> Optional[str]:
    """
    Tự suy luận tham số lệnh an toàn mặc định (Default Parameter Heuristics)
    khi người dùng đưa ra yêu cầu chẩn đoán chung chung hoặc câu hỏi tự nhiên / phương ngữ không có động từ.
    """
    q = query.lower()

    # 1. RAM / Bộ nhớ / Swap
    if any(k in q for k in ("ram", "bộ nhớ", "swap")):
        if any(v in q for v in (
            "kiểm tra", "xem", "check", "tình trạng", "thế nào", "bao nhiêu", "răng", "sao",
            "ổn không", "hết chưa", "hết", "trống", "đang dùng", "dùng bao nhiêu", "còn bao nhiêu",
            "chừ", "hè", "máy em", "làm sao", "làm cách nào", "biết", "hiện tại", "sức khỏe"
        )):
            return "free -h"

    # 2. Uptime / Thời gian bật / hoạt động của máy chủ
    if any(k in q for k in (
        "uptime", "bật bao lâu", "mở bao lâu", "chạy bao lâu", "hoạt động bao lâu",
        "chạy từ khi nào", "bật từ khi nào", "máy đã bật", "máy bật", "server bật"
    )):
        return "uptime"

    # 3. Ổ đĩa / Dung lượng lưu trữ
    if any(k in q for k in ("ổ đĩa", "disk", "dung lượng", "ổ cứng", "ổ ssd")):
        if any(v in q for v in (
            "kiểm tra", "xem", "check", "tình trạng", "còn trống", "trống", "đầy chưa",
            "đầy không", "hết dung lượng", "bao nhiêu", "thế nào", "sao", "làm sao", "làm cách nào"
        )):
            return "df -h /"

    # 4. Docker / Container
    if any(k in q for k in ("docker", "container")):
        if any(v in q for v in (
            "kiểm tra", "xem", "check", "tình trạng", "danh sách", "đang chạy", "chạy không",
            "làm sao", "làm cách nào", "thế nào", "có chạy"
        )):
            return "docker ps --format \"table {{.Names}}\t{{.Status}}\t{{.Ports}}\""

    # 5. CPU / Tải hệ thống
    if any(k in q for k in ("cpu", "load", "tải cpu", "tải hệ thống", "tải máy", "tải cao")):
        if any(v in q for v in (
            "kiểm tra", "xem", "check", "tải", "thế nào", "bao nhiêu", "cao không",
            "sao", "ổn không", "tình trạng", "làm sao", "làm cách nào"
        )):
            return "top -b -n 1 | head -n 15"

    return None



class AgentToolExecutor:
    """
    Quản lý Tool Schemas, Dynamic Tool Scoping (Gorilla RAT / BFCL)
    và Dispatcher thực thi các công cụ hệ thống, Facebook, Browser, Memory.
    """

    DIRECT_RETURN_TOOLS = DIRECT_RETURN_TOOLS
    _DIRECT_RETURN_TOOLS = DIRECT_RETURN_TOOLS
    SCREENSHOT_TOOLS = SCREENSHOT_TOOLS
    _SCREENSHOT_TOOLS = SCREENSHOT_TOOLS

    def __init__(
        self,
        ssh_client: SshClient,
        message_cache: FacebookMessageCache,
        fb_service: Any = None,
        browser_agent: Any = None,
        appointment_service: Any = None,
        telegram_bot: Any = None,
        memory_service: Any = None,
    ):
        self.ssh_client = ssh_client
        self.message_cache = message_cache
        self.fb_service = fb_service
        self.browser_agent = browser_agent
        self.appointment_service = appointment_service
        self.telegram_bot = telegram_bot
        self.memory_service = memory_service

    def set_fb_service(self, fb_service: Any) -> None:
        self.fb_service = fb_service

    def set_telegram_bot(self, telegram_bot: Any) -> None:
        self.telegram_bot = telegram_bot

    def set_browser_agent(self, browser_agent: Any) -> None:
        self.browser_agent = browser_agent

    def set_appointment_service(self, appointment_service: Any) -> None:
        self.appointment_service = appointment_service

    def set_memory_service(self, memory_service: Any) -> None:
        """Inject the AgentMemoryService for self-improving capabilities."""
        self.memory_service = memory_service

    # Expose Action Risk Tri-Tier on class
    ACTION_TIER_1_SAFE = ACTION_TIER_1_SAFE
    ACTION_TIER_2_REVERSIBLE = ACTION_TIER_2_REVERSIBLE
    ACTION_TIER_3_LETHAL = ACTION_TIER_3_LETHAL
    classify_action_risk = staticmethod(classify_action_risk)
    classify_command_risk = staticmethod(classify_command_risk)
    infer_default_diagnostic_command = staticmethod(infer_default_diagnostic_command)

    _TOOL_CLUSTER_SERVER = {
        "run_command",
        "get_server_active_sessions",
        "get_server_location",
        "server_capture_screenshot",
    }
    _TOOL_CLUSTER_WEATHER = {
        "get_weather",
        "get_server_location",
        "run_command",
    }
    _TOOL_CLUSTER_ARCHIVE = {
        "read_archive_file",
        "extract_archive_file",
        "recover_archive_password",
        "run_command",
    }
    _TOOL_CLUSTER_BROWSER_NAV = {
        "browser_navigate",
        "browser_search_google",
        "browser_take_screenshot",
        "browser_get_text",
    }
    _TOOL_CLUSTER_BROWSER_INTERACT = {
        "browser_click",
        "browser_type",
        "browser_scroll",
        "browser_press_key",
        "browser_take_screenshot",
        "browser_navigate",
        "browser_get_text",
    }
    _TOOL_CLUSTER_FACEBOOK = {
        "facebook_get_messages",
        "facebook_capture_screenshot",
        "facebook_send_reply",
        "get_appointments",
        "messenger_list_groups",
        "messenger_get_group_members",
        "facebook_view_profile",
    }
    _TOOL_CLUSTER_TASKS = {
        "remember_for_later",
        "complete_task",
    }
    _TOOL_CLUSTER_MEDIA = {
        "download_media_video",
        "download_media_audio",
        "run_command",
    }
    _TOOL_CLUSTER_CORE = {
        "run_command",
        "get_weather",
        "get_server_location",
        "download_media_video",
        "download_media_audio",
        "browser_search_google",
        "remember_for_later",
    }

    _SHORT_SERVER_RE = re.compile(r"\b(ip|top|df|free|port|load|log|ps|ram|cpu|ssh|swap)\b", re.IGNORECASE)
    _SHORT_TASK_RE = re.compile(r"\b(task|done|việc)\b", re.IGNORECASE)
    _SHORT_WEB_RE = re.compile(r"\b(web|url|link|form)\b", re.IGNORECASE)

    def _resolve_scoped_tool_names(
        self,
        query: str = "",
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> Set[str]:
        """
        Dynamically selects a relevant tool subset (4-8 tools) based on query semantics
        and multi-turn execution history, reducing schema overhead from ~4,200 tokens
        to <= 700 tokens to strictly comply with Groq's 8,000 TPM limit (preventing HTTP 413).
        """
        q = (query or "").lower()
        selected: Set[str] = set()

        # Detect active multi-turn browser automation session
        has_browser_history = False
        if history:
            for msg in reversed(history[-4:]):
                role = msg.get("role")
                if role in ("assistant", "tool"):
                    msg_str = str(msg)
                    if "browser_" in msg_str:
                        has_browser_history = True
                        break

        # Media download detection: strictly isolate from CPU load/system keywords
        has_media_link = any(link in q for link in (
            "tiktok.com", "youtu.be", "youtube.com", "fb.watch", "fb.me",
            "facebook.com/watch", "facebook.com/reel", "facebook.com/share", "facebook.com/videos",
            "douyin.com", "threads.net", "threads.com"
        ))
        is_media = has_media_link or any(k in q for k in (
            "tiktok", "youtube", "douyin", "reels", "reel", "video", "clip", "mp4",
            "shorts", "down video", "lưu clip", "tải video", "tải clip", "tải về",
            "download video", "download clip", "tai video", "tai clip", "tai ve",
            "lay video", "lay clip", "keo video",
            "tải mp3", "tai mp3", "tách nhạc", "tach nhac", "lấy audio", "lay audio",
            "nhạc tiktok", "nhac tiktok", "audio", "mp3", "bài hát", "bai hat", "nhạc", "nhac",
            "tải audio", "tai audio", "download audio", "download mp3"
        ))

        is_server = bool(self._SHORT_SERVER_RE.search(q)) or any(k in q for k in (
            "server", "máy chủ", "bộ nhớ", "ổ đĩa", "dung lượng",
            "docker", "container", "tiến trình", "process", "htop", "cortex",
            "trạng thái", "kiểm tra", "vị trí", "đăng nhập", "session", "reboot", "uptime", "sức khỏe",
            "bật bao lâu", "mở bao lâu", "chạy bao lâu", "hoạt động bao lâu", "máy đã bật", "máy em"
        ))

        is_archive = any(k in q for k in (
            "zip", "rar", "7z", "tar", "gz", "nén", "giải nén", "mật khẩu",
            "password", "pass", "crack", "bẻ khóa", "khôi phục", "archive", "extract"
        ))

        is_fb = any(k in q for k in (
            "facebook", "fb", "messenger", "tin nhắn", "inbox", "nhắn tin",
            "rep", "profile", "trang cá nhân", "nhóm", "group", "thành viên", "lịch hẹn"
        ))

        is_web = bool(self._SHORT_WEB_RE.search(q)) or any(k in q for k in (
            "website", "trang web", "google", "tìm kiếm", "search",
            "tra cứu", "click", "bấm", "nhấp", "gõ", "điền", "scroll", "cuộn"
        ))

        is_task = bool(self._SHORT_TASK_RE.search(q)) or any(k in q for k in (
            "nhớ", "ghi nhớ", "remind", "lưu lại", "xong", "hoàn thành"
        ))

        is_weather = any(k in q for k in (
            "thời tiết", "weather", "nhiệt độ", "độ ẩm", "mưa", "nắng",
            "dự báo", "bão", "không khí", "trời", "nóng", "lạnh", "gió",
            "áp thấp", "mưa rào", "giông", "rét", "ấm", "sương mù",
            "wttr", "a răng", "bựa ni"
        ))

        is_audio = any(k in q for k in (
            "tải mp3", "tai mp3", "tách nhạc", "tach nhac", "lấy audio", "lay audio",
            "nhạc tiktok", "nhac tiktok", "audio", "mp3", "bài hát", "bai hat", "nhạc", "nhac",
            "tải audio", "tai audio", "download audio", "download mp3"
        ))

        if is_media:
            if is_audio:
                selected.update(self._TOOL_CLUSTER_MEDIA)
            else:
                selected.add("download_media_video")
                selected.add("run_command")

        if is_weather:
            selected.update(self._TOOL_CLUSTER_WEATHER)

        if is_server:
            selected.update(self._TOOL_CLUSTER_SERVER)

        if is_archive:
            selected.update(self._TOOL_CLUSTER_ARCHIVE)

        if is_fb:
            selected.update(self._TOOL_CLUSTER_FACEBOOK)

        if is_web or has_browser_history:
            selected.update(self._TOOL_CLUSTER_BROWSER_NAV)
            if has_browser_history or any(k in q for k in ("click", "bấm", "nhấp", "gõ", "điền", "form", "scroll", "cuộn", "chờ")):
                selected.update(self._TOOL_CLUSTER_BROWSER_INTERACT)

        if is_task:
            selected.update(self._TOOL_CLUSTER_TASKS)

        if not selected:
            selected.update(self._TOOL_CLUSTER_CORE)

        # Priority Pruning: Enforce strict token budget (max 6 tools when archive/facebook present, else max 8)
        has_heavy_cluster = bool(
            is_archive or is_fb or (selected & (self._TOOL_CLUSTER_ARCHIVE | self._TOOL_CLUSTER_FACEBOOK))
        )
        max_tools = 6 if has_heavy_cluster else 8

        if len(selected) > max_tools:
            priority_order = [
                "run_command", "download_media_video",
                *(["download_media_audio"] if is_audio else []),
                "get_weather", "read_archive_file",
                "extract_archive_file", "get_server_location", "browser_navigate",
                "browser_search_google", "facebook_get_messages", "facebook_send_reply",
                "server_capture_screenshot", "get_server_active_sessions", "remember_for_later",
                "complete_task", "recover_archive_password", "facebook_capture_screenshot",
                *(["download_media_audio"] if not is_audio else []),
                "browser_click", "browser_type", "browser_scroll", "browser_press_key"
            ]
            pruned: Set[str] = set()
            for t in priority_order:
                if t in selected:
                    pruned.add(t)
                    if len(pruned) == max_tools:
                        break
            selected = pruned if len(pruned) >= 2 else set(list(selected)[:max_tools])

        return selected

    # ──────────────────────────────────────────────────────────────────────────
    # Tool Registry
    # ──────────────────────────────────────────────────────────────────────────

    def _build_tools(
        self,
        query: str = "",
        history: Optional[List[Dict[str, Any]]] = None,
        excluded_tools: Optional[set] = None,
    ) -> List[Dict[str, Any]]:
        excluded = set(excluded_tools or set())
        scoped_allowed: Optional[Set[str]] = None
        if query or history:
            scoped_allowed = self._resolve_scoped_tool_names(query=query, history=history)
        tools = [
            # ── Server Management ──
            {
                "type": "function",
                "function": {
                    "name": "get_server_active_sessions",
                    "description": "Tra cứu các phiên kết nối Web và SSH Terminal đang hoạt động trên máy chủ.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_server_location",
                    "description": "Tra cứu vị trí địa lý thực tế và ISP của máy chủ qua Wi-Fi WPS và IP Geolocation.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Tra cứu thời tiết thời gian thực. Bỏ trống location để tự động định vị máy chủ.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {
                                "type": "string",
                                "description": "Địa danh/tọa độ. Bỏ trống để tự định vị.",
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "run_command",
                    "description": "Thực thi lệnh shell an toàn trên server qua SSH (CPU, RAM, Disk, Docker, Logs).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "Lệnh bash (ví dụ: 'free -h', 'docker ps', 'df -h /').",
                            }
                        },
                        "required": ["command"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "download_media_video",
                    "description": "Tải video/audio (TikTok, YouTube, YouTube Shorts, Facebook, Facebook Reels, Threads) gửi Telegram.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "URL video cần tải (hỗ trợ TikTok, YouTube Shorts, Facebook Reels, Threads...).",
                            },
                            "caption": {
                                "type": "string",
                                "description": "Chú thích kèm video.",
                            },
                            "media_type": {
                                "type": "string",
                                "enum": ["video", "audio"],
                                "default": "video",
                                "description": "Loại: 'video' (mặc định) hoặc 'audio' (MP3).",
                            },
                        },
                        "required": ["url"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "download_media_audio",
                    "description": "Tải MP3/audio chất lượng cao (320kbps) từ TikTok, YouTube, Facebook gửi Telegram.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "URL video/audio cần tải hoặc tách nhạc.",
                            },
                            "caption": {
                                "type": "string",
                                "description": "Chú thích kèm tệp audio.",
                            },
                        },
                        "required": ["url"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_archive_file",
                    "description": "Liệt kê tệp bên trong archive (ZIP, RAR, 7Z, TAR).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {
                                "type": "string",
                                "description": "Đường dẫn tệp nén.",
                            },
                            "password": {
                                "type": "string",
                                "description": "Mật khẩu nếu có.",
                            },
                        },
                        "required": ["file_path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "extract_archive_file",
                    "description": "Giải nén archive (ZIP, RAR, 7Z, TAR) ra thư mục chỉ định.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {
                                "type": "string",
                                "description": "Đường dẫn tệp nén.",
                            },
                            "destination_dir": {
                                "type": "string",
                                "description": "Thư mục đích.",
                            },
                            "password": {
                                "type": "string",
                                "description": "Mật khẩu nếu có.",
                            },
                        },
                        "required": ["file_path", "destination_dir"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "recover_archive_password",
                    "description": "Tìm mật khẩu tệp nén (RAR, ZIP, 7Z) qua gợi ý hoặc thử danh sách.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {
                                "type": "string",
                                "description": "Đường dẫn tệp nén.",
                            },
                            "clues": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Từ khóa gợi ý.",
                            },
                            "candidate_passwords": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Danh sách mật khẩu thử.",
                            },
                        },
                    },
                },
            },
            # ── Facebook Messenger ──
            {
                "type": "function",
                "function": {
                    "name": "facebook_get_messages",
                    "description": "Lấy danh sách tin nhắn Facebook Messenger mới nhất.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "facebook_capture_screenshot",
                    "description": "Chụp ảnh màn hình hội thoại Messenger với liên hệ.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "recipient_name": {
                                "type": "string",
                                "description": "Tên người nhận.",
                            }
                        },
                        "required": ["recipient_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "facebook_send_reply",
                    "description": "Gửi tin nhắn trả lời qua Facebook Messenger.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "recipient_name": {
                                "type": "string",
                                "description": "Tên người nhận.",
                            },
                            "message": {
                                "type": "string",
                                "description": "Nội dung tin nhắn.",
                            },
                        },
                        "required": ["recipient_name", "message"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_appointments",
                    "description": "Lấy danh sách lịch hẹn từ Facebook Messenger.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "limit": {
                                "type": "integer",
                                "description": "Số lượng lịch hẹn (mặc định 10).",
                            }
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "messenger_list_groups",
                    "description": "Liệt kê các nhóm Messenger đã lưu.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "messenger_get_group_members",
                    "description": "Tra cứu thành viên một nhóm Messenger.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "group_name": {
                                "type": "string",
                                "description": "Tên nhóm cần tra cứu.",
                            }
                        },
                        "required": ["group_name"],
                    },
                },
            },
            # ── Autonomous Browser Tools ──
            {
                "type": "function",
                "function": {
                    "name": "facebook_view_profile",
                    "description": "Mở trang cá nhân Facebook và trích xuất tiểu sử.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name_query": {
                                "type": "string",
                                "description": "Tên người cần tìm kiếm.",
                            }
                        },
                        "required": ["name_query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_navigate",
                    "description": "Mở trang web bằng Chromium headless và trích xuất nội dung.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "URL trang web cần truy cập.",
                            }
                        },
                        "required": ["url"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_search_google",
                    "description": "Tìm kiếm trên Google và trả về top kết quả.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Câu truy vấn tìm kiếm.",
                            }
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_take_screenshot",
                    "description": "Chụp ảnh màn hình trang web hiện tại.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            # ── Fine-grained Browser Control ──
            {
                "type": "function",
                "function": {
                    "name": "browser_click",
                    "description": "Click phần tử trên trang web bằng selector hoặc text.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector_or_text": {
                                "type": "string",
                                "description": "Selector hoặc text cần click.",
                            }
                        },
                        "required": ["selector_or_text"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_type",
                    "description": "Gõ văn bản vào ô input trên trang web.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector": {
                                "type": "string",
                                "description": "Selector ô input.",
                            },
                            "text": {
                                "type": "string",
                                "description": "Văn bản cần gõ.",
                            },
                            "press_enter": {
                                "type": "boolean",
                                "description": "True nếu nhấn Enter sau khi gõ.",
                            },
                        },
                        "required": ["selector", "text"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_scroll",
                    "description": "Cuộn trang web ('up', 'down', 'top', 'bottom').",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "direction": {
                                "type": "string",
                                "enum": ["up", "down", "top", "bottom"],
                                "description": "Hướng cuộn: 'down', 'up', 'top', 'bottom'.",
                            },
                            "pixels": {
                                "type": "integer",
                                "description": "Số pixel cuộn (mặc định 500).",
                            },
                        },
                        "required": ["direction"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_go_back",
                    "description": "Quay lại trang trước trong lịch sử duyệt web.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_go_forward",
                    "description": "Tiến tới trang kế tiếp trong lịch sử duyệt web.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_get_text",
                    "description": "Đọc văn bản từ phần tử DOM bằng selector.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector": {
                                "type": "string",
                                "description": "Selector phần tử cần đọc.",
                            }
                        },
                        "required": ["selector"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_press_key",
                    "description": "Nhấn phím bàn phím trên trang web.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "key": {
                                "type": "string",
                                "description": "Tên phím: 'Enter', 'Tab', 'Escape'...",
                            }
                        },
                        "required": ["key"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_hover",
                    "description": "Hover chuột lên phần tử trên trang web.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector_or_text": {
                                "type": "string",
                                "description": "Selector hoặc text của phần tử.",
                            }
                        },
                        "required": ["selector_or_text"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_select_option",
                    "description": "Chọn option từ dropdown select.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector": {
                                "type": "string",
                                "description": "Selector thẻ select.",
                            },
                            "value": {
                                "type": "string",
                                "description": "Giá trị value hoặc text.",
                            },
                        },
                        "required": ["selector", "value"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_execute_js",
                    "description": "Thực thi JavaScript trên trang hiện tại.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "script": {
                                "type": "string",
                                "description": "Mã JavaScript cần chạy.",
                            }
                        },
                        "required": ["script"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_fill_form",
                    "description": "Điền form (dict selector -> value) và submit.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "fields": {
                                "type": "object",
                                "description": "Mapping selector -> giá trị.",
                                "additionalProperties": {"type": "string"},
                            },
                            "submit_selector": {
                                "type": "string",
                                "description": "Selector nút submit.",
                            },
                        },
                        "required": ["fields"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_wait_for",
                    "description": "Chờ một phần tử DOM xuất hiện hoặc biến mất.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector": {
                                "type": "string",
                                "description": "Selector cần chờ.",
                            },
                            "timeout_ms": {
                                "type": "integer",
                                "description": "Thời gian chờ ms.",
                            },
                            "state": {
                                "type": "string",
                                "enum": ["visible", "attached", "hidden", "detached"],
                                "description": "Trạng thái: visible, hidden, attached, detached.",
                            },
                        },
                        "required": ["selector"],
                    },
                },
            },
            # ── Server Screenshot ──
            {
                "type": "function",
                "function": {
                    "name": "server_capture_screenshot",
                    "description": "Chụp toàn bộ màn hình desktop/server Linux gửi Telegram.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            # ── Phase 5A: Prospective Memory ──
            {
                "type": "function",
                "function": {
                    "name": "remember_for_later",
                    "description": "Ghi nhớ việc cần làm vào Prospective Memory.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "task": {
                                "type": "string",
                                "description": "Mô tả việc cần nhớ.",
                            },
                            "remind_turns": {
                                "type": "integer",
                                "description": "Nhắc lại sau mỗi bao nhiêu lượt hội thoại (mặc định: 3).",
                                "default": 3,
                            },
                        },
                        "required": ["task"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "complete_task",
                    "description": "Đánh dấu hoàn thành việc trong Prospective Memory.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "task_id": {
                                "type": "integer",
                                "description": "ID của task cần hoàn thành.",
                            }
                        },
                        "required": ["task_id"],
                    },
                },
            },
        ]
        filtered_tools: List[Dict[str, Any]] = []
        for t in tools:
            fn = t.get("function")
            if isinstance(fn, dict):
                fn_name = fn.get("name")
                if fn_name not in excluded:
                    if scoped_allowed is None or fn_name in scoped_allowed:
                        filtered_tools.append(t)
        # Deterministic sorting by function name guarantees KV-cache prefix stability across calls
        filtered_tools.sort(key=lambda x: x.get("function", {}).get("name", ""))
        return filtered_tools

    # ──────────────────────────────────────────────────────────────────────────
    # Tool Execution
    # ──────────────────────────────────────────────────────────────────────────

    def _format_vn_time(self, dt: Optional[Any]) -> str:
        """Converts UTC or naive database datetime to Vietnam Timezone (ICT, UTC+7)."""
        if not dt:
            return "chưa quét"
        try:
            if isinstance(dt, str):
                dt = datetime.fromisoformat(dt)
            if isinstance(dt, datetime):
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(VN_TZ).strftime("%d/%m/%Y %H:%M")
        except Exception:
            pass
        return str(dt)

    async def _execute_tool(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        chat_id: Optional[str] = None,
        pending_photos: Optional[list] = None,
        user_message: Optional[str] = None,
    ) -> str:
        try:
            # ── Server ──
            if tool_name == "get_server_active_sessions":
                # 1. Query Web Dashboard Active Sessions from metrics-service via internal JWT
                web_clients = []
                try:
                    import jwt as _jwt
                    import time as _time
                    import urllib.request as _urllib
                    token_payload = {
                        "sub": "kiritoserver",
                        "iat": int(_time.time()),
                        "exp": int(_time.time()) + 3600
                    }
                    admin_token = _jwt.encode(token_payload, settings.JWT_SECRET, algorithm="HS256")
                    req = _urllib.Request(
                        "http://metrics-service:8082/api/metrics/geolocation",
                        headers={"Authorization": f"Bearer {admin_token}"}
                    )
                    with _urllib.urlopen(req, timeout=4) as res:
                        geo_res = json.loads(res.read().decode())
                        web_clients = geo_res.get("connections", [])
                except Exception as e:
                    logger.warning("[AiAgent] Error fetching web clients from metrics-service: %s", e)

                # 2. Query OS-level SSH & Terminal logins via SSH command
                ssh_raw = await self.ssh_client.execute_command(
                    "who 2>/dev/null; echo '---SS_ESTABLISHED---'; ss -tn state established '( dport = :22 )' 2>/dev/null"
                )

                # 3. Format structured dual-layer response
                lines = ["📊 **BÁO CÁO TOÀN DIỆN CÁC PHIÊN ĐĂNG NHẬP & KẾT NỐI VÀO MÁY CHỦ (REAL-TIME)**:\n"]

                # Tầng 1: Web Dashboard Sessions
                lines.append("🌐 **1. TẦNG WEB DASHBOARD (QUẢN TRỊ VIÊN ĐĂNG NHẬP TRÌNH DUYỆT)**:")
                if web_clients:
                    for idx, c in enumerate(web_clients, 1):
                        ip = c.get("ip", "Unknown")
                        city = c.get("city", "Unknown")
                        country = c.get("country", c.get("countryName", "Vietnam"))
                        isp = c.get("isp", "Unknown ISP")
                        status = c.get("loginTime", "CONNECTED")
                        lat = c.get("lat")
                        lon = c.get("lon")
                        coord_str = f" (`{lat:.4f}°N, {lon:.4f}°E`)" if lat and lon else ""
                        lines.append(
                            f"• **Thiết bị #{idx} (Máy tính Web Client)**: Đang đăng nhập Web Dashboard (`{status}`)\n"
                            f"  - Địa chỉ IP: `{ip}`\n"
                            f"  - Vị trí địa lý thực tế: **{city}, {country}**{coord_str}\n"
                            f"  - Nhà mạng (ISP): **{isp}**\n"
                            f"  - Giao thức: `HTTP/HTTPS` (Mini Server Web UI)"
                        )
                else:
                    lines.append("• Hiện không có phiên Web Dashboard nào từ bên ngoài đang mở.")

                lines.append("")
                # Tầng 2: SSH Terminal Sessions
                lines.append("🖥️ **2. TẦNG TERMINAL / SSH (DÒNG LỆNH CỔNG 22 & CỤC BỘ)**:")
                lines.append(f"• Trạng thái phiên SSH:\n```\n{ssh_raw.strip()}\n```")

                return "\n".join(lines)

            if tool_name == "get_server_location":
                # Step 1: Run autonomous Wi-Fi Positioning System locator
                wifi_raw = await self.ssh_client.execute_command(
                    "python3 /home/kirito/quan_ly_server/scripts/server_wifi_locator.py 2>/dev/null"
                )
                geo_data = {}
                if wifi_raw and "{" in wifi_raw:
                    try:
                        parsed = json.loads(wifi_raw[wifi_raw.find("{"):wifi_raw.rfind("}")+1])
                        if "lat" in parsed and "lon" in parsed:
                            geo_data = parsed
                    except Exception:
                        pass

                # Step 2: Fallback to IP Geolocation if Wi-Fi WPS returned error or empty
                if not geo_data:
                    ip_raw = await self.ssh_client.execute_command("curl -s --max-time 4 http://ip-api.com/json/")
                    if ip_raw and "{" in ip_raw:
                        try:
                            geo_data = json.loads(ip_raw[ip_raw.find("{"):ip_raw.rfind("}")+1])
                            geo_data["source"] = "ip_geolocation"
                        except Exception:
                            pass

                if geo_data:
                    city = geo_data.get("city", "Hanoi")
                    country = geo_data.get("country", geo_data.get("countryName", "Vietnam"))
                    lat = geo_data.get("lat", 0.0)
                    lon = geo_data.get("lon", 0.0)
                    source = geo_data.get("source", "wifi_wps")
                    method_str = "Hệ thống định vị sóng Wi-Fi (Wi-Fi WPS - Apple Global Location DB)" if source == "wifi_wps" else "IP Geolocation (FPT Gateway)"

                    return (
                        f"📍 **VỊ TRÍ MÁY CHỦ THỰC TẾ (REAL-TIME TELEMETRY)**:\n"
                        f"• Vị trí: **{city}, {country}**\n"
                        f"• Tọa độ GPS: `{lat:.6f}°N, {lon:.6f}°E`\n"
                        f"• Phương thức xác định: {method_str}\n"
                        f"• IP Mạng nội bộ (LAN): `192.168.0.100`\n"
                        f"• IP Công khai (Public): `1.53.99.21` (FPT Telecom Company)\n"
                        f"• Trạng thái: Đang hoạt động bình thường (On-premise)"
                    )
                return "Không thể xác định vị trí máy chủ vào lúc này."

            if tool_name == "get_weather":
                loc_raw = tool_args.get("location") if tool_args else None
                loc = (loc_raw or "").strip()

                detected_city = None
                detected_country = "Vietnam"
                detected_lat = None
                detected_lon = None
                detected_source = None

                # Tự động định vị máy chủ nếu location rỗng hoặc là từ khóa chỉ vị trí tại chỗ
                if not loc or loc.lower() in ("here", "hiện tại", "máy chủ", "server", "ở đây", "chỗ này", "nơi này"):
                    # 1. Thử Wi-Fi WPS locator
                    wifi_raw = await self.ssh_client.execute_command(
                        "python3 /home/kirito/quan_ly_server/scripts/server_wifi_locator.py 2>/dev/null"
                    )
                    if wifi_raw and "{" in wifi_raw:
                        try:
                            parsed = json.loads(wifi_raw[wifi_raw.find("{"):wifi_raw.rfind("}")+1])
                            if "lat" in parsed and "lon" in parsed:
                                detected_lat = parsed.get("lat")
                                detected_lon = parsed.get("lon")
                                detected_city = parsed.get("city")
                                detected_country = parsed.get("country", "Vietnam")
                                detected_source = "Wi-Fi WPS (Apple DB)"
                        except Exception:
                            pass

                    # 2. Fallback IP Geolocation
                    if not detected_city:
                        ip_raw = await self.ssh_client.execute_command("curl -s --max-time 4 http://ip-api.com/json/")
                        if ip_raw and "{" in ip_raw:
                            try:
                                geo_data = json.loads(ip_raw[ip_raw.find("{"):ip_raw.rfind("}")+1])
                                detected_city = geo_data.get("city") or geo_data.get("regionName", "Hanoi")
                                detected_country = geo_data.get("country", "Vietnam")
                                detected_lat = geo_data.get("lat", 21.0184)
                                detected_lon = geo_data.get("lon", 105.8461)
                                detected_source = f"IP Geolocation ({geo_data.get('isp', 'ISP Gateway')})"
                            except Exception:
                                pass

                    if not detected_city:
                        detected_city = "Hanoi"
                        detected_country = "Vietnam"
                        detected_lat = 21.0285
                        detected_lon = 105.8542
                        detected_source = "Mặc định hệ thống"

                    target_query = detected_city
                else:
                    target_query = loc

                # Format query an toàn cho URL
                query_encoded = target_query.replace(" ", "+")
                weather_cmd = f'curl -s --max-time 5 "wttr.in/{query_encoded}?format=j1" 2>/dev/null'
                res_raw = await self.ssh_client.execute_command(weather_cmd)

                if res_raw and "current_condition" in res_raw:
                    try:
                        wdata = json.loads(res_raw[res_raw.find("{"):res_raw.rfind("}")+1])
                        curr = wdata["current_condition"][0]
                        forecast = wdata.get("weather", [{}])[0]
                        hourly = forecast.get("hourly", [{}])[0] if forecast.get("hourly") else {}

                        desc = curr.get("weatherDesc", [{}])[0].get("value", "Bình thường").strip()
                        temp_c = curr.get("temp_C", "N/A")
                        feels_c = curr.get("FeelsLikeC", temp_c)
                        humidity = curr.get("humidity", "N/A")
                        wind_speed = curr.get("windspeedKmph", "N/A")
                        wind_dir = curr.get("winddir16Point", "")
                        uv_index = curr.get("uvIndex", "N/A")
                        max_temp = forecast.get("maxtempC", "N/A")
                        min_temp = forecast.get("mintempC", "N/A")
                        rain_prob = hourly.get("chanceofrain", "0")

                        desc_vi_map = {
                            "Clear": "Trời quang đãng, nắng ráo ☀️",
                            "Sunny": "Trời nắng ráo ☀️",
                            "Partly cloudy": "Có mây rải rác ⛅",
                            "Partly Cloudy": "Có mây rải rác ⛅",
                            "Cloudy": "Trời nhiều mây ☁️",
                            "Overcast": "Trời u ám, âm u ☁️",
                            "Mist": "Sương mù nhẹ 🌫️",
                            "Patchy rain possible": "Có thể có mưa vài nơi 🌦️",
                            "Light rain": "Mưa nhỏ nhẹ hạt 🌧️",
                            "Moderate rain": "Mưa rào vừa 🌧️",
                            "Heavy rain": "Mưa to nặng hạt ⛈️",
                            "Thundery outbreaks possible": "Có thể có dông sét ⚡",
                        }
                        desc_display = desc_vi_map.get(desc, f"{desc} 🌤️")

                        lines = []
                        if detected_city:
                            lines.append(f"📍 **[TỰ ĐỘNG ĐỊNH VỊ VỊ TRÍ MÁY CHỦ]**: **{detected_city}, {detected_country}**")
                            if detected_lat and detected_lon:
                                lines.append(f"• Tọa độ GPS: `{detected_lat:.4f}°N, {detected_lon:.4f}°E` ({detected_source})")
                            lines.append(f"🌤️ **THỜI TIẾT THỰC TẾ KHU VỰC MÁY CHỦ ({detected_city.upper()})**:")
                        else:
                            lines.append(f"🌤️ **THỜI TIẾT TẠI {target_query.upper()}**:")

                        lines.append(f"• Trạng thái: **{desc_display}**")
                        lines.append(f"• Nhiệt độ: **{temp_c}°C** (Cảm giác thực tế: **{feels_c}°C**)")
                        lines.append(f"• Biên độ ngày: Thấp nhất `{min_temp}°C` — Cao nhất `{max_temp}°C`")
                        lines.append(f"• Độ ẩm không khí: **{humidity}%** | Gió: **{wind_speed} km/h** ({wind_dir})")
                        lines.append(f"• Chỉ số UV: **{uv_index}** | Xác suất mưa: **{rain_prob}%**")

                        try:
                            rain_num = int(rain_prob)
                        except Exception:
                            rain_num = 0
                        if rain_num >= 40:
                            lines.append("💡 **Gợi ý**: Khả năng có mưa khá cao, anh nên mang theo áo mưa/ô khi ra ngoài nhé.")
                        elif float(uv_index) >= 7 if uv_index != "N/A" else False:
                            lines.append("💡 **Gợi ý**: Chỉ số UV khá cao, anh nhớ hạn chế đứng nắng lâu và bảo vệ da.")
                        else:
                            lines.append("💡 **Gợi ý**: Thời tiết khá thuận lợi cho các hoạt động làm việc và di chuyển ngoài trời.")

                        return "\n".join(lines)
                    except Exception as parse_err:
                        logger.warning("[AiAgent] Weather JSON parse error: %s", parse_err)

                # Fallback format string
                fb_cmd = f'curl -s --max-time 4 "wttr.in/{query_encoded}?format=%l:+%c+%t+(cảm+giác+%f),+độ+ẩm+%h,+gió+%w&lang=vi"'
                fb_raw = await self.ssh_client.execute_command(fb_cmd)
                if fb_raw and not fb_raw.startswith("curl:") and not fb_raw.startswith("<!DOCTYPE"):
                    loc_prefix = f"📍 [Vị trí máy chủ: {detected_city}]\n" if detected_city else ""
                    return f"{loc_prefix}🌤️ Thời tiết hiện tại: {fb_raw.strip()}"

                return f"Không thể lấy dữ liệu thời tiết cho khu vực '{target_query}' vào lúc này."

            if tool_name == "run_command":
                cmd = tool_args.get("command", "").strip()
                if not cmd:
                    return "Error: No command specified."
                veto_err = evaluate_spinal_safety_veto(cmd, tool_args.get("confirm"))
                if veto_err:
                    return veto_err
                # Raw output; RTK compression applied at chat-loop level before inserting into history
                return await self.ssh_client.execute_command(cmd)

            if tool_name == "read_archive_file":
                fpath = tool_args.get("file_path", "").strip()
                pwd = tool_args.get("password")
                if not fpath:
                    return "Lỗi: Chưa cung cấp đường dẫn file nén (file_path)."

                check_cmd = f"test -f {shlex.quote(fpath)} && echo 'EXISTS' || echo 'NOT_FOUND'"
                check_res = await self.ssh_client.execute_command(check_cmd)
                if "EXISTS" not in check_res:
                    return f"Lỗi: Không tìm thấy tệp nén tại đường dẫn `{fpath}` trên máy chủ."

                pwd_arg = f"-p{shlex.quote(pwd)}" if pwd else "-p-"
                list_cmd = f"7z l {pwd_arg} {shlex.quote(fpath)} 2>&1"
                list_output = await self.ssh_client.execute_command(list_cmd)
                out_lower = list_output.lower()

                if "wrong password" in out_lower or "data error in encrypted" in out_lower:
                    if pwd:
                        return f"❌ Mật khẩu '{pwd}' không chính xác cho tệp nén `{fpath}`."
                    return f"🔒 Tệp nén `{fpath}` được đặt mật khẩu bảo vệ. Vui lòng cung cấp mật khẩu để giải nén và đọc nội dung."

                if "enter password" in out_lower:
                    if pwd:
                        return f"❌ Mật khẩu '{pwd}' không chính xác cho tệp nén `{fpath}`."
                    return f"🔒 Tệp nén `{fpath}` yêu cầu mật khẩu để xem danh mục tệp."

                return f"📦 **DANH MỤC TỆP NÉN `{fpath}`**:\n```\n{list_output.strip()[:4000]}\n```"

            if tool_name == "extract_archive_file":
                fpath = tool_args.get("file_path", "").strip()
                dest = tool_args.get("destination_dir", "").strip()
                pwd = tool_args.get("password")
                if not fpath or not dest:
                    return "Lỗi: Cần cung cấp đầy đủ file_path và destination_dir."

                pwd_arg = f"-p{shlex.quote(pwd)}" if pwd else "-p-"
                extract_cmd = f"mkdir -p {shlex.quote(dest)} && 7z x -y {pwd_arg} -o{shlex.quote(dest)} {shlex.quote(fpath)} 2>&1"
                res = await self.ssh_client.execute_command(extract_cmd)
                out_lower = res.lower()

                if "wrong password" in out_lower or "data error in encrypted" in out_lower:
                    if pwd:
                        return f"❌ Mật khẩu '{pwd}' không chính xác cho tệp nén `{fpath}`."
                    return f"🔒 Tệp nén `{fpath}` được đặt mật khẩu bảo vệ. Vui lòng cung cấp mật khẩu để giải nén."

                if "everything is ok" in out_lower:
                    return f"✅ Đã giải nén thành công tệp `{fpath}` vào thư mục `{dest}`."
                return f"Kết quả giải nén:\n```\n{res.strip()[:2000]}\n```"

            if tool_name == "recover_archive_password":
                fpath = tool_args.get("file_path", "").strip()
                clues = tool_args.get("clues", [])
                custom_passwords = tool_args.get("candidate_passwords", [])

                target_bytes: Optional[bytes] = None
                display_name = fpath

                # Check if user refers to a recently uploaded file from Telegram
                if (not fpath or any(w in fpath.lower() for w in ("gửi", "recent", "vừa", "telegram", "pending"))) and self.telegram_bot:
                    pending_map = getattr(self.telegram_bot, "_pending_archives", {})
                    # Look for pending archive for this chat_id or the single active pending archive
                    pending_entry = pending_map.get(chat_id)
                    if not pending_entry and len(pending_map) == 1:
                        pending_entry = next(iter(pending_map.values()))
                    if pending_entry:
                        target_bytes = pending_entry["file_bytes"]
                        display_name = pending_entry["filename"]

                if not target_bytes and not fpath:
                    return (
                        "Lỗi: Chưa cung cấp đường dẫn file nén (file_path) trên máy chủ, "
                        "và hiện không có tệp nén nào đang chờ mở khóa từ Telegram."
                    )

                from app.services.archive_recovery import run_archive_recovery

                recovery_res = await run_archive_recovery(
                    archive_path_or_bytes=target_bytes if target_bytes is not None else fpath,
                    clues=clues,
                    custom_candidates=custom_passwords,
                    filename=display_name,
                    ssh_client=self.ssh_client,
                )

                if recovery_res.get("found"):
                    found_pwd = recovery_res.get("password") or ""
                    elapsed = recovery_res.get("elapsed_sec", 0.0)
                    tested = recovery_res.get("tested_count", 0)
                    already_unlocked = recovery_res.get("already_unlocked", False)

                    if already_unlocked:
                        return f"ℹ️ Tệp nén `{display_name}` hoàn toàn KHÔNG đặt mật khẩu bảo vệ! Anh có thể giải nén trực tiếp mà không cần pass."

                    return (
                        f"🎉 **PHÁ KHÓA MẬT KHẨU TỆP NÉN `{display_name}` THÀNH CÔNG!**\n\n"
                        f"🔑 **Mật khẩu chính xác**: `{found_pwd}`\n"
                        f"⏱️ **Thời gian tìm kiếm**: {elapsed}s (đã kiểm tra {tested} mật khẩu ứng viên với 4 workers song song)\n\n"
                        f"💡 Anh có muốn em giải nén tệp này ngay bây giờ không? Hãy cho em biết thư mục đích anh muốn lưu nhé!"
                    )

                tested = recovery_res.get("tested_count", 0)
                elapsed = recovery_res.get("elapsed_sec", 0.0)
                return (
                    f"⚠️ **CHƯA TÌM THẤY MẬT KHẨU CHO TỆP `{display_name}`**\n\n"
                    f"- Đã thử nghiệm: **{tested}** mật khẩu ứng viên trong {elapsed}s nhưng chưa khớp.\n"
                    f"- **Gợi ý**: Anh có nhớ thêm manh mối nào khác không? Ví dụ:\n"
                    f"  * Năm sinh hoặc 4 số cuối điện thoại hay dùng\n"
                    f"  * Biệt danh, tên người thân hoặc chữ cái viết hoa đầu\n"
                    f"  * Ký tự đặc biệt ở cuối như `@`, `!`, `#`\n"
                    f"Hãy chia sẻ thêm cho em, em sẽ mở rộng phạm vi dò tìm ngay nhé!"
                )

            # ── Messenger ──
            if tool_name == "facebook_get_messages":
                # Raw output; RTK compression applied at chat-loop level before inserting into history
                return await self.message_cache.to_ai_summary()

            if tool_name == "facebook_capture_screenshot":
                if not self.fb_service:
                    return "Facebook service chưa được khởi tạo."
                recipient = tool_args.get("recipient_name", "").strip()
                res = await self.fb_service.capture_chat_screenshot(recipient)
                if isinstance(res, dict):
                    if res.get("success"):
                        img_path = res.get("image_path", "")
                        if self.telegram_bot and chat_id and img_path:
                            await self.telegram_bot.send_photo(
                                chat_id=chat_id,
                                photo_path=img_path,
                                caption=f"📸 Màn hình hội thoại Messenger với `{recipient}`",
                            )
                        return f"📸 Đã chụp và gửi ảnh màn hình hội thoại với `{recipient}` qua Telegram!"
                    return f"Lỗi khi chụp màn hình hội thoại: {res.get('error', 'Unknown error')}"
                return str(res)

            if tool_name == "facebook_send_reply":
                if not self.fb_service:
                    return "Facebook service chưa được khởi tạo."
                recipient = tool_args.get("recipient_name", "").strip()
                msg = tool_args.get("message", "").strip()
                res = await self.fb_service.send_direct_reply(recipient, msg)
                if isinstance(res, dict):
                    if res.get("success"):
                        img_path = res.get("image_path", "")
                        if self.telegram_bot and chat_id and img_path:
                            await self.telegram_bot.send_photo(
                                chat_id=chat_id,
                                photo_path=img_path,
                                caption=f"📸 Minh chứng: Đã gửi tin nhắn cho `{recipient}`: \"{msg}\"",
                            )
                        return f'✅ Đã gửi tin nhắn cho "{recipient}": "{msg}"'
                    return f"Lỗi khi gửi tin nhắn cho '{recipient}': {res.get('error', 'Unknown error')}"
                return str(res)

            if tool_name == "get_appointments":
                if not self.appointment_service:
                    return "Dịch vụ quản lý lịch hẹn chưa sẵn sàng."
                limit = tool_args.get("limit", 10)
                apts = await self.appointment_service.get_upcoming_appointments(limit=limit)
                if not apts:
                    return "Hiện tại không có lịch hẹn nào sắp tới từ Facebook Messenger."
                lines = ["📅 Danh sách lịch hẹn từ Facebook Messenger:"]
                for idx, a in enumerate(apts, 1):
                    status_text = "Đã xác nhận" if a.get("status") == "confirmed" else "Đang chờ xác nhận"
                    lines.append(
                        f"{idx}. {a.get('summary', 'Lịch hẹn')} ({status_text})\n"
                        f"   - Người hẹn: {a.get('sender_name', 'Ẩn danh')}\n"
                        f"   - Thời gian: {a.get('proposed_time', 'Chưa rõ')}\n"
                        f"   - Địa điểm: {a.get('location', 'Chưa rõ')}\n"
                        f"   - Tin nhắn gốc: \"{a.get('original_message', '')}\""
                    )
                return "\n".join(lines)

            if tool_name == "messenger_list_groups":
                if not self.fb_service:
                    return "Facebook service chưa được khởi tạo."
                groups = await self.fb_service.get_all_groups()
                if not groups:
                    return (
                        "❌ Chưa phát hiện nhóm Messenger nào trong hệ thống.\n\n"
                        "💡 _Gợi ý: Nhóm sẽ được tự động cập nhật khi bot thực hiện chu kỳ quét tin nhắn._"
                    )
                lines = [
                    f"👥 *DANH SÁCH NHÓM MESSENGER* (Tổng cộng: *{len(groups)} nhóm*)\n"
                ]
                for idx, g in enumerate(groups, 1):
                    scanned = g.get("last_scanned_at")
                    scanned_str = self._format_vn_time(scanned)
                    g_name = g.get("group_name", "Nhóm không tên")
                    m_count = g.get("member_count", 0)
                    lines.append(
                        f"📌 *{idx}. {g_name}*\n"
                        f"   • Số thành viên: *{m_count} người*\n"
                        f"   • Lần quét cuối: `{scanned_str}`"
                    )
                lines.append("\n💡 _Anh có thể nhắn: \"Xem thành viên nhóm [Tên Nhóm]\" để kiểm tra chi tiết!_")
                return "\n\n".join(lines)

            if tool_name == "messenger_get_group_members":
                if not self.fb_service:
                    return "Facebook service chưa được khởi tạo."
                group_name = tool_args.get("group_name", "").strip()
                if not group_name:
                    return "Vui lòng cung cấp tên nhóm cần tra cứu."
                group = await self.fb_service.get_group_members(group_name)
                if not group:
                    return (
                        f"❌ Không tìm thấy nhóm nào khớp với tên: *{group_name}*\n\n"
                        "💡 _Anh có thể nhắn \"Có những nhóm mess nào\" để xem toàn bộ danh sách nhóm hiện có._"
                    )
                members = group.get("members", [])
                if not members:
                    return (
                        f"⚠️ Nhóm *{group.get('group_name')}* hiện chưa có dữ liệu thành viên.\n"
                        "_Dữ liệu sẽ được tự động cập nhật trong chu kỳ quét tiếp theo._"
                    )
                scanned = group.get("last_scanned_at")
                scanned_str = self._format_vn_time(scanned)
                num_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
                lines = [
                    f"👥 *THÀNH VIÊN NHÓM: {group.get('group_name', 'Không tên')}*",
                    f"📊 Tổng cộng: *{len(members)} thành viên*",
                    f"🕒 Cập nhật: `{scanned_str}`\n",
                ]

                # Verified profile registry
                VERIFIED_PROFILES = {
                    "mạnh văn trần": "https://www.facebook.com/tran.v.manh.509",
                    "trần văn mạnh": "https://www.facebook.com/manh090305",
                }

                for idx, m in enumerate(members):
                    num = num_emojis[idx] if idx < len(num_emojis) else f"{idx + 1}."
                    name = m.get("name", "Không tên")
                    role = m.get("role", "")
                    profile = m.get("profile_url", "")
                    
                    low_name = name.lower()
                    if not profile and low_name in VERIFIED_PROFILES:
                        profile = VERIFIED_PROFILES[low_name]
                        
                    is_self = "phạm minh" in low_name or "tài khoản cấu hình" in role.lower() or "tài khoản hiện tại" in role.lower()
                    role_icon = "👑 " if any(k in role.lower() for k in ["quản trị", "admin", "tạo nhóm", "creator"]) else "👤 "
                    
                    if is_self:
                        clean_role = role.replace("(Tài khoản cấu hình hiện tại)", "").strip()
                        role_str = f" — _{clean_role} (Tài khoản cấu hình hiện tại)_" if clean_role else " — _(Tài khoản cấu hình hiện tại)_"
                        member_line = f"{num} {role_icon}*{name}*{role_str}"
                    else:
                        role_str = f" — _{role}_" if role else ""
                        member_line = f"{num} {role_icon}*{name}*{role_str}"
                        if profile:
                            member_line += f"\n   🔗 `{profile}`"
                    lines.append(member_line)
                return "\n".join(lines)

            # ── Autonomous Browser ──
            if tool_name == "facebook_view_profile":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                name_query = tool_args.get("name_query", "").strip()
                # 1. Resolve thread and direct profile URL from known Messenger threads
                resolved_profile_url, matched_thread_href = await self._resolve_thread_info_for_profile(name_query)
                if resolved_profile_url:
                    logger.info(
                        "[AiAgent] Resolved direct profile URL for '%s': %s",
                        name_query,
                        resolved_profile_url,
                    )
                elif matched_thread_href:
                    logger.info(
                        "[AiAgent] Resolved thread_href for '%s': %s",
                        name_query,
                        matched_thread_href,
                    )

                # 2. View profile using BrowserAgent (direct URL, thread click, or ranked People Search)
                res = await self.browser_agent.facebook_view_profile(
                    name_query,
                    profile_url=resolved_profile_url,
                    thread_href=matched_thread_href,
                )

                profile_display_name = res.get("profile_name", name_query)
                profile_url = res.get("profile_url", resolved_profile_url or "N/A")
                intro_text = res.get("intro_text", "Không có thông tin giới thiệu.")[:600]

                return await self._handle_browser_result(
                    res,
                    chat_id=chat_id,
                    default_caption=f"👤 Trang cá nhân Facebook của `{profile_display_name}`",
                    success_prefix=(
                        f"👤 **{profile_display_name}**\n"
                        f"🔗 **Liên kết**: {profile_url}\n\n"
                        f"📝 **Giới thiệu**:\n{intro_text}"
                    ),
                    send_now=True,
                )


            if tool_name == "browser_navigate":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                url = tool_args.get("url", "").strip()
                res = await self.browser_agent.browser_navigate(url)
                return await self._handle_browser_result(
                    res,
                    chat_id=chat_id,
                    default_caption=f"🌐 Trang web: {res.get('url', url)}",
                    success_prefix=(
                        f"🌐 **{res.get('page_title', url)}**\n"
                        f"🔗 URL: {res.get('url', url)}\n\n"
                        f"📄 Nội dung trích xuất:\n{res.get('page_text', '')[:800]}"
                    ),
                    pending_photos=pending_photos,
                )

            if tool_name == "browser_search_google":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                query = tool_args.get("query", "").strip()
                res = await self.browser_agent.browser_search_google(query)
                if res.get("success"):
                    top = res.get("top_results", [])
                    results_text = "\n".join(
                        f"{i+1}. **{r.get('title', '')}**\n   🔗 {r.get('url', '')}\n   {r.get('snippet', '')}"
                        for i, r in enumerate(top)
                    )
                    img_path = res.get("image_path", "")
                    # Defer: add to pending_photos so only the last one is sent
                    if pending_photos is not None and img_path:
                        pending_photos.clear()
                        pending_photos.append((f"🔍 Kết quả Google: {query}", img_path))
                    summary = f"🔍 Kết quả tìm kiếm Google cho: **{query}**\n\n{results_text}" if results_text else res.get("page_text", "")[:1000]
                    return summary
                return f"Lỗi khi tìm kiếm Google: {res.get('error', 'Unknown error')}"

            if tool_name == "browser_take_screenshot":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                res = await self.browser_agent.browser_take_screenshot()
                # Flush any pending deferred photo — this IS the explicit final screenshot
                if pending_photos:
                    pending_photos.clear()
                return await self._handle_browser_result(
                    res,
                    chat_id=chat_id,
                    default_caption=f"📸 Màn hình: {res.get('page_title', 'Trình duyệt')}",
                    success_prefix=f"📸 Ảnh chụp màn hình trang: **{res.get('page_title', '')}**\n🔗 {res.get('url', '')}",
                    send_now=True,  # user explicitly requested this screenshot
                )

            if tool_name == "server_capture_screenshot":
                from pathlib import Path as _Path
                img_path = "/tmp/server_screen.png"
                await self.ssh_client.execute_command(
                    f"DISPLAY=:99 scrot -z {img_path} 2>/dev/null "
                    f"|| DISPLAY=:99 import -window root {img_path} 2>/dev/null || true"
                )
                if self.telegram_bot and chat_id and _Path(img_path).exists():
                    await self.telegram_bot.send_photo(
                        chat_id=chat_id,
                        photo_path=img_path,
                        caption="🖥️ Màn hình máy chủ `kirito-server`",
                    )
                    return "🖥️ Đã chụp và gửi ảnh màn hình máy chủ qua Telegram!"
                return "Đã thực hiện chụp màn hình máy chủ."

            if tool_name in ("download_media_video", "download_media_audio"):
                url = (tool_args.get("url") or "").strip()
                caption_override = tool_args.get("caption") or ""
                req_media_type = tool_args.get("media_type")
                if tool_name == "download_media_audio" or req_media_type == "audio":
                    media_type = "audio"
                else:
                    media_type = (req_media_type or "video").lower()

                if not url:
                    return f"❌ Lỗi: Vui lòng cung cấp đường dẫn (URL) {'âm thanh (audio/mp3)' if media_type == 'audio' else 'video'} hợp lệ."

                logger.info("[AiAgentTools] Executing %s (media_type=%s) for URL: %s", tool_name, media_type, url)
                if self.telegram_bot and chat_id:
                    chat_action = "upload_voice" if media_type == "audio" else "upload_video"
                    await self.telegram_bot.send_chat_action(chat_id, chat_action)

                media_item = None
                try:
                    from app.services.media_downloader import MultiTierMediaPipeline, VideoTooLargeError
                    client = getattr(self.telegram_bot, "_http_client", None)
                    pipeline = MultiTierMediaPipeline(http_client=client)
                    if media_type == "audio":
                        media_item = await pipeline.download_audio(url)
                    else:
                        media_item = await pipeline.download(url)

                    raw_title = media_item.title or ("Audio" if media_type == "audio" else "Video")
                    if len(raw_title) > 350:
                        raw_title = raw_title[:347] + "..."
                    safe_title = html.escape(raw_title)
                    safe_author = html.escape(media_item.author or "Unknown")

                    if (media_item.media_type == "audio" or media_type == "audio") and media_item.file_path:
                        file_size = getattr(media_item, "file_size", 0) or 0
                        if not file_size and media_item.file_path and os.path.exists(media_item.file_path):
                            file_size = os.path.getsize(media_item.file_path)
                        total_mb = file_size / (1024 * 1024) if file_size else 0.0

                        if file_size <= 50 * 1024 * 1024:
                            cap = caption_override or (
                                f"🎵 <b>{safe_title}</b>\n"
                                f"👤 Nghệ sĩ / Kênh: <code>@{safe_author}</code>\n"
                                f"⏱ Thời lượng: {media_item.duration}s | 📦 Dung lượng: {total_mb:.1f} MB\n\n"
                                f"✨ <i>Tiểu Bảo Bảo đã trích xuất âm thanh MP3 320kbps chất lượng cao cho anh Mạnh!</i>"
                            )
                            if self.telegram_bot and chat_id:
                                sent = await self.telegram_bot.send_audio(
                                    chat_id=chat_id,
                                    audio_path=media_item.file_path,
                                    title=media_item.title,
                                    performer=media_item.author,
                                    duration=media_item.duration,
                                    caption=cap,
                                    parse_mode="HTML",
                                    thumbnail=getattr(media_item, "thumbnail_path", None) or getattr(media_item, "cover_url", None),
                                )
                                if not sent and hasattr(self.telegram_bot, "send_document_file"):
                                    await self.telegram_bot.send_document_file(
                                        chat_id=chat_id,
                                        file_path=media_item.file_path,
                                        filename=Path(media_item.file_path).name,
                                        caption=cap,
                                    )
                            return f"🎵 Em đã tải và trích xuất âm thanh MP3 **{media_item.title}** ({total_mb:.1f} MB) thành công và gửi trực tiếp qua Telegram cho anh Mạnh rồi ạ!"
                        else:
                            clean_filename = Path(media_item.file_path).name
                            download_rec = media_storage_manager.publish_download_item(
                                file_path=media_item.file_path,
                                filename=clean_filename,
                                title=raw_title,
                                duration=media_item.duration,
                                ttl_seconds=4 * 3600,
                            )
                            media_item.is_temp_file = False
                            if self.telegram_bot and chat_id:
                                await self.telegram_bot.send_message(
                                    chat_id,
                                    f"📦 <b>Tệp âm thanh chất lượng cao có dung lượng lớn ({total_mb:.1f} MB, vượt quá 50MB của Telegram)!</b>\n\n"
                                    f"🔗 Anh Mạnh có thể tải trực tiếp file MP3 tại:\n"
                                    f"🌐 <b>Link Internet (Ngrok):</b> {download_rec.internet_url}\n"
                                    f"🏠 <b>Link Nội Bộ (LAN):</b> {download_rec.lan_url}\n\n"
                                    f"<i>(Đường link trực tiếp có hiệu lực trong vòng 4 giờ)</i>"
                                )
                            return (
                                f"🎵 Em đã tải file MP3 **{raw_title}** ({total_mb:.1f} MB) thành công!\n"
                                f"📦 Do dung lượng tệp vượt quá 50MB của Telegram, em đã tạo liên kết tải trực tiếp cho anh Mạnh:\n"
                                f"- Internet: {download_rec.internet_url}\n"
                                f"- LAN nội bộ: {download_rec.lan_url}"
                            )

                    elif media_item.media_type == "video" and media_item.file_path:
                        file_size = media_item.file_size
                        total_mb = file_size / (1024 * 1024)

                        if file_size <= 50 * 1024 * 1024:
                            # Video <= 50MB: Gửi trực tiếp 1 video duy nhất qua Telegram
                            cap = caption_override or (
                                f"🎬 <b>{safe_title}</b>\n"
                                f"👤 Kênh: <code>@{safe_author}</code>\n"
                                f"⏱ Thời lượng: {media_item.duration}s | 📦 Dung lượng: {total_mb:.1f} MB\n\n"
                                f"✨ <i>Tiểu Bảo Bảo đã tải thành công video không logo cho anh Mạnh!</i>"
                            )
                            if self.telegram_bot and chat_id:
                                sent = await self.telegram_bot.send_video(
                                    chat_id=chat_id,
                                    video_path=media_item.file_path,
                                    caption=cap,
                                    duration=media_item.duration,
                                )
                                if not sent:
                                    # Fallback stream trực tiếp từ đĩa (Zero-RAM Leak)
                                    if hasattr(self.telegram_bot, "send_document_file"):
                                        await self.telegram_bot.send_document_file(
                                            chat_id=chat_id,
                                            file_path=media_item.file_path,
                                            filename=Path(media_item.file_path).name,
                                            caption=cap,
                                        )
                            return f"🎬 Em đã tải video **{media_item.title}** ({total_mb:.1f} MB) thành công và gửi trực tiếp qua Telegram cho anh Mạnh rồi ạ!"
                        else:
                            # Video > 50MB: Kích hoạt Phân phối video kép (Dual-Track Large Video Distribution)
                            # Thông báo chuẩn bị chia phần nếu có telegram bot
                            if self.telegram_bot and chat_id:
                                await self.telegram_bot.send_message(
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
                            media_item.is_temp_file = False

                            # Kênh 1: Cắt tệp gốc (tại download_rec.file_path) bằng VideoChunker.split_video()
                            parts_dir = Path(tempfile.mkdtemp(prefix="media_parts_", dir=str(media_storage_manager.temp_dir)))
                            try:
                                parts = await VideoChunker.split_video(
                                    video_path=str(download_rec.file_path),
                                    output_dir=parts_dir,
                                )
                                total_parts = len(parts)

                                if self.telegram_bot and chat_id:
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
                                        sent_part = await self.telegram_bot.send_video(
                                            chat_id=chat_id,
                                            video_path=p_path,
                                            caption=part_caption,
                                            duration=p_dur,
                                            width=p_info.get("width", 0),
                                            height=p_info.get("height", 0),
                                        )
                                        if not sent_part and hasattr(self.telegram_bot, "send_document_file"):
                                            await self.telegram_bot.send_document_file(
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

                                        if p_idx < total_parts:
                                            await asyncio.sleep(1.0)

                                    await self.telegram_bot.send_message(
                                        chat_id,
                                        f"✨ <b>Đã gửi trọn vẹn {total_parts}/{total_parts} phần lên Telegram!</b>\n\n"
                                        f"🔗 Hoặc anh Mạnh có thể bấm tải trực tiếp toàn bộ video gốc nguyên khối ({total_mb:.1f} MB) tại:\n"
                                        f"🌐 <b>Link Internet (Ngrok):</b> {download_rec.internet_url}\n"
                                        f"🏠 <b>Link Nội Bộ (LAN):</b> {download_rec.lan_url}\n\n"
                                        f"<i>(Đường link trực tiếp có hiệu lực trong vòng 4 giờ)</i>"
                                    )

                                return (
                                    f"🎬 Em đã tải video **{raw_title}** ({total_mb:.1f} MB) chất lượng cao nhất thành công!\n"
                                    f"📦 Video dung lượng lớn đã được chia thành {total_parts} phần lossless gửi qua Telegram.\n"
                                    f"🔗 Đường link tải trực tiếp nguyên khối (hạn 4 giờ):\n"
                                    f"- Internet: {download_rec.internet_url}\n"
                                    f"- LAN nội bộ: {download_rec.lan_url}"
                                )
                            finally:
                                shutil.rmtree(parts_dir, ignore_errors=True)

                    elif media_item.media_type == "images" and media_item.images:
                        album_caption = caption_override or f"📸 <b>{safe_title}</b>\n👤 Kênh: <code>@{safe_author}</code>"
                        if self.telegram_bot and chat_id:
                            for idx, img_url in enumerate(media_item.images[:10]):
                                await self.telegram_bot.send_photo(chat_id, photo_path=img_url, caption=album_caption if idx == 0 else None)
                        return f"📸 Em đã tải toàn bộ Album ảnh ({len(media_item.images)} ảnh) và gửi qua Telegram cho anh Mạnh rồi ạ!"

                    return f"✅ Đã tải dữ liệu media từ {url} thành công."
                except VideoTooLargeError as v_err:
                    return f"⚠️ Media có dung lượng vượt quá giới hạn 50MB của Telegram Bot ({v_err}). Anh Mạnh có thể xem hoặc tải trực tiếp tại: {url}"
                except Exception as dl_err:
                    logger.error("[AiAgentTools] %s error: %s", tool_name, dl_err, exc_info=True)
                    return f"❌ Xin lỗi anh Mạnh, em gặp sự cố khi tải {'âm thanh' if media_type == 'audio' else 'video'} từ liên kết này ({dl_err})."
                finally:
                    if media_item:
                        media_item.cleanup()

            # ── Phase 5A: Prospective Memory Tools ──────────────────────────
            if tool_name == "remember_for_later":
                if not self.memory_service:
                    return "Prospective memory chưa được khởi tạo."
                task = tool_args.get("task", "").strip()
                remind_turns = int(tool_args.get("remind_turns", 3))
                if not task:
                    return "Cần cung cấp nội dung việc cần nhớ."
                task_id = await self.memory_service.add_pending_task(
                    task_summary=task,
                    created_by_msg=(user_message or task)[:500],
                    remind_turns=remind_turns,
                )
                if task_id:
                    return f"✅ Em đã ghi nhớ việc cần làm (#{task_id}): **{task}**\nEm sẽ nhắc lại anh Mạnh sau mỗi {remind_turns} lượt hội thoại."
                return "Có lỗi khi ghi nhớ, anh Mạnh thử lại nhé."

            if tool_name == "complete_task":
                if not self.memory_service:
                    return "Prospective memory chưa được khởi tạo."
                task_id = int(tool_args.get("task_id", 0))
                if not task_id:
                    return "Cần cung cấp task_id cụ thể."
                success = await self.memory_service.complete_pending_task(task_id)
                if success:
                    return f"✅ Đã đánh dấu hoàn thành việc #{task_id}. Em xóa khỏi danh sách nhắc nhở rồi ạ!"
                return f"Không tìm thấy task #{task_id} hoặc task đã được đánh dấu trước đó."

            if tool_name == "browser_click":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                sel = tool_args.get("selector_or_text", "").strip()
                res = await self.browser_agent.browser_click(sel)
                return await self._handle_browser_result(
                    res, chat_id=chat_id,
                    default_caption=f"💎 Click: {sel}",
                    success_prefix=res.get("action", f"📌 Đã click vào `{sel}`"),
                    pending_photos=pending_photos,
                )

            if tool_name == "browser_type":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                sel = tool_args.get("selector", "").strip()
                text = tool_args.get("text", "").strip()
                press_enter = tool_args.get("press_enter", False)
                res = await self.browser_agent.browser_type(sel, text, press_enter=press_enter)
                return await self._handle_browser_result(
                    res, chat_id=chat_id,
                    default_caption="⌨️ Gõ text",
                    success_prefix=res.get("action", f"⌨️ Đã gõ '{text}' vào `{sel}`"),
                    pending_photos=pending_photos,
                )

            if tool_name == "browser_scroll":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                direction = tool_args.get("direction", "down")
                pixels = int(tool_args.get("pixels", 500))
                res = await self.browser_agent.browser_scroll(direction, pixels)
                return await self._handle_browser_result(
                    res, chat_id=chat_id,
                    default_caption=f"↕️ Cuộn {direction}",
                    success_prefix=res.get("action", f"↕️ Đã cuộn trang {direction}"),
                    pending_photos=pending_photos,
                )

            if tool_name == "browser_go_back":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                res = await self.browser_agent.browser_go_back()
                return await self._handle_browser_result(
                    res, chat_id=chat_id,
                    default_caption="◀️ Quay lại trang trước",
                    success_prefix=f"◀️ {res.get('action', 'Quay lại')} → **{res.get('title', '')}**\n🔗 {res.get('url', '')}",
                    pending_photos=pending_photos,
                )

            if tool_name == "browser_go_forward":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                res = await self.browser_agent.browser_go_forward()
                return await self._handle_browser_result(
                    res, chat_id=chat_id,
                    default_caption="▶️ Tiến tới trang kế tiếp",
                    success_prefix=f"▶️ {res.get('action', 'Tiến tới')} → **{res.get('title', '')}**\n🔗 {res.get('url', '')}",
                    pending_photos=pending_photos,
                )

            if tool_name == "browser_get_text":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                sel = tool_args.get("selector", "").strip()
                res = await self.browser_agent.browser_get_text(sel)
                if res.get("success"):
                    return f"📝 Nội dung `{sel}`:\n```\n{res.get('text', '')}\n```"
                return f"❌ Không lấy được text: {res.get('error')}"

            if tool_name == "browser_press_key":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                key = tool_args.get("key", "").strip()
                res = await self.browser_agent.browser_press_key(key)
                return await self._handle_browser_result(
                    res, chat_id=chat_id,
                    default_caption=f"⌨️ Phím: {key}",
                    success_prefix=res.get("action", f"⌨️ Đã nhấn phím `{key}`"),
                    pending_photos=pending_photos,
                )

            if tool_name == "browser_hover":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                target = tool_args.get("selector_or_text", "").strip()
                res = await self.browser_agent.browser_hover(target)
                return await self._handle_browser_result(
                    res, chat_id=chat_id,
                    default_caption=f"📸 Hover: {target}",
                    success_prefix=res.get("action", f"🔲 Đã hover vào `{target}`"),
                    pending_photos=pending_photos,
                )

            if tool_name == "browser_select_option":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                sel = tool_args.get("selector", "").strip()
                val = tool_args.get("value", "").strip()
                res = await self.browser_agent.browser_select_option(sel, val)
                return await self._handle_browser_result(
                    res, chat_id=chat_id,
                    default_caption=f"📌 Chọn: {val}",
                    success_prefix=res.get("action", f"✔️ Đã chọn `{val}` trong `{sel}`"),
                    pending_photos=pending_photos,
                )

            if tool_name == "browser_execute_js":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                script = tool_args.get("script", "").strip()
                res = await self.browser_agent.browser_execute_js(script)
                if not res.get("success"):
                    return f"❌ Lỗi JS: {res.get('error')}"
                result_text = f"✅ **Kết quả JavaScript:**\n```\n{res.get('result', '')}\n```"
                return await self._handle_browser_result(
                    res, chat_id=chat_id,
                    default_caption="💻 JS executed",
                    success_prefix=result_text,
                    pending_photos=pending_photos,
                )

            if tool_name == "browser_fill_form":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                fields = tool_args.get("fields", {})
                submit_selector = tool_args.get("submit_selector")
                res = await self.browser_agent.browser_fill_form(fields, submit_selector)
                return await self._handle_browser_result(
                    res,
                    chat_id=chat_id,
                    default_caption="📋 Điền form",
                    success_prefix=(
                        f"✅ {res.get('action', 'Đã điền form')}\n"
                        f"🔗 {res.get('url', '')}\n"
                        f"📜 Trang: **{res.get('title', '')}**"
                    ),
                    pending_photos=pending_photos,
                )

            if tool_name == "browser_wait_for":
                if not self.browser_agent:
                    return "Browser agent chưa được khởi tạo."
                sel = tool_args.get("selector", "").strip()
                timeout_ms = int(tool_args.get("timeout_ms", 10000))
                state = tool_args.get("state", "visible")
                res = await self.browser_agent.browser_wait_for(sel, timeout_ms, state)
                return await self._handle_browser_result(
                    res, chat_id=chat_id,
                    default_caption=f"⏳ Chờ: {sel}",
                    success_prefix=res.get("action", f"✅ Element `{sel}` đã xuất hiện"),
                    pending_photos=pending_photos,
                )



            return f"Unknown tool: {tool_name}"


        except Exception as e:
            logger.error("[AiAgent] Tool '%s' error: %s", tool_name, e, exc_info=True)
            return f"Lỗi khi thực thi công cụ `{tool_name}`. Vui lòng kiểm tra lại tham số hoặc liên hệ quản trị viên."

    async def _resolve_thread_info_for_profile(self, name_query: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Resolves the exact Facebook profile URL and/or Messenger thread href for a contact
        by looking up their thread in the persistent DB or in-memory message cache.

        Returns: (profile_url, thread_href)
        """
        import re as _re

        def _extract_standard_user_id(href: str) -> Optional[str]:
            if not href or "/e2ee/" in href:
                return None
            m = _re.search(r"/messages/t/(\d+)", href)
            return m.group(1) if m else None

        if self.fb_service:
            try:
                db_threads = await self.fb_service.get_known_threads_from_db()
                best_score = 0.0
                best_thread: Optional[Dict[str, str]] = None

                for t in db_threads:
                    t_name = t.get("text", "")
                    score = self.fb_service._name_match_score(name_query, t_name)
                    if score > best_score and score >= 0.85:
                        best_score = score
                        best_thread = t

                if best_thread:
                    t_href = best_thread.get("href", "")
                    t_profile = best_thread.get("profile_url", "")
                    if t_profile and t_profile.startswith("http"):
                        return (t_profile, t_href)

                    uid = _extract_standard_user_id(t_href)
                    if uid:
                        return (f"https://www.facebook.com/{uid}", t_href)

                    return (None, t_href)
            except Exception as e:
                logger.warning("[AiAgent] DB thread lookup error: %s", e)

        if self.message_cache:
            try:
                thread_href = await self.message_cache.find_thread_href(name_query)
                if thread_href:
                    uid = _extract_standard_user_id(thread_href)
                    if uid:
                        return (f"https://www.facebook.com/{uid}", thread_href)
                    return (None, thread_href)
            except Exception as e:
                logger.warning("[AiAgent] MessageCache lookup error: %s", e)

        return (None, None)

    async def _flush_pending_photos(self, pending_photos: list, chat_id: Optional[str]) -> None:
        """Send the single deferred photo (if any) to Telegram.

        Design: Only the LAST screenshot from a multi-step chain ends up in
        pending_photos (each new screenshot clears the list before appending).
        This guarantees exactly 1 photo is sent regardless of how many tools ran.

        Skips sending if the photo file is missing or if Telegram is not configured.
        """
        if not pending_photos or not self.telegram_bot or not chat_id:
            return
        caption, img_path = pending_photos[-1]
        pending_photos.clear()
        if img_path:
            try:
                await self.telegram_bot.send_photo(
                    chat_id=chat_id,
                    photo_path=img_path,
                    caption=caption,
                )
            except Exception as e:
                logger.warning("[AiAgent] Failed to flush pending photo %s: %s", img_path, e)

    async def _handle_browser_result(
        self,
        res: Dict[str, Any],
        chat_id: Optional[str],
        default_caption: str,
        success_prefix: str,
        send_now: bool = False,
        pending_photos: Optional[list] = None,
    ) -> str:
        """Process browser tool result.

        Instead of sending the photo immediately (which causes spam when multiple
        tools chain together), we defer the photo to pending_photos and only
        flush the LAST one at the end of the ReAct loop.

        Args:
            send_now: If True, send the photo to Telegram immediately (for terminal tools).
            pending_photos: Accumulator list for deferred (caption, path) tuples.
                           Pass the same list across all tool calls in one turn.
        """
        if not res.get("success"):
            return f"Lỗi: {res.get('error', 'Unknown error')}"

        img_path = res.get("image_path", "")

        if send_now:
            # Terminal tools (facebook_view_profile, server screenshot, etc.) send immediately
            if self.telegram_bot and chat_id and img_path:
                await self.telegram_bot.send_photo(
                    chat_id=chat_id,
                    photo_path=img_path,
                    caption=default_caption,
                )
        elif pending_photos is not None and img_path:
            # Intermediate tool: defer photo, replace any previous pending photo
            # (we only want the LAST screenshot from a multi-step chain)
            pending_photos.clear()
            pending_photos.append((default_caption, img_path))

        return success_prefix

    async def _resolve_profile_url_from_thread(self, name_query: str) -> Optional[str]:
        """
        Resolves the exact Facebook profile URL for a contact by looking up their
        Messenger thread in the persistent DB or in-memory message cache.

        Resolution strategy:
        1. Query known threads in DB and rank by Vietnamese name match score.
        2. If best thread has a saved profile_url, return it immediately.
        3. If best thread is a standard thread (/messages/t/<user_id>/), construct direct URL.
        4. If best thread is E2EE (/messages/e2ee/t/<id>/), invoke extract_profile_url_from_thread.
        5. Otherwise fallback to People Search.
        """
        import re as _re

        def _extract_standard_user_id(href: str) -> Optional[str]:
            """Extract user_id from a standard (non-E2EE) Messenger thread URL."""
            if not href or "/e2ee/" in href:
                return None
            m = _re.search(r"/messages/t/(\d+)", href)
            return m.group(1) if m else None

        if self.fb_service:
            try:
                db_threads = await self.fb_service.get_known_threads_from_db()
                best_score = 0.0
                best_thread: Optional[Dict[str, str]] = None

                for t in db_threads:
                    t_name = t.get("text", "")
                    score = self.fb_service._name_match_score(name_query, t_name)
                    logger.info(
                        "[AiAgent] DB thread check: score=%.2f name='%s' href=%s profile=%s",
                        score, t_name, t.get("href", ""), t.get("profile_url", ""),
                    )
                    if score > best_score and score >= 0.85:
                        best_score = score
                        best_thread = t

                if best_thread:
                    t_href = best_thread.get("href", "")
                    t_profile = best_thread.get("profile_url", "")
                    if t_profile and t_profile.startswith("http"):
                        logger.info(
                            "[AiAgent] DB direct profile hit for '%s' (score=%.2f): %s",
                            name_query, best_score, t_profile,
                        )
                        return t_profile

                    # Check standard thread user ID
                    uid = _extract_standard_user_id(t_href)
                    if uid:
                        profile_url = f"https://www.facebook.com/{uid}"
                        logger.info(
                            "[AiAgent] Standard thread hit for '%s' → profile_url=%s",
                            name_query, profile_url,
                        )
                        return profile_url

                    # Check E2EE thread -> extract live profile URL from Right Sidebar
                    if "/e2ee/" in t_href:
                        logger.info(
                            "[AiAgent] E2EE thread matched for '%s' (score=%.2f) → resolving profile via Messenger...",
                            name_query, best_score,
                        )
                        e2ee_profile = await self.fb_service.extract_profile_url_from_thread(t_href)
                        if e2ee_profile:
                            return e2ee_profile
            except Exception as e:
                logger.warning("[AiAgent] DB thread lookup error: %s", e)

        # Fallback check in-memory message cache
        if self.message_cache:
            try:
                thread_href = await self.message_cache.find_thread_href(name_query)
                if thread_href:
                    uid = _extract_standard_user_id(thread_href)
                    if uid:
                        profile_url = f"https://www.facebook.com/{uid}"
                        logger.info(
                            "[AiAgent] Cache hit → thread '%s' → profile_url=%s",
                            thread_href, profile_url,
                        )
                        return profile_url
                    elif "/e2ee/" in thread_href and self.fb_service:
                        e2ee_profile = await self.fb_service.extract_profile_url_from_thread(thread_href)
                        if e2ee_profile:
                            return e2ee_profile
            except Exception as e:
                logger.warning("[AiAgent] Cache lookup error: %s", e)

        logger.info("[AiAgent] No high-confidence thread found for '%s'; using People Search.", name_query)
        return None


    # ──────────────────────────────────────────────────────────────────────────
    # Direct-return tools — skip the second LLM call to avoid hallucination
    # ──────────────────────────────────────────────────────────────────────────

    # Tools that always terminate the ReAct loop — the screenshot IS the final answer.
    _DIRECT_RETURN_TOOLS = frozenset({
        "facebook_send_reply",
        "facebook_capture_screenshot",
        "facebook_view_profile",
        "server_capture_screenshot",
        "browser_take_screenshot",
        "download_media_video",
        "download_media_audio",
    })

    # Fine-grained browser tools: produce a screenshot observation that the LLM
    # can inspect to decide the NEXT action. NOT terminal — the loop continues.
    _SCREENSHOT_TOOLS = frozenset({
        "browser_navigate",
        "browser_search_google",
        "browser_click",
        "browser_type",
        "browser_scroll",
        "browser_go_back",
        "browser_go_forward",
        "browser_press_key",
        "browser_hover",
        "browser_select_option",
        "browser_execute_js",
        "browser_fill_form",
        "browser_wait_for",
    })


    # ──────────────────────────────────────────────────────────────────────────
    # Public method aliases (Clean API & Backward Compatibility)
    # ──────────────────────────────────────────────────────────────────────────
    resolve_scoped_tool_names = _resolve_scoped_tool_names
    build_tools = _build_tools
    execute_tool = _execute_tool
    flush_pending_photos = _flush_pending_photos
