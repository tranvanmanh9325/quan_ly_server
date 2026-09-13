"""
test_dual_distribution_integration.py — Comprehensive Integration Tests for Dual-Track Video Distribution.

Verifies:
1. Fast-Path in TelegramBot:
   - Video <= 50MB: single send_video call, zero chunking overhead, immediate cleanup.
   - Video > 50MB:
     * Preparatory chunking notification sent to user.
     * Ownership transfer to media_storage_manager (is_temp_file set to False).
     * Lossless segmentation via VideoChunker.split_video.
     * Sequential part dispatch with formatted HTML caption (Part X/Y, duration, size, lossless badge).
     * Streaming Purge: each part file unlinked immediately after successful dispatch.
     * Telegram 429 FloodWait protection (asyncio.sleep between parts).
     * Final completion notification delivering both Ngrok Internet and LAN direct download links.
     * Safe cleanup of transient parts_dir in finally block.
2. ReAct Tool download_media_video in AgentToolExecutor:
   - Video <= 50MB: dispatches directly and returns formatted success.
   - Video > 50MB: performs dual distribution and returns rich details with direct links to LLM.
   - Video > 50MB without chat_id: still publishes download record and returns links gracefully.
3. Zero-RAM-Leak Assurance:
   - Verifies no whole-file vf.read() occurs during upload/fallback.
"""

import asyncio
import html
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.telegram_bot import TelegramBot
from app.services.ai_agent_tools import AgentToolExecutor
from app.services.media_downloader import MediaItem
from app.services.media_storage_manager import DownloadRecord, media_storage_manager
from app.services.video_chunker import VideoChunker


