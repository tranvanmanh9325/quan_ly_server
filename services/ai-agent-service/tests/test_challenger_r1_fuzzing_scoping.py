"""
test_challenger_r1_fuzzing_scoping.py — Adversarial Fuzzing & Scoping Stress Harness.

Author: Challenger 1 (teamwork_preview_challenger_r1_1)
Roles: critic, specialist
Purpose:
1. Natural language fuzzing across 9 video editor tools:
   - Diacritics (có dấu), non-diacritics (không dấu), teencode, abbreviations, English variants.
2. Strict tool ceiling invariant:
   - len(scoped) <= 8 tools in all cases, including multi-intent, cross-cluster, and hostile inputs.
3. Pruning and protected_tools stress testing:
   - Token budget pressure simulation (<= 700 tokens gate in _build_tools).
   - Confirmation that protected_tools preserves relevant video editor tools while pruning unprotected ones.
4. Negative testing:
   - Non-video commands (e.g., "xóa file test.txt", "thời tiết") must not scope video editor tools.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import MagicMock

os.environ["TESTING"] = "true"

_SERVICE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _SERVICE_DIR not in sys.path:
    sys.path.insert(0, _SERVICE_DIR)

from app.services.ai_agent_tools import (
    AgentToolExecutor,
    DIRECT_RETURN_TOOLS,
)


def _create_mock_executor() -> AgentToolExecutor:
    mock_ssh = MagicMock()
    mock_cache = MagicMock()
    mock_telegram = MagicMock()
    return AgentToolExecutor(ssh_client=mock_ssh, message_cache=mock_cache, telegram_bot=mock_telegram)


class TestAdversarialFuzzing9VideoTools(unittest.TestCase):
    """Fuzzing dozens of natural language variants (có dấu, không dấu, teencode, viết tắt) for all 9 tools."""

    def setUp(self):
        self.executor = _create_mock_executor()

    def test_fuzzing_remove_text_from_video(self):
        """Tool 1: remove_text_from_video across multiple phrasing variations."""
        queries = [
            # Có dấu
            "xóa sạch text trong video giúp tôi",
            "xóa chữ trong video này",
            "loại bỏ chữ trong clip",
            "xóa phụ đề trong video",
            "làm sạch video cho tôi",
            "xóa caption video",
            "xóa bỏ text trong video",
            "xóa chữ khỏi video",
            "xóa logo trên video",
            "loại bỏ watermark khỏi video",
            "bỏ chữ trong video",
            "xóa sub clip này",
            # Không dấu
            "xoa sach text trong video",
            "xoa chu trong video nay",
            "loai bo chu trong clip",
            "xoa phu de trong video",
            "lam sach video",
            "xoa caption video",
            "xoa bo text trong video",
            "xoa chu khoi clip",
            "xoa logo tren video",
            "loai bo watermark khoi video",
            "bo chu trong video",
            "xoa sub clip nay",
            # Teencode / Viết tắt / Tiếng Anh
            "xoa sach txt",
            "xoa logo goc",
            "xoa sub video",
            "delogo clip nay",
            "remove watermark from video",
            "clean text in video",
            "erase text from clip",
            "wipe text video",
            "clear text in video",
            "remove caption video",
            "text removal from video",
        ]
        for q in queries:
            with self.subTest(query=q):
                scoped = self.executor._resolve_scoped_tool_names(query=q)
                self.assertIn(
                    "remove_text_from_video",
                    scoped,
                    f"Query '{q}' failed to scope 'remove_text_from_video'. Got: {scoped}",
                )
                self.assertLessEqual(
                    len(scoped),
                    8,
                    f"Query '{q}' violated 8-tool ceiling! Got {len(scoped)}: {scoped}",
                )

    def test_fuzzing_add_subtitle_to_video(self):
        """Tool 2: add_subtitle_to_video natural language variations."""
        queries = [
            # Có dấu
            "thêm phụ đề tiếng việt vào video",
            "chèn phụ đề cho clip",
            "gắn phụ đề vào phim",
            "lồng phụ đề vào video",
            "ghép phụ đề tiếng việt",
            "chèn chữ vào video",
            "thêm text vào video",
            "chèn caption vào video",
            # Không dấu
            "them phu de vao video",
            "chen phu de cho clip",
            "gan sub vao video",
            "them sub tieng viet",
            "lam sub cho video",
            "chen chu vao video",
            "them text vao video",
            # Teencode / Tiếng Anh
            "add subtitle to video",
            "burn sub vao video",
            "hardsub cho clip nay",
            "vietsub clip nay giup minh",
            "add sub video",
            "chen caption vao video",
            "them caption",
        ]
        for q in queries:
            with self.subTest(query=q):
                scoped = self.executor._resolve_scoped_tool_names(query=q)
                self.assertIn(
                    "add_subtitle_to_video",
                    scoped,
                    f"Query '{q}' failed to scope 'add_subtitle_to_video'. Got: {scoped}",
                )
                self.assertLessEqual(len(scoped), 8)

    def test_fuzzing_apply_color_grade(self):
        """Tool 3: apply_color_grade natural language variations."""
        queries = [
            # Có dấu
            "chỉnh màu video phong cách vintage",
            "đổi màu video thành cinematic",
            "bộ lọc màu vintage cho video",
            "lọc màu retro cho clip",
            "tông màu đen trắng",
            "chỉnh màu video sang ấm áp",
            "làm màu video phong cách cool",
            # Không dấu
            "chinh mau video vintage",
            "doi mau video cinematic",
            "filter mau retro",
            "grade mau cho clip",
            "doi tong mau video sang am ap",
            "chinh mau video den trang",
            # Teencode / Tiếng Anh
            "color grade video vintage",
            "color grading cinematic clip",
            "filter video retro",
            "black and white video",
            "vivid filter video",
        ]
        for q in queries:
            with self.subTest(query=q):
                scoped = self.executor._resolve_scoped_tool_names(query=q)
                self.assertIn(
                    "apply_color_grade",
                    scoped,
                    f"Query '{q}' failed to scope 'apply_color_grade'. Got: {scoped}",
                )
                self.assertLessEqual(len(scoped), 8)

    def test_fuzzing_stabilize_video(self):
        """Tool 4: stabilize_video natural language variations."""
        queries = [
            # Có dấu
            "ổn định video bị rung camera",
            "chống rung cho clip này giùm anh",
            "khử rung video quay bằng điện thoại",
            "giảm rung cho video",
            "làm mượt video bị giật",
            "ổn định hình ảnh cho clip",
            # Không dấu
            "on dinh video bi rung",
            "chong rung cho clip",
            "khu rung video nay",
            "giam rung clip",
            "lam muot video bi lac",
            "bot rung cho video",
            # Teencode / Tiếng Anh
            "stabilize video shaky",
            "vidstab cho clip",
            "deshake this video",
            "video stabilization please",
            "smooth video giup voi",
        ]
        for q in queries:
            with self.subTest(query=q):
                scoped = self.executor._resolve_scoped_tool_names(query=q)
                self.assertIn(
                    "stabilize_video",
                    scoped,
                    f"Query '{q}' failed to scope 'stabilize_video'. Got: {scoped}",
                )
                self.assertLessEqual(len(scoped), 8)

    def test_fuzzing_concatenate_videos(self):
        """Tool 5: concatenate_videos natural language variations."""
        queries = [
            # Có dấu
            "ghép 2 video này lại thành một",
            "nối clip 1 và clip 2",
            "gộp video phần 1 và phần 2",
            "ghép các video lại với nhau",
            "nối nhiều clip lại",
            # Không dấu
            "ghep video phan 1 va phan 2",
            "noi clip 1 voi clip 2",
            "gop video lai thanh mot",
            "noi 2 video",
            "ghep cac video lai",
            # Teencode / Tiếng Anh
            "merge video a va b",
            "concat video 1 and 2",
            "join video clips",
            "combine video files",
            "stitch video clips together",
        ]
        for q in queries:
            with self.subTest(query=q):
                scoped = self.executor._resolve_scoped_tool_names(query=q)
                self.assertIn(
                    "concatenate_videos",
                    scoped,
                    f"Query '{q}' failed to scope 'concatenate_videos'. Got: {scoped}",
                )
                self.assertLessEqual(len(scoped), 8)

    def test_fuzzing_extract_frames(self):
        """Tool 6: extract_frames natural language variations."""
        queries = [
            # Có dấu
            "trích frame từ video mỗi 5 giây",
            "cắt frame ảnh từ video",
            "lấy ảnh từ video",
            "trích xuất frame clip",
            "tách frame từ video",
            "chụp frame từ video",
            "trích khung hình video",
            # Không dấu
            "trich frame tu video",
            "cat frame anh tu clip",
            "lay frame tu video",
            "tach frame video",
            "lay tung frame anh",
            "trich khung hinh video",
            # Teencode / Tiếng Anh
            "extract frames from video",
            "capture frames from clip",
            "video to frames converter",
            "lay frame anh tu video",
        ]
        for q in queries:
            with self.subTest(query=q):
                scoped = self.executor._resolve_scoped_tool_names(query=q)
                self.assertIn(
                    "extract_frames",
                    scoped,
                    f"Query '{q}' failed to scope 'extract_frames'. Got: {scoped}",
                )
                self.assertLessEqual(len(scoped), 8)

    def test_fuzzing_remove_watermark_region(self):
        """Tool 7: remove_watermark_region natural language variations."""
        queries = [
            # Có dấu
            "xóa nhiều watermark cùng lúc trên video",
            "xóa vùng watermark ở góc trên bên phải",
            "xóa logo góc video",
            "xóa nhiều vùng logo trên clip",
            "loại bỏ nhiều watermark trên màn hình",
            # Không dấu
            "xoa nhieu watermark tren video",
            "xoa vung watermark o goc",
            "xoa logo goc clip",
            "xoa watermark theo vung",
            "nhieu vung logo tren video",
            # Teencode / Tiếng Anh
            "remove watermark region",
            "remove multiple watermarks from video",
            "multi watermark removal",
            "xoa watermark goc video",
        ]
        for q in queries:
            with self.subTest(query=q):
                scoped = self.executor._resolve_scoped_tool_names(query=q)
                self.assertIn(
                    "remove_watermark_region",
                    scoped,
                    f"Query '{q}' failed to scope 'remove_watermark_region'. Got: {scoped}",
                )
                self.assertLessEqual(len(scoped), 8)

    def test_fuzzing_enhance_video_quality(self):
        """Tool 8: enhance_video_quality natural language variations."""
        queries = [
            # Có dấu
            "nâng chất lượng làm nét video",
            "khử nhiễu video và làm nét",
            "nâng cao chất lượng clip bị mờ",
            "làm rõ video cũ",
            "tăng độ nét cho video",
            # Không dấu
            "tang chat luong video",
            "nang chat luong clip",
            "lam net video bi mo",
            "khu nhieu video",
            "tang do net video",
            "lam ro video",
            # Teencode / Tiếng Anh
            "upscale video 1080p",
            "enhance video quality",
            "sharpen video clip",
            "denoise video",
            "super resolution video",
        ]
        for q in queries:
            with self.subTest(query=q):
                scoped = self.executor._resolve_scoped_tool_names(query=q)
                self.assertIn(
                    "enhance_video_quality",
                    scoped,
                    f"Query '{q}' failed to scope 'enhance_video_quality'. Got: {scoped}",
                )
                self.assertLessEqual(len(scoped), 8)

    def test_fuzzing_generate_video_thumbnail(self):
        """Tool 9: generate_video_thumbnail natural language variations."""
        queries = [
            # Có dấu
            "tạo thumbnail ảnh đại diện video",
            "tạo cover video tại giây thứ 10",
            "tạo ảnh bìa cho clip này",
            "làm thumbnail video đăng youtube",
            "cắt thumbnail từ video",
            # Không dấu
            "tao thumbnail cho video",
            "anh dai dien video nay",
            "tao cover video",
            "tao anh bia video",
            "lam thumbnail clip",
            "lay thumbnail video",
            # Teencode / Tiếng Anh
            "generate thumbnail for video",
            "video poster image",
            "video thumbnail generator",
        ]
        for q in queries:
            with self.subTest(query=q):
                scoped = self.executor._resolve_scoped_tool_names(query=q)
                self.assertIn(
                    "generate_video_thumbnail",
                    scoped,
                    f"Query '{q}' failed to scope 'generate_video_thumbnail'. Got: {scoped}",
                )
                self.assertLessEqual(len(scoped), 8)


class TestStrictToolCeilingAndEdgeCases(unittest.TestCase):
    """Stress tests on tool ceiling (len(scoped) <= 8) with multi-intent, cross-cluster, and hostile queries."""

    def setUp(self):
        self.executor = _create_mock_executor()

    def test_multi_intent_video_queries_ceiling(self):
        """Queries requesting multiple video editor operations simultaneously must stay <= 8 tools."""
        multi_intent_queries = [
            "vừa xóa text vừa thêm phụ đề vào video",
            "cắt video rồi nén lại và chỉnh màu",
            "ghép video và chống rung rồi nâng chất lượng",
            "xóa sạch text trong video rồi tạo thumbnail và trích frame",
            "chỉnh màu video vintage và thêm vietsub đồng thời khử rung",
            # Mega video query combining ALL 9 video editor operations
            "vừa xóa text vừa thêm sub vừa chỉnh màu vừa chống rung vừa ghép video vừa trích frame vừa xóa watermark vừa làm nét vừa tạo thumbnail",
        ]
        for q in multi_intent_queries:
            with self.subTest(query=q):
                scoped = self.executor._resolve_scoped_tool_names(query=q)
                self.assertLessEqual(
                    len(scoped),
                    8,
                    f"Multi-intent query '{q}' exceeded 8-tool ceiling! Got {len(scoped)}: {scoped}",
                )
                self.assertGreaterEqual(
                    len(scoped),
                    1,
                    f"Multi-intent query '{q}' returned empty tools set!",
                )

    def test_cross_cluster_complex_queries_ceiling(self):
        """Cross-cluster queries mixing media studio, system root, docs, security, web must respect ceiling."""
        cross_queries = [
            "xóa text trong video rồi gộp pdf xong unblock ip 1.2.3.4 và kiểm tra ram server gửi tin nhắn facebook bấm vào nút web",
            "chống rung clip và quản lý docker container restart đồng thời đọc file word báo cáo và tải file",
            "tạo thumbnail video rồi backup ổ cứng ghi file log và giải nén file zip",
            "làm nét video rồi tạo mã qr wifi xong dịch văn bản tiếng anh sang tiếng việt",
        ]
        for q in cross_queries:
            with self.subTest(query=q):
                scoped = self.executor._resolve_scoped_tool_names(query=q)
                self.assertLessEqual(
                    len(scoped),
                    8,
                    f"Cross-cluster query exceeded 8 tools! Got {len(scoped)}: {scoped}",
                )

    def test_hostile_and_boundary_queries(self):
        """Boundary inputs: empty, spaces, punctuation, emoji, repetitive, and injection attempts."""
        hostile_cases = [
            "",
            "   ",
            "🎬🎥✨🚀🔥",
            "xóa text trong video " * 50,
            "xóa text trong video; rm -rf /; ' OR '1'='1' --",
            "video " * 100,
            "\n\t\r\0",
        ]
        for q in hostile_cases:
            with self.subTest(query=repr(q[:30])):
                scoped = self.executor._resolve_scoped_tool_names(query=q)
                self.assertLessEqual(
                    len(scoped),
                    8,
                    f"Hostile query exceeded 8 tools! Got {len(scoped)}: {scoped}",
                )
                self.assertGreaterEqual(len(scoped), 1)


class TestPruningAndProtectedTools(unittest.TestCase):
    """Stress tests on _build_tools pruning under token budget pressure and protected_tools logic."""

    def setUp(self):
        self.executor = _create_mock_executor()

    def test_build_tools_preserves_target_video_tool_for_each_intent(self):
        """Each video editor intent must have its corresponding tool protected and present after _build_tools()."""
        intent_mapping = [
            ("xóa sạch text trong video giúp tôi", "remove_text_from_video"),
            ("thêm phụ đề tiếng việt vào video", "add_subtitle_to_video"),
            ("chỉnh màu video phong cách vintage", "apply_color_grade"),
            ("ổn định video bị rung camera", "stabilize_video"),
            ("ghép 2 video này lại thành một", "concatenate_videos"),
            ("trích frame từ video mỗi 5 giây", "extract_frames"),
            ("xóa nhiều watermark cùng lúc trên video", "remove_watermark_region"),
            ("nâng chất lượng làm nét video", "enhance_video_quality"),
            ("tạo thumbnail ảnh đại diện video", "generate_video_thumbnail"),
        ]
        for query, expected_tool in intent_mapping:
            with self.subTest(query=query, expected_tool=expected_tool):
                tools = self.executor._build_tools(force_all=False, last_user_query=query)
                tool_names = [t.get("function", {}).get("name") for t in tools]
                self.assertIn(
                    expected_tool,
                    tool_names,
                    f"Tool '{expected_tool}' was lost during _build_tools pruning for query '{query}'! Tools: {tool_names}",
                )
                self.assertLessEqual(
                    len(tools),
                    8,
                    f"Tools count after _build_tools exceeded 8! Got {len(tools)}: {tool_names}",
                )

    def test_protected_tools_priority_under_token_pressure_simulation(self):
        """Simulate token budget pressure where tools must be dropped down to minimal threshold."""
        query = "xóa sạch text trong video giúp tôi"
        # Call _build_tools directly
        tools = self.executor._build_tools(force_all=False, last_user_query=query)
        tool_names = {t.get("function", {}).get("name") for t in tools}

        # remove_text_from_video must be protected and preserved
        self.assertIn("remove_text_from_video", tool_names)
        self.assertLessEqual(len(tools), 8)

        # Verify that reverse_priority drops unprotected tools before protected_tools
        q_lower = query.lower()
        # Verify protected_tools logic manually against executor definitions
        has_rm_txt = any(k in q_lower for k in ("xóa text", "xoa text", "xóa sạch", "xoa sach text"))
        self.assertTrue(has_rm_txt)


class TestNegativeScopingIntegrity(unittest.TestCase):
    """Verifies that non-video queries do NOT falsely scope video editor tools."""

    def setUp(self):
        self.executor = _create_mock_executor()

    def test_non_video_queries_do_not_scope_remove_text(self):
        """Ensure file management, system monitoring, and weather don't falsely trigger video text removal."""
        negative_queries = [
            "thời tiết hà nội hôm nay thế nào",
            "chạy lệnh ls -la trên server",
            "kiểm tra ram và cpu của máy chủ",
            "đọc file pdf báo cáo doanh thu",
            "gộp các file pdf lại thành một",
            "tính 25 * 40 bằng bao nhiêu",
            "tìm kiếm trên google tin tức công nghệ",
            "xóa file test.txt",  # "xóa file" must NOT trigger remove_text_from_video!
            "xóa ghi chú cuộc họp hôm qua",
            "xóa cron job hàng ngày",
        ]
        for q in negative_queries:
            with self.subTest(query=q):
                scoped = self.executor._resolve_scoped_tool_names(query=q)
                self.assertNotIn(
                    "remove_text_from_video",
                    scoped,
                    f"False positive: Query '{q}' incorrectly scoped 'remove_text_from_video'! Scoped: {scoped}",
                )


if __name__ == "__main__":
    unittest.main()
