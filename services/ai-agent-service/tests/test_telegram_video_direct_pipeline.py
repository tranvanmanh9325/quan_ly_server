"""
Unit tests for Direct Video Pipeline and Smart Delivery in TelegramBot.
Verifies:
1. Lazy property `_video_editor_service` initializes on-demand and caches the instance.
2. Video edit intent (remove text auto) bypasses LLM and executes remove_text_from_video directly.
3. Video edit intent with explicit 'delogo' keyword passes mode='delogo'.
4. Video edit intent (color grading) bypasses LLM and executes apply_color_grade directly with matching preset.
5. Video edit intent (stabilization) bypasses LLM and executes stabilize_video directly.
6. Complex edit request (concatenation) gracefully falls back to LLM flow.
7. Subtitle edit request without subtitle content falls back to LLM flow.
8. Non-edit video request (summarize) runs standard video pipeline and calls LLM.
9. Oversized video output (>50MB) delivers via portal storage link without calling send_video.
10. Video editor tool failures and exceptions are gracefully handled without crashing bot loop.
"""

import asyncio
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock, patch

# Ensure app is in path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.telegram_bot import TelegramBot
from app.services.video_pipeline import (
    PendingVideoSession,
    VideoMetadata,
)
import app.services.video_editor_service


class TestTelegramVideoDirectPipeline(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_tg_direct_pipeline_")
        self.dummy_video_path = os.path.join(self.temp_dir, "input_video.mp4")
        with open(self.dummy_video_path, "wb") as f:
            f.write(b"\x00" * 2048)

        # Build TelegramBot instance without executing heavy __init__
        self.bot = TelegramBot.__new__(TelegramBot)
        self.bot.token = "mock_token"
        self.bot._running = False

        # Mock dependencies
        self.bot._video_pipeline = MagicMock()
        self.bot._video_pipeline.process_video = AsyncMock(return_value="[mock context: transcript and vision]")
        self.bot.send_message = AsyncMock(return_value=True)
        self.bot.send_video = AsyncMock(return_value=True)
        self.bot.send_document_file = AsyncMock(return_value=True)
        self.bot.chat_with_agent = AsyncMock(return_value="Mock LLM Answer")

        # Mock VideoEditorService
        self.mock_editor = AsyncMock()
        self.bot._video_editor_svc = self.mock_editor

        self.session = PendingVideoSession(
            chat_id="12345",
            file_id="fid_999",
            temp_dir=self.temp_dir,
            video_path=self.dummy_video_path,
            metadata=VideoMetadata(
                filename="input_video.mp4",
                duration=45,
                width=1280,
                height=720,
                file_size=2048,
            ),
        )

    async def asyncTearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_telegram_bot_lazy_video_editor_service_property(self):
        """Test 1: _video_editor_service property lazily instantiates VideoEditorService and caches it."""
        fresh_bot = TelegramBot.__new__(TelegramBot)
        fresh_bot._video_editor_svc = None

        with patch("app.services.video_editor_service.VideoEditorService") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance

            # First access creates instance
            svc1 = fresh_bot._video_editor_service
            self.assertEqual(mock_cls.call_count, 1)
            self.assertIs(svc1, mock_instance)

            # Second access returns cached instance
            svc2 = fresh_bot._video_editor_service
            self.assertEqual(mock_cls.call_count, 1)
            self.assertIs(svc1, svc2)

    async def test_video_pipeline_bypasses_llm_and_executes_remove_text_auto(self):
        """Test 2: Instruction 'xóa sạch text trong video giúp tôi' calls remove_text_from_video mode='auto' and bypasses LLM."""
        clean_output = os.path.join(self.temp_dir, "clean_video.mp4")
        with open(clean_output, "wb") as f:
            f.write(b"\x00" * 4096)

        self.mock_editor.remove_text_from_video = AsyncMock(return_value={
            "status": "ok",
            "tool": "remove_text_from_video",
            "mode_used": "delogo",
            "output_path": clean_output,
            "delivery": "direct",
            "message": "Đã xóa text thành công",
        })

        instruction = "xóa sạch text trong video giúp tôi"
        await self.bot._on_video_process_pipeline(
            chat_id="12345",
            session=self.session,
            instruction=instruction,
        )

        # VideoEditorService was called with mode='auto'
        self.mock_editor.remove_text_from_video.assert_called_once_with(
            input_path_or_url=self.dummy_video_path,
            mode="auto",
            progress_callback=ANY,
        )
        # LLM was NOT called
        self.bot.chat_with_agent.assert_not_called()
        self.bot._video_pipeline.process_video.assert_not_called()
        # Direct video delivery occurred
        self.bot.send_video.assert_called_once()
        call_args, call_kwargs = self.bot.send_video.call_args
        self.assertEqual(call_kwargs.get("chat_id") or call_args[0], "12345")
        self.assertIn("clean_video.mp4", str(call_kwargs.get("video_path") or call_args[1]))

    async def test_video_pipeline_delogo_mode_explicit(self):
        """Test 3: Instruction containing 'delogo' passes mode='delogo' to remove_text_from_video."""
        clean_output = os.path.join(self.temp_dir, "delogo_out.mp4")
        with open(clean_output, "wb") as f:
            f.write(b"\x00" * 1024)

        self.mock_editor.remove_text_from_video = AsyncMock(return_value={
            "status": "ok",
            "output_path": clean_output,
            "delivery": "direct",
            "message": "Đã delogo thành công",
        })

        await self.bot._on_video_process_pipeline(
            chat_id="12345",
            session=self.session,
            instruction="delogo video này giùm em",
        )

        self.mock_editor.remove_text_from_video.assert_called_once_with(
            input_path_or_url=self.dummy_video_path,
            mode="delogo",
            progress_callback=ANY,
        )
        self.bot.chat_with_agent.assert_not_called()

    async def test_video_pipeline_bypasses_llm_and_executes_apply_color_grade(self):
        """Test 4: Instruction 'chỉnh màu video vintage hoài cổ' calls apply_color_grade preset='vintage' and bypasses LLM."""
        color_output = os.path.join(self.temp_dir, "color_out.mp4")
        with open(color_output, "wb") as f:
            f.write(b"\x00" * 1024)

        self.mock_editor.apply_color_grade = AsyncMock(return_value={
            "status": "ok",
            "output_path": color_output,
            "delivery": "direct",
            "message": "Đã áp dụng bộ lọc màu vintage",
        })

        await self.bot._on_video_process_pipeline(
            chat_id="12345",
            session=self.session,
            instruction="chỉnh màu video vintage hoài cổ",
        )

        self.mock_editor.apply_color_grade.assert_called_once_with(
            input_path_or_url=self.dummy_video_path,
            preset="vintage",
        )
        self.bot.chat_with_agent.assert_not_called()
        self.bot.send_video.assert_called_once()

    async def test_video_pipeline_bypasses_llm_and_executes_stabilize_video(self):
        """Test 5: Instruction 'ổn định video bị rung camera này' calls stabilize_video and bypasses LLM."""
        stab_output = os.path.join(self.temp_dir, "stab_out.mp4")
        with open(stab_output, "wb") as f:
            f.write(b"\x00" * 1024)

        self.mock_editor.stabilize_video = AsyncMock(return_value={
            "status": "ok",
            "output_path": stab_output,
            "delivery": "direct",
            "message": "Đã khử rung thành công",
        })

        await self.bot._on_video_process_pipeline(
            chat_id="12345",
            session=self.session,
            instruction="ổn định video bị rung camera này",
        )

        self.mock_editor.stabilize_video.assert_called_once_with(
            input_path_or_url=self.dummy_video_path,
            smoothing=15,
        )
        self.bot.chat_with_agent.assert_not_called()
        self.bot.send_video.assert_called_once()

    async def test_video_pipeline_falls_back_to_llm_for_complex_concat(self):
        """Test 6: Complex multi-file instruction 'ghép 2 video này lại thành một' falls back to LLM."""
        await self.bot._on_video_process_pipeline(
            chat_id="12345",
            session=self.session,
            instruction="ghép 2 video này lại thành một",
        )

        # Editor direct tools must NOT be invoked
        self.mock_editor.remove_text_from_video.assert_not_called()
        self.mock_editor.apply_color_grade.assert_not_called()
        self.mock_editor.stabilize_video.assert_not_called()

        # LLM flow MUST be invoked
        self.bot._video_pipeline.process_video.assert_called_once()
        self.bot.chat_with_agent.assert_called_once()

    async def test_video_pipeline_falls_back_to_llm_for_subtitles_without_text(self):
        """Test 7: Subtitle instruction 'thêm phụ đề tiếng việt vào video' falls back to LLM."""
        await self.bot._on_video_process_pipeline(
            chat_id="12345",
            session=self.session,
            instruction="thêm phụ đề tiếng việt vào video",
        )

        self.mock_editor.remove_text_from_video.assert_not_called()
        self.bot._video_pipeline.process_video.assert_called_once()
        self.bot.chat_with_agent.assert_called_once()

    async def test_video_pipeline_falls_back_to_llm_for_summarize_intent(self):
        """Test 8: Non-edit instruction 'tóm tắt nội dung video này' calls LLM as normal."""
        await self.bot._on_video_process_pipeline(
            chat_id="12345",
            session=self.session,
            instruction="tóm tắt nội dung video này",
        )

        self.mock_editor.remove_text_from_video.assert_not_called()
        self.mock_editor.apply_color_grade.assert_not_called()
        self.mock_editor.stabilize_video.assert_not_called()
        self.bot._video_pipeline.process_video.assert_called_once()
        self.bot.chat_with_agent.assert_called_once()

    async def test_video_pipeline_large_file_portal_delivery(self):
        """Test 9: When video editor returns portal delivery (>50MB), send portal download link instead of send_video."""
        self.mock_editor.remove_text_from_video = AsyncMock(return_value={
            "status": "ok",
            "tool": "remove_text_from_video",
            "delivery": "portal",
            "file_size_formatted": "68.2 MB",
            "internet_url": "https://ngrok.example.com/download/large_video.mp4",
            "lan_url": "http://192.168.1.10:8084/download/large_video.mp4",
            "message": "Đã xóa logo thành công",
        })

        await self.bot._on_video_process_pipeline(
            chat_id="12345",
            session=self.session,
            instruction="xóa logo trong video",
        )

        # send_video MUST NOT be called because file exceeds 50MB
        self.bot.send_video.assert_not_called()

        # send_message MUST contain both URLs and file size
        found_portal_msg = False
        for call_item in self.bot.send_message.call_args_list:
            text = call_item[0][1] if len(call_item[0]) > 1 else call_item[1].get("text", "")
            if "https://ngrok.example.com/download/large_video.mp4" in text:
                found_portal_msg = True
                self.assertIn("http://192.168.1.10:8084/download/large_video.mp4", text)
                self.assertIn("68.2 MB", text)
                break

        self.assertTrue(found_portal_msg, "Portal download links must be delivered to chat via send_message")

    async def test_video_pipeline_tool_error_graceful_recovery(self):
        """Test 10: Graceful recovery and Vietnamese error message when VideoEditorService raises exception or error."""
        # 10a: VideoEditorService raises an exception
        self.mock_editor.remove_text_from_video = AsyncMock(
            side_effect=RuntimeError("FFmpeg delogo filter crashed")
        )

        await self.bot._on_video_process_pipeline(
            chat_id="12345",
            session=self.session,
            instruction="xóa text trên video",
        )

        # Bot does not crash, sends polite error message
        found_err = False
        for call_item in self.bot.send_message.call_args_list:
            text = call_item[0][1] if len(call_item[0]) > 1 else call_item[1].get("text", "")
            if "Có lỗi trong quá trình biên tập video" in text:
                found_err = True
                break
        self.assertTrue(found_err, "Polite Vietnamese error notification must be sent on exception")
        self.bot.chat_with_agent.assert_not_called()

        # 10b: VideoEditorService returns status='error'
        self.bot.send_message.reset_mock()
        self.mock_editor.remove_text_from_video = AsyncMock(return_value={
            "status": "error",
            "message": "Không tìm thấy vùng text hợp lệ",
        })

        await self.bot._on_video_process_pipeline(
            chat_id="12345",
            session=self.session,
            instruction="xóa text trên video",
        )

        found_err_status = False
        for call_item in self.bot.send_message.call_args_list:
            text = call_item[0][1] if len(call_item[0]) > 1 else call_item[1].get("text", "")
            if "Không thể hoàn thành biên tập video" in text or "Không tìm thấy vùng text hợp lệ" in text:
                found_err_status = True
                break
        self.assertTrue(found_err_status, "Status='error' must be communicated clearly to user")

    async def test_send_video_file_under_50mb_direct_and_cleans_up(self):
        """Test 11: send_video_file with file <= 50MB calls send_video and unlinks temporary file."""
        test_file = os.path.join(self.temp_dir, "test_send_direct.mp4")
        with open(test_file, "wb") as f:
            f.write(b"\x00" * 1024)

        self.assertTrue(os.path.exists(test_file))
        res = await self.bot.send_video_file(
            chat_id="12345",
            video_path=test_file,
            caption="Direct delivery test",
            cleanup_after_send=True,
        )

        self.assertTrue(res)
        self.bot.send_video.assert_called_once()
        # Verify Zero-Disk Leak: file was deleted after transmission
        self.assertFalse(os.path.exists(test_file), "Transient file must be unlinked after sending")

    async def test_send_video_file_under_50mb_fallback_document(self):
        """Test 12: send_video_file falls back to send_document_file when send_video returns False."""
        test_file = os.path.join(self.temp_dir, "test_fallback_doc.mp4")
        with open(test_file, "wb") as f:
            f.write(b"\x00" * 1024)

        self.bot.send_video = AsyncMock(return_value=False)
        self.bot.send_document_file = AsyncMock(return_value=True)

        res = await self.bot.send_video_file(
            chat_id="12345",
            video_path=test_file,
            caption="Fallback doc test",
            cleanup_after_send=True,
        )

        self.assertTrue(res)
        self.bot.send_video.assert_called_once()
        self.bot.send_document_file.assert_called_once()
        self.assertFalse(os.path.exists(test_file), "Transient file must be unlinked after fallback sending")

    async def test_send_video_file_over_50mb_publishes_portal(self):
        """Test 13: send_video_file with file > 50MB publishes to media_storage_manager with ttl_seconds."""
        test_file = os.path.join(self.temp_dir, "large_file.mp4")
        with open(test_file, "wb") as f:
            f.write(b"\x00" * 1024)

        # Mock stat().st_size to pretend it is 60MB
        with patch.object(Path, "stat") as mock_stat:
            mock_stat_res = MagicMock()
            mock_stat_res.st_size = 60 * 1024 * 1024
            mock_stat.return_value = mock_stat_res

            with patch("app.services.media_storage_manager.media_storage_manager.publish_download_item") as mock_pub:
                mock_rec = MagicMock()
                mock_rec.internet_url = "https://ngrok.example.com/large_file.mp4"
                mock_rec.lan_url = "http://192.168.1.10:8084/large_file.mp4"
                mock_pub.return_value = mock_rec

                res = await self.bot.send_video_file(
                    chat_id="12345",
                    video_path=test_file,
                    caption="Large portal test",
                )

                self.assertTrue(res)
                mock_pub.assert_called_once()
                call_kwargs = mock_pub.call_args[1]
                self.assertEqual(call_kwargs.get("ttl_seconds"), 4 * 3600)
                self.bot.send_video.assert_not_called()
                self.bot.send_message.assert_called_once()
                sent_text = self.bot.send_message.call_args[0][1]
                self.assertIn("https://ngrok.example.com/large_file.mp4", sent_text)
                self.assertIn("http://192.168.1.10:8084/large_file.mp4", sent_text)


if __name__ == "__main__":
    unittest.main()
