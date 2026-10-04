"""
Empirical Verification Test Suite by Challenger 2 (Empirical Pipeline Execution & Zero-Disk Leak Verifier).
Directly tests:
1. _on_video_process_pipeline():
   - 'xóa sạch text trong video giúp tôi' -> LLM NOT CALLED (0 calls), remove_text_from_video CALLED (1 call, mode='auto').
   - Adversarial variations (case sensitivity, whitespace, delogo, inpaint, fallback to LLM on complex/subtitles/summarize).
2. send_video_file:
   - File <= 50MB: sent via send_video and unlinked on disk (Zero-Disk Leak verification on real filesystem).
   - File <= 50MB fallback: sent via send_document_file and unlinked on disk.
   - File <= 50MB with cleanup_after_send=False: retained on disk.
   - File > 50MB: activates portal link, calls publish_download_item with ttl_seconds, sends WAN/LAN links.
   - Non-existent file: returns False on real bot instance.
3. video_editor_service.py:274 ttl_seconds:
   - _publish_or_direct with file > 50MB calls storage.publish_download_item with ttl_seconds without TypeError.
   - Live execution with MediaStorageManager instance.
"""

import asyncio
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock, patch

# Ensure app is on path
APP_ROOT = Path(__file__).resolve().parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.services.telegram_bot import TelegramBot
from app.services.video_pipeline import PendingVideoSession, VideoMetadata
from app.services.video_editor_service import VideoEditorService
from app.services.media_storage_manager import MediaStorageManager


