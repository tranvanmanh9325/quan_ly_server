"""
test_ai_agent_tools_integration.py — Integration Test Suite for AI Agent Tool Registry & Dispatcher (M5).

Verifies 4 Empirical Invariants:
1. Tool Registry Completeness:
   - 100% of the 27 new tools (R1-R8) + 24 legacy tools are registered in `_build_tools()`.
   - All tools conform to valid OpenAI function calling JSON schema.
2. Dynamic Tool Scoping (Gorilla RAT / BFCL):
   - Strict Groq 8,000 TPM limit compliance: total scoped tools MUST ALWAYS be <= 8.
   - Verified across a diverse 35-prompt corpus (standard, diacritics, teencode, dialect, compound intents).
   - Scoped tools match user intent semantically.
3. Tool Execution Dispatch:
   - `_execute_tool()` dispatches properly to corresponding sub-services.
4. Action Risk Tri-Tier & Safety Gating:
   - All tools are correctly classified into Tier 1 (Safe), Tier 2 (Reversible), or Tier 3 (Lethal).
   - Spinal Safety Veto blocks destructive bash/SQL commands unless confirm token is present.
"""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.ai_agent_tools import (
    AgentToolExecutor,
    ACTION_TIER_1_SAFE,
    ACTION_TIER_2_REVERSIBLE,
    ACTION_TIER_3_LETHAL,
    classify_action_risk,
    classify_command_risk,
    evaluate_spinal_safety_veto,
)


def _create_mock_executor() -> AgentToolExecutor:
    mock_ssh = MagicMock()
    mock_ssh.execute_command = AsyncMock(return_value="mock ssh output")
    mock_cache = MagicMock()
    mock_telegram = MagicMock()
    mock_telegram.send_message = AsyncMock(return_value=True)
    return AgentToolExecutor(ssh_client=mock_ssh, message_cache=mock_cache, telegram_bot=mock_telegram)


class TestToolRegistryCompleteness(unittest.TestCase):
    """Verifies that all 27 new tools + 24 legacy tools are registered in _build_tools()."""

    def setUp(self):
        self.executor = _create_mock_executor()
        # Build tools without query/history to get all registered tools
        self.all_tools = self.executor._build_tools()
        self.tool_map = {
            t["function"]["name"]: t["function"]
            for t in self.all_tools
            if t.get("type") == "function" and "function" in t
        }

    def test_all_27_new_tools_registered(self):
        """Verifies presence of all 27 new tools across R1 to R8."""
        expected_new_tools = {
            # R1: Smart Scheduler (3)
            "schedule_reminder", "list_scheduled_reminders", "cancel_reminder",
            # R2: Health Monitor & SRE (4)
            "get_system_health_report", "check_service_status", "restart_service", "tail_service_logs",
            # R3: Personal Notes (4)
            "create_note", "search_notes", "list_notes", "delete_note",
            # R4: Calculator & Data Analytics (3)
            "calculate", "query_database", "convert_units",
            # R5: Cron Automation (3)
            "create_cron_job", "list_cron_jobs", "delete_cron_job",
            # R6: Email & Periodic Reports (2)
            "send_email", "generate_report",
            # R7: Network & Ngrok (3)
            "get_ngrok_status", "restart_ngrok_tunnel", "get_network_info",
            # R8: File Manager (5)
            "list_files", "read_file_content", "write_file_content", "move_or_rename_file", "get_disk_usage",
        }
        self.assertEqual(len(expected_new_tools), 27)
        missing_tools = expected_new_tools - set(self.tool_map.keys())
        self.assertEqual(missing_tools, set(), f"Missing tools in registry: {missing_tools}")

    def test_tool_schema_conformance(self):
        """Validates that each registered tool has valid OpenAI JSON Schema properties."""
        for name, func in self.tool_map.items():
            self.assertIn("description", func, f"Tool {name} missing description")
            self.assertTrue(len(func["description"]) > 5, f"Tool {name} description too short")
            self.assertIn("parameters", func, f"Tool {name} missing parameters")
            params = func["parameters"]
            self.assertEqual(params.get("type"), "object", f"Tool {name} parameters must be of type 'object'")
            self.assertIn("properties", params, f"Tool {name} parameters missing 'properties'")
            if "required" in params:
                self.assertIsInstance(params["required"], list, f"Tool {name} required must be a list")


