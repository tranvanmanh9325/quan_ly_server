"""
test_challenger_m6_adversarial_stress.py — Empirical Adversarial Stress Test Suite (Milestone M6).

Conducted by Challenger 1 (Empirical Adversarial Stress-Tester).
Adversarial Stress Testing of Core Capabilities:
1. `get_system_health_report`: Latency benchmark (< 3.0s), p95/p99 measurements, corrupted probe outputs,
   missing delimiters, degraded/critical states detection.
2. `calculate`: Extreme math, division by zero, float overflow, CPU exhaustion (DoS/bomb),
   ast injection attacks, forbidden functions, code executions, compound interest boundary limits.
3. `read_file_content`: Exact 2000-char clamping boundaries (1999, 2000, 2001, 10000 chars),
   sensitive file isolation (.env variants, .ssh, /etc), path traversal, injection payloads, null-byte rejection.
4. `schedule_reminder`: Delay boundaries (0, negative, invalid types), repeat normalization and rejection,
   empty messages, SQL injection resilient storage, lifecycle state transitions.
"""

import asyncio
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.ai_agent_tools import AgentToolExecutor
from app.services.server_monitor_service import ServerMonitorService
from app.services.calculator_service import (
    CalculatorService,
    evaluate_expression_safely,
    MAX_EXPR_LENGTH,
    MAX_EXPONENT,
    MAX_FACTORIAL_INPUT,
)
from app.services.file_manager_service import (
    FileManagerService,
    MAX_READ_CHARS_LIMIT,
)
from app.services.scheduler_service import (
    SchedulerService,
    VALID_REPEAT_OPTIONS,
)


class TestAdversarialHealthReport(unittest.IsolatedAsyncioTestCase):
    """Stress tests and edge case mining on get_system_health_report."""

    async def asyncSetUp(self):
        self.mock_ssh = MagicMock()
        self.standard_output = (
            "0.25 0.30 0.28 1/250 8888\n"
            "===DELIM_RAM===\n"
            "              total        used        free      shared  buff/cache   available\n"
            "Mem:          16000        4000        8000         200        4000       11800\n"
            "Swap:          2048           0        2048\n"
            "===DELIM_DISK===\n"
            "Filesystem      Size  Used Avail Use% Mounted on\n"
            "/dev/sda1       100G   35G   65G  35% /\n"
            "===DELIM_DOCKER===\n"
            "dashboard_ai_agent\tUp 3 days (healthy)\tai_agent:latest\t0.0.0.0:8084->8084/tcp\n"
            "postgres\tUp 5 days (healthy)\tpostgres:17-alpine\t127.0.0.1:5432->5432/tcp\n"
            "===DELIM_NET===\n"
            "Netid State Recv-Q Send-Q Local Address:Port Peer Address:Port\n"
            "tcp   LISTEN 0      128        0.0.0.0:80          0.0.0.0:*\n"
            "tcp   LISTEN 0      128        0.0.0.0:8084        0.0.0.0:*\n"
        )
        self.mock_ssh.execute_command = AsyncMock(return_value=self.standard_output)
        self.monitor = ServerMonitorService(ssh_client=self.mock_ssh)
        self.executor = AgentToolExecutor(
            ssh_client=self.mock_ssh,
            message_cache=MagicMock(),
            server_monitor_service=self.monitor,
        )

    async def test_health_report_latency_stress_benchmark(self):
        """Stress-tests execution latency over 50 consecutive runs to ensure P95/P99 < 3.0s."""
        latencies = []
        for _ in range(50):
            t0 = time.perf_counter()
            res = await self.executor._execute_tool("get_system_health_report", {})
            t1 = time.perf_counter()
            latencies.append(t1 - t0)
            self.assertIn("BÁO CÁO SỨC KHỎE MÁY CHỦ", str(res))

        mean_lat = sum(latencies) / len(latencies)
        max_lat = max(latencies)
        latencies.sort()
        p95 = latencies[int(len(latencies) * 0.95)]
        p99 = latencies[int(len(latencies) * 0.99)]

        self.assertLess(max_lat, 3.0, f"Max latency {max_lat:.4f}s exceeded 3.0s!")
        self.assertLess(p95, 0.5, f"P95 latency {p95:.4f}s exceeded 0.5s baseline!")
        self.assertLess(mean_lat, 0.1, f"Mean latency {mean_lat:.4f}s exceeded 0.1s!")

    async def test_health_report_corrupted_probe_missing_delimiters(self):
        """Tests resilience against corrupted SSH outputs where delimiters are missing."""
        corrupted_outputs = [
            "",  # Empty output
            "Garbage unformatted string with no delimiters at all",
            "===DELIM_RAM===\nInvalid RAM table",
            "===DELIM_DOCKER===\nMalformed docker list",
            "cat: /proc/loadavg: No such file or directory",
        ]
        for out in corrupted_outputs:
            with self.subTest(corrupted_out=out):
                self.mock_ssh.execute_command = AsyncMock(return_value=out)
                res = await self.monitor.get_system_health_report()
                self.assertEqual(res["status"], "success")
                # Even with corrupted text, it must not crash with unhandled exception
                # and should fall back gracefully
                self.assertIn("overall_health", res)

    async def test_health_report_ssh_error_handling(self):
        """Tests graceful handling when SSH connection raises an exception."""
        self.mock_ssh.execute_command = AsyncMock(side_effect=ConnectionResetError("Connection lost"))
        res = await self.executor._execute_tool("get_system_health_report", {})
        self.assertIn("Không thể kết nối SSH", str(res))


