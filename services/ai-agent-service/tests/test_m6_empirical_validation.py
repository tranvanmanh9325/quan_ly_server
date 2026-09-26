"""
test_m6_empirical_validation.py — Final Empirical Validation Test Suite (Milestone M6).

Validates real SUT (System Under Test) operational capabilities across critical R1-R8 tools:
1. `schedule_reminder`: Real reminder creation, listing, cancellation, boundary validation.
2. `get_system_health_report`: 5-dimensional server diagnostics (CPU, RAM, Disk, Load, Network)
   with latency benchmark (< 3.0 seconds) and Telegram-compliant Markdown summary format.
3. `create_note`, `search_notes`, `list_notes`, `delete_note`: Real markdown notes management,
   full-text searching, tag filtering, and Tier 2 safe trash deletion (.trash/).
4. `calculate`, `convert_units`: Complex math formulas (powers, roots, statistics, compound interest),
   unit conversions across temperature, mass, length, speed, data size, and security sandbox checks.
5. `get_ngrok_status`: Probing ports 4040-4044 or host SSH, validating structured tunnel outputs.
6. `list_files`, `read_file_content`: Real filesystem inspection with 2000-char clamping,
   sensitive files blacklist protection (.env, .ssh), and binary rejection.
7. DevOps 1-Shot Protocol: Dynamic tool scoping selects unified 5-dim health probe over fragmented calls.
"""

import asyncio
import base64
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.ai_agent_tools import (
    AgentToolExecutor,
    ACTION_TIER_1_SAFE,
    ACTION_TIER_2_REVERSIBLE,
)
from app.services.scheduler_service import SchedulerService
from app.services.server_monitor_service import ServerMonitorService
from app.services.notes_service import NotesService
from app.services.calculator_service import CalculatorService
from app.services.cron_service import CronService
from app.services.email_report_service import EmailReportService
from app.services.network_service import NetworkService
from app.services.file_manager_service import FileManagerService, MAX_READ_CHARS_LIMIT


class StatefulNotesSshClient:
    """
    Simulates a stateful remote Linux host SSH shell specifically for NotesService.
    Maintains a virtual filesystem dictionary for genuine file creation, searching,
    listing, and trash movements.
    """

    def __init__(self, notes_dir: str = "/home/kirito/quan_ly_server/data/notes"):
        self.notes_dir = notes_dir
        self.trash_dir = f"{notes_dir}/.trash"
        self.virtual_fs = {}  # filepath -> file_content
        self.executed_commands = []

    async def execute_command(self, cmd: str) -> str:
        self.executed_commands.append(cmd)

        # 1. Write note via Base64 pipeline: mkdir -p ... && echo <b64> | base64 -d | tee <path>
        if "base64 -d | tee" in cmd:
            try:
                parts = cmd.split("echo ")
                b64_part = parts[1].split(" |")[0].strip()
                target_path = cmd.split("tee ")[1].strip()
                content = base64.b64decode(b64_part).decode("utf-8")
                self.virtual_fs[target_path] = content
                return content
            except Exception as e:
                return f"Error writing file: {e}"

        # 2. Safe delete (move to .trash/): mkdir -p ... && mv <src> <trash_path>
        if "mv " in cmd:
            parts = cmd.split("mv ")[1].split()
            if len(parts) >= 2:
                src = parts[0]
                dst = parts[1]
                if src in self.virtual_fs:
                    content = self.virtual_fs.pop(src)
                    self.virtual_fs[dst] = content
                    return ""
                return f"mv: cannot stat '{src}': No such file or directory"

        # 3. Directory creation
        if cmd.startswith("mkdir -p"):
            return ""

        # 3. List notes metadata: grep -H -E "^(id|title|tags|created_at):" ...
        if "grep -H -E" in cmd:
            output_lines = []
            for path, content in self.virtual_fs.items():
                if path.startswith(self.trash_dir):
                    continue
                for line in content.splitlines():
                    clean_l = line.strip()
                    for key in ("id", "title", "tags", "created_at"):
                        if clean_l.startswith(f"{key}:"):
                            output_lines.append(f"{path}:{clean_l}")
            return "\n".join(output_lines)

        # 4. Full-text search: grep -rn -i ...
        if "grep -rn -i" in cmd:
            parts = cmd.split("-- ")
            if len(parts) > 1:
                raw_q = parts[1].split(" ")[0].strip().strip("'").strip('"')
            else:
                raw_q = ""
            query_lower = raw_q.lower()
            matches = []
            for path, content in self.virtual_fs.items():
                if path.startswith(self.trash_dir):
                    continue
                lines = content.splitlines()
                for idx, line in enumerate(lines, 1):
                    if query_lower in line.lower():
                        matches.append(f"{path}:{idx}:{line}")
            return "\n".join(matches)

        return ""


