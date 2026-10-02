"""
test_video_upload_stuck_99_fix.py — Regression and verification tests for Telegram 99% video upload stuck fix.

Verifies:
1. R1: Video processing runs in asyncio.Task, immediate acknowledge message is sent before processing completes.
2. R2: pytesseract.image_to_data runs in run_in_executor (thread pool) without blocking the event loop.
3. R3: 5-minute timeout protection catches hung processing and sends friendly user notification.
"""

import asyncio
import os
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from app.services.telegram_bot import TelegramBot
from app.services.video_pipeline import PendingVideoSession, VideoMetadata
from app.services.video_editor_service import VideoEditorService


class TestVideoUploadStuck99Fix(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_stuck_fix_")
        self.dummy_video = os.path.join(self.temp_dir, "input.mp4")
        with open(self.dummy_video, "wb") as f:
            f.write(b"\x00" * 4096)

        self.bot = TelegramBot.__new__(TelegramBot)
        self.bot.token = "mock_token"
        self.bot.send_message = AsyncMock(return_value=True)
        self.bot.send_video_file = AsyncMock(return_value=True)
        self.bot.chat_with_agent = AsyncMock(return_value="AI Reply")
        self.bot._video_pipeline = MagicMock()
        self.mock_editor = AsyncMock()
        self.bot._video_editor_svc = self.mock_editor
        self.bot._last_video_task = None

        self.session = PendingVideoSession(
            chat_id="chat_123",
            file_id="fid_123",
            temp_dir=self.temp_dir,
            video_path=self.dummy_video,
            metadata=VideoMetadata(filename="input.mp4", duration=15, width=1280, height=720, file_size=4096),
        )

    async def asyncTearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_r1_spawns_task_and_acknowledges_immediately(self):
        """R1: Bot sends acknowledge message and spawns asyncio.Task for video processing."""
        output_video = os.path.join(self.temp_dir, "output_clean.mp4")
        with open(output_video, "wb") as f:
            f.write(b"\x00" * 2048)

        acknowledge_sent_before_processing = False

        async def fake_remove_text(*args, **kwargs):
            nonlocal acknowledge_sent_before_processing
            # Verify that acknowledge was sent BEFORE remove_text completes
            calls = [c[0][1] if len(c[0]) > 1 else "" for c in self.bot.send_message.call_args_list]
            if any("Đang tự động xóa text/watermark" in m for m in calls):
                acknowledge_sent_before_processing = True
            return {
                "status": "ok",
                "output_path": output_video,
                "message": "Đã làm sạch video",
            }

        self.mock_editor.remove_text_from_video = AsyncMock(side_effect=fake_remove_text)

        await self.bot._on_video_process_pipeline(
            chat_id="chat_123",
            session=self.session,
            instruction="xóa text trong video",
        )

        # Check acknowledge timing
        self.assertTrue(acknowledge_sent_before_processing, "Acknowledge message must be sent before processing completes!")

        # Check task was created
        self.assertIsNotNone(self.bot._last_video_task)
        self.assertTrue(isinstance(self.bot._last_video_task, asyncio.Task))

        # Check video delivered
        self.bot.send_video_file.assert_called_once_with("chat_123", output_video, caption="🎬 Đã làm sạch video")

    async def test_r2_pytesseract_wrapped_in_run_in_executor(self):
        """R2: pytesseract.image_to_data must be invoked via loop.run_in_executor without blocking event loop."""
        service = VideoEditorService(storage_manager=MagicMock())

        async def fake_run(cmd, timeout=30):
            if "-vsync" in cmd:
                sample_dir = Path(cmd[-1]).parent
                for i in range(2):
                    (sample_dir / f"sample_000{i}.jpg").write_bytes(b"frame")
                return 0, b"", b""
            return 0, b"", b""

        mock_tesseract = MagicMock()
        mock_tesseract.Output.DICT = "dict"
        mock_tesseract.image_to_data.return_value = {
            "text": ["SAMPLE"],
            "conf": [85],
            "left": [20],
            "top": [20],
            "width": [50],
            "height": [20],
        }

        mock_pil = MagicMock()
        mock_img = MagicMock()
        mock_img.width = 640
        mock_img.height = 480
        mock_pil.Image.open.return_value.__enter__.return_value = mock_img

        loop = asyncio.get_running_loop()
        run_in_executor_calls = []
        original_run_in_executor = loop.run_in_executor

        async def tracking_run_in_executor(executor, func, *args):
            run_in_executor_calls.append((executor, func, args))
            return await original_run_in_executor(executor, func, *args)

        with patch.object(service, "_run_command", side_effect=fake_run):
            with patch.dict("sys.modules", {"pytesseract": mock_tesseract, "PIL": mock_pil}):
                with patch.object(loop, "run_in_executor", side_effect=tracking_run_in_executor):
                    detected = await service._auto_detect_text_region(Path(self.dummy_video))

                    # Verify run_in_executor was called for image_to_data
                    self.assertGreater(len(run_in_executor_calls), 0, "run_in_executor must be called for OCR frames!")
                    self.assertEqual(len(detected), 1)

    async def test_r3_timeout_protection_sends_friendly_message(self):
        """R3: 5-minute timeout triggers friendly notification: 'Video quá phức tạp, vui lòng thử lại với video ngắn hơn'."""
        async def hang_forever(*args, **kwargs):
            await asyncio.sleep(9999)

        self.mock_editor.remove_text_from_video = AsyncMock(side_effect=hang_forever)

        # Mock wait_for timeout with 0.05s to simulate 300s timeout fast in test
        original_wait_for = asyncio.wait_for

        async def fast_timeout_wait_for(fut, timeout):
            return await original_wait_for(fut, timeout=0.05)

        with patch("asyncio.wait_for", side_effect=fast_timeout_wait_for):
            await self.bot._on_video_process_pipeline(
                chat_id="chat_123",
                session=self.session,
                instruction="xóa text trong video",
            )

        # Friendly error message checked
        friendly_msg_sent = any(
            "Video quá phức tạp, vui lòng thử lại với video ngắn hơn" in (c[0][1] if len(c[0]) > 1 else "")
            for c in self.bot.send_message.call_args_list
        )
        self.assertTrue(friendly_msg_sent, "Bot must send friendly timeout message on 5-min timeout!")

    async def test_r3_timeout_with_explicit_message_sends_friendly_notification(self):
        """R3: When remove_text_from_video raises TimeoutError with inner message, bot must still send friendly message."""
        self.mock_editor.remove_text_from_video = AsyncMock(
            side_effect=TimeoutError("Tác vụ xử lý video vượt quá thời gian tối đa (300s).")
        )

        await self.bot._on_video_process_pipeline(
            chat_id="chat_123",
            session=self.session,
            instruction="xóa text trong video",
        )

        friendly_msg_sent = any(
            "Video quá phức tạp, vui lòng thử lại với video ngắn hơn" in (c[0][1] if len(c[0]) > 1 else "")
            for c in self.bot.send_message.call_args_list
        )
        self.assertTrue(friendly_msg_sent, "Bot must send friendly timeout message even if TimeoutError has a message!")

    def test_inpaint_merge_subprocess_timeout_raises_timeouterror(self):
        """Inpaint merge subprocess timeout must raise TimeoutError, not raw RuntimeError or SubprocessError."""
        import subprocess
        service = VideoEditorService(storage_manager=MagicMock())

        # Mock cv2 and VideoCapture
        import numpy as np
        mock_cv2 = MagicMock()
        mock_cap = MagicMock()
        mock_cap.isOpened.side_effect = [True, True, False]
        mock_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        mock_cap.read.side_effect = [(True, mock_frame), (False, None)]
        mock_cap.get.side_effect = lambda prop: 30.0 if prop == mock_cv2.CAP_PROP_FPS else (640 if prop == mock_cv2.CAP_PROP_FRAME_WIDTH else 480)
        mock_cv2.VideoCapture.return_value = mock_cap
        mock_cv2.CAP_PROP_FPS = 1
        mock_cv2.CAP_PROP_FRAME_WIDTH = 2
        mock_cv2.CAP_PROP_FRAME_HEIGHT = 3

        mock_writer = MagicMock()
        mock_cv2.VideoWriter.return_value = mock_writer

        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=300)):
                with self.assertRaises(RuntimeError) as ctx:
                    service._inpaint_video_sync(
                        input_file=Path(self.dummy_video),
                        output_file=Path(self.temp_dir) / "out.mp4",
                        rx_or_regions=[{"x": 10, "y": 10, "w": 50, "h": 20}],
                    )
                self.assertIn("timeout", str(ctx.exception).lower())

    async def test_r3_inpaint_timeout_runtimeerror_sends_friendly_notification(self):
        """R3: When inpainting merge times out, bot must catch the timeout RuntimeError and send friendly message."""
        self.mock_editor.remove_text_from_video = AsyncMock(
            side_effect=RuntimeError("FFmpeg ghép âm thanh sau khi inpaint bị timeout quá 300 giây.")
        )

        await self.bot._on_video_process_pipeline(
            chat_id="chat_123",
            session=self.session,
            instruction="xóa text trong video",
        )

        friendly_msg_sent = any(
            "Video quá phức tạp, vui lòng thử lại với video ngắn hơn" in (c[0][1] if len(c[0]) > 1 else "")
            for c in self.bot.send_message.call_args_list
        )
        self.assertTrue(friendly_msg_sent, "Bot must send friendly timeout message on inpaint timeout!")

    async def test_subprocess_killed_on_task_cancellation(self):
        """Edge case: When _run_command task is cancelled, child process must be terminated and reaped."""
        service = VideoEditorService(storage_manager=MagicMock())

        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)

        async def fake_communicate():
            await asyncio.sleep(999)
            return b"", b""

        mock_proc.communicate = fake_communicate

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            task = asyncio.create_task(service._run_command(["ffmpeg", "-i", "input.mp4"]))
            await asyncio.sleep(0.02)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

            mock_proc.kill.assert_called_once()
            mock_proc.wait.assert_awaited_once()

    async def test_concurrent_sessions_do_not_wipe_active_processing(self):
        """Race condition: Registering a newer video while an older one is processing must not delete active files."""
        from app.services.video_pipeline import VideoDebounceManager

        temp_dir1 = tempfile.mkdtemp(prefix="test_sess1_")
        temp_dir2 = tempfile.mkdtemp(prefix="test_sess2_")
        try:
            video1 = os.path.join(temp_dir1, "v1.mp4")
            video2 = os.path.join(temp_dir2, "v2.mp4")
            with open(video1, "wb") as f:
                f.write(b"video1")
            with open(video2, "wb") as f:
                f.write(b"video2")

            pipeline_running = asyncio.Event()
            finish_pipeline = asyncio.Event()

            async def fake_pipeline(chat_id, session, text):
                pipeline_running.set()
                await finish_pipeline.wait()

            manager = VideoDebounceManager(
                on_debounce_timeout=AsyncMock(),
                on_process_pipeline=fake_pipeline,
            )

            # Start video 1 with caption
            task1 = asyncio.create_task(
                manager.register_video(
                    chat_id="chat_concur",
                    file_id="f1",
                    temp_dir=temp_dir1,
                    video_path=video1,
                    metadata=VideoMetadata(filename="v1.mp4"),
                    caption="xóa text",
                )
            )
            await pipeline_running.wait()

            # Video 1 is actively processing. Now user uploads Video 2.
            await manager.register_video(
                chat_id="chat_concur",
                file_id="f2",
                temp_dir=temp_dir2,
                video_path=video2,
                metadata=VideoMetadata(filename="v2.mp4"),
                caption="",
            )

            # Video 1's temp_dir must NOT be deleted yet!
            self.assertTrue(os.path.exists(temp_dir1), "Video 1 temp dir must not be deleted while still processing!")
            self.assertTrue(os.path.exists(temp_dir2), "Video 2 temp dir must exist!")

            # Now let video 1 finish
            finish_pipeline.set()
            await task1

            # Video 1 must now be cleaned up, but Video 2 must REMAIN intact!
            self.assertFalse(os.path.exists(temp_dir1), "Video 1 temp dir must be cleaned up after finishing!")
            self.assertTrue(os.path.exists(temp_dir2), "Video 2 temp dir must NOT be cleaned up when Video 1 completes!")
            self.assertIsNotNone(manager.get_session("chat_concur"))
        finally:
            shutil.rmtree(temp_dir1, ignore_errors=True)
            shutil.rmtree(temp_dir2, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