class TestAdversarialCalculator(unittest.IsolatedAsyncioTestCase):
    """Stress tests, edge cases, and code injection attacks on calculate tool."""

    async def asyncSetUp(self):
        self.calc_svc = CalculatorService()
        self.executor = AgentToolExecutor(
            ssh_client=MagicMock(),
            message_cache=MagicMock(),
            calculator_service=self.calc_svc,
        )

    async def test_division_by_zero_variants(self):
        """Tests all permutations of division and modulo by zero."""
        div_zero_expressions = [
            "1 / 0",
            "0 / 0",
            "100 / (10 - 10)",
            "1 // 0",
            "50 // (5 * 0)",
            "10 % 0",
            "100 % (2 - 2)",
            "pow(2, 5, 0)",  # Ternary pow mod 0
        ]
        for expr in div_zero_expressions:
            with self.subTest(expr=expr):
                res = await self.executor._execute_tool("calculate", {"expression": expr})
                res_str = str(res)
                self.assertTrue(
                    "chia cho số 0" in res_str or "Lỗi" in res_str,
                    f"Division by zero '{expr}' not caught cleanly! Got: {res_str}",
                )

    async def test_extreme_domain_violations_and_overflow(self):
        """Tests math functions with domain errors or excessive exponents."""
        domain_errors = [
            "sqrt(-1)",
            "sqrt(-100.5)",
            "log(0)",
            "log(-10)",
            "log10(-5)",
            "factorial(-1)",
            "factorial(101)",  # Exceeds MAX_FACTORIAL_INPUT (100)
            "acos(2)",
            "asin(1.5)",
        ]
        for expr in domain_errors:
            with self.subTest(expr=expr):
                res = await self.executor._execute_tool("calculate", {"expression": expr})
                self.assertIn("Lỗi", str(res))

    async def test_cpu_exhaustion_dos_bomb_attacks(self):
        """Tests exponential and combinatorial DoS bomb attacks."""
        dos_expressions = [
            "2 ** 10001",  # Exponent > MAX_EXPONENT (10000)
            "2 ** 1001",   # Base > 1 and exponent > 1000
            "9 ** 9999999",
            "pow(2, 10001)",
            "factorial(500)",
            "2 ** (2 ** 100)",
            "a" * 1500,  # String > MAX_EXPR_LENGTH (1000)
        ]
        for expr in dos_expressions:
            with self.subTest(expr=expr[:30]):
                res = await self.executor._execute_tool("calculate", {"expression": expr})
                self.assertIn("Lỗi", str(res))

    async def test_code_injection_and_sandbox_escape(self):
        """Tests adversarial code execution, dunder crawling, and arbitrary execution bypasses."""
        injection_attempts = [
            "__import__('os').system('id')",
            "__import__('subprocess').run(['whoami'])",
            "[c for c in ().__class__.__base__.__subclasses__() if c.__name__ == 'catch_warnings'][0]()._module.__builtins__['__import__']('os').system('ls')",
            "(lambda x: x + 1)(5)",
            "exec('import os')",
            "eval('1 + 1')",
            "open('/etc/passwd').read()",
            "globals()",
            "locals()",
            "dir()",
            "getattr(math, 'sin')(1)",
            "1 + 1; import os",
            "1\nimport sys",
            "class Evil: pass",
            "{'a': 1}['a']",  # Subscript / indexing forbidden
            "f'{1+1}'",  # FormattedValue forbidden
        ]
        for payload in injection_attempts:
            with self.subTest(payload=payload[:30]):
                res = await self.executor._execute_tool("calculate", {"expression": payload})
                res_str = str(res)
                self.assertTrue(
                    "Lỗi" in res_str or "không được phép" in res_str,
                    f"Security injection payload '{payload}' escaped sandbox! Got: {res_str}",
                )

    async def test_compound_interest_adversarial_boundaries(self):
        """Tests compound interest function with extreme / adversarial arguments."""
        # Negative principal / years
        res_neg = await self.executor._execute_tool(
            "calculate",
            {"expression": "compound_interest(-1000, 7.2, 12, 1)"},
        )
        self.assertIn("Lỗi", str(res_neg))

        # Extreme exponents (years = 10000)
        res_extreme = await self.executor._execute_tool(
            "calculate",
            {"expression": "compound_interest(1000, 7.2, 12, 10000)"},
        )
        self.assertIn("Lỗi", str(res_extreme))

        # Rate normalization check: percentage 7.2% vs decimal 0.072 gives identical result
        res_pct = await self.calc_svc.calculate("compound_interest(1000000, 7.2, 12, 2)")
        res_dec = await self.calc_svc.calculate("compound_interest(1000000, 0.072, 12, 2)")
        self.assertEqual(res_pct["result"], res_dec["result"])