class TestEmpiricalScheduleReminder(unittest.IsolatedAsyncioTestCase):
    """Empirical testing of R1 Smart Scheduler over real service & executor."""

    async def asyncSetUp(self):
        # Initialize isolated in-memory scheduler service (use_db=False)
        self.scheduler = SchedulerService(use_db=False)
        mock_ssh = MagicMock()
        mock_cache = MagicMock()
        mock_telegram = MagicMock()
        mock_telegram.send_message = AsyncMock(return_value=True)

        self.executor = AgentToolExecutor(
            ssh_client=mock_ssh,
            message_cache=mock_cache,
            telegram_bot=mock_telegram,
            scheduler_service=self.scheduler,
        )

    async def test_schedule_reminder_lifecycle(self):
        """Creates, lists, inspects, and cancels a real reminder."""
        # 1. Create reminder
        res_create = await self.executor._execute_tool(
            "schedule_reminder",
            {
                "message": "Kiểm tra sao lưu cơ sở dữ liệu PostgreSQL",
                "delay_minutes": 30,
                "repeat": "daily",
            },
        )
        self.assertIn("Đã đặt lịch nhắc thành công", str(res_create))
        self.assertIn("Kiểm tra sao lưu", str(res_create))

        # 2. List scheduled reminders
        res_list = await self.executor._execute_tool("list_scheduled_reminders", {})
        self.assertIn("DANH SÁCH LỊCH NHẮC ĐANG CHỜ", str(res_list).upper())
        self.assertIn("Kiểm tra sao lưu cơ sở dữ liệu PostgreSQL", str(res_list))

        # Extract reminder ID from internal store to perform genuine cancellation
        pending_items = await self.scheduler.list_scheduled_reminders()
        self.assertEqual(pending_items["total"], 1)
        reminder_id = pending_items["reminders"][0]["id"]

        # 3. Cancel reminder
        res_cancel = await self.executor._execute_tool(
            "cancel_reminder",
            {"reminder_id": reminder_id},
        )
        self.assertIn(f"#{reminder_id}", str(res_cancel))
        self.assertIn("thành công", str(res_cancel))

        # 4. Verify list is now empty of pending items
        res_list_after = await self.executor._execute_tool("list_scheduled_reminders", {})
        self.assertIn("Hiện không có lịch nhắc nhở nào đang chờ", str(res_list_after))

    async def test_schedule_reminder_boundary_validation(self):
        """Verifies input sanitization and error handling on bad inputs."""
        # Negative / Zero minutes
        res_zero = await self.executor._execute_tool(
            "schedule_reminder",
            {"message": "Test zero delay", "delay_minutes": 0},
        )
        self.assertIn("phải lớn hơn 0", str(res_zero))

        # Invalid repeat option
        res_bad_repeat = await self.executor._execute_tool(
            "schedule_reminder",
            {"message": "Test repeat", "delay_minutes": 10, "repeat": "hourly"},
        )
        self.assertIn("Tần suất lặp 'hourly' không hợp lệ", str(res_bad_repeat))

        # Empty message
        res_empty = await self.executor._execute_tool(
            "schedule_reminder",
            {"message": "   ", "delay_minutes": 10},
        )
        self.assertIn("không được để trống", str(res_empty))


