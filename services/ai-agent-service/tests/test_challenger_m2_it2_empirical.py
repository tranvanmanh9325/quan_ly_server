"""
test_challenger_m2_it2_empirical.py — Challenger 1 Empirical Adversarial Stress Test Suite for Milestone M2 Iteration 2.

Author: Challenger 1 (Empirical Adversarial Verifier)
Target Components:
1. notes_service.py (R3): search_notes grep breakout and option injection defense.
2. server_monitor_service.py (R2): get_system_health_report alert hierarchy and critical preservation.
"""

import asyncio
import json
import shlex
import unittest
from unittest.mock import AsyncMock

from app.core.security import find_security_violation
from app.services.notes_service import NotesService
from app.services.server_monitor_service import ServerMonitorService


class MockSshClient:
    """Mock SSH client capturing executed commands and simulating responses."""

    def __init__(self, responses=None, default_response=""):
        self.responses = responses or {}
        self.default_response = default_response
        self.executed_commands = []

    async def execute_command(self, command: str) -> str:
        self.executed_commands.append(command)
        violation = find_security_violation(command)
        if violation:
            return f"BLOCKED: Lệnh bị từ chối vì lý do bảo mật ({violation})."
        for pattern, resp in self.responses.items():
            if pattern in command:
                return resp
        return self.default_response


class TestNotesSearchAdversarialEmpirical(unittest.IsolatedAsyncioTestCase):
    """Stress-test harness for search_notes against escape breakout & option injection."""

    async def asyncSetUp(self):
        self.mock_ssh = MockSshClient()
        self.service = NotesService(
            ssh_client=self.mock_ssh,
            base_path="/home/kirito/quan_ly_server/data/notes",
        )

    async def test_01_query_breakout_escaped_quote_semicolon(self):
        """Query: \\"; id; echo \\" must NOT breakout of grep or execute commands."""
        malicious_query = '\\"; id; echo \\"'
        res = await self.service.search_notes(malicious_query)
        self.assertEqual(res["status"], "success")

        executed_cmd = self.mock_ssh.executed_commands[0]
        # Must contain '--' argument separator
        self.assertIn("--", executed_cmd)

        # Must parse cleanly via POSIX shlex without shell expansion
        tokens = shlex.split(executed_cmd)
        self.assertEqual(tokens[0], "grep")
        dash_dash_idx = tokens.index("--")
        pattern_arg = tokens[dash_dash_idx + 1]

        # The pattern argument must contain the exact literal string, NOT executed as shell commands
        self.assertEqual(pattern_arg, malicious_query)
        self.assertNotIn("id", tokens[:dash_dash_idx])
        self.assertNotIn("echo", tokens[:dash_dash_idx])
        self.assertIsNone(find_security_violation(executed_cmd))

    async def test_02_query_command_substitution_dollar_parenthesis(self):
        """Query: $(id) must be neutralized or blocked by Defense-in-Depth."""
        subshell_query = "$(id)"
        res = await self.service.search_notes(subshell_query)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["total"], 0)

        executed_cmd = self.mock_ssh.executed_commands[0]
        # In POSIX shlex tokens, it must be literal $(id) within quotes
        tokens = shlex.split(executed_cmd)
        dash_dash_idx = tokens.index("--")
        self.assertEqual(tokens[dash_dash_idx + 1], "$(id)")

        # Defense-in-depth: find_security_violation flags $(
        violation = find_security_violation(executed_cmd)
        self.assertIsNotNone(violation)
        self.assertIn("$(", violation)

    async def test_03_query_command_substitution_backticks(self):
        """Query: `id` must be neutralized or blocked by Defense-in-Depth."""
        backtick_query = "`id`"
        res = await self.service.search_notes(backtick_query)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["total"], 0)

        executed_cmd = self.mock_ssh.executed_commands[0]
        tokens = shlex.split(executed_cmd)
        dash_dash_idx = tokens.index("--")
        self.assertEqual(tokens[dash_dash_idx + 1], "`id`")

        # Defense-in-depth: find_security_violation flags `
        violation = find_security_violation(executed_cmd)
        self.assertIsNotNone(violation)
        self.assertIn("`", violation)

    async def test_04_query_option_injection_help(self):
        """Query: --help must be treated as a literal search pattern, not grep flag."""
        help_query = "--help"
        res = await self.service.search_notes(help_query)
        self.assertEqual(res["status"], "success")

        executed_cmd = self.mock_ssh.executed_commands[0]
        tokens = shlex.split(executed_cmd)
        dash_dash_idx = tokens.index("--")
        # --help MUST appear after -- to prevent option interpretation
        self.assertEqual(tokens[dash_dash_idx + 1], "--help")
        self.assertNotIn("--help", tokens[:dash_dash_idx])
        self.assertIsNone(find_security_violation(executed_cmd))

    async def test_05_query_option_injection_invert_match(self):
        """Query: -v must be treated as a literal search pattern, not grep flag."""
        invert_query = "-v"
        res = await self.service.search_notes(invert_query)
        self.assertEqual(res["status"], "success")

        executed_cmd = self.mock_ssh.executed_commands[0]
        tokens = shlex.split(executed_cmd)
        dash_dash_idx = tokens.index("--")
        # -v MUST appear after -- to prevent option interpretation
        self.assertEqual(tokens[dash_dash_idx + 1], "-v")
        self.assertNotIn("-v", tokens[:dash_dash_idx])
        self.assertIsNone(find_security_violation(executed_cmd))

    async def test_06_comprehensive_adversarial_matrix(self):
        """Matrix testing of various injection vectors."""
        adversarial_payloads = [
            "-E",
            "-f /etc/passwd",
            "--exclude-dir=/",
            "'; cat /etc/shadow #",
            "\\'; uname -a; #",
            "\" || echo pwned || \"",
            "test | cat",
            "test & touch /tmp/pwn",
            "> /tmp/leak",
            "< /etc/passwd",
            "*",
            "?",
            "~",
            "hello'; id; echo 'world",
            "normal query with spaces",
            "Tiếng Việt có dấu và biểu tượng 🔍",
        ]

        for payload in adversarial_payloads:
            self.mock_ssh.executed_commands.clear()
            res = await self.service.search_notes(payload)
            self.assertEqual(res["status"], "success", f"Payload failed: {payload}")
            self.assertEqual(len(self.mock_ssh.executed_commands), 1)

            executed_cmd = self.mock_ssh.executed_commands[0]
            tokens = shlex.split(executed_cmd)
            self.assertIn("--", tokens)
            dash_dash_idx = tokens.index("--")
            # All options before -- must be safe grep flags
            for opt in tokens[1:dash_dash_idx]:
                self.assertIn(opt, ["-rn", "-i", "-F", "--exclude-dir=.trash"])
            # The search query must be at tokens[dash_dash_idx + 1]
            self.assertEqual(tokens[dash_dash_idx + 1], payload)