class TestAdversarialFileManager(unittest.IsolatedAsyncioTestCase):
    """Stress tests, 2000-char clamp, and security boundaries on read_file_content and list_files."""

    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.test_dir.name)
        self.file_svc = FileManagerService(base_dir=str(self.base_path))
        self.executor = AgentToolExecutor(
            ssh_client=MagicMock(),
            message_cache=MagicMock(),
            file_manager_service=self.file_svc,
        )

    def tearDown(self):
        self.test_dir.cleanup()

    async def test_exact_2000_char_clamping_boundary(self):
        """Verifies clamping at 1999, 2000, 2001, and 5000 characters."""
        # 1. Exact 1999 characters -> Not truncated
        f_1999 = self.base_path / "f1999.txt"
        f_1999.write_text("A" * 1999, encoding="utf-8")
        res_1999 = await self.file_svc.read_file_content(str(f_1999))
        self.assertFalse(res_1999["is_truncated"])
        self.assertEqual(len(res_1999["content"]), 1999)
        self.assertNotIn("cắt ngắn", res_1999["content"])

        # 2. Exact 2000 characters -> Not truncated
        f_2000 = self.base_path / "f2000.txt"
        f_2000.write_text("B" * 2000, encoding="utf-8")
        res_2000 = await self.file_svc.read_file_content(str(f_2000))
        self.assertFalse(res_2000["is_truncated"])
        self.assertEqual(len(res_2000["content"]), 2000)
        self.assertNotIn("cắt ngắn", res_2000["content"])

        # 3. Exact 2001 characters -> MUST be truncated
        f_2001 = self.base_path / "f2001.txt"
        f_2001.write_text("C" * 2001, encoding="utf-8")
        res_2001 = await self.file_svc.read_file_content(str(f_2001))
        self.assertTrue(res_2001["is_truncated"])
        self.assertIn("vượt quá giới hạn 2000 ký tự", res_2001["content"])
        raw_body = res_2001["content"].split("\n... [Nội dung bị cắt ngắn")[0]
        self.assertEqual(len(raw_body), 2000)
        self.assertEqual(raw_body, "C" * 2000)

        # 4. Large file 10,000 characters -> Truncated with raw body exactly 2000
        f_10000 = self.base_path / "f10000.txt"
        f_10000.write_text("D" * 10000, encoding="utf-8")
        res_10000 = await self.file_svc.read_file_content(str(f_10000))
        self.assertTrue(res_10000["is_truncated"])
        raw_body_large = res_10000["content"].split("\n... [Nội dung bị cắt ngắn")[0]
        self.assertEqual(len(raw_body_large), 2000)

    async def test_sensitive_files_blacklist_variations(self):
        """Tests that all variants of sensitive files (.env*, .ssh, keys) are vetoed."""
        sensitive_names = [
            ".env",
            ".env.local",
            ".env.production",
            ".env.staging",
            "id_rsa",
            "id_rsa.pub",
            "id_ed25519",
            "authorized_keys",
            ".bashrc",
            ".zshrc",
        ]
        for name in sensitive_names:
            target_f = self.base_path / name
            target_f.write_text("SECRET_KEY=12345", encoding="utf-8")
            with self.subTest(sensitive_name=name):
                res = await self.file_svc.read_file_content(str(target_f))
                self.assertEqual(
                    res.get("status"),
                    "security_veto",
                    f"Sensitive file '{name}' was not vetoed! Got: {res}",
                )

    async def test_path_traversal_attempts(self):
        """Tests prevention of path traversal attacks attempting to escape boundary."""
        traversals = [
            "../../etc/passwd",
            "..\\..\\windows\\win.ini",
            "%2e%2e%2fetc%2fpasswd",
            "subdir/../../.env",
            "foo/../../../bar",
        ]
        for trav in traversals:
            with self.subTest(traversal=trav):
                res = await self.file_svc.read_file_content(trav)
                self.assertTrue(
                    res.get("status") in ("security_veto", "error"),
                    f"Traversal '{trav}' was not blocked! Got: {res}",
                )

    async def test_command_injection_in_file_path(self):
        """Tests injection symbols in file paths are rejected immediately."""
        bad_paths = [
            "file.txt; rm -rf /",
            "file.txt && cat /etc/passwd",
            "file.txt | whoami",
            "`id`.txt",
            "$(cat /etc/shadow)",
            "file\nname.txt",
        ]
        for bp in bad_paths:
            with self.subTest(bad_path=bp):
                res = await self.file_svc.read_file_content(bp)
                self.assertEqual(res["status"], "error")
                self.assertIn("ký tự nguy hiểm", res["message"])