class TestEmpiricalSystemHealthReport(unittest.IsolatedAsyncioTestCase):
    """Empirical testing of R2 Health Monitor: 5 dimensions, latency < 3s, Markdown formatting."""

    async def asyncSetUp(self):
        # Mock SSH Client returning deterministic Linux server composite output
        self.mock_ssh = MagicMock()
        mock_output = (
            "0.35 0.42 0.38 2/320 9876\n"
            "===DELIM_RAM===\n"
            "              total        used        free      shared  buff/cache   available\n"
            "Mem:          15890        4500        7800         150        3590       11240\n"
            "Swap:          2048           0        2048\n"
            "===DELIM_DISK===\n"
            "Filesystem      Size  Used Avail Use% Mounted on\n"
            "/dev/sda1       100G   42G   58G  42% /\n"
            "===DELIM_DOCKER===\n"
            "dashboard_ai_agent\tUp 4 days (healthy)\tai_agent:latest\t0.0.0.0:8084->8084/tcp\n"
            "dashboard_server_api\tUp 4 days (healthy)\tserver_api:latest\t0.0.0.0:8000->8000/tcp\n"
            "postgres\tUp 6 days (healthy)\tpostgres:17-alpine\t127.0.0.1:5432->5432/tcp\n"
            "===DELIM_NET===\n"
            "Netid State Recv-Q Send-Q Local Address:Port Peer Address:Port\n"
            "tcp   LISTEN 0      128        0.0.0.0:80          0.0.0.0:*\n"
            "tcp   LISTEN 0      128        0.0.0.0:443         0.0.0.0:*\n"
            "tcp   LISTEN 0      128      127.0.0.1:5432        0.0.0.0:*\n"
            "tcp   LISTEN 0      128        0.0.0.0:8084        0.0.0.0:*\n"
        )
        self.mock_ssh.execute_command = AsyncMock(return_value=mock_output)

        self.monitor = ServerMonitorService(ssh_client=self.mock_ssh)
        self.executor = AgentToolExecutor(
            ssh_client=self.mock_ssh,
            message_cache=MagicMock(),
            server_monitor_service=self.monitor,
        )

    async def test_get_system_health_report_latency_and_markdown(self):
        """Measures latency (< 3s) and verifies valid Markdown 5-dim output format."""
        start_time = time.perf_counter()
        raw_res = await self.executor._execute_tool("get_system_health_report", {})
        latency = time.perf_counter() - start_time

        # Latency constraint
        self.assertLess(latency, 3.0, f"Health report probe latency {latency:.2f}s exceeded 3.0s!")

        # Format inspection
        res_str = str(raw_res)
        self.assertIn("BÁO CÁO SỨC KHỎE MÁY CHỦ", res_str)
        self.assertIn("CPU Load:", res_str)
        self.assertIn("RAM:", res_str)
        self.assertIn("Ổ cứng (/):", res_str)
        self.assertIn("Docker:", res_str)
        self.assertIn("Mạng:", res_str)
        self.assertIn("HEALTHY", res_str)

        # Granular metrics inspection directly from service
        report_dict = await self.monitor.get_system_health_report()
        self.assertEqual(report_dict["status"], "success")
        self.assertEqual(report_dict["overall_health"], "HEALTHY")
        self.assertEqual(report_dict["cpu"]["load_1m"], 0.35)
        self.assertEqual(report_dict["ram"]["usage_percent"], 28.3)
        self.assertEqual(report_dict["disk"]["usage_percent"], "42%")
        self.assertEqual(report_dict["docker"]["total_running"], 3)
        self.assertIn(8084, report_dict["network"]["listening_ports"])

    async def test_get_system_health_report_degraded_state(self):
        """Verifies warning state detection when memory is critical or container unhealthy."""
        degraded_output = (
            "4.50 3.80 2.90 5/450 1122\n"
            "===DELIM_RAM===\n"
            "              total        used        free      shared  buff/cache   available\n"
            "Mem:          16000       15200         400         100         400         500\n"
            "===DELIM_DISK===\n"
            "Filesystem      Size  Used Avail Use% Mounted on\n"
            "/dev/sda1       100G   92G    8G  92% /\n"
            "===DELIM_DOCKER===\n"
            "dashboard_server_api\tUp 1 hour (unhealthy)\tserver_api:latest\t0.0.0.0:8000->8000/tcp\n"
            "===DELIM_NET===\n"
            "Netid State Recv-Q Send-Q Local Address:Port Peer Address:Port\n"
            "tcp   LISTEN 0      128        0.0.0.0:80          0.0.0.0:*\n"
        )
        self.mock_ssh.execute_command = AsyncMock(return_value=degraded_output)
        report_dict = await self.monitor.get_system_health_report()
        self.assertEqual(report_dict["overall_health"], "CRITICAL")
        self.assertTrue(len(report_dict["issues"]) >= 2)
        self.assertTrue(any("unhealthy" in iss for iss in report_dict["issues"]))


