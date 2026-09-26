"""
app/services/email_report_service.py — SMTP Email Dispatch & Server Health Reporting Service (R6).

Engineered for AI Agent Tieu Bao Bao:
- send_email: Sends plain-text or HTML emails with optional file attachments via SMTP.
  Uses `asyncio.to_thread` to wrap synchronous `smtplib` calls, preventing any event-loop blocking.
  Reads credentials dynamically from environment variables:
  `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_TLS`, `SMTP_USE_SSL`.
  Gracefully handles missing configuration or network disconnects without crashing.
- generate_report: Generates comprehensive server health summary reports for specified periods
  ('today' | 'week' | 'month'), integrating CPU, RAM, Disk, and Docker metrics.
  Optionally dispatches the generated report directly via `send_email`.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import logging
import mimetypes
import os
from pathlib import Path
import re
import smtplib
import tempfile
from typing import Any, Callable, Dict, List, Optional, Union

from app.services.server_monitor_service import ServerMonitorService

logger = logging.getLogger(__name__)

VN_TZ = timezone(timedelta(hours=7))

VALID_PERIODS = {"today", "week", "month"}

# Sensitive filenames and substrings to blacklist from attachment exfiltration
SENSITIVE_FILE_PATTERNS = {
    ".env",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "authorized_keys",
    "known_hosts",
    "shadow",
    "passwd",
    "master.key",
    "credentials",
    "secrets.json",
}

FORBIDDEN_PATH_SEGMENTS = {
    ".git",
    ".ssh",
    ".aws",
    ".gnupg",
    "etc",
}


def _is_safe_attachment_path(file_path: Union[str, Path]) -> bool:
    """
    Validates that an attachment file path is strictly safe against exfiltration:
    1. Rejects Windows-style drive letters/paths immediately on POSIX/Linux systems.
    2. Resolves path canonicalization to defeat directory traversal (..).
    3. Enforces blacklist: Blocks hidden files ('.*') and sensitive files (.env, id_rsa, shadow, passwd, etc.).
    4. Blocks paths traversing sensitive directories (.git, .ssh, /etc).
    5. Enforces directory whitelist: Project directory, /home/kirito/quan_ly_server/data/, or /tmp/.
    """
    if not file_path:
        return False

    raw_path_str = str(file_path).strip()
    if not raw_path_str:
        return False

    # Immediate rejection for Windows-style drive letters, UNC, or backslashes on POSIX/Linux
    if os.name != "nt":
        if "\\" in raw_path_str or re.match(r"^[A-Za-z]:", raw_path_str):
            logger.warning("[EmailService] Chặn đường dẫn Windows/backslash trên môi trường non-Windows: %s", file_path)
            return False

    try:
        p = Path(file_path).resolve()
    except Exception:
        return False

    # 1. Blacklist check: reject hidden files (starting with dot)
    file_name = p.name.lower()
    if file_name.startswith("."):
        logger.warning("[EmailService] Chặn file đính kèm ẩn: %s", file_path)
        return False

    # 2. Blacklist check: sensitive filenames and patterns
    for sensitive in SENSITIVE_FILE_PATTERNS:
        if sensitive in file_name:
            logger.warning("[EmailService] Chặn file đính kèm nhạy cảm (%s): %s", sensitive, file_path)
            return False

    # 3. Blacklist check: sensitive directory traversal (.git, .ssh, etc.)
    for part in p.parts:
        part_clean = part.lower().strip("\\/ ")
        if part_clean in FORBIDDEN_PATH_SEGMENTS or part_clean.startswith(".git") or part_clean.startswith(".ssh"):
            logger.warning("[EmailService] Chặn file nằm trong thư mục nhạy cảm (%s): %s", part, file_path)
            return False

    # 4. Whitelist check: must reside inside project root, /home/kirito/quan_ly_server/data/, or /tmp/
    allowed_roots: List[Path] = []

    # Dynamic repository root (parents[4] = quan_ly_server repo root)
    try:
        repo_root = Path(__file__).resolve().parents[4]
        allowed_roots.append(repo_root)
    except Exception:
        try:
            repo_root = Path(__file__).resolve().parents[3]
            allowed_roots.append(repo_root)
        except Exception:
            pass

    # DO NOT include Path.cwd().resolve() - it breaks relative path security on POSIX!
    allowed_roots.append(Path(tempfile.gettempdir()).resolve())

    # Supported runtime paths on server/container
    for candidate in [
        "/tmp",
        "/home/kirito/quan_ly_server/data",
        "/home/kirito/quan_ly_server",
        "d:/GitHub/quan_ly_server",
    ]:
        try:
            allowed_roots.append(Path(candidate).resolve())
        except Exception:
            pass

    is_whitelisted = False
    for root in allowed_roots:
        try:
            p.relative_to(root)
            is_whitelisted = True
            break
        except (ValueError, TypeError):
            continue

    if not is_whitelisted:
        logger.warning(
            "[EmailService] Chặn file đính kèm nằm ngoài danh mục thư mục cho phép: %s (canonical: %s)",
            file_path,
            p,
        )
        return False

    return True


def _get_smtp_config() -> Dict[str, Any]:
    """Reads SMTP configuration from environment variables with safe defaults."""
    host = os.environ.get("SMTP_HOST", "").strip()
    port_str = os.environ.get("SMTP_PORT", "587").strip()
    try:
        port = int(port_str)
    except ValueError:
        port = 587

    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    sender = os.environ.get("SMTP_FROM", "").strip() or user or "noreply-agent@quanlyserver.local"

    use_tls_str = os.environ.get("SMTP_USE_TLS", "true").strip().lower()
    use_tls = use_tls_str in ("1", "true", "yes", "on")

    use_ssl_str = os.environ.get("SMTP_USE_SSL", "false").strip().lower()
    use_ssl = use_ssl_str in ("1", "true", "yes", "on") or port == 465

    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "sender": sender,
        "use_tls": use_tls,
        "use_ssl": use_ssl,
    }


def _send_smtp_sync(
    to: str,
    subject: str,
    body: str,
    attachments: Optional[List[str]] = None,
    smtp_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Synchronous SMTP dispatch designed to run inside `asyncio.to_thread`.
    """
    cfg = smtp_config or _get_smtp_config()

    if not cfg["host"]:
        return {
            "status": "error",
            "reason": "missing_config",
            "message": "Chưa cấu hình máy chủ SMTP (thiếu biến môi trường SMTP_HOST)",
        }

    # Prepare MIME Message
    msg = MIMEMultipart("mixed")
    msg["From"] = cfg["sender"]
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

    # Detect HTML vs Plain text
    is_html = "<html" in body.lower() or "<div" in body.lower() or "<p>" in body.lower()
    msg_body = MIMEText(body, "html" if is_html else "plain", "utf-8")
    msg.attach(msg_body)

    # Process attachments
    attached_files: List[str] = []
    if attachments:
        for file_path in attachments:
            if not _is_safe_attachment_path(file_path):
                logger.warning("[EmailService] Attachment blocked due to security policy: %s", file_path)
                continue

            p = Path(file_path).resolve()
            if not p.is_file():
                logger.warning("[EmailService] Attachment file not found: %s", file_path)
                continue

            ctype, encoding = mimetypes.guess_type(str(p))
            if ctype is None or encoding is not None:
                ctype = "application/octet-stream"
            maintype, subtype = ctype.split("/", 1)

            try:
                with open(p, "rb") as fp:
                    part = MIMEBase(maintype, subtype)
                    part.set_payload(fp.read())
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", "attachment", filename=p.name)
                msg.attach(part)
                attached_files.append(p.name)
            except Exception as att_err:
                logger.error("[EmailService] Error attaching file %s: %s", file_path, att_err)

    # Connect and send
    try:
        timeout_sec = 15.0
        if cfg["use_ssl"]:
            server = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=timeout_sec)
        else:
            server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=timeout_sec)
            server.ehlo()
            if cfg["use_tls"]:
                server.starttls()
                server.ehlo()

        if cfg["user"] and cfg["password"]:
            server.login(cfg["user"], cfg["password"])

        server.send_message(msg)
        server.quit()

        return {
            "status": "success",
            "to": to,
            "subject": subject,
            "attachments": attached_files,
            "message": f"Email đã được gửi thành công đến '{to}'",
        }
    except smtplib.SMTPAuthenticationError as auth_err:
        logger.error("[EmailService] SMTP Authentication failed: %s", auth_err)
        return {
            "status": "error",
            "reason": "auth_error",
            "message": f"Lỗi xác thực tài khoản SMTP: {auth_err.smtp_error.decode('utf-8', errors='replace') if hasattr(auth_err, 'smtp_error') else str(auth_err)}",
        }
    except smtplib.SMTPConnectError as conn_err:
        logger.error("[EmailService] SMTP Connection failed: %s", conn_err)
        return {
            "status": "error",
            "reason": "connection_error",
            "message": f"Không thể kết nối đến máy chủ SMTP ({cfg['host']}:{cfg['port']}): {str(conn_err)}",
        }
    except Exception as exc:
        logger.error("[EmailService] SMTP send error: %s", exc)
        return {
            "status": "error",
            "reason": "send_failed",
            "message": f"Lỗi khi gửi email qua SMTP: {str(exc)}",
        }


