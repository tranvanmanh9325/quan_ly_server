"""
test_challenger_m4_empirical.py — Milestone 4 Empirical Verification Suite.

Target: Autonomous Action Gating, Tool-First Imperative & Gorilla RAT Scoped Tools
Code Under Test:
  - services/ai-agent-service/app/services/ai_agent.py
  - services/ai-agent-service/app/services/ai_agent_tools.py

Test Objectives (Challenger M4 Verification):
1. Action Risk Tri-Tier Classification:
   - Tier 1: Safe Read-Only / Diagnostic / Utility
   - Tier 2: Reversible Changes / Low-Risk Operational
   - Tier 3: Lethal / Destructive (Spinal Veto Interlocked)
2. Tool-First Imperative & Anti-Deflection Constitutional Grounding:
   - Zero turn wasted on Tier 1 tasks
   - Prohibition against micro-permission requests
   - Prohibition against deflecting terminal commands to user
   - Default parameter heuristics for common diagnostic requests
3. Gorilla RAT Scoped Tools Token Budget:
   - All tool clusters strictly within 2 to 8 tools
   - Tool schema JSON token budget strictly <= 700 tokens across all intents
   - Word boundary regex isolation preventing substring false matches (zip != ip, download != load)
   - Priority Pruning capping combinatorial queries at max 8 tools
"""
import json
import re
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.ai_agent import AiAgentService
from app.services.ai_agent_tools import (
    AgentToolExecutor,
    ACTION_TIER_1_SAFE,
    ACTION_TIER_2_REVERSIBLE,
    ACTION_TIER_3_LETHAL,
    classify_action_risk,
    classify_command_risk,
    infer_default_diagnostic_command,
    evaluate_spinal_safety_veto,
)