class TestEmpiricalChallengerGen21Pipeline(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="challenger2_empirical_")
        self.dummy_video_path = os.path.join(self.temp_dir, "test_input_video.mp4")
        with open(self.dummy_video_path, "wb") as f:
            f.write(b"\x00" * 4096)

        # TelegramBot stub
        self.bot = TelegramBot.__new__(TelegramBot)
        self.bot.token = "fake_test_token"
        self.bot._running = False

        self.bot._video_pipeline = MagicMock()
        self.bot._video_pipeline.process_video = AsyncMock(return_value="[MOCK PIPELINE CONTEXT]")
        self.bot.send_message = AsyncMock(return_value=True)
        self.bot.send_video = AsyncMock(return_value=True)
        self.bot.send_document_file = AsyncMock(return_value=True)
        self.bot.chat_with_agent = AsyncMock(return_value="MOCK LLM RESPONSE")

        self.mock_editor = AsyncMock()
        self.bot._video_editor_svc = self.mock_editor

        self.session = PendingVideoSession(
            chat_id="chat_777",
            file_id="file_777",
            temp_dir=self.temp_dir,
            video_path=self.dummy_video_path,
            metadata=VideoMetadata(
                filename="test_input_video.mp4",
                duration=30,
                width=1920,
                height=1080,
                file_size=4096,
            ),
        )

    async def asyncTearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    # =========================================================================
    # ITEM 1: Pipeline Execution & LLM Bypass Verification
    # =========================================================================
    async def test_item1_exact_instruction_xoa_sach_text_bypasses_llm(self):
        """
        MANDATORY VERIFICATION:
        Instruction: 'xóa sạch text trong video giúp tôi'
        Must:
        1. LLM (chat_with_agent) is NEVER called (0 calls).
        2. _video_pipeline.process_video is NEVER called (0 calls).
        3. remove_text_from_video is CALLED EXACTLY ONCE with mode='auto'.
        4. input_path_or_url is exact session.video_path.
        5. User receives status progress message and final video via send_video_file.
        """
        output_video = os.path.join(self.temp_dir, "output_clean.mp4")
        with open(output_video, "wb") as f:
            f.write(b"\x00" * 8192)

        self.mock_editor.remove_text_from_video = AsyncMock(return_value={
            "status": "ok",
            "tool": "remove_text_from_video",
            "mode_used": "auto",
            "output_path": output_video,
            "delivery": "direct",
            "message": "Đã xóa sạch text khỏi video thành công",
        })

        exact_instruction = "xóa sạch text trong video giúp tôi"
        await self.bot._on_video_process_pipeline(
            chat_id="chat_777",
            session=self.session,
            instruction=exact_instruction,
        )

        # 1. CRITICAL CHECK: LLM was NEVER called!
        self.bot.chat_with_agent.assert_not_called()
        self.assertEqual(self.bot.chat_with_agent.call_count, 0, "LLM must NOT be called for text removal!")

        # 2. CRITICAL CHECK: process_video was NEVER called!
        self.bot._video_pipeline.process_video.assert_not_called()
        self.assertEqual(self.bot._video_pipeline.process_video.call_count, 0)

        # 3. CRITICAL CHECK: remove_text_from_video called EXACTLY ONCE with mode='auto'
        self.mock_editor.remove_text_from_video.assert_called_once()
        call_kwargs = self.mock_editor.remove_text_from_video.call_args.kwargs
        self.assertEqual(call_kwargs.get("input_path_or_url"), self.dummy_video_path)
        self.assertEqual(call_kwargs.get("mode"), "auto")
        self.assertTrue(callable(call_kwargs.get("progress_callback")), "progress_callback must be callable!")

        # 4. Progress message was sent
        progress_sent = any(
            "Đang tự động xóa text/watermark" in str(call[0][1] if len(call[0]) > 1 else call[1].get("text", ""))
            for call in self.bot.send_message.call_args_list
        )
        self.assertTrue(progress_sent, "Progress message must be notified to user")

        # 5. Result delivered via send_video
        self.bot.send_video.assert_called_once()
        sent_path = str(self.bot.send_video.call_args[1].get("video_path") or self.bot.send_video.call_args[0][1])
        self.assertIn("output_clean.mp4", sent_path)

    async def test_item1_adversarial_case_insensitivity_and_whitespace(self):
        """Adversarial: uppercase, messy whitespace, punctuation around 'xóa sạch text'."""
        output_video = os.path.join(self.temp_dir, "output_upper.mp4")
        with open(output_video, "wb") as f:
            f.write(b"\x00" * 1024)

        self.mock_editor.remove_text_from_video = AsyncMock(return_value={
            "status": "ok",
            "output_path": output_video,
            "delivery": "direct",
            "message": "ok",
        })

        instructions = [
            "   XÓA SẠCH TEXT TRONG VIDEO GIÚP TÔI   ",
            "xóa sạch text trong video giúp tôi!!!",
            "nhờ bot xóa sạch text ở video này",
            "Xóa Sạch Chữ trong video",
            "XÓA SẠCH WATERMARK",
        ]

        for instr in instructions:
            self.mock_editor.remove_text_from_video.reset_mock()
            self.bot.chat_with_agent.reset_mock()
            self.bot._video_pipeline.process_video.reset_mock()
            self.bot.send_video.reset_mock()

            # Ensure file exists for each iteration
            with open(output_video, "wb") as f:
                f.write(b"\x00" * 1024)

            await self.bot._on_video_process_pipeline(
                chat_id="chat_777",
                session=self.session,
                instruction=instr,
            )

            self.bot.chat_with_agent.assert_not_called()
            self.bot._video_pipeline.process_video.assert_not_called()
            self.mock_editor.remove_text_from_video.assert_called_once()
            self.assertEqual(self.mock_editor.remove_text_from_video.call_args.kwargs["mode"], "auto")

    async def test_item1_mode_selection_delogo_and_inpaint(self):
        """Mode selection: explicit delogo or inpaint keyword in prompt."""
        output_video = os.path.join(self.temp_dir, "output_mode.mp4")
        with open(output_video, "wb") as f:
            f.write(b"\x00" * 1024)

        self.mock_editor.remove_text_from_video = AsyncMock(return_value={
            "status": "ok",
            "output_path": output_video,
            "delivery": "direct",
        })

        # Delogo mode
        await self.bot._on_video_process_pipeline(
            chat_id="chat_777",
            session=self.session,
            instruction="xóa text bằng delogo filter giúp tôi",
        )
        self.assertEqual(self.mock_editor.remove_text_from_video.call_args.kwargs["mode"], "delogo")
        self.bot.chat_with_agent.assert_not_called()

        # Inpaint mode
        with open(output_video, "wb") as f:
            f.write(b"\x00" * 1024)
        self.mock_editor.remove_text_from_video.reset_mock()
        await self.bot._on_video_process_pipeline(
            chat_id="chat_777",
            session=self.session,
            instruction="xóa sạch text bằng phương pháp inpaint nhé",
        )
        self.assertEqual(self.mock_editor.remove_text_from_video.call_args.kwargs["mode"], "inpaint")
        self.bot.chat_with_agent.assert_not_called()

    async def test_item1_complex_operations_fallback_to_llm(self):
        """Complex operations like 'ghép video' or 'thêm phụ đề' must fallback to LLM."""
        complex_prompts = [
            "ghép video này với video khác và xóa sạch text",
            "nối video lại giùm tôi",
            "thêm phụ đề tiếng Việt vào video này",
            "chèn chữ Bản quyền Mạnh Kirito vào góc",
        ]

        for prompt in complex_prompts:
            self.mock_editor.remove_text_from_video.reset_mock()
            self.bot.chat_with_agent.reset_mock()
            self.bot._video_pipeline.process_video.reset_mock()

            await self.bot._on_video_process_pipeline(
                chat_id="chat_777",
                session=self.session,
                instruction=prompt,
            )

            # Must NOT call remove_text_from_video directly
            self.mock_editor.remove_text_from_video.assert_not_called()
            # MUST invoke LLM and pipeline
            self.bot._video_pipeline.process_video.assert_called_once()
            self.bot.chat_with_agent.assert_called_once()

    # =========================================================================
    # ITEM 2: Smart Delivery & Zero-Disk Leak Verification
    # =========================================================================
    async def test_item2_send_video_file_under_50mb_unlinks_on_real_disk(self):
        """
        REAL DISK VERIFICATION:
        File <= 50MB sent directly:
        - Must be sent via send_video.
        - Must be physically removed (unlinked) from filesystem (Zero-Disk Leak).
        """
        real_video_file = os.path.join(self.temp_dir, "real_transient_output.mp4")
        with open(real_video_file, "wb") as f:
            f.write(b"REAL_VIDEO_PAYLOAD" * 1024)  # ~18KB file

        self.assertTrue(os.path.exists(real_video_file), "File must exist before send")

        sent = await self.bot.send_video_file(
            chat_id="chat_777",
            video_path=real_video_file,
            caption="Empirical verification direct",
            cleanup_after_send=True,
        )

        self.assertTrue(sent)
        self.bot.send_video.assert_called_once()
        # CRITICAL ZERO-DISK LEAK CHECK ON REAL DISK:
        self.assertFalse(os.path.exists(real_video_file), "File MUST be unlinked from disk after direct send!")

    async def test_item2_send_video_file_under_50mb_fallback_document_unlinks_on_real_disk(self):
        """
        REAL DISK VERIFICATION:
        When send_video returns False, fallback to send_document_file and unlink on real disk.
        """
        real_video_file = os.path.join(self.temp_dir, "fallback_transient.mp4")
        with open(real_video_file, "wb") as f:
            f.write(b"REAL_FALLBACK_PAYLOAD" * 1024)

        self.bot.send_video = AsyncMock(return_value=False)
        self.bot.send_document_file = AsyncMock(return_value=True)

        sent = await self.bot.send_video_file(
            chat_id="chat_777",
            video_path=real_video_file,
            caption="Empirical verification fallback doc",
            cleanup_after_send=True,
        )

        self.assertTrue(sent)
        self.bot.send_video.assert_called_once()
        self.bot.send_document_file.assert_called_once()
        # CRITICAL ZERO-DISK LEAK CHECK ON REAL DISK:
        self.assertFalse(os.path.exists(real_video_file), "File MUST be unlinked after document fallback send!")

    async def test_item2_send_video_file_respects_cleanup_after_send_false(self):
        """When cleanup_after_send=False, file must NOT be unlinked."""
        real_video_file = os.path.join(self.temp_dir, "keep_transient.mp4")
        with open(real_video_file, "wb") as f:
            f.write(b"PERSISTENT_DATA" * 512)

        sent = await self.bot.send_video_file(
            chat_id="chat_777",
            video_path=real_video_file,
            caption="Keep file test",
            cleanup_after_send=False,
        )

        self.assertTrue(sent)
        self.assertTrue(os.path.exists(real_video_file), "File must remain on disk when cleanup_after_send=False")

    async def test_item2_send_video_file_over_50mb_activates_portal_and_ttl_seconds(self):
        """
        REAL STORAGE INTEGRATION VERIFICATION:
        File > 50MB triggers MediaStorageManager.publish_download_item with ttl_seconds=14400.
        Telegram send_video is NOT called.
        Portal message is sent with WAN and LAN links.
        """
        storage_dir = os.path.join(self.temp_dir, "portal_storage")
        storage_mgr = MediaStorageManager(base_dir=storage_dir)

        # Create a simulated large file (>50MB) using sparse write
        large_file = os.path.join(self.temp_dir, "large_emp_video.mp4")
        with open(large_file, "wb") as f:
            f.seek(52 * 1024 * 1024)  # 52MB
            f.write(b"\x00")

        self.assertGreater(os.path.getsize(large_file), 50 * 1024 * 1024)

        with patch("app.services.telegram_bot.media_storage_manager", storage_mgr), \
             patch.object(storage_mgr, "resolve_public_download_base_url_sync", return_value=("https://ngrok.example.com", "http://192.168.1.10:8084")):
            sent = await self.bot.send_video_file(
                chat_id="chat_777",
                video_path=large_file,
                caption="Large video empirical test",
            )

        self.assertTrue(sent)
        # Telegram send_video was NOT called
        self.bot.send_video.assert_not_called()
        self.bot.send_document_file.assert_not_called()

        # send_message was called with portal details
        self.bot.send_message.assert_called_once()
        portal_msg = self.bot.send_message.call_args[0][1]
        self.assertIn("52.0 MB", portal_msg)
        self.assertIn("https://ngrok.example.com", portal_msg)
        self.assertIn("http://192.168.1.10:8084", portal_msg)
        self.assertIn("4 giờ", portal_msg)

    async def test_item2_send_video_file_nonexistent_returns_false_on_real_bot(self):
        """Non-existent file returns False gracefully without unhandled exception on real bot instance."""
        nonexistent = os.path.join(self.temp_dir, "missing_video_file.mp4")
        real_bot = TelegramBot.__new__(TelegramBot)
        # Real send_video method does NOT have mock assertion methods
        sent = await real_bot.send_video_file(
            chat_id="chat_777",
            video_path=nonexistent,
        )
        self.assertFalse(sent)

    # =========================================================================
    # ITEM 3: VideoEditorService:274 ttl_seconds Verification
    # =========================================================================
    async def test_item3_video_editor_service_publish_or_direct_ttl_seconds(self):
        """
        EMPIRICAL EXECUTION VERIFICATION:
        Directly verify VideoEditorService._publish_or_direct calls
        publish_download_item with ttl_seconds without throwing TypeError.
        """
        storage_dir = os.path.join(self.temp_dir, "ves_storage")
        storage_mgr = MediaStorageManager(base_dir=storage_dir)

        # Create real VideoEditorService with storage_mgr
        ves = VideoEditorService(storage_manager=storage_mgr)

        # Create simulated 55MB output file
        ves_large_file = os.path.join(self.temp_dir, "ves_large_output.mp4")
        with open(ves_large_file, "wb") as f:
            f.seek(55 * 1024 * 1024)
            f.write(b"\x00")

        with patch.object(storage_mgr, "resolve_public_download_base_url_sync", return_value=("https://ngrok.example.com", "http://192.168.1.10:8084")):
            # Execute _publish_or_direct directly
            result = ves._publish_or_direct(
                file_path=Path(ves_large_file),
                title="Empirical Video Test",
                duration=90,
            )

        self.assertEqual(result["delivery"], "portal")
        self.assertEqual(result["file_size_mb"], 55.0)
        self.assertIsNotNone(result["internet_url"])
        self.assertIsNotNone(result["lan_url"])
        self.assertIsNotNone(result["expires_at"])
        # The file was published to public directory
        self.assertTrue(os.path.exists(result["file_path"]))

    # =========================================================================
    # ITEM 4: Error Resiliency & Exception Recovery
    # =========================================================================
    async def test_item4_video_editor_exception_resiliency(self):
        """When VideoEditorService raises an unexpected exception, bot does not crash and informs user."""
        self.mock_editor.remove_text_from_video = AsyncMock(
            side_effect=RuntimeError("GPU / FFmpeg out of memory")
        )

        await self.bot._on_video_process_pipeline(
            chat_id="chat_777",
            session=self.session,
            instruction="xóa sạch text trong video giúp tôi",
        )

        # LLM still not called
        self.bot.chat_with_agent.assert_not_called()

        # User notified of error politely
        error_sent = any(
            "Có lỗi trong quá trình biên tập video" in str(call[0][1] if len(call[0]) > 1 else call[1].get("text", ""))
            for call in self.bot.send_message.call_args_list
        )
        self.assertTrue(error_sent)


if __name__ == "__main__":
    unittest.main()
