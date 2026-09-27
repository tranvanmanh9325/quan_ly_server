"""
tests/test_security_ai_tools.py
Milestone 3: Unit Tests for 6 Security AI Tools, Scoping, and Dispatching.

Tests cover:
- Tool Registry & JSON Schemas for 6 security tools.
- Action Risk Tri-Tier classification (Tier 1 vs Tier 2).
- Dynamic Tool Scoping & Regex Intent matching for security queries.
- Groq 8k TPM token budget invariant (len(tools) <= 8).
- Tool Execution Dispatching (get_security_report, list_blocked_ips, get_honeypot_log,
  get_attack_history, block_ip, unblock_ip).
- Whitelist VETO protection during manual or autonomous block attempts.
"""

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock

os.environ["TESTING"] = "true"

from app.services.ai_agent_tools import (
    ACTION_TIER_1_SAFE,
    ACTION_TIER_2_REVERSIBLE,
    AgentToolExecutor,
    classify_action_risk,
)


class TestSecurityAiTools(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mock_ssh = MagicMock()
        self.mock_cache = MagicMock()
        self.mock_sec_mon = MagicMock()
        self.mock_honeypot = MagicMock()

        self.executor = AgentToolExecutor(
            ssh_client=self.mock_ssh,
            message_cache=self.mock_cache,
            security_monitor_service=self.mock_sec_mon,
            honeypot_service=self.mock_honeypot,
        )

    def test_security_tools_registered_and_schemas_valid(self):
        """Verifies that all 6 security tools exist in full tool definitions with valid schemas."""
        tools = self.executor._build_tools()
        tool_names = {t["function"]["name"] for t in tools}

        expected_tools = {
            "get_security_report",
            "list_blocked_ips",
            "get_honeypot_log",
            "get_attack_history",
            "block_ip",
            "unblock_ip",
        }
        for name in expected_tools:
            self.assertIn(name, tool_names, f"Tool {name} must be registered in _build_tools()")

        # Verify specific parameter requirements
        block_tool = next(t for t in tools if t["function"]["name"] == "block_ip")
        self.assertIn("ip", block_tool["function"]["parameters"]["required"])
        self.assertIn("reason", block_tool["function"]["parameters"]["required"])

        unblock_tool = next(t for t in tools if t["function"]["name"] == "unblock_ip")
        self.assertIn("ip", unblock_tool["function"]["parameters"]["required"])

    def test_action_risk_tri_tier_classification(self):
        """Confirms that diagnostic tools are Tier 1 and firewall mutation tools are Tier 2."""
        self.assertEqual(classify_action_risk("get_security_report"), ACTION_TIER_1_SAFE)
        self.assertEqual(classify_action_risk("list_blocked_ips"), ACTION_TIER_1_SAFE)
        self.assertEqual(classify_action_risk("get_honeypot_log"), ACTION_TIER_1_SAFE)
        self.assertEqual(classify_action_risk("get_attack_history"), ACTION_TIER_1_SAFE)

        self.assertEqual(classify_action_risk("block_ip"), ACTION_TIER_2_REVERSIBLE)
        self.assertEqual(classify_action_risk("unblock_ip"), ACTION_TIER_2_REVERSIBLE)

    def test_dynamic_scoping_security_prompts(self):
        """Tests that natural language queries correctly activate the security cluster within token budget."""
        test_cases = [
            ("Báo cáo tình hình an ninh mạng của server hôm nay", "get_security_report"),
            ("Có ai đang tấn công máy chủ không em", "get_security_report"),
            ("Danh sách IP đang bị chặn", "list_blocked_ips"),
            ("Cho anh xem nhật ký bẫy honeypot", "get_honeypot_log"),
            ("Kẻ thất bại đã thử những mật khẩu nào", "get_honeypot_log"),
            ("Khóa IP 45.83.122.7 vì quét SSH", "block_ip"),
            ("Chặn ngay thằng hacker 185.220.101.5", "block_ip"),
            ("Mở khóa cho IP 45.83.122.7 giúp anh", "unblock_ip"),
            ("Gỡ chặn ip 14.162.12.33", "unblock_ip"),
            ("Lịch sử các vụ tấn công SQL injection gần đây", "get_attack_history"),
            ("Kiểm tra tường lửa iptables xem đang chặn ai", "list_blocked_ips"),
        ]

        for query, expected_tool in test_cases:
            scoped = self.executor._resolve_scoped_tool_names(query=query)
            self.assertIn(
                expected_tool,
                scoped,
                f"Query '{query}' expected to include tool '{expected_tool}', got {scoped}",
            )
            # Invariant: hard limit of at most 8 tools per turn to prevent Groq HTTP 413
            self.assertLessEqual(
                len(scoped),
                8,
                f"Scoped tool count exceeded 8 for query '{query}': {len(scoped)}",
            )

    async def test_dispatch_get_security_report(self):
        """Verifies dispatching get_security_report formats output with threat badge."""
        self.mock_sec_mon.get_security_report = AsyncMock(return_value={
            "current_threat_status": "ORANGE",
            "active_blocked_ips_count": 5,
            "attack_events_24h": {
                "total_events": 142,
                "by_type": {"ssh_brute_force": 100, "sqli": 42},
            },
            "top_attacking_ips": [
                {"ip": "45.83.122.7", "attack_count": 50, "is_blocked": True, "is_whitelisted": False}
            ],
            "system_protection": {"firewall_mode": "iptables", "uptime_seconds": 7200},
        })

        output = await self.executor._execute_tool("get_security_report", {})
        self.assertIn("BÁO CÁO TỔNG QUAN TÌNH TRẠNG AN NINH MÁY CHỦ", output)
        self.assertIn("ORANGE", output)
        self.assertIn("5 IP", output)
        self.assertIn("142 vụ", output)
        self.assertIn("ssh_brute_force", output)
        self.assertIn("45.83.122.7", output)

    async def test_dispatch_list_blocked_ips(self):
        """Verifies dispatching list_blocked_ips formats remaining TTL properly."""
        self.mock_sec_mon.list_blocked_ips = AsyncMock(return_value=[
            {
                "ip": "45.83.122.7",
                "threat_level": "HIGH",
                "reason": "SSH brute force detected",
                "blocked_at": "13:00:00 27/09/2026",
                "expires_at": "13:00:00 28/09/2026",
                "remaining_seconds": 82800,
            }
        ])

        output = await self.executor._execute_tool("list_blocked_ips", {})
        self.assertIn("DANH SÁCH 1 ĐỊA CHỈ IP ĐANG BỊ KHÓA TRÊN FIREWALL", output)
        self.assertIn("45.83.122.7", output)
        self.assertIn("SSH brute force detected", output)
        self.assertIn("23 giờ", output)

    async def test_dispatch_block_ip_success(self):
        """Verifies dispatching block_ip calls security_monitor and returns success message."""
        self.mock_sec_mon.block_ip = AsyncMock(return_value={
            "status": "success",
            "ip": "45.83.122.7",
            "expires_at": "13:00:00 28/09/2026",
        })

        output = await self.executor._execute_tool("block_ip", {
            "ip": "45.83.122.7",
            "reason": "Quét cổng liên tục",
            "duration_seconds": 86400,
        })
        self.assertIn("Đã khóa thành công IP `45.83.122.7`", output)
        self.assertIn("24 giờ", output)

    async def test_dispatch_block_ip_whitelist_veto(self):
        """Verifies that attempting to block a whitelisted IP triggers safety VETO."""
        self.mock_sec_mon.block_ip = AsyncMock(return_value={
            "status": "veto",
            "reason": "IP 127.0.0.1 is in Whitelist",
        })

        output = await self.executor._execute_tool("block_ip", {
            "ip": "127.0.0.1",
            "reason": "Test accidental block",
        })
        self.assertIn("VETO BẢO VỆ AN TOÀN", output)
        self.assertIn("Whitelist", output)

    async def test_dispatch_unblock_ip(self):
        """Verifies dispatching unblock_ip calls security_monitor and returns confirmation."""
        self.mock_sec_mon.unblock_ip = AsyncMock(return_value={
            "status": "success",
            "ip": "45.83.122.7",
        })

        output = await self.executor._execute_tool("unblock_ip", {"ip": "45.83.122.7"})
        self.assertIn("Đã gỡ bỏ thành công lệnh chặn đối với IP `45.83.122.7`", output)

    async def test_dispatch_get_honeypot_log(self):
        """Verifies dispatching get_honeypot_log extracts captures and probe stats."""
        self.mock_honeypot.get_honeypot_log = AsyncMock(return_value=[
            {
                "service": "ssh",
                "captured_at": "13:45:00 27/09/2026",
                "ip": "103.145.12.8",
                "username": "root",
                "password": "password123",
                "attempt_count": 1,
            }
        ])
        self.mock_honeypot.get_stats = MagicMock(return_value={
            "total_probes": 15,
            "total_credentials": 3,
            "unique_ips_count": 2,
        })

        output = await self.executor._execute_tool("get_honeypot_log", {"limit": 10})
        self.assertIn("BÁO CÁO BẪY HONEYPOT", output)
        self.assertIn("root", output)
        self.assertIn("password123", output)
        self.assertIn("103.145.12.8", output)


if __name__ == "__main__":
    unittest.main()
