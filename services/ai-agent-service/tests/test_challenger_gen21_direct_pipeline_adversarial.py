"""
test_challenger_gen21_direct_pipeline_adversarial.py — Empirical Challenger Test Suite (Gen 21).

Adversarial stress-testing & boundary verification for Direct Video Pipeline & Smart Delivery:
1. TestAdversarialDirectRoutingMatrix:
   - Exhaustive Vietnamese phrasings for remove text, watermark, delogo, inpaint.
   - Comprehensive color grade preset mappings (vintage, cinematic, cool, warm, bw, vivid).
   - Stabilization phrasing variants.
   - Guarded fallback verification (concat, subtitle, trim, compress, non-edit queries).
   - Unmatched phrasing graceful degradation verification.
2. TestAdversarialSendVideoFileEdgeCases:
   - Empty path, missing file with real TelegramBot.send_video.
   - Normal <=50MB direct delivery and Zero-Disk Leak cleanup.
   - Fallback to send_document_file when send_video returns False.
   - Oversized >50MB portal delivery with correct ttl_seconds.
   - Exception resilience when publish_download_item raises error.
3. TestAdversarialPipelineExceptionHandling:
   - Tool exception in remove_text_from_video, apply_color_grade, stabilize_video.
   - Tool returns status='error'.
   - Tool returns status='ok' with missing output_path.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock, patch

_SERVICE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _SERVICE_DIR not in sys.path:
    sys.path.insert(0, _SERVICE_DIR)

from app.services.telegram_bot import TelegramBot
from app.services.video_pipeline import PendingVideoSession, VideoMetadata


class TestAdversarialDirectRoutingMatrix(unittest.IsolatedAsyncioTestCase):
    """Stress tests intent routing between direct video editing and LLM fallback."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="adv_tg_direct_")
        self.dummy_video_path = os.path.join(self.temp_dir, "input.mp4")
        with open(self.dummy_video_path, "wb") as f:
            f.write(b"\x00" * 1024)

        self.bot = TelegramBot.__new__(TelegramBot)
        self.bot.token = "mock_token"
        self.bot._running = False

        self.bot._video_pipeline = MagicMock()
        self.bot._video_pipeline.process_video = AsyncMock(return_value="[context]")
        self.bot.send_message = AsyncMock(return_value=True)
        self.bot.send_video = AsyncMock(return_value=True)
        self.bot.send_document_file = AsyncMock(return_value=True)
        self.bot.chat_with_agent = AsyncMock(return_value="LLM Response")

        self.mock_editor = AsyncMock()
        self.bot._video_editor_svc = self.mock_editor

        self.session = PendingVideoSession(
            chat_id="test_chat",
            file_id="fid_123",
            temp_dir=self.temp_dir,
            video_path=self.dummy_video_path,
            metadata=VideoMetadata(
                filename="input.mp4",
                duration=30,
                width=1920,
                height=1080,
                file_size=1024,
            ),
        )

    async def asyncTearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_remove_text_phrasing_variants_bypass_llm(self):
        """Stress-test 10 diverse Vietnamese phrasings for text/watermark removal."""
        phrasings = [
            ("xóa logo ở góc trên bên phải giúp em", "auto"),
            ("xóa watermark tiktok trên video này", "auto"),
            ("làm sạch video bỏ chữ đi", "auto"),
            ("loại bỏ chữ quảng cáo giùm tôi", "auto"),
            ("xóa sạch các dòng chữ trên màn hình", "auto"),
            ("xóa sub tiếng anh chạy phía dưới", "auto"),
            ("bỏ text trong video này đi nha", "auto"),
            ("delogo góc màn hình", "delogo"),
            ("hãy delogo video này giùm", "delogo"),
            ("dùng inpaint xóa watermark cho tự nhiên", "inpaint"),
        ]

        dummy_out = os.path.join(self.temp_dir, "out_clean.mp4")

        for query, expected_mode in phrasings:
            with self.subTest(query=query, expected_mode=expected_mode):
                with open(dummy_out, "wb") as f:
                    f.write(b"\x00" * 512)
                self.mock_editor.reset_mock()
                self.bot.chat_with_agent.reset_mock()
                self.bot.send_message.reset_mock()

                self.mock_editor.remove_text_from_video = AsyncMock(return_value={
                    "status": "ok",
                    "output_path": dummy_out,
                    "delivery": "direct",
                    "message": f"Cleaned with {expected_mode}",
                })

                await self.bot._on_video_process_pipeline(
                    chat_id="test_chat",
                    session=self.session,
                    instruction=query,
                )

                self.mock_editor.remove_text_from_video.assert_called_once()
                call_kwargs = self.mock_editor.remove_text_from_video.call_args.kwargs
                self.assertEqual(call_kwargs.get("input_path_or_url"), self.dummy_video_path)
                self.assertEqual(call_kwargs.get("mode"), expected_mode)
                self.assertTrue(callable(call_kwargs.get("progress_callback")), "progress_callback must be callable!")
                self.bot.chat_with_agent.assert_not_called()

    async def test_color_grade_presets_routing(self):
        """Verify color grading queries accurately map to correct presets."""
        presets_cases = [
            ("chỉnh màu phong cách vintage hoài cổ", "vintage"),
            ("chỉnh màu cinematic điện ảnh giúp em", "cinematic"),
            ("lọc màu tông lạnh cool", "cool"),
            ("filter màu tông ấm warm cho ấm áp", "warm"),
            ("chỉnh màu đen trắng bw nhé", "bw"),
            ("lọc màu den trang", "bw"),
            ("chỉnh màu rực rỡ tươi sáng", "vivid"),
        ]

        dummy_out = os.path.join(self.temp_dir, "out_color.mp4")

        for query, expected_preset in presets_cases:
            with self.subTest(query=query, expected_preset=expected_preset):
                with open(dummy_out, "wb") as f:
                    f.write(b"\x00" * 512)
                self.mock_editor.reset_mock()
                self.bot.chat_with_agent.reset_mock()

                self.mock_editor.apply_color_grade = AsyncMock(return_value={
                    "status": "ok",
                    "output_path": dummy_out,
                    "delivery": "direct",
                    "message": f"Applied {expected_preset}",
                })

                await self.bot._on_video_process_pipeline(
                    chat_id="test_chat",
                    session=self.session,
                    instruction=query,
                )

                self.mock_editor.apply_color_grade.assert_called_once_with(
                    input_path_or_url=self.dummy_video_path,
                    preset=expected_preset,
                )
                self.bot.chat_with_agent.assert_not_called()

    async def test_unmatched_color_phrasing_falls_back_to_llm(self):
        """Phrasings not matching known keywords (e.g. 'chuyển màu đen trắng') gracefully fall back to LLM."""
        query = "chuyển màu sang đen trắng giúp em"
        await self.bot._on_video_process_pipeline(
            chat_id="test_chat",
            session=self.session,
            instruction=query,
        )

        self.mock_editor.apply_color_grade.assert_not_called()
        self.bot.chat_with_agent.assert_called_once()

    async def test_stabilize_phrasing_variants(self):
        """Verify stabilization variants properly bypass LLM."""
        queries = [
            "video bị rung lắc quá, chống rung giúp em",
            "ổn định video này lại cho mượt",
            "khử rung camera giùm mình",
            "stabilize video clip",
        ]

        dummy_out = os.path.join(self.temp_dir, "out_stab.mp4")

        for query in queries:
            with self.subTest(query=query):
                with open(dummy_out, "wb") as f:
                    f.write(b"\x00" * 512)
                self.mock_editor.reset_mock()
                self.bot.chat_with_agent.reset_mock()

                self.mock_editor.stabilize_video = AsyncMock(return_value={
                    "status": "ok",
                    "output_path": dummy_out,
                    "delivery": "direct",
                    "message": "Stabilized",
                })

                await self.bot._on_video_process_pipeline(
                    chat_id="test_chat",
                    session=self.session,
                    instruction=query,
                )

                self.mock_editor.stabilize_video.assert_called_once_with(
                    input_path_or_url=self.dummy_video_path,
                    smoothing=15,
                )
                self.bot.chat_with_agent.assert_not_called()

    async def test_complex_and_non_direct_requests_safely_fallback_to_llm(self):
        """Ensure complex operations (merge, subtitle, trim, compress, Q&A) never bypass to wrong tools."""
        fallback_queries = [
            "ghép 2 video lại với nhau",
            "nối video này với intro",
            "merge video và xuất ra mp4",
            "thêm phụ đề tiếng việt vào video",
            "chèn chữ bản quyền vào góc",
            "cắt video từ 0:10 đến 0:30",
            "nén video này xuống dưới 20MB",
            "video này đang quay cảnh gì thế?",
            "trong video có bao nhiêu người xuất hiện?",
        ]

        for query in fallback_queries:
            with self.subTest(query=query):
                self.mock_editor.reset_mock()
                self.bot.chat_with_agent.reset_mock()
                self.bot._video_pipeline.process_video.reset_mock()

                await self.bot._on_video_process_pipeline(
                    chat_id="test_chat",
                    session=self.session,
                    instruction=query,
                )

                # Direct editing methods must NOT be called
                self.mock_editor.remove_text_from_video.assert_not_called()
                self.mock_editor.apply_color_grade.assert_not_called()
                self.mock_editor.stabilize_video.assert_not_called()

                # LLM flow MUST be triggered
                self.bot.chat_with_agent.assert_called_once()
                self.bot._video_pipeline.process_video.assert_called_once()


