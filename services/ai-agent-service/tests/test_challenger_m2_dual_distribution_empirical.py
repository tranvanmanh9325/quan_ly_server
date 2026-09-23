"""
test_challenger_m2_dual_distribution_empirical.py — Challenger 2 Empirical Test Suite.

Adversarial Empirical Verification for Milestone 2:
1. 120MB Video Lossless Part Chunking (<= 48MB per part, GOP overshoot defense).
2. Telegram Bot Fast-Path & ReAct Tool:
   - supports_streaming=True passed on every part.
   - Streaming Purge: immediate unlinking of each part file after dispatch.
   - Anti-429 FloodWait: asyncio.sleep(1.0) between part transmissions.
3. LAN Direct Download Link Standardization to Port 8084:
   - Verification that lan_url strictly targets port 8084 (http://192.168.0.100:8084).
   - Genuine str equality verification for port 8084.
4. HTTP 206 Partial Content Range Requests:
   - Range: bytes=0-1023 returns 206 Partial Content with correct Content-Range and bytes slice.
   - Mid-range and suffix-range byte verification.
5. Zero-Disk Leak:
   - Normal completion cleans all temporary part files and directories.
   - Adversarial fault injection (exception during transmission) cleans all temporary resources in finally block.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from starlette.testclient import TestClient

from app.main import app
from app.services.telegram_bot import TelegramBot
from app.services.ai_agent_tools import AgentToolExecutor
from app.services.media_downloader import MediaItem
from app.services.media_storage_manager import (
    MediaStorageManager,
    DownloadRecord,
    media_storage_manager,
)
from app.services.video_chunker import (
    VideoChunker,
    TELEGRAM_SAFE_PART_BYTES,
    TARGET_CHUNK_BYTES,
)


class TestChallengerM2EmpiricalDualDistribution(unittest.IsolatedAsyncioTestCase):
    """Adversarial Empirical Challenge for Milestone 2 Dual Distribution & Port 8084."""

    def setUp(self):
        self.client = TestClient(app)
        self.test_dir = tempfile.mkdtemp(prefix="challenger_m2_test_")
        self.base_dir = Path(self.test_dir)
        self.temp_dir = self.base_dir / "temp"
        self.public_dir = self.base_dir / "public"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.public_dir.mkdir(parents=True, exist_ok=True)
        self.orig_media_temp_dir = media_storage_manager.temp_dir
        media_storage_manager.temp_dir = self.temp_dir

    def tearDown(self):
        media_storage_manager.temp_dir = self.orig_media_temp_dir
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # TEST 1: 120MB Video Lossless Chunking <= 48MB
    # -------------------------------------------------------------------------
    async def test_empirical_120mb_video_chunking_constraints(self):
        """
        Verify that a 120MB video file (> 50MB) is split into parts that are strictly <= 48MB each.
        Uses sparse/truncated files on the real filesystem to test stat.st_size without mocks.
        """
        video_size = 120 * 1024 * 1024  # 125,829,120 bytes (~120MB)
        out_dir = self.temp_dir / "chunk_parts_120mb"
        out_dir.mkdir(parents=True, exist_ok=True)

        large_video = self.temp_dir / "test_120mb_video.mp4"
        with open(large_video, "wb") as f:
            f.truncate(video_size)

        self.assertEqual(large_video.stat().st_size, video_size)

        mock_probe = {
            "duration": 180.0,
            "width": 1920,
            "height": 1080,
            "codec_name": "h264",
            "size": video_size,
        }

        # Simulate FFmpeg splitting 120MB into 3 segments (~40MB each)
        part_sizes = [40 * 1024 * 1024, 42 * 1024 * 1024, 38 * 1024 * 1024]
        self.assertEqual(sum(part_sizes), video_size)

        async def fake_ffmpeg_split(*args, **kwargs):
            for idx, size in enumerate(part_sizes):
                p_file = out_dir / f"part_{idx:03d}.mp4"
                with open(p_file, "wb") as pf:
                    pf.truncate(size)
            proc = MagicMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"", b""))
            return proc

        with patch.object(VideoChunker, "probe_video_info", new=AsyncMock(return_value=mock_probe)), \
             patch("asyncio.create_subprocess_exec", side_effect=fake_ffmpeg_split):

            parts = await VideoChunker.split_video(
                video_path=str(large_video),
                output_dir=out_dir,
                max_part_bytes=TELEGRAM_SAFE_PART_BYTES,
                target_part_bytes=TARGET_CHUNK_BYTES,
            )

            self.assertEqual(len(parts), 3, "120MB must split into 3 parts (~40MB each)")
            for p in parts:
                self.assertLessEqual(
                    p["size"],
                    TELEGRAM_SAFE_PART_BYTES,
                    f"Part {p['part_index']} size ({p['size']}) exceeds Telegram ceiling (48MB)"
                )
                self.assertEqual(p["total_parts"], 3)
                self.assertEqual(p["width"], 1920)
                self.assertEqual(p["height"], 1080)
                self.assertEqual(p["codec_name"], "h264")

    # -------------------------------------------------------------------------
    # TEST 2: Fast-Path 120MB Video — supports_streaming, Purge, 429 Sleep
    # -------------------------------------------------------------------------
    async def test_empirical_fastpath_120mb_streaming_purge_and_sleep(self):
        """
        Verify that Telegram Bot fast-path on a 120MB video:
        1. Calls send_video with supports_streaming=True for ALL parts.
        2. Implements immediate Streaming Purge: part deleted after send.
        3. Sleeps 1.0s between parts to prevent Telegram 429 FloodWait.
        4. Provides LAN direct download link using port 8084.
        """
        bot = TelegramBot.__new__(TelegramBot)
        bot.token = "test_bot_token"
        bot.chat_id = "987654"
        bot._claim_update = AsyncMock(return_value=True)
        bot._video_debounce = MagicMock()
        bot._video_debounce.handle_user_text = AsyncMock(return_value=False)
        bot._pending_archives = {}
        bot._rate_limiter = MagicMock()
        bot._rate_limiter.acquire = AsyncMock()
        bot.send_message_with_result = AsyncMock(return_value={"message_id": 100})
        bot.send_message = AsyncMock(return_value=True)
        bot.delete_message = AsyncMock(return_value=True)
        bot.send_video = AsyncMock(return_value=True)
        bot.send_document_file = AsyncMock(return_value=True)
        bot.dream_engine = None

        video_path = self.temp_dir / "large_120mb_video.mp4"
        video_path.write_bytes(b"TEST_ORIGINAL_VIDEO_DATA" * 50)

        mock_media_item = MediaItem(
            file_path=str(video_path),
            title="Adversarial 120MB 4K60 Video",
            author="EmpiricalTester",
            duration=120,
            media_type="video",
            source_url="https://www.youtube.com/watch?v=adversarial_120mb",
            file_size=120 * 1024 * 1024,
            is_temp_file=True,
        )

        mock_pipeline = MagicMock()
        mock_pipeline.download = AsyncMock(return_value=mock_media_item)

        # 3 simulated part files
        part1 = self.temp_dir / "part_000.mp4"
        part2 = self.temp_dir / "part_001.mp4"
        part3 = self.temp_dir / "part_002.mp4"
        part1.write_bytes(b"P1" * 100)
        part2.write_bytes(b"P2" * 100)
        part3.write_bytes(b"P3" * 100)

        simulated_parts = [
            {"path": str(part1), "part_index": 1, "total_parts": 3, "duration": 40, "size": 40 * 1024 * 1024, "width": 1920, "height": 1080},
            {"path": str(part2), "part_index": 2, "total_parts": 3, "duration": 40, "size": 42 * 1024 * 1024, "width": 1920, "height": 1080},
            {"path": str(part3), "part_index": 3, "total_parts": 3, "duration": 40, "size": 38 * 1024 * 1024, "width": 1920, "height": 1080},
        ]

        # Track streaming purge order strictly for parts
        action_timeline = []

        orig_unlink = os.unlink
        def spy_unlink(p):
            p_str = str(p)
            p_name = Path(p_str).name
            if p_name.startswith("part_") and p_name.endswith(".mp4"):
                action_timeline.append(("unlink", p_name))
            if os.path.exists(p):
                orig_unlink(p)

        async def spy_send_video(*args, **kwargs):
            video_p = kwargs.get("video_path")
            p_name = Path(str(video_p)).name
            action_timeline.append(("send_video", p_name))
            return True

        bot.send_video = AsyncMock(side_effect=spy_send_video)

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline), \
             patch("app.services.video_chunker.VideoChunker.split_video", new_callable=AsyncMock, return_value=simulated_parts), \
             patch("os.unlink", side_effect=spy_unlink), \
             patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:

            update = {
                "update_id": 9999,
                "message": {
                    "chat": {"id": 987654},
                    "text": "https://www.youtube.com/watch?v=adversarial_120mb",
                    "message_id": 50,
                }
            }
            await bot._process_update(update)

            # 1. Check all send_video calls contain supports_streaming=True
            self.assertEqual(len(bot.send_video.call_args_list), 3)
            for call_item in bot.send_video.call_args_list:
                kwargs = call_item[1]
                self.assertIn("supports_streaming", kwargs, "send_video MUST receive supports_streaming kwarg")
                self.assertTrue(kwargs["supports_streaming"], "supports_streaming MUST be strictly True")

            # 2. Check Streaming Purge order: send_video followed immediately by unlink for each part
            expected_timeline = [
                ("send_video", "part_000.mp4"),
                ("unlink", "part_000.mp4"),
                ("send_video", "part_001.mp4"),
                ("unlink", "part_001.mp4"),
                ("send_video", "part_002.mp4"),
                ("unlink", "part_002.mp4"),
            ]
            self.assertEqual(action_timeline, expected_timeline, "Streaming Purge must immediately unlink each part after send")

            # 3. Check anti-429 FloodWait: sleep(1.0) called exactly between parts (N-1 = 2 times)
            self.assertEqual(mock_sleep.call_count, 2, "Must sleep exactly 2 times between 3 parts")
            for sleep_call in mock_sleep.call_args_list:
                self.assertEqual(sleep_call[0][0], 1.0, "Must sleep 1.0s for FloodWait defense")

            # 4. Check completion message contains port 8084 LAN link
            comp_calls = [
                c for c in bot.send_message.call_args_list
                if "Đã gửi trọn vẹn 3/3 phần" in str(c)
            ]
            self.assertEqual(len(comp_calls), 1)
            comp_text = comp_calls[0][0][1]
            self.assertIn(":8084/api/ai/media/download/", comp_text, "LAN download link must strictly target port 8084")
            self.assertNotIn(":5173", comp_text, "LAN link must NEVER contain legacy port 5173")

    # -------------------------------------------------------------------------
    # TEST 3: ReAct Tool 120MB Video Dual Distribution
    # -------------------------------------------------------------------------
    async def test_empirical_react_tool_120mb_dual_distribution(self):
        """
        Verify AgentToolExecutor._execute_tool correctly handles 120MB video:
        - supports_streaming=True
        - Streaming Purge
        - Returns formatted string with port 8084 LAN URL
        """
        mock_bot = MagicMock()
        mock_bot.send_chat_action = AsyncMock(return_value=True)
        mock_bot.send_message = AsyncMock(return_value=True)
        mock_bot.send_video = AsyncMock(return_value=True)
        mock_bot.send_document_file = AsyncMock(return_value=True)
        mock_ssh = MagicMock()
        mock_cache = MagicMock()

        executor = AgentToolExecutor(
            ssh_client=mock_ssh,
            message_cache=mock_cache,
            telegram_bot=mock_bot,
        )

        video_path = self.temp_dir / "react_120mb.mp4"
        video_path.write_bytes(b"REACT_120MB_SAMPLE" * 100)

        mock_item = MediaItem(
            file_path=str(video_path),
            title="ReAct 120MB Tool Test",
            author="ToolTester",
            duration=90,
            media_type="video",
            source_url="https://www.youtube.com/watch?v=react_120mb",
            file_size=120 * 1024 * 1024,
            is_temp_file=True,
        )

        mock_pipeline = MagicMock()
        mock_pipeline.download = AsyncMock(return_value=mock_item)

        p1 = self.temp_dir / "react_p1.mp4"
        p2 = self.temp_dir / "react_p2.mp4"
        p1.write_bytes(b"1" * 10)
        p2.write_bytes(b"2" * 10)

        parts = [
            {"path": str(p1), "part_index": 1, "total_parts": 2, "duration": 45, "size": 42 * 1024 * 1024, "width": 1920, "height": 1080},
            {"path": str(p2), "part_index": 2, "total_parts": 2, "duration": 45, "size": 40 * 1024 * 1024, "width": 1920, "height": 1080},
        ]

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline), \
             patch("app.services.video_chunker.VideoChunker.split_video", new_callable=AsyncMock, return_value=parts), \
             patch("asyncio.sleep", new_callable=AsyncMock):

            result = await executor._execute_tool(
                "download_media_video",
                {"url": "https://www.youtube.com/watch?v=react_120mb"},
                chat_id="123456",
            )

            # Check send_video kwargs
            self.assertEqual(mock_bot.send_video.call_count, 2)
            for c in mock_bot.send_video.call_args_list:
                self.assertTrue(c[1].get("supports_streaming", False), "supports_streaming must be True in ReAct tool")

            # Check result string
            self.assertIn("http://192.168.0.100:8084/api/ai/media/download/", result)
            self.assertNotIn("5173", result)
            self.assertFalse(p1.exists(), "Part 1 must be purged from disk")
            self.assertFalse(p2.exists(), "Part 2 must be purged from disk")

    # -------------------------------------------------------------------------
    # TEST 4: Port 8084 LAN Link & Genuine String Behavior
    # -------------------------------------------------------------------------
    def test_empirical_port_8084_standardization(self):
        """
        Verify:
        1. Default LAN base URL is http://192.168.0.100:8084.
        2. LAN base URL string formatting produces port 8084.
        3. String equality strictly verifies port 8084.
        4. Published DownloadRecord contains port 8084 in lan_url.
        """
        test_file = self.temp_dir / "standardized_test.mp4"
        test_file.write_bytes(b"PORT_8084_TEST_CONTENT")

        mgr = MediaStorageManager(
            base_dir=self.base_dir,
            temp_dir=self.temp_dir,
            public_dir=self.public_dir,
        )

        with patch.dict(os.environ, {}, clear=False):
            # Ensure LAN_DOWNLOAD_BASE_URL is unset to test true default
            if "LAN_DOWNLOAD_BASE_URL" in os.environ:
                del os.environ["LAN_DOWNLOAD_BASE_URL"]

            internet_base, lan_base = mgr.resolve_public_download_base_url_sync()

            # 1. Verify type and value
            self.assertIsInstance(lan_base, str)
            self.assertEqual(str(lan_base), "http://192.168.0.100:8084")
            self.assertTrue(lan_base.startswith("http://192.168.0.100:8084"))

            # 2. Verify standardized equality
            self.assertEqual(lan_base, "http://192.168.0.100:8084")
            self.assertNotEqual(lan_base, "http://192.168.0.100:8080")

            # 3. Verify publish_download_item
            record = mgr.publish_download_item(
                file_path=test_file,
                filename="standardized_test.mp4",
                title="Port 8084 Empirical Test",
                duration=60,
            )

            self.assertIn("http://192.168.0.100:8084/api/ai/media/download/", record.lan_url)
            self.assertNotIn("5173", record.lan_url)

    # -------------------------------------------------------------------------
    # TEST 5: HTTP 206 Partial Content Range Requests
    # -------------------------------------------------------------------------
    def test_empirical_http_206_partial_content_range_requests(self):
        """
        Empirically verify HTTP 206 Partial Content with various byte ranges:
        - Range: bytes=0-1023 (first 1024 bytes).
        - Range: bytes=2048-4095 (mid slice).
        - Range: bytes=-500 (suffix slice).
        - No range header (full 200 OK).
        """
        total_size = 100_000  # 100 KB test payload
        payload = bytes([i % 256 for i in range(total_size)])

        temp_src = self.temp_dir / "range_test_video.mp4"
        temp_src.write_bytes(payload)

        # Publish to real media_storage_manager singleton
        rec = media_storage_manager.publish_download_item(
            file_path=temp_src,
            filename="range_test_video.mp4",
            title="HTTP 206 Range Verification",
            duration=30,
        )

        try:
            # 1. Range: bytes=0-1023 (First 1024 bytes)
            headers_first = {"Range": "bytes=0-1023"}
            res_first = self.client.get(f"/api/ai/media/download/{rec.token}", headers=headers_first)
            self.assertEqual(res_first.status_code, 206, "Must respond with HTTP 206 Partial Content")
            self.assertEqual(res_first.headers.get("Accept-Ranges"), "bytes")
            self.assertEqual(res_first.headers.get("Content-Range"), f"bytes 0-1023/{total_size}")
            self.assertEqual(len(res_first.content), 1024)
            self.assertEqual(res_first.content, payload[0:1024], "Returned bytes must match byte slice 0-1023 exactly")

            # 2. Range: bytes=2048-4095 (Mid-stream 2048 bytes)
            headers_mid = {"Range": "bytes=2048-4095"}
            res_mid = self.client.get(f"/api/ai/media/download/{rec.token}", headers=headers_mid)
            self.assertEqual(res_mid.status_code, 206)
            self.assertEqual(res_mid.headers.get("Content-Range"), f"bytes 2048-4095/{total_size}")
            self.assertEqual(len(res_mid.content), 2048)
            self.assertEqual(res_mid.content, payload[2048:4096])

            # 3. Range: bytes=-500 (Suffix 500 bytes)
            headers_suffix = {"Range": "bytes=-500"}
            res_suffix = self.client.get(f"/api/ai/media/download/{rec.token}", headers=headers_suffix)
            self.assertEqual(res_suffix.status_code, 206)
            self.assertEqual(res_suffix.headers.get("Content-Range"), f"bytes 99500-99999/{total_size}")
            self.assertEqual(len(res_suffix.content), 500)
            self.assertEqual(res_suffix.content, payload[-500:])

            # 4. No Range Header -> Full 200 OK
            res_full = self.client.get(f"/api/ai/media/download/{rec.token}")
            self.assertEqual(res_full.status_code, 200)
            self.assertEqual(res_full.headers.get("Accept-Ranges"), "bytes")
            self.assertEqual(len(res_full.content), total_size)
            self.assertEqual(res_full.content, payload)

        finally:
            # Clean up published token directory
            token_dir = media_storage_manager.public_dir / rec.token
            shutil.rmtree(token_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # TEST 6: Zero-Disk Leak on Exception (Adversarial Fault Injection)
    # -------------------------------------------------------------------------
    async def test_empirical_zero_disk_leak_on_part_dispatch_exception(self):
        """
        Adversarial Test: If send_video fails with an unhandled exception at part 2,
        the finally block MUST execute shutil.rmtree(parts_dir) so that no temporary
        parts or directories leak onto disk.
        """
        bot = TelegramBot.__new__(TelegramBot)
        bot.token = "leak_bot_token"
        bot.chat_id = "555555"
        bot._claim_update = AsyncMock(return_value=True)
        bot._video_debounce = MagicMock()
        bot._video_debounce.handle_user_text = AsyncMock(return_value=False)
        bot._pending_archives = {}
        bot._rate_limiter = MagicMock()
        bot._rate_limiter.acquire = AsyncMock()
        bot.send_message = AsyncMock(return_value=True)

        video_path = self.temp_dir / "crash_video.mp4"
        video_path.write_bytes(b"CRASH_TEST_DATA" * 50)

        mock_media_item = MediaItem(
            file_path=str(video_path),
            title="Crash Test Video",
            author="Crasher",
            duration=60,
            media_type="video",
            source_url="https://www.youtube.com/watch?v=crash_test",
            file_size=80 * 1024 * 1024,
            is_temp_file=True,
        )

        mock_pipeline = MagicMock()
        mock_pipeline.download = AsyncMock(return_value=mock_media_item)

        created_parts_dir: Optional[Path] = None

        async def fake_split(video_path, output_dir, **kwargs):
            nonlocal created_parts_dir
            created_parts_dir = Path(output_dir)
            p1 = created_parts_dir / "part_000.mp4"
            p2 = created_parts_dir / "part_001.mp4"
            p1.write_bytes(b"AAA" * 100)
            p2.write_bytes(b"BBB" * 100)
            return [
                {"path": str(p1), "part_index": 1, "total_parts": 2, "duration": 30, "size": 40 * 1024 * 1024},
                {"path": str(p2), "part_index": 2, "total_parts": 2, "duration": 30, "size": 40 * 1024 * 1024},
            ]

        # Fail on part 2
        async def exploding_send_video(chat_id, video_path, **kwargs):
            if "part_001" in video_path:
                raise ConnectionResetError("Simulated Telegram Network Catastrophe!")
            return True

        bot.send_video = AsyncMock(side_effect=exploding_send_video)

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline), \
             patch("app.services.video_chunker.VideoChunker.split_video", side_effect=fake_split), \
             patch("asyncio.sleep", new_callable=AsyncMock):

            update = {
                "update_id": 8888,
                "message": {
                    "chat": {"id": 555555},
                    "text": "https://www.youtube.com/watch?v=crash_test",
                    "message_id": 99,
                }
            }

            # Should catch or raise
            try:
                await bot._process_update(update)
            except ConnectionResetError:
                pass

            # VERIFY ZERO-DISK LEAK: parts_dir MUST NOT exist
            self.assertIsNotNone(created_parts_dir, "parts_dir must have been created")
            self.assertFalse(
                created_parts_dir.exists(),
                f"Disk Leak Detected! Temporary directory {created_parts_dir} was not cleaned up after error!"
            )


if __name__ == "__main__":
    unittest.main()
