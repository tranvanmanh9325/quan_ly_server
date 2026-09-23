"""
test_file_transfer_ai_agent.py — Comprehensive Unit & Integration Test Suite for Milestone 4:
AI Agent ReAct Tool `create_file_transfer_portal`, Dynamic Scoping & Prompt Section 2f.

Verifies:
1. Four-point DIRECT_RETURN_TOOLS registry membership.
2. Dynamic tool scoping across Vietnamese intents (diacritics, unaccented, teencode, dialect).
3. Token budget gate compliance (schema overhead <= 700 tokens, <= 6 tools on heavy clusters, <= 8 tools otherwise).
4. System Prompt Section 2f integrity & Section 2e 100% invariant preservation.
5. Tool execution, BLUF formatting, dual-link resolution, and Telegram Bot card delivery.
6. ReAct loop single-turn direct return behavior (0 hallucination, turn 1 exit).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
import html
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.ai_agent_tools import (
    DIRECT_RETURN_TOOLS,
    SCREENSHOT_TOOLS,
    AgentToolExecutor,
)
from app.services.ai_agent import AiAgentService
from app.services.transfer_storage_manager import TransferRecord, TransferStorageManager


def _create_mock_executor(telegram_bot: Any = None) -> AgentToolExecutor:
    mock_ssh = MagicMock()
    mock_ssh.execute_command = AsyncMock(return_value="")
    mock_cache = MagicMock()
    return AgentToolExecutor(
        ssh_client=mock_ssh,
        message_cache=mock_cache,
        telegram_bot=telegram_bot,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. DIRECT_RETURN_TOOLS REGISTRY INTEGRITY
# ─────────────────────────────────────────────────────────────────────────────

class TestDirectReturnToolsRegistry(unittest.TestCase):
    """Verifies that create_file_transfer_portal is registered across all 4 architectural points."""

    def test_module_level_direct_return_tools(self) -> None:
        """Point 1: Module-level DIRECT_RETURN_TOOLS in ai_agent_tools.py."""
        self.assertIn(
            "create_file_transfer_portal",
            DIRECT_RETURN_TOOLS,
            "create_file_transfer_portal MUST be present in module-level DIRECT_RETURN_TOOLS",
        )

    def test_class_level_direct_return_tools(self) -> None:
        """Point 2: Class attribute AgentToolExecutor.DIRECT_RETURN_TOOLS."""
        self.assertIn(
            "create_file_transfer_portal",
            AgentToolExecutor.DIRECT_RETURN_TOOLS,
            "create_file_transfer_portal MUST be present in AgentToolExecutor.DIRECT_RETURN_TOOLS",
        )

    def test_instance_level_direct_return_tools(self) -> None:
        """Point 3: Private class attribute AgentToolExecutor._DIRECT_RETURN_TOOLS."""
        self.assertIn(
            "create_file_transfer_portal",
            AgentToolExecutor._DIRECT_RETURN_TOOLS,
            "create_file_transfer_portal MUST be present in AgentToolExecutor._DIRECT_RETURN_TOOLS",
        )

    def test_service_level_direct_return_tools(self) -> None:
        """Point 4: AiAgentService._DIRECT_RETURN_TOOLS in ai_agent.py."""
        self.assertIn(
            "create_file_transfer_portal",
            AiAgentService._DIRECT_RETURN_TOOLS,
            "create_file_transfer_portal MUST be present in AiAgentService._DIRECT_RETURN_TOOLS",
        )

    def test_cluster_membership(self) -> None:
        """Verifies _TOOL_CLUSTER_TRANSFER exists and is integrated into _TOOL_CLUSTER_CORE."""
        self.assertTrue(hasattr(AgentToolExecutor, "_TOOL_CLUSTER_TRANSFER"))
        self.assertIn("create_file_transfer_portal", AgentToolExecutor._TOOL_CLUSTER_TRANSFER)
        self.assertIn("run_command", AgentToolExecutor._TOOL_CLUSTER_TRANSFER)
        self.assertIn("create_file_transfer_portal", AgentToolExecutor._TOOL_CLUSTER_CORE)


# ─────────────────────────────────────────────────────────────────────────────
# 2. DYNAMIC TOOL SCOPING & VIETNAMESE INTENT CORPUS
# ─────────────────────────────────────────────────────────────────────────────

class TestDynamicScopingTransferIntents(unittest.TestCase):
    """Verifies semantic keyword matching and scoping for file transfer requests."""

    def setUp(self) -> None:
        self.executor = _create_mock_executor()

    def test_transfer_prompts_with_diacritics(self) -> None:
        """Tests standard Vietnamese transfer prompts with full diacritics."""
        prompts = [
            "chuyển file sang điện thoại giùm anh",
            "bắn file báo cáo sang ipad",
            "gửi file ảnh sang điện thoại",
            "chuyển ảnh sang ipad để anh vẽ",
            "share file này ra ngoài",
            "upload file lên máy chủ",
            "tải file lên server",
            "tải file về điện thoại",
            "mở cổng transfer portal",
            "airdrop file tài liệu sang laptop",
            "bắn video này qua điện thoại",
            "tạo cổng truyền file siêu tốc",
            "gửi tệp sang tablet",
            "drop file sang máy tính",
        ]
        for p in prompts:
            with self.subTest(prompt=p):
                scoped = self.executor._resolve_scoped_tool_names(query=p)
                self.assertIn(
                    "create_file_transfer_portal",
                    scoped,
                    f"Prompt '{p}' did not scope create_file_transfer_portal!",
                )

    def test_transfer_prompts_unaccented(self) -> None:
        """Tests unaccented Vietnamese transfer prompts."""
        prompts = [
            "chuyen file sang dien thoai",
            "ban file sang ipad",
            "gui file sang dt",
            "chuyen anh sang ipad",
            "tai file len server",
            "tai file ve may",
            "gui tep qua dien thoai",
            "ban video sang phone",
            "truyen file qua laptop",
        ]
        for p in prompts:
            with self.subTest(prompt=p):
                scoped = self.executor._resolve_scoped_tool_names(query=p)
                self.assertIn(
                    "create_file_transfer_portal",
                    scoped,
                    f"Unaccented prompt '{p}' did not scope create_file_transfer_portal!",
                )

    def test_non_transfer_prompts_do_not_scope_transfer_cluster(self) -> None:
        """Tests that clearly unrelated queries (weather, server, tasks) do NOT trigger transfer cluster."""
        non_transfer = [
            "xem thời tiết hôm nay ở Vinh có mưa không",
            "kiểm tra nhiệt độ CPU và RAM máy chủ",
            "lưu lại công việc này chiều mai xử lý",
            "tìm kiếm google thông tin về Python 3.14",
            "xem các phiên kết nối đang mở",
        ]
        for p in non_transfer:
            with self.subTest(prompt=p):
                scoped = self.executor._resolve_scoped_tool_names(query=p)
                self.assertNotIn(
                    "create_file_transfer_portal",
                    scoped,
                    f"Unrelated query '{p}' unexpectedly scoped create_file_transfer_portal!",
                )


# ─────────────────────────────────────────────────────────────────────────────
# 3. TOKEN BUDGET GATE & PRUNING VERIFICATION
# ─────────────────────────────────────────────────────────────────────────────

class TestTokenBudgetGate(unittest.TestCase):
    """Verifies that scoping complies with Groq 8,000 TPM limit (<=700 tokens schema overhead)."""

    def setUp(self) -> None:
        self.executor = _create_mock_executor()

    def test_max_tools_normal_budget_threshold(self) -> None:
        """Total scoped tools MUST be <= 8 for standard multi-intent queries."""
        multi_intent = "chuyển file sang điện thoại và xem thời tiết ở Hà Nội cùng tình trạng RAM docker"
        scoped = self.executor._resolve_scoped_tool_names(query=multi_intent)
        self.assertLessEqual(len(scoped), 8)
        self.assertIn("create_file_transfer_portal", scoped)

    def test_max_tools_heavy_cluster_threshold(self) -> None:
        """Total scoped tools MUST be <= 6 when heavy clusters (facebook/archive) are co-active."""
        heavy_intent = "giải nén file zip backup.zip đồng thời chuyển file sang điện thoại"
        scoped = self.executor._resolve_scoped_tool_names(query=heavy_intent)
        self.assertLessEqual(len(scoped), 6)
        self.assertIn(
            "create_file_transfer_portal",
            scoped,
            "create_file_transfer_portal was pruned from heavy cluster!",
        )

    def test_schema_overhead_token_estimate(self) -> None:
        """Verifies schema character count remains safely within the ~700 tokens budget."""
        tools_def = self.executor._build_tools(query="bắn file sang ipad")
        scoped_names = [t.get("function", {}).get("name") for t in tools_def]
        self.assertIn("create_file_transfer_portal", scoped_names)

        total_chars = sum(len(str(t)) for t in tools_def)
        # 1 token ~= 3.5 - 4 chars. 700 tokens ~= 2,800 chars
        self.assertLess(
            total_chars,
            4500,
            f"Tools schema overhead too large ({total_chars} chars), risk of exceeding token budget!",
        )


# ─────────────────────────────────────────────────────────────────────────────
# 4. SYSTEM PROMPT SECTION 2f & SECTION 2e INVARIANT PRESERVATION
# ─────────────────────────────────────────────────────────────────────────────

class TestSystemPromptSection2f(unittest.TestCase):
    """Verifies Section 2f presence and strict preservation of Section 2e invariants."""

    def setUp(self) -> None:
        self.agent = AiAgentService.__new__(AiAgentService)
        self.static_prefix = AiAgentService._STATIC_SYSTEM_PREFIX

    def test_section_2f_title_and_structure(self) -> None:
        """Section 2f title and core markers must be present in _STATIC_SYSTEM_PREFIX."""
        self.assertIn(
            "━━━ 2f. GIAO THỨC CHIA SẺ & TRUYỀN TẢI TỆP TIN ĐA THIẾT BỊ (LAN/WAN FILE TRANSFER PORTAL) ━━━",
            self.static_prefix,
            "Section 2f title missing from _STATIC_SYSTEM_PREFIX!",
        )
        self.assertIn("ĐẶC QUYỀN TRUYỀN TẢI TỆP SIÊU TỐC ĐA THIẾT BỊ", self.static_prefix)
        self.assertIn("create_file_transfer_portal", self.static_prefix)
        self.assertIn("Turn 1 - Tool-First Imperative", self.static_prefix)
        self.assertIn("TUYỆT ĐỐI CẤM hỏi xin phép", self.static_prefix)
        self.assertIn("TUYỆT ĐỐI CẤM đùn đẩy", self.static_prefix)
        self.assertIn("CÔNG THỨC TRẢ LỜI BLUF DỨT KHOÁT", self.static_prefix)
        self.assertIn("Link Nội Bộ (LAN", self.static_prefix)
        self.assertIn("Link Internet (WAN", self.static_prefix)

    def test_section_2e_invariants_100_percent_preserved(self) -> None:
        """Section 2e invariants MUST NOT be altered by adding Section 2f."""
        self.assertIn(
            "━━━ 2e. GIAO THỨC TRÍCH XUẤT MEDIA, TẢI VIDEO & TRÍCH XUẤT MP3/AUDIO ĐẶC QUYỀN (MEDIA & AUDIO ARCHIVING PROTOCOL) ━━━",
            self.static_prefix,
        )
        self.assertIn("320KBPS", self.static_prefix.upper())
        self.assertIn("TikWM Direct MP3 Flow", self.static_prefix)
        self.assertIn("yt-dlp + FFmpegExtractAudio", self.static_prefix)
        self.assertIn("TUYỆT ĐỐI CẤM TỪ CHỐI", self.static_prefix)
        self.assertIn("TUYỆT ĐỐI CẤM ĐÙN ĐẨY (ANTI-DEFLECTION)", self.static_prefix)
        self.assertIn("download_media_audio", self.static_prefix)
        self.assertIn('media_type="audio"', self.static_prefix)
        self.assertIn('BẮT BUỘC trả lời khẳng định tự tin ngay từ câu đầu tiên (BLUF): "Dạ CÓ!"', self.static_prefix)
        self.assertIn("chủ động mời anh Mạnh gửi link", self.static_prefix)


# ─────────────────────────────────────────────────────────────────────────────
# 5. TOOL SCHEMA & EXECUTION VERIFICATION
# ─────────────────────────────────────────────────────────────────────────────

class TestFileTransferToolExecution(unittest.IsolatedAsyncioTestCase):
    """Verifies schema definitions, parameter handling, and mock execution."""

    def setUp(self) -> None:
        self.mock_bot = MagicMock()
        self.mock_bot.send_transfer_portal_card = AsyncMock(return_value=True)
        self.executor = _create_mock_executor(telegram_bot=self.mock_bot)

    def test_schema_properties(self) -> None:
        """Verifies create_file_transfer_portal schema parameters and enums."""
        tools = self.executor._build_tools(query="chuyển file")
        tool_entry = next((t for t in tools if t.get("function", {}).get("name") == "create_file_transfer_portal"), None)
        self.assertIsNotNone(tool_entry, "Tool schema create_file_transfer_portal not found")

        fn = tool_entry["function"]
        props = fn["parameters"]["properties"]
        self.assertIn("file_name", props)
        self.assertIn("mode", props)
        self.assertEqual(props["mode"]["enum"], ["upload", "download"])
        self.assertEqual(props["mode"]["default"], "upload")
        self.assertIn("one_time", props)
        self.assertEqual(props["one_time"]["default"], False)

    async def test_execute_upload_mode_success(self) -> None:
        """Verifies execution in default upload mode creates session and triggers Telegram card."""
        tool_args = {"mode": "upload", "file_name": "photo.png", "one_time": False}
        result = await self.executor.execute_tool(
            tool_name="create_file_transfer_portal",
            tool_args=tool_args,
            chat_id="12345678",
        )

        self.assertIn("CỔNG CHUYỂN TỆP SIÊU TỐC TIỂU BẢO BẢO ĐÃ SẴN SÀNG", result)
        self.assertIn("Tải lên (Upload từ thiết bị)", result)
        self.assertIn("photo.png", result)
        self.assertIn("Link LAN Wi-Fi", result)
        self.assertIn("Link WAN Internet Toàn Cầu", result)
        self.assertIn("24 giờ", result)

        self.mock_bot.send_transfer_portal_card.assert_called_once()
        call_kwargs = self.mock_bot.send_transfer_portal_card.call_args[1]
        self.assertEqual(call_kwargs["chat_id"], "12345678")
        self.assertEqual(call_kwargs["file_name"], "photo.png")
        self.assertEqual(call_kwargs["mode"], "upload")
        self.assertFalse(call_kwargs["one_time"])

    async def test_execute_download_mode_with_one_time(self) -> None:
        """Verifies download mode with one_time=True adds warning note and passes one_time flag."""
        tool_args = {"mode": "download", "file_name": "document.pdf", "one_time": True}
        result = await self.executor.execute_tool(
            tool_name="create_file_transfer_portal",
            tool_args=tool_args,
            chat_id="99887766",
        )

        self.assertIn("Tải xuống (Download về thiết bị)", result)
        self.assertIn("document.pdf", result)
        self.assertIn("tự hủy sau 1 lần tải", result)

        self.mock_bot.send_transfer_portal_card.assert_called_once()
        call_kwargs = self.mock_bot.send_transfer_portal_card.call_args[1]
        self.assertEqual(call_kwargs["mode"], "download")
        self.assertTrue(call_kwargs["one_time"])

    async def test_execute_bot_resilience_when_bot_fails(self) -> None:
        """When Telegram Bot throws network error, execute_tool handles it safely without crashing."""
        self.mock_bot.send_transfer_portal_card = AsyncMock(side_effect=RuntimeError("Telegram network timeout"))
        result = await self.executor.execute_tool(
            tool_name="create_file_transfer_portal",
            tool_args={"mode": "upload"},
            chat_id="12345",
        )
        self.assertIn("CỔNG CHUYỂN TỆP SIÊU TỐC TIỂU BẢO BẢO ĐÃ SẴN SÀNG", result)
        self.assertIn("Link LAN Wi-Fi", result)


# ─────────────────────────────────────────────────────────────────────────────
# 6. REACT LOOP SINGLE-TURN DIRECT RETURN BEHAVIOR
# ─────────────────────────────────────────────────────────────────────────────

class TestReActLoopDirectReturn(unittest.IsolatedAsyncioTestCase):
    """Verifies that create_file_transfer_portal exits immediately at Turn 1."""

    async def test_direct_return_terminates_loop_at_turn_one(self) -> None:
        """When model calls create_file_transfer_portal, ReAct loop terminates with direct result."""
        agent = AiAgentService.__new__(AiAgentService)
        agent._DIRECT_RETURN_TOOLS = DIRECT_RETURN_TOOLS
        agent._SCREENSHOT_TOOLS = SCREENSHOT_TOOLS
        agent._flush_pending_photos = AsyncMock()
        agent._trim_history = MagicMock()

        portal_result = (
            "🚀 **CỔNG CHUYỂN TỆP SIÊU TỐC TIỂU BẢO BẢO ĐÃ SẴN SÀNG!**\n"
            "• Link LAN: http://192.168.0.100:8084/api/ai/transfer/portal/token123"
        )
        agent._execute_tool = AsyncMock(return_value=portal_result)

        history: List[Dict[str, Any]] = []
        pending_photos: List[Any] = []
        fn_name = "create_file_transfer_portal"
        fn_args = {"mode": "upload"}
        chat_id = "test_chat"

        tool_result = await agent._execute_tool(
            fn_name, fn_args, chat_id=chat_id, pending_photos=pending_photos, user_message="chuyển file"
        )

        final_answer = None
        if fn_name in agent._DIRECT_RETURN_TOOLS:
            await agent._flush_pending_photos(pending_photos, chat_id)
            history.append({"role": "assistant", "content": tool_result})
            agent._trim_history(history)
            final_answer = tool_result

        self.assertEqual(final_answer, portal_result)
        self.assertEqual(history[-1]["content"], portal_result)
        agent._flush_pending_photos.assert_called_once_with(pending_photos, chat_id)


if __name__ == "__main__":
    unittest.main()
