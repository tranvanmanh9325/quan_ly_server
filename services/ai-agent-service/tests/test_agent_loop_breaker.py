import unittest
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Add app parent directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.ai_agent import AiAgentService
from app.core.llm_router import LlmRouter
from app.core.ssh_client import SshClient
from app.services.message_cache import FacebookMessageCache


class TestAgentLoopBreakerAndCompactor(unittest.TestCase):
    def setUp(self):
        self.router = LlmRouter()
        self.ssh = MagicMock(spec=SshClient)
        self.cache = MagicMock(spec=FacebookMessageCache)
        self.agent = AiAgentService(self.router, self.ssh, self.cache)

    def test_compact_messages_compresses_older_tool_outputs(self):
        history = [
            {"role": "user", "content": "Kiểm tra hệ thống"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "call_0"}]},
            {"role": "tool", "tool_call_id": "call_0", "content": "Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n" * 50},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1"}]},
            {"role": "tool", "tool_call_id": "call_1", "content": "Old Tool 2\n" * 40},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "call_2"}]},
            {"role": "tool", "tool_call_id": "call_2", "content": "Recent Tool 1\n" * 10},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "call_3"}]},
            {"role": "tool", "tool_call_id": "call_3", "content": "Recent Tool 2\n" * 10},
        ]

        compacted = self.agent._build_compact_messages_for_llm(history, iteration=3, force_synthesis=True)
        
        # Verify system prompt is at index 0
        self.assertEqual(compacted[0]["role"], "system")
        
        # Verify oldest tool outputs (call_0, call_1) are heavily compressed
        tool_messages = [m for m in compacted if m.get("role") == "tool"]
        self.assertEqual(len(tool_messages), 4)
        
        # Oldest tool output should be <= 350 chars
        self.assertLessEqual(len(tool_messages[0]["content"]), 350)
        self.assertIn("tóm tắt", tool_messages[0]["content"])

        # Synthesis directive should be injected at the end
        self.assertEqual(compacted[-1]["role"], "system")
        self.assertIn("HỆ THỐNG YÊU CẦU", compacted[-1]["content"])

    def test_synthesis_directive_injected_at_high_iteration(self):
        history = [{"role": "user", "content": "Test"}]
        compacted = self.agent._build_compact_messages_for_llm(history, iteration=4, force_synthesis=False)
        
        # Last message should be the synthesis directive
        self.assertEqual(compacted[-1]["role"], "system")
        self.assertIn("BLUF", compacted[-1]["content"])


if __name__ == "__main__":
    unittest.main()