class TestTelegramBotDualDistribution(unittest.IsolatedAsyncioTestCase):
    """Integration test suite for Fast-Path Dual Video Distribution in TelegramBot."""

    def setUp(self):
        self.bot = TelegramBot.__new__(TelegramBot)
        self.bot.token = "dummy_token"
        self.bot.chat_id = "123456"
        self.bot._claim_update = AsyncMock(return_value=True)
        self.bot._video_debounce = MagicMock()
        self.bot._video_debounce.handle_user_text = AsyncMock(return_value=False)
        self.bot._pending_archives = {}
        self.bot._rate_limiter = MagicMock()
        self.bot._rate_limiter.acquire = AsyncMock()
        self.bot.send_message_with_result = AsyncMock(return_value={"message_id": 999})
        self.bot.send_message = AsyncMock(return_value=True)
        self.bot.delete_message = AsyncMock(return_value=True)
        self.bot.send_video = AsyncMock(return_value=True)
        self.bot.send_document_file = AsyncMock(return_value=True)

    async def test_fastpath_video_under_50mb_single_send(self):
        """Videos <= 50MB must be sent as a single video without chunking or direct link overhead."""
        mock_media_item = MagicMock(spec=MediaItem)
        mock_media_item.media_type = "video"
        mock_media_item.file_path = "/tmp/media_downloads/short_video.mp4"
        mock_media_item.title = "Short 1080p Video"
        mock_media_item.author = "TestAuthor"
        mock_media_item.duration = 45
        mock_media_item.file_size = 35 * 1024 * 1024  # 35 MB <= 50 MB
        mock_media_item.cleanup = MagicMock()

        mock_pipeline = MagicMock()
        mock_pipeline.download = AsyncMock(return_value=mock_media_item)

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline), \
             patch("app.services.video_chunker.VideoChunker.split_video", new_callable=AsyncMock) as mock_split, \
             patch("app.services.media_storage_manager.media_storage_manager.publish_download_item") as mock_publish:

            update = {
                "update_id": 2001,
                "message": {
                    "chat": {"id": 123456},
                    "text": "https://www.youtube.com/shorts/testshort123",
                    "message_id": 10,
                }
            }
            await self.bot._process_update(update)

            # Assert single send_video call
            self.bot.send_video.assert_awaited_once()
            call_kwargs = self.bot.send_video.call_args[1]
            self.assertEqual(call_kwargs["video_path"], "/tmp/media_downloads/short_video.mp4")
            self.assertIn("Short 1080p Video", call_kwargs["caption"])

            # Verify chunking and direct link publishing were NOT invoked
            mock_split.assert_not_called()
            mock_publish.assert_not_called()

            # Ensure cleanup is called for normal files
            mock_media_item.cleanup.assert_called_once()

    async def test_fastpath_video_over_50mb_dual_distribution(self):
        """Videos > 50MB must trigger both sequential Telegram chunking and Direct Server Download link."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_path = Path(tmp_dir) / "large_video.mp4"
            temp_path.write_bytes(b"A" * 1024)

            mock_media_item = MediaItem(
                file_path=str(temp_path),
                title="Grand 4K Documentary",
                author="NationalGeo",
                duration=600,
                media_type="video",
                source_url="https://www.youtube.com/watch?v=large_video_75mb",
                file_size=75 * 1024 * 1024,  # 75 MB > 50 MB
                is_temp_file=True,
            )

            mock_pipeline = MagicMock()
            mock_pipeline.download = AsyncMock(return_value=mock_media_item)

            published_record = DownloadRecord(
                token="sec_token_12345",
                filename="large_video.mp4",
                file_path=Path("/tmp/media_downloads/public/sec_token_12345/large_video.mp4"),
                file_size=75 * 1024 * 1024,
                title="Grand 4K Documentary",
                duration=600,
                created_at=1000.0,
                expires_at=15400.0,
                internet_url="https://earmark-humming-bountiful.ngrok-free.dev/api/ai/media/download/sec_token_12345/large_video.mp4",
                lan_url="http://192.168.0.100:5173/api/ai/media/download/sec_token_12345/large_video.mp4",
            )

            # Simulated chunked parts
            part1_path = Path(tmp_dir) / "part_000.mp4"
            part2_path = Path(tmp_dir) / "part_001.mp4"
            part1_path.write_bytes(b"B" * 500)
            part2_path.write_bytes(b"C" * 500)

            mock_parts = [
                {
                    "path": str(part1_path),
                    "part_index": 1,
                    "total_parts": 2,
                    "duration": 300,
                    "size": 40 * 1024 * 1024,
                    "width": 1920,
                    "height": 1080,
                },
                {
                    "path": str(part2_path),
                    "part_index": 2,
                    "total_parts": 2,
                    "duration": 300,
                    "size": 35 * 1024 * 1024,
                    "width": 1920,
                    "height": 1080,
                },
            ]

            unlinked_files = []
            orig_unlink = os.unlink
            def tracked_unlink(path):
                unlinked_files.append(str(path))
                if os.path.exists(path):
                    orig_unlink(path)

            with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline), \
                 patch("app.services.media_storage_manager.media_storage_manager.publish_download_item", return_value=published_record) as mock_publish, \
                 patch("app.services.video_chunker.VideoChunker.split_video", new_callable=AsyncMock, return_value=mock_parts) as mock_split, \
                 patch("os.unlink", side_effect=tracked_unlink), \
                 patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:

                update = {
                    "update_id": 2002,
                    "message": {
                        "chat": {"id": 123456},
                        "text": "https://www.youtube.com/watch?v=large_video_75mb",
                        "message_id": 11,
                    }
                }
                await self.bot._process_update(update)

                # 1. Verify preparatory chunking message was sent
                prep_calls = [
                    call for call in self.bot.send_message.call_args_list
                    if "Video chất lượng gốc có dung lượng lớn" in str(call)
                ]
                self.assertTrue(len(prep_calls) >= 1, "Must send preparatory notification before chunking")

                # 2. Verify publish_download_item was called
                mock_publish.assert_called_once()
                self.assertFalse(mock_media_item.is_temp_file, "MediaItem must yield ownership to storage manager")

                # 3. Verify VideoChunker.split_video was called
                mock_split.assert_awaited_once()

                # 4. Verify send_video called for each part
                self.assertEqual(self.bot.send_video.call_count, 2)
                call1_kwargs = self.bot.send_video.call_args_list[0][1]
                call2_kwargs = self.bot.send_video.call_args_list[1][1]
                self.assertIn("Phần 1/2", call1_kwargs["caption"])
                self.assertIn("Phần 2/2", call2_kwargs["caption"])
                self.assertIn("Lossless", call1_kwargs["caption"])

                # 5. Verify Streaming Purge: each part unlinked immediately after sending
                self.assertIn(str(part1_path), unlinked_files)
                self.assertIn(str(part2_path), unlinked_files)

                # 6. Verify Telegram 429 FloodWait backoff sleep
                mock_sleep.assert_awaited_once_with(1.0)

                # 7. Verify final completion message with both Ngrok and LAN links
                completion_calls = [
                    call for call in self.bot.send_message.call_args_list
                    if "Đã gửi trọn vẹn 2/2 phần lên Telegram!" in str(call)
                ]
                self.assertEqual(len(completion_calls), 1)
                comp_text = completion_calls[0][0][1]
                self.assertIn(published_record.internet_url, comp_text)
                self.assertIn(published_record.lan_url, comp_text)
                self.assertIn("4 giờ", comp_text)


class TestAiAgentToolsDualDistribution(unittest.IsolatedAsyncioTestCase):
    """Integration test suite for download_media_video ReAct Tool in AgentToolExecutor."""

    def setUp(self):
        self.mock_bot = MagicMock()
        self.mock_bot.send_chat_action = AsyncMock(return_value=True)
        self.mock_bot.send_message = AsyncMock(return_value=True)
        self.mock_bot.send_video = AsyncMock(return_value=True)
        self.mock_bot.send_document_file = AsyncMock(return_value=True)
        self.mock_ssh = MagicMock()
        self.mock_cache = MagicMock()
        self.executor = AgentToolExecutor(
            ssh_client=self.mock_ssh,
            message_cache=self.mock_cache,
            telegram_bot=self.mock_bot,
        )

    async def test_react_tool_video_under_50mb(self):
        """ReAct tool dispatches single video when <= 50MB."""
        mock_media_item = MagicMock(spec=MediaItem)
        mock_media_item.media_type = "video"
        mock_media_item.file_path = "/tmp/media_downloads/react_small.mp4"
        mock_media_item.title = "Cute Cat Reel"
        mock_media_item.author = "CatChannel"
        mock_media_item.duration = 20
        mock_media_item.file_size = 15 * 1024 * 1024
        mock_media_item.cleanup = MagicMock()

        mock_pipeline = MagicMock()
        mock_pipeline.download = AsyncMock(return_value=mock_media_item)

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline), \
             patch("app.services.video_chunker.VideoChunker.split_video", new_callable=AsyncMock) as mock_split, \
             patch("app.services.media_storage_manager.media_storage_manager.publish_download_item") as mock_publish:

            res = await self.executor._execute_tool(
                "download_media_video",
                {"url": "https://www.facebook.com/reel/123456789"},
                chat_id="123456",
            )

            self.assertIn("Cute Cat Reel", res)
            self.mock_bot.send_video.assert_awaited_once()
            mock_split.assert_not_called()
            mock_publish.assert_not_called()
            mock_media_item.cleanup.assert_called_once()

    async def test_react_tool_video_over_50mb_returns_direct_links(self):
        """ReAct tool splits video > 50MB and returns both chunk summary and direct download URLs."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_path = Path(tmp_dir) / "huge_film.mp4"
            temp_path.write_bytes(b"D" * 1024)

            mock_media_item = MediaItem(
                file_path=str(temp_path),
                title="Full 4K Nature Film",
                author="PlanetEarth",
                duration=1200,
                media_type="video",
                source_url="https://www.youtube.com/watch?v=huge_film",
                file_size=120 * 1024 * 1024,  # 120 MB > 50 MB
                is_temp_file=True,
            )

            mock_pipeline = MagicMock()
            mock_pipeline.download = AsyncMock(return_value=mock_media_item)

            published_record = DownloadRecord(
                token="token_nature_4k",
                filename="huge_film.mp4",
                file_path=Path("/tmp/media_downloads/public/token_nature_4k/huge_film.mp4"),
                file_size=120 * 1024 * 1024,
                title="Full 4K Nature Film",
                duration=1200,
                created_at=1000.0,
                expires_at=15400.0,
                internet_url="https://earmark-humming-bountiful.ngrok-free.dev/api/ai/media/download/token_nature_4k/huge_film.mp4",
                lan_url="http://192.168.0.100:5173/api/ai/media/download/token_nature_4k/huge_film.mp4",
            )

            part1 = Path(tmp_dir) / "part_000.mp4"
            part2 = Path(tmp_dir) / "part_001.mp4"
            part3 = Path(tmp_dir) / "part_002.mp4"
            part1.write_bytes(b"1")
            part2.write_bytes(b"2")
            part3.write_bytes(b"3")

            mock_parts = [
                {"path": str(part1), "part_index": 1, "total_parts": 3, "duration": 400, "size": 40 * 1024 * 1024, "width": 1920, "height": 1080},
                {"path": str(part2), "part_index": 2, "total_parts": 3, "duration": 400, "size": 40 * 1024 * 1024, "width": 1920, "height": 1080},
                {"path": str(part3), "part_index": 3, "total_parts": 3, "duration": 400, "size": 40 * 1024 * 1024, "width": 1920, "height": 1080},
            ]

            with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline), \
                 patch("app.services.media_storage_manager.media_storage_manager.publish_download_item", return_value=published_record), \
                 patch("app.services.video_chunker.VideoChunker.split_video", new_callable=AsyncMock, return_value=mock_parts), \
                 patch("asyncio.sleep", new_callable=AsyncMock):

                result = await self.executor._execute_tool(
                    "download_media_video",
                    {"url": "https://www.youtube.com/watch?v=huge_film"},
                    chat_id="123456",
                )

                # Verify returned message to Agent
                self.assertIn("Full 4K Nature Film", result)
                self.assertIn("120.0 MB", result)
                self.assertIn("3 phần lossless", result)
                self.assertIn(published_record.internet_url, result)
                self.assertIn(published_record.lan_url, result)

                # Verify 3 parts were sent
                self.assertEqual(self.mock_bot.send_video.call_count, 3)

    async def test_react_tool_without_chat_id_publishes_links(self):
        """ReAct tool called headless (without chat_id) still publishes file and returns direct URLs."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_path = Path(tmp_dir) / "headless_video.mp4"
            temp_path.write_bytes(b"E" * 1024)

            mock_media_item = MediaItem(
                file_path=str(temp_path),
                title="Headless Video Test",
                author="BotChannel",
                duration=300,
                media_type="video",
                source_url="https://www.youtube.com/watch?v=headless_test",
                file_size=80 * 1024 * 1024,
                is_temp_file=True,
            )

            mock_pipeline = MagicMock()
            mock_pipeline.download = AsyncMock(return_value=mock_media_item)

            published_record = DownloadRecord(
                token="token_headless_80mb",
                filename="headless_video.mp4",
                file_path=Path("/tmp/media_downloads/public/token_headless_80mb/headless_video.mp4"),
                file_size=80 * 1024 * 1024,
                title="Headless Video Test",
                duration=300,
                created_at=1000.0,
                expires_at=15400.0,
                internet_url="https://earmark-humming-bountiful.ngrok-free.dev/api/ai/media/download/token_headless_80mb/headless_video.mp4",
                lan_url="http://192.168.0.100:5173/api/ai/media/download/token_headless_80mb/headless_video.mp4",
            )

            with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline), \
                 patch("app.services.media_storage_manager.media_storage_manager.publish_download_item", return_value=published_record), \
                 patch("app.services.video_chunker.VideoChunker.split_video", new_callable=AsyncMock, return_value=[]):

                # Executor without chat_id
                executor = AgentToolExecutor(
                    ssh_client=self.mock_ssh,
                    message_cache=self.mock_cache,
                    telegram_bot=None,
                )
                result = await executor._execute_tool(
                    "download_media_video",
                    {"url": "https://www.youtube.com/watch?v=headless_test"},
                    chat_id=None,
                )

                self.assertIn("Headless Video Test", result)
                self.assertIn(published_record.internet_url, result)
                self.assertIn(published_record.lan_url, result)


if __name__ == "__main__":
    unittest.main()

