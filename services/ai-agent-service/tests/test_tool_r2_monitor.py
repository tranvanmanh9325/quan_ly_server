"""
test_tool_r2_monitor.py — Unit & Adversarial Tests for ServerMonitorService (R2).

Validates Autonomous Server Health Monitor & SRE interface contracts:
- get_system_health_report()
- check_service_status(service_name)
- restart_service(service_name, confirm)
- tail_service_logs(service_name, lines)
- Strict confirmation gating for production services (Tier 2 Reversible)
- Empty logs vs Error/Warning log parsing & deduplication
- Command injection resistance
"""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.server_monitor_service import (
    PROTECTED_PRODUCTION_SERVICES,
    ServerMonitorService,
    check_service_status,
    get_system_health_report,
    restart_service,
    tail_service_logs,
)


class MockSshClient:
    """Mock SSH client for simulating deterministic server outputs."""

    def __init__(self, responses=None, default_response=""):
        self.responses = responses or {}
        self.default_response = default_response
        self.executed_commands = []

    async def execute_command(self, command: str) -> str:
        self.executed_commands.append(command)
        for pattern, resp in self.responses.items():
            if pattern in command:
                return resp
        return self.default_response


class TestServerMonitorService(unittest.IsolatedAsyncioTestCase):
    """Test suite for ServerMonitorService (R2)."""

    def setUp(self):
        self.mock_ssh = MockSshClient()
        self.service = ServerMonitorService(ssh_client=self.mock_ssh)

    # ──────────────────────────────────────────────────────────────────────────
    # 1. restart_service Confirmation Gating & Security Tests
    # ──────────────────────────────────────────────────────────────────────────

    async def test_restart_production_services_without_confirm_token_vetoed(self):
        """All protected production services must require confirm='RESTART_CONFIRMED'."""
        protected_list = [
            "dashboard_ai_agent",
            "dashboard_server_api",
            "dashboard_client",
            "postgres",
            "postgresql",
            "redis",
            "traefik",
            "nginx",
            "dashboard_custom_worker",
        ]
        for sname in protected_list:
            res = await self.service.restart_service(sname, confirm=None)
            self.assertEqual(
                res["status"],
                "confirmation_required",
                f"Service '{sname}' did not enforce confirmation gating!",
            )
            self.assertTrue(res["requires_confirm"])
            self.assertEqual(res["confirm_token"], "RESTART_CONFIRMED")
            self.assertIn("CẢNH BÁO BẢO MẬT", res["message"])

        # Verify NO SSH command was executed for any of these
        self.assertEqual(len(self.mock_ssh.executed_commands), 0)

    async def test_restart_production_service_with_invalid_confirm_token(self):
        invalid_tokens = ["yes", "true", "CONFIRM", "RESTART", "restart_confirmed", "1"]
        for token in invalid_tokens:
            res = await self.service.restart_service("dashboard_ai_agent", confirm=token)
            self.assertEqual(res["status"], "confirmation_required")
            self.assertTrue(res["requires_confirm"])

        self.assertEqual(len(self.mock_ssh.executed_commands), 0)

    async def test_restart_production_service_with_valid_confirm_token(self):
        self.mock_ssh.responses = {
            "docker inspect": '{"Running": true, "Status": "running"}',
            "docker restart": "dashboard_ai_agent",
        }
        res = await self.service.restart_service("dashboard_ai_agent", confirm="RESTART_CONFIRMED")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["service_name"], "dashboard_ai_agent")
        self.assertEqual(res["action"], "restart")

        # Verify restart command was executed
        self.assertTrue(any("docker restart dashboard_ai_agent" in cmd for cmd in self.mock_ssh.executed_commands))

    async def test_restart_non_production_service_without_confirm(self):
        self.mock_ssh.responses = {
            "docker inspect": '{"Running": true, "Status": "running"}',
            "docker restart": "temporary_worker",
        }
        res = await self.service.restart_service("temporary_worker", confirm=None)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["service_name"], "temporary_worker")

    async def test_restart_service_command_injection_rejected(self):
        injection_attempts = [
            "dashboard_ai_agent; rm -rf /",
            "redis && whoami",
            "postgres | cat /etc/passwd",
            "nginx$(whoami)",
            "traefik`id`",
            "service\nreboot",
            "service; reboot",
            "",
            "   ",
        ]
        for evil_name in injection_attempts:
            res = await self.service.restart_service(evil_name, confirm="RESTART_CONFIRMED")
            self.assertEqual(res["status"], "error")
            self.assertIn("Tên dịch vụ không hợp lệ", res["message"])

        self.assertEqual(len(self.mock_ssh.executed_commands), 0)

    # ──────────────────────────────────────────────────────────────────────────
    # 2. tail_service_logs Parsing Tests
    # ──────────────────────────────────────────────────────────────────────────

    async def test_tail_service_logs_empty(self):
        self.mock_ssh.responses = {
            "docker logs": "",
        }
        res = await self.service.tail_service_logs("dashboard_ai_agent", lines=50)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["total_lines"], 0)
        self.assertEqual(res["error_count"], 0)
        self.assertEqual(res["warning_count"], 0)
        self.assertEqual(res["error_samples"], [])
        self.assertIn("Hoàn toàn bình thường", res["error_summary"])

    async def test_tail_service_logs_with_errors_and_warnings(self):
        log_sample = (
            "2026-09-26 10:00:00 [INFO] Server started\n"
            "2026-09-26 10:00:01 [ERROR] Connection lost to PostgreSQL\n"
            "2026-09-26 10:00:02 [WARN] High memory consumption detected: 88%\n"
            "2026-09-26 10:00:03 [CRITICAL] Exception in thread asyncio_1: division by zero\n"
            "2026-09-26 10:00:04 [INFO] Heartbeat OK\n"
            "2026-09-26 10:00:05 [FATAL] Kernel panic - out of memory\n"
            "2026-09-26 10:00:01 [ERROR] Connection lost to PostgreSQL\n"  # Exact duplicate line
            "2026-09-26 10:00:07 [WARNING] Token refresh slow\n"
        )
        self.mock_ssh.responses = {
            "docker logs": log_sample,
        }
        res = await self.service.tail_service_logs("dashboard_ai_agent", lines=50)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["total_lines"], 8)
        self.assertEqual(res["error_count"], 4)    # ERROR, CRITICAL/Exception, FATAL, ERROR
        self.assertEqual(res["warning_count"], 2)  # WARN, WARNING
        self.assertIn("Phát hiện 4 dòng log chứa lỗi", res["error_summary"])
        # Deduplication check: 4 error lines, but one exact duplicate -> 3 unique samples
        self.assertEqual(len(res["error_samples"]), 3)

    async def test_tail_service_logs_lines_clamping(self):
        self.mock_ssh.responses = {"docker logs": "line1\nline2"}

        # Negative lines clamped to 1
        res1 = await self.service.tail_service_logs("dashboard_ai_agent", lines=-10)
        self.assertEqual(res1["lines_requested"], 1)

        # Huge lines clamped to 500
        res2 = await self.service.tail_service_logs("dashboard_ai_agent", lines=1000)
        self.assertEqual(res2["lines_requested"], 500)

        # Invalid string lines fallback to 50
        res3 = await self.service.tail_service_logs("dashboard_ai_agent", lines="abc")
        self.assertEqual(res3["lines_requested"], 50)

    async def test_tail_service_logs_injection_rejected(self):
        res = await self.service.tail_service_logs("service; rm -rf /")
        self.assertEqual(res["status"], "error")
        self.assertIn("Tên dịch vụ không hợp lệ", res["message"])

    # ──────────────────────────────────────────────────────────────────────────
    # 3. get_system_health_report Tests (5 Dimensions)
    # ──────────────────────────────────────────────────────────────────────────

    async def test_get_system_health_report_healthy(self):
        mock_output = (
            "0.15 0.10 0.05 1/200 12345\n"
            "===DELIM_RAM===\n"
            "Mem: 3300 1200 300 50 1800 2000\n"
            "===DELIM_DISK===\n"
            "Filesystem Size Used Avail Use% Mounted on\n"
            "/dev/sda1 100G 30G 70G 30% /\n"
            "===DELIM_DOCKER===\n"
            "dashboard_ai_agent\tUp 2 days (healthy)\timage:v1\t8084/tcp\n"
            "dashboard_db\tUp 5 days (healthy)\tpostgres:17\t5432/tcp\n"
            "===DELIM_NET===\n"
            "tcp LISTEN 0 128 127.0.0.1:8084 0.0.0.0:*\n"
            "tcp LISTEN 0 128 0.0.0.0:22 0.0.0.0:*\n"
        )
        self.mock_ssh.default_response = mock_output
        report = await self.service.get_system_health_report()
        self.assertEqual(report["status"], "success")
        self.assertEqual(report["overall_health"], "HEALTHY")
        self.assertEqual(len(report["issues"]), 0)
        self.assertEqual(report["cpu"]["load_1m"], 0.15)
        self.assertEqual(report["ram"]["total_mb"], 3300)
        self.assertEqual(report["disk"]["usage_percent_val"], 30)
        self.assertEqual(report["docker"]["total_running"], 2)
        self.assertIn(8084, report["network"]["listening_ports"])
        self.assertIn(22, report["network"]["listening_ports"])

    async def test_get_system_health_report_critical_ram(self):
        mock_output = (
            "0.15 0.10 0.05\n"
            "===DELIM_RAM===\n"
            "Mem: 3300 3150 50 50 100 100\n"  # 3150 / 3300 = 95.4%
            "===DELIM_DISK===\n"
            "Filesystem Size Used Avail Use% Mounted on\n"
            "/dev/sda1 100G 30G 70G 30% /\n"
            "===DELIM_DOCKER===\n"
            "dashboard_ai_agent\tUp 2 days\timage:v1\t8084/tcp\n"
            "===DELIM_NET===\n"
            "tcp LISTEN 0 128 127.0.0.1:8084 0.0.0.0:*\n"
        )
        self.mock_ssh.default_response = mock_output
        report = await self.service.get_system_health_report()
        self.assertEqual(report["overall_health"], "CRITICAL")
        self.assertTrue(any("RAM nguy cấp" in i for i in report["issues"]))

    async def test_get_system_health_report_critical_disk(self):
        mock_output = (
            "0.15 0.10 0.05\n"
            "===DELIM_RAM===\n"
            "Mem: 3300 1000 2300 50 100 2000\n"
            "===DELIM_DISK===\n"
            "Filesystem Size Used Avail Use% Mounted on\n"
            "/dev/sda1 100G 95G 5G 95% /\n"  # 95% disk
            "===DELIM_DOCKER===\n"
            "dashboard_ai_agent\tUp 2 days\timage:v1\t8084/tcp\n"
            "===DELIM_NET===\n"
            "tcp LISTEN 0 128 127.0.0.1:8084 0.0.0.0:*\n"
        )
        self.mock_ssh.default_response = mock_output
        report = await self.service.get_system_health_report()
        self.assertEqual(report["overall_health"], "CRITICAL")
        self.assertTrue(any("Ổ cứng gần đầy" in i for i in report["issues"]))

    async def test_get_system_health_report_unhealthy_container(self):
        mock_output = (
            "0.15 0.10 0.05\n"
            "===DELIM_RAM===\n"
            "Mem: 3300 1000 2300 50 100 2000\n"
            "===DELIM_DISK===\n"
            "Filesystem Size Used Avail Use% Mounted on\n"
            "/dev/sda1 100G 30G 70G 30% /\n"
            "===DELIM_DOCKER===\n"
            "dashboard_ai_agent\tUp 2 days (unhealthy)\timage:v1\t8084/tcp\n"
            "===DELIM_NET===\n"
            "tcp LISTEN 0 128 127.0.0.1:8084 0.0.0.0:*\n"
        )
        self.mock_ssh.default_response = mock_output
        report = await self.service.get_system_health_report()
        self.assertEqual(report["overall_health"], "WARNING")
        self.assertTrue(any("Container unhealthy" in i for i in report["issues"]))

    # ──────────────────────────────────────────────────────────────────────────
    # 4. check_service_status Tests
    # ──────────────────────────────────────────────────────────────────────────

    async def test_check_service_status_docker_running(self):
        self.mock_ssh.responses = {
            "docker inspect": json.dumps({"Running": True, "Status": "running", "ExitCode": 0}),
        }
        res = await self.service.check_service_status("dashboard_ai_agent")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["service_type"], "docker")
        self.assertTrue(res["is_active"])

    async def test_check_service_status_systemd_fallback(self):
        self.mock_ssh.responses = {
            "docker inspect": "Error: No such container",
            "systemctl is-active": "active\nActiveState=active\nSubState=running\nLoadState=loaded\nDescription=Nginx",
        }
        res = await self.service.check_service_status("nginx")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["service_type"], "systemd")
        self.assertTrue(res["is_active"])

    async def test_check_service_status_not_found(self):
        self.mock_ssh.responses = {
            "docker inspect": "Error: No such container",
            "systemctl": "unknown\nLoadState=not-found",
        }
        res = await self.service.check_service_status("ghost_service_xyz")
        self.assertEqual(res["status"], "not_found")

    async def test_check_service_status_injection_rejected(self):
        res = await self.service.check_service_status("nginx; reboot")
        self.assertEqual(res["status"], "error")


if __name__ == "__main__":
    unittest.main()
