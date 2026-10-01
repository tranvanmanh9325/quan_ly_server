"""
test_challenger_video_editor_invocation.py — Challenger Test Suite for Video Editor Invocation & Prompt Reflex.

Verifies:
1. TestDirectReturnToolsRegistry:
   - All 9 M7 Video Editor tools are registered in DIRECT_RETURN_TOOLS (module, executor, service).
   - M6 Multimedia tools are present in DIRECT_RETURN_TOOLS.
   - Non-terminal tools (run_command, get_weather, etc.) remain non-direct-return.
2. TestVideoEditorKeywordScoping:
   - Expanded keywords (is_rm_txt) detect all realistic user phrasing (có dấu, không dấu, teencode).
   - Scoped tools count <= 8 (Groq TPM limit compliant).
   - Protected tools logic preserves remove_text_from_video during pruning.
   - Other 8 video editor tools are properly scoped on corresponding intents.
3. TestVideoEditorPromptImperative:
   - Section 2t in _STATIC_SYSTEM_PREFIX contains mandatory TOOL-FIRST IMPERATIVE.
   - Prohibits text tutorials (DaVinci Resolve, software recommendations).
   - Mandates mode='auto' for text removal.
   - Handles missing video paths without refusing.
   - Verifies static KV-cache invariant.
4. TestVideoEditorActionRiskTier:
   - All 9 video editor tools are classified as ACTION_TIER_1_SAFE.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

os.environ["TESTING"] = "true"

_SERVICE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _SERVICE_DIR not in sys.path:
    sys.path.insert(0, _SERVICE_DIR)

from app.services.ai_agent import AiAgentService
from app.services.ai_agent_tools import (
    ACTION_TIER_1_SAFE,
    AgentToolExecutor,
    DIRECT_RETURN_TOOLS,
    classify_action_risk,
)


def _create_mock_executor() -> AgentToolExecutor:
    mock_ssh = MagicMock()
    mock_cache = MagicMock()
    mock_telegram = MagicMock()
    return AgentToolExecutor(ssh_client=mock_ssh, message_cache=mock_cache, telegram_bot=mock_telegram)


class TestDirectReturnToolsRegistry(unittest.TestCase):
    """Verifies that all 9 video editor tools and M6 tools are in DIRECT_RETURN_TOOLS across all access points."""

    EXPECTED_VIDEO_TOOLS = {
        "remove_text_from_video",
        "add_subtitle_to_video",
        "apply_color_grade",
        "stabilize_video",
        "concatenate_videos",
        "extract_frames",
        "remove_watermark_region",
        "enhance_video_quality",
        "generate_video_thumbnail",
    }

    EXPECTED_M6_TOOLS = {
        "edit_video_clip",
        "compress_video",
        "convert_video_format",
        "convert_audio_format",
        "trim_audio_clip",
        "normalize_audio_volume",
        "convert_and_resize_image",
        "generate_custom_qr",
        "inspect_media_metadata",
        "merge_pdf_documents",
        "split_pdf_document",
        "extract_document_text",
        "translate_text",
        "download_direct_file",
    }

    def test_video_editor_9_tools_in_module_direct_return(self):
        """All 9 video editor tools must be in module-level DIRECT_RETURN_TOOLS."""
        for tool in self.EXPECTED_VIDEO_TOOLS:
            with self.subTest(tool=tool):
                self.assertIn(
                    tool,
                    DIRECT_RETURN_TOOLS,
                    f"Tool '{tool}' must be in DIRECT_RETURN_TOOLS",
                )

    def test_multimedia_m6_tools_in_module_direct_return(self):
        """All M6 multimedia and knowledge tools must be in module-level DIRECT_RETURN_TOOLS."""
        for tool in self.EXPECTED_M6_TOOLS:
            with self.subTest(tool=tool):
                self.assertIn(
                    tool,
                    DIRECT_RETURN_TOOLS,
                    f"Tool '{tool}' must be in DIRECT_RETURN_TOOLS",
                )

    def test_direct_return_class_attributes_propagation(self):
        """DIRECT_RETURN_TOOLS must be propagated to AgentToolExecutor and AiAgentService."""
        for tool in self.EXPECTED_VIDEO_TOOLS:
            with self.subTest(tool=tool):
                self.assertIn(tool, AgentToolExecutor.DIRECT_RETURN_TOOLS)
                self.assertIn(tool, AgentToolExecutor._DIRECT_RETURN_TOOLS)
                self.assertIn(tool, AiAgentService._DIRECT_RETURN_TOOLS)

    def test_differential_non_terminal_tools_remain_excluded(self):
        """Non-terminal tools must NOT be in DIRECT_RETURN_TOOLS."""
        non_terminal = ["run_command", "get_weather", "get_server_location", "read_archive_file"]
        for tool in non_terminal:
            with self.subTest(tool=tool):
                self.assertNotIn(tool, DIRECT_RETURN_TOOLS)


class TestVideoEditorKeywordScoping(unittest.TestCase):
    """Verifies keyword detection and dynamic scoping for video editing requests."""

    def setUp(self):
        self.executor = _create_mock_executor()

    def test_remove_text_realistic_queries_scoping(self):
        """Tests that realistic phrasing for text/watermark removal scopes remove_text_from_video."""
        test_queries = [
            "xóa sạch text trong video giúp tôi",
            "xoa sach text trong video giup toi",
            "xóa chữ trong video này",
            "xoa chu trong video nay",
            "loại bỏ chữ trong clip này",
            "loai bo chu trong clip nay",
            "loại bỏ watermark khỏi video",
            "xóa phụ đề trong video",
            "xoa phu de trong video",
            "xóa sub clip này",
            "làm sạch video cho tôi",
            "lam sach video cho toi",
            "remove watermark from video",
            "remove text from video",
            "xóa watermark góc video",
            "xóa logo trên video",
            "bỏ chữ trong video",
            "xóa bỏ text trong video",
            "xóa caption video",
            "xóa text khỏi video",
            "delogo video này giùm",
        ]
        for query in test_queries:
            with self.subTest(query=query):
                scoped = self.executor._resolve_scoped_tool_names(query=query)
                self.assertIn(
                    "remove_text_from_video",
                    scoped,
                    f"Query '{query}' must scope 'remove_text_from_video'. Scoped: {scoped}",
                )
                self.assertLessEqual(
                    len(scoped),
                    8,
                    f"Query '{query}' exceeded 8-tool ceiling! Got {len(scoped)}: {scoped}",
                )

    def test_other_video_editor_intents_scoping(self):
        """Verifies scoping for the other 8 video editor tools."""
        intent_cases = [
            ("thêm phụ đề tiếng việt vào video này", "add_subtitle_to_video"),
            ("chèn text vào video giúp em", "add_subtitle_to_video"),
            ("chỉnh màu video phong cách vintage", "apply_color_grade"),
            ("filter màu cinematic cho clip", "apply_color_grade"),
            ("ổn định video bị rung camera", "stabilize_video"),
            ("chống rung cho clip này giùm anh", "stabilize_video"),
            ("ghép 2 video này lại thành một", "concatenate_videos"),
            ("nối clip 1 và clip 2", "concatenate_videos"),
            ("trích frame từ video mỗi 5 giây", "extract_frames"),
            ("chụp màn hình video lấy frame ảnh", "extract_frames"),
            ("xóa nhiều watermark cùng lúc trên video", "remove_watermark_region"),
            ("xóa nhiều vùng logo trên clip", "remove_watermark_region"),
            ("nâng chất lượng làm nét video", "enhance_video_quality"),
            ("khử nhiễu video và làm nét", "enhance_video_quality"),
            ("tạo thumbnail ảnh đại diện video", "generate_video_thumbnail"),
            ("tạo cover video tại giây thứ 10", "generate_video_thumbnail"),
        ]
        for query, expected_tool in intent_cases:
            with self.subTest(query=query, expected_tool=expected_tool):
                scoped = self.executor._resolve_scoped_tool_names(query=query)
                self.assertIn(
                    expected_tool,
                    scoped,
                    f"Query '{query}' must scope '{expected_tool}'. Scoped: {scoped}",
                )
                self.assertLessEqual(len(scoped), 8)

    def test_build_tools_pruning_protects_remove_text(self):
        """Verifies that protected_tools in _build_tools() retains remove_text_from_video during pruning."""
        query = "xóa sạch text trong video giúp tôi"
        tools = self.executor._build_tools(force_all=False, last_user_query=query)
        tool_names = [t["function"]["name"] for t in tools]
        self.assertIn(
            "remove_text_from_video",
            tool_names,
            f"Query '{query}' lost 'remove_text_from_video' during _build_tools pruning! Got: {tool_names}",
        )
        self.assertLessEqual(len(tools), 8)


class TestVideoEditorPromptImperative(unittest.TestCase):
    """Verifies that AiAgentService._STATIC_SYSTEM_PREFIX contains the imperative protocol for video editor."""

    def setUp(self):
        self.prefix = AiAgentService._STATIC_SYSTEM_PREFIX

    def test_prompt_contains_tool_first_imperative_header(self):
        """Prompt must contain the non-negotiable tool-first imperative header."""
        self.assertIn(
            "PHẢN XẠ THỰC THI BẮT BUỘC (TOOL-FIRST IMPERATIVE — KHÔNG THƯƠNG LƯỢNG)",
            self.prefix,
        )

    def test_prompt_strictly_prohibits_text_tutorials(self):
        """Prompt must forbid textual tutorials like DaVinci Resolve or generic software."""
        self.assertIn("TUYỆT ĐỐI CẤM trả lời bằng hướng dẫn văn bản", self.prefix)
        self.assertIn("DaVinci Resolve", self.prefix)

    def test_prompt_mandates_auto_mode_for_text_removal(self):
        """Prompt must mandate calling remove_text_from_video with mode='auto'."""
        self.assertIn("remove_text_from_video", self.prefix)
        self.assertIn("mode='auto'", self.prefix)

    def test_prompt_mandates_asking_for_missing_video_path(self):
        """Prompt must instruct asking for link/path without refusing."""
        self.assertIn("Anh gửi đường dẫn file video hoặc link cho em nhé?", self.prefix)
        self.assertIn("CẤM tự ý từ chối thực hiện", self.prefix)

    def test_prompt_static_kv_cache_invariant(self):
        """_STATIC_SYSTEM_PREFIX must be purely invariant without dynamic timestamps."""
        self.assertNotIn("Giờ Việt Nam - ICT/UTC+7", self.prefix)
        self.assertIsInstance(self.prefix, str)
        self.assertGreater(len(self.prefix), 5000)


class TestVideoEditorActionRiskTier(unittest.TestCase):
    """Verifies that all 9 video editor tools are classified as ACTION_TIER_1_SAFE."""

    def test_all_9_tools_classified_as_tier_1_safe(self):
        video_tools = [
            "remove_text_from_video",
            "add_subtitle_to_video",
            "apply_color_grade",
            "stabilize_video",
            "concatenate_videos",
            "extract_frames",
            "remove_watermark_region",
            "enhance_video_quality",
            "generate_video_thumbnail",
        ]
        for tool in video_tools:
            with self.subTest(tool=tool):
                risk = classify_action_risk(tool, {})
                self.assertEqual(
                    risk,
                    ACTION_TIER_1_SAFE,
                    f"Tool '{tool}' must be classified as ACTION_TIER_1_SAFE, got {risk}",
                )


if __name__ == "__main__":
    unittest.main()
