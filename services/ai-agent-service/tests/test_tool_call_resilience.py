import json
import unittest
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Add app parent directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.llm_router import LlmRouter
from app.core.ssh_client import SshClient
from app.services.ai_agent import AiAgentService
from app.services.message_cache import FacebookMessageCache


class TestToolCallResilience(unittest.TestCase):
    def setUp(self):
        self.router = LlmRouter()
        self.ssh = MagicMock(spec=SshClient)
        self.cache = MagicMock(spec=FacebookMessageCache)
        self.agent = AiAgentService(self.router, self.ssh, self.cache)

    def test_rehydrate_standard_json_tool_call(self):
        """Verify rehydration of exact error payload from Groq failed_generation."""
        raw_error = '{"name": "run_command", "arguments": {"command":"journalctl --since \\"2026-09-09 06:00\\" -p warning -n 20"}}'
        tool_calls = LlmRouter._rehydrate_failed_tool_call(raw_error)
        self.assertIsNotNone(tool_calls)
        self.assertEqual(len(tool_calls), 1)
        self.assertEqual(tool_calls[0]["function"]["name"], "run_command")
        args = json.loads(tool_calls[0]["function"]["arguments"])
        self.assertIn("journalctl", args["command"])

    def test_rehydrate_markdown_fenced_json(self):
        raw_error = "```json\n{\"name\": \"server_capture_screenshot\", \"arguments\": {}}\n```"
        tool_calls = LlmRouter._rehydrate_failed_tool_call(raw_error)
        self.assertIsNotNone(tool_calls)
        self.assertEqual(len(tool_calls), 1)
        self.assertEqual(tool_calls[0]["function"]["name"], "server_capture_screenshot")

    def test_rehydrate_openai_format(self):
        raw_error = '{"type": "function", "function": {"name": "run_command", "arguments": "{\\"command\\": \\"uptime\\"}"}}'
        tool_calls = LlmRouter._rehydrate_failed_tool_call(raw_error)
        self.assertIsNotNone(tool_calls)
        self.assertEqual(tool_calls[0]["function"]["name"], "run_command")
        self.assertIn("uptime", tool_calls[0]["function"]["arguments"])

    def test_rehydrate_pseudo_xml(self):
        raw_error = '<function=run_command>{"command": "free -m"}</function>'
        tool_calls = LlmRouter._rehydrate_failed_tool_call(raw_error)
        self.assertIsNotNone(tool_calls)
        self.assertEqual(tool_calls[0]["function"]["name"], "run_command")
        args = json.loads(tool_calls[0]["function"]["arguments"])
        self.assertEqual(args["command"], "free -m")

    def test_rehydrate_normal_text_returns_none(self):
        raw_text = "Chào anh Mạnh! Em là Tiểu Bảo Bảo, trợ lý của anh."
        tool_calls = LlmRouter._rehydrate_failed_tool_call(raw_text)
        self.assertIsNone(tool_calls)

    def test_agent_extract_pseudo_tool_calls_json(self):
        raw = '{"name": "run_command", "arguments": {"command": "docker ps"}}'
        calls = self.agent._extract_pseudo_tool_calls(raw)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "run_command")
        self.assertEqual(calls[0]["args"]["command"], "docker ps")

    def test_is_raw_tool_leak_detection(self):
        leak_json = '{"name": "run_command", "arguments": {"command": "date"}}'
        leak_xml = '<function=date>{}</function>'
        leak_md = '```json\n{"name": "date"}\n```'
        clean_text = "Dạ máy chủ hiện đang chạy bình thường, CPU 2% và RAM còn trống 1.4 GiB ạ."

        self.assertTrue(AiAgentService._is_raw_tool_leak(leak_json))
        self.assertTrue(AiAgentService._is_raw_tool_leak(leak_xml))
        self.assertTrue(AiAgentService._is_raw_tool_leak(leak_md))
        self.assertFalse(AiAgentService._is_raw_tool_leak(clean_text))

    def test_run_command_failure_false_positive_immunity(self):
        """
        Verify that system log output with words 'not found' or 'failed' is NOT
        treated as a tool execution failure.
        """
        normal_journalctl_output = (
            'Sep 09 12:51:18 kirito-server networkctl[880311]: Interface "vethc38c968" not found.\n'
            'Sep 09 13:40:42 kirito-server networkctl[922780]: Failed to issue io.systemd.Network.GetLLDPNeighbors() varlink call'
        )
        
        # Test helper logic matching lines in ai_agent.py
        fn_name = "run_command"
        tool_result = normal_journalctl_output
        
        _SHELL_ERROR_STARTS = (
            "error:", "lỗi:", "blocked:", "không thể kết nối",
            "bash:", "sh:", "zsh:", "timeout:", "failed to parse",
        )
        _SHELL_ERROR_CONTAINS = (
            "command not found", "no such file or directory",
            "permission denied", "syntax error", "invalid option",
            "failed to parse timestamp",
        )
        res_lower = tool_result.lower().strip()
        is_tool_failure = (
            any(res_lower.startswith(s) for s in _SHELL_ERROR_STARTS)
            or any(s in res_lower for s in _SHELL_ERROR_CONTAINS)
        )
        
        # Must be FALSE: reading system logs that have 'failed'/'not found' is not an execution failure
        self.assertFalse(is_tool_failure)

        # Real failure cases:
        bad_timestamp = "Failed to parse timestamp: today 06:00"
        res_bad = bad_timestamp.lower().strip()
        is_bad_failure = (
            any(res_bad.startswith(s) for s in _SHELL_ERROR_STARTS)
            or any(s in res_bad for s in _SHELL_ERROR_CONTAINS)
        )
        self.assertTrue(is_bad_failure)

        not_found_cmd = "bash: journalctlll: command not found"
        res_cmd = not_found_cmd.lower().strip()
        is_cmd_failure = (
            any(res_cmd.startswith(s) for s in _SHELL_ERROR_STARTS)
            or any(s in res_cmd for s in _SHELL_ERROR_CONTAINS)
        )
        self.assertTrue(is_cmd_failure)

    def test_strip_cot_leakage_preserves_clean_vietnamese_content(self):
        """Verify that clean normal responses from LLM are never converted to None or empty."""
        clean_text = "Chào anh Mạnh! Em là Tiểu Bảo Bảo, sáng nay hệ thống hoạt động bình thường ạ."
        result = self.router._strip_cot_leakage(clean_text)
        self.assertEqual(result, clean_text)

    def test_strip_cot_leakage_strips_thinking_process_preamble(self):
        """Verify that leaked chain of thought with separator is stripped properly."""
        cot_text = (
            "Here's a thinking process:\n"
            "1. Analyze the user request\n"
            "2. Formulate response\n"
            "---\n"
            "Chào anh Mạnh! Hệ thống đang chạy ổn định."
        )
        result = self.router._strip_cot_leakage(cot_text)
        self.assertEqual(result, "Chào anh Mạnh! Hệ thống đang chạy ổn định.")


if __name__ == "__main__":
    unittest.main()