class TestEmpiricalNotesService(unittest.IsolatedAsyncioTestCase):
    """Empirical testing of R3 Personal Notes & Knowledge Base."""

    async def asyncSetUp(self):
        self.ssh_shell = StatefulNotesSshClient()
        self.notes_svc = NotesService(ssh_client=self.ssh_shell)
        self.executor = AgentToolExecutor(
            ssh_client=self.ssh_shell,
            message_cache=MagicMock(),
            notes_service=self.notes_svc,
        )

    async def test_notes_full_crud_and_search_lifecycle(self):
        """Tests create, list, search, and delete note operations."""
        # 1. Create note A
        res_create_a = await self.executor._execute_tool(
            "create_note",
            {
                "title": "Kiến trúc 9Router Multi-Provider",
                "content": "Hệ thống gồm Groq Tier 1 và OpenRouter Tier 2 với cơ chế Round-Robin",
                "tags": ["architecture", "ai_agent"],
            },
        )
        self.assertIn("Đã lưu ghi chú thành công", str(res_create_a))
        self.assertIn("Kiến trúc 9Router Multi-Provider", str(res_create_a))

        # 2. Create note B
        res_create_b = await self.executor._execute_tool(
            "create_note",
            {
                "title": "Sổ tay DevOps Kirito Server",
                "content": "Hướng dẫn cấu hình Nginx, Traefik và PostgreSQL 17 trên Docker",
                "tags": ["devops", "server"],
            },
        )
        self.assertIn("Đã lưu ghi chú thành công", str(res_create_b))

        # 3. List notes (all)
        res_list = await self.executor._execute_tool("list_notes", {})
        self.assertIn("Kiến trúc 9Router Multi-Provider", str(res_list))
        self.assertIn("Sổ tay DevOps Kirito Server", str(res_list))

        # 4. List notes filtered by tag
        res_filter = await self.executor._execute_tool("list_notes", {"tag": "devops"})
        self.assertIn("Sổ tay DevOps Kirito Server", str(res_filter))
        self.assertNotIn("Kiến trúc 9Router Multi-Provider", str(res_filter))

        # 5. Search notes by query
        res_search = await self.executor._execute_tool("search_notes", {"query": "Traefik"})
        self.assertIn("Sổ tay DevOps Kirito Server", str(res_search))

        # Get note ID to delete
        list_data = await self.notes_svc.list_notes(tag="architecture")
        note_id_to_del = list_data["notes"][0]["id"]

        # 6. Delete note (Tier 2 safe move to .trash/)
        res_del = await self.executor._execute_tool("delete_note", {"note_id": note_id_to_del})
        self.assertIn("thùng rác (.trash) an toàn", str(res_del))
        self.assertIn(".trash", str(res_del))

        # 7. Verify deleted note is no longer in active list
        res_list_final = await self.executor._execute_tool("list_notes", {})
        self.assertNotIn("Kiến trúc 9Router Multi-Provider", str(res_list_final))
        self.assertIn("Sổ tay DevOps Kirito Server", str(res_list_final))