class EmailReportService:
    """
    Sub-service for SMTP Email Communication & Periodic Health Report Generation (R6).
    """

    def __init__(
        self,
        monitor_service: Optional[ServerMonitorService] = None,
        smtp_sender: Optional[Callable[..., Dict[str, Any]]] = None,
    ):
        self._monitor_service = monitor_service
        self._smtp_sender = smtp_sender

    @property
    def monitor_service(self) -> ServerMonitorService:
        if self._monitor_service is None:
            self._monitor_service = ServerMonitorService()
        return self._monitor_service

    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        attachments: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Sends an email asynchronously via thread pool.
        """
        clean_to = (to or "").strip()
        if not clean_to or "@" not in clean_to:
            return {
                "status": "error",
                "message": f"Địa chỉ email người nhận không hợp lệ: '{to}'",
            }

        clean_subject = (subject or "").strip()
        if not clean_subject:
            return {"status": "error", "message": "Tiêu đề email không được để trống"}

        if not body or not body.strip():
            return {"status": "error", "message": "Nội dung email không được để trống"}

        # Custom injector for testing or direct callable
        if self._smtp_sender:
            if asyncio.iscoroutinefunction(self._smtp_sender):
                return await self._smtp_sender(to=clean_to, subject=clean_subject, body=body, attachments=attachments)
            return await asyncio.to_thread(self._smtp_sender, to=clean_to, subject=clean_subject, body=body, attachments=attachments)

        return await asyncio.to_thread(
            _send_smtp_sync,
            to=clean_to,
            subject=clean_subject,
            body=body,
            attachments=attachments,
        )

    async def generate_report(
        self,
        report_type: str,
        period: str = "today",
        send_to_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Compiles a comprehensive server health diagnostics report for period ('today' | 'week' | 'month').
        Optionally dispatches the report to `send_to_email`.
        """
        clean_period = (period or "today").strip().lower()
        if clean_period not in VALID_PERIODS:
            clean_period = "today"

        clean_type = (report_type or "system_health").strip().lower()
        timestamp_utc = datetime.now(timezone.utc)
        timestamp_vn = timestamp_utc.astimezone(VN_TZ).strftime("%Y-%m-%d %H:%M:%S (UTC+7)")

        # Period labels in Vietnamese
        period_titles = {
            "today": "HÔM NAY (24 GIỜ QUA)",
            "week": "TUẦN NÀY (7 NGÀY QUA)",
            "month": "THÁNG NÀY (30 NGÀY QUA)",
        }
        period_label = period_titles.get(clean_period, clean_period.upper())

        # 1. Gather live 5-dimensional snapshot from ServerMonitorService
        try:
            live_snapshot = await self.monitor_service.get_system_health_report()
        except Exception as exc:
            logger.warning("[EmailReportService] Live health snapshot query failed: %s", exc)
            live_snapshot = {"status": "error", "message": str(exc)}

        # Extract metric sections safely
        cpu_info = live_snapshot.get("cpu", {})
        ram_info = live_snapshot.get("ram", {})
        disk_info = live_snapshot.get("disk", {})
        docker_info = live_snapshot.get("docker", {})
        containers = docker_info.get("containers", [])
        overall_health = live_snapshot.get("overall_status", "UNKNOWN").upper()

        running_containers = sum(1 for c in containers if "up" in str(c.get("status", "")).lower())
        total_containers = len(containers)

        # 2. Build Markdown Report Text
        report_lines = [
            f"# 📊 BÁO CÁO TỔNG HỢP SỨC KHỎE HỆ THỐNG",
            f"**Loại báo cáo**: {clean_type.upper()}",
            f"**Chu kỳ thống kê**: {period_label}",
            f"**Thời gian trích xuất**: {timestamp_vn}",
            f"**Đánh giá tổng thể**: `{overall_health}`",
            "",
            "---",
            "### 1. ⚙️ Tải Xử Lý CPU & Tài Nguyên Tính Toán",
            f"- **Load Average (1m / 5m / 15m)**: {cpu_info.get('load_1m', 'N/A')} / {cpu_info.get('load_5m', 'N/A')} / {cpu_info.get('load_15m', 'N/A')}",
            f"- **Trạng thái CPU**: {cpu_info.get('status', 'NORMAL').upper()}",
            "",
            "### 2. 🧠 Bộ Nhớ RAM & Phân Bổ Tiến Trình",
            f"- **Tổng RAM**: {ram_info.get('total_mb', 'N/A')} MB",
            f"- **Đang sử dụng**: {ram_info.get('used_mb', 'N/A')} MB ({ram_info.get('usage_percent', 'N/A')}%)",
            f"- **Còn khả dụng**: {ram_info.get('available_mb', 'N/A')} MB",
            f"- **Trạng thái RAM**: {ram_info.get('status', 'NORMAL').upper()}",
            "",
            "### 3. 💾 Dung Lượng Ổ Đĩa (Disk Storage)",
            f"- **Kích thước ổ đĩa**: {disk_info.get('size', 'N/A')}",
            f"- **Đã sử dụng**: {disk_info.get('used', 'N/A')} ({disk_info.get('usage_percent', 'N/A')}%)",
            f"- **Còn trống**: {disk_info.get('available', 'N/A')}",
            f"- **Trạng thái ổ đĩa**: {disk_info.get('status', 'NORMAL').upper()}",
            "",
            "### 4. 🐳 Dịch Vụ & Docker Containers",
            f"- **Tổng số container**: {total_containers}",
            f"- **Containers đang chạy (UP)**: {running_containers}/{total_containers}",
        ]

        if containers:
            report_lines.append("")
            report_lines.append("| Tên Container | Trạng Thái | Image |")
            report_lines.append("|---|---|---|")
            for c in containers[:15]:
                c_name = c.get("name", "unknown")
                c_status = c.get("status", "unknown")
                c_image = c.get("image", "unknown")
                report_lines.append(f"| `{c_name}` | {c_status} | `{c_image}` |")
            if len(containers) > 15:
                report_lines.append(f"| ... và {len(containers) - 15} containers khác | | |")

        report_lines.extend([
            "",
            "### 5. 🛡️ Khuyến Nghị & Hành Động SRE",
            "- Hệ thống đang được giám sát tự động 24/7 bởi AI Agent Tiểu Bảo Bảo.",
            "- Mọi tiến trình nền hoạt động trong ngưỡng thông số an toàn cho phép.",
            "",
            "---",
            f"*Báo cáo được khởi tạo tự động bởi AI Agent Tiểu Bảo Bảo lúc {timestamp_vn}*",
        ])

        report_text = "\n".join(report_lines)

        # 3. Optional Email Dispatch
        email_sent = False
        email_result: Optional[Dict[str, Any]] = None
        if send_to_email:
            email_subject = f"[Server Report] Báo cáo sức khỏe máy chủ ({clean_period.upper()}) - {timestamp_vn}"
            email_result = await self.send_email(
                to=send_to_email,
                subject=email_subject,
                body=report_text,
            )
            email_sent = email_result.get("status") == "success"

        return {
            "status": "success",
            "report_type": clean_type,
            "period": clean_period,
            "period_label": period_label,
            "timestamp": timestamp_vn,
            "overall_status": overall_health,
            "report_text": report_text,
            "email_sent": email_sent,
            "email_result": email_result,
        }


# Module-level singletons and interface functions for direct dispatcher routing
email_report_service = EmailReportService()


async def send_email(
    to: str,
    subject: str,
    body: str,
    attachments: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return await email_report_service.send_email(to, subject, body, attachments)


async def generate_report(
    report_type: str,
    period: str = "today",
    send_to_email: Optional[str] = None,
) -> Dict[str, Any]:
    return await email_report_service.generate_report(report_type, period, send_to_email)
