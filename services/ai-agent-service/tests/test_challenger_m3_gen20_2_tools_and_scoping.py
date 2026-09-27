"""
services/ai-agent-service/tests/test_challenger_m3_gen20_2_tools_and_scoping.py
Milestone 3 Empirical Adversarial Challenge Test Suite (Challenger 2).

Covers 3 Empirical Challenges:
1. Dynamic Tool Scoping & Groq Token Budget:
   - 20 diverse user queries (10 security vs 10 non-security).
   - Invariants: Security queries activate security tools, non-security queries contain ZERO security tools.
   - Invariants: Total tools <= 8 and schema tokens <= 700 tokens across all 20 queries.
2. Whitelist VETO via Tool Execution:
   - Calling execute_tool("block_ip") on 127.0.0.1, 192.168.1.1, ::ffff:127.0.0.1 (and extended whitelist).
   - Invariants: 100% safety VETO rejection, zero self-lockout of admin/local networks.
3. Clean Lifecycle & Resource Hygiene:
   - 10 consecutive start() / stop() cycles on SecurityAlertEngine.
   - Idempotent start/stop and concurrent drain on shutdown.
   - Invariants: 0 ResourceWarning for unclosed tasks, sockets, or transports.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
import sys
import time
import unittest
import warnings
from unittest.mock import AsyncMock, MagicMock

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

os.environ["TESTING"] = "true"

from app.services.ai_agent_tools import (
    ACTION_TIER_1_SAFE,
    ACTION_TIER_2_REVERSIBLE,
    AgentToolExecutor,
    classify_action_risk,
)
from app.services.security_monitor_service import SecurityMonitorService
from app.services.security_alert_engine import SecurityAlertEngine


@dataclass
class DummyThreatEvent:
    ip: str
    attack_type: str
    threat_level: str
    target_service: str
    raw_payload: str
    timestamp: float
    action_taken: str = "iptables_drop"


class TestMilestone3Challenger2ToolsAndScoping(unittest.IsolatedAsyncioTestCase):

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

        self.security_tools = {
            "get_security_report",
            "list_blocked_ips",
            "get_honeypot_log",
            "get_attack_history",
            "block_ip",
            "unblock_ip",
        }

    def test_dynamic_scoping_and_token_budget_20_queries(self):
        """
        Challenge 1: Evaluates Dynamic Tool Scoping & Groq Token Budget across 20 diverse queries.
        - 10 security queries must trigger security tools.
        - 10 non-security queries must NEVER contain any security tools.
        - Every single query must have len(tools) <= 8 and schema tokens <= 700.
        """
        security_queries = [
            "tình hình bảo mật server",
            "chặn IP 45.83.122.7",
            "xem honeypot bắt được ai",
            "gỡ chặn IP",
            "hôm nay có bị tấn công không",
            "có hacker nào quét cổng không em",
            "danh sách các IP đang bị khóa trên iptables",
            "báo cáo an ninh mạng máy chủ hôm nay thế nào",
            "kẻ thất bại đã nhập thông tin gì vào bẫy honeypot",
            "lịch sử các vụ tấn công SQL injection gần đây",
        ]

        non_security_queries = [
            "thời tiết Hà Nội",
            "tạo cuộc hẹn họp lúc 3h",
            "dịch bài viết này sang tiếng Anh",
            "hướng dẫn nấu phở bò",
            "tính giúp anh 1500 * 350 + 2000",
            "nhắc anh uống thuốc lúc 8h tối nhé",
            "gửi email báo cáo ngày cho sếp tranvanmanh@gmail.com",
            "liệt kê danh sách file trong thư mục /home/kirito",
            "tải video tiktok https://www.tiktok.com/@user/video/123456789",
            "tạo note ghi nhớ mua quà sinh nhật mẹ",
        ]

        # 1. Verify 10 Security Queries
        for q in security_queries:
            scoped_names = self.executor._resolve_scoped_tool_names(query=q)
            built_tools = self.executor._build_tools(query=q)
            tokens = len(json.dumps(built_tools, ensure_ascii=False)) / 3.5
            sec_in_built = {t["function"]["name"] for t in built_tools}.intersection(self.security_tools)

            self.assertGreater(
                len(sec_in_built),
                0,
                f"Security query '{q}' must contain at least one security tool in built_tools, got {sec_in_built}",
            )
            self.assertLessEqual(
                len(built_tools),
                8,
                f"Built tool count exceeded 8 for security query '{q}': {len(built_tools)}",
            )
            self.assertLessEqual(
                tokens,
                700.0,
                f"Token budget exceeded 700 for security query '{q}': {tokens:.1f}",
            )

        # 2. Verify 10 Non-Security Queries
        for q in non_security_queries:
            scoped_names = self.executor._resolve_scoped_tool_names(query=q)
            built_tools = self.executor._build_tools(query=q)
            tokens = len(json.dumps(built_tools, ensure_ascii=False)) / 3.5
            sec_in_built = {t["function"]["name"] for t in built_tools}.intersection(self.security_tools)

            self.assertEqual(
                len(sec_in_built),
                0,
                f"Non-security query '{q}' must NOT contain any security tools, found: {sec_in_built}",
            )
            self.assertLessEqual(
                len(built_tools),
                8,
                f"Built tool count exceeded 8 for non-security query '{q}': {len(built_tools)}",
            )
            self.assertLessEqual(
                tokens,
                700.0,
                f"Token budget exceeded 700 for non-security query '{q}': {tokens:.1f}",
            )

    async def test_whitelist_veto_tool_execution(self):
        """
        Challenge 2: Whitelist VETO protection during AgentToolExecutor.execute_tool("block_ip").
        - Verifies 127.0.0.1, 192.168.1.1, ::ffff:127.0.0.1 are 100% VETOED.
        - Verifies extended private/Cloudflare IPs are safely protected against lockout.
        """
        real_sec_svc = SecurityMonitorService.get_instance(ssh_client=self.mock_ssh)
        self.executor.set_security_monitor_service(real_sec_svc)

        mandatory_ips = [
            "127.0.0.1",
            "192.168.1.1",
            "::ffff:127.0.0.1",
        ]

        for ip in mandatory_ips:
            res = await self.executor.execute_tool("block_ip", {"ip": ip, "reason": "empirical_challenge_test"})
            self.assertIn("VETO", res, f"Expected VETO for IP {ip}, got: {res}")
            self.assertIn("Whitelist", res, f"Expected Whitelist mention for IP {ip}, got: {res}")
            self.assertNotIn("Đã khóa thành công", res, f"Accidentally blocked whitelisted IP {ip}!")

        # Extended Whitelist edge cases
        extended_ips = [
            "::1",
            "10.0.0.1",
            "172.16.0.5",
            "169.254.0.1",
            "104.16.1.1",  # Cloudflare IPv4
            "::ffff:192.168.1.1",  # IPv4-mapped IPv6 LAN
        ]
        for ip in extended_ips:
            res = await self.executor.execute_tool("block_ip", {"ip": ip, "reason": "extended_veto_test"})
            self.assertIn("VETO", res, f"Expected VETO for extended IP {ip}, got: {res}")

    async def test_clean_lifecycle_10_cycles_zero_resource_warning(self):
        """
        Challenge 3: Clean Lifecycle stress test on SecurityAlertEngine.
        - 10 consecutive start() / stop() cycles.
        - Strict ResourceWarning check ensuring 0 unclosed tasks or clients.
        """
        warnings.simplefilter("error", ResourceWarning)
        SecurityAlertEngine.reset_instance()

        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock(return_value=True)
        mock_bot.chat_id = "12345678"

        engine = SecurityAlertEngine(
            telegram_bot=mock_bot,
            digest_window_seconds=1.0,
            flush_interval_seconds=0.05,
            token="test-token",
            chat_id="12345678",
        )

        try:
            for cycle in range(10):
                await engine.start()
                self.assertTrue(engine._running, f"Engine should be running on cycle {cycle + 1}")
                self.assertIsNotNone(engine._flush_task, f"Flush task should exist on cycle {cycle + 1}")

                # Let task yield
                await asyncio.sleep(0.01)

                await engine.stop()
                self.assertFalse(engine._running, f"Engine should be stopped on cycle {cycle + 1}")
                self.assertIsNone(engine._flush_task, f"Flush task should be None on cycle {cycle + 1}")

            # Idempotence verification
            await engine.start()
            await engine.start()  # consecutive start
            self.assertTrue(engine._running)
            await engine.stop()
            await engine.stop()   # consecutive stop
            self.assertFalse(engine._running)

        finally:
            await engine.stop()
            SecurityAlertEngine.reset_instance()
            warnings.resetwarnings()

    async def test_lifecycle_shutdown_with_pending_digests(self):
        """
        Verifies that stop() cleanly drains pending digests without crashing or leaving tasks.
        """
        warnings.simplefilter("error", ResourceWarning)
        SecurityAlertEngine.reset_instance()

        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock(return_value=True)
        mock_bot.chat_id = "12345678"

        engine = SecurityAlertEngine(
            telegram_bot=mock_bot,
            digest_window_seconds=10.0,
            flush_interval_seconds=0.1,
            token="test-token",
            chat_id="12345678",
        )

        try:
            await engine.start()
            # Enqueue multiple events
            for i in range(10):
                ev = DummyThreatEvent(
                    ip=f"198.51.100.{i % 3}",
                    attack_type="ssh_brute_force",
                    threat_level="HIGH",
                    target_service="ssh",
                    raw_payload=f"fail_{i}",
                    timestamp=time.time(),
                    action_taken="iptables_drop",
                )
                await engine.enqueue_threat_event(ev)

            # Stop while pending digests exist
            await engine.stop()
            self.assertFalse(engine._running)
            self.assertIsNone(engine._flush_task)
            self.assertEqual(len(engine._pending_digests), 0, "All pending digests should be drained on stop()")

        finally:
            await engine.stop()
            SecurityAlertEngine.reset_instance()
            warnings.resetwarnings()


if __name__ == "__main__":
    unittest.main()