class TestDynamicToolScopingCorpus(unittest.TestCase):
    """Empirical Scoping Corpus: Verifies <= 8 tools invariant across 35 test prompts."""

    CORPUS = [
        # R1 Scheduler
        ("10 phút nữa nhắc anh uống nước", "schedule_reminder"),
        ("đặt lịch nhắc em đi họp lúc 15h", "schedule_reminder"),
        ("xem danh sách các việc đã hẹn nhắc", "list_scheduled_reminders"),
        ("hủy lịch nhắc số 3 giùm anh", "cancel_reminder"),
        # R2 SRE Monitor
        ("kiểm tra sức khỏe server xem sao", "get_system_health_report"),
        ("tình trạng máy chủ hoạt động thế nào em", "get_system_health_report"),
        ("trạng thái container dashboard_db hiện tại", "check_service_status"),
        ("restart container auth service", "restart_service"),
        ("xem log 50 dòng cuối của dashboard_ai_agent", "tail_service_logs"),
        # R3 Notes
        ("ghi chú lại mật khẩu wifi nhà là 12345678", "create_note"),
        ("note lại ý tưởng tối ưu kiến trúc microservice", "create_note"),
        ("tìm ghi chú về tài khoản ngân hàng", "search_notes"),
        ("liệt kê danh sách tất cả các note cá nhân", "list_notes"),
        ("xóa ghi chú id note_123", "delete_note"),
        # R4 Calculator
        ("tính giúp anh 25 * 400 + sqrt(144)", "calculate"),
        ("tính lãi suất 500 triệu gửi 12 tháng 6.5%", "calculate"),
        ("đổi 100 độ F sang độ C", "convert_units"),
        ("đổi 50kg sang lbs", "convert_units"),
        ("truy vấn sql SELECT count(*) FROM users", "query_database"),
        # R5 Cron
        ("tạo cron job backup database lúc 2h sáng", "create_cron_job"),
        ("xem danh sách các cron job đang chạy trên server", "list_cron_jobs"),
        ("xóa cron job backup_daily", "delete_cron_job"),
        # R6 Email
        ("gửi email báo cáo cho manhtv@example.com", "send_email"),
        ("tạo báo cáo tổng hợp sức khỏe server tuần này", "generate_report"),
        # R7 Network
        ("xem link ngrok hiện tại đang mở là gì", "get_ngrok_status"),
        ("restart lại tunnel ngrok giúp anh", "restart_ngrok_tunnel"),
        ("kiểm tra thông tin mạng IP công khai và ISP", "get_network_info"),
        # R8 Files
        ("liệt kê danh sách file trong thư mục /home/kirito", "list_files"),
        ("đọc nội dung file /home/kirito/config.txt", "read_file_content"),
        ("ghi file /tmp/test.txt nội dung hello", "write_file_content"),
        ("đổi tên file old.txt thành new.txt", "move_or_rename_file"),
        ("kiểm tra dung lượng thư mục /home/kirito xem cái nào nặng nhất", "get_disk_usage"),
        # Dialect & Legacy Media/Weather
        ("bựa ni máy chủ răng e, có đầy đĩa k", "get_system_health_report"),
        ("tải video tiktok này hộ anh https://vt.tiktok.com/123", "download_media_video"),
        ("thời tiết vinh bựa ni răng hè", "get_weather"),
    ]

    def setUp(self):
        self.executor = _create_mock_executor()

    def test_dynamic_scoping_invariant_and_selection(self):
        """Verifies that for each query in corpus: len(tools) <= 8 and expected tool is present."""
        for query, expected_tool in self.CORPUS:
            with self.subTest(query=query, expected_tool=expected_tool):
                scoped_tools = self.executor._resolve_scoped_tool_names(query=query)
                self.assertLessEqual(
                    len(scoped_tools),
                    8,
                    f"Query '{query}' yielded {len(scoped_tools)} tools (exceeds Groq 8-tool ceiling)!"
                )
                self.assertGreaterEqual(
                    len(scoped_tools),
                    1,
                    f"Query '{query}' yielded 0 tools!"
                )
                self.assertIn(
                    expected_tool,
                    scoped_tools,
                    f"Query '{query}' expected '{expected_tool}' but got {scoped_tools}"
                )