class TestChallengerM4EmpiricalSuite(unittest.TestCase):
    """Milestone 4 Empirical Test Suite."""

    def setUp(self):
        self.mock_llm = MagicMock()
        self.mock_ssh = MagicMock()
        self.mock_cache = MagicMock()
        self.agent = AiAgentService(
            llm_router=self.mock_llm,
            ssh_client=self.mock_ssh,
            message_cache=self.mock_cache,
        )
        self.tools = AgentToolExecutor(ssh_client=self.mock_ssh, message_cache=self.mock_cache)

    # ──────────────────────────────────────────────────────────────────────────
    # 1. Action Risk Tri-Tier Classification Tests
    # ──────────────────────────────────────────────────────────────────────────

    def test_01_tier1_safe_diagnostic_commands(self):
        """Tier 1 safe diagnostic commands are accurately classified as TIER_1_SAFE."""
        safe_commands = [
            "free -h",
            "free -m",
            "df -h /",
            "uptime",
            "top -b -n 1 | head -n 15",
            "htop",
            "docker ps",
            "docker stats --no-stream",
            "docker logs dashboard_ai_agent --tail 20",
            "journalctl -u dashboard_ai_agent -n 30 --no-pager",
            "systemctl status postgresql",
            "cat /proc/meminfo",
            "cat /etc/os-release",
            "netstat -tuln",
            "ss -tulpn",
            "ip addr show",
            "uname -a",
            "whoami",
            "vmstat 1 3",
            "ls -la /home/kirito",
        ]
        for cmd in safe_commands:
            tier = classify_command_risk(cmd)
            self.assertEqual(
                tier, ACTION_TIER_1_SAFE,
                f"Command '{cmd}' must be classified as TIER_1_SAFE, got '{tier}'"
            )

    def test_02_tier2_reversible_commands(self):
        """Tier 2 reversible operational commands are classified as TIER_2_REVERSIBLE."""
        reversible_commands = [
            "docker restart dashboard_ai_agent",
            "docker start dashboard_db",
            "systemctl restart nginx",
            "systemctl reload nginx",
            "touch /tmp/test_marker",
            "mkdir -p /tmp/scratch_dir",
            "cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf_bak",
        ]
        for cmd in reversible_commands:
            tier = classify_command_risk(cmd)
            self.assertEqual(
                tier, ACTION_TIER_2_REVERSIBLE,
                f"Command '{cmd}' must be classified as TIER_2_REVERSIBLE, got '{tier}'"
            )

    def test_03_tier3_lethal_commands_vetoed(self):
        """Tier 3 lethal commands matching spinal safety veto are classified as TIER_3_LETHAL."""
        lethal_commands = [
            "rm -rf /",
            "rm -rf ~",
            "rm -rf *",
            "rm -rf .",
            "rm --recursive --force /",
            "mkfs.ext4 /dev/sda1",
            "dd if=/dev/zero of=/dev/sda",
            "DROP DATABASE quan_ly_server",
            "truncate table agent_memories",
            "docker system prune -a --volumes",
            "iptables -F",
            "ufw --force reset",
            "chmod -R 777 /",
            "stress --cpu 4",
            ":(){ :|:& };:",
        ]
        for cmd in lethal_commands:
            tier = classify_command_risk(cmd)
            self.assertEqual(
                tier, ACTION_TIER_3_LETHAL,
                f"Lethal command '{cmd}' must be classified as TIER_3_LETHAL, got '{tier}'"
            )
            # Must also trigger spinal veto
            veto = evaluate_spinal_safety_veto(cmd)
            self.assertIsNotNone(veto, f"Lethal command '{cmd}' must be blocked by spinal veto")

    def test_04_classify_action_risk_across_tools(self):
        """classify_action_risk properly categorizes all tool types into appropriate tiers."""
        # Tier 1 tools
        self.assertEqual(classify_action_risk("get_weather"), ACTION_TIER_1_SAFE)
        self.assertEqual(classify_action_risk("get_server_location"), ACTION_TIER_1_SAFE)
        self.assertEqual(classify_action_risk("download_media_video", {"url": "https://youtu.be/123"}), ACTION_TIER_1_SAFE)
        self.assertEqual(classify_action_risk("read_archive_file", {"file_path": "/tmp/a.zip"}), ACTION_TIER_1_SAFE)
        self.assertEqual(classify_action_risk("browser_search_google", {"query": "test"}), ACTION_TIER_1_SAFE)
        self.assertEqual(classify_action_risk("remember_for_later", {"task": "meeting"}), ACTION_TIER_1_SAFE)

        # Tier 2 tools
        self.assertEqual(classify_action_risk("extract_archive_file", {"file_path": "/tmp/a.zip"}), ACTION_TIER_2_REVERSIBLE)
        self.assertEqual(classify_action_risk("recover_archive_password", {"file_path": "/tmp/a.zip"}), ACTION_TIER_2_REVERSIBLE)
        self.assertEqual(classify_action_risk("facebook_send_reply", {"message": "hi"}), ACTION_TIER_2_REVERSIBLE)
        self.assertEqual(classify_action_risk("browser_click", {"selector": "#btn"}), ACTION_TIER_2_REVERSIBLE)
        self.assertEqual(classify_action_risk("browser_type", {"text": "hello"}), ACTION_TIER_2_REVERSIBLE)

        # Tier 3 via run_command
        self.assertEqual(
            classify_action_risk("run_command", {"command": "rm -rf /"}),
            ACTION_TIER_3_LETHAL
        )

    # ──────────────────────────────────────────────────────────────────────────
    # 2. Default Parameter Heuristics Tests
    # ──────────────────────────────────────────────────────────────────────────

    def test_05_default_parameter_heuristics_inference(self):
        """infer_default_diagnostic_command derives safe, optimal parameters for vague requests."""
        # RAM queries
        ram_cmd = infer_default_diagnostic_command("kiểm tra ram máy chủ giúp anh")
        self.assertEqual(ram_cmd, "free -h")

        # Disk queries
        disk_cmd = infer_default_diagnostic_command("xem dung lượng ổ đĩa")
        self.assertEqual(disk_cmd, "df -h /")

        # Docker queries
        docker_cmd = infer_default_diagnostic_command("kiểm tra docker xem có những container nào")
        self.assertIsNotNone(docker_cmd)
        self.assertIn("docker ps", docker_cmd)

        # CPU queries
        cpu_cmd = infer_default_diagnostic_command("kiểm tra cpu tải hệ thống")
        self.assertIsNotNone(cpu_cmd)
        self.assertIn("top", cpu_cmd)

        # Uptime queries
        uptime_cmd = infer_default_diagnostic_command("server này hoạt động bao lâu rồi")
        self.assertEqual(uptime_cmd, "uptime")

    # ──────────────────────────────────────────────────────────────────────────
    # 3. Constitutional AI & Tool-First Grounding Tests
    # ──────────────────────────────────────────────────────────────────────────

    def test_06_constitution_contains_tool_first_imperative(self):
        """System prompt (Constitution 9) contains explicit Tool-First and Anti-Deflection mandates."""
        system_prompt = self.agent._build_system_prompt()

        # Check Constitution 9 Header & Imperative
        self.assertIn("TOOL-FIRST IMPERATIVE", system_prompt)
        self.assertIn("ZERO TURN WASTED", system_prompt)
        self.assertIn("ANTI-DEFLECTION", system_prompt)

        # Check Action Risk Tri-Tier in prompt
        self.assertIn("Tier 1 (Safe Read-Only", system_prompt)
        self.assertIn("Tier 2 (Reversible", system_prompt)
        self.assertIn("Tier 3 (Lethal", system_prompt)

        # Check Anti-Permission and Anti-Deflection rules
        self.assertIn("CẤM TUYỆT ĐỐI xin phép vụn vặt", system_prompt)
        self.assertIn("CẤM TUYỆT ĐỐI đùn đẩy trách nhiệm", system_prompt)
        self.assertIn("Tự suy luận tham số mặc định an toàn", system_prompt)

        # Check Subconscious Action Calibration grounding
        self.assertIn("Action Calibration", system_prompt)
        self.assertIn("EXECUTE_TOOL", system_prompt)

    # ──────────────────────────────────────────────────────────────────────────
    # 4. Gorilla RAT Scoped Tools & Token Budget Tests
    # ──────────────────────────────────────────────────────────────────────────

    def test_07_word_boundary_isolation_prevents_false_positives(self):
        """Word boundary regex prevents substring false positive cluster activations."""
        # 'zip' should NOT trigger is_server via 'ip'
        zip_tools = self.tools._resolve_scoped_tool_names("giải nén file zip này")
        self.assertIn("read_archive_file", zip_tools)
        self.assertIn("extract_archive_file", zip_tools)
        # Should not include server-only screenshot or active sessions
        self.assertNotIn("get_server_active_sessions", zip_tools)
        self.assertNotIn("server_capture_screenshot", zip_tools)

        # 'download' should NOT trigger is_server via 'load'
        dl_tools = self.tools._resolve_scoped_tool_names("download clip tiktok https://tiktok.com/123")
        self.assertIn("download_media_video", dl_tools)
        self.assertNotIn("get_server_active_sessions", dl_tools)

    def test_08_scoped_tools_token_budget_strictly_under_700_tokens(self):
        """Tool schema JSON token budget is <= 700 tokens across all representative intents."""
        test_queries = [
            ("kiểm tra ram máy chủ", "server"),
            ("xem thời tiết hôm nay ra sao", "weather"),
            ("tải video tiktok này https://tiktok.com/123", "media"),
            ("giải nén tệp tin rar data.rar", "archive"),
            ("xem tin nhắn messenger facebook", "facebook"),
            ("tìm kiếm google thông tin ubuntu 26.04", "browser"),
            ("ghi nhớ ngày mai backup database lúc 9h", "task"),
            ("chào em buổi sáng", "core_fallback"),
        ]

        for query, intent in test_queries:
            tools = self.tools.build_tools(query=query)
            dumped_json = json.dumps(tools, ensure_ascii=False)
            # Conservative token calculation: 3.5 chars per token
            approx_tokens = len(dumped_json) / 3.5

            self.assertGreaterEqual(
                len(tools), 2,
                f"Query '{query}' ({intent}) must activate at least 2 tools, got {len(tools)}"
            )
            self.assertLessEqual(
                len(tools), 8,
                f"Query '{query}' ({intent}) must activate at most 8 tools, got {len(tools)}"
            )
            self.assertLessEqual(
                approx_tokens, 700.0,
                f"Query '{query}' ({intent}) tool schema tokens ({approx_tokens:.1f}) exceeds 700 tokens budget!"
            )

    def test_09_priority_pruning_caps_combinatorial_query_at_max_8_tools(self):
        """When multiple clusters are triggered simultaneously, Priority Pruning caps tools at <= 8."""
        combinatorial_query = (
            "kiểm tra server, ram, docker, xem thời tiết, tải video tiktok https://tiktok.com/v123 "
            "và xem tin nhắn facebook rồi nhớ lại mai làm"
        )
        scoped = self.tools._resolve_scoped_tool_names(combinatorial_query)
        self.assertLessEqual(
            len(scoped), 8,
            f"Combinatorial query must be pruned to max 8 tools, got {len(scoped)}: {scoped}"
        )
        # Priority tools must be preserved
        self.assertIn("run_command", scoped)
        self.assertIn("download_media_video", scoped)

    def test_10_ai_agent_service_delegates_action_tier_apis(self):
        """AiAgentService exposes and delegates Action Risk Tri-Tier constants and helpers."""
        self.assertEqual(self.agent.ACTION_TIER_1_SAFE, ACTION_TIER_1_SAFE)
        self.assertEqual(self.agent.ACTION_TIER_2_REVERSIBLE, ACTION_TIER_2_REVERSIBLE)
        self.assertEqual(self.agent.ACTION_TIER_3_LETHAL, ACTION_TIER_3_LETHAL)
        self.assertTrue(callable(self.agent.classify_action_risk))
        self.assertTrue(callable(self.agent.classify_command_risk))
        self.assertTrue(callable(self.agent.infer_default_diagnostic_command))


if __name__ == "__main__":
    unittest.main()