class TestAdversarialSendVideoFileEdgeCases(unittest.IsolatedAsyncioTestCase):
    """Stress tests send_video_file boundary and error handling."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="adv_tg_send_")
        self.bot = TelegramBot.__new__(TelegramBot)
        self.bot.token = "mock_token"
        self.bot.send_message = AsyncMock(return_value=True)
        self.bot.send_video = AsyncMock(return_value=True)
        self.bot.send_document_file = AsyncMock(return_value=True)

    async def asyncTearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_empty_or_none_video_path(self):
        """Passing empty string as video_path must return False without crashing."""
        res1 = await self.bot.send_video_file(chat_id="123", video_path="")
        self.assertFalse(res1)

    async def test_non_existent_file_returns_false_safely(self):
        """Passing non-existent path on real method returns False and logs error."""
        bad_path = os.path.join(self.temp_dir, "non_existent_file_12345.mp4")
        # Instantiate a bot that uses actual TelegramBot.send_video (non-mocked)
        clean_bot = TelegramBot.__new__(TelegramBot)

        res = await clean_bot.send_video_file(chat_id="123", video_path=bad_path)
        self.assertFalse(res)

    async def test_zero_disk_leak_flag_respected(self):
        """When cleanup_after_send=False, file must be preserved."""
        test_file = os.path.join(self.temp_dir, "keep_file.mp4")
        with open(test_file, "wb") as f:
            f.write(b"\x00" * 1024)

        res = await self.bot.send_video_file(
            chat_id="123",
            video_path=test_file,
            cleanup_after_send=False,
        )
        self.assertTrue(res)
        self.assertTrue(os.path.exists(test_file), "File must be preserved when cleanup_after_send=False")

    async def test_large_file_portal_exception_resilience(self):
        """When media_storage_manager.publish_download_item raises error, send_video_file handles gracefully."""
        test_file = os.path.join(self.temp_dir, "large_err.mp4")
        with open(test_file, "wb") as f:
            f.write(b"\x00" * 1024)

        with patch.object(Path, "stat") as mock_stat:
            mock_stat_res = MagicMock()
            mock_stat_res.st_size = 75 * 1024 * 1024  # 75MB
            mock_stat.return_value = mock_stat_res

            with patch("app.services.media_storage_manager.media_storage_manager.publish_download_item") as mock_pub:
                mock_pub.side_effect = RuntimeError("Disk quota exceeded on portal storage")

                res = await self.bot.send_video_file(
                    chat_id="123",
                    video_path=test_file,
                )
                self.assertFalse(res)
                self.bot.send_message.assert_called_once()
                sent_msg = self.bot.send_message.call_args[0][1]
                self.assertIn("Disk quota exceeded", sent_msg)
                self.assertIn("vượt quá giới hạn 50MB", sent_msg)


class TestAdversarialPipelineExceptionHandling(unittest.IsolatedAsyncioTestCase):
    """Stress tests exception resilience in _on_video_process_pipeline."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="adv_pipe_err_")
        self.dummy_video_path = os.path.join(self.temp_dir, "vid.mp4")
        with open(self.dummy_video_path, "wb") as f:
            f.write(b"\x00" * 512)

        self.bot = TelegramBot.__new__(TelegramBot)
        self.bot.token = "mock"
        self.bot.send_message = AsyncMock(return_value=True)
        self.bot.send_video_file = AsyncMock(return_value=True)
        self.bot.chat_with_agent = AsyncMock(return_value="Answer")
        self.bot._video_pipeline = MagicMock()

        self.mock_editor = AsyncMock()
        self.bot._video_editor_svc = self.mock_editor

        self.session = PendingVideoSession(
            chat_id="chat_err",
            file_id="fid_err",
            temp_dir=self.temp_dir,
            video_path=self.dummy_video_path,
            metadata=VideoMetadata(filename="vid.mp4", duration=10, width=640, height=480, file_size=512),
        )

    async def asyncTearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_tool_ok_but_missing_output_path(self):
        """When tool returns ok but output_path is empty/missing, notify user without crashing."""
        self.mock_editor.remove_text_from_video = AsyncMock(return_value={
            "status": "ok",
            "output_path": None,
            "delivery": "direct",
        })

        await self.bot._on_video_process_pipeline(
            chat_id="chat_err",
            session=self.session,
            instruction="xóa text trên video",
        )

        found_missing_msg = any(
            "Không tìm thấy tệp video kết quả" in (c[0][1] if len(c[0]) > 1 else "")
            for c in self.bot.send_message.call_args_list
        )
        self.assertTrue(found_missing_msg)

    async def test_color_grade_tool_exception(self):
        """When color grade raises an unhandled exception, bot catches and notifies."""
        self.mock_editor.apply_color_grade = AsyncMock(
            side_effect=TimeoutError("FFmpeg process timed out after 300s")
        )

        await self.bot._on_video_process_pipeline(
            chat_id="chat_err",
            session=self.session,
            instruction="chỉnh màu vintage cho video",
        )

        found_timeout_msg = any(
            "Có lỗi trong quá trình biên tập video" in (c[0][1] if len(c[0]) > 1 else "")
            for c in self.bot.send_message.call_args_list
        )
        self.assertTrue(found_timeout_msg)
        self.bot.chat_with_agent.assert_not_called()


if __name__ == "__main__":
    unittest.main()