class TestEmpiricalCalculatorAndUnitConversion(unittest.IsolatedAsyncioTestCase):
    """Empirical testing of R4 Calculator & Unit Conversion."""

    async def asyncSetUp(self):
        self.calc_svc = CalculatorService()
        self.executor = AgentToolExecutor(
            ssh_client=MagicMock(),
            message_cache=MagicMock(),
            calculator_service=self.calc_svc,
        )

    async def test_calculate_complex_expressions(self):
        """Tests complex arithmetic, mathematical functions, statistics, and compound interest."""
        # 1. Complex arithmetic
        res_arith = await self.executor._execute_tool(
            "calculate",
            {"expression": "(2 ** 8 + 44) * 3 / 2"},
        )
        self.assertIn("450", str(res_arith))

        # 2. Math functions (sqrt, sin, log10)
        res_math = await self.executor._execute_tool(
            "calculate",
            {"expression": "sqrt(144) + log10(1000)"},
        )
        self.assertIn("15", str(res_math))

        # 3. Statistics (mean)
        res_stat = await self.executor._execute_tool(
            "calculate",
            {"expression": "mean([10, 20, 30, 40, 50])"},
        )
        self.assertIn("30", str(res_stat))

        # 4. Compound interest: 100,000,000 VND at 7.2% for 3 years compounded monthly
        res_interest = await self.executor._execute_tool(
            "calculate",
            {"expression": "compound_interest(100000000, 7.2, 12, 3)"},
        )
        self.assertIn("124,030", str(res_interest))  # Output format contains commas

    async def test_calculate_security_sandbox(self):
        """Rejects code injection, builtins, and dangerous imports."""
        bad_expressions = [
            "__import__('os').system('ls')",
            "open('/etc/passwd').read()",
            "eval('2 + 2')",
            "exec('x = 10')",
        ]
        for bad_expr in bad_expressions:
            with self.subTest(bad_expr=bad_expr):
                res = await self.executor._execute_tool("calculate", {"expression": bad_expr})
                self.assertTrue(
                    "Lỗi tính toán" in str(res) or "không được phép" in str(res),
                    f"Bad expression '{bad_expr}' was not cleanly rejected! Result: {res}"
                )

    async def test_convert_units_multi_domain(self):
        """Tests unit conversions across multiple physical and computational domains."""
        # Temperature
        res_temp = await self.executor._execute_tool(
            "convert_units",
            {"value": 100, "from_unit": "celsius", "to_unit": "fahrenheit"},
        )
        self.assertIn("212", str(res_temp))

        # Length
        res_len = await self.executor._execute_tool(
            "convert_units",
            {"value": 5, "from_unit": "km", "to_unit": "m"},
        )
        self.assertIn("5000", str(res_len))

        # Mass
        res_mass = await self.executor._execute_tool(
            "convert_units",
            {"value": 2.5, "from_unit": "kg", "to_unit": "g"},
        )
        self.assertIn("2500", str(res_mass))

        # Speed
        res_speed = await self.executor._execute_tool(
            "convert_units",
            {"value": 72, "from_unit": "km/h", "to_unit": "m/s"},
        )
        self.assertIn("20", str(res_speed))

        # Digital Data Size
        res_data = await self.executor._execute_tool(
            "convert_units",
            {"value": 2048, "from_unit": "mb", "to_unit": "gb"},
        )
        self.assertIn("2", str(res_data))


class TestEmpiricalNgrokStatus(unittest.IsolatedAsyncioTestCase):
    """Empirical testing of R7 Ngrok status probing."""

    async def asyncSetUp(self):
        self.mock_ssh = MagicMock()
        mock_ngrok_json = json.dumps({
            "tunnels": [
                {
                    "name": "fastapi_api",
                    "public_url": "https://kirito-server.ngrok-free.app",
                    "proto": "https",
                    "config": {"addr": "http://localhost:8084"},
                    "metrics": {"conns": {"count": 128}},
                }
            ]
        })
        self.mock_ssh.execute_command = AsyncMock(return_value=mock_ngrok_json)

        # Force HTTP ports to fail so it falls back cleanly to mock SSH
        self.net_svc = NetworkService(ssh_client=self.mock_ssh, probe_ports=[9998, 9999])
        self.executor = AgentToolExecutor(
            ssh_client=self.mock_ssh,
            message_cache=MagicMock(),
            network_service=self.net_svc,
        )

    async def test_get_ngrok_status_tunnel_structure(self):
        """Verifies tunnel discovery and output schema."""
        res = await self.executor._execute_tool("get_ngrok_status", {})
        res_str = str(res)
        self.assertIn("Tìm thấy 1 tunnel", res_str)

        # Direct service call
        status_data = await self.net_svc.get_ngrok_status()
        self.assertEqual(status_data["status"], "success")
        self.assertEqual(status_data["total_tunnels"], 1)
        self.assertEqual(status_data["tunnels"][0]["public_url"], "https://kirito-server.ngrok-free.app")