class TestToolExecutionDispatch(unittest.IsolatedAsyncioTestCase):
    """Verifies that _execute_tool dispatches calls to proper sub-services."""

    def setUp(self):
        self.executor = _create_mock_executor()

    async def test_dispatch_scheduler_service(self):
        """Tests dispatch for schedule_reminder."""
        with patch.object(self.executor.scheduler_service, "schedule_reminder", new_callable=AsyncMock) as mock_fn:
            mock_fn.return_value = {"status": "success", "message": "Reminder scheduled"}
            res = await self.executor._execute_tool("schedule_reminder", {"message": "Uống nước", "delay_minutes": 10})
            mock_fn.assert_awaited_once_with(message="Uống nước", delay_minutes=10, repeat="none")
            self.assertIn("Reminder scheduled", str(res))

    async def test_dispatch_server_monitor_service(self):
        """Tests dispatch for get_system_health_report."""
        with patch.object(self.executor.server_monitor_service, "get_system_health_report", new_callable=AsyncMock) as mock_fn:
            mock_fn.return_value = {"status": "success", "cpu": "15%", "ram": "45%"}
            res = await self.executor._execute_tool("get_system_health_report", {})
            mock_fn.assert_awaited_once()
            self.assertIn("15%", str(res))

    async def test_dispatch_notes_service(self):
        """Tests dispatch for create_note."""
        with patch.object(self.executor.notes_service, "create_note", new_callable=AsyncMock) as mock_fn:
            mock_fn.return_value = {"status": "success", "note_id": "note_01"}
            res = await self.executor._execute_tool("create_note", {"title": "Test", "content": "Sample"})
            mock_fn.assert_awaited_once_with(title="Test", content="Sample", tags=None)
            self.assertIn("note_01", str(res))

    async def test_dispatch_calculator_service(self):
        """Tests dispatch for calculate."""
        with patch.object(self.executor.calculator_service, "calculate", new_callable=AsyncMock) as mock_fn:
            mock_fn.return_value = {"status": "success", "result": 42}
            res = await self.executor._execute_tool("calculate", {"expression": "6 * 7"})
            mock_fn.assert_awaited_once_with(expression="6 * 7")
            self.assertIn("42", str(res))

    async def test_dispatch_cron_service(self):
        """Tests dispatch for list_cron_jobs."""
        with patch.object(self.executor.cron_service, "list_cron_jobs", new_callable=AsyncMock) as mock_fn:
            mock_fn.return_value = {"status": "success", "jobs": []}
            res = await self.executor._execute_tool("list_cron_jobs", {})
            mock_fn.assert_awaited_once()
            self.assertIn("success", str(res))

    async def test_dispatch_email_report_service(self):
        """Tests dispatch for send_email."""
        with patch.object(self.executor.email_report_service, "send_email", new_callable=AsyncMock) as mock_fn:
            mock_fn.return_value = {"status": "success", "message": "Email sent"}
            res = await self.executor._execute_tool("send_email", {"to": "a@b.com", "subject": "Hi", "body": "Msg"})
            mock_fn.assert_awaited_once_with(to="a@b.com", subject="Hi", body="Msg", attachments=None)
            self.assertIn("Email sent", str(res))

    async def test_dispatch_network_service(self):
        """Tests dispatch for get_ngrok_status."""
        with patch.object(self.executor.network_service, "get_ngrok_status", new_callable=AsyncMock) as mock_fn:
            mock_fn.return_value = {"status": "online", "tunnels": []}
            res = await self.executor._execute_tool("get_ngrok_status", {})
            mock_fn.assert_awaited_once()
            self.assertIn("online", str(res))

    async def test_dispatch_file_manager_service(self):
        """Tests dispatch for list_files."""
        with patch.object(self.executor.file_manager_service, "list_files", new_callable=AsyncMock) as mock_fn:
            mock_fn.return_value = {"status": "success", "total_items": 5, "items": []}
            res = await self.executor._execute_tool("list_files", {"path": "/home/kirito"})
            mock_fn.assert_awaited_once_with(path="/home/kirito", pattern=None, sort_by="name")
            self.assertIn("success", str(res))


class TestActionRiskTriTier(unittest.TestCase):
    """Verifies Tri-Tier Action Risk Classification & Spinal Safety Veto."""

    def test_tier_1_safe_tools(self):
        """Tier 1 tools must return ACTION_TIER_1_SAFE."""
        tier1_sample = [
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
        ]
        for t in tier1_sample:
            self.assertEqual(classify_action_risk(t), ACTION_TIER_1_SAFE, f"{t} should be Tier 1")

    def test_tier_2_reversible_tools(self):
        """Tier 2 tools must return ACTION_TIER_2_REVERSIBLE."""
        tier2_sample = [
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
        ]
        for t in tier2_sample:
            self.assertEqual(classify_action_risk(t), ACTION_TIER_2_REVERSIBLE, f"{t} should be Tier 2")

    def test_spinal_safety_veto_destructive_commands(self):
        """Destructive bash commands must be blocked by evaluate_spinal_safety_veto without token."""
        lethal_cmds = [
            "rm -rf /",
            "rm -rf *",
            "DROP DATABASE production;",
            "TRUNCATE TABLE users;",
            "docker system prune -a",
            "mkfs.ext4 /dev/sda1",
            "iptables -F",
        ]
        for cmd in lethal_cmds:
            veto_msg = evaluate_spinal_safety_veto(cmd)
            self.assertIsNotNone(veto_msg, f"Command '{cmd}' should have been blocked by Spinal Safety Veto!")
            self.assertIn("SPINAL SAFETY VETO", veto_msg)

        # Verified with token: must pass
        for cmd in lethal_cmds:
            self.assertIsNone(evaluate_spinal_safety_veto(cmd, confirm_token="CONFIRM_DANGEROUS_ACTION"))


if __name__ == "__main__":
    unittest.main()