class TestAdversarialScheduler(unittest.IsolatedAsyncioTestCase):
    """Stress tests and boundary validation for schedule_reminder."""

    async def asyncSetUp(self):
        self.scheduler = SchedulerService(use_db=False)
        self.executor = AgentToolExecutor(
            ssh_client=MagicMock(),
            message_cache=MagicMock(),
            scheduler_service=self.scheduler,
        )

    async def test_delay_minutes_edge_cases(self):
        """Tests negative, zero, and invalid type delays."""
        invalid_delays = [
            0,
            -1,
            -60,
            -999999,
            "not_a_number",
            "0",
            "-5",
        ]
        for delay in invalid_delays:
            with self.subTest(delay=delay):
                res = await self.executor._execute_tool(
                    "schedule_reminder",
                    {"message": "Test invalid delay", "delay_minutes": delay},
                )
                res_str = str(res)
                self.assertTrue(
                    "phải lớn hơn 0" in res_str or "không hợp lệ" in res_str or "Lỗi khi thực thi công cụ" in res_str,
                    f"Invalid delay '{delay}' was unexpectedly accepted! Result: {res_str}",
                )

    async def test_repeat_options_normalization_and_rejection(self):
        """Tests repeat parameter validation: case insensitivity and rejection of invalid options."""
        # Valid normalized variations (case-insensitive)
        valid_repeats = ["daily", "DAILY", " Daily ", "weekly", "WEEKLY", "none", None]
        for rep in valid_repeats:
            with self.subTest(rep=rep):
                res = await self.scheduler.schedule_reminder(
                    message=f"Reminder repeat {rep}",
                    delay_minutes=15,
                    repeat=rep,
                )
                self.assertEqual(
                    res["status"],
                    "success",
                    f"Valid repeat option '{rep}' failed! Got: {res}",
                )

        # Invalid repeats must be rejected
        invalid_repeats = [
            "hourly",
            "monthly",
            "yearly",
            "every_minute",
            "custom",
            "cron",
            "123",
        ]
        for bad_rep in invalid_repeats:
            with self.subTest(bad_rep=bad_rep):
                res = await self.scheduler.schedule_reminder(
                    message="Reminder test",
                    delay_minutes=15,
                    repeat=bad_rep,
                )
                self.assertEqual(res["status"], "error")
                self.assertIn("không hợp lệ", res["message"])

    async def test_empty_or_whitespace_message(self):
        """Tests empty or pure whitespace messages are rejected."""
        empty_messages = ["", "   ", "\t", "\n\r", None]
        for msg in empty_messages:
            with self.subTest(msg=msg):
                res = await self.scheduler.schedule_reminder(
                    message=msg,
                    delay_minutes=10,
                )
                self.assertEqual(res["status"], "error")
                self.assertIn("không được để trống", res["message"])

    async def test_sql_injection_resilience_in_message(self):
        """Tests SQL injection payloads in message string do not compromise reminder storage."""
        sql_payloads = [
            "'; DROP TABLE agent_pending_tasks; --",
            "' OR 1=1; --",
            "\" UNION SELECT * FROM users; --",
            "<script>alert('xss')</script>",
        ]
        for payload in sql_payloads:
            with self.subTest(payload=payload):
                res = await self.scheduler.schedule_reminder(
                    message=payload,
                    delay_minutes=10,
                )
                self.assertEqual(res["status"], "success")
                self.assertEqual(res["message"], payload)
                # Verify retrieval preserves verbatim payload without corruption
                item = await self.scheduler._memory_store.get(res["reminder_id"])
                self.assertEqual(item["message"], payload)

    async def test_cancellation_of_nonexistent_and_already_cancelled_reminder(self):
        """Tests cancel_reminder on non-existent or duplicate IDs."""
        # Non-existent ID
        res_non = await self.executor._execute_tool(
            "cancel_reminder",
            {"reminder_id": 99999999},
        )
        self.assertIn("Không tìm thấy", str(res_non))

        # Create one, cancel once -> Success; cancel twice -> Not found / already cancelled
        create_res = await self.scheduler.schedule_reminder(
            message="To be cancelled",
            delay_minutes=10,
        )
        r_id = create_res["reminder_id"]
        res_c1 = await self.executor._execute_tool("cancel_reminder", {"reminder_id": r_id})
        self.assertIn("thành công", str(res_c1))

        res_c2 = await self.executor._execute_tool("cancel_reminder", {"reminder_id": r_id})
        self.assertIn("Không tìm thấy", str(res_c2))


if __name__ == "__main__":
    unittest.main()