class TestEmpiricalFileManagerAndSecurity(unittest.IsolatedAsyncioTestCase):
    """Empirical testing of R8 File Manager: Real directory scanning, 2000-char clamp, security vetos."""

    def setUp(self):
        # Create a genuine temporary directory on the host filesystem
        self.test_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.test_dir.name)

        # Populate test files
        self.readme = self.base_path / "README.md"
        self.readme.write_text("# Project Server Documentation\nLine 1\nLine 2", encoding="utf-8")

        # Large file exceeding 2000 characters
        self.large_file = self.base_path / "syslog.txt"
        large_content = "ENTRY LOG INFO: System healthy and active.\n" * 70  # ~3000 chars
        self.large_file.write_text(large_content, encoding="utf-8")

        # Sensitive file
        self.env_file = self.base_path / ".env"
        self.env_file.write_text("DB_PASSWORD=secret_super_token_12345", encoding="utf-8")

        # Binary file
        self.binary_file = self.base_path / "image.png"
        self.binary_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00")

        self.file_svc = FileManagerService(base_dir=str(self.base_path))
        self.executor = AgentToolExecutor(
            ssh_client=MagicMock(),
            message_cache=MagicMock(),
            file_manager_service=self.file_svc,
        )

    def tearDown(self):
        self.test_dir.cleanup()

    async def test_list_files_filters_sensitive_env(self):
        """Directory listing must omit sensitive files like .env."""
        res = await self.file_svc.list_files(path=str(self.base_path))
        self.assertEqual(res["status"], "success")
        item_names = [it["name"] for it in res["items"]]
        self.assertIn("README.md", item_names)
        self.assertIn("syslog.txt", item_names)
        self.assertNotIn(".env", item_names, ".env must be filtered out of directory listing!")

    async def test_read_file_content_clamping_2000_chars(self):
        """Reading file content larger than 2000 characters must clamp and notify."""
        res = await self.file_svc.read_file_content(path=str(self.large_file))
        self.assertEqual(res["status"], "success")
        self.assertTrue(res["is_truncated"])
        self.assertIn("vượt quá giới hạn 2000 ký tự", res["content"])
        # Content length up to truncation notice
        raw_part = res["content"].split("\n... [Nội dung bị cắt ngắn")[0]
        self.assertEqual(len(raw_part), MAX_READ_CHARS_LIMIT)

    async def test_read_file_content_security_veto_sensitive(self):
        """Reading sensitive files must be strictly vetoed."""
        res = await self.file_svc.read_file_content(path=str(self.env_file))
        self.assertEqual(res["status"], "security_veto")
        self.assertIn("Từ chối đọc tệp nhạy cảm", res["message"])

    async def test_read_file_content_binary_rejection(self):
        """Binary files must be cleanly rejected from text reading."""
        res = await self.file_svc.read_file_content(path=str(self.binary_file))
        self.assertEqual(res["status"], "error")
        self.assertEqual(res["reason"], "binary_file")
        self.assertIn("Không thể đọc tệp nhị phân", res["message"])


class TestEmpiricalDevOpsOneShotProtocol(unittest.TestCase):
    """Verifies that user health questions activate the 1-shot health report tool and obey <= 8 tools."""

    def setUp(self):
        self.executor = AgentToolExecutor(
            ssh_client=MagicMock(),
            message_cache=MagicMock(),
        )

    def test_devops_health_query_scoping(self):
        queries = [
            "Kiểm tra tình trạng sức khỏe toàn bộ máy chủ giúp anh",
            "Báo cáo tổng thể hệ thống server xem sao em",
            "Server dạo này sức khỏe thế nào có quá tải không",
        ]
        for q in queries:
            with self.subTest(query=q):
                tools = self.executor._resolve_scoped_tool_names(query=q)
                self.assertLessEqual(len(tools), 8, "Dynamic scoping exceeded 8-tool ceiling!")
                self.assertIn("get_system_health_report", tools)


if __name__ == "__main__":
    unittest.main()
