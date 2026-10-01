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
    # Existing tools
    "facebook_send_reply",
    "facebook_capture_screenshot",
    "facebook_view_profile",
    "server_capture_screenshot",
    "browser_take_screenshot",
    "download_media_video",
    "download_media_audio",
    "create_file_transfer_portal",
    # M7 Video Editor Studio (9 tools)
    "remove_text_from_video",
    "add_subtitle_to_video",
    "apply_color_grade",
    "stabilize_video",
    "concatenate_videos",
    "extract_frames",
    "remove_watermark_region",
    "enhance_video_quality",
    "generate_video_thumbnail",
    # M6 Multimedia Studio (14 tools)
    "edit_video_clip",
    "compress_video",
    "convert_video_format",
    "convert_audio_format",
    "trim_audio_clip",
    "normalize_audio_volume",
    "convert_and_resize_image",
    "generate_custom_qr",
    "inspect_media_metadata",
    "merge_pdf_documents",
    "split_pdf_document",
    "extract_document_text",
    "translate_text",
    "download_direct_file",
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
ACTION_TIER_2_OPERATIONAL = ACTION_TIER_2_REVERSIBLE
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


_GOAL_WORKER_UNSET = object()


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
        "create_file_transfer_portal",
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
        # ── R1 - R8 Tier 1 Safe Read-Only / Diagnostic / Utility Tools ──
        "get_system_health_report",
        "check_service_status",
        "tail_service_logs",
        "list_files",
        "read_file_content",
        "get_disk_usage",
        "calculate",
        "convert_units",
        "list_notes",
        "search_notes",
        "list_cron_jobs",
        "list_scheduled_reminders",
        "get_ngrok_status",
        "get_network_info",
        # ── Milestone 3 Tier 1 Safe Read-Only Security Guardian Tools ──
        "get_security_report",
        "list_blocked_ips",
        "get_honeypot_log",
        "get_attack_history",
        # ── R4 Conversational Goal Management Tier 1 Safe Read-Only Tools ──
        "list_autonomous_goals",
        # ── M6 Omni Super-Agent Tier 1 Safe Multimedia & Document Tools ──
        "edit_video_clip",
        "compress_video",
        "convert_video_format",
        "convert_audio_format",
        "trim_audio_clip",
        "normalize_audio_volume",
        "convert_and_resize_image",
        "generate_custom_qr",
        "merge_pdf_documents",
        "split_pdf_document",
        "extract_document_text",
        "translate_text",
        "inspect_media_metadata",
        "download_direct_file",
        "extract_clean_web_article",
        # ── Milestone 2 Professional Video Editor Tools ──
        "remove_text_from_video",
        "add_subtitle_to_video",
        "apply_color_grade",
        "stabilize_video",
        "concatenate_videos",
        "extract_frames",
        "remove_watermark_region",
        "enhance_video_quality",
        "generate_video_thumbnail",
    }
    if tool_name in tier1_tools:
        return ACTION_TIER_1_SAFE

    if tool_name == "execute_system_script":
        script_code = (tool_args or {}).get("script_code", "")
        confirm = (tool_args or {}).get("confirm", "")
        if confirm == "CONFIRM_DANGEROUS_ACTION":
            return ACTION_TIER_2_REVERSIBLE
        for pattern in _SPINAL_VETO_PATTERNS:
            if pattern.search(script_code):
                return ACTION_TIER_3_LETHAL
        return ACTION_TIER_2_REVERSIBLE

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
        # ── R1 - R8 Tier 2 Reversible / Operational Tools ──
        "restart_service",
        "restart_ngrok_tunnel",
        "delete_cron_job",
        "create_cron_job",
        "send_email",
        "generate_report",
        "write_file_content",
        "move_or_rename_file",
        "schedule_reminder",
        "cancel_reminder",
        "create_note",
        "delete_note",
        "query_database",
        # ── Milestone 3 Tier 2 Reversible Security Guardian Tools ──
        "block_ip",
        "unblock_ip",
        # ── M6 Omni Super-Agent Tier 2 System Mastery Tools ──
        "manage_docker_containers",
        "optimize_system_resources",
        # ── R4 Conversational Goal Management Tier 2 Reversible Tools ──
        "create_autonomous_goal",
        "cancel_autonomous_goal",
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
        pool: Optional[Any] = None,
        scheduler_service: Any = None,
        server_monitor_service: Any = None,
        notes_service: Any = None,
        calculator_service: Any = None,
        cron_service: Any = None,
        email_report_service: Any = None,
        network_service: Any = None,
        file_manager_service: Any = None,
        security_monitor_service: Any = None,
        honeypot_service: Any = None,
        multimedia_service: Any = None,
        document_service: Any = None,
        universal_downloader: Any = None,
        web_article_extractor: Any = None,
        system_mastery_service: Any = None,
        video_editor_service: Any = None,
        autonomous_goal_worker: Any = None,
    ):
        self.ssh_client = ssh_client
        self.message_cache = message_cache
        self.fb_service = fb_service
        self.browser_agent = browser_agent
        self.appointment_service = appointment_service
        self.telegram_bot = telegram_bot
        self.memory_service = memory_service
        self.security_monitor_service = security_monitor_service
        self.honeypot_service = honeypot_service

        # M6 Omni Super-Agent Sub-services
        self._multimedia_service = multimedia_service
        self._document_service = document_service
        self._universal_downloader = universal_downloader
        self._web_article_extractor = web_article_extractor
        self._system_mastery_service = system_mastery_service
        self._video_editor_service = video_editor_service
        self._autonomous_goal_worker = autonomous_goal_worker if autonomous_goal_worker is not None else _GOAL_WORKER_UNSET

        # DB Connection Pool
        from app.core.db import db_manager
        self.pool = pool or db_manager

        # Lazy / Injected Sub-services initialization with SSH and Pool binding
        from app.services.scheduler_service import SchedulerService
        from app.services.server_monitor_service import ServerMonitorService
        from app.services.notes_service import NotesService
        from app.services.calculator_service import CalculatorService
        from app.services.cron_service import CronService
        from app.services.email_report_service import EmailReportService
        from app.services.network_service import NetworkService
        from app.services.file_manager_service import FileManagerService

        self.scheduler_service = scheduler_service or SchedulerService(use_db=True)
        self.server_monitor_service = server_monitor_service or ServerMonitorService(ssh_client=self.ssh_client)
        self.notes_service = notes_service or NotesService(ssh_client=self.ssh_client)
        self.calculator_service = calculator_service or CalculatorService()
        self.cron_service = cron_service or CronService(ssh_client=self.ssh_client)
        self.email_report_service = email_report_service or EmailReportService(monitor_service=self.server_monitor_service)
        self.network_service = network_service or NetworkService(ssh_client=self.ssh_client)
        self.file_manager_service = file_manager_service or FileManagerService(ssh_client=self.ssh_client)

    def set_security_monitor_service(self, service: Any) -> None:
        self.security_monitor_service = service

    def set_honeypot_service(self, service: Any) -> None:
        self.honeypot_service = service

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

    def set_multimedia_service(self, service: Any) -> None:
        self._multimedia_service = service

    def set_document_service(self, service: Any) -> None:
        self._document_service = service

    def set_universal_downloader(self, service: Any) -> None:
        self._universal_downloader = service

    def set_web_article_extractor(self, service: Any) -> None:
        self._web_article_extractor = service

    def set_system_mastery_service(self, service: Any) -> None:
        self._system_mastery_service = service

    def set_video_editor_service(self, service: Any) -> None:
        self._video_editor_service = service

    @property
    def video_editor_service(self) -> Any:
        if self._video_editor_service is None:
            from app.services.video_editor_service import VideoEditorService
            self._video_editor_service = VideoEditorService()
        return self._video_editor_service

    @property
    def multimedia_service(self) -> Any:
        if self._multimedia_service is None:
            from app.services.multimedia_service import MultimediaService
            self._multimedia_service = MultimediaService()
        return self._multimedia_service

    @property
    def document_service(self) -> Any:
        if self._document_service is None:
            from app.services.document_service import DocumentService
            self._document_service = DocumentService()
        return self._document_service

    @property
    def universal_downloader(self) -> Any:
        if self._universal_downloader is None:
            from app.services.universal_downloader import UniversalDownloader
            self._universal_downloader = UniversalDownloader()
        return self._universal_downloader

    @property
    def web_article_extractor(self) -> Any:
        if self._web_article_extractor is None:
            from app.services.web_article_extractor import WebArticleExtractor
            self._web_article_extractor = WebArticleExtractor(browser_agent=self.browser_agent)
        return self._web_article_extractor

    @property
    def system_mastery_service(self) -> Any:
        if self._system_mastery_service is None:
            from app.services.system_mastery_service import SystemMasteryService
            self._system_mastery_service = SystemMasteryService(ssh_client=self.ssh_client)
        return self._system_mastery_service

    def set_autonomous_goal_worker(self, worker: Any) -> None:
        self._autonomous_goal_worker = worker

    @property
    def autonomous_goal_worker(self) -> Any:
        if getattr(self, "_autonomous_goal_worker", _GOAL_WORKER_UNSET) is _GOAL_WORKER_UNSET:
            try:
                from app.services.autonomous_goal_worker import AutonomousGoalWorker
                self._autonomous_goal_worker = AutonomousGoalWorker(tool_executor=self)
            except Exception:
                self._autonomous_goal_worker = None
        return self._autonomous_goal_worker

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
    _TOOL_CLUSTER_TRANSFER = {
        "create_file_transfer_portal",
        "run_command",
    }

    # ── M6 Omni Super-Agent Expanded Clusters (R1 - R4) ──
    _TOOL_CLUSTER_MEDIA = {
        "edit_video_clip",
        "compress_video",
        "convert_video_format",
        "convert_audio_format",
        "trim_audio_clip",
        "normalize_audio_volume",
        "convert_and_resize_image",
        "generate_custom_qr",
        "inspect_media_metadata",
        "download_media_video",
        "download_media_audio",
        # ── Milestone 2 Video Editor Tools ──
        "remove_text_from_video",
        "add_subtitle_to_video",
        "apply_color_grade",
        "stabilize_video",
        "concatenate_videos",
        "extract_frames",
        "remove_watermark_region",
        "enhance_video_quality",
        "generate_video_thumbnail",
    }
    _TOOL_CLUSTER_DOCS = {
        "merge_pdf_documents",
        "split_pdf_document",
        "extract_document_text",
        "translate_text",
        "read_file_content",
        "inspect_media_metadata",
    }
    _TOOL_CLUSTER_WEB = {
        "download_direct_file",
        "extract_clean_web_article",
        "browser_search_google",
        "browser_navigate",
    }
    _TOOL_CLUSTER_SYSTEM = {
        "run_command",
        "execute_system_script",
        "manage_docker_containers",
        "optimize_system_resources",
        "get_system_health_report",
    }

    # ── M5 Extended Tool Clusters (R1 - R8) ──
    _TOOL_CLUSTER_REMINDER = {
        "schedule_reminder",
        "list_scheduled_reminders",
        "cancel_reminder",
    }
    _TOOL_CLUSTER_SERVER_HEALTH = {
        "get_system_health_report",
        "check_service_status",
        "restart_service",
        "tail_service_logs",
        "run_command",
    }
    _TOOL_CLUSTER_NOTES = {
        "create_note",
        "search_notes",
        "list_notes",
        "delete_note",
    }
    _TOOL_CLUSTER_CALCULATOR = {
        "calculate",
        "query_database",
        "convert_units",
    }
    _TOOL_CLUSTER_CRON = {
        "create_cron_job",
        "list_cron_jobs",
        "delete_cron_job",
        "run_command",
    }
    _TOOL_CLUSTER_EMAIL = {
        "send_email",
        "generate_report",
        "get_system_health_report",
    }
    _TOOL_CLUSTER_NETWORK = {
        "get_ngrok_status",
        "restart_ngrok_tunnel",
        "get_network_info",
        "run_command",
    }
    _TOOL_CLUSTER_FILE_MANAGER = {
        "list_files",
        "read_file_content",
        "write_file_content",
        "move_or_rename_file",
        "get_disk_usage",
        "run_command",
    }
    _TOOL_CLUSTER_SECURITY = {
        "get_security_report",
        "list_blocked_ips",
        "get_honeypot_log",
        "get_attack_history",
        "block_ip",
        "unblock_ip",
        "run_command",
    }
    # ── R4 Conversational Goal Management Cluster ──
    _TOOL_CLUSTER_GOALS = {
        "create_autonomous_goal",
        "list_autonomous_goals",
        "cancel_autonomous_goal",
        "get_system_health_report",
        "run_command",
    }

    # Cập nhật _TOOL_CLUSTER_CORE (Đúng 8 tools tinh túy)
    _TOOL_CLUSTER_CORE = {
        "run_command",
        "get_system_health_report",
        "get_weather",
        "get_server_location",
        "download_media_video",
        "download_media_audio",
        "create_file_transfer_portal",
        "browser_search_google",
    }

    _SHORT_SERVER_RE = re.compile(r"\b(ip|top|df|free|port|load|log|ps|ram|cpu|ssh|swap)\b", re.IGNORECASE)
    _SHORT_TASK_RE = re.compile(r"\b(task|done|việc)\b", re.IGNORECASE)
    _SHORT_WEB_RE = re.compile(r"\b(web|url|link|form)\b", re.IGNORECASE)

    # ── Milestone 2 Video Editor Keyword Constants (DRY Tri-Tier Sync) ──
    _KW_REMOVE_TEXT: Tuple[str, ...] = (
        "xóa text", "xoa text", "xóa chữ", "xoa chu",
        "xóa watermark", "xoa watermark", "xóa logo", "xoa logo",
        "remove text", "delogo",
        "xóa sạch", "xoa sach",
        "loại bỏ chữ", "loai bo chu", "loại bỏ text", "loai bo text",
        "loại bỏ watermark", "loai bo watermark", "loại bỏ logo", "loai bo logo",
        "bỏ chữ trong video", "bo chu trong video", "bỏ text trong video", "bo text trong video",
        "bỏ chữ trong clip", "bo chu trong clip", "bỏ text trong clip", "bo text trong clip",
        "xóa bỏ chữ trong video", "xoa bo chu trong video", "xóa bỏ text trong video", "xoa bo text trong video",
        "loại bỏ chữ trong clip", "loai bo chu trong clip", "loại bỏ text trong clip", "loai bo text trong clip",
        "loại bỏ chữ trong video", "loai bo chu trong video", "loại bỏ text trong video", "loai bo text trong video",
        "xóa phụ đề", "xoa phu de", "xóa sub", "xoa sub",
        "làm sạch video", "lam sach video",
        "clean text", "erase text", "wipe text", "clear text",
        "remove watermark", "watermark removal", "text removal",
        "xóa chữ trong video", "xoa chu trong video",
        "xóa text trong video", "xoa text trong video",
        "xóa sạch text", "xoa sach text", "xóa sạch chữ", "xoa sach chu",
        "xóa caption", "xoa caption", "remove caption",
        "xóa chữ khỏi", "xoa chu khoi", "xóa text khỏi", "xoa text khoi",
    )
    _KW_ADD_SUBTITLE: Tuple[str, ...] = (
        "thêm phụ đề", "them phu de", "gắn phụ đề", "gan phu de",
        "chèn phụ đề", "chen phu de", "add subtitle", "subtitles",
        "vietsub", "làm sub", "lam sub",
        "thêm sub", "them sub", "gắn sub", "gan sub",
        "chèn sub", "chen sub", "add sub",
        "thêm caption", "them caption", "chèn caption", "chen caption", "add caption",
        "thêm chữ vào video", "them chu vao video", "chèn chữ vào video", "chen chu vao video",
        "thêm text vào video", "them text vao video", "chèn text vào video", "chen text vao video",
        "thêm chữ vào clip", "them chu vao clip", "chèn chữ vào clip", "chen chu vao clip",
        "thêm text vào clip", "them text vao clip", "chèn text vào clip", "chen text vao clip",
        "lồng phụ đề", "long phu de", "ghép phụ đề", "ghep phu de",
        "hardsub", "softsub", "burn sub", "burn subtitle",
        "phụ đề tiếng việt", "phu de tieng viet",
        "phụ đề", "phu de", "subtitle", "caption",
    )
    _KW_COLOR_GRADE: Tuple[str, ...] = (
        "chỉnh màu", "chinh mau", "đổi màu video", "doi mau video",
        "color grade", "vivid", "vintage", "cinematic",
        "bộ lọc màu", "bo loc mau",
        "lọc màu", "loc mau", "color grading", "grade màu", "grade mau",
        "chỉnh màu video", "chinh mau video", "làm màu video", "lam mau video",
        "tông ấm", "tong am", "tone ấm", "tone am", "màu ấm", "mau am", "warm tone",
        "tông lạnh", "tong lanh", "tone lạnh", "tone lanh", "màu lạnh", "mau lanh", "cool tone",
        "chỉnh màu ấm", "chinh mau am", "chỉnh màu lạnh", "chinh mau lanh",
        "retro", "đen trắng", "den trang", "black and white",
        "filter video", "filter màu", "filter mau", "bộ lọc video", "bo loc video",
        "đổi tông màu", "doi tong mau", "tông màu", "tong mau",
    )
    _KW_STABILIZE: Tuple[str, ...] = (
        "chống rung", "chong rung", "ổn định video", "on dinh video",
        "stabilize video", "vidstab", "rung lắc", "rung lac",
        "khử rung", "khu rung", "giảm rung", "giam rung", "bớt rung", "bot rung",
        "chống rung video", "chong rung video", "khử rung video", "khu rung video",
        "làm mượt video", "lam muot video", "video bị rung", "video bi rung",
        "ổn định hình ảnh", "on dinh hinh anh", "video stabilization", "stabilizer",
        "deshake", "smooth video",
    )
    _KW_CONCAT: Tuple[str, ...] = (
        "ghép video", "ghep video", "nối video", "noi video",
        "concatenate video", "gộp video", "gop video",
        "ghép clip", "ghep clip", "nối clip", "noi clip", "gộp clip", "gop clip",
        "ghép các video", "ghep cac video", "nối các video", "noi cac video", "gộp các video", "gop cac video",
        "ghép nhiều video", "ghep nhieu video", "nối nhiều video", "noi nhieu video",
        "nối nhiều clip", "noi nhieu clip", "ghép nhiều clip", "ghep nhieu clip", "gộp nhiều clip", "gop nhieu clip",
        "merge video", "join video", "combine video", "concat video", "stitch video",
        "nối 2 video", "noi 2 video", "ghép 2 video", "ghep 2 video",
    )
    _KW_EXTRACT_FRAMES: Tuple[str, ...] = (
        "trích frame", "trich frame", "cắt frame", "cat frame",
        "trích xuất frame", "trich xuat frame", "extract frames",
        "lấy ảnh từ video", "lay anh tu video",
        "tách frame", "tach frame", "lấy frame", "lay frame", "xuất frame", "xuat frame",
        "trích khung hình", "trich khung hinh", "lấy khung hình", "lay khung hinh", "cắt khung hình", "cat khung hinh",
        "chụp frame", "chup frame", "lấy từng frame", "lay tung frame",
        "rút frame", "rut frame", "capture frames", "frame extraction", "video to frames",
        "frame ảnh", "frame anh",
    )
    _KW_REMOVE_WATERMARK: Tuple[str, ...] = (
        "xóa nhiều watermark", "xoa nhieu watermark",
        "xóa vùng watermark", "xoa vung watermark",
        "xóa logo góc", "xoa logo goc",
        "xóa watermark theo vùng", "xoa watermark theo vung",
        "xóa watermark vùng", "xoa watermark vung",
        "xóa nhiều logo", "xoa nhieu logo",
        "xóa nhiều vùng logo", "xoa nhieu vung logo",
        "xóa vùng logo", "xoa vung logo",
        "nhiều vùng logo", "nhieu vung logo",
        "loại bỏ nhiều watermark", "loai bo nhieu watermark",
        "xóa watermark góc", "xoa watermark goc",
        "xóa logo ở góc", "xoa logo o goc",
        "remove watermark region", "remove multiple watermarks",
        "multi watermark", "watermark regions", "vùng watermark", "vung watermark",
    )
    _KW_ENHANCE_VIDEO: Tuple[str, ...] = (
        "tăng chất lượng video", "tang chat luong video", "nâng cao chất lượng video", "nang cao chat luong video",
        "nâng chất lượng video", "nang chat luong video", "nâng chất lượng clip", "nang chat luong clip",
        "tăng chất lượng clip", "tang chat luong clip", "nâng cao chất lượng clip", "nang cao chat luong clip",
        "làm nét video", "lam net video", "làm nét clip", "lam net clip",
        "khử nhiễu video", "khu nhieu video", "khử nhiễu clip", "khu nhieu clip",
        "upscale video", "enhance video", "sharpen video", "denoise video",
        "tăng độ nét cho video", "tang do net cho video", "tăng độ nét video", "tang do net video",
        "nâng độ nét video", "nang do net video", "tăng độ nét clip", "tang do net clip",
        "làm rõ video", "lam ro video", "làm rõ clip", "lam ro clip",
        "video bị mờ", "video bi mo", "video mờ", "video mo", "khử mờ video", "khu mo video",
        "video bị nhiễu", "video bi nhieu", "clip bị mờ", "clip bi mo", "clip bị nhiễu", "clip bi nhieu",
        "super resolution video", "video enhance", "improve video quality",
    )
    _KW_GENERATE_THUMBNAIL: Tuple[str, ...] = (
        "tạo thumbnail", "tao thumbnail", "ảnh đại diện video", "anh dai dien video",
        "thumbnail video", "video thumbnail", "generate thumbnail", "bìa video", "bia video",
        "làm thumbnail", "lam thumbnail", "tạo ảnh bìa", "tao anh bia",
        "ảnh bìa video", "anh bia video", "làm bìa video", "lam bia video",
        "tạo cover", "tao cover", "cover video", "cắt thumbnail", "cat thumbnail",
        "lấy thumbnail", "lay thumbnail", "video poster",
    )
    _ALL_VIDEO_EDITOR_KEYWORDS: Tuple[str, ...] = tuple(
        dict.fromkeys(
            _KW_REMOVE_TEXT
            + _KW_ADD_SUBTITLE
            + _KW_COLOR_GRADE
            + _KW_STABILIZE
            + _KW_CONCAT
            + _KW_EXTRACT_FRAMES
            + _KW_REMOVE_WATERMARK
            + _KW_ENHANCE_VIDEO
            + _KW_GENERATE_THUMBNAIL
        )
    )
    # ── M6 Super-Agent Semantic Scoping Patterns (R1 - R4) ──
    _SHORT_MEDIA_STUDIO_RE = re.compile(
        r"\b("
        r"cắt(?:\s+\w+)?\s+(?:video|clip)|cat(?:\s+\w+)?\s+(?:video|clip)|nén(?:\s+\w+)?\s+video|nen(?:\s+\w+)?\s+video|compress\s+video|giảm\s+dung\s+lượng\s+video|giam\s+dung\s+luong\s+video|"
        r"đổi\s+đuôi\s+video|doi\s+duoi\s+video|chuyển\s+định\s+dạng\s+video|chuyen\s+dinh\s+dang\s+video|convert\s+video|mp4\s+sang|mkv\s+sang|tạo\s+gif|tao\s+gif|làm\s+gif|lam\s+gif|"
        r"đổi\s+đuôi\s+nhạc|doi\s+duoi\s+nhac|convert\s+audio|chuyển\s+định\s+dạng\s+âm\s+thanh|chuyen\s+dinh\s+dang\s+am\s+thanh|flac\s+sang|wav\s+sang|m4a\s+sang|320k(?:bps)?|"
        r"cắt(?:\s+\w+)?\s+(?:nhạc|audio|bài hát)|cat(?:\s+\w+)?\s+(?:nhac|audio|bai hat)|làm\s+nhạc\s+chuông|lam\s+nhac\s+chuong|nhạc\s+chuông|nhac\s+chuong|trim\s+audio|"
        r"chuẩn\s+hóa\s+âm\s+lượng|chuan\s+hoa\s+am\s+luong|cân\s+bằng\s+âm\s+lượng|can\s+bang\s+am\s+luong|tang\s+am\s+luong|tăng\s+âm\s+lượng|giam\s+am\s+luong|giảm\s+âm\s+lượng|loudnorm|ebu\s+r128|"
        r"resize\s+ảnh|resize\s+anh|nén\s+ảnh|nen\s+anh|đổi\s+kích\s+thước\s+ảnh|doi\s+kich\s+thuoc\s+anh|webp\s+sang|png\s+sang|jpg\s+sang|chuyển\s+ảnh\s+sang|chuyen\s+anh\s+sang|"
        r"tạo(?:\s+mã)?\s+qr|tao(?:\s+ma)?\s+qr|sinh\s+qr|mã\s+qr|ma\s+qr|qr\s+code|qr\s+wifi|qr\s+ngân\s+hàng|quet\s+qr|quét\s+qr|"
        r"metadata|thông\s+tin\s+video|thong\s+tin\s+video|thông\s+tin\s+audio|thong\s+tin\s+audio|ffprobe|exif|độ\s+phân\s+giải\s+video|do\s+phan\s+giai\s+video|codec\s+video|"
        r"xóa\s+(?:sạch\s+)?(?:text|chữ|chu|watermark|logo|phụ\s+đề|phu\s+de|sub|caption)|xoa\s+(?:sach\s+)?(?:text|chữ|chu|watermark|logo|phu\s+de|sub|caption)|"
        r"loại\s+bỏ\s+(?:chữ|chu|text|watermark|logo)|loai\s+bo\s+(?:chu|text|watermark|logo)|"
        r"bỏ\s+(?:chữ|chu|text)|bo\s+(?:chu|text)|"
        r"xóa\s+bỏ\s+(?:chữ|chu|text)|xoa\s+bo\s+(?:chu|text)|"
        r"làm\s+sạch\s+video|lam\s+sach\s+video|clean\s+text|erase\s+text|wipe\s+text|clear\s+text|"
        r"remove\s+watermark|watermark\s+removal|text\s+removal|remove\s+caption|"
        r"thêm\s+phụ\s+đề|them\s+phu\s+de|gắn\s+phụ\s+đề|gan\s+phu\s+de|chèn\s+phụ\s+đề|chen\s+phu\s+de|add\s+subtitle|subtitles|vietsub|"
        r"chỉnh\s+màu|chinh\s+mau|đổi\s+màu\s+video|doi\s+mau\s+video|color\s+grade|bộ\s+lọc\s+màu|bo\s+loc\s+mau|"
        r"chống\s+rung|chong\s+rung|ổn\s+định\s+video|on\s+dinh\s+video|stabilize\s+video|vidstab|rung\s+lắc|rung\s+lac|"
        r"ghép\s+video|ghep\s+video|nối\s+video|noi\s+video|concatenate\s+video|gộp\s+video|gop\s+video|"
        r"trích\s+frame|trich\s+frame|cắt\s+frame|cat\s+frame|trích\s+xuất\s+frame|trich\s+xuat\s+frame|extract\s+frames|lấy\s+ảnh\s+từ\s+video|lay\s+anh\s+tu\s+video|"
        r"xóa\s+vùng\s+watermark|xoa\s+vung\s+watermark|xóa\s+nhiều\s+watermark|xoa\s+nhieu\s+watermark|"
        r"tăng\s+chất\s+lượng|tang\s+chat\s+luong|nâng\s+cao\s+chất\s+lượng|nang\s+cao\s+chat\s+luong|làm\s+nét\s+video|lam\s+net\s+video|khử\s+nhiễu\s+video|khu\s+nhieu\s+video|upscale\s+video|enhance\s+video|"
        r"tạo\s+thumbnail|tao\s+thumbnail|ảnh\s+đại\s+diện\s+video|anh\s+dai\s+dien\s+video|thumbnail\s+video|generate\s+thumbnail|bìa\s+video|bia\s+video"
        r")\b",
        re.IGNORECASE,
    )

    _SHORT_DOCS_RE = re.compile(
        r"\b("
        r"gộp(?:\s+[\w\s]{1,25})?\s+pdf|gop(?:\s+[\w\s]{1,25})?\s+pdf|merge\s+pdf|ghép(?:\s+[\w\s]{1,25})?\s+pdf|ghep(?:\s+[\w\s]{1,25})?\s+pdf|nối(?:\s+[\w\s]{1,25})?\s+pdf|noi(?:\s+[\w\s]{1,25})?\s+pdf|"
        r"tách(?:\s+[\w\s\d\-]{1,35})?\s+pdf|tach(?:\s+[\w\s\d\-]{1,35})?\s+pdf|split\s+pdf|cắt\s+trang\s+pdf|cat\s+trang\s+pdf|trích\s+trang\s+pdf|trich\s+trang\s+pdf|tách(?:\s+\w+)?\s+trang|tach(?:\s+\w+)?\s+trang|"
        r"đọc(?:\s+[\w\s]{1,40})?\s+(?:pdf|docx|word)|doc(?:\s+[\w\s]{1,40})?\s+(?:pdf|docx|word)|"
        r"nội\s+dung\s+file(?:\s+[\w\s]{1,20})?\s+(?:pdf|docx|word)|noi\s+dung\s+file(?:\s+[\w\s]{1,20})?\s+(?:pdf|docx|word)|"
        r"(?:dịch|dich)(?!\s+(?:vụ|vu))\b|translate|dịch\s+văn\s+bản|dich\s+van\s+ban|dịch\s+sang|nghĩa\s+là\s+gì|nghia\s+la\s+gi"
        r")\b",
        re.IGNORECASE,
    )

    _SHORT_WEB_DOWNLOAD_ARTICLE_RE = re.compile(
        r"\b("
        r"tải\s+tệp|tai\s+tep|tải\s+file|tai\s+file|download\s+file|download\s+direct|tải\s+link|tai\s+link|file\s+zip|file\s+iso|"
        r"bóc\s+tách\s+bài\s+viết|boc\s+tach\s+bai\s+viet|bóc\s+bài\s+viết|boc\s+bai\s+viet|đọc\s+bài\s+báo|doc\s+bai\s+bao|bài\s+báo|bai\s+bao|đọc\s+báo|doc\s+bao|trích\s+xuất\s+bài\s+viết|trich\s+xuat\s+bai\s+viet|extract\s+article|nội\s+dung\s+bài\s+báo|noi\s+dung\s+bai\s+bao|tóm\s+tắt\s+bài\s+báo|tom\s+tat\s+bai\s+bao|tóm\s+tắt\s+bài\s+viết|tom\s+tat\s+bai\s+viet"
        r")\b",
        re.IGNORECASE,
    )

    _SHORT_SYSTEM_ROOT_RE = re.compile(
        r"\b("
        r"chạy\s+script|chay\s+script|execute\s+script|script\s+bash|script\s+python|chạy\s+code\s+python|chay\s+code\s+python|chạy\s+kịch\s+bản|chay\s+kich\s+ban|kịch\s+bản\s+bash|kich\s+ban\s+bash|kịch\s+bản\s+python|kich\s+ban\s+python|"
        r"quản\s+lý\s+docker|quan\s+ly\s+docker|docker\s+restart|restart\s+container|khởi\s+động\s+lại\s+container|khoi\s+dong\s+lai\s+container|dừng\s+container|dung\s+container|stop\s+container|bật\s+container|bat\s+container|start\s+container|"
        r"xóa\s+rác\s+docker|xoa\s+rac\s+docker|docker\s+prune|dọn\s+dẹp\s+hệ\s+thống|don\s+dep\s+he\s+thong|giải\s+phóng\s+ram|giai\s+phong\s+ram|drop_caches|giảm\s+tải\s+ram|giam\s+tai\s+ram|dọn(?:\s+dẹp)?\s+ram|don(?:\s+dep)?\s+ram|"
        r"tối\s+ưu\s+máy\s+chủ|toi\s+uu\s+may\s+chu|tối\s+ưu\s+server|toi\s+uu\s+server|tối\s+ưu\s+hệ\s+thống|toi\s+uu\s+he\s+thong|root|sudo"
        r")\b",
        re.IGNORECASE,
    )

    _SHORT_REMINDER_RE = re.compile(
        r"\b(nhắc|nhac|remind|reminder|alarm|hẹn giờ|hen gio|đặt lịch|dat lich|lịch nhắc|lich nhac)\b",
        re.IGNORECASE,
    )
    _SHORT_SERVER_HEALTH_RE = re.compile(
        r"\b(sức khỏe|suc khoe|health|health report|tail log|service log|restart service|check service|reboot service|dịch vụ|dich vu|systemctl|đang active|active không|is-active|service status)\b",
        re.IGNORECASE,
    )
    _SHORT_NOTES_RE = re.compile(
        r"\b(ghi chú|ghi chu|note|notes|notepad|sổ tay|so tay)\b",
        re.IGNORECASE,
    )
    _MATH_EXPR_RE = re.compile(
        r"(?:(?:\d+(?:\.\d+)?)\s*[\+\-\*\/\^%]\s*(?:\d+(?:\.\d+)?))|"
        r"\b(?:sin|cos|tan|sqrt|log|exp|pow|compound_interest)\s*\(",
        re.IGNORECASE,
    )
    _SHORT_CALC_RE = re.compile(
        r"\b(tính|tinh|calculate|calculator|math|phép tính|phep tinh|máy tính|may tinh|lãi suất|lai suat|lãi kép|lai kep|đổi đơn vị|doi don vi|chuyển đổi đơn vị|chuyen doi don vi|convert units|query database|truy vấn|truy van|sql|postgres|postgresql)\b",
        re.IGNORECASE,
    )
    _SHORT_CRON_RE = re.compile(
        r"\b(cron|crontab|cronjob|tự động hóa|tu dong hoa|lên lịch tự động|len lich tu dong|định kỳ|dinh ky|hàng ngày|hang ngay|hàng tuần|hang tuan|hàng tháng|hang thang)\b",
        re.IGNORECASE,
    )
    _EMAIL_ADDRESS_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
    _SHORT_EMAIL_RE = re.compile(
        r"\b(email|send email|gửi email|gui email|send mail|gửi thư|gui thu|hộp thư|hop thu|báo cáo|bao cao|report|generate report)\b",
        re.IGNORECASE,
    )
    _SHORT_NETWORK_RE = re.compile(
        r"\b(ngrok|tunnel|public ip|ip công khai|ip cong khai|địa chỉ ip|dia chi ip|tốc độ mạng|toc do mang|isp|kiểm tra mạng|kiem tra mang|mạng internet|mang internet)\b",
        re.IGNORECASE,
    )
    _PATH_PREFIX_RE = re.compile(r"(?:^|\s)(?:/(?:home|tmp|var|etc|usr|opt)(?:/[\w\.\-]+)*|\./[\w\.\-]+)\b")
    _SHORT_FILE_RE = re.compile(
        r"\b(file|folder|thư mục|thu muc|tệp tin|tep tin|tệp|tep|đọc file|doc file|xem file|danh sách file|danh sach file|ghi file|đổi tên file|doi ten file|dung lượng ổ đĩa|dung luong o dia|disk usage|du -sh)\b",
        re.IGNORECASE,
    )
    _SHORT_SECURITY_RE = re.compile(
        r"\b("
        r"an ninh|an ninh mạng|bảo mật|bao mat|tấn công|tan cong|attack|attacker|threat|hacker|hack|"
        r"block ip|chặn ip|chan ip|khóa ip|khoa ip|mở khóa ip|mo khoa ip|unblock ip|unblock|chặn|block|"
        r"mở khóa|mo khoa|gỡ chặn|go chan|bỏ chặn|bo chan|"
        r"honeypot|bẫy|kẻ thất bại|ke that bai|brute force|bruteforce|sqli|sql injection|"
        r"xss|port scan|quét cổng|quet cong|iptables|firewall|tường lửa|tuong lua|"
        r"blacklist|whitelist|danh sách đen|danh sách trắng|bị chặn|bi chan|"
        r"lịch sử tấn công|lich su tan cong|báo cáo an ninh|bao cao an ninh"
        r")\b",
        re.IGNORECASE,
    )
    _SHORT_GOAL_RE = re.compile(
        r"\b("
        r"mục tiêu|muc tieu|goal|goals|autonomous|tự hành|tu hanh|"
        r"lập kế hoạch|lap ke hoach|kế hoạch tự động|ke hoach tu dong|"
        r"theo dõi và|theo doi va|bám sát|tự động theo dõi|tu dong theo doi|"
        r"task tự động|task tu dong|tác vụ tự động|tac vu tu dong|"
        r"đang theo dõi gì|đang theo dõi những gì|dang theo doi gi|dang theo doi nhung gi"
        r")\b",
        re.IGNORECASE,
    )

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
            "douyin.com", "threads.net", "threads.com",
            "instagram.com", "instagr.am", "twitter.com", "x.com", "t.co",
            "soundcloud.com", "reddit.com", "redd.it", "v.redd.it",
            "bilibili.com", "b23.tv", "pinterest.com", "pin.it", "kuaishou.com",
            "twitch.tv", "vimeo.com", "dailymotion.com", "dai.ly", "rumble.com",
            "streamable.com", "loom.com", "capcut.com", "xiaohongshu.com", "xhslink.com",
            "weibo.com", "weibo.cn", "lemon8-app.com", "likee.video", "likee.com", "bsky.app"
        ))
        is_audio = any(k in q for k in (
            "tải mp3", "tai mp3", "tách nhạc", "tach nhac", "lấy audio", "lay audio",
            "nhạc tiktok", "nhac tiktok", "audio", "mp3", "bài hát", "bai hat", "nhạc", "nhac",
            "tải audio", "tai audio", "download audio", "download mp3", "soundcloud"
        ))

        is_media = has_media_link or is_audio or any(k in q for k in (
            "tiktok", "youtube", "douyin", "reels", "reel", "video", "clip", "mp4",
            "shorts", "down video", "lưu clip", "tải video", "tải clip", "tải về",
            "download video", "download clip", "tai video", "tai clip", "tai ve",
            "lay video", "lay clip", "keo video", "instagram", "insta", "threads", "twitter",
            "soundcloud", "reddit", "bilibili", "pinterest", "kuaishou",
            "twitch", "vimeo", "dailymotion", "rumble", "streamable", "loom",
            "capcut", "xiaohongshu", "rednote", "tiểu hồng thư", "tieu hong thu", "xhs",
            "weibo", "lemon8", "likee", "bluesky", "bsky",
            "4k", "60fps", "1080p60", "fps cao", "mượt mà",
        ))

        is_transfer = any(k in q for k in (
            "chuyển file", "chuyen file", "bắn file", "ban file", "gửi file", "gui file",
            "chuyển ảnh", "chuyen anh", "bắn ảnh", "ban anh", "gửi ảnh", "gui anh",
            "chuyển video", "chuyen video", "bắn video", "ban video", "gửi video", "gui video",
            "gửi file sang điện thoại", "chuyển ảnh sang ipad", "bắn ảnh sang ipad",
            "sang điện thoại", "sang dien thoai", "sang dt", "sang phone",
            "sang ipad", "sang tablet", "sang laptop", "sang máy tính", "sang may tinh",
            "sang máy khác", "sang may khac",
            "share file", "chia sẻ file", "chia se file", "upload file", "download file",
            "tải file lên", "tai file len", "tải file về", "tai file ve", "tải tệp", "tai tep",
            "gửi tệp", "gui tep", "chuyển tệp", "chuyen tep", "bắn tệp", "ban tep",
            "airdrop", "drop file", "file drop", "chuyển tài liệu", "chuyen tai lieu",
            "portal transfer", "file portal", "cổng truyền file", "cong truyen file",
            "truyền file", "truyen file", "transfer portal", "portal"
        ))

        is_server = bool(self._SHORT_SERVER_RE.search(q)) or any(k in q for k in (
            "server", "máy chủ", "bộ nhớ", "ổ đĩa", "dung lượng",
            "docker", "container", "tiến trình", "process", "htop", "cortex",
            "trạng thái", "kiểm tra", "vị trí", "đăng nhập", "session", "phiên", "phiên kết nối", "phiên làm việc", "reboot", "uptime", "sức khỏe",
            "bật bao lâu", "mở bao lâu", "chạy bao lâu", "hoạt động bao lâu", "máy đã bật", "máy em"
        ))

        is_archive = bool(re.search(r"\b(?:zip|rar|7z|tar|gz|archive|extract|crack)\b", q)) or any(k in q for k in (
            ".zip", ".rar", ".7z", ".tar", ".gz", ".tgz",
            "nén", "giải nén", "mật khẩu",
            "password", "bẻ khóa", "khôi phục"
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
            "nhớ", "ghi nhớ", "lưu lại", "xong", "hoàn thành"
        ))

        is_weather = any(k in q for k in (
            "thời tiết", "thoi tiet", "weather", "nhiệt độ", "độ ẩm", "mưa", "nắng",
            "dự báo", "bão", "không khí", "trời", "nóng", "lạnh", "gió",
            "áp thấp", "mưa rào", "giông", "rét", "ấm", "sương mù",
            "wttr", "a răng", "bựa ni", "bua ni"
        ))

        is_reminder = bool(self._SHORT_REMINDER_RE.search(q)) or any(k in q for k in (
            "đặt lịch", "nhắc nhở", "nhắc anh", "nhắc em", "nhắc tôi", "nhắc mình",
            "báo anh", "báo em", "lịch nhắc", "nhắc việc", "hẹn giờ", "đặt hẹn",
            "nhắc lịch", "lên lịch nhắc", "canh giờ", "xem lịch nhắc", "danh sách nhắc",
            "hủy nhắc", "xóa nhắc", "lịch hẹn nhắc", "hẹn nhắc", "đã hẹn nhắc", "hủy lịch nhắc",
            "dat lich", "nhac nho", "nhac anh", "nhac em", "nhac toi", "nhac minh",
            "bao anh", "bao em", "lich nhac", "nhac viec", "hen gio", "dat hen",
            "nhac lich", "len lich nhac", "canh gio", "xem lich nhac", "danh sach nhac",
            "huy nhac", "xoa nhac", "huy lich nhac",
            "set reminder", "remind me", "reminder", "schedule reminder", "list reminders", "cancel reminder", "timer"
        ))

        is_server_health = bool(self._SHORT_SERVER_HEALTH_RE.search(q)) or any(k in q for k in (
            "sức khỏe server", "sức khỏe hệ thống", "tình trạng server", "tổng quan server",
            "trạng thái service", "kiểm tra service", "khởi động lại service", "xem log",
            "xem log service", "tail log", "báo cáo hệ thống", "kiểm tra container", "sức khỏe máy chủ",
            "tình trạng máy chủ", "tinh trang may chu", "máy chủ hoạt động thế nào",
            "trạng thái container", "trang thai container", "restart container",
            "suc khoe server", "suc khoe he thong", "tinh trang server", "tong quan server",
            "trang thai service", "kiem tra service", "khoi dong lai service", "xem log",
            "xem log service", "bao cao he thong", "kiem tra container", "suc khoe may chu",
            "sức khỏe", "suc khoe", "health", "system health", "service status", "check service",
            "restart service", "tail service logs", "container health", "docker status",
            "bựa ni máy chủ răng", "máy chủ răng", "có đầy đĩa k", "đầy đĩa", "đầy đĩa không",
            "kiểm tra sức khỏe", "kiem tra suc khoe",
            "dịch vụ", "dich vu", "trạng thái dịch vụ", "systemctl",
            "đang active", "active không", "is-active", "service status"
        ))

        is_notes = False
        if not is_media:
            is_notes = bool(self._SHORT_NOTES_RE.search(q)) or any(k in q for k in (
                "ghi chú", "tạo note", "tìm note", "xem note", "danh sách note", "xóa note",
                "sổ tay", "lưu lại thông tin", "lưu thông tin", "ghi nhớ thông tin", "ghi chép",
                "viết note", "tra cứu ghi chú", "note cá nhân", "note lại", "tìm ghi chú", "xóa ghi chú",
                "ghi chu", "tao note", "tim note", "xem note", "danh sach note", "xoa note",
                "so tay", "luu lai thong tin", "luu thong tin", "ghi nho thong tin", "ghi chep",
                "viet note", "tra cuu ghi chu", "note ca nhan", "note lai", "tim ghi chu", "xoa ghi chu",
                "create note", "search notes", "list notes", "delete note", "notepad", "my notes", "take note"
            ))

        is_calc = bool(self._MATH_EXPR_RE.search(q)) or bool(self._SHORT_CALC_RE.search(q)) or bool(re.search(r"\b(?:đổi|doi)\s+\d+", q)) or any(k in q for k in (
            "tính toán", "tính lãi", "lãi suất", "lãi kép", "công thức", "thống kê",
            "chuyển đổi", "đổi đơn vị", "quy đổi", "truy vấn", "cơ sở dữ liệu", "truy vấn sql",
            "bảng postgres", "tính giúp anh", "tính hộ", "tính ", "tinh ",
            "đổi sang", "doi sang", "đổi từ", "doi tu", "quy đổi", "quy doi",
            "tinh toan", "tinh lai", "lai suat", "lai kep", "cong thuc", "thong ke",
            "chuyen doi", "doi don vi", "truy van", "co so du lieu", "truy van sql",
            "bang postgres",
            "calculate", "convert_units", "unit convert", "currency convert", "query database", "select from", "sql query",
            "độ f sang độ c", "kg sang lbs", "độ f", "độ c", "lbs"
        ))

        is_cron = bool(self._SHORT_CRON_RE.search(q)) or any(k in q for k in (
            "tự động", "lên lịch cron", "định kỳ", "hàng ngày", "hàng tuần", "hàng tháng",
            "chạy tự động", "danh sách cron", "xóa cron", "tạo cron", "tác vụ định kỳ", "cron job",
            "tu dong", "len lich cron", "dinh ky", "hang ngay", "hang tuan", "hang thang",
            "chay tu dong", "danh sach cron", "xoa cron", "tao cron", "tac vu dinh ky",
            "cron", "crontab", "cron job", "cronjob", "automation", "create cron", "list cron", "delete cron", "schedule job", "periodic task"
        ))

        is_email = bool(self._EMAIL_ADDRESS_RE.search(q)) or bool(self._SHORT_EMAIL_RE.search(q)) or any(k in q for k in (
            "gửi email", "gửi thư", "hộp thư", "gửi mail cho", "gửi mail",
            "báo cáo tổng hợp", "báo cáo ngày", "báo cáo tuần", "báo cáo tháng", "gửi báo cáo", "email thông báo",
            "tạo báo cáo", "bao cao tong hop",
            "gui email", "gui thu", "hop thu", "gui mail cho", "gui mail",
            "bao cao tong hop", "bao cao ngay", "bao cao tuan", "bao cao thang", "gui bao cao", "email thong bao",
            "send email", "send mail", "mail to", "generate report", "daily report", "weekly report", "monthly report", "smtp"
        ))

        is_network = bool(self._SHORT_NETWORK_RE.search(q)) or any(k in q for k in (
            "ip công khai", "ip ngoài", "ip server", "địa chỉ ip", "kiểm tra mạng",
            "tốc độ mạng", "khởi động lại ngrok", "trạng thái ngrok", "đường truyền", "nhà mạng",
            "ngrok", "tunnel", "link ngrok", "restart lại tunnel", "thông tin mạng",
            "ip cong khai", "ip ngoai", "ip server", "dia chi ip", "kiem tra mang",
            "toc do mang", "khoi dong lai ngrok", "trang thai ngrok", "duong truyen", "nha mang",
            "public ip", "external ip", "network info", "restart ngrok", "ngrok status", "lan ip", "network speed"
        ))

        is_file_manager = (not is_transfer) and (
            bool(self._PATH_PREFIX_RE.search(q)) or bool(self._SHORT_FILE_RE.search(q)) or any(k in q for k in (
                "thư mục", "tệp tin", "đọc file", "xem file", "danh sách file", "liệt kê file", "liệt kê danh sách file",
                "đọc nội dung file", "ghi file", "ghi nội dung", "đổi tên file", "di chuyển file",
                "dung lượng ổ đĩa", "xem dung lượng", "top file lớn", "nặng nhất", "nội dung file",
                "dung lượng thư mục",
                "thu muc", "tep tin", "doc file", "xem file", "danh sach file", "liet ke file",
                "doc noi dung file", "ghi file", "ghi noi dung", "doi ten file", "di chuyen file",
                "dung luong o dia", "xem dung luong", "top file lon", "nang nhat", "noi dung file",
                "list files", "read file", "write file", "move file", "rename file", "disk usage", "file content", "directory tree"
            ))
        )

        is_security = bool(self._SHORT_SECURITY_RE.search(q)) or any(k in q for k in (
            "an ninh", "bao mat", "bảo mật", "tấn công", "tan cong", "attack", "attacker",
            "hacker", "hack", "block ip", "chặn ip", "chan ip", "khóa ip", "khoa ip", "chặn", "block",
            "mở khóa", "mo khoa", "gỡ chặn", "go chan", "bỏ chặn", "bo chan",
            "gỡ chặn ip", "mở khóa ip", "unblock ip", "unblock", "honeypot", "bẫy mật", "ke that bai", "kẻ thất bại",
            "brute force", "bruteforce", "sqli", "port scan", "quet cong", "quét cổng",
            "iptables", "firewall", "tường lửa", "tuong lua", "bị chặn", "bi chan",
            "danh sách chặn", "danh sach chan", "danh sách đen", "blacklist", "whitelist",
            "security report", "báo cáo an ninh", "lịch sử tấn công", "lich su tan cong"
        ))

        is_media_studio = (
            bool(self._SHORT_MEDIA_STUDIO_RE.search(q))
            or any(k in q for k in self._ALL_VIDEO_EDITOR_KEYWORDS)
        )
        is_docs = bool(self._SHORT_DOCS_RE.search(q))
        is_web_extract = bool(self._SHORT_WEB_DOWNLOAD_ARTICLE_RE.search(q))
        is_system_root = bool(self._SHORT_SYSTEM_ROOT_RE.search(q))
        is_goal = bool(self._SHORT_GOAL_RE.search(q)) or any(k in q for k in (
            "mục tiêu", "muc tieu", "goal", "goals", "autonomous", "tự hành", "tu hanh",
            "lập kế hoạch", "lap ke hoach", "tiến trình tự động", "tien trinh tu dong",
            "theo dõi tự động", "theo doi tu dong", "kế hoạch tự động", "ke hoach tu dong",
            "danh sách mục tiêu", "danh sach muc tieu", "hủy mục tiêu", "huy muc tieu",
            "xóa mục tiêu", "xoa muc tieu", "tạo mục tiêu", "tao muc tieu",
            "đặt mục tiêu", "dat muc tieu", "cancel goal", "list goals", "create goal",
            "autonomous goal", "bám sát", "bam sat", "theo dõi và",
            "task tự động", "task tu dong", "các task tự động", "cac task tu dong",
            "hủy task tự động", "huy task tu dong", "xóa task tự động", "xoa task tu dong",
            "dừng task tự động", "dung task tu dong", "đang theo dõi những gì", "dang theo doi nhung gi",
            "đang theo dõi gì", "dang theo doi gi"
        ))

        if is_media_studio:
            selected.update(self._TOOL_CLUSTER_MEDIA)
        elif is_media:
            if is_audio:
                selected.update(self._TOOL_CLUSTER_MEDIA)
            else:
                selected.add("download_media_video")
                selected.add("run_command")

        if is_docs:
            selected.update(self._TOOL_CLUSTER_DOCS)

        if is_web_extract:
            selected.update(self._TOOL_CLUSTER_WEB)

        if is_system_root:
            selected.update(self._TOOL_CLUSTER_SYSTEM)

        if is_transfer:
            selected.update(self._TOOL_CLUSTER_TRANSFER)

        if is_weather:
            selected.update(self._TOOL_CLUSTER_WEATHER)

        if is_reminder:
            selected.update(self._TOOL_CLUSTER_REMINDER)

        if is_security:
            selected.update(self._TOOL_CLUSTER_SECURITY)

        if is_server_health:
            selected.update(self._TOOL_CLUSTER_SERVER_HEALTH)
        elif is_server:
            selected.update(self._TOOL_CLUSTER_SERVER)

        if is_notes:
            selected.update(self._TOOL_CLUSTER_NOTES)

        if is_calc:
            selected.update(self._TOOL_CLUSTER_CALCULATOR)

        if is_cron:
            selected.update(self._TOOL_CLUSTER_CRON)

        if is_email:
            selected.update(self._TOOL_CLUSTER_EMAIL)

        if is_network:
            selected.update(self._TOOL_CLUSTER_NETWORK)

        if is_file_manager:
            selected.update(self._TOOL_CLUSTER_FILE_MANAGER)

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

        if is_goal:
            selected.update(self._TOOL_CLUSTER_GOALS)

        if not selected:
            selected.update(self._TOOL_CLUSTER_CORE)

        # Priority Pruning: Enforce strict token budget (max 6 tools when heavy cluster present, else max 8)
        is_facebook = is_fb
        has_heavy_cluster = (
            is_archive
            or is_facebook
            or is_media_studio
            or bool(
                selected
                & (
                    (self._TOOL_CLUSTER_ARCHIVE - {"run_command"})
                    | self._TOOL_CLUSTER_FACEBOOK
                    | (self._TOOL_CLUSTER_MEDIA - {"download_media_video", "download_media_audio", "run_command"})
                )
            )
        )
        max_tools = 6 if has_heavy_cluster else 8

        if len(selected) > max_tools:
            is_rename_or_move = any(k in q for k in ("đổi tên", "doi ten", "move", "rename", "di chuyển", "di chuyen"))
            is_write = any(k in q for k in ("ghi file", "ghi noi dung", "ghi nội dung", "write file"))
            is_disk = any(k in q for k in ("dung lượng", "dung luong", "disk usage", "du -sh", "nặng nhất", "nang nhat"))
            is_unblock = any(k in q for k in ("gỡ chặn", "go chan", "mở khóa", "mo khoa", "unblock", "bỏ chặn"))
            is_block = any(k in q for k in ("chặn ip", "chan ip", "block ip", "khóa ip", "khoa ip", "chặn", "block"))
            is_honeypot = any(k in q for k in ("honeypot", "bẫy", "kẻ thất bại", "ke that bai", "credentials", "mật khẩu hacker"))
            is_history = any(k in q for k in ("lịch sử", "lich su", "history", "các vụ tấn công", "nhật ký tấn công"))
            is_list_blk = any(k in q for k in ("danh sách chặn", "danh sach chan", "ai đang bị chặn", "ip bị chặn", "list block", "đang bị chặn"))
            is_restart = any(k in q for k in ("restart", "khởi động lại", "khoi dong lai", "reboot service", "restart service", "restart container"))

            # R1 - R4 Specific intent flags
            is_edit_vid = any(k in q for k in ("cắt video", "cat video", "cắt clip", "cat clip", "edit video", "cắt đoạn video", "cat doan video"))
            is_comp_vid = any(k in q for k in ("nén video", "nen video", "compress video", "giảm dung lượng video", "giam dung luong video"))
            is_conv_vid = any(k in q for k in ("đổi đuôi video", "doi duoi video", "convert video", "chuyển định dạng video", "mp4 sang", "mkv sang", "tạo gif", "tao gif"))
            is_conv_aud = any(k in q for k in ("đổi đuôi nhạc", "doi duoi nhac", "convert audio", "flac sang", "wav sang", "m4a sang", "320k"))
            is_trim_aud = any(k in q for k in ("cắt nhạc", "cat nhac", "cắt audio", "cat audio", "nhạc chuông", "nhac chuong", "trim audio"))
            is_norm_aud = any(k in q for k in ("chuẩn hóa âm lượng", "chuan hoa am luong", "cân bằng âm lượng", "can bang am luong", "loudnorm", "ebu r128"))
            is_img_proc = any(k in q for k in ("resize ảnh", "resize anh", "nén ảnh", "nen anh", "đổi kích thước ảnh", "doi kich thuoc anh", "doi kich thuoc", "đổi kích thước", "chuyển ảnh sang", "chuyen anh sang", "webp", "png sang jpg", "jpg sang png"))
            is_qr_gen   = any(k in q for k in ("mã qr", "ma qr", "qr code", "tạo qr", "tao qr", "sinh qr", "quet qr", "quét qr"))
            is_meta_chk = any(k in q for k in ("metadata", "thông tin video", "thông tin audio", "ffprobe", "exif", "codec"))

            is_mrg_pdf  = any(k in q for k in ("gộp pdf", "gop pdf", "merge pdf", "ghép pdf", "ghep pdf", "nối pdf", "noi pdf", "gộp các file pdf", "gop cac file pdf", "gộp file pdf", "gop file pdf")) or bool(re.search(r"\b(?:gộp|gop|ghép|ghep|nối|noi|merge)\s+.*pdf\b", q))
            is_splt_pdf = any(k in q for k in ("tách pdf", "tach pdf", "split pdf", "cắt trang pdf", "trích trang pdf", "tách các trang", "tach cac trang", "tách trang", "tach trang", "tach file pdf", "tách file pdf")) or bool(re.search(r"\b(?:tách|tach|split|cắt trang|cat trang|trích trang|trich trang)\s+.*pdf\b", q))
            is_ext_doc  = any(k in q for k in ("đọc pdf", "doc pdf", "trích xuất văn bản", "trich xuat van ban", "extract text", "đọc word", "doc word", "đọc docx", "doc docx", "doc file docx", "đọc file docx", "nội dung file", "noi dung file", "báo cáo pdf", "bao cao pdf", "file báo cáo", "file bao cao")) or bool(re.search(r"\b(?:đọc|doc|xem|trích|trich|nội dung|noi dung)\s+.*(?:pdf|docx|tài liệu|tai lieu|văn bản|van ban)\b", q))
            has_service_kw = any(sv in q for sv in ("dịch vụ", "dich vu", "service"))
            is_trans    = any(k in q for k in ("dịch văn bản", "dich van ban", "dịch sang", "dich sang", "nghĩa là gì", "nghia la gi", "translate")) or (
                not has_service_kw and any(k in q for k in ("dịch", "dich"))
            ) or bool(re.search(r"\b(?:dịch|dich|translate)(?!\s+(?:vụ|vu))\s+.*(?:sang|tiếng|tieng|văn bản|van ban|tài liệu|tai lieu|text)\b", q))

            is_dl_file  = any(k in q for k in ("tải tệp", "tai tep", "tải file trực tiếp", "download direct", "tải link", "tải file zip", "tải file iso", "download file", "tải file"))
            is_ext_art  = any(k in q for k in ("bóc tách bài viết", "boc tach bai viet", "đọc bài báo", "doc bai bao", "bài báo", "bai bao", "đọc báo", "doc bao", "trích xuất bài viết", "extract article", "nội dung bài báo", "tóm tắt bài báo", "tóm tắt bài viết"))

            is_sys_scr  = any(k in q for k in ("chạy script", "chay script", "execute script", "script bash", "script python", "chạy code python", "chạy kịch bản", "chay kich ban", "kịch bản bash", "kich ban bash", "kịch bản python", "kich ban python"))
            is_dck_mgmt = any(k in q for k in ("quản lý docker", "docker restart", "restart container", "khởi động lại container", "khoi dong lai container", "dừng container", "stop container", "bật container", "start container", "docker prune", "xóa rác docker", "container docker"))
            is_sys_opt  = any(k in q for k in ("tối ưu hệ thống", "toi uu he thong", "dọn dẹp hệ thống", "giải phóng ram", "giai phong ram", "drop_caches", "tối ưu máy chủ", "tối ưu server", "dọn ram", "don ram", "dọn dẹp ram", "don dep ram"))

            # Milestone 2 Video Editor intent flags (DRY synced with class constants)
            is_rm_txt   = any(k in q for k in self._KW_REMOVE_TEXT)
            is_add_sub  = any(k in q for k in self._KW_ADD_SUBTITLE)
            is_clr_grd  = any(k in q for k in self._KW_COLOR_GRADE)
            is_stab_vid = any(k in q for k in self._KW_STABILIZE)
            is_concat   = any(k in q for k in self._KW_CONCAT)
            is_ext_frm  = any(k in q for k in self._KW_EXTRACT_FRAMES)
            is_rm_wm    = any(k in q for k in self._KW_REMOVE_WATERMARK)
            is_enh_vid  = any(k in q for k in self._KW_ENHANCE_VIDEO)
            is_gen_thm  = any(k in q for k in self._KW_GENERATE_THUMBNAIL)

            # R4 Conversational Goals intent flags
            is_goal_list = any(k in q for k in (
                "danh sách mục tiêu", "danh sach muc tieu", "list goals", "danh sách goal", "danh sach goal",
                "xem mục tiêu", "xem muc tieu", "các mục tiêu", "cac muc tieu", "mục tiêu đang chạy", "muc tieu dang chay",
                "tiến trình goal", "tien trinh goal", "các task tự động", "cac task tu dong",
                "danh sách task", "danh sach task", "đang theo dõi những gì", "dang theo doi nhung gi",
                "đang theo dõi gì", "dang theo doi gi"
            ))
            is_goal_cancel = any(k in q for k in (
                "hủy mục tiêu", "huy muc tieu", "xóa mục tiêu", "xoa muc tieu", "cancel goal",
                "dừng mục tiêu", "dung muc tieu", "hủy goal", "huy goal", "dừng goal", "dung goal",
                "xóa goal", "xoa goal", "hủy task tự động", "huy task tu dong", "hủy task", "huy task",
                "xóa task tự động", "xoa task tu dong", "xóa task", "xoa task",
                "dừng task tự động", "dung task tu dong", "dừng task", "dung task"
            ))

            priority_order: List[str] = [
                # 1. Specialized Intent Boosters (Mỗi intent đưa các công cụ cốt lõi nhất lên đỉnh)
                *(["list_autonomous_goals"] if (is_goal and is_goal_list) else []),
                *(["cancel_autonomous_goal"] if (is_goal and is_goal_cancel) else []),
                *(["create_autonomous_goal", "list_autonomous_goals", "cancel_autonomous_goal"] if is_goal else []),
                *(["remove_text_from_video"] if is_rm_txt else []),
                *(["add_subtitle_to_video"] if is_add_sub else []),
                *(["apply_color_grade"] if is_clr_grd else []),
                *(["stabilize_video"] if is_stab_vid else []),
                *(["concatenate_videos"] if is_concat else []),
                *(["extract_frames"] if is_ext_frm else []),
                *(["remove_watermark_region"] if is_rm_wm else []),
                *(["enhance_video_quality"] if is_enh_vid else []),
                *(["generate_video_thumbnail"] if is_gen_thm else []),
                *(["edit_video_clip"] if is_edit_vid else []),
                *(["compress_video"] if is_comp_vid else []),
                *(["convert_video_format"] if is_conv_vid else []),
                *(["convert_audio_format"] if is_conv_aud else []),
                *(["trim_audio_clip"] if is_trim_aud else []),
                *(["normalize_audio_volume"] if is_norm_aud else []),
                *(["convert_and_resize_image"] if is_img_proc else []),
                *(["generate_custom_qr"] if is_qr_gen else []),
                *(["inspect_media_metadata"] if is_meta_chk else []),
                *(["merge_pdf_documents"] if is_mrg_pdf else []),
                *(["split_pdf_document"] if is_splt_pdf else []),
                *(["extract_document_text"] if is_ext_doc else []),
                *(["translate_text"] if is_trans else []),
                *(["download_direct_file"] if is_dl_file else []),
                *(["extract_clean_web_article"] if is_ext_art else []),
                *(["execute_system_script"] if is_sys_scr else []),
                *(["manage_docker_containers"] if is_dck_mgmt else []),
                *(["optimize_system_resources"] if is_sys_opt else []),

                *(["unblock_ip"] if (is_security and is_unblock) else []),
                *(["block_ip"] if (is_security and is_block and not is_unblock) else []),
                *(["get_honeypot_log"] if (is_security and is_honeypot) else []),
                *(["get_attack_history"] if (is_security and is_history) else []),
                *(["list_blocked_ips"] if (is_security and is_list_blk) else []),
                *(["get_security_report", "list_blocked_ips"] if is_security else []),
                *(["create_file_transfer_portal"] if is_transfer else []),
                *(["schedule_reminder", "list_scheduled_reminders"] if is_reminder else []),
                *(["calculate", "convert_units"] if is_calc else []),
                *(["restart_service"] if is_restart else []),
                *(["get_system_health_report", "check_service_status", "restart_service"] if is_server_health else []),
                *(["send_email", "generate_report"] if is_email else []),
                *(["get_ngrok_status", "get_network_info"] if is_network else []),
                *(["create_note", "search_notes"] if is_notes else []),
                *(["create_cron_job", "list_cron_jobs"] if is_cron else []),
                *(["recover_archive_password", "extract_archive_file"] if (is_archive and any(k in q for k in ("mật khẩu", "password", "pass", "crack", "bẻ khóa", "khôi phục"))) else ["extract_archive_file", "read_archive_file"] if is_archive else []),
                *(["move_or_rename_file"] if (is_file_manager and is_rename_or_move) else ["write_file_content"] if (is_file_manager and is_write) else ["get_disk_usage"] if (is_file_manager and is_disk) else ["list_files", "read_file_content"] if is_file_manager else []),
                *(["download_media_video"] if is_media and not is_audio else []),
                *(["download_media_audio"] if is_audio else []),

                # 2. Universal Lifesaver (Fallback an toàn cho mọi lệnh hệ thống)
                "run_command",

                # 3. Primary Secondary Operations (Công cụ bổ trợ thường dùng)
                "get_security_report",
                "list_blocked_ips",
                "get_system_health_report",
                "check_service_status",
                "calculate",
                "schedule_reminder",
                "send_email",
                "get_ngrok_status",
                "list_files",
                "create_note",
                "create_cron_job",
                "download_media_video",
                "download_media_audio",
                "get_weather",

                # 4. M6 Secondary Operations & Conversions
                "edit_video_clip",
                "compress_video",
                "convert_video_format",
                "convert_audio_format",
                "trim_audio_clip",
                "normalize_audio_volume",
                "convert_and_resize_image",
                "generate_custom_qr",
                "merge_pdf_documents",
                "split_pdf_document",
                "extract_document_text",
                "translate_text",
                "inspect_media_metadata",
                "download_direct_file",
                "extract_clean_web_article",
                "manage_docker_containers",
                "optimize_system_resources",
                "execute_system_script",

                # 5. Diagnostic & Passive Utilities
                "block_ip",
                "unblock_ip",
                "get_honeypot_log",
                "get_attack_history",
                "restart_service",
                "tail_service_logs",
                "read_file_content",
                "write_file_content",
                "move_or_rename_file",
                "get_disk_usage",
                "search_notes",
                "list_notes",
                "delete_note",
                "query_database",
                "convert_units",
                "list_cron_jobs",
                "delete_cron_job",
                "restart_ngrok_tunnel",
                "get_network_info",
                "generate_report",
                "cancel_reminder",
                "list_scheduled_reminders",
                "get_server_location",
                "get_server_active_sessions",
                "server_capture_screenshot",
                "remember_for_later",
                "complete_task",

                # 6. Archive Heavy Group
                "read_archive_file",
                "extract_archive_file",
                "recover_archive_password",

                # 7. Facebook & Social Group
                "facebook_get_messages",
                "facebook_send_reply",
                "facebook_capture_screenshot",
                "messenger_list_groups",
                "messenger_get_group_members",
                "facebook_view_profile",
                "get_appointments",

                # 8. Browser Navigation & Automation Group
                "browser_navigate",
                "browser_search_google",
                "browser_take_screenshot",
                "browser_get_text",
                "browser_click",
                "browser_type",
                "browser_scroll",
                "browser_press_key",
                "browser_hover",
                "browser_select_option",
                "browser_execute_js",
                "browser_fill_form",
                "browser_wait_for",
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
        force_all: bool = False,
        last_user_query: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        effective_query = last_user_query if last_user_query is not None else query
        excluded = set(excluded_tools or set())
        scoped_allowed: Optional[Set[str]] = None
        if not force_all and (effective_query or history):
            scoped_allowed = self._resolve_scoped_tool_names(query=effective_query, history=history)
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
                    "description": "Thực thi trực tiếp lệnh shell toàn quyền (unrestricted root/sudo) trên máy chủ qua SSH (CPU, RAM, Disk, Docker, Package Management, Logs) với vi mạch an toàn tủy sống bảo vệ.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "Lệnh bash (ví dụ: 'free -h', 'docker ps', 'df -h /', 'apt update').",
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
                    "description": "Tải video chất lượng phòng thu (ưu tiên 4K, 2K, 1080p và 60fps mượt mà) từ hơn 20+ nền tảng mạng xã hội (YouTube, YouTube Shorts, TikTok, Douyin, Facebook, Facebook Reels, Instagram, Threads, Twitter/X, Twitch, Vimeo, Dailymotion, CapCut, Xiaohongshu, Weibo, Bilibili, Reddit, Pinterest, Kuaishou, Lemon8, Likee, Bluesky, Rumble, Streamable, Loom...) hoặc bất kỳ web video nào. Tự động hỗ trợ mô hình Phân phối kép (Video <= 50MB gửi Telegram; Video > 50MB chia phần lossless kèm link tải trực tiếp tốc độ cao LAN/WAN).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "URL video/media cần tải (hỗ trợ 20+ nền tảng: YouTube, YouTube Shorts, TikTok, Douyin, Facebook, Facebook Reels, Instagram, Twitter/X, Threads, Twitch, Vimeo, Dailymotion, CapCut, Xiaohongshu, Weibo, Bilibili, Reddit, Pinterest, Kuaishou, Lemon8, Likee, Bluesky, Rumble, Streamable, Loom hoặc bất kỳ liên kết video nào).",
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
                    "description": "Tải MP3/audio Studio Master (320kbps) từ TikTok, YouTube, SoundCloud, Facebook, Instagram, Reddit... gửi Telegram.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "URL video/audio cần tải hoặc tách nhạc (TikTok, YouTube, SoundCloud, Facebook, Instagram, Reddit...).",
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
                    "name": "create_file_transfer_portal",
                    "description": "Tạo cổng truyền file siêu tốc an toàn (LAN Gigabit/WAN Internet) giữa máy tính, điện thoại, iPad và máy chủ. Tự động sinh mã QR Code gửi Telegram.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_name": {
                                "type": "string",
                                "description": "Tên file hoặc đường dẫn tệp muốn chuyển hoặc nhận diện (nếu có).",
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["upload", "download"],
                                "default": "upload",
                                "description": "'upload' khi người dùng muốn chuyển/tải file từ thiết bị lên để chia sẻ; 'download' khi người dùng muốn nhận/tải file sẵn có.",
                            },
                            "one_time": {
                                "type": "boolean",
                                "default": False,
                                "description": "True nếu muốn liên kết tự hủy sau 1 lần tải thành công.",
                            },
                        },
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
            # ── R1: Smart Calendar & Scheduler ──
            {
                "type": "function",
                "function": {
                    "name": "schedule_reminder",
                    "description": "Đặt lịch nhắc nhở tự động gửi thông báo qua Telegram sau một khoảng thời gian (phút), hỗ trợ tần suất lặp lại (daily, weekly, none).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "message": {
                                "type": "string",
                                "description": "Nội dung lời nhắc cần gửi cho anh Mạnh (ví dụ: 'Uống thuốc', 'Họp giao ban sprint').",
                            },
                            "delay_minutes": {
                                "type": "integer",
                                "description": "Số phút chờ trước khi kích hoạt thông báo nhắc việc (phải là số nguyên > 0).",
                            },
                            "repeat": {
                                "type": "string",
                                "enum": ["none", "daily", "weekly"],
                                "default": "none",
                                "description": "Tần suất lặp lại nhắc nhở: 'none' (chỉ nhắc 1 lần), 'daily' (lặp hàng ngày), hoặc 'weekly' (lặp hàng tuần).",
                            },
                        },
                        "required": ["message", "delay_minutes"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_scheduled_reminders",
                    "description": "Liệt kê tất cả các lịch nhắc nhở công việc đang ở trạng thái chờ kích hoạt (pending) trong hệ thống.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "cancel_reminder",
                    "description": "Hủy bỏ một lịch nhắc nhở đang chờ kích hoạt bằng mã định danh ID của nhắc nhở (Tier 2 Reversible).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "reminder_id": {
                                "type": "integer",
                                "description": "Mã ID của lịch nhắc nhở cần hủy (ví dụ: 12, 1005).",
                            },
                        },
                        "required": ["reminder_id"],
                    },
                },
            },

            # ── R2: Autonomous Health Monitor ──
            {
                "type": "function",
                "function": {
                    "name": "get_system_health_report",
                    "description": "Thu thập báo cáo tổng hợp sức khỏe máy chủ 1-shot toàn diện 5 chiều: tải CPU, bộ nhớ RAM, dung lượng ổ đĩa Disk, trạng thái Docker containers, và các cổng mạng đang mở (ss -tuln).",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "check_service_status",
                    "description": "Kiểm tra chi tiết trạng thái hoạt động của một dịch vụ Systemd hoặc Docker container trên máy chủ (active, exited, restart count, uptime).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "service_name": {
                                "type": "string",
                                "description": "Tên container Docker (ví dụ: 'dashboard_ai_agent', 'postgres') hoặc dịch vụ systemd (ví dụ: 'nginx', 'ssh').",
                            },
                        },
                        "required": ["service_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "restart_service",
                    "description": "Khởi động lại một Docker container hoặc Systemd service (Tier 2 Reversible). Yêu cầu mã xác nhận an toàn confirm='RESTART_CONFIRMED' khi restart các dịch vụ production trọng yếu.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "service_name": {
                                "type": "string",
                                "description": "Tên dịch vụ hoặc container cần khởi động lại.",
                            },
                            "confirm": {
                                "type": "string",
                                "description": "Mã xác nhận an toàn ('RESTART_CONFIRMED') khi khởi động lại các container/service production.",
                            },
                        },
                        "required": ["service_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "tail_service_logs",
                    "description": "Đọc các dòng nhật ký (logs) gần nhất của dịch vụ/container, tự động bóc tách phân tích lỗi (error/exception) và tóm tắt tình trạng.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "service_name": {
                                "type": "string",
                                "description": "Tên Docker container hoặc Systemd service cần xem logs.",
                            },
                            "lines": {
                                "type": "integer",
                                "default": 50,
                                "description": "Số dòng nhật ký cuối cần đọc và phân tích (mặc định 50 dòng, tối đa 500).",
                            },
                        },
                        "required": ["service_name"],
                    },
                },
            },

            # ── R3: Personal Notes & Knowledge Base ──
            {
                "type": "function",
                "function": {
                    "name": "create_note",
                    "description": "Tạo hoặc cập nhật ghi chú cá nhân lưu trữ dạng Markdown với YAML frontmatter trên máy chủ tại /home/kirito/quan_ly_server/data/notes/.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "title": {
                                "type": "string",
                                "description": "Tiêu đề ghi chú cá nhân.",
                            },
                            "content": {
                                "type": "string",
                                "description": "Nội dung chi tiết của ghi chú (hỗ trợ đầy đủ định dạng Markdown).",
                            },
                            "tags": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Danh sách các nhãn/thẻ phân loại (ví dụ: ['cong_viec', 'server', 'y_tuong']).",
                            },
                        },
                        "required": ["title", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_notes",
                    "description": "Tìm kiếm toàn văn (full-text) trong tiêu đề và nội dung của kho ghi chú cá nhân, hỗ trợ lọc theo thẻ phân loại.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Từ khóa tìm kiếm nội dung ghi chú.",
                            },
                            "tags": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Danh sách nhãn/thẻ lọc kết quả tìm kiếm.",
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_notes",
                    "description": "Liệt kê danh sách các ghi chú cá nhân hiện có trên hệ thống, kèm metadata và có thể lọc theo một thẻ (tag) cụ thể.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "tag": {
                                "type": "string",
                                "description": "Nhãn/thẻ cần lọc danh sách (bỏ trống để liệt kê toàn bộ ghi chú).",
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "delete_note",
                    "description": "Xóa an toàn một ghi chú cá nhân bằng cách chuyển vào thư mục thùng rác .trash/ (Tier 2 Reversible).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "note_id": {
                                "type": "string",
                                "description": "Mã ID của ghi chú cần xóa (ví dụ: 'hop_giao_ban_20260926_123456_abcd').",
                            },
                        },
                        "required": ["note_id"],
                    },
                },
            },

            # ── R4: Calculator & Data Analytics ──
            {
                "type": "function",
                "function": {
                    "name": "calculate",
                    "description": "Tính toán an toàn biểu thức toán học, tài chính (lãi kép), thống kê (mean, median, stdev) hoặc hàm lượng giác qua cây cú pháp AST (chống tiêm mã độc).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "expression": {
                                "type": "string",
                                "description": "Biểu thức toán học cần tính (ví dụ: 'sqrt(144) + 2**8', 'compound_interest(100000000, 0.07, 12, 5)', 'mean([4, 8, 15, 16, 23, 42])').",
                            },
                        },
                        "required": ["expression"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "query_database",
                    "description": "Thực thi truy vấn SQL chỉ đọc (chỉ cho phép SELECT và EXPLAIN) trên cơ sở dữ liệu PostgreSQL của server và trả về kết quả dạng bảng ASCII định dạng cho Telegram. Tuyệt đối ngăn chặn mọi thao tác sửa đổi DML/DDL.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "sql_query": {
                                "type": "string",
                                "description": "Câu lệnh SQL SELECT hoặc EXPLAIN cần thực thi (ví dụ: 'SELECT id, username, email FROM users LIMIT 10;').",
                            },
                            "database": {
                                "type": "string",
                                "default": "postgres",
                                "description": "Tên cơ sở dữ liệu truy vấn (mặc định 'postgres').",
                            },
                        },
                        "required": ["sql_query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "convert_units",
                    "description": "Chuyển đổi đại lượng giữa các đơn vị đo lường (nhiệt độ C/F/K, khối lượng kg/g/lb/oz/tấn, chiều dài km/m/cm/mm/mile/inch, tốc độ m/s/kmh/mph, dung lượng byte/KB/MB/GB/TB, tiền tệ USD/VND/EUR/GBP/JPY).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "value": {
                                "type": "number",
                                "description": "Số lượng giá trị cần chuyển đổi.",
                            },
                            "from_unit": {
                                "type": "string",
                                "description": "Đơn vị gốc (ví dụ: 'c', 'kg', 'km', 'usd', 'mb').",
                            },
                            "to_unit": {
                                "type": "string",
                                "description": "Đơn vị đích muốn chuyển đổi sang (ví dụ: 'f', 'lb', 'mile', 'vnd', 'gb').",
                            },
                        },
                        "required": ["value", "from_unit", "to_unit"],
                    },
                },
            },

            # ── R5: Cron Automation ──
            {
                "type": "function",
                "function": {
                    "name": "create_cron_job",
                    "description": "Tạo lịch chạy định kỳ cron job mới trên máy chủ với cú pháp cron chuẩn 5 trường và lệnh bash thực thi an toàn (Tier 2 Reversible).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Tên định danh duy nhất của cron job (chỉ chứa chữ cái, số, gạch dưới, gạch ngang).",
                            },
                            "schedule": {
                                "type": "string",
                                "description": "Biểu thức cron chuẩn 5 trường (ví dụ: '0 2 * * *' chạy 2h sáng mỗi ngày, '*/15 * * * *' mỗi 15 phút).",
                            },
                            "command": {
                                "type": "string",
                                "description": "Lệnh bash shell cần thực thi khi kích hoạt.",
                            },
                            "description": {
                                "type": "string",
                                "default": "",
                                "description": "Mô tả mục đích hoạt động của cron job.",
                            },
                        },
                        "required": ["name", "schedule", "command"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_cron_jobs",
                    "description": "Liệt kê tất cả các cron job đang hoạt động trên hệ thống (cả job do AI Agent quản lý lẫn job crontab hệ thống).",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "delete_cron_job",
                    "description": "Xóa một cron job khỏi hệ thống theo tên định danh (Tier 2 Reversible). Bắt buộc cung cấp mã xác nhận confirm='DELETE_CONFIRMED'.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Tên định danh của cron job cần xóa.",
                            },
                            "confirm": {
                                "type": "string",
                                "description": "Mã xác nhận an toàn bắt buộc: 'DELETE_CONFIRMED'.",
                            },
                        },
                        "required": ["name"],
                    },
                },
            },

            # ── R6: Email & Notification ──
            {
                "type": "function",
                "function": {
                    "name": "send_email",
                    "description": "Gửi email thông báo qua giao thức SMTP (văn bản thuần hoặc HTML) kèm tùy chọn đính kèm tệp an toàn (Tier 2 Reversible).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "to": {
                                "type": "string",
                                "description": "Địa chỉ email người nhận (ví dụ: 'admin@example.com').",
                            },
                            "subject": {
                                "type": "string",
                                "description": "Tiêu đề thư email.",
                            },
                            "body": {
                                "type": "string",
                                "description": "Nội dung thư (hỗ trợ văn bản thuần hoặc HTML).",
                            },
                            "attachments": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Danh sách đường dẫn các tệp cần đính kèm an toàn.",
                            },
                        },
                        "required": ["to", "subject", "body"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "generate_report",
                    "description": "Tự động sinh báo cáo tổng hợp sức khỏe máy chủ theo chu kỳ thời gian (hôm nay, tuần, tháng), trả về văn bản Markdown và tùy chọn gửi qua email.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "report_type": {
                                "type": "string",
                                "description": "Loại báo cáo cần tạo (ví dụ: 'health', 'system', 'summary').",
                            },
                            "period": {
                                "type": "string",
                                "enum": ["today", "week", "month"],
                                "default": "today",
                                "description": "Chu kỳ dữ liệu: 'today' (hôm nay), 'week' (tuần này), 'month' (tháng này).",
                            },
                            "send_to_email": {
                                "type": "string",
                                "description": "Địa chỉ email nhận báo cáo nếu muốn tự động gửi đi sau khi tạo.",
                            },
                        },
                        "required": ["report_type"],
                    },
                },
            },

            # ── R7: Network Management ──
            {
                "type": "function",
                "function": {
                    "name": "get_ngrok_status",
                    "description": "Kiểm tra trạng thái hoạt động của Ngrok, quét các cổng API nội bộ (4040-4044) để lấy danh sách các tunnel công khai đang mở, URL công khai và số kết nối.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "restart_ngrok_tunnel",
                    "description": "Khởi động lại tiến trình Ngrok tunnel trên máy chủ để nhận URL công khai mới (Tier 2 Reversible). Yêu cầu mã xác nhận confirm='RESTART_CONFIRMED'.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "tunnel_name": {
                                "type": "string",
                                "description": "Tên tunnel cụ thể cần khởi động lại (để trống nếu muốn khởi động lại toàn bộ dịch vụ Ngrok).",
                            },
                            "confirm": {
                                "type": "string",
                                "description": "Mã xác nhận an toàn bắt buộc: 'RESTART_CONFIRMED'.",
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_network_info",
                    "description": "Lấy thông tin mạng toàn diện của máy chủ: IP mạng nội bộ (LAN), IP công khai (Public IP), nhà mạng ISP, quốc gia, và số lượng kết nối TCP đang mở.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },

            # ── R8: File Server Manager ──
            {
                "type": "function",
                "function": {
                    "name": "list_files",
                    "description": "Liệt kê danh sách tệp và thư mục tại đường dẫn chỉ định với metadata chi tiết (loại, dung lượng, thời gian chỉnh sửa), hỗ trợ lọc mẫu glob và sắp xếp.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "default": "/home/kirito",
                                "description": "Đường dẫn thư mục cần xem (mặc định '/home/kirito').",
                            },
                            "pattern": {
                                "type": "string",
                                "description": "Mẫu glob để lọc tệp (ví dụ: '*.py', '*.json', '*.log').",
                            },
                            "sort_by": {
                                "type": "string",
                                "enum": ["name", "size", "date"],
                                "default": "name",
                                "description": "Tiêu chí sắp xếp: 'name' (tên), 'size' (kích thước), 'date' (ngày sửa).",
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_file_content",
                    "description": "Đọc nội dung tệp văn bản thuần (giới hạn tối đa 2000 ký tự an toàn, từ chối đọc tệp nhị phân binary và các tệp nhạy cảm).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Đường dẫn tệp văn bản cần đọc.",
                            },
                            "lines": {
                                "type": "integer",
                                "description": "Số dòng đầu tiên cần đọc (bỏ trống để đọc theo giới hạn ký tự).",
                            },
                        },
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "write_file_content",
                    "description": "Ghi nội dung văn bản vào tệp trên máy chủ (Tier 2 Reversible). Giới hạn an toàn nghiêm ngặt chỉ cho phép ghi bên trong /home/kirito/ và /tmp/, chặn ghi tệp nhạy cảm.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Đường dẫn tệp cần ghi (phải nằm trong /home/kirito/ hoặc /tmp/).",
                            },
                            "content": {
                                "type": "string",
                                "description": "Nội dung văn bản cần ghi.",
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["overwrite", "append"],
                                "default": "overwrite",
                                "description": "Chế độ ghi: 'overwrite' (ghi đè toàn bộ) hoặc 'append' (nối tiếp vào cuối tệp).",
                            },
                        },
                        "required": ["path", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "move_or_rename_file",
                    "description": "Di chuyển hoặc đổi tên tệp/thư mục trong ranh giới an toàn cho phép (/home/kirito/ và /tmp/) (Tier 2 Reversible).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "src": {
                                "type": "string",
                                "description": "Đường dẫn tệp hoặc thư mục nguồn.",
                            },
                            "dst": {
                                "type": "string",
                                "description": "Đường dẫn tệp hoặc thư mục đích mới.",
                            },
                        },
                        "required": ["src", "dst"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_disk_usage",
                    "description": "Phân tích dung lượng lưu trữ của thư mục hoặc phân vùng ổ đĩa (sử dụng du -sh) và trích xuất top 10 mục (tệp/thư mục con) chiếm dung lượng lớn nhất.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "default": "/",
                                "description": "Đường dẫn thư mục hoặc phân vùng ổ đĩa cần phân tích dung lượng (mặc định '/').",
                            },
                        },
                    },
                },
            },

            # ── Milestone 3: Autonomous Security Guardian Tools ──
            {
                "type": "function",
                "function": {
                    "name": "get_security_report",
                    "description": "Báo cáo tổng hợp tình trạng an ninh máy chủ real-time (threat level, số IP đang bị chặn, thống kê sự kiện tấn công 24h qua, top IP nguy hiểm).",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_blocked_ips",
                    "description": "Liệt kê danh sách các địa chỉ IP đang bị chặn trên tường lửa máy chủ kèm lý do, thời điểm chặn và thời gian còn lại (TTL).",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_honeypot_log",
                    "description": "Truy xuất danh sách credentials (tài khoản/mật khẩu) và probes mà kẻ tấn công đã thử trên bẫy Honeypot SSH 2222 và Telnet 23 'Kẻ thất bại'.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "limit": {
                                "type": "integer",
                                "description": "Số lượng bản ghi tối đa muốn lấy (mặc định: 50, tối đa: 200).",
                                "default": 50,
                            },
                            "service": {
                                "type": "string",
                                "enum": ["all", "ssh", "telnet"],
                                "description": "Lọc theo loại bẫy: 'all' (tất cả), 'ssh' (cổng 2222), hoặc 'telnet' (cổng 23). Mặc định là 'all'.",
                                "default": "all",
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_attack_history",
                    "description": "Tra cứu lịch sử các vụ tấn công mạng gần nhất được phát hiện bởi Security Guardian (SSH brute force, SQLi, XSS, Path Traversal, Port Scan, DDoS...).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "limit": {
                                "type": "integer",
                                "description": "Số sự kiện tối đa cần tra cứu (mặc định: 50, tối đa: 200).",
                                "default": 50,
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "block_ip",
                    "description": "Chủ động chặn một địa chỉ IP trên tường lửa máy chủ (iptables/ufw DROP) với thời hạn hiệu lực TTL (Tier 2 Reversible). Có cơ chế Whitelist VETO bảo vệ.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "ip": {
                                "type": "string",
                                "description": "Địa chỉ IPv4 hoặc IPv6 cần chặn (ví dụ: '45.83.122.7').",
                            },
                            "reason": {
                                "type": "string",
                                "description": "Lý do chặn địa chỉ IP (ví dụ: 'Tấn công dò quét cổng', 'Admin yêu cầu chặn').",
                            },
                            "duration_seconds": {
                                "type": "integer",
                                "description": "Thời gian chặn tính bằng giây (mặc định: 86400 = 24 giờ).",
                                "default": 86400,
                            },
                        },
                        "required": ["ip", "reason"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "unblock_ip",
                    "description": "Chủ động gỡ bỏ lệnh chặn (DROP) cho một địa chỉ IP trên tường lửa máy chủ (Tier 2 Reversible).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "ip": {
                                "type": "string",
                                "description": "Địa chỉ IP cần gỡ lệnh chặn (ví dụ: '45.83.122.7').",
                            },
                        },
                        "required": ["ip"],
                    },
                },
            },
            # ── Milestone 2: Professional Video Editor Tools (9 Tools) ──
            {
                "type": "function",
                "function": {
                    "name": "remove_text_from_video",
                    "description": "Xóa chữ, text overlay, phụ đề tĩnh hoặc watermark trên video. Hỗ trợ 3 chế độ: 'delogo' (FFmpeg nội suy biên nhanh), 'inpaint' (OpenCV Telea tái tạo nền vân gỗ/cảnh tự nhiên), hoặc 'auto' (tự động phát hiện vùng chữ qua OCR Tesseract rồi xóa).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "input_path_or_url": {"type": "string", "description": "Đường dẫn file video cục bộ trên máy chủ hoặc URL media cần xóa text."},
                            "region": {
                                "type": "object",
                                "description": "Tọa độ hộp bao {x, y, w, h} của vùng chữ cần xóa. Nếu mode='auto' có thể bỏ trống để AI tự phát hiện.",
                                "properties": {
                                    "x": {"type": "integer", "description": "Tọa độ X điểm góc trên bên trái (pixels)."},
                                    "y": {"type": "integer", "description": "Tọa độ Y điểm góc trên bên trái (pixels)."},
                                    "w": {"type": "integer", "description": "Chiều rộng vùng chữ (pixels)."},
                                    "h": {"type": "integer", "description": "Chiều cao vùng chữ (pixels)."}
                                }
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["delogo", "inpaint", "auto"],
                                "default": "delogo",
                                "description": "Chế độ xử lý: 'delogo' (nhanh), 'inpaint' (chất lượng cao qua OpenCV), 'auto' (tự phát hiện tọa độ)."
                            },
                            "output_format": {
                                "type": "string",
                                "enum": ["mp4", "mkv", "mov", "webm"],
                                "default": "mp4",
                                "description": "Định dạng tệp video đầu ra."
                            }
                        },
                        "required": ["input_path_or_url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "add_subtitle_to_video",
                    "description": "Gắn phụ đề trực tiếp (hardsub burn-in) vào khung hình video. Hỗ trợ tệp phụ đề chuẩn .SRT hoặc văn bản thô tự động chia mốc thời gian, với tùy biến font chữ, màu sắc và vị trí hiển thị.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "input_path_or_url": {"type": "string", "description": "Đường dẫn file video cục bộ hoặc URL nguồn."},
                            "subtitle_text_or_path": {"type": "string", "description": "Đường dẫn tệp .srt có sẵn hoặc đoạn văn bản phụ đề cần gắn vào video."},
                            "style": {
                                "type": "object",
                                "description": "Tùy biến kiểu chữ phụ đề: fontsize (kích cỡ, mặc định 22), color (mã màu ASS hex, ví dụ '&H00FFFFFF' cho màu trắng), outline (màu viền chữ).",
                                "properties": {
                                    "fontsize": {"type": "integer", "default": 22, "description": "Kích cỡ phông chữ phụ đề."},
                                    "color": {"type": "string", "default": "&H00FFFFFF", "description": "Mã màu chính của chữ phụ đề."},
                                    "outline": {"type": "string", "default": "&H00000000", "description": "Mã màu viền chữ phụ đề."}
                                }
                            },
                            "position": {
                                "type": "string",
                                "enum": ["bottom", "top", "center"],
                                "default": "bottom",
                                "description": "Vị trí đặt phụ đề trên khung hình video."
                            },
                            "output_format": {
                                "type": "string",
                                "enum": ["mp4", "mkv", "mov", "webm"],
                                "default": "mp4",
                                "description": "Định dạng video đầu ra."
                            }
                        },
                        "required": ["input_path_or_url", "subtitle_text_or_path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "apply_color_grade",
                    "description": "Căn chỉnh màu sắc video chuyên nghiệp theo các preset thẩm mỹ (vivid, vintage, cinematic, cool, warm, bw) hoặc tùy biến thông số Equalizer chi tiết (contrast, brightness, saturation, gamma).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "input_path_or_url": {"type": "string", "description": "Đường dẫn video cục bộ hoặc URL nguồn."},
                            "preset": {
                                "type": "string",
                                "enum": ["vivid", "vintage", "cinematic", "cool", "warm", "bw", "custom"],
                                "default": "vivid",
                                "description": "Bộ lọc màu sắc nghệ thuật mong muốn."
                            },
                            "custom_eq": {
                                "type": "object",
                                "description": "Các thông số căn chỉnh khi chọn preset='custom'.",
                                "properties": {
                                    "contrast": {"type": "number", "default": 1.0, "description": "Độ tương phản (-2.0 đến 2.0)."},
                                    "brightness": {"type": "number", "default": 0.0, "description": "Độ sáng (-1.0 đến 1.0)."},
                                    "saturation": {"type": "number", "default": 1.0, "description": "Độ bão hòa màu (0.0 đến 3.0)."},
                                    "gamma": {"type": "number", "default": 1.0, "description": "Hệ số Gamma (0.1 đến 10.0)."}
                                }
                            },
                            "output_format": {
                                "type": "string",
                                "enum": ["mp4", "mkv", "mov", "webm"],
                                "default": "mp4",
                                "description": "Định dạng video đầu ra."
                            }
                        },
                        "required": ["input_path_or_url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "stabilize_video",
                    "description": "Ổn định và loại bỏ hiện tượng rung lắc camera bằng thuật toán FFmpeg vidstab 2-pass (Pass 1 phân tích vector chuyển động, Pass 2 bù trừ biến dạng và làm sắc nét unsharp).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "input_path_or_url": {"type": "string", "description": "Đường dẫn video bị rung hoặc URL nguồn."},
                            "smoothing": {
                                "type": "integer",
                                "default": 10,
                                "description": "Độ mượt mà chống rung (1 - 60, khuyến nghị 10 - 20)."
                            },
                            "output_format": {
                                "type": "string",
                                "enum": ["mp4", "mkv", "mov", "webm"],
                                "default": "mp4",
                                "description": "Định dạng video đầu ra."
                            }
                        },
                        "required": ["input_path_or_url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "concatenate_videos",
                    "description": "Ghép nối liên tiếp nhiều đoạn video thành 1 video hoàn chỉnh theo thứ tự danh sách (hỗ trợ từ 1 đến 10 clip, tổng dung lượng đầu vào <= 500MB). Hỗ trợ stream-copy siêu tốc (-c copy) hoặc re-encode đồng bộ.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "input_paths": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Danh sách các đường dẫn video hoặc URL cần ghép nối theo thứ tự (tối đa 10 clips)."
                            },
                            "output_format": {
                                "type": "string",
                                "enum": ["mp4", "mkv", "mov", "webm"],
                                "default": "mp4",
                                "description": "Định dạng video đầu ra."
                            },
                            "reencode": {
                                "type": "boolean",
                                "default": False,
                                "description": "True nếu các video khác độ phân giải/codec cần mã hóa lại, False để ghép siêu tốc không nén lại."
                            }
                        },
                        "required": ["input_paths"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "extract_frames",
                    "description": "Trích xuất các khung hình (frames) tĩnh định kỳ từ video theo khoảng thời gian tùy chọn và tự động đóng gói toàn bộ vào tệp nén ZIP tiện lợi.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "input_path_or_url": {"type": "string", "description": "Đường dẫn video hoặc URL nguồn."},
                            "interval_seconds": {
                                "type": "number",
                                "default": 1.0,
                                "description": "Khoảng thời gian giữa các lần trích xuất ảnh tính bằng giây (ví dụ: 1.0 = mỗi giây 1 ảnh, 0.5 = mỗi giây 2 ảnh)."
                            },
                            "output_format": {
                                "type": "string",
                                "enum": ["jpg", "jpeg", "png"],
                                "default": "jpg",
                                "description": "Định dạng ảnh trích xuất."
                            },
                            "quality": {
                                "type": "integer",
                                "default": 2,
                                "description": "Chất lượng ảnh JPEG (1 - 31 trong FFmpeg, 2 là chất lượng rất cao)."
                            }
                        },
                        "required": ["input_path_or_url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "remove_watermark_region",
                    "description": "Xóa cùng lúc nhiều vùng watermark hoặc logo (tối đa 5 vùng) trên video bằng chuỗi bộ lọc FFmpeg chained delogo.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "input_path_or_url": {"type": "string", "description": "Đường dẫn video hoặc URL nguồn."},
                            "regions": {
                                "type": "array",
                                "description": "Danh sách các vùng watermark cần xóa (tối đa 5 vùng), mỗi vùng là object {x, y, w, h}.",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "x": {"type": "integer", "description": "Tọa độ X (pixels)."},
                                        "y": {"type": "integer", "description": "Tọa độ Y (pixels)."},
                                        "w": {"type": "integer", "description": "Chiều rộng vùng watermark (pixels)."},
                                        "h": {"type": "integer", "description": "Chiều cao vùng watermark (pixels)."}
                                    },
                                    "required": ["x", "y", "w", "h"]
                                }
                            },
                            "output_format": {
                                "type": "string",
                                "enum": ["mp4", "mkv", "mov", "webm"],
                                "default": "mp4",
                                "description": "Định dạng video đầu ra."
                            }
                        },
                        "required": ["input_path_or_url", "regions"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "enhance_video_quality",
                    "description": "Nâng cấp chất lượng hình ảnh video bằng các bộ lọc chuyên sâu: làm sắc nét viền (sharpen), khử nhiễu hạt 3D (denoise qua hqdn3d), khử răng cưa đan xen (deinterlace qua yadif), siêu phân giải Lanczos x2 (upscale_2x), hoặc tăng cường độ tương phản sống động (hdr_tonemap).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "input_path_or_url": {"type": "string", "description": "Đường dẫn video hoặc URL nguồn."},
                            "preset": {
                                "type": "string",
                                "enum": ["sharpen", "denoise", "deinterlace", "upscale_2x", "hdr_tonemap"],
                                "default": "sharpen",
                                "description": "Bộ lọc nâng cấp chất lượng hình ảnh áp dụng."
                            },
                            "output_format": {
                                "type": "string",
                                "enum": ["mp4", "mkv", "mov", "webm"],
                                "default": "mp4",
                                "description": "Định dạng video đầu ra."
                            }
                        },
                        "required": ["input_path_or_url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "generate_video_thumbnail",
                    "description": "Trích xuất ảnh đại diện (thumbnail / poster) sắc nét từ video tại mốc thời gian bất kỳ với kích thước co giãn giữ nguyên tỷ lệ khung hình.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "input_path_or_url": {"type": "string", "description": "Đường dẫn video hoặc URL nguồn."},
                            "timestamp": {
                                "type": "number",
                                "default": 0.0,
                                "description": "Mốc thời gian trích xuất thumbnail tính bằng giây (ví dụ: 10.5)."
                            },
                            "width": {
                                "type": "integer",
                                "default": 320,
                                "description": "Chiều rộng thumbnail tối đa (pixels, giữ nguyên tỷ lệ khung hình)."
                            },
                            "height": {
                                "type": "integer",
                                "default": 240,
                                "description": "Chiều cao thumbnail tối đa (pixels, giữ nguyên tỷ lệ khung hình)."
                            },
                            "output_format": {
                                "type": "string",
                                "enum": ["jpg", "png"],
                                "default": "jpg",
                                "description": "Định dạng ảnh thumbnail."
                            }
                        },
                        "required": ["input_path_or_url"]
                    }
                }
            },
            # ── M6 Omni Super-Agent: R1 Multimedia Studio Suite ──
            {
                "type": "function",
                "function": {
                    "name": "edit_video_clip",
                    "description": "Cắt đoạn clip từ tệp video hoặc URL theo mốc thời gian bắt đầu và thời lượng. Hỗ trợ cắt nhanh không mã hóa lại (-c copy) hoặc re-encode chất lượng cao qua FFmpeg.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "input_path_or_url": {"type": "string", "description": "Đường dẫn file video cục bộ trên máy chủ hoặc URL media cần cắt."},
                            "start_time": {"type": "string", "description": "Mốc thời gian bắt đầu, định dạng HH:MM:SS hoặc SS (ví dụ: '00:01:30' hoặc '90')."},
                            "duration": {"type": "string", "description": "Thời lượng đoạn cần cắt, định dạng HH:MM:SS hoặc số giây (ví dụ: '30' hoặc '00:00:45')."},
                            "output_format": {"type": "string", "enum": ["mp4", "mkv", "mov", "webm", "gif"], "default": "mp4", "description": "Định dạng tệp video đầu ra."},
                            "reencode": {"type": "boolean", "default": False, "description": "True nếu muốn re-encode chính xác từng frame, False để cắt siêu tốc không nén lại (-c copy)."}
                        },
                        "required": ["input_path_or_url", "start_time", "duration"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "compress_video",
                    "description": "Nén dung lượng video tự động sử dụng thuật toán 2-pass bitrate của FFmpeg để đưa kích thước file về dưới ngưỡng mục tiêu (mặc định < 50MB) gửi mượt mà qua Telegram.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "input_path_or_url": {"type": "string", "description": "Đường dẫn file video hoặc URL cần nén."},
                            "target_size_mb": {"type": "number", "default": 48.0, "description": "Dung lượng đích mong muốn tính bằng MB (khuyến nghị 45.0 - 48.0 MB cho Telegram)."}
                        },
                        "required": ["input_path_or_url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "convert_video_format",
                    "description": "Chuyển đổi định dạng video qua lại giữa MP4, MKV, AVI, MOV, WEBM và Animated GIF tối ưu hóa hiển thị.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "input_path_or_url": {"type": "string", "description": "Đường dẫn file video nguồn hoặc URL."},
                            "target_format": {"type": "string", "enum": ["mp4", "mkv", "avi", "mov", "webm", "gif"], "description": "Định dạng đích cần chuyển đổi."},
                            "preset": {"type": "string", "enum": ["ultrafast", "fast", "medium", "slow"], "default": "fast", "description": "Mức độ cân đối giữa tốc độ xử lý và độ nén."}
                        },
                        "required": ["input_path_or_url", "target_format"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "convert_audio_format",
                    "description": "Chuyển đổi âm thanh chuyên nghiệp đa định dạng (FLAC, WAV, M4A, OGG, AAC -> MP3) với tùy chỉnh bitrate phòng thu lên tới 320kbps.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "input_path_or_url": {"type": "string", "description": "Đường dẫn file âm thanh hoặc URL."},
                            "target_format": {"type": "string", "enum": ["mp3", "aac", "wav", "flac", "ogg", "m4a"], "default": "mp3", "description": "Định dạng audio đích."},
                            "bitrate": {"type": "string", "enum": ["128k", "192k", "256k", "320k"], "default": "320k", "description": "Chất lượng âm thanh đầu ra."}
                        },
                        "required": ["input_path_or_url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "trim_audio_clip",
                    "description": "Cắt đoạn âm thanh hoặc nhạc chuông chính xác theo thời gian bắt đầu và thời lượng.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "input_path_or_url": {"type": "string", "description": "Đường dẫn file âm thanh hoặc URL nguồn."},
                            "start_time": {"type": "string", "description": "Thời điểm bắt đầu (ví dụ: '00:00:15' hoặc '15')."},
                            "duration": {"type": "string", "description": "Thời lượng đoạn nhạc cần trích xuất (ví dụ: '30' hoặc '00:00:30')."}
                        },
                        "required": ["input_path_or_url", "start_time", "duration"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "normalize_audio_volume",
                    "description": "Tự động chuẩn hóa và cân bằng âm lượng tệp âm thanh theo chuẩn phát thanh châu Âu EBU R128 (loudnorm filter), loại bỏ hiện tượng âm lượng quá nhỏ hoặc rè méo tiếng.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "input_path_or_url": {"type": "string", "description": "Đường dẫn file âm thanh hoặc URL nguồn."}
                        },
                        "required": ["input_path_or_url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "convert_and_resize_image",
                    "description": "Xử lý ảnh chuyên nghiệp in-memory/file: Chuyển đổi định dạng (WEBP, HEIC, PNG, JPG), thay đổi kích thước theo tỷ lệ chuẩn, và nén giảm dung lượng mà vẫn giữ độ nét.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "input_path_or_url": {"type": "string", "description": "Đường dẫn file ảnh cục bộ hoặc URL ảnh."},
                            "format": {"type": "string", "enum": ["jpg", "png", "webp"], "default": "webp", "description": "Định dạng ảnh đầu ra."},
                            "max_width": {"type": "integer", "description": "Chiều rộng tối đa (pixels), giữ nguyên tỷ lệ khung hình."},
                            "max_height": {"type": "integer", "description": "Chiều cao tối đa (pixels), giữ nguyên tỷ lệ khung hình."},
                            "quality": {"type": "integer", "default": 85, "description": "Chất lượng nén từ 1-100 (khuyến nghị 80-90)."}
                        },
                        "required": ["input_path_or_url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "generate_custom_qr",
                    "description": "Sinh mã QR Code độ phân giải cao in-memory từ nội dung bất kỳ (WiFi, URL, tin nhắn, số tài khoản, vCard) với nhãn tiêu đề và màu sắc tùy chỉnh.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string", "description": "Nội dung cần mã hóa thành mã QR (chuỗi URL, cấu hình WiFi: 'WIFI:S:MySSID;T:WPA;P:MyPassword;;', văn bản)."},
                            "label": {"type": "string", "description": "Nhãn hiển thị bên dưới hoặc chú thích cho mã QR."},
                            "fill_color": {"type": "string", "default": "#0f172a", "description": "Mã màu Hex cho các điểm ảnh QR."},
                            "back_color": {"type": "string", "default": "#ffffff", "description": "Mã màu nền Hex cho mã QR."}
                        },
                        "required": ["content"]
                    }
                }
            },

            # ── M6 Omni Super-Agent: R2 Document & Knowledge Processing ──
            {
                "type": "function",
                "function": {
                    "name": "merge_pdf_documents",
                    "description": "Gộp nhiều tệp PDF riêng lẻ thành một tệp PDF duy nhất với thứ tự xác định bằng PyMuPDF tốc độ cao.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_paths": {"type": "array", "items": {"type": "string"}, "description": "Danh sách các đường dẫn tệp PDF theo thứ tự cần gộp."},
                            "output_name": {"type": "string", "description": "Tên tệp PDF đầu ra mong muốn (ví dụ: 'tai_lieu_tong_hop.pdf')."}
                        },
                        "required": ["file_paths"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "split_pdf_document",
                    "description": "Tách một tệp PDF lớn thành tệp con chứa các trang được chỉ định.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string", "description": "Đường dẫn tệp PDF cần trích xuất trang."},
                            "page_ranges": {"type": "string", "description": "Phạm vi các trang cần lấy, đánh số từ 1 (ví dụ: '1-3, 5, 8-10')."},
                            "output_name": {"type": "string", "description": "Tên tệp kết quả đầu ra."}
                        },
                        "required": ["file_path", "page_ranges"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "extract_document_text",
                    "description": "Trích xuất toàn bộ nội dung văn bản thuần sạch sẽ từ các tệp tài liệu số (PDF, DOCX, TXT, MD, CSV, JSON, LOG).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string", "description": "Đường dẫn tới tệp tài liệu trên máy chủ."},
                            "max_characters": {"type": "integer", "default": 10000, "description": "Giới hạn số ký tự tối đa cần trích xuất để nạp vào ngữ cảnh AI."}
                        },
                        "required": ["file_path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "translate_text",
                    "description": "Dịch thuật văn bản đa ngôn ngữ siêu tốc và chuẩn xác (Anh, Việt, Trung, Nhật, Hàn, Pháp, Đức...) bảo toàn văn phong chuyên môn.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string", "description": "Đoạn văn bản cần dịch."},
                            "target_lang": {"type": "string", "default": "vi", "description": "Mã ngôn ngữ đích (ví dụ: 'vi', 'en', 'zh', 'ja', 'ko', 'fr')."},
                            "source_lang": {"type": "string", "default": "auto", "description": "Mã ngôn ngữ nguồn ('auto' để tự động nhận diện)."}
                        },
                        "required": ["text"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "inspect_media_metadata",
                    "description": "Trích xuất siêu dữ liệu chi tiết chuyên sâu của tệp video, âm thanh hoặc hình ảnh qua ffprobe và EXIF (độ phân giải, codec, fps, bitrate, audio channels, sample rate, thời lượng, tag ID3).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path_or_url": {"type": "string", "description": "Đường dẫn tệp phương tiện cục bộ hoặc URL."}
                        },
                        "required": ["file_path_or_url"]
                    }
                }
            },

            # ── M6 Omni Super-Agent: R3 Universal Internet Extraction ──
            {
                "type": "function",
                "function": {
                    "name": "download_direct_file",
                    "description": "Tải tệp bất kỳ từ internet (ISO, ZIP, tài liệu, file nhị phân, drivers) hỗ trợ streaming chunked trực tiếp ra đĩa tạm, resume tải tiếp và báo cáo tiến độ chi tiết.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "Đường dẫn URL trực tiếp của tệp cần tải về."},
                            "custom_filename": {"type": "string", "description": "Tên tệp tùy chỉnh muốn lưu lại trên máy chủ."},
                            "timeout_seconds": {"type": "integer", "default": 300, "description": "Thời gian chờ tối đa cho quá trình tải."}
                        },
                        "required": ["url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "extract_clean_web_article",
                    "description": "Bóc tách bài viết sạch từ trang báo điện tử hoặc blog bất kỳ, loại bỏ hoàn toàn các mã script, CSS, quảng cáo, menu điều hướng, và trả về định dạng Markdown cấu trúc rõ ràng cho AI đọc hiểu.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "URL bài viết hoặc trang tin tức cần bóc tách nội dung."}
                        },
                        "required": ["url"]
                    }
                }
            },

            # ── M6 Omni Super-Agent: R4 Unrestricted Root System Mastery ──
            {
                "type": "function",
                "function": {
                    "name": "execute_system_script",
                    "description": "Thực thi trực tiếp script hoàn chỉnh (Bash shell hoặc Python 3) trên máy chủ kirito-server với quyền hạn được phân cấp an toàn, trả về stdout, stderr và mã thoát.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "script_code": {"type": "string", "description": "Mã nguồn script đầy đủ cần thực thi."},
                            "interpreter": {"type": "string", "enum": ["bash", "python3"], "default": "bash", "description": "Trình thông dịch để chạy script."},
                            "timeout_seconds": {"type": "integer", "default": 60, "description": "Thời gian chờ tối đa (giây)."}
                        },
                        "required": ["script_code"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "manage_docker_containers",
                    "description": "Điều hành toàn diện vòng đời các container Docker trên máy chủ (start, stop, restart, inspect, logs, prune rác container/images thừa).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": ["start", "stop", "restart", "inspect", "logs", "prune"], "description": "Hành động quản trị container."},
                            "container_name": {"type": "string", "description": "Tên container (ví dụ: 'dashboard_ai_agent', 'dashboard_db', 'dashboard_frontend'). Bắt buộc khi action != 'prune'."},
                            "force": {"type": "boolean", "default": False, "description": "Cưỡng chế thực thi nếu container bị treo."}
                        },
                        "required": ["action"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "optimize_system_resources",
                    "description": "Tự động tối ưu hóa tài nguyên máy chủ kirito-server: Đồng bộ và giải phóng RAM đệm (sync && drop_caches), dọn dẹp các image/container Docker rác (docker system prune -f), và xoay vòng dọn log thừa.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "clean_docker": {"type": "boolean", "default": True, "description": "Dọn dẹp rác Docker."},
                            "drop_caches": {"type": "boolean", "default": True, "description": "Giải phóng pagecache, dentries và inodes trong RAM Linux."}
                        }
                    }
                }
            },
            # ── R4: Autonomous Goal Management ──
            {
                "type": "function",
                "function": {
                    "name": "create_autonomous_goal",
                    "description": "Tạo một mục tiêu tự hành dài hạn (Autonomous Goal) hoặc tác vụ tự động có điều kiện kích hoạt. Hệ thống Autonomous Goal Worker sẽ tự động lập kế hoạch đa bước và thực thi ngầm trên máy chủ mà không làm phiền người dùng.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "goal": {
                                "type": "string",
                                "description": "Mô tả chi tiết mục tiêu cần đạt được (ví dụ: 'Theo dõi RAM mỗi 10 phút, nếu > 90% thì restart container dashboard_metrics_service và gửi báo cáo Telegram', 'Kiểm tra dung lượng đĩa hàng giờ và dọn dẹp nếu > 85%').",
                            },
                            "trigger_condition": {
                                "type": "string",
                                "description": "Điều kiện kích hoạt định kỳ hoặc theo ngưỡng số liệu (ví dụ: 'every 10m', 'ram > 90%', 'disk > 85%', 'immediate'). Bỏ trống nếu muốn chạy kế hoạch ngay lập tức.",
                            },
                        },
                        "required": ["goal"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_autonomous_goals",
                    "description": "Liệt kê danh sách tất cả các mục tiêu tự hành (Autonomous Goals) đang hoạt động, đang chờ kích hoạt hoặc mới hoàn thành trên máy chủ.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "status_filter": {
                                "type": "string",
                                "enum": ["all", "active", "completed", "failed"],
                                "description": "Bộ lọc trạng thái mục tiêu (mặc định: 'active' để xem các task đang theo dõi).",
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "cancel_autonomous_goal",
                    "description": "Hủy bỏ một mục tiêu tự hành đang theo dõi trên máy chủ theo ID mục tiêu.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "goal_id": {
                                "type": "string",
                                "description": "Mã định danh (Task ID hoặc Goal ID) của mục tiêu cần hủy.",
                            },
                        },
                        "required": ["goal_id"],
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

        # Strict Token Budget Gate: prune lowest priority tools until schema <= 700 tokens
        # Only prune if scoping was actively invoked (i.e. query or history provided)
        if scoped_allowed is not None and len(filtered_tools) > 2:
            import json
            q_lower = (effective_query or "").lower()

            # Detect actively boosted tools from user query to protect them from being dropped
            protected_tools = set()
            if any(k in q_lower for k in ("mục tiêu", "muc tieu", "goal", "goals", "tự hành", "tu hanh", "lập kế hoạch", "lap ke hoach", "hủy mục tiêu", "danh sách mục tiêu", "task tự động", "task tu dong", "theo dõi")):
                protected_tools.update({"create_autonomous_goal", "list_autonomous_goals", "cancel_autonomous_goal"})
            if any(k in q_lower for k in ("tải mp3", "tai mp3", "nhạc", "nhac", "audio", "mp3", "bài hát", "bai hat")):
                protected_tools.add("download_media_audio")
            if any(k in q_lower for k in ("tải video", "tai video", "video", "clip", "mp4", "down video", "tiktok", "youtube")):
                protected_tools.add("download_media_video")
            if any(k in q_lower for k in ("restart", "khởi động lại", "khoi dong lai", "reboot service")):
                protected_tools.add("restart_service")
            if any(k in q_lower for k in ("cắt video", "cat video", "cắt clip", "cat clip", "edit video", "cắt đoạn video", "cat doan video")):
                protected_tools.add("edit_video_clip")
            if any(k in q_lower for k in ("nén video", "nen video", "compress video", "giảm dung lượng video", "giam dung luong video")):
                protected_tools.add("compress_video")
            if any(k in q_lower for k in ("đổi đuôi video", "doi duoi video", "convert video", "chuyển định dạng video", "mp4 sang", "mkv sang", "tạo gif", "tao gif")):
                protected_tools.add("convert_video_format")
            if any(k in q_lower for k in ("đổi đuôi nhạc", "doi duoi nhac", "convert audio", "flac sang", "wav sang", "m4a sang", "320k")):
                protected_tools.add("convert_audio_format")
            if any(k in q_lower for k in ("cắt nhạc", "cat nhac", "cắt audio", "cat audio", "nhạc chuông", "nhac chuong", "trim audio")):
                protected_tools.add("trim_audio_clip")
            if any(k in q_lower for k in ("chuẩn hóa âm lượng", "chuan hoa am luong", "cân bằng âm lượng", "can bang am luong", "loudnorm", "ebu r128")):
                protected_tools.add("normalize_audio_volume")
            if any(k in q_lower for k in ("resize ảnh", "resize anh", "nén ảnh", "nen anh", "đổi kích thước ảnh", "doi kich thuoc anh", "doi kich thuoc", "đổi kích thước", "chuyển ảnh sang", "webp", "png sang jpg", "jpg sang png")):
                protected_tools.add("convert_and_resize_image")
            if any(k in q_lower for k in ("mã qr", "ma qr", "qr code", "tạo qr", "tao qr", "sinh qr", "quet qr", "quét qr")):
                protected_tools.add("generate_custom_qr")
            if any(k in q_lower for k in ("metadata", "thông tin video", "thông tin audio", "ffprobe", "exif", "codec")):
                protected_tools.add("inspect_media_metadata")
            if any(k in q_lower for k in ("gộp pdf", "gop pdf", "merge pdf", "ghép pdf", "ghep pdf", "nối pdf", "noi pdf", "gộp các file pdf", "gop cac file pdf", "gộp file pdf", "gop file pdf")) or bool(re.search(r"\b(?:gộp|gop|ghép|ghep|nối|noi|merge)\s+.*pdf\b", q_lower)):
                protected_tools.add("merge_pdf_documents")
            if any(k in q_lower for k in ("tách pdf", "tach pdf", "split pdf", "cắt trang pdf", "trích trang pdf", "tách các trang", "tach cac trang", "tách trang", "tach trang", "tach file pdf", "tách file pdf")) or bool(re.search(r"\b(?:tách|tach|split|cắt trang|cat trang|trích trang|trich trang)\s+.*pdf\b", q_lower)):
                protected_tools.add("split_pdf_document")
            if any(k in q_lower for k in ("đọc pdf", "doc pdf", "trích xuất văn bản", "trich xuat van ban", "extract text", "đọc word", "doc word", "đọc docx", "đọc nội dung file", "doc noi dung file", "báo cáo pdf", "bao cao pdf", "nội dung file", "file pdf", "doc file docx", "đọc file docx")) or bool(re.search(r"\b(?:đọc|doc|xem|trích|trich|nội dung|noi dung)\s+.*(?:pdf|docx|tài liệu|tai lieu|văn bản|van ban)\b", q_lower)):
                protected_tools.add("extract_document_text")
            if any(k in q_lower for k in ("dịch", "dich", "translate", "dịch văn bản", "dịch sang", "nghĩa là gì")):
                protected_tools.add("translate_text")
            if any(k in q_lower for k in ("tải tệp", "tai tep", "tải file trực tiếp", "download direct", "tải link", "tải file zip", "tải file iso", "download file", "tải file", "download file iso")):
                protected_tools.add("download_direct_file")
            if any(k in q_lower for k in ("bóc tách bài viết", "boc tach bai viet", "bóc bài viết", "boc bai viet", "đọc bài báo", "doc bai bao", "bài báo", "bai bao", "đọc báo", "doc bao", "trích xuất bài viết", "extract article", "nội dung bài báo", "tóm tắt bài báo", "tóm tắt bài viết")):
                protected_tools.add("extract_clean_web_article")
            if any(k in q_lower for k in ("chạy script", "chay script", "execute script", "script bash", "script python", "chạy code python", "chay code python", "chạy kịch bản", "chay kich ban", "kịch bản bash", "kich ban bash", "kịch bản python", "kich ban python")):
                protected_tools.add("execute_system_script")
            if any(k in q_lower for k in ("quản lý docker", "docker restart", "restart container", "khởi động lại container", "khoi dong lai container", "dừng container", "stop container", "bật container", "start container", "docker prune", "xóa rác docker", "container docker")):
                protected_tools.add("manage_docker_containers")
            if any(k in q_lower for k in ("tối ưu hệ thống", "toi uu he thong", "dọn dẹp hệ thống", "giải phóng ram", "giai phong ram", "drop_caches", "tối ưu máy chủ", "tối ưu server", "giải phóng ram đệm", "dọn ram", "don ram", "dọn dẹp ram", "don dep ram")):
                protected_tools.add("optimize_system_resources")
            if any(k in q_lower for k in ("honeypot", "bẫy", "bay", "kẻ thất bại", "ke that bai")):
                protected_tools.add("get_honeypot_log")
            if any(k in q_lower for k in ("lịch sử", "lich su", "history", "tấn công", "tan cong")):
                protected_tools.add("get_attack_history")
            if any(k in q_lower for k in ("thời tiết", "thoi tiet", "weather", "nhiệt độ", "nhiet do", "mưa", "mua")):
                protected_tools.add("get_weather")
            if any(k in q_lower for k in ("dọn ram", "don ram", "dọn dẹp ram", "don dep ram")):
                protected_tools.add("optimize_system_resources")
            if any(k in q_lower for k in ("cân bằng âm lượng", "can bang am luong")):
                protected_tools.add("normalize_audio_volume")
            if any(k in q_lower for k in self._KW_REMOVE_TEXT):
                protected_tools.add("remove_text_from_video")
            if any(k in q_lower for k in self._KW_ADD_SUBTITLE):
                protected_tools.add("add_subtitle_to_video")
            if any(k in q_lower for k in self._KW_COLOR_GRADE):
                protected_tools.add("apply_color_grade")
            if any(k in q_lower for k in self._KW_STABILIZE):
                protected_tools.add("stabilize_video")
            if any(k in q_lower for k in self._KW_CONCAT):
                protected_tools.add("concatenate_videos")
            if any(k in q_lower for k in self._KW_EXTRACT_FRAMES):
                protected_tools.add("extract_frames")
            if any(k in q_lower for k in self._KW_REMOVE_WATERMARK):
                protected_tools.add("remove_watermark_region")
            if any(k in q_lower for k in self._KW_ENHANCE_VIDEO):
                protected_tools.add("enhance_video_quality")
            if any(k in q_lower for k in self._KW_GENERATE_THUMBNAIL):
                protected_tools.add("generate_video_thumbnail")

            unprotected_drop_priority = [
                "browser_press_key", "browser_scroll", "browser_type", "browser_click",
                "facebook_capture_screenshot", "recover_archive_password", "complete_task",
                "remember_for_later", "get_server_active_sessions", "server_capture_screenshot",
                "facebook_send_reply", "facebook_get_messages", "browser_search_google",
                "browser_navigate", "get_server_location", "extract_archive_file",
                "read_archive_file", "get_attack_history", "get_honeypot_log", "list_blocked_ips",
                "unblock_ip", "block_ip", "get_security_report", "get_weather",
                "calculate", "convert_units", "query_database", "create_file_transfer_portal",
                "list_files", "read_file_content", "write_file_content", "move_or_rename_file", "get_disk_usage",
                "create_cron_job", "list_cron_jobs", "delete_cron_job",
                "download_media_audio", "download_media_video", "get_system_health_report", "check_service_status",
                "generate_video_thumbnail", "extract_frames", "remove_watermark_region", "enhance_video_quality",
                "apply_color_grade", "stabilize_video", "concatenate_videos", "add_subtitle_to_video",
                "remove_text_from_video", "inspect_media_metadata", "convert_and_resize_image", "normalize_audio_volume",
                "trim_audio_clip", "convert_audio_format", "convert_video_format", "compress_video",
                "edit_video_clip", "generate_custom_qr", "split_pdf_document", "merge_pdf_documents",
                "extract_document_text", "translate_text", "extract_clean_web_article",
                "download_direct_file", "optimize_system_resources", "manage_docker_containers",
                "execute_system_script", "run_command"
            ]
            reverse_priority = [t for t in unprotected_drop_priority if t not in protected_tools] + [t for t in unprotected_drop_priority if t in protected_tools]

            while len(filtered_tools) > 2 and (len(json.dumps(filtered_tools, ensure_ascii=False)) / 3.5) > 700.0:
                dropped = False
                for candidate in reverse_priority:
                    cand_tool = next((t for t in filtered_tools if t.get("function", {}).get("name") == candidate), None)
                    if cand_tool is not None:
                        filtered_tools.remove(cand_tool)
                        dropped = True
                        break
                if not dropped:
                    unprotected_cand = next((t for t in reversed(filtered_tools) if t.get("function", {}).get("name") not in protected_tools), None)
                    if unprotected_cand is not None:
                        filtered_tools.remove(unprotected_cand)
                    else:
                        filtered_tools.pop()

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
                # Raw output
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
                                    width=getattr(media_item, "width", 0) or 0,
                                    height=getattr(media_item, "height", 0) or 0,
                                    supports_streaming=True,
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
                                            supports_streaming=True,
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

            # ── High-Speed File Transfer Portal (Multi-Device LAN/WAN) ──
            if tool_name == "create_file_transfer_portal":
                from app.services.transfer_storage_manager import transfer_storage_manager
                file_name = tool_args.get("file_name")
                raw_mode = str(tool_args.get("mode", "upload")).strip().lower()
                mode = "download" if raw_mode == "download" else "upload"
                one_time = bool(tool_args.get("one_time", False))

                session = transfer_storage_manager.create_session(
                    filename=file_name,
                    mode=mode,
                    one_time=one_time,
                    ttl_hours=24,
                )

                internet_base, lan_base = transfer_storage_manager.resolve_public_transfer_base_url_sync()
                lan_url = f"{lan_base}/api/ai/transfer/portal/{session.token}"
                wan_url = f"{internet_base}/api/ai/transfer/portal/{session.token}"

                qr_sent = False
                if self.telegram_bot and chat_id:
                    try:
                        qr_target = wan_url if (wan_url and not wan_url.startswith("http://192.168.") and not wan_url.startswith("http://127.0.0.1")) else lan_url
                        qr_sent = await self.telegram_bot.send_transfer_portal_card(
                            chat_id=chat_id,
                            file_name=session.filename,
                            file_size_bytes=session.file_size,
                            token=session.token,
                            lan_url=lan_url,
                            wan_url=wan_url,
                            qr_target_url=qr_target,
                            ttl_hours=24,
                            mode=mode,
                            one_time=one_time,
                        )
                    except Exception as tg_err:
                        logger.warning("[AiAgentTools] Failed to send Telegram transfer portal card: %s", tg_err)

                mode_text = "Tải lên (Upload từ thiết bị)" if mode == "upload" else "Tải xuống (Download về thiết bị)"
                one_time_note = "\n⚠️ **Lưu ý:** Liên kết sẽ tự hủy sau 1 lần tải thành công." if one_time else ""
                qr_status = "Đã gửi trực tiếp mã QR Code lên Telegram, anh chỉ cần bật Camera điện thoại/iPad quét là mở cổng ngay!" if (qr_sent or self.telegram_bot) else "Anh có thể mở trực tiếp đường link trên hoặc quét mã QR từ cổng web."

                return (
                    f"🚀 **CỔNG CHUYỂN TỆP SIÊU TỐC TIỂU BẢO BẢO ĐÃ SẴN SÀNG!**\n\n"
                    f"Em đã khởi tạo phiên truyền tệp thành công và gửi thông tin kèm mã QR Code cho anh Mạnh rồi ạ:\n"
                    f"• 📋 **Chế độ:** `{mode_text}`\n"
                    f"• 📁 **Tên tệp:** `{html.escape(session.filename)}`\n"
                    f"• ⚡ **Link LAN Wi-Fi (Tốc độ tối đa Gigabit 50-100MB/s):**\n`{lan_url}`\n"
                    f"• 🌐 **Link WAN Internet Toàn Cầu:**\n`{wan_url}`\n"
                    f"• ⏳ **Thời hạn hiệu lực:** 24 giờ\n"
                    f"• 📷 **Mã QR:** {qr_status}{one_time_note}"
                )

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

            # ── R1: Smart Calendar & Scheduler ──
            if tool_name == "schedule_reminder":
                msg = tool_args.get("message", "")
                delay = int(tool_args.get("delay_minutes", 0))
                repeat = tool_args.get("repeat", "none")
                res = await self.scheduler_service.schedule_reminder(
                    message=msg, delay_minutes=delay, repeat=repeat
                )
                return res.get("text") or res.get("message") or json.dumps(res, ensure_ascii=False)

            if tool_name == "list_scheduled_reminders":
                res = await self.scheduler_service.list_scheduled_reminders()
                reminders = res.get("reminders", [])
                if not reminders:
                    return "⏰ Hiện không có lịch nhắc nhở nào đang chờ kích hoạt."
                lines = [f"📋 **DANH SÁCH LỊCH NHẮC ĐANG CHỜ ({len(reminders)} lịch)**:"]
                for r in reminders:
                    r_id = r.get("id")
                    r_msg = r.get("message")
                    r_time = r.get("remind_at_vn") or r.get("remind_at")
                    r_repeat = r.get("repeat", "none")
                    repeat_str = f" [Lặp: {r_repeat}]" if r_repeat != "none" else ""
                    lines.append(f"• **#{r_id}**: \"{r_msg}\" — lúc `{r_time}`{repeat_str}")
                return "\n".join(lines)

            if tool_name == "cancel_reminder":
                r_id = int(tool_args.get("reminder_id", 0))
                res = await self.scheduler_service.cancel_reminder(reminder_id=r_id)
                return res.get("message") or json.dumps(res, ensure_ascii=False)

            # ── R2: Autonomous Health Monitor ──
            if tool_name == "get_system_health_report":
                res = await self.server_monitor_service.get_system_health_report()
                if res.get("status") == "error":
                    return f"❌ Lỗi lấy báo cáo sức khỏe máy chủ: {res.get('message')}"
                return res.get("summary") or json.dumps(res, ensure_ascii=False, indent=2)

            if tool_name == "check_service_status":
                svc_name = tool_args.get("service_name", "").strip()
                res = await self.server_monitor_service.check_service_status(service_name=svc_name)
                return res.get("text") or res.get("message") or json.dumps(res, ensure_ascii=False)

            if tool_name == "restart_service":
                svc_name = tool_args.get("service_name", "").strip()
                confirm = tool_args.get("confirm")
                res = await self.server_monitor_service.restart_service(service_name=svc_name, confirm=confirm)
                return res.get("message") or json.dumps(res, ensure_ascii=False)

            if tool_name == "tail_service_logs":
                svc_name = tool_args.get("service_name", "").strip()
                lines_cnt = int(tool_args.get("lines", 50))
                res = await self.server_monitor_service.tail_service_logs(service_name=svc_name, lines=lines_cnt)
                if res.get("status") == "error":
                    return f"❌ Lỗi lấy logs: {res.get('message')}"
                error_sum = res.get("error_summary", "")
                logs_raw = res.get("logs", "")
                return (
                    f"📜 **LOGS DỊCH VỤ '{svc_name}' ({res.get('total_lines', 0)} dòng)**:\n"
                    f"💡 **Tóm tắt chẩn đoán**: {error_sum}\n\n"
                    f"```\n{logs_raw[-1500:] if len(logs_raw) > 1500 else logs_raw}\n```"
                )

            # ── R3: Personal Notes & Knowledge Base ──
            if tool_name == "create_note":
                title = tool_args.get("title", "")
                content = tool_args.get("content", "")
                tags = tool_args.get("tags")
                res = await self.notes_service.create_note(title=title, content=content, tags=tags)
                return res.get("text") or res.get("message") or json.dumps(res, ensure_ascii=False)

            if tool_name == "search_notes":
                query = tool_args.get("query", "")
                tags = tool_args.get("tags")
                res = await self.notes_service.search_notes(query=query, tags=tags)
                return res.get("text") or res.get("message") or json.dumps(res, ensure_ascii=False)

            if tool_name == "list_notes":
                tag = tool_args.get("tag")
                res = await self.notes_service.list_notes(tag=tag)
                return res.get("text") or res.get("message") or json.dumps(res, ensure_ascii=False)

            if tool_name == "delete_note":
                note_id = tool_args.get("note_id", "").strip()
                res = await self.notes_service.delete_note(note_id=note_id)
                return res.get("message") or json.dumps(res, ensure_ascii=False)

            # ── R4: Calculator & Data Analytics ──
            if tool_name == "calculate":
                expr = tool_args.get("expression", "")
                res = await self.calculator_service.calculate(expression=expr)
                if res.get("status") == "success":
                    formatted = res.get("formatted", res.get("result"))
                    return f"🔢 **Kết quả tính toán:** `{expr}` = **{formatted}**"
                return f"❌ {res.get('message', 'Lỗi tính toán')}"

            if tool_name == "query_database":
                sql = tool_args.get("sql_query", "")
                db_name = tool_args.get("database", "postgres")
                res = await self.calculator_service.query_database(sql_query=sql, database=db_name)
                if res.get("status") == "success":
                    table = res.get("formatted_table", "")
                    row_cnt = res.get("row_count", 0)
                    dur = res.get("duration_ms", 0)
                    return f"📊 **KẾT QUẢ TRUY VẤN SQL ({row_cnt} dòng, {dur}ms)**:\n```\n{table}\n```"
                return f"❌ {res.get('message', 'Lỗi truy vấn SQL')}"

            if tool_name == "convert_units":
                val = float(tool_args.get("value", 0))
                f_unit = tool_args.get("from_unit", "")
                t_unit = tool_args.get("to_unit", "")
                res = await self.calculator_service.convert_units(value=val, from_unit=f_unit, to_unit=t_unit)
                if res.get("status") == "success":
                    return f"🔄 **Chuyển đổi đơn vị:** {val} {f_unit} = **{res.get('formatted')}**"
                return f"❌ {res.get('message', 'Lỗi chuyển đổi đơn vị')}"

            # ── R5: Cron Automation ──
            if tool_name == "create_cron_job":
                c_name = tool_args.get("name", "").strip()
                c_sched = tool_args.get("schedule", "").strip()
                c_cmd = tool_args.get("command", "").strip()
                c_desc = tool_args.get("description", "")
                res = await self.cron_service.create_cron_job(
                    name=c_name, schedule=c_sched, command=c_cmd, description=c_desc
                )
                return res.get("message") or json.dumps(res, ensure_ascii=False)

            if tool_name == "list_cron_jobs":
                res = await self.cron_service.list_cron_jobs()
                jobs = res.get("jobs", [])
                if not jobs:
                    return res.get("text") or res.get("message") or f"⏰ Hiện không có cron job nào (status: {res.get('status', 'success')})."
                lines = [f"📋 **DANH SÁCH CRON JOBS ({len(jobs)} jobs)**:"]
                for j in jobs:
                    j_name = j.get("name")
                    j_sched = j.get("schedule")
                    j_cmd = j.get("command")
                    j_desc = j.get("description")
                    desc_str = f" ({j_desc})" if j_desc else ""
                    lines.append(f"• **{j_name}** [`{j_sched}`]: `{j_cmd}`{desc_str}")
                return "\n".join(lines)

            if tool_name == "delete_cron_job":
                c_name = tool_args.get("name", "").strip()
                confirm = tool_args.get("confirm")
                res = await self.cron_service.delete_cron_job(name=c_name, confirm=confirm)
                return res.get("message") or json.dumps(res, ensure_ascii=False)

            # ── R6: Email & Notification ──
            if tool_name == "send_email":
                to_addr = tool_args.get("to", "").strip()
                subj = tool_args.get("subject", "").strip()
                body = tool_args.get("body", "")
                attachments = tool_args.get("attachments")
                res = await self.email_report_service.send_email(
                    to=to_addr, subject=subj, body=body, attachments=attachments
                )
                return res.get("message") or json.dumps(res, ensure_ascii=False)

            if tool_name == "generate_report":
                r_type = tool_args.get("report_type", "health")
                period = tool_args.get("period", "today")
                send_to = tool_args.get("send_to_email")
                res = await self.email_report_service.generate_report(
                    report_type=r_type, period=period, send_to_email=send_to
                )
                rep_text = res.get("report_text", "")
                email_note = f"\n\n📧 Đã gửi báo cáo đến: `{send_to}`" if res.get("email_sent") else ""
                return f"{rep_text}{email_note}"

            # ── R7: Network Management ──
            if tool_name == "get_ngrok_status":
                res = await self.network_service.get_ngrok_status()
                return res.get("message") or res.get("summary_text") or json.dumps(res, ensure_ascii=False)

            if tool_name == "restart_ngrok_tunnel":
                tun_name = tool_args.get("tunnel_name")
                confirm = tool_args.get("confirm")
                res = await self.network_service.restart_ngrok_tunnel(tunnel_name=tun_name, confirm=confirm)
                return res.get("message") or json.dumps(res, ensure_ascii=False)

            if tool_name == "get_network_info":
                res = await self.network_service.get_network_info()
                return res.get("summary_text") or json.dumps(res, ensure_ascii=False)

            # ── R8: File Server Manager ──
            if tool_name == "list_files":
                f_path = tool_args.get("path", "/home/kirito")
                pattern = tool_args.get("pattern")
                sort_by = tool_args.get("sort_by", "name")
                res = await self.file_manager_service.list_files(path=f_path, pattern=pattern, sort_by=sort_by)
                return res.get("text") or res.get("message") or json.dumps(res, ensure_ascii=False)

            if tool_name == "read_file_content":
                f_path = tool_args.get("path", "").strip()
                lines_cnt = tool_args.get("lines")
                res = await self.file_manager_service.read_file_content(path=f_path, lines=lines_cnt)
                if res.get("status") == "success":
                    content = res.get("content", "")
                    trunc_note = " (đã cắt bớt vì vượt quá 2000 ký tự)" if res.get("truncated") else ""
                    return f"📄 **Nội dung tệp `{f_path}`**{trunc_note}:\n```\n{content}\n```"
                return f"❌ {res.get('message', 'Lỗi đọc tệp')}"

            if tool_name == "write_file_content":
                f_path = tool_args.get("path", "").strip()
                content = tool_args.get("content", "")
                mode = tool_args.get("mode", "overwrite")
                res = await self.file_manager_service.write_file_content(path=f_path, content=content, mode=mode)
                return res.get("message") or json.dumps(res, ensure_ascii=False)

            if tool_name == "move_or_rename_file":
                src = tool_args.get("src", "").strip()
                dst = tool_args.get("dst", "").strip()
                res = await self.file_manager_service.move_or_rename_file(src=src, dst=dst)
                return res.get("message") or json.dumps(res, ensure_ascii=False)

            if tool_name == "get_disk_usage":
                d_path = tool_args.get("path", "/")
                res = await self.file_manager_service.get_disk_usage(path=d_path)
                if res.get("status") == "success":
                    summary = res.get("summary_text", "")
                    top_items = res.get("top_items", [])
                    item_lines = [f"• `{it['size']}` — `{it['path']}`" for it in top_items]
                    return f"{summary}\n" + "\n".join(item_lines)
                return f"❌ {res.get('message', 'Lỗi phân tích ổ đĩa')}"

            # ── Milestone 3: Security Guardian Tools Dispatch ──
            if tool_name == "get_security_report":
                sec_svc = self.security_monitor_service
                if sec_svc is None:
                    from app.services.security_monitor_service import SecurityMonitorService
                    sec_svc = SecurityMonitorService.get_instance()
                report = await sec_svc.get_security_report()

                status = report.get("current_threat_status", "GREEN")
                status_badges = {
                    "CRITICAL": "🚨 [BÁO ĐỘNG ĐỎ - NGUY HIỂM CAO]",
                    "ORANGE": "🟠 [CẢNH BÁO - ĐANG CÓ TẤN CÔNG]",
                    "YELLOW": "🟡 [CHÚ Ý - CÓ DẤU HIỆU BẤT THƯỜNG]",
                    "GREEN": "🟢 [HỆ THỐNG AN TOÀN - BÌNH THƯỜNG]",
                }
                badge = status_badges.get(status, "🛡️ [GIÁM SÁT AN NINH]")

                lines = [
                    f"{badge} **BÁO CÁO TỔNG QUAN TÌNH TRẠNG AN NINH MÁY CHỦ**\n",
                    f"• Mức độ đe dọa hiện tại: **{status}**",
                    f"• Số lượng IP đang bị khóa trên Firewall: **{report.get('active_blocked_ips_count', 0)} IP**",
                    f"• Tổng số sự kiện tấn công ghi nhận 24h qua: **{report.get('attack_events_24h', {}).get('total_events', 0)} vụ**",
                ]

                by_type = report.get("attack_events_24h", {}).get("by_type", {})
                if by_type:
                    lines.append("\n📊 **Phân loại tấn công 24h qua**:")
                    for atype, cnt in by_type.items():
                        lines.append(f"  - `{atype}`: **{cnt}** lần")

                top_ips = report.get("top_attacking_ips", [])
                if top_ips:
                    lines.append("\n🎯 **Top địa chỉ IP tấn công nhiều nhất**:")
                    for idx, ip_info in enumerate(top_ips, 1):
                        tag = " 🔒 [ĐÃ CHẶN]" if ip_info.get("is_blocked") else (" 🛡️ [WHITELIST]" if ip_info.get("is_whitelisted") else "")
                        lines.append(f"  {idx}. `{ip_info.get('ip')}`: {ip_info.get('attack_count')} lần{tag}")

                prot = report.get("system_protection", {})
                uptime_h = prot.get("uptime_seconds", 0) // 3600
                lines.append(f"\n⚙️ **Hệ thống phòng thủ**: Firewall: `{prot.get('firewall_mode')}` | Uptime Guardian: `{uptime_h}h`")
                return "\n".join(lines)

            if tool_name == "list_blocked_ips":
                sec_svc = self.security_monitor_service
                if sec_svc is None:
                    from app.services.security_monitor_service import SecurityMonitorService
                    sec_svc = SecurityMonitorService.get_instance()
                blocked_list = await sec_svc.list_blocked_ips()
                if not blocked_list:
                    return "🛡️ **Hiện không có địa chỉ IP nào đang bị chặn trên tường lửa máy chủ.** Máy chủ an toàn tuyệt đối."

                lines = [f"🔒 **DANH SÁCH {len(blocked_list)} ĐỊA CHỈ IP ĐANG BỊ KHÓA TRÊN FIREWALL (IPTABLES DROP)**:\n"]
                for idx, rec in enumerate(blocked_list, 1):
                    rem = rec.get("remaining_seconds", 0)
                    rem_str = f"{rem // 3600} giờ {(rem % 3600) // 60} phút" if rem >= 3600 else f"{rem // 60} phút {rem % 60} giây"
                    lines.append(
                        f"{idx}. Địa chỉ IP: `{rec.get('ip')}` (Mức độ: `{rec.get('threat_level', 'HIGH')}`)\n"
                        f"   - Lý do chặn: {rec.get('reason', 'Không có lý do')}\n"
                        f"   - Thời điểm chặn: {rec.get('blocked_at')}\n"
                        f"   - Tự động mở khóa sau: **{rem_str}** (Hết hạn: {rec.get('expires_at')})"
                    )
                return "\n".join(lines)

            if tool_name == "get_honeypot_log":
                hp_svc = self.honeypot_service
                if hp_svc is None:
                    from app.services.honeypot_service import HoneypotService
                    hp_svc = HoneypotService.get_instance()
                limit = max(1, min(int(tool_args.get("limit", 50)), 200))
                svc_param = tool_args.get("service", "all")
                svc_filter = None if svc_param == "all" else svc_param.lower().strip()

                logs = await hp_svc.get_honeypot_log(limit=limit, service=svc_filter)
                stats = hp_svc.get_stats()

                lines = [
                    f"🍯 **BÁO CÁO BẪY HONEYPOT 'KẺ THẤT BẠI' (SSH :2222 & TELNET :23)**\n",
                    f"• Tổng số lần thăm dò (Probes): **{stats.get('total_probes', 0)}**",
                    f"• Tổng số cặp credentials thu hoạch được: **{stats.get('total_credentials', 0)}** (từ {stats.get('unique_ips_count', 0)} IP độc nhất)",
                ]

                if not logs:
                    lines.append("\nHiện chưa có thông tin đăng nhập nào bị bẫy ghi nhận.")
                    return "\n".join(lines)

                lines.append(f"\n📋 **Danh sách {len(logs)} lần thử đăng nhập gần nhất**:")
                for idx, item in enumerate(logs, 1):
                    srv = item.get("service", "unknown").upper()
                    ts = item.get("captured_at", "")
                    ip = item.get("ip", "unknown")
                    user = item.get("username", "<empty>")
                    pwd = item.get("password", "<empty>")
                    lines.append(f"{idx}. `[{srv}]` Lúc {ts} từ IP `{ip}`: User: `{user}` | Pass: `{pwd}` (Lần thử #{item.get('attempt_count', 1)})")

                return "\n".join(lines)

            if tool_name == "get_attack_history":
                sec_svc = self.security_monitor_service
                if sec_svc is None:
                    from app.services.security_monitor_service import SecurityMonitorService
                    sec_svc = SecurityMonitorService.get_instance()
                limit = max(1, min(int(tool_args.get("limit", 50)), 200))
                events = await sec_svc.get_attack_history(limit=limit)

                if not events:
                    return "🛡️ Chưa có sự kiện tấn công mạng nào được ghi nhận trong lịch sử hệ thống."

                lines = [f"⚔️ **LỊCH SỬ {len(events)} SỰ KIỆN TẤN CÔNG GẦN NHẤT PHÁT HIỆN ĐƯỢC**:\n"]
                for idx, ev in enumerate(events, 1):
                    level = ev.get("threat_level", "LOW")
                    atype = ev.get("attack_type", "unknown")
                    ip = ev.get("ip", "unknown")
                    ts = ev.get("timestamp", "")
                    svc = ev.get("target_service", "unknown")
                    action = ev.get("action_taken", "none")
                    act_tag = " [ĐÃ BLOCK 🔒]" if action == "iptables_drop" or "blocked" in action else (" [GIỚI HẠN TỐC ĐỘ ⏱️]" if action == "rate_limited" else "")

                    payload = ev.get("raw_payload", "").strip().replace("\n", " ")
                    payload_str = f"\n     Payload: `{payload[:80]}...`" if payload else ""

                    lines.append(
                        f"{idx}. `[{level}]` **{atype}** từ IP `{ip}`{act_tag}\n"
                        f"   - Thời gian: {ts} | Dịch vụ đích: `{svc}`{payload_str}"
                    )
                return "\n".join(lines)

            if tool_name == "block_ip":
                sec_svc = self.security_monitor_service
                if sec_svc is None:
                    from app.services.security_monitor_service import SecurityMonitorService
                    sec_svc = SecurityMonitorService.get_instance()
                ip = str(tool_args.get("ip", "")).strip()
                reason = str(tool_args.get("reason", "Admin block qua AI Agent")).strip()
                duration = int(tool_args.get("duration_seconds", 86400))

                res = await sec_svc.block_ip(ip=ip, reason=reason, duration_seconds=duration)
                status = res.get("status")

                if status == "veto":
                    return f"🛑 [VETO BẢO VỆ AN TOÀN]: Không thể chặn địa chỉ IP `{ip}`! Địa chỉ này thuộc danh sách IP Whitelist an toàn (Loopback, LAN, Docker, Cloudflare, hoặc IP nhà của anh Mạnh)."
                elif status == "success":
                    hours = duration // 3600
                    return f"🔒 **Đã khóa thành công IP `{ip}` trên tường lửa máy chủ!**\n• Lý do: {reason}\n• Thời hạn hiệu lực: {hours} giờ (tự động mở lúc {res.get('expires_at')})."
                else:
                    return f"❌ Không thể chặn IP `{ip}`: {res.get('message', 'Lỗi không xác định')}"

            if tool_name == "unblock_ip":
                sec_svc = self.security_monitor_service
                if sec_svc is None:
                    from app.services.security_monitor_service import SecurityMonitorService
                    sec_svc = SecurityMonitorService.get_instance()
                ip = str(tool_args.get("ip", "")).strip()

                res = await sec_svc.unblock_ip(ip=ip, reason="Admin yêu cầu gỡ chặn qua AI Agent")
                if res.get("status") == "success":
                    return f"🔓 **Đã gỡ bỏ thành công lệnh chặn đối với IP `{ip}` trên tường lửa máy chủ.** Địa chỉ IP này hiện đã có thể kết nối lại bình thường."
                else:
                    return f"❌ Lỗi khi gỡ chặn IP `{ip}`: {res.get('message', 'Lỗi không xác định')}"

            # ── Milestone 2 Professional Video Editor Dispatchers ──
            if tool_name == "remove_text_from_video":
                in_target = str(tool_args.get("input_path_or_url", "")).strip()
                region = tool_args.get("region")
                mode = str(tool_args.get("mode", "delogo")).strip().lower()
                out_format = str(tool_args.get("output_format", "mp4")).strip()
                res = await self.video_editor_service.remove_text_from_video(
                    input_path_or_url=in_target,
                    region=region,
                    mode=mode,
                    output_format=out_format,
                )
                if res.get("status") == "ok":
                    r = res.get("region", {})
                    msg = (
                        f"✨ **Xóa text/watermark video thành công!**\n"
                        f"• Chế độ áp dụng: `{res.get('mode_used', mode)}` (yêu cầu: `{res.get('mode_requested', mode)}`)\n"
                        f"• Tọa độ vùng xóa: `x={r.get('x')}, y={r.get('y')}, w={r.get('w')}, h={r.get('h')}`\n"
                        f"• Dung lượng tệp: {res.get('file_size_formatted', 'N/A')}\n"
                        f"• Đường dẫn: `{res.get('output_path', '')}`"
                    )
                    if res.get("delivery") == "direct":
                        msg += "\n• Phương thức: Sẵn sàng gửi trực tiếp qua Telegram (<= 50MB)."
                    elif res.get("internet_url"):
                        msg += f"\n• Link tải trực tiếp (Dual-Delivery): {res.get('internet_url')}"
                    return msg
                return f"❌ Lỗi khi xóa text video: {res.get('message', 'Không rõ nguyên nhân')}"

            if tool_name == "add_subtitle_to_video":
                in_target = str(tool_args.get("input_path_or_url", "")).strip()
                sub_input = str(tool_args.get("subtitle_text_or_path", "")).strip()
                style = tool_args.get("style")
                pos = str(tool_args.get("position", "bottom")).strip()
                out_format = str(tool_args.get("output_format", "mp4")).strip()
                res = await self.video_editor_service.add_subtitle_to_video(
                    input_path_or_url=in_target,
                    subtitle_text_or_path=sub_input,
                    style=style,
                    position=pos,
                    output_format=out_format,
                )
                if res.get("status") == "ok":
                    msg = (
                        f"📝 **Gắn phụ đề vào video thành công!**\n"
                        f"• Vị trí phụ đề: `{res.get('position', pos)}`\n"
                        f"• Dung lượng tệp: {res.get('file_size_formatted', 'N/A')}\n"
                        f"• Đường dẫn: `{res.get('output_path', '')}`"
                    )
                    if res.get("delivery") == "direct":
                        msg += "\n• Phương thức: Sẵn sàng gửi trực tiếp qua Telegram (<= 50MB)."
                    elif res.get("internet_url"):
                        msg += f"\n• Link tải trực tiếp (Dual-Delivery): {res.get('internet_url')}"
                    return msg
                return f"❌ Lỗi khi gắn phụ đề video: {res.get('message', 'Không rõ nguyên nhân')}"

            if tool_name == "apply_color_grade":
                in_target = str(tool_args.get("input_path_or_url", "")).strip()
                preset = str(tool_args.get("preset", "vivid")).strip()
                custom_eq = tool_args.get("custom_eq")
                out_format = str(tool_args.get("output_format", "mp4")).strip()
                res = await self.video_editor_service.apply_color_grade(
                    input_path_or_url=in_target,
                    preset=preset,
                    custom_eq=custom_eq,
                    output_format=out_format,
                )
                if res.get("status") == "ok":
                    msg = (
                        f"🎨 **Chỉnh màu video thành công!**\n"
                        f"• Bộ lọc preset: `{res.get('preset', preset)}`\n"
                        f"• Dung lượng tệp: {res.get('file_size_formatted', 'N/A')}\n"
                        f"• Đường dẫn: `{res.get('output_path', '')}`"
                    )
                    if res.get("delivery") == "direct":
                        msg += "\n• Phương thức: Sẵn sàng gửi trực tiếp qua Telegram (<= 50MB)."
                    elif res.get("internet_url"):
                        msg += f"\n• Link tải trực tiếp (Dual-Delivery): {res.get('internet_url')}"
                    return msg
                return f"❌ Lỗi khi chỉnh màu video: {res.get('message', 'Không rõ nguyên nhân')}"

            if tool_name == "stabilize_video":
                in_target = str(tool_args.get("input_path_or_url", "")).strip()
                smoothing = int(tool_args.get("smoothing", 10))
                out_format = str(tool_args.get("output_format", "mp4")).strip()
                res = await self.video_editor_service.stabilize_video(
                    input_path_or_url=in_target,
                    smoothing=smoothing,
                    output_format=out_format,
                )
                if res.get("status") == "ok":
                    msg = (
                        f"🛡️ **Ổn định chống rung video 2-pass thành công!**\n"
                        f"• Độ mượt smoothing: {res.get('smoothing', smoothing)}\n"
                        f"• Dung lượng tệp: {res.get('file_size_formatted', 'N/A')}\n"
                        f"• Đường dẫn: `{res.get('output_path', '')}`"
                    )
                    if res.get("delivery") == "direct":
                        msg += "\n• Phương thức: Sẵn sàng gửi trực tiếp qua Telegram (<= 50MB)."
                    elif res.get("internet_url"):
                        msg += f"\n• Link tải trực tiếp (Dual-Delivery): {res.get('internet_url')}"
                    return msg
                return f"❌ Lỗi khi chống rung video: {res.get('message', 'Không rõ nguyên nhân')}"

            if tool_name == "concatenate_videos":
                in_paths = tool_args.get("input_paths", [])
                out_format = str(tool_args.get("output_format", "mp4")).strip()
                reencode = bool(tool_args.get("reencode", False))
                res = await self.video_editor_service.concatenate_videos(
                    input_paths=in_paths,
                    output_format=out_format,
                    reencode=reencode,
                )
                if res.get("status") == "ok":
                    msg = (
                        f"🎞️ **Ghép nối {res.get('clips_count', len(in_paths))} video thành công!**\n"
                        f"• Chế độ nén: {'Re-encode chất lượng cao' if res.get('reencode') else 'Stream copy siêu tốc'}\n"
                        f"• Dung lượng tệp: {res.get('file_size_formatted', 'N/A')}\n"
                        f"• Đường dẫn: `{res.get('output_path', '')}`"
                    )
                    if res.get("delivery") == "direct":
                        msg += "\n• Phương thức: Sẵn sàng gửi trực tiếp qua Telegram (<= 50MB)."
                    elif res.get("internet_url"):
                        msg += f"\n• Link tải trực tiếp (Dual-Delivery): {res.get('internet_url')}"
                    return msg
                return f"❌ Lỗi khi ghép video: {res.get('message', 'Không rõ nguyên nhân')}"

            if tool_name == "extract_frames":
                in_target = str(tool_args.get("input_path_or_url", "")).strip()
                interval = float(tool_args.get("interval_seconds", 1.0))
                out_fmt = str(tool_args.get("output_format", "jpg")).strip()
                quality = int(tool_args.get("quality", 2))
                res = await self.video_editor_service.extract_frames(
                    input_path_or_url=in_target,
                    interval_seconds=interval,
                    output_format=out_fmt,
                    quality=quality,
                )
                if res.get("status") == "ok":
                    msg = (
                        f"📸 **Trích xuất frames video thành công!**\n"
                        f"• Số lượng frames: {res.get('frames_count', 0)}\n"
                        f"• Chu kỳ trích xuất: mỗi {res.get('interval_seconds', interval)}s\n"
                        f"• Tệp nén ZIP: `{res.get('zip_path', '')}`\n"
                        f"• Dung lượng ZIP: {res.get('file_size_formatted', 'N/A')}"
                    )
                    if res.get("delivery") == "direct":
                        msg += "\n• Phương thức: Sẵn sàng gửi trực tiếp qua Telegram (<= 50MB)."
                    elif res.get("internet_url"):
                        msg += f"\n• Link tải trực tiếp (Dual-Delivery): {res.get('internet_url')}"
                    return msg
                return f"❌ Lỗi khi trích xuất frames: {res.get('message', 'Không rõ nguyên nhân')}"

            if tool_name == "remove_watermark_region":
                in_target = str(tool_args.get("input_path_or_url", "")).strip()
                regions = tool_args.get("regions", [])
                out_format = str(tool_args.get("output_format", "mp4")).strip()
                res = await self.video_editor_service.remove_watermark_region(
                    input_path_or_url=in_target,
                    regions=regions,
                    output_format=out_format,
                )
                if res.get("status") == "ok":
                    msg = (
                        f"🧹 **Xóa {res.get('regions_count', len(regions))} vùng watermark thành công!**\n"
                        f"• Bộ lọc áp dụng: Chained delogo filter\n"
                        f"• Dung lượng tệp: {res.get('file_size_formatted', 'N/A')}\n"
                        f"• Đường dẫn: `{res.get('output_path', '')}`"
                    )
                    if res.get("delivery") == "direct":
                        msg += "\n• Phương thức: Sẵn sàng gửi trực tiếp qua Telegram (<= 50MB)."
                    elif res.get("internet_url"):
                        msg += f"\n• Link tải trực tiếp (Dual-Delivery): {res.get('internet_url')}"
                    return msg
                return f"❌ Lỗi khi xóa nhiều watermark: {res.get('message', 'Không rõ nguyên nhân')}"

            if tool_name == "enhance_video_quality":
                in_target = str(tool_args.get("input_path_or_url", "")).strip()
                preset = str(tool_args.get("preset", "sharpen")).strip()
                out_format = str(tool_args.get("output_format", "mp4")).strip()
                res = await self.video_editor_service.enhance_video_quality(
                    input_path_or_url=in_target,
                    preset=preset,
                    output_format=out_format,
                )
                if res.get("status") == "ok":
                    msg = (
                        f"🚀 **Nâng cấp chất lượng video thành công!**\n"
                        f"• Bộ lọc: `{res.get('preset', preset)}`\n"
                        f"• Dung lượng tệp: {res.get('file_size_formatted', 'N/A')}\n"
                        f"• Đường dẫn: `{res.get('output_path', '')}`"
                    )
                    if res.get("delivery") == "direct":
                        msg += "\n• Phương thức: Sẵn sàng gửi trực tiếp qua Telegram (<= 50MB)."
                    elif res.get("internet_url"):
                        msg += f"\n• Link tải trực tiếp (Dual-Delivery): {res.get('internet_url')}"
                    return msg
                return f"❌ Lỗi khi nâng cấp chất lượng video: {res.get('message', 'Không rõ nguyên nhân')}"

            if tool_name == "generate_video_thumbnail":
                in_target = str(tool_args.get("input_path_or_url", "")).strip()
                ts = float(tool_args.get("timestamp", 0.0))
                w = int(tool_args.get("width", 320))
                h = int(tool_args.get("height", 240))
                out_fmt = str(tool_args.get("output_format", "jpg")).strip()
                res = await self.video_editor_service.generate_video_thumbnail(
                    input_path_or_url=in_target,
                    timestamp=ts,
                    width=w,
                    height=h,
                    output_format=out_fmt,
                )
                if res.get("status") == "ok":
                    out_path = res.get("output_path", "")
                    if pending_photos is not None and out_path:
                        pending_photos.clear()
                        pending_photos.append((f"Thumbnail video ({ts}s)", out_path))
                    return (
                        f"🖼️ **Tạo ảnh thumbnail video thành công!**\n"
                        f"• Mốc thời gian: {ts}s\n"
                        f"• Kích thước: {res.get('width', w)}x{res.get('height', h)} px\n"
                        f"• Dung lượng: {res.get('file_size_formatted', 'N/A')}\n"
                        f"• Đường dẫn tệp: `{out_path}`"
                    )
                return f"❌ Lỗi khi tạo thumbnail video: {res.get('message', 'Không rõ nguyên nhân')}"

            # ── M6 Omni Super-Agent Dispatchers (R1 - R4) ──
            if tool_name == "edit_video_clip":
                in_target = str(tool_args.get("input_path_or_url", "")).strip()
                start_time = str(tool_args.get("start_time", "00:00:00")).strip()
                duration = tool_args.get("duration")
                out_format = str(tool_args.get("output_format", "mp4")).strip()
                reencode = bool(tool_args.get("reencode", False))
                res = await self.multimedia_service.edit_video_clip(
                    input_path_or_url=in_target,
                    start_time=start_time,
                    duration=str(duration) if duration is not None else None,
                    output_format=out_format,
                    reencode=reencode,
                )
                if res.get("status") == "ok":
                    msg = (
                        f"✂️ **Cắt clip video thành công!**\n"
                        f"• Thời lượng: {res.get('duration_processed', duration)}s\n"
                        f"• Định dạng: {res.get('output_format', out_format)}\n"
                        f"• Dung lượng: {res.get('file_size_formatted', 'N/A')}\n"
                        f"• Đường dẫn: `{res.get('output_path', '')}`"
                    )
                    if res.get("delivery") == "direct":
                        msg += "\n• Phương thức: Sẵn sàng gửi trực tiếp qua Telegram (<= 50MB)."
                    elif res.get("public_url"):
                        msg += f"\n• Link tải trực tiếp (Dual-Delivery): {res.get('public_url')}"
                    return msg
                return f"❌ Lỗi khi cắt clip video: {res.get('message', 'Không rõ nguyên nhân')}"

            if tool_name == "compress_video":
                in_target = str(tool_args.get("input_path_or_url", "")).strip()
                target_mb = float(tool_args.get("target_size_mb", 48.0))
                res = await self.multimedia_service.compress_video(
                    input_path_or_url=in_target,
                    target_size_mb=target_mb,
                )
                if res.get("status") == "ok":
                    return (
                        f"🗜️ **Nén video thành công qua FFmpeg 2-pass bitrate!**\n"
                        f"• Dung lượng ban đầu: {res.get('original_size_formatted', 'N/A')}\n"
                        f"• Dung lượng sau nén: {res.get('compressed_size_formatted', 'N/A')} (< {target_mb}MB)\n"
                        f"• Tỷ lệ giảm: {res.get('compression_ratio', 'N/A')}\n"
                        f"• Video Bitrate: {res.get('video_bitrate_kbps', 'N/A')} kbps\n"
                        f"• Đường dẫn: `{res.get('output_path', '')}`\n"
                        f"• Trạng thái: Đã tối ưu hoàn hảo để gửi qua Telegram."
                    )
                return f"❌ Lỗi khi nén video: {res.get('message', 'Không rõ nguyên nhân')}"

            if tool_name == "convert_video_format":
                in_target = str(tool_args.get("input_path_or_url", "")).strip()
                target_fmt = str(tool_args.get("target_format", "mp4")).strip()
                preset = str(tool_args.get("preset", "fast")).strip()
                res = await self.multimedia_service.convert_video_format(
                    input_path_or_url=in_target,
                    target_format=target_fmt,
                    preset=preset,
                )
                if res.get("status") == "ok":
                    return (
                        f"🔄 **Chuyển đổi định dạng video thành công!**\n"
                        f"• Định dạng đích: **{target_fmt.upper()}**\n"
                        f"• Dung lượng tệp: {res.get('file_size_formatted', 'N/A')}\n"
                        f"• Đường dẫn: `{res.get('output_path', '')}`"
                    )
                return f"❌ Lỗi khi chuyển đổi video: {res.get('message', 'Không rõ nguyên nhân')}"

            if tool_name == "convert_audio_format":
                in_target = str(tool_args.get("input_path_or_url", "")).strip()
                target_fmt = str(tool_args.get("target_format", "mp3")).strip()
                bitrate = str(tool_args.get("bitrate", "320k")).strip()
                res = await self.multimedia_service.convert_audio_format(
                    input_path_or_url=in_target,
                    target_format=target_fmt,
                    bitrate=bitrate,
                )
                if res.get("status") == "ok":
                    return (
                        f"🎵 **Chuyển đổi âm thanh chuyên nghiệp thành công!**\n"
                        f"• Định dạng: **{target_fmt.upper()}** ({bitrate})\n"
                        f"• Dung lượng: {res.get('file_size_formatted', 'N/A')}\n"
                        f"• Đường dẫn: `{res.get('output_path', '')}`"
                    )
                return f"❌ Lỗi khi chuyển đổi âm thanh: {res.get('message', 'Không rõ nguyên nhân')}"

            if tool_name == "trim_audio_clip":
                in_target = str(tool_args.get("input_path_or_url", "")).strip()
                start_time = str(tool_args.get("start_time", "00:00:00")).strip()
                duration = tool_args.get("duration")
                res = await self.multimedia_service.trim_audio_clip(
                    input_path_or_url=in_target,
                    start_time=start_time,
                    duration=str(duration) if duration is not None else None,
                )
                if res.get("status") == "ok":
                    return (
                        f"✂️ **Cắt đoạn âm thanh / nhạc chuông thành công!**\n"
                        f"• Mốc bắt đầu: {start_time}\n"
                        f"• Thời lượng: {duration}s\n"
                        f"• Dung lượng: {res.get('file_size_formatted', 'N/A')}\n"
                        f"• Đường dẫn: `{res.get('output_path', '')}`"
                    )
                return f"❌ Lỗi khi cắt âm thanh: {res.get('message', 'Không rõ nguyên nhân')}"

            if tool_name == "normalize_audio_volume":
                in_target = str(tool_args.get("input_path_or_url", "")).strip()
                res = await self.multimedia_service.normalize_audio_volume(
                    input_path_or_url=in_target,
                )
                if res.get("status") == "ok":
                    return (
                        f"🔊 **Chuẩn hóa âm lượng EBU R128 thành công!**\n"
                        f"• Chuẩn áp dụng: EBU R128 (loudnorm filter)\n"
                        f"• Đường dẫn: `{res.get('output_path', '')}`\n"
                        f"• Dung lượng: {res.get('file_size_formatted', 'N/A')}"
                    )
                return f"❌ Lỗi khi chuẩn hóa âm lượng: {res.get('message', 'Không rõ nguyên nhân')}"

            if tool_name == "convert_and_resize_image":
                in_target = str(tool_args.get("input_path_or_url", "")).strip()
                fmt = str(tool_args.get("format", "webp")).strip()
                max_w = tool_args.get("max_width")
                max_h = tool_args.get("max_height")
                quality = int(tool_args.get("quality", 85))
                res = await self.multimedia_service.convert_and_resize_image(
                    input_path_or_url=in_target,
                    format=fmt,
                    max_width=int(max_w) if max_w is not None else None,
                    max_height=int(max_h) if max_h is not None else None,
                    quality=quality,
                )
                if res.get("status") == "ok":
                    return (
                        f"🖼️ **Xử lý hình ảnh thành công!**\n"
                        f"• Định dạng: **{fmt.upper()}** (Chất lượng: {quality}%)\n"
                        f"• Kích thước: {res.get('width', 'N/A')}x{res.get('height', 'N/A')} px\n"
                        f"• Dung lượng: {res.get('file_size_formatted', 'N/A')}\n"
                        f"• Đường dẫn: `{res.get('output_path', '')}`"
                    )
                return f"❌ Lỗi khi xử lý ảnh: {res.get('message', 'Không rõ nguyên nhân')}"

            if tool_name == "generate_custom_qr":
                content = str(tool_args.get("content", "")).strip()
                label = tool_args.get("label")
                fill_c = str(tool_args.get("fill_color", "#0f172a")).strip()
                back_c = str(tool_args.get("back_color", "#ffffff")).strip()
                res = await self.multimedia_service.generate_custom_qr(
                    content=content,
                    label=str(label) if label else None,
                    fill_color=fill_c,
                    back_color=back_c,
                )
                if res.get("status") == "ok":
                    out_path = res.get("output_path", "")
                    if pending_photos is not None and out_path:
                        pending_photos.clear()
                        pending_photos.append((f"Mã QR: {label or content[:30]}", out_path))
                    return (
                        f"📱 **Sinh mã QR Code độ nét cao thành công!**\n"
                        f"• Nội dung: `{content[:100]}{'...' if len(content) > 100 else ''}`\n"
                        f"• Nhãn chú thích: {label or 'Không có'}\n"
                        f"• Kích thước: {res.get('width', 0)}x{res.get('height', 0)} px\n"
                        f"• Đường dẫn tệp: `{out_path}`"
                    )
                return f"❌ Lỗi khi sinh mã QR: {res.get('message', 'Không rõ nguyên nhân')}"

            if tool_name == "merge_pdf_documents":
                files = tool_args.get("file_paths", [])
                out_name = tool_args.get("output_name")
                res = await self.document_service.merge_pdf_documents(
                    file_paths=files,
                    output_name=out_name,
                )
                if res.get("status") == "ok":
                    return (
                        f"📑 **Gộp tệp PDF thành công!**\n"
                        f"• Số lượng tệp đã gộp: {res.get('total_files_merged', len(files))}\n"
                        f"• Tổng số trang: {res.get('total_pages', 'N/A')}\n"
                        f"• Dung lượng: {res.get('file_size_formatted', 'N/A')}\n"
                        f"• Đường dẫn: `{res.get('output_path', '')}`"
                    )
                return f"❌ Lỗi khi gộp tệp PDF: {res.get('message', 'Không rõ nguyên nhân')}"

            if tool_name == "split_pdf_document":
                fpath = str(tool_args.get("file_path", "")).strip()
                ranges = str(tool_args.get("page_ranges", "")).strip()
                out_name = tool_args.get("output_name")
                res = await self.document_service.split_pdf_document(
                    file_path=fpath,
                    page_ranges=ranges,
                    output_name=out_name,
                )
                if res.get("status") == "ok":
                    return (
                        f"📄 **Tách trang PDF thành công!**\n"
                        f"• Các trang đã trích xuất: `{res.get('pages_extracted', ranges)}`\n"
                        f"• Tổng số trang trích xuất: {res.get('total_pages_extracted', 'N/A')}\n"
                        f"• Dung lượng: {res.get('file_size_formatted', 'N/A')}\n"
                        f"• Đường dẫn: `{res.get('output_path', '')}`"
                    )
                return f"❌ Lỗi khi tách trang PDF: {res.get('message', 'Không rõ nguyên nhân')}"

            if tool_name == "extract_document_text":
                fpath = str(tool_args.get("file_path", "")).strip()
                max_chars = int(tool_args.get("max_characters", 10000))
                res = await self.document_service.extract_document_text(
                    file_path=fpath,
                    max_chars=max_chars,
                )
                if res.get("status") == "ok":
                    content = res.get("text", "")
                    trunc_note = f"\n\n*(Đã trích xuất {len(content)} ký tự)*"
                    return f"📖 **NỘI DUNG TÀI LIỆU `{res.get('file_name', fpath)}`**:\n\n{content[:max_chars]}{trunc_note}"
                return f"❌ Lỗi khi đọc tài liệu: {res.get('message', 'Không rõ nguyên nhân')}"

            if tool_name == "translate_text":
                text = str(tool_args.get("text", "")).strip()
                target_lang = str(tool_args.get("target_lang", "vi")).strip()
                source_lang = str(tool_args.get("source_lang", "auto")).strip()
                res = await self.document_service.translate_text(
                    text=text,
                    target_lang=target_lang,
                    source_lang=source_lang,
                )
                if res.get("status") == "ok":
                    return (
                        f"🌐 **BẢN DỊCH ({res.get('source_lang', source_lang).upper()} ➔ {target_lang.upper()})**:\n\n"
                        f"{res.get('translated_text', '')}"
                    )
                return f"❌ Lỗi khi dịch văn bản: {res.get('message', 'Không rõ nguyên nhân')}"

            if tool_name == "inspect_media_metadata":
                fpath = str(tool_args.get("file_path_or_url", "")).strip()
                res = await self.document_service.inspect_media_metadata(
                    file_path_or_url=fpath,
                )
                if res.get("status") == "ok":
                    meta = res.get("metadata", {})
                    mtype = res.get("media_type", "media")
                    lines = [f"🔍 **SIÊU DỮ LIỆU KỸ THUẬT ({mtype.upper()})**:\n• Đường dẫn: `{fpath}`"]
                    if res.get("file_size_formatted"):
                        lines.append(f"• Dung lượng: {res.get('file_size_formatted')}")
                    if "duration_sec" in meta:
                        lines.append(f"• Thời lượng: {meta.get('duration_sec')}s")
                    if "width" in meta and "height" in meta:
                        lines.append(f"• Độ phân giải: {meta.get('width')}x{meta.get('height')}")
                    if "codec_name" in meta:
                        lines.append(f"• Codec: {meta.get('codec_name')}")
                    if "bitrate_kbps" in meta:
                        lines.append(f"• Bitrate: {meta.get('bitrate_kbps')} kbps")
                    if "fps" in meta:
                        lines.append(f"• Tốc độ khung hình (FPS): {meta.get('fps')}")
                    if "channels" in meta:
                        lines.append(f"• Kênh âm thanh: {meta.get('channels')} ({meta.get('sample_rate', '')} Hz)")
                    if "exif" in meta and meta["exif"]:
                        lines.append("• Thông tin EXIF máy ảnh:")
                        for ek, ev in list(meta["exif"].items())[:5]:
                            lines.append(f"  - {ek}: {ev}")
                    return "\n".join(lines)
                return f"❌ Lỗi khi trích xuất siêu dữ liệu: {res.get('message', 'Không rõ nguyên nhân')}"

            if tool_name == "download_direct_file":
                url = str(tool_args.get("url", "")).strip()
                c_name = tool_args.get("custom_filename")
                res = await self.universal_downloader.download_direct_file(
                    url=url,
                    custom_filename=c_name,
                )
                if res.get("status") == "success":
                    return (
                        f"📥 **Tải tệp thành công từ Internet!**\n"
                        f"• Tên tệp: **{res.get('filename', '')}**\n"
                        f"• Dung lượng: {res.get('file_size_formatted', 'N/A')}\n"
                        f"• Tốc độ trung bình: {res.get('speed_formatted', 'N/A')}\n"
                        f"• Thời gian tải: {res.get('elapsed_seconds', 'N/A')}s\n"
                        f"• Đường dẫn lưu trữ: `{res.get('file_path', '')}`\n"
                        f"• Resume hỗ trợ: {'Có' if res.get('resumed') else 'Không'}"
                    )
                return f"❌ Lỗi khi tải tệp: {res.get('message', 'Không rõ nguyên nhân')}"

            if tool_name == "extract_clean_web_article":
                url = str(tool_args.get("url", "")).strip()
                res = await self.web_article_extractor.extract_clean_web_article(url=url)
                if res.get("status") == "success":
                    title = res.get("title", "Bài viết không tiêu đề")
                    author = res.get("author")
                    pdate = res.get("publish_date")
                    wcount = res.get("word_count", 0)
                    rtime = res.get("reading_time_min", 0)
                    content = res.get("markdown_content", "")

                    header_lines = [f"📰 **{title}**"]
                    if author:
                        header_lines.append(f"• Tác giả: {author}")
                    if pdate:
                        header_lines.append(f"• Thời gian: {pdate}")
                    header_lines.append(f"• Độ dài: ~{wcount} từ (khoảng {rtime} phút đọc)")
                    header_lines.append(f"• Nguồn: {url}")
                    header_lines.append("\n---\n")
                    header_lines.append(content[:15000])
                    if len(content) > 15000:
                        header_lines.append("\n\n*(Nội dung bài viết quá dài, đã hiển thị 15.000 ký tự đầu tiên)*")
                    return "\n".join(header_lines)
                return f"❌ Lỗi khi bóc tách bài viết: {res.get('message', 'Không rõ nguyên nhân')}"

            if tool_name == "execute_system_script":
                script_code = str(tool_args.get("script_code", "")).strip()
                interp = str(tool_args.get("interpreter", "bash")).strip()
                timeout = int(tool_args.get("timeout_seconds", 60))
                confirm = tool_args.get("confirm")

                veto_err = evaluate_spinal_safety_veto(script_code, confirm)
                if veto_err:
                    return veto_err

                res = await self.system_mastery_service.execute_system_script(
                    script_code=script_code,
                    interpreter=interp,
                    timeout=timeout,
                )
                if res.get("status") == "success":
                    return (
                        f"⚙️ **Thực thi script {res.get('interpreter')} thành công (exit code {res.get('exit_code')})!**\n"
                        f"• Thời gian chạy: {res.get('execution_time_ms', 0)} ms\n"
                        f"• Kết quả xuất ra (stdout/stderr):\n```\n{res.get('output', '').strip()}\n```"
                    )
                return (
                    f"❌ **Thực thi script {res.get('interpreter')} thất bại (exit code {res.get('exit_code', -1)})!**\n"
                    f"• {res.get('message', '')}\n"
                    f"```\n{res.get('output', '').strip()}\n```"
                )

            if tool_name == "manage_docker_containers":
                action = str(tool_args.get("action", "")).strip()
                c_name = tool_args.get("container_name")
                force = bool(tool_args.get("force", False))
                res = await self.system_mastery_service.manage_docker_containers(
                    action=action,
                    container_name=c_name,
                    force=force,
                )
                if res.get("status") == "success":
                    out_text = res.get("output", "").strip()
                    lines = [f"🐳 **Quản lý Docker ({action.upper()}) thành công!**"]
                    if c_name:
                        lines.append(f"• Container: `{c_name}`")
                    if out_text:
                        lines.append(f"• Kết quả:\n```\n{out_text[:3000]}\n```")
                    return "\n".join(lines)
                return f"❌ Lỗi quản lý Docker ({action}): {res.get('message', 'Không rõ nguyên nhân')}"

            if tool_name == "optimize_system_resources":
                res = await self.system_mastery_service.optimize_system_resources()
                if res.get("status") == "success":
                    freed = res.get("freed", {})
                    after = res.get("after", {})
                    steps = res.get("steps_executed", [])
                    steps_formatted = "\n".join([f"  • {s}" for s in steps])
                    return (
                        f"🚀 **Tối ưu hóa tài nguyên máy chủ hoàn tất ({res.get('execution_time_sec', 0)}s)!**\n"
                        f"• RAM khả dụng hiện tại: **{after.get('ram_available_mb', 0)} MB** (Đã giải phóng ~{freed.get('ram_freed_mb', 0)} MB)\n"
                        f"• Dung lượng đĩa trống: **{after.get('disk_available_mb', 0)} MB** (Đã thu hồi ~{freed.get('disk_freed_mb', 0)} MB)\n"
                        f"• Các bước tự động đã thực hiện:\n{steps_formatted}"
                    )
                return f"❌ Lỗi khi tối ưu hóa tài nguyên: {res.get('message', 'Không rõ nguyên nhân')}"

            # ── R4: Autonomous Goal Management ──
            if tool_name == "create_autonomous_goal":
                goal_desc = str(tool_args.get("goal", "")).strip()
                trigger = tool_args.get("trigger_condition")
                worker = self.autonomous_goal_worker
                if worker and hasattr(worker, "create_goal"):
                    try:
                        res = await worker.create_goal(goal=goal_desc, trigger_condition=trigger, chat_id=chat_id)
                        if isinstance(res, dict):
                            task_id = res.get("id") or res.get("task_id") or "N/A"
                        elif isinstance(res, str):
                            task_id = res
                        else:
                            task_id = str(res)
                        return (
                            f"🎯 **ĐÃ THIẾT LẬP MỤC TIÊU TỰ HÀNH**: `#{task_id}`\n"
                            f"• **Mục tiêu**: {goal_desc}\n"
                            f"• **Điều kiện kích hoạt**: {trigger or 'Thực thi ngay'}\n"
                            f"• **Trạng thái**: Đã lập kế hoạch và chuyển giao cho Autonomous Goal Worker theo dõi ngầm."
                        )
                    except Exception as e:
                        logger.warning("[AiAgent] worker.create_goal error: %s", e)
                        return f"❌ Lỗi khi thiết lập mục tiêu tự hành: {e}"

                import uuid as _uuid
                task_id = f"goal_{_uuid.uuid4().hex[:8]}"
                return (
                    f"🎯 **ĐÃ THIẾT LẬP MỤC TIÊU TỰ HÀNH**: `#{task_id}`\n"
                    f"• **Mục tiêu**: {goal_desc}\n"
                    f"• **Điều kiện kích hoạt**: {trigger or 'Thực thi ngay'}\n"
                    f"• **Trạng thái**: Đã lập kế hoạch và chuyển giao cho Autonomous Goal Worker theo dõi ngầm."
                )

            if tool_name == "list_autonomous_goals":
                s_filter = tool_args.get("status_filter", "active")
                worker = self.autonomous_goal_worker
                if worker and hasattr(worker, "list_goals"):
                    try:
                        query_status = None if s_filter in ("active", "all", None) else s_filter
                        goals = await worker.list_goals(status=query_status)
                        if isinstance(goals, list):
                            if s_filter == "active":
                                goals = [g for g in goals if g.get("status") in ("pending", "running", "waiting_approval")]
                            if not goals:
                                return "📋 Hiện không có mục tiêu tự hành nào đang chạy ngầm trên máy chủ."
                            lines = [f"📋 **DANH SÁCH MỤC TIÊU TỰ HÀNH ({len(goals)} mục tiêu)**:"]
                            for g in goals:
                                gid = g.get("id", "N/A")
                                gdesc = g.get("goal", "")
                                gst = g.get("status", "unknown")
                                gstep = g.get("current_step", 0)
                                total_steps = len(g.get("steps", []))
                                gtrig = g.get("trigger_condition") or "immediate"
                                lines.append(f"• `#{gid}` [{gst.upper()} - Bước {gstep}/{total_steps}]: \"{gdesc}\" (Kích hoạt: {gtrig})")
                            return "\n".join(lines)
                        elif isinstance(goals, dict):
                            return json.dumps(goals, ensure_ascii=False, indent=2)
                        return str(goals)
                    except Exception as e:
                        logger.warning("[AiAgent] worker.list_goals error: %s", e)
                        return f"❌ Lỗi khi lấy danh sách mục tiêu: {e}"
                return "📋 Hiện không có mục tiêu tự hành nào đang chạy ngầm trên máy chủ."

            if tool_name == "cancel_autonomous_goal":
                g_id = str(tool_args.get("goal_id", "")).strip()
                worker = self.autonomous_goal_worker
                if worker and hasattr(worker, "cancel_goal"):
                    try:
                        ok = await worker.cancel_goal(goal_id=g_id)
                        if isinstance(ok, bool):
                            if ok:
                                return f"✅ Đã hủy bỏ mục tiêu tự hành `#{g_id}` thành công."
                            return f"⚠️ Không thể hủy mục tiêu `#{g_id}` (Mục tiêu không tồn tại hoặc đã ở trạng thái kết thúc)."
                        elif isinstance(ok, dict):
                            return json.dumps(ok, ensure_ascii=False)
                        return str(ok)
                    except Exception as e:
                        logger.warning("[AiAgent] worker.cancel_goal error: %s", e)
                        return f"❌ Lỗi khi hủy mục tiêu `{g_id}`: {e}"
                return f"⚠️ Autonomous Goal Worker chưa sẵn sàng. Không thể hủy mục tiêu `#{g_id}`."

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
    _DIRECT_RETURN_TOOLS = DIRECT_RETURN_TOOLS

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
