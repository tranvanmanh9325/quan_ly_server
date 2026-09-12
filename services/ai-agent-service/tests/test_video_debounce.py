"""
Unit tests for VideoDebounceManager and LightweightVideoPipeline.
Verifies:
1. Video with caption dispatches pipeline immediately without delay.
2. Video without caption arms debounce timer; incoming user text cancels timer and dispatches with user instruction.
3. Video without caption triggers debounce timeout if no text arrives within window.
4. Callback actions (summarize, transcribe, visual_analyze) dispatch pipeline with expected prompt.
5. Agent context formatting synthesizes audio transcript and visual summary correctly.
"""

import asyncio
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.video_pipeline import (
    LightweightVideoPipeline,
    PendingVideoSession,
    VideoDebounceManager,
    VideoMetadata,
)


class TestVideoDebounceManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_video_debounce_")
        self.dummy_video_path = os.path.join(self.temp_dir, "test.mp4")
        with open(self.dummy_video_path, "wb") as f:
            f.write(b"\x00" * 1024)

        self.mock_on_timeout = AsyncMock()
        self.mock_on_pipeline = AsyncMock()

        self.manager = VideoDebounceManager(
            on_debounce_timeout=self.mock_on_timeout,
            on_process_pipeline=self.mock_on_pipeline,
        )
        # Use short delay for rapid deterministic unit tests
        self.manager.DEBOUNCE_DELAY_SECONDS = 0.1
        self.manager.SESSION_TTL_SECONDS = 1.0

    async def asyncTearDown(self):
        for chat_id in list(self.manager._sessions.keys()):
            await self.manager.remove_session(chat_id)
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_video_with_caption_dispatches_immediately(self):
        """If user sends video with caption, it must bypass debounce and process right away."""
        metadata = VideoMetadata(duration=15, width=1280, height=720, filename="clip.mp4", file_size=1024)
        chat_id = "user_101"

        await self.manager.register_video(
            chat_id=chat_id,
            file_id="file_abc123",
            temp_dir=self.temp_dir,
            video_path=self.dummy_video_path,
            metadata=metadata,
            caption="Tóm tắt video này giúp anh",
        )

        self.mock_on_pipeline.assert_awaited_once()
        args = self.mock_on_pipeline.call_args[0]
        self.assertEqual(args[0], chat_id)
        self.assertEqual(args[2], "Tóm tắt video này giúp anh")
        self.mock_on_timeout.assert_not_called()
        self.assertIsNone(self.manager.get_session(chat_id))

    async def test_video_without_caption_intercepts_user_text_early(self):
        """If user sends video without caption, and then sends text within debounce window,
        the text must be consumed as instruction and cancel the timeout."""
        metadata = VideoMetadata(duration=30, width=1920, height=1080, filename="demo.mp4", file_size=2048)
        chat_id = "user_102"

        await self.manager.register_video(
            chat_id=chat_id,
            file_id="file_def456",
            temp_dir=self.temp_dir,
            video_path=self.dummy_video_path,
            metadata=metadata,
            caption="",
        )

        session = self.manager.get_session(chat_id)
        self.assertIsNotNone(session)
        self.assertIsNotNone(session.debounce_task)

        # Simulate user typing a follow-up instruction after 0.02s (< 0.1s delay)
        await asyncio.sleep(0.02)
        consumed = await self.manager.handle_user_text(chat_id, "Video này nói về cái gì thế em?")

        self.assertTrue(consumed)
        self.mock_on_pipeline.assert_awaited_once()
        args = self.mock_on_pipeline.call_args[0]
        self.assertEqual(args[0], chat_id)
        self.assertEqual(args[2], "Video này nói về cái gì thế em?")

        await asyncio.sleep(0.12)
        self.mock_on_timeout.assert_not_called()

    async def test_video_without_caption_triggers_timeout_menu(self):
        """If user sends video without caption and sends nothing, on_debounce_timeout must be called."""
        metadata = VideoMetadata(duration=45, width=720, height=1280, filename="story.mp4", file_size=4096)
        chat_id = "user_103"

        await self.manager.register_video(
            chat_id=chat_id,
            file_id="file_ghi789",
            temp_dir=self.temp_dir,
            video_path=self.dummy_video_path,
            metadata=metadata,
            caption="",
        )

        # Wait for debounce timer to elapse (> 0.1s)
        await asyncio.sleep(0.15)

        self.mock_on_timeout.assert_awaited_once()
        args = self.mock_on_timeout.call_args[0]
        self.assertEqual(args[0], chat_id)
        self.assertEqual(args[1].metadata.duration, 45)

        self.mock_on_pipeline.assert_not_called()
        self.assertIsNotNone(self.manager.get_session(chat_id))

    async def test_handle_callback_action_after_timeout(self):
        """If user clicks an inline action button after timeout, pipeline must be dispatched."""
        metadata = VideoMetadata(duration=20, width=1280, height=720, filename="clip2.mp4", file_size=1024)
        chat_id = "user_104"

        await self.manager.register_video(
            chat_id=chat_id,
            file_id="file_jkl012",
            temp_dir=self.temp_dir,
            video_path=self.dummy_video_path,
            metadata=metadata,
            caption="",
        )

        await asyncio.sleep(0.15)
        self.mock_on_timeout.assert_awaited_once()

        handled = await self.manager.handle_callback_action(chat_id, "summarize")
        self.assertTrue(handled)

        self.mock_on_pipeline.assert_awaited_once()
        args = self.mock_on_pipeline.call_args[0]
        self.assertEqual(args[0], chat_id)
        self.assertIn("tóm tắt", args[2].lower())

    async def test_compose_agent_context(self):
        """Test formatting of multimodal context block for AI Agent."""
        mock_media = MagicMock()
        pipeline = LightweightVideoPipeline(mock_media)

        context = pipeline._compose_agent_context(
            filename="tutorial.mp4",
            duration=50,
            instruction="Xem video và tóm tắt",
            transcript="Xin chào các bạn hôm nay tôi hướng dẫn cài đặt server",
            visual_summary="[Khung hình 00:00]: Màn hình hiển thị terminal Linux.\n[Khung hình 00:25]: Trình duyệt đang tải web.",
        )

        self.assertIn("THÔNG TIN ĐA PHƯƠNG TIỆN TỪ VIDEO", context)
        self.assertIn("tutorial.mp4", context)
        self.assertIn("50s", context)
        self.assertIn("Xin chào các bạn hôm nay tôi hướng dẫn", context)
        self.assertIn("Màn hình hiển thị terminal Linux", context)


if __name__ == "__main__":
    unittest.main()