class TestSystemHealthReportTelemetryAdversarial(unittest.IsolatedAsyncioTestCase):
    """Stress-test harness for get_system_health_report alert hierarchy."""

    def _build_telemetry(self, ram_used=1200, ram_total=3300, disk_pct=30, load_1m=0.15, container_status="healthy"):
        return (
            f"{load_1m} 0.10 0.05\n"
            f"===DELIM_RAM===\n"
            f"Mem: {ram_total} {ram_used} 100 50 100 2000\n"
            f"===DELIM_DISK===\n"
            f"Filesystem Size Used Avail Use% Mounted on\n"
            f"/dev/sda1 100G {disk_pct}G 10G {disk_pct}% /\n"
            f"===DELIM_DOCKER===\n"
            f"dashboard_ai_agent\tUp 2 days ({container_status})\timage:v1\t8084/tcp\n"
            f"dashboard_db\tUp 5 days (healthy)\tpostgres:17\t5432/tcp\n"
            f"===DELIM_NET===\n"
            f"tcp LISTEN 0 128 127.0.0.1:8084 0.0.0.0:*\n"
        )

    async def asyncSetUp(self):
        self.mock_ssh = MockSshClient()
        self.service = ServerMonitorService(ssh_client=self.mock_ssh)

    async def test_07_ram_95_and_unhealthy_container_maintains_critical(self):
        """MANDATORY: RAM 95% + container unhealthy must PRESERVE 'CRITICAL' overall_health."""
        # 3150 / 3300 = 95.4% RAM
        telemetry = self._build_telemetry(ram_used=3150, ram_total=3300, container_status="unhealthy")
        self.mock_ssh.default_response = telemetry

        report = await self.service.get_system_health_report()
        self.assertEqual(report["status"], "success")
        self.assertEqual(
            report["overall_health"],
            "CRITICAL",
            f"CRITICAL was downgraded! Got: {report['overall_health']}",
        )

        # Both issues must be clearly reported
        issues = report["issues"]
        self.assertTrue(any("RAM nguy cấp" in i for i in issues), f"Missing RAM critical issue: {issues}")
        self.assertTrue(any("Container unhealthy" in i for i in issues), f"Missing Container issue: {issues}")

    async def test_08_disk_95_and_unhealthy_container_maintains_critical(self):
        """Disk 95% + container unhealthy must PRESERVE 'CRITICAL' overall_health."""
        telemetry = self._build_telemetry(disk_pct=95, container_status="unhealthy")
        self.mock_ssh.default_response = telemetry

        report = await self.service.get_system_health_report()
        self.assertEqual(report["overall_health"], "CRITICAL")
        issues = report["issues"]
        self.assertTrue(any("Ổ cứng gần đầy" in i for i in issues))
        self.assertTrue(any("Container unhealthy" in i for i in issues))

    async def test_09_cpu_load_8_5_and_unhealthy_container_maintains_critical(self):
        """CPU load 8.5 + container unhealthy must PRESERVE 'CRITICAL' overall_health."""
        telemetry = self._build_telemetry(load_1m=8.5, container_status="unhealthy")
        self.mock_ssh.default_response = telemetry

        report = await self.service.get_system_health_report()
        self.assertEqual(report["overall_health"], "CRITICAL")
        issues = report["issues"]
        self.assertTrue(any("CPU load rất cao" in i for i in issues))
        self.assertTrue(any("Container unhealthy" in i for i in issues))

    async def test_10_multi_critical_resources_and_unhealthy_container(self):
        """Multiple critical metrics (RAM 96%, Disk 95%, CPU 9.0) + unhealthy container."""
        telemetry = self._build_telemetry(
            ram_used=3200, ram_total=3300, disk_pct=95, load_1m=9.0, container_status="unhealthy"
        )
        self.mock_ssh.default_response = telemetry

        report = await self.service.get_system_health_report()
        self.assertEqual(report["overall_health"], "CRITICAL")
        issues = report["issues"]
        self.assertTrue(any("RAM nguy cấp" in i for i in issues))
        self.assertTrue(any("Ổ cứng gần đầy" in i for i in issues))
        self.assertTrue(any("CPU load rất cao" in i for i in issues))
        self.assertTrue(any("Container unhealthy" in i for i in issues))

    async def test_11_warning_ram_and_unhealthy_container_stays_warning(self):
        """RAM 88% (WARNING) + container unhealthy must remain 'WARNING'."""
        # 2900 / 3300 = 87.8% RAM
        telemetry = self._build_telemetry(ram_used=2900, ram_total=3300, container_status="unhealthy")
        self.mock_ssh.default_response = telemetry

        report = await self.service.get_system_health_report()
        self.assertEqual(report["overall_health"], "WARNING")
        issues = report["issues"]
        self.assertTrue(any("RAM cao" in i for i in issues))
        self.assertTrue(any("Container unhealthy" in i for i in issues))

    async def test_12_healthy_resources_and_unhealthy_container_sets_warning(self):
        """Healthy resources + container unhealthy must elevate from HEALTHY to 'WARNING'."""
        telemetry = self._build_telemetry(ram_used=1000, ram_total=3300, disk_pct=30, load_1m=0.2, container_status="unhealthy")
        self.mock_ssh.default_response = telemetry

        report = await self.service.get_system_health_report()
        self.assertEqual(report["overall_health"], "WARNING")
        issues = report["issues"]
        self.assertEqual(len(issues), 1)
        self.assertTrue(any("Container unhealthy" in i for i in issues))

    async def test_13_healthy_resources_and_healthy_containers_sets_healthy(self):
        """All resources healthy + containers healthy must be 'HEALTHY' with 0 issues."""
        telemetry = self._build_telemetry(ram_used=1000, ram_total=3300, disk_pct=30, load_1m=0.2, container_status="healthy")
        self.mock_ssh.default_response = telemetry

        report = await self.service.get_system_health_report()
        self.assertEqual(report["overall_health"], "HEALTHY")
        self.assertEqual(len(report["issues"]), 0)


if __name__ == "__main__":
    unittest.main()
