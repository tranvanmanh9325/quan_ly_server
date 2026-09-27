"""
services/ai-agent-service/tests/test_ai_agent_omni_tools.py
Milestone 3 Comprehensive Unit & Empirical Test Suite for Omni Tool Registry,
Dynamic Scoping with Token Budgeting, Dispatcher Integrations, and Spinal Safety Veto.

Covers:
1. TestOmniToolSchemas: Validates OpenAI function-calling format, property schemas, and required params.
2. TestOmniDynamicScoping: Tests 30+ Vietnamese queries (with/without accents, teencode),
   validates Priority Pruning (<= 6 tools for heavy cluster, <= 8 tools otherwise),
   token budget threshold (< 700 tokens), and specialized intent boosting.
3. TestOmniDispatchers: Verifies parameter mapping and markdown outputs for all 18 new tools + run_command.
4. TestOmniRiskAndSpinalVeto: Asserts Action Risk Tri-Tier classifications and Spinal Safety Veto guards.
5. TestStaticSystemPrefixIntegration: Asserts static system prefix protocols 2p, 2q, 2r, 2s & Tier updates.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

os.environ["TESTING"] = "true"

_SERVICE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _SERVICE_DIR not in sys.path:
    sys.path.insert(0, _SERVICE_DIR)

from app.services.ai_agent_tools import (
    ACTION_TIER_1_SAFE,
    ACTION_TIER_2_OPERATIONAL,
    ACTION_TIER_2_REVERSIBLE,
    ACTION_TIER_3_LETHAL,
    AgentToolExecutor,
    classify_action_risk,
)
from app.services.ai_agent import AiAgentService


class TestOmniToolSchemas(unittest.TestCase):
    """Verifies that all 18 new M1/M2 tools + run_command have valid OpenAI schemas."""

    def setUp(self):
        self.mock_ssh = MagicMock()
        self.mock_cache = MagicMock()
        self.executor = AgentToolExecutor(ssh_client=self.mock_ssh, message_cache=self.mock_cache)
        self.all_tools = self.executor._build_tools(force_all=True)
        self.tool_map = {t["function"]["name"]: t["function"] for t in self.all_tools}

    def test_all_18_new_tools_and_run_command_present(self):
        expected_tools = {
            # Multimedia (8)
            "edit_video_clip",
            "compress_video",
            "convert_video_format",
            "convert_audio_format",
            "trim_audio_clip",
            "normalize_audio_volume",
            "convert_and_resize_image",
            "generate_custom_qr",
            # Documents (5)
            "merge_pdf_documents",
            "split_pdf_document",
            "extract_document_text",
            "translate_text",
            "inspect_media_metadata",
            # Web (2)
            "download_direct_file",
            "extract_clean_web_article",
            # System (4)
            "run_command",
            "execute_system_script",
            "manage_docker_containers",
            "optimize_system_resources",
        }
        for tool_name in expected_tools:
            self.assertIn(
                tool_name,
                self.tool_map,
                f"Tool '{tool_name}' must be registered in AgentToolExecutor._build_tools()",
            )

    def test_openai_format_compliance(self):
        for tool in self.all_tools:
            self.assertEqual(tool.get("type"), "function", f"Tool {tool} must specify type='function'")
            fn = tool.get("function", {})
            self.assertTrue(bool(fn.get("name")), f"Tool {tool} missing function name")
            self.assertTrue(bool(fn.get("description")), f"Tool {fn.get('name')} missing description")
            params = fn.get("parameters", {})
            self.assertEqual(params.get("type"), "object", f"Tool {fn.get('name')} parameters type must be object")
            self.assertIsInstance(params.get("properties"), dict, f"Tool {fn.get('name')} missing properties dict")

    def test_required_parameters_integrity(self):
        required_checks = {
            "edit_video_clip": ["input_path_or_url", "start_time", "duration"],
            "compress_video": ["input_path_or_url"],
            "convert_video_format": ["input_path_or_url", "target_format"],
            "convert_audio_format": ["input_path_or_url"],
            "trim_audio_clip": ["input_path_or_url", "start_time", "duration"],
            "normalize_audio_volume": ["input_path_or_url"],
            "convert_and_resize_image": ["input_path_or_url"],
            "generate_custom_qr": ["content"],
            "merge_pdf_documents": ["file_paths"],
            "split_pdf_document": ["file_path", "page_ranges"],
            "extract_document_text": ["file_path"],
            "translate_text": ["text"],
            "inspect_media_metadata": ["file_path_or_url"],
            "download_direct_file": ["url"],
            "extract_clean_web_article": ["url"],
            "execute_system_script": ["script_code"],
            "manage_docker_containers": ["action"],
            "run_command": ["command"],
        }
        for tool_name, expected_reqs in required_checks.items():
            fn = self.tool_map[tool_name]
            actual_reqs = fn.get("parameters", {}).get("required", [])
            for req in expected_reqs:
                self.assertIn(
                    req,
                    actual_reqs,
                    f"Parameter '{req}' must be required for tool '{tool_name}'",
                )


class TestOmniDynamicScoping(unittest.TestCase):
    """
    Evaluates Dynamic Tool Scoping & Groq Token Budget across 30+ queries.
    Asserts:
    1. Tool count: <= 6 when heavy cluster is active; <= 8 otherwise.
    2. Estimated token budget < 700 tokens across all queries.
    3. Specialized Intent Boosters prioritize the exact tool needed.
    """

    def setUp(self):
        self.mock_ssh = MagicMock()
        self.mock_cache = MagicMock()
        self.executor = AgentToolExecutor(ssh_client=self.mock_ssh, message_cache=self.mock_cache)

    def _estimate_tokens(self, tools: list[dict]) -> int:
        raw_json = json.dumps(tools, ensure_ascii=False)
        return len(raw_json) // 4

    def test_multimedia_queries_dynamic_scoping(self):
        media_queries = [
            ("cắt đoạn video này từ phút thứ 1 đến 2", "edit_video_clip"),
            ("cat clip video nay", "edit_video_clip"),
            ("nén video này cho nhẹ để gửi telegram", "compress_video"),
            ("nen video nay xuong duoi 50mb", "compress_video"),
            ("chuyển định dạng video sang mkv", "convert_video_format"),
            ("convert video mp4 sang gif", "convert_video_format"),
            ("đổi đuôi nhạc sang mp3 320kbps", "convert_audio_format"),
            ("flac sang mp3 chat luong cao", "convert_audio_format"),
            ("cắt nhạc chuông 30 giây", "trim_audio_clip"),
            ("cat audio bai hat nay", "trim_audio_clip"),
            ("chuẩn hóa âm lượng bài hát loudnorm", "normalize_audio_volume"),
            ("can bang am luong ebu r128", "normalize_audio_volume"),
            ("can bang am luong bai hat", "normalize_audio_volume"),
            ("resize ảnh và đổi sang webp", "convert_and_resize_image"),
            ("doi kich thuoc anh nay giup anh", "convert_and_resize_image"),
            ("tạo mã qr kết nối wifi gia đình", "generate_custom_qr"),
            ("tao ma qr stk ngan hang", "generate_custom_qr"),
            ("kiểm tra thông tin codec video ffprobe", "inspect_media_metadata"),
            ("check metadata va do phan giai video", "inspect_media_metadata"),
        ]
        for query, expected_boosted_tool in media_queries:
            scoped = self.executor._build_tools(force_all=False, last_user_query=query)
            scoped_names = [t["function"]["name"] for t in scoped]
            token_count = self._estimate_tokens(scoped)

            # Heavy cluster rule: <= 6 tools
            self.assertLessEqual(
                len(scoped),
                6,
                f"Query '{query}' has heavy cluster, tool count must be <= 6. Got: {len(scoped)} ({scoped_names})",
            )
            # Token budget gate: < 700 tokens
            self.assertLess(
                token_count,
                700,
                f"Query '{query}' exceeded token budget: {token_count} tokens >= 700",
            )
            # Expected boosted tool must be included
            self.assertIn(
                expected_boosted_tool,
                scoped_names,
                f"Query '{query}' must include boosted tool '{expected_boosted_tool}'. Found: {scoped_names}",
            )

    def test_document_and_knowledge_queries_dynamic_scoping(self):
        doc_queries = [
            ("gộp các file pdf này thành một tệp", "merge_pdf_documents"),
            ("ghep pdf bao cao quy 3", "merge_pdf_documents"),
            ("tách các trang 1-5 từ file pdf này", "split_pdf_document"),
            ("tach file pdf hop dong", "split_pdf_document"),
            ("đọc nội dung file báo cáo pdf này", "extract_document_text"),
            ("doc file docx hop dong xem noi dung", "extract_document_text"),
            ("dịch tài liệu kỹ thuật này sang tiếng việt", "translate_text"),
            ("dich doan text sang tieng anh", "translate_text"),
        ]
        for query, expected_boosted_tool in doc_queries:
            scoped = self.executor._build_tools(force_all=False, last_user_query=query)
            scoped_names = [t["function"]["name"] for t in scoped]
            token_count = self._estimate_tokens(scoped)

            self.assertLessEqual(
                len(scoped),
                8,
                f"Query '{query}' tool count must be <= 8. Got: {len(scoped)} ({scoped_names})",
            )
            self.assertLess(
                token_count,
                700,
                f"Query '{query}' exceeded token budget: {token_count} tokens >= 700",
            )
            self.assertIn(
                expected_boosted_tool,
                scoped_names,
                f"Query '{query}' must include boosted tool '{expected_boosted_tool}'. Found: {scoped_names}",
            )

    def test_web_extraction_queries_dynamic_scoping(self):
        web_queries = [
            ("tải tệp zip này từ mạng về máy", "download_direct_file"),
            ("download file iso tu link nay", "download_direct_file"),
            ("bóc bài viết từ link vnexpress này sang markdown", "extract_clean_web_article"),
            ("doc bai bao tu duong dan nay", "extract_clean_web_article"),
        ]
        for query, expected_boosted_tool in web_queries:
            scoped = self.executor._build_tools(force_all=False, last_user_query=query)
            scoped_names = [t["function"]["name"] for t in scoped]
            token_count = self._estimate_tokens(scoped)

            self.assertLessEqual(
                len(scoped),
                8,
                f"Query '{query}' tool count must be <= 8. Got: {len(scoped)} ({scoped_names})",
            )
            self.assertLess(
                token_count,
                700,
                f"Query '{query}' exceeded token budget: {token_count} tokens >= 700",
            )
            self.assertIn(
                expected_boosted_tool,
                scoped_names,
                f"Query '{query}' must include boosted tool '{expected_boosted_tool}'. Found: {scoped_names}",
            )

    def test_system_root_queries_dynamic_scoping(self):
        system_queries = [
            ("khởi động lại container docker postgres", "manage_docker_containers"),
            ("restart container dashboard_db", "manage_docker_containers"),
            ("tối ưu hệ thống giải phóng ram", "optimize_system_resources"),
            ("toi uu he thong drop caches", "optimize_system_resources"),
            ("don ram", "optimize_system_resources"),
            ("dọn ram máy chủ", "optimize_system_resources"),
            ("dọn dẹp ram", "optimize_system_resources"),
            ("don dep ram", "optimize_system_resources"),
            ("chạy script python tính fibonacci", "execute_system_script"),
            ("chay kich ban bash backup du lieu", "execute_system_script"),
        ]
        for query, expected_boosted_tool in system_queries:
            scoped = self.executor._build_tools(force_all=False, last_user_query=query)
            scoped_names = [t["function"]["name"] for t in scoped]
            token_count = self._estimate_tokens(scoped)

            self.assertLessEqual(
                len(scoped),
                8,
                f"Query '{query}' tool count must be <= 8. Got: {len(scoped)} ({scoped_names})",
            )
            self.assertLess(
                token_count,
                700,
                f"Query '{query}' exceeded token budget: {token_count} tokens >= 700",
            )
            self.assertIn(
                expected_boosted_tool,
                scoped_names,
                f"Query '{query}' must include boosted tool '{expected_boosted_tool}'. Found: {scoped_names}",
            )

    def test_general_queries_fallback_and_token_budget(self):
        general_queries = [
            "chào em yêu",
            "server tình hình thế nào rồi em",
            "thời tiết hôm nay ở vinh ra răng",
            "mấy giờ rồi em",
            "kiểm tra ram máy chủ",
        ]
        for query in general_queries:
            scoped = self.executor._build_tools(force_all=False, last_user_query=query)
            token_count = self._estimate_tokens(scoped)
            self.assertLessEqual(len(scoped), 8)
            self.assertLess(token_count, 700)

    def test_m3_iteration_2_adversarial_fixes(self):
        """Validates all adversarial edge cases identified by Challenger M3-1 & M3-2:
        1. 'don ram' / 'dọn ram' / 'dọn dẹp ram' / 'don dep ram' routing to optimize_system_resources
        2. 'can bang am luong' unaccented routing to normalize_audio_volume
        3. 'thoi tiet' unaccented query preserving get_weather
        4. 'bẫy kẻ thất bại' preserving get_honeypot_log through Token Budget Gate
        """
        checks = [
            ("don ram", "optimize_system_resources"),
            ("dọn ram", "optimize_system_resources"),
            ("dọn dẹp ram", "optimize_system_resources"),
            ("don dep ram", "optimize_system_resources"),
            ("don ram he thong", "optimize_system_resources"),
            ("can bang am luong bai hat", "normalize_audio_volume"),
            ("thoi tiet hom nay", "get_weather"),
            ("thoi tiet", "get_weather"),
            ("bua ni thoi tiet the nao", "get_weather"),
            ("bẫy kẻ thất bại", "get_honeypot_log"),
            ("xem honeypot", "get_honeypot_log"),
            ("lịch sử tấn công", "get_attack_history"),
            ("lich su tan cong", "get_attack_history"),
        ]
        for query, expected_tool in checks:
            scoped = self.executor._build_tools(force_all=False, last_user_query=query)
            scoped_names = [t["function"]["name"] for t in scoped]
            token_count = self._estimate_tokens(scoped)

            self.assertLessEqual(
                len(scoped),
                8,
                f"Query '{query}' exceeded max tools: {len(scoped)} > 8",
            )
            self.assertLess(
                token_count,
                700,
                f"Query '{query}' exceeded token budget: {token_count} >= 700",
            )
            self.assertIn(
                expected_tool,
                scoped_names,
                f"Query '{query}' must include expected tool '{expected_tool}'. Found: {scoped_names}",
            )



class TestOmniDispatchers(unittest.IsolatedAsyncioTestCase):
    """Verifies end-to-end tool execution and dispatcher parameter mapping for all 18 tools + run_command."""

    def setUp(self):
        self.mock_ssh = AsyncMock()
        self.mock_cache = MagicMock()
        self.mock_multimedia = AsyncMock()
        self.mock_document = AsyncMock()
        self.mock_universal_downloader = AsyncMock()
        self.mock_web_extractor = AsyncMock()
        self.mock_system_mastery = AsyncMock()

        self.executor = AgentToolExecutor(
            ssh_client=self.mock_ssh,
            message_cache=self.mock_cache,
            multimedia_service=self.mock_multimedia,
            document_service=self.mock_document,
            universal_downloader=self.mock_universal_downloader,
            web_article_extractor=self.mock_web_extractor,
            system_mastery_service=self.mock_system_mastery,
        )

    async def test_dispatch_edit_video_clip(self):
        self.mock_multimedia.edit_video_clip.return_value = {
            "status": "ok",
            "output_path": "/tmp/cut.mp4",
            "file_size_formatted": "12.5 MB",
            "duration_processed": 30,
            "output_format": "mp4",
        }
        res = await self.executor._execute_tool(
            "edit_video_clip",
            {"input_path_or_url": "/tmp/orig.mp4", "start_time": "00:01:00", "duration": "30"},
        )
        self.mock_multimedia.edit_video_clip.assert_awaited_once_with(
            input_path_or_url="/tmp/orig.mp4",
            start_time="00:01:00",
            duration="30",
            output_format="mp4",
            reencode=False,
        )
        self.assertIn("/tmp/cut.mp4", res)

    async def test_dispatch_compress_video(self):
        self.mock_multimedia.compress_video.return_value = {
            "status": "ok",
            "output_path": "/tmp/compressed.mp4",
            "compressed_size_formatted": "45.0 MB",
            "original_size_formatted": "120.0 MB",
            "compression_ratio": "62.5%",
        }
        res = await self.executor._execute_tool(
            "compress_video",
            {"input_path_or_url": "/tmp/big.mp4", "target_size_mb": 45.0},
        )
        self.mock_multimedia.compress_video.assert_awaited_once_with(
            input_path_or_url="/tmp/big.mp4",
            target_size_mb=45.0,
        )
        self.assertIn("/tmp/compressed.mp4", res)

    async def test_dispatch_convert_video_format(self):
        self.mock_multimedia.convert_video_format.return_value = {
            "status": "ok",
            "output_path": "/tmp/converted.mkv",
            "file_size_formatted": "25.0 MB",
            "target_format": "mkv",
        }
        res = await self.executor._execute_tool(
            "convert_video_format",
            {"input_path_or_url": "/tmp/orig.mp4", "target_format": "mkv"},
        )
        self.mock_multimedia.convert_video_format.assert_awaited_once_with(
            input_path_or_url="/tmp/orig.mp4",
            target_format="mkv",
            preset="fast",
        )
        self.assertIn("/tmp/converted.mkv", res)

    async def test_dispatch_convert_audio_format(self):
        self.mock_multimedia.convert_audio_format.return_value = {
            "status": "ok",
            "output_path": "/tmp/song.mp3",
            "file_size_formatted": "8.0 MB",
            "bitrate": "320k",
            "target_format": "mp3",
        }
        res = await self.executor._execute_tool(
            "convert_audio_format",
            {"input_path_or_url": "/tmp/song.flac", "target_format": "mp3", "bitrate": "320k"},
        )
        self.mock_multimedia.convert_audio_format.assert_awaited_once_with(
            input_path_or_url="/tmp/song.flac",
            target_format="mp3",
            bitrate="320k",
        )
        self.assertIn("/tmp/song.mp3", res)

    async def test_dispatch_trim_audio_clip(self):
        self.mock_multimedia.trim_audio_clip.return_value = {
            "status": "ok",
            "output_path": "/tmp/ringtone.mp3",
            "file_size_formatted": "1.2 MB",
        }
        res = await self.executor._execute_tool(
            "trim_audio_clip",
            {"input_path_or_url": "/tmp/song.mp3", "start_time": "15", "duration": "30"},
        )
        self.mock_multimedia.trim_audio_clip.assert_awaited_once_with(
            input_path_or_url="/tmp/song.mp3",
            start_time="15",
            duration="30",
        )
        self.assertIn("/tmp/ringtone.mp3", res)

    async def test_dispatch_normalize_audio_volume(self):
        self.mock_multimedia.normalize_audio_volume.return_value = {
            "status": "ok",
            "output_path": "/tmp/normalized.mp3",
            "file_size_formatted": "5.0 MB",
        }
        res = await self.executor._execute_tool(
            "normalize_audio_volume",
            {"input_path_or_url": "/tmp/quiet.mp3"},
        )
        self.mock_multimedia.normalize_audio_volume.assert_awaited_once_with(
            input_path_or_url="/tmp/quiet.mp3",
        )
        self.assertIn("/tmp/normalized.mp3", res)

    async def test_dispatch_convert_and_resize_image(self):
        self.mock_multimedia.convert_and_resize_image.return_value = {
            "status": "ok",
            "output_path": "/tmp/thumb.webp",
            "file_size_formatted": "450 KB",
            "width": 1280,
            "height": 720,
        }
        res = await self.executor._execute_tool(
            "convert_and_resize_image",
            {"input_path_or_url": "/tmp/photo.jpg", "format": "webp", "max_width": 1280},
        )
        self.mock_multimedia.convert_and_resize_image.assert_awaited_once_with(
            input_path_or_url="/tmp/photo.jpg",
            format="webp",
            max_width=1280,
            max_height=None,
            quality=85,
        )
        self.assertIn("/tmp/thumb.webp", res)

    async def test_dispatch_generate_custom_qr(self):
        self.mock_multimedia.generate_custom_qr.return_value = {
            "status": "ok",
            "output_path": "/tmp/qr_wifi.png",
            "width": 300,
            "height": 300,
        }
        res = await self.executor._execute_tool(
            "generate_custom_qr",
            {"content": "WIFI:S:Home;P:Secret;;", "label": "Kirito WiFi"},
        )
        self.mock_multimedia.generate_custom_qr.assert_awaited_once_with(
            content="WIFI:S:Home;P:Secret;;",
            label="Kirito WiFi",
            fill_color="#0f172a",
            back_color="#ffffff",
        )
        self.assertIn("/tmp/qr_wifi.png", res)

    async def test_dispatch_merge_pdf_documents(self):
        self.mock_document.merge_pdf_documents.return_value = {
            "status": "ok",
            "output_path": "/tmp/merged.pdf",
            "file_size_formatted": "4.2 MB",
            "total_pages": 25,
            "total_files_merged": 3,
        }
        res = await self.executor._execute_tool(
            "merge_pdf_documents",
            {"file_paths": ["/tmp/p1.pdf", "/tmp/p2.pdf", "/tmp/p3.pdf"], "output_name": "merged.pdf"},
        )
        self.mock_document.merge_pdf_documents.assert_awaited_once_with(
            file_paths=["/tmp/p1.pdf", "/tmp/p2.pdf", "/tmp/p3.pdf"],
            output_name="merged.pdf",
        )
        self.assertIn("/tmp/merged.pdf", res)

    async def test_dispatch_split_pdf_document(self):
        self.mock_document.split_pdf_document.return_value = {
            "status": "ok",
            "output_path": "/tmp/split.pdf",
            "file_size_formatted": "1.5 MB",
            "total_pages_extracted": 5,
        }
        res = await self.executor._execute_tool(
            "split_pdf_document",
            {"file_path": "/tmp/book.pdf", "page_ranges": "1-5"},
        )
        self.mock_document.split_pdf_document.assert_awaited_once_with(
            file_path="/tmp/book.pdf",
            page_ranges="1-5",
            output_name=None,
        )
        self.assertIn("/tmp/split.pdf", res)

    async def test_dispatch_extract_document_text(self):
        self.mock_document.extract_document_text.return_value = {
            "status": "ok",
            "text": "Báo cáo kinh doanh Q3 đạt kỳ vọng...",
            "file_name": "report.pdf",
        }
        res = await self.executor._execute_tool(
            "extract_document_text",
            {"file_path": "/tmp/report.pdf", "max_characters": 5000},
        )
        self.mock_document.extract_document_text.assert_awaited_once_with(
            file_path="/tmp/report.pdf",
            max_chars=5000,
        )
        self.assertIn("Báo cáo kinh doanh", res)

    async def test_dispatch_translate_text(self):
        self.mock_document.translate_text.return_value = {
            "status": "ok",
            "translated_text": "Autonomous Agent Architecture",
            "source_lang": "vi",
            "target_lang": "en",
        }
        res = await self.executor._execute_tool(
            "translate_text",
            {"text": "Kiến trúc tác tử tự hành", "target_lang": "en"},
        )
        self.mock_document.translate_text.assert_awaited_once_with(
            text="Kiến trúc tác tử tự hành",
            target_lang="en",
            source_lang="auto",
        )
        self.assertIn("Autonomous Agent Architecture", res)

    async def test_dispatch_inspect_media_metadata(self):
        self.mock_document.inspect_media_metadata.return_value = {
            "status": "ok",
            "media_type": "video",
            "file_size_formatted": "50 MB",
            "metadata": {
                "duration_sec": 135,
                "width": 1920,
                "height": 1080,
                "codec_name": "h264",
                "bitrate_kbps": 3000,
                "fps": 60,
            },
        }
        res = await self.executor._execute_tool(
            "inspect_media_metadata",
            {"file_path_or_url": "/tmp/video.mp4"},
        )
        self.mock_document.inspect_media_metadata.assert_awaited_once_with(
            file_path_or_url="/tmp/video.mp4",
        )
        self.assertIn("1920x1080", res)

    async def test_dispatch_download_direct_file(self):
        self.mock_universal_downloader.download_direct_file.return_value = {
            "status": "success",
            "filename": "archive.zip",
            "file_size_formatted": "150 MB",
            "speed_formatted": "12.5 MB/s",
            "elapsed_seconds": 12.0,
            "file_path": "/tmp/archive.zip",
            "resumed": False,
        }
        res = await self.executor._execute_tool(
            "download_direct_file",
            {"url": "https://example.com/archive.zip"},
        )
        self.mock_universal_downloader.download_direct_file.assert_awaited_once_with(
            url="https://example.com/archive.zip",
            custom_filename=None,
        )
        self.assertIn("archive.zip", res)

    async def test_dispatch_extract_clean_web_article(self):
        self.mock_web_extractor.extract_clean_web_article.return_value = {
            "status": "success",
            "title": "Trí tuệ nhân tạo năm 2026",
            "author": "Tech Analyst",
            "publish_date": "2026-09-27",
            "word_count": 1200,
            "reading_time_min": 4,
            "markdown_content": "# Trí tuệ nhân tạo năm 2026\nĐột phá lớn về Agentic AI.",
        }
        res = await self.executor._execute_tool(
            "extract_clean_web_article",
            {"url": "https://example.com/ai-2026"},
        )
        self.mock_web_extractor.extract_clean_web_article.assert_awaited_once_with(
            url="https://example.com/ai-2026",
        )
        self.assertIn("Trí tuệ nhân tạo năm 2026", res)

    async def test_dispatch_manage_docker_containers(self):
        self.mock_system_mastery.manage_docker_containers.return_value = {
            "status": "success",
            "output": "Container dashboard_db restarted.",
        }
        res = await self.executor._execute_tool(
            "manage_docker_containers",
            {"action": "restart", "container_name": "dashboard_db"},
        )
        self.mock_system_mastery.manage_docker_containers.assert_awaited_once_with(
            action="restart",
            container_name="dashboard_db",
            force=False,
        )
        self.assertIn("Container dashboard_db restarted.", res)

    async def test_dispatch_optimize_system_resources(self):
        self.mock_system_mastery.optimize_system_resources.return_value = {
            "status": "success",
            "freed": {"ram_freed_mb": 512, "disk_freed_mb": 1024},
            "after": {"ram_available_mb": 1800, "disk_available_mb": 25000},
            "steps_executed": ["sync && echo 3 > /proc/sys/vm/drop_caches", "docker system prune -f"],
            "execution_time_sec": 1.8,
        }
        res = await self.executor._execute_tool(
            "optimize_system_resources",
            {},
        )
        self.mock_system_mastery.optimize_system_resources.assert_awaited_once_with()
        self.assertIn("1800 MB", res)

    async def test_dispatch_execute_system_script(self):
        self.mock_system_mastery.execute_system_script.return_value = {
            "status": "success",
            "interpreter": "python3",
            "output": "42",
            "exit_code": 0,
            "execution_time_ms": 15,
        }
        res = await self.executor._execute_tool(
            "execute_system_script",
            {"script_code": "print(42)", "interpreter": "python3", "timeout_seconds": 30},
        )
        self.mock_system_mastery.execute_system_script.assert_awaited_once_with(
            script_code="print(42)",
            interpreter="python3",
            timeout=30,
        )
        self.assertIn("42", res)

    async def test_dispatch_run_command_unrestricted_root(self):
        self.mock_ssh.execute_command.return_value = "Linux kirito-server 6.8.0 #1 SMP"
        res = await self.executor._execute_tool("run_command", {"command": "uname -a"})
        self.mock_ssh.execute_command.assert_awaited_once_with("uname -a", unrestricted=True)
        self.assertIn("kirito-server", res)


class TestOmniRiskAndSpinalVeto(unittest.IsolatedAsyncioTestCase):
    """Verifies Action Risk Tri-Tier and Spinal Safety Veto enforcement."""

    def setUp(self):
        self.mock_ssh = AsyncMock()
        self.mock_cache = MagicMock()
        self.mock_system_mastery = AsyncMock()
        self.executor = AgentToolExecutor(
            ssh_client=self.mock_ssh,
            message_cache=self.mock_cache,
            system_mastery_service=self.mock_system_mastery,
        )

    def test_tier_1_safe_classification(self):
        tier1_tools = [
            "edit_video_clip",
            "compress_video",
            "convert_video_format",
            "convert_audio_format",
            "trim_audio_clip",
            "normalize_audio_volume",
            "convert_and_resize_image",
            "generate_custom_qr",
            "merge_pdf_documents",
            "split_pdf_document",
            "extract_document_text",
            "translate_text",
            "inspect_media_metadata",
            "download_direct_file",
            "extract_clean_web_article",
        ]
        for tool_name in tier1_tools:
            risk = classify_action_risk(tool_name, {})
            self.assertEqual(
                risk,
                ACTION_TIER_1_SAFE,
                f"Tool '{tool_name}' must be classified as ACTION_TIER_1_SAFE",
            )

    def test_tier_2_operational_classification(self):
        tier2_tools = ["manage_docker_containers", "optimize_system_resources"]
        for tool_name in tier2_tools:
            risk = classify_action_risk(tool_name, {})
            self.assertIn(
                risk,
                (ACTION_TIER_2_OPERATIONAL, ACTION_TIER_2_REVERSIBLE),
                f"Tool '{tool_name}' must be classified as Tier 2",
            )

        safe_script_risk = classify_action_risk("execute_system_script", {"script_code": "echo 'Hello World'"})
        self.assertIn(
            safe_script_risk,
            (ACTION_TIER_2_OPERATIONAL, ACTION_TIER_2_REVERSIBLE),
            "Safe script_code must be classified as Tier 2",
        )

    def test_tier_3_spinal_veto_classification_and_bypass(self):
        dangerous_codes = [
            "rm -rf /",
            "rm -fr /home/kirito",
            "mkfs.ext4 /dev/sda",
            "dd if=/dev/zero of=/dev/sda",
            "iptables -F",
            "iptables --flush",
        ]
        for dangerous_code in dangerous_codes:
            # Without confirmation: must be ACTION_TIER_3_LETHAL
            risk_unconfirmed = classify_action_risk(
                "execute_system_script",
                {"script_code": dangerous_code},
            )
            self.assertEqual(
                risk_unconfirmed,
                ACTION_TIER_3_LETHAL,
                f"Dangerous code '{dangerous_code}' without confirm must be ACTION_TIER_3_LETHAL",
            )

            # With confirmation: downgrades to Tier 2
            risk_confirmed = classify_action_risk(
                "execute_system_script",
                {"script_code": dangerous_code, "confirm": "CONFIRM_DANGEROUS_ACTION"},
            )
            self.assertIn(
                risk_confirmed,
                (ACTION_TIER_2_OPERATIONAL, ACTION_TIER_2_REVERSIBLE),
                f"Dangerous code '{dangerous_code}' with confirm must downgrade to Tier 2",
            )

    async def test_spinal_veto_execution_blocked(self):
        """execute_system_script with dangerous script_code without confirm must be blocked before calling service."""
        res = await self.executor._execute_tool(
            "execute_system_script",
            {"script_code": "rm -rf /var/data"},
        )
        self.assertIn("SPINAL SAFETY VETO", res)
        self.assertIn("CONFIRM_DANGEROUS_ACTION", res)
        self.mock_system_mastery.execute_system_script.assert_not_called()

    async def test_spinal_veto_execution_confirmed_passes(self):
        """execute_system_script with confirm token passes through to service."""
        self.mock_system_mastery.execute_system_script.return_value = {
            "status": "success",
            "interpreter": "bash",
            "output": "cleaned",
            "exit_code": 0,
            "execution_time_ms": 10,
        }
        res = await self.executor._execute_tool(
            "execute_system_script",
            {"script_code": "rm -rf /tmp/scratch", "confirm": "CONFIRM_DANGEROUS_ACTION"},
        )
        self.mock_system_mastery.execute_system_script.assert_awaited_once_with(
            script_code="rm -rf /tmp/scratch",
            interpreter="bash",
            timeout=60,
        )
        self.assertIn("cleaned", res)


class TestStaticSystemPrefixIntegration(unittest.TestCase):
    """Verifies that _STATIC_SYSTEM_PREFIX contains all 4 protocols and retains its static KV-cache structure."""

    def test_static_system_prefix_has_all_protocols(self):
        prefix = AiAgentService._STATIC_SYSTEM_PREFIX
        self.assertIn("2p. GIAO THỨC PHÒNG THU XỬ LÝ ĐA PHƯƠNG TIỆN", prefix)
        self.assertIn("2q. GIAO THỨC XỬ LÝ TÀI LIỆU SỐ & TRI THỨC CHUYÊN SÂU", prefix)
        self.assertIn("2r. GIAO THỨC KHAI THÁC INTERNET & TẢI TỆP VẠN NĂNG", prefix)
        self.assertIn("2s. GIAO THỨC QUẢN TRỊ HỆ THỐNG TOÀN QUYỀN ROOT", prefix)

    def test_static_system_prefix_tier_updates(self):
        prefix = AiAgentService._STATIC_SYSTEM_PREFIX
        self.assertIn("edit_video_clip", prefix)
        self.assertIn("compress_video", prefix)
        self.assertIn("extract_document_text", prefix)
        self.assertIn("download_direct_file", prefix)
        self.assertIn("extract_clean_web_article", prefix)
        self.assertIn("manage_docker_containers", prefix)
        self.assertIn("execute_system_script", prefix)

    def test_static_system_prefix_invariant(self):
        # Must be pure string without runtime dynamic datetime injection
        prefix = AiAgentService._STATIC_SYSTEM_PREFIX
        self.assertNotIn("Giờ Việt Nam - ICT/UTC+7", prefix)
        self.assertIsInstance(prefix, str)
        self.assertGreater(len(prefix), 5000)


if __name__ == "__main__":
    unittest.main()
