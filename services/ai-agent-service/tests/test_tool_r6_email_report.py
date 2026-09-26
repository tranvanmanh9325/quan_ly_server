"""
test_tool_r6_email_report.py — Unit & Adversarial Tests for EmailReportService (R6).

Validates SMTP Email Dispatch & Periodic Server Health Reporting interface contracts:
- send_email(to, subject, body, attachments):
  - Successful dispatch with plain-text and HTML bodies
  - Handling file attachments
  - Input validation (invalid recipient email, empty subject, empty body)
  - Missing SMTP configuration handled gracefully without crashing
  - SMTP connection errors & authentication errors handled gracefully
  - Asynchronous non-blocking dispatch via `asyncio.to_thread`
- generate_report(report_type, period, send_to_email):
  - Health report generation for 'today', 'week', 'month'
  - Markdown report contents (CPU, RAM, Disk, Docker containers)
  - Automatic fallback on invalid period string
  - Integrated email dispatch when `send_to_email` is specified
  - Resilience against monitor service probe errors
"""

import os
from pathlib import Path
import smtplib
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.email_report_service import (
    EmailReportService,
    _get_smtp_config,
    _is_safe_attachment_path,
    _send_smtp_sync,
    generate_report,
    send_email,
)


class TestEmailReportServiceEmail(unittest.IsolatedAsyncioTestCase):
    """Test suite for send_email() SMTP dispatcher."""

    def setUp(self):
        self.service = EmailReportService()

    # ──────────────────────────────────────────────────────────────────────────
    # 1. Input Validation Tests
    # ──────────────────────────────────────────────────────────────────────────

    async def test_send_email_invalid_recipient_no_at(self):
        res = await self.service.send_email(to="invalid_email", subject="Test", body="Hello")
        self.assertEqual(res["status"], "error")
        self.assertIn("không hợp lệ", res["message"])

    async def test_send_email_empty_recipient(self):
        res = await self.service.send_email(to="", subject="Test", body="Hello")
        self.assertEqual(res["status"], "error")
        self.assertIn("không hợp lệ", res["message"])

    async def test_send_email_empty_subject(self):
        res = await self.service.send_email(to="user@example.com", subject="   ", body="Hello")
        self.assertEqual(res["status"], "error")
        self.assertIn("Tiêu đề", res["message"])

    async def test_send_email_empty_body(self):
        res = await self.service.send_email(to="user@example.com", subject="Test", body="   ")
        self.assertEqual(res["status"], "error")
        self.assertIn("Nội dung", res["message"])

    # ──────────────────────────────────────────────────────────────────────────
    # 2. Configuration & Resilience Tests
    # ──────────────────────────────────────────────────────────────────────────

    async def test_send_email_missing_smtp_host_graceful_error(self):
        # Ensure SMTP_HOST is unset
        with patch.dict(os.environ, {"SMTP_HOST": ""}, clear=False):
            res = await self.service.send_email(
                to="kirito@example.com",
                subject="Test Alert",
                body="Alert content",
            )
            self.assertEqual(res["status"], "error")
            self.assertEqual(res.get("reason"), "missing_config")
            self.assertIn("Chưa cấu hình máy chủ SMTP", res["message"])

    # ──────────────────────────────────────────────────────────────────────────
    # 3. Successful Dispatch & Mocked SMTP Interactions
    # ──────────────────────────────────────────────────────────────────────────

    @patch("smtplib.SMTP")
    async def test_send_email_success_plain_text(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        custom_config = {
            "host": "smtp.gmail.com",
            "port": 587,
            "user": "test@gmail.com",
            "password": "app-password",
            "sender": "test@gmail.com",
            "use_tls": True,
            "use_ssl": False,
        }

        with patch.dict(os.environ, {
            "SMTP_HOST": "smtp.gmail.com",
            "SMTP_PORT": "587",
            "SMTP_USER": "test@gmail.com",
            "SMTP_PASSWORD": "app-password",
        }):
            res = await self.service.send_email(
                to="recipient@example.com",
                subject="Server SRE Alert",
                body="Disk usage reached 85%",
            )
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["to"], "recipient@example.com")
            self.assertIn("thành công", res["message"])

            mock_server.starttls.assert_called_once()
            mock_server.login.assert_called_once_with("test@gmail.com", "app-password")
            mock_server.send_message.assert_called_once()
            mock_server.quit.assert_called_once()

    @patch("smtplib.SMTP")
    async def test_send_email_with_valid_attachment(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tmp:
            tmp.write("Sample log content for testing email attachments")
            tmp_path = tmp.name

        try:
            with patch.dict(os.environ, {"SMTP_HOST": "mail.local", "SMTP_PORT": "25", "SMTP_USE_TLS": "false"}):
                res = await self.service.send_email(
                    to="dev@example.com",
                    subject="Log Report",
                    body="Attached is the log file.",
                    attachments=[tmp_path],
                )
                self.assertEqual(res["status"], "success")
                self.assertEqual(len(res["attachments"]), 1)
                self.assertEqual(res["attachments"][0], Path(tmp_path).name)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_attachment_security_blocks_sensitive_paths(self):
        # Sensitive files must be rejected by _is_safe_attachment_path
        self.assertFalse(_is_safe_attachment_path(".env"))
        self.assertFalse(_is_safe_attachment_path("/home/kirito/quan_ly_server/.env"))
        self.assertFalse(_is_safe_attachment_path("/home/kirito/.ssh/id_rsa"))
        self.assertFalse(_is_safe_attachment_path("/etc/shadow"))
        self.assertFalse(_is_safe_attachment_path("/etc/passwd"))
        self.assertFalse(_is_safe_attachment_path(".git/config"))
        self.assertFalse(_is_safe_attachment_path("C:\\Windows\\System32\\cmd.exe"))

    @patch("smtplib.SMTP")
    async def test_send_email_blocks_sensitive_attachments(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as valid_tmp:
            valid_tmp.write("Legitimate log content")
            valid_path = valid_tmp.name

        try:
            with patch.dict(os.environ, {"SMTP_HOST": "mail.local", "SMTP_PORT": "25", "SMTP_USE_TLS": "false"}):
                # Attempt to exfiltrate .env, /etc/shadow, and id_rsa along with legitimate file
                res = await self.service.send_email(
                    to="dev@example.com",
                    subject="Report with attachments",
                    body="Please review attached files.",
                    attachments=[
                        valid_path,
                        ".env",
                        "/etc/shadow",
                        "/home/kirito/.ssh/id_rsa",
                    ],
                )
                self.assertEqual(res["status"], "success")
                # Only the legitimate file must be attached; sensitive files must be strictly excluded
                self.assertEqual(len(res["attachments"]), 1)
                self.assertEqual(res["attachments"][0], Path(valid_path).name)
        finally:
            if os.path.exists(valid_path):
                os.remove(valid_path)

    # ──────────────────────────────────────────────────────────────────────────
    # 4. Network and Authentication Error Mitigations
    # ──────────────────────────────────────────────────────────────────────────

    @patch("smtplib.SMTP")
    async def test_send_email_authentication_error(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Authentication credentials invalid")
        mock_smtp_cls.return_value = mock_server

        with patch.dict(os.environ, {"SMTP_HOST": "smtp.mail.com", "SMTP_USER": "user", "SMTP_PASSWORD": "bad"}):
            res = await self.service.send_email(
                to="alert@domain.com",
                subject="Ping",
                body="Testing auth error",
            )
            self.assertEqual(res["status"], "error")
            self.assertEqual(res.get("reason"), "auth_error")
            self.assertIn("xác thực", res["message"])

    @patch("smtplib.SMTP")
    async def test_send_email_connection_timeout(self, mock_smtp_cls):
        mock_smtp_cls.side_effect = smtplib.SMTPConnectError(421, "Connection timed out")

        with patch.dict(os.environ, {"SMTP_HOST": "10.255.255.1", "SMTP_PORT": "587"}):
            res = await self.service.send_email(
                to="sysadmin@local",
                subject="Notice",
                body="Testing connection timeout",
            )
            self.assertEqual(res["status"], "error")
            self.assertEqual(res.get("reason"), "connection_error")
            self.assertIn("Không thể kết nối", res["message"])


class TestEmailReportServiceReport(unittest.IsolatedAsyncioTestCase):
    """Test suite for generate_report()."""

    def setUp(self):
        self.mock_monitor = MagicMock()
        self.service = EmailReportService(monitor_service=self.mock_monitor)

    # ──────────────────────────────────────────────────────────────────────────
    # 1. Report Generation Across Periods
    # ──────────────────────────────────────────────────────────────────────────

    async def test_generate_report_today_success(self):
        # Configure simulated health data
        self.mock_monitor.get_system_health_report = AsyncMock(return_value={
            "status": "success",
            "overall_status": "HEALTHY",
            "cpu": {"load_1m": "0.45", "load_5m": "0.38", "load_15m": "0.40", "status": "NORMAL"},
            "ram": {"total_mb": 3192, "used_mb": 1420, "available_mb": 1772, "usage_percent": 44.5, "status": "NORMAL"},
            "disk": {"size": "40G", "used": "16G", "available": "22G", "usage_percent": 42.0, "status": "NORMAL"},
            "docker": {
                "containers": [
                    {"name": "dashboard_ai_agent", "status": "Up 3 days", "image": "ai-agent:latest"},
                    {"name": "postgres", "status": "Up 3 days (healthy)", "image": "postgres:15"},
                ]
            },
        })

        res = await self.service.generate_report(report_type="system_health", period="today")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["period"], "today")
        self.assertEqual(res["overall_status"], "HEALTHY")
        self.assertFalse(res["email_sent"])

        # Check structured Markdown content
        report_text = res["report_text"]
        self.assertIn("BÁO CÁO TỔNG HỢP SỨC KHỎE HỆ THỐNG", report_text)
        self.assertIn("HÔM NAY (24 GIỜ QUA)", report_text)
        self.assertIn("dashboard_ai_agent", report_text)
        self.assertIn("postgres", report_text)
        self.assertIn("44.5%", report_text)

    async def test_generate_report_week_and_month(self):
        self.mock_monitor.get_system_health_report = AsyncMock(return_value={
            "status": "success",
            "overall_status": "NORMAL",
            "cpu": {},
            "ram": {},
            "disk": {},
            "docker": {"containers": []},
        })

        res_week = await self.service.generate_report(report_type="weekly_audit", period="week")
        self.assertEqual(res_week["period"], "week")
        self.assertIn("TUẦN NÀY", res_week["period_label"])

        res_month = await self.service.generate_report(report_type="monthly_audit", period="month")
        self.assertEqual(res_month["period"], "month")
        self.assertIn("THÁNG NÀY", res_month["period_label"])

    async def test_generate_report_invalid_period_fallback_to_today(self):
        self.mock_monitor.get_system_health_report = AsyncMock(return_value={"status": "success"})
        res = await self.service.generate_report(report_type="health", period="yesteryear")
        self.assertEqual(res["period"], "today")

    # ──────────────────────────────────────────────────────────────────────────
    # 2. Integrated Email Dispatch on Report Generation
    # ──────────────────────────────────────────────────────────────────────────

    async def test_generate_report_with_send_to_email_success(self):
        self.mock_monitor.get_system_health_report = AsyncMock(return_value={
            "status": "success",
            "overall_status": "HEALTHY",
            "cpu": {},
            "ram": {},
            "disk": {},
            "docker": {"containers": []},
        })

        mock_email_result = {"status": "success", "to": "director@company.vn", "message": "Email sent"}
        self.service.send_email = AsyncMock(return_value=mock_email_result)

        res = await self.service.generate_report(
            report_type="daily_digest",
            period="today",
            send_to_email="director@company.vn",
        )
        self.assertEqual(res["status"], "success")
        self.assertTrue(res["email_sent"])
        self.assertEqual(res["email_result"], mock_email_result)
        self.service.send_email.assert_called_once()

    # ──────────────────────────────────────────────────────────────────────────
    # 3. Resilience When Monitor Service Probe Fails
    # ──────────────────────────────────────────────────────────────────────────

    async def test_generate_report_resilient_when_monitor_fails(self):
        self.mock_monitor.get_system_health_report = AsyncMock(side_effect=RuntimeError("SSH connection dropped"))

        res = await self.service.generate_report(report_type="emergency", period="today")
        self.assertEqual(res["status"], "success")
        self.assertIn("BÁO CÁO TỔNG HỢP SỨC KHỎE HỆ THỐNG", res["report_text"])
        self.assertIn("N/A", res["report_text"])


if __name__ == "__main__":
    unittest.main()
