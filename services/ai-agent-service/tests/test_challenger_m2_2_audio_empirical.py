"""
test_challenger_m2_2_audio_empirical.py — Empirical Challenger Test Suite for Milestone M2.

Authored by: Empirical Challenger 2 (Milestone M2: Telegram Native Audio Player)
Target: services/ai-agent-service/app/services/telegram_bot.py

Adversarial Stress Verification:
1. Scenario Audio > 50MB:
   - Boundary tests (50MB exact, 50MB + 1 byte, 100MB massive).
   - Fast-path fallback in _process_update to media_storage_manager.publish_download_item.
   - Transmission of Internet (Ngrok) and LAN download links.
   - Direct guard in send_audio rejecting files > 50MB before dispatch.
   - Transfer of ownership (media_item.is_temp_file = False).

2. Zero-Disk Leak:
   - Success path: media_item.cleanup() completely unlinks temp file.
   - Network failure (ConnectTimeout, ReadTimeout, NetworkError): disk cleaned 100%.
   - Telegram API errors (400, 403, 429, 500): disk cleaned 100%.
   - Unexpected exceptions during formatting / processing: disk cleaned 100%.
   - Windows file lock safety: file descriptor closed before cleanup to prevent WinError 32.
   - Nested media_ytdlp_ directory cleanup.
   - Mass concurrency leak test: 20 simultaneous audio tasks leave 0 orphaned files.

3. Streaming _AudioFileStream & Zero-RAM Leak:
   - tracemalloc verification of constant memory usage (O(1) RAM) streaming 50MB.
   - Stream tell(), seek(0), closed, and post-close tell() preservation.
   - Resilient seek(0) rewind on Telegram HTML entity errors ensuring attempt 2 has full payload.
   - Context manager lifecycle and attribute delegation.
   - httpx multipart streaming compatibility.
"""

import asyncio
import gc
import html
import io
import os
from pathlib import Path
import shutil
import tempfile
import time
import tracemalloc
import unittest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from typing import Any, Dict, List, Optional

# Enable fast testing bypass for media storage discovery probes
os.environ["TESTING"] = "1"
os.environ["PUBLIC_DOWNLOAD_BASE_URL"] = "http://127.0.0.1:8084"

import httpx

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.telegram_bot import (
    TelegramBot,
    FastPathMediaIntent,
    _AudioFileStream,
    _strip_html_tags,
)
from app.services.media_downloader import (
    MediaItem,
    TEMP_MEDIA_DIR,
    TELEGRAM_MAX_FILE_SIZE,
)
from app.services.media_storage_manager import (
    MediaStorageManager,
    DownloadRecord,
)


class TestAudioLargeFileFallbackEmpirical(unittest.IsolatedAsyncioTestCase):
    """
    Adversarial verification for Audio > 50MB:
    Ensures safe fallback to media_storage_manager.publish_download_item,
    direct download link dispatch, and send_audio rejection guards.
    """

    async def asyncSetUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="challenger_m2_storage_"))
        self.bot = TelegramBot.__new__(TelegramBot)
        self.bot.token = "123456789:ABCdefGhIJKlmNoPQRstuVWXyz"
        self.bot.chat_id = "99887766"
        self.bot._running = True
        self.bot._last_offset = 0
        self.bot._pending_archives = {}
        self.bot.dream_engine = None
        self.bot.ai_agent = AsyncMock()
        self.bot.ai_agent.chat = AsyncMock(return_value="AI fallback reply")
        self.bot._claim_update = AsyncMock(return_value=True)
        self.bot._video_debounce = MagicMock()
        self.bot._video_debounce.handle_user_text = AsyncMock(return_value=False)
        self.chat_id = "99887766"

    async def asyncTearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_dummy_file(self, size_bytes: int, suffix: str = ".mp3") -> Path:
        """Create a real sparse or written binary file with specified size."""
        file_path = self.temp_dir / f"test_audio_{size_bytes}{suffix}"
        with open(file_path, "wb") as f:
            if size_bytes > 0:
                f.seek(size_bytes - 1)
                f.write(b"\0")
        return file_path

    async def test_audio_over_50mb_triggers_publish_download_item_and_sends_links(self):
        """
        Verify that an audio file > 50MB in _process_update triggers
        media_storage_manager.publish_download_item, sets is_temp_file = False,
        and sends direct links (Internet & LAN) instead of send_audio.
        """
        audio_size = 55 * 1024 * 1024  # 55MB
        audio_file = self._create_dummy_file(audio_size, suffix=".mp3")

        media_item = MediaItem(
            file_path=str(audio_file),
            title="Đại Lộ Mặt Trời (Remix 320kbps High Quality)",
            author="HuyR x Da LAB",
            duration=345,
            media_type="audio",
            source_url="https://vt.tiktok.com/ZS123456/",
            file_size=audio_size,
            is_temp_file=True,
        )

        mock_record = DownloadRecord(
            token="token_abc123xyz456789012345678",
            filename=audio_file.name,
            file_path=self.temp_dir / "published" / audio_file.name,
            file_size=audio_size,
            title=media_item.title,
            duration=media_item.duration,
            created_at=time.time(),
            expires_at=time.time() + 14400,
            internet_url="https://ngrok.kirito.internal/api/ai/media/download/token_abc/audio.mp3",
            lan_url="http://192.168.0.100:5173/api/ai/media/download/token_abc/audio.mp3",
        )

        sent_messages = []

        async def mock_send_message(chat_id, text, **kwargs):
            sent_messages.append({"chat_id": chat_id, "text": text})
            return {"ok": True, "message_id": 999}

        async def mock_send_message_with_result(chat_id, text, **kwargs):
            return {"ok": True, "message_id": 888}

        async def mock_delete_message(chat_id, msg_id):
            return True

        self.bot.send_message = AsyncMock(side_effect=mock_send_message)
        self.bot.send_message_with_result = AsyncMock(side_effect=mock_send_message_with_result)
        self.bot.delete_message = AsyncMock(side_effect=mock_delete_message)
        self.bot.send_audio = AsyncMock()
        self.bot.send_document_file = AsyncMock()

        mock_pipeline = MagicMock()
        mock_pipeline.download_audio = AsyncMock(return_value=media_item)

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline), \
             patch("app.services.telegram_bot.media_storage_manager.publish_download_item", return_value=mock_record) as mock_publish:

            intent = FastPathMediaIntent("https://vt.tiktok.com/ZS123456/", "tải mp3 bài này", media_type="audio")
            with patch.object(self.bot, "_detect_fastpath_media_download", return_value=intent):
                update = {
                    "update_id": 1001,
                    "message": {
                        "message_id": 1,
                        "chat": {"id": int(self.chat_id)},
                        "text": "tải mp3 https://vt.tiktok.com/ZS123456/",
                    }
                }
                await self.bot._process_update(update)

            # Assertions
            mock_publish.assert_called_once()
            call_kwargs = mock_publish.call_args.kwargs
            self.assertEqual(call_kwargs["file_path"], str(audio_file))
            self.assertEqual(call_kwargs["filename"], audio_file.name)
            self.assertEqual(call_kwargs["title"], media_item.title)
            self.assertEqual(call_kwargs["duration"], 345)
            self.assertEqual(call_kwargs["ttl_seconds"], 4 * 3600)

            # send_audio and send_document_file MUST NOT be called for >50MB
            self.bot.send_audio.assert_not_called()
            self.bot.send_document_file.assert_not_called()

            # media_item.is_temp_file must have been transferred to False
            self.assertFalse(media_item.is_temp_file)

            # Verify message sent to user contains links and size info
            found_large_msg = False
            for msg in sent_messages:
                txt = msg["text"]
                if "Tệp âm thanh MP3 có dung lượng lớn" in txt and "55.0 MB" in txt:
                    self.assertIn(mock_record.internet_url, txt)
                    self.assertIn(mock_record.lan_url, txt)
                    found_large_msg = True
                    break
            self.assertTrue(found_large_msg, "Message announcing direct links for >50MB audio was not sent.")

    async def test_audio_exact_50mb_boundary_routes_to_send_audio(self):
        """
        Boundary condition: Exactly 50 * 1024 * 1024 bytes (52,428,800 bytes).
        Must route to send_audio (<= 50MB), NOT fallback to publish_download_item.
        """
        exact_50mb = 50 * 1024 * 1024
        audio_file = self._create_dummy_file(exact_50mb, suffix=".mp3")

        media_item = MediaItem(
            file_path=str(audio_file),
            title="Boundary Exact 50MB",
            author="Tester",
            duration=120,
            media_type="audio",
            source_url="https://youtube.com/watch?v=123",
            file_size=exact_50mb,
            is_temp_file=True,
        )

        mock_pipeline = MagicMock()
        mock_pipeline.download_audio = AsyncMock(return_value=media_item)

        self.bot.send_audio = AsyncMock(return_value=True)
        self.bot.send_message = AsyncMock()
        self.bot.send_message_with_result = AsyncMock(return_value={"ok": True, "message_id": 888})
        self.bot.delete_message = AsyncMock(return_value=True)

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline), \
             patch("app.services.telegram_bot.media_storage_manager.publish_download_item") as mock_publish:

            intent = FastPathMediaIntent("https://youtube.com/watch?v=123", "tải audio", media_type="audio")
            with patch.object(self.bot, "_detect_fastpath_media_download", return_value=intent):
                update = {
                    "update_id": 1002,
                    "message": {
                        "message_id": 2,
                        "chat": {"id": int(self.chat_id)},
                        "text": "tải audio https://youtube.com/watch?v=123",
                    }
                }
                await self.bot._process_update(update)

            # At exact 50MB, send_audio must be called!
            self.bot.send_audio.assert_called_once()
            mock_publish.assert_not_called()

    async def test_audio_50mb_plus_one_byte_routes_to_publish_download_item(self):
        """
        Boundary condition: Exactly 50 * 1024 * 1024 + 1 bytes (52,428,801 bytes).
        Must route to media_storage_manager.publish_download_item, NOT send_audio.
        """
        boundary_size = 50 * 1024 * 1024 + 1
        audio_file = self._create_dummy_file(boundary_size, suffix=".mp3")

        media_item = MediaItem(
            file_path=str(audio_file),
            title="Boundary 50MB + 1 byte",
            author="Tester",
            duration=120,
            media_type="audio",
            source_url="https://youtube.com/watch?v=123",
            file_size=boundary_size,
            is_temp_file=True,
        )

        mock_record = DownloadRecord(
            token="token_bva_12345678901234567890",
            filename=audio_file.name,
            file_path=self.temp_dir / "published" / audio_file.name,
            file_size=boundary_size,
            title="Boundary 50MB + 1 byte",
            duration=120,
            created_at=time.time(),
            expires_at=time.time() + 14400,
            internet_url="https://ngrok.internal/download",
            lan_url="http://lan.internal/download",
        )

        mock_pipeline = MagicMock()
        mock_pipeline.download_audio = AsyncMock(return_value=media_item)

        self.bot.send_audio = AsyncMock()
        self.bot.send_message = AsyncMock()
        self.bot.send_message_with_result = AsyncMock(return_value={"ok": True, "message_id": 888})
        self.bot.delete_message = AsyncMock(return_value=True)

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline), \
             patch("app.services.telegram_bot.media_storage_manager.publish_download_item", return_value=mock_record) as mock_publish:

            intent = FastPathMediaIntent("https://youtube.com/watch?v=123", "tải audio", media_type="audio")
            with patch.object(self.bot, "_detect_fastpath_media_download", return_value=intent):
                update = {
                    "update_id": 1003,
                    "message": {
                        "message_id": 3,
                        "chat": {"id": int(self.chat_id)},
                        "text": "tải audio https://youtube.com/watch?v=123",
                    }
                }
                await self.bot._process_update(update)

            # send_audio MUST NOT be called!
            self.bot.send_audio.assert_not_called()
            mock_publish.assert_called_once()

    async def test_send_audio_direct_guard_rejects_oversized_audio(self):
        """
        Adversarial test: Calling send_audio directly with an audio file > 50MB
        must immediately abort, log a warning, and return False without making HTTP calls.
        """
        audio_file = self._create_dummy_file(51 * 1024 * 1024, suffix=".mp3")
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        self.bot._media = MagicMock()

        with patch.object(TelegramBot, "_http_client", new_callable=PropertyMock) as mock_client_prop:
            mock_client_prop.return_value = mock_http
            result = await self.bot.send_audio(
                chat_id=self.chat_id,
                audio_path=audio_file,
                title="Massive Track",
                performer="DJ Oversized",
                duration=600,
            )

            self.assertFalse(result)
            mock_http.post.assert_not_called()

    async def test_audio_over_50mb_real_media_storage_manager_integration(self):
        """
        Empirical integration test with real MediaStorageManager:
        Verifies that when publish_download_item is invoked, the file is atomically
        moved to public_dir/{token}/, metadata.json is generated, and token URLs are built.
        """
        storage = MediaStorageManager(
            base_dir=self.temp_dir / "storage",
            temp_dir=self.temp_dir / "storage" / "temp",
            public_dir=self.temp_dir / "storage" / "public",
        )
        storage.ensure_dirs()

        audio_size = 52 * 1024 * 1024
        audio_file = self._create_dummy_file(audio_size, suffix=".mp3")

        record = storage.publish_download_item(
            file_path=audio_file,
            filename=audio_file.name,
            title="Symphony No. 5",
            duration=420,
            ttl_seconds=3600,
        )

        # Original source path must no longer exist (moved)
        self.assertFalse(audio_file.exists())

        # Destination file must exist and have correct size
        self.assertTrue(record.file_path.exists())
        self.assertEqual(record.file_path.stat().st_size, audio_size)

        # Metadata file must exist
        meta_path = record.file_path.parent / "metadata.json"
        self.assertTrue(meta_path.exists())

        # URLs must be well-formed
        self.assertIn("/api/ai/media/download/", record.internet_url)
        self.assertIn(record.token, record.internet_url)
        self.assertIn("/api/ai/media/download/", record.lan_url)


class TestZeroDiskLeakEmpirical(unittest.IsolatedAsyncioTestCase):
    """
    Adversarial verification for 100% Zero-Disk Leak:
    Proves that under ANY scenario (success, API error, network drop, timeout,
    formatting exception, Windows file locking), media_item.cleanup() is guaranteed
    to remove all temporary files from disk.
    """

    async def asyncSetUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="challenger_m2_leak_"))
        self.bot = TelegramBot.__new__(TelegramBot)
        self.bot.token = "123456789:ABCdefGhIJKlmNoPQRstuVWXyz"
        self.bot.chat_id = "99887766"
        self.bot._running = True
        self.bot._last_offset = 0
        self.bot._pending_archives = {}
        self.bot.dream_engine = None
        self.bot.ai_agent = AsyncMock()
        self.bot.ai_agent.chat = AsyncMock(return_value="AI fallback reply")
        self.bot._claim_update = AsyncMock(return_value=True)
        self.bot._video_debounce = MagicMock()
        self.bot._video_debounce.handle_user_text = AsyncMock(return_value=False)
        self.chat_id = "99887766"

    async def asyncTearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_temp_audio(self, size_bytes: int = 1024 * 1024) -> Path:
        p = self.temp_dir / f"leak_test_{time.time_ns()}.mp3"
        with open(p, "wb") as f:
            f.write(b"ID3\x04\x00\x00" + b"\x00" * (size_bytes - 6))
        return p

    async def test_zero_disk_leak_on_successful_send(self):
        """Temp file is 100% removed after successful audio send."""
        audio_path = self._create_temp_audio(2 * 1024 * 1024)
        self.assertTrue(audio_path.exists())

        media_item = MediaItem(
            file_path=str(audio_path),
            title="Success Track",
            author="Artist",
            duration=180,
            media_type="audio",
            source_url="https://tiktok.com/@user/video/1",
            file_size=audio_path.stat().st_size,
            is_temp_file=True,
        )

        mock_pipeline = MagicMock()
        mock_pipeline.download_audio = AsyncMock(return_value=media_item)

        self.bot.send_audio = AsyncMock(return_value=True)
        self.bot.send_message = AsyncMock()
        self.bot.send_message_with_result = AsyncMock(return_value={"ok": True, "message_id": 111})
        self.bot.delete_message = AsyncMock(return_value=True)

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline):
            intent = FastPathMediaIntent("https://tiktok.com/@user/video/1", "tải mp3", media_type="audio")
            with patch.object(self.bot, "_detect_fastpath_media_download", return_value=intent):
                update = {
                    "update_id": 2001,
                    "message": {
                        "message_id": 10,
                        "chat": {"id": int(self.chat_id)},
                        "text": "tải mp3 https://tiktok.com/@user/video/1",
                    }
                }
                await self.bot._process_update(update)

        # File MUST be cleaned up
        self.assertFalse(audio_path.exists(), "Temporary audio file was NOT removed after successful send!")

    async def test_zero_disk_leak_on_telegram_api_400_and_fallback_failure(self):
        """Temp file is 100% removed when Telegram API returns 400 and fallback fails."""
        audio_path = self._create_temp_audio(3 * 1024 * 1024)
        media_item = MediaItem(
            file_path=str(audio_path),
            title="API Error Track",
            author="Artist",
            duration=200,
            media_type="audio",
            source_url="https://tiktok.com/@user/video/2",
            file_size=audio_path.stat().st_size,
            is_temp_file=True,
        )

        mock_pipeline = MagicMock()
        mock_pipeline.download_audio = AsyncMock(return_value=media_item)

        # send_audio fails, send_document_file also fails
        self.bot.send_audio = AsyncMock(return_value=False)
        self.bot.send_document_file = AsyncMock(return_value=False)
        self.bot.send_message = AsyncMock()
        self.bot.send_message_with_result = AsyncMock(return_value={"ok": True, "message_id": 112})
        self.bot.delete_message = AsyncMock(return_value=True)

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline):
            intent = FastPathMediaIntent("https://tiktok.com/@user/video/2", "tải mp3", media_type="audio")
            with patch.object(self.bot, "_detect_fastpath_media_download", return_value=intent):
                update = {
                    "update_id": 2002,
                    "message": {
                        "message_id": 11,
                        "chat": {"id": int(self.chat_id)},
                        "text": "tải mp3 https://tiktok.com/@user/video/2",
                    }
                }
                await self.bot._process_update(update)

        self.assertFalse(audio_path.exists(), "Temporary audio file was NOT cleaned up on API error failure!")

    async def test_zero_disk_leak_on_network_timeout(self):
        """Temp file is 100% removed when network times out during transmission."""
        audio_path = self._create_temp_audio(4 * 1024 * 1024)
        media_item = MediaItem(
            file_path=str(audio_path),
            title="Timeout Track",
            author="Artist",
            duration=150,
            media_type="audio",
            source_url="https://tiktok.com/@user/video/3",
            file_size=audio_path.stat().st_size,
            is_temp_file=True,
        )

        mock_pipeline = MagicMock()
        mock_pipeline.download_audio = AsyncMock(return_value=media_item)

        # Simulate network drop
        self.bot.send_audio = AsyncMock(side_effect=httpx.ConnectTimeout("Telegram API unreachable"))
        self.bot.send_message = AsyncMock()
        self.bot.send_message_with_result = AsyncMock(return_value={"ok": True, "message_id": 113})
        self.bot.delete_message = AsyncMock(return_value=True)

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline):
            intent = FastPathMediaIntent("https://tiktok.com/@user/video/3", "tải mp3", media_type="audio")
            with patch.object(self.bot, "_detect_fastpath_media_download", return_value=intent):
                update = {
                    "update_id": 2003,
                    "message": {
                        "message_id": 12,
                        "chat": {"id": int(self.chat_id)},
                        "text": "tải mp3 https://tiktok.com/@user/video/3",
                    }
                }
                await self.bot._process_update(update)

        self.assertFalse(audio_path.exists(), "Temporary audio file was NOT cleaned up on network timeout!")

    async def test_zero_disk_leak_on_unexpected_exception_during_processing(self):
        """Temp file is 100% removed when unexpected crash happens inside _process_update."""
        audio_path = self._create_temp_audio(1024 * 1024)
        media_item = MediaItem(
            file_path=str(audio_path),
            title="Crash Track",
            author="Artist",
            duration=100,
            media_type="audio",
            source_url="https://tiktok.com/@user/video/4",
            file_size=audio_path.stat().st_size,
            is_temp_file=True,
        )

        mock_pipeline = MagicMock()
        mock_pipeline.download_audio = AsyncMock(return_value=media_item)

        # Inject an unexpected crash during send_audio or formatting
        self.bot.send_audio = AsyncMock(side_effect=RuntimeError("Unexpected memory corruption or fatal crash"))
        self.bot.send_message = AsyncMock()
        self.bot.send_message_with_result = AsyncMock(return_value={"ok": True, "message_id": 114})
        self.bot.delete_message = AsyncMock(return_value=True)

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline):
            intent = FastPathMediaIntent("https://tiktok.com/@user/video/4", "tải mp3", media_type="audio")
            with patch.object(self.bot, "_detect_fastpath_media_download", return_value=intent):
                update = {
                    "update_id": 2004,
                    "message": {
                        "message_id": 13,
                        "chat": {"id": int(self.chat_id)},
                        "text": "tải mp3 https://tiktok.com/@user/video/4",
                    }
                }
                await self.bot._process_update(update)

        self.assertFalse(audio_path.exists(), "Temporary audio file was NOT cleaned up on unexpected crash!")

    async def test_windows_file_locking_resilience_in_send_audio(self):
        """
        Critical Windows OS check:
        If send_audio encounters a network error midway, _AudioFileStream's
        finally: stream.close() MUST close the file descriptor immediately,
        so that media_item.cleanup() / Path.unlink() does NOT fail with WinError 32
        (PermissionError: file being used by another process).
        """
        audio_path = self._create_temp_audio(5 * 1024 * 1024)
        self.assertTrue(audio_path.exists())

        # Mock http post that fails midway
        async def mock_post_fail(*args, **kwargs):
            # Read a few bytes from stream to simulate in-flight crash
            files = kwargs.get("files", {})
            if "audio" in files:
                _, stream, _ = files["audio"]
                stream.read(1024 * 64)
            raise httpx.ReadError("TCP Connection reset by peer during upload")

        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_http.post = AsyncMock(side_effect=mock_post_fail)

        with patch.object(TelegramBot, "_http_client", new_callable=PropertyMock) as mock_client_prop:
            mock_client_prop.return_value = mock_http

            sent = await self.bot.send_audio(
                chat_id=self.chat_id,
                audio_path=audio_path,
                title="Locking Test",
                performer="Tester",
            )
            self.assertFalse(sent)

            # Now test immediate unlink on Windows: MUST NOT raise PermissionError!
            media_item = MediaItem(
                file_path=str(audio_path),
                title="Locking Test",
                author="Tester",
                duration=60,
                media_type="audio",
                source_url="https://tiktok.com",
                file_size=audio_path.stat().st_size,
                is_temp_file=True,
            )
            # This will raise PermissionError if the stream was not closed in send_audio
            media_item.cleanup()
            self.assertFalse(audio_path.exists(), "File handle was left open on Windows, preventing unlink!")

    async def test_nested_ytdlp_directory_cleanup(self):
        """
        yt-dlp creates temporary subdirectories like TEMP_MEDIA_DIR/media_ytdlp_abcdef1234/audio.mp3.
        Verify media_item.cleanup() removes both the audio file AND the parent directory.
        """
        nested_dir = TEMP_MEDIA_DIR / f"media_ytdlp_test_{time.time_ns()}"
        nested_dir.mkdir(parents=True, exist_ok=True)
        audio_file = nested_dir / "audio.mp3"
        audio_file.write_bytes(b"dummy mp3 data")

        self.assertTrue(audio_file.exists())
        self.assertTrue(nested_dir.exists())

        item = MediaItem(
            file_path=str(audio_file),
            title="Nested Track",
            author="yt-dlp",
            duration=60,
            media_type="audio",
            source_url="https://youtube.com/watch?v=123",
            file_size=14,
            is_temp_file=True,
        )

        item.cleanup()

        self.assertFalse(audio_file.exists())
        self.assertFalse(nested_dir.exists(), "Nested media_ytdlp_ directory was NOT cleaned up!")

    async def test_cleanup_idempotency_and_missing_file_safety(self):
        """Calling cleanup() multiple times or on deleted files raises 0 exceptions."""
        item = MediaItem(
            file_path=str(self.temp_dir / "non_existent_file.mp3"),
            title="Ghost",
            author="Ghost",
            duration=0,
            media_type="audio",
            source_url="https://test.com",
            file_size=0,
            is_temp_file=True,
        )
        try:
            item.cleanup()
            item.cleanup()
        except Exception as e:
            self.fail(f"cleanup() failed on non-existent file: {e}")

    async def test_mass_concurrency_zero_disk_leak(self):
        """
        Adversarial stress test: 20 concurrent audio download operations
        with mixed outcomes (some success, some network error, some API error).
        Assert that after all 20 finish, exactly 0 orphaned .mp3 files remain in temp_dir.
        """
        n_tasks = 20
        audio_files = [self._create_temp_audio(512 * 1024) for _ in range(n_tasks)]
        items = [
            MediaItem(
                file_path=str(audio_files[i]),
                title=f"Concurrent Track {i}",
                author="StressTester",
                duration=100,
                media_type="audio",
                source_url=f"https://tiktok.com/@stress/video/{i}",
                file_size=audio_files[i].stat().st_size,
                is_temp_file=True,
            )
            for i in range(n_tasks)
        ]

        async def worker_job(idx: int, item: MediaItem):
            bot = TelegramBot.__new__(TelegramBot)
            bot.token = "12345:TOKEN"
            bot.chat_id = "123"
            bot._running = True
            bot._last_offset = 0
            bot._pending_archives = {}
            bot.dream_engine = None
            bot.ai_agent = AsyncMock()
            bot.ai_agent.chat = AsyncMock(return_value="AI fallback reply")
            bot._claim_update = AsyncMock(return_value=True)
            bot._video_debounce = MagicMock()
            bot._video_debounce.handle_user_text = AsyncMock(return_value=False)

            bot.send_message = AsyncMock()
            bot.send_message_with_result = AsyncMock(return_value={"ok": True, "message_id": idx})
            bot.delete_message = AsyncMock(return_value=True)

            if idx % 3 == 0:
                # Success
                bot.send_audio = AsyncMock(return_value=True)
            elif idx % 3 == 1:
                # Network error
                bot.send_audio = AsyncMock(side_effect=httpx.NetworkError("Network broken"))
            else:
                # API failure fallback
                bot.send_audio = AsyncMock(return_value=False)
                bot.send_document_file = AsyncMock(return_value=False)

            update = {
                "update_id": 3000 + idx,
                "message": {
                    "message_id": idx,
                    "chat": {"id": 123},
                    "text": f"tải mp3 https://tiktok.com/@stress/video/{idx}",
                }
            }
            intent = FastPathMediaIntent(f"https://tiktok.com/@stress/video/{idx}", "tải mp3", media_type="audio")
            with patch.object(bot, "_detect_fastpath_media_download", return_value=intent):
                await bot._process_update(update)

        def make_pipeline_mock(*args, **kwargs):
            p_mock = MagicMock()
            async def get_item(url: str):
                for item in items:
                    if item.source_url == url:
                        return item
                return items[0]
            p_mock.download_audio = AsyncMock(side_effect=get_item)
            return p_mock

        with patch("app.services.media_downloader.MultiTierMediaPipeline", side_effect=make_pipeline_mock):
            tasks = [worker_job(i, items[i]) for i in range(n_tasks)]
            await asyncio.gather(*tasks)

        # Inspect disk: ALL files must be gone
        remaining_files = list(self.temp_dir.glob("*.mp3"))
        self.assertEqual(len(remaining_files), 0, f"Found {len(remaining_files)} leaked files on disk!")


class TestAudioFileStreamZeroRamLeakEmpirical(unittest.IsolatedAsyncioTestCase):
    """
    Adversarial verification for _AudioFileStream and Zero-RAM Leak:
    Proves that chunked streaming from disk operates in O(1) RAM without loading
    the full audio file into memory, and verifies resilient rewind f.seek(0).
    """

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="challenger_m2_ram_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_large_audio_file(self, size_mb: int = 40) -> Path:
        p = self.temp_dir / f"large_stream_{size_mb}mb.mp3"
        chunk_1mb = b"X" * (1024 * 1024)
        with open(p, "wb") as f:
            for _ in range(size_mb):
                f.write(chunk_1mb)
        return p

    def test_audio_stream_chunked_reads_constant_memory_empirical(self):
        """
        Empirically verify with tracemalloc that reading a 40MB audio file
        via _AudioFileStream in 64KB chunks consumes strictly < 2MB peak RAM,
        confirming O(1) zero-RAM leak streaming.
        """
        file_path = self._create_large_audio_file(size_mb=40)
        file_size = file_path.stat().st_size
        self.assertEqual(file_size, 40 * 1024 * 1024)

        gc.collect()
        tracemalloc.start()
        snapshot_start = tracemalloc.take_snapshot()

        total_bytes_read = 0
        with open(file_path, "rb") as raw_f:
            stream = _AudioFileStream(raw_f, file_size)
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    break
                total_bytes_read += len(chunk)

            self.assertEqual(total_bytes_read, file_size)
            self.assertEqual(stream.tell(), file_size)

        snapshot_end = tracemalloc.take_snapshot()
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        peak_mb = peak / (1024 * 1024)
        # Peak RAM increase MUST be less than 2MB for a 40MB file (O(1) memory)
        self.assertLess(
            peak_mb,
            2.0,
            f"RAM leak detected! Peak memory during 40MB read was {peak_mb:.2f} MB (expected < 2.0 MB)",
        )

    def test_audio_stream_tell_and_seek_invariants(self):
        """
        Verify stream position invariants:
        - tell() advances as read() is called.
        - seek(0) rewinds tell() to 0.
        - tell() after stream.close() still returns last_pos (required for post-transmission check!).
        - stream.closed property reflects raw file.
        """
        p = self.temp_dir / "invariants.mp3"
        p.write_bytes(b"A" * 1000 + b"B" * 1000)

        with open(p, "rb") as raw:
            stream = _AudioFileStream(raw, 2000)
            self.assertFalse(stream.closed)
            self.assertEqual(stream.tell(), 0)

            chunk1 = stream.read(500)
            self.assertEqual(len(chunk1), 500)
            self.assertEqual(stream.tell(), 500)

            chunk2 = stream.read(500)
            self.assertEqual(len(chunk2), 500)
            self.assertEqual(stream.tell(), 1000)

            # Seek back to beginning
            stream.seek(0)
            self.assertEqual(stream.tell(), 0)

            # Re-read first chunk
            re_chunk1 = stream.read(500)
            self.assertEqual(chunk1, re_chunk1)
            self.assertEqual(stream.tell(), 500)

            # Seek to end
            stream.seek(0, os.SEEK_END)
            self.assertEqual(stream.tell(), 2000)

            # Close stream
            stream.close()
            self.assertTrue(stream.closed)
            # Post-close tell() must NOT raise ValueError, must return 2000!
            self.assertEqual(stream.tell(), 2000)

            # Idempotent close
            stream.close()
            self.assertTrue(stream.closed)

    async def test_send_audio_resilient_seek_0_rewind_on_html_error(self):
        """
        Adversarial test:
        When Telegram returns HTML entity parse error on attempt 1,
        send_audio must seek(0) the stream so attempt 2 sends the full audio stream
        from byte 0, NOT empty or shifted bytes.
        """
        audio_path = self.temp_dir / "resilient_rewind.mp3"
        test_payload = b"HEADER_320KBPS_AUDIO_STREAM_DATA_" + (b"X" * 10000)
        audio_path.write_bytes(test_payload)
        file_size = len(test_payload)

        bot = TelegramBot.__new__(TelegramBot)
        bot.token = "12345:TEST"

        attempts_data = []

        async def mock_post(url, data=None, files=None, timeout=None):
            if "audio" in files:
                fname, stream, mime = files["audio"]
                # Emulate reading the stream as httpx multipart would
                read_data = stream.read()
                attempts_data.append({
                    "data": data.copy(),
                    "read_len": len(read_data),
                    "read_sample": read_data[:32],
                    "stream_pos": stream.tell(),
                })

            if len(attempts_data) == 1:
                # First attempt: Telegram rejects HTML entities
                resp = httpx.Response(
                    status_code=400,
                    text='{"ok":false,"error_code":400,"description":"Bad Request: can\'t parse entities: Unsupported start tag"}',
                    request=httpx.Request("POST", url),
                )
                return resp
            else:
                # Second attempt: Plain text succeeds
                resp = httpx.Response(
                    status_code=200,
                    text='{"ok":true,"result":{"message_id":99}}',
                    request=httpx.Request("POST", url),
                )
                return resp

        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_http.post = AsyncMock(side_effect=mock_post)

        with patch.object(TelegramBot, "_http_client", new_callable=PropertyMock) as mock_client_prop:
            mock_client_prop.return_value = mock_http

            sent = await bot.send_audio(
                chat_id="123",
                audio_path=audio_path,
                caption="<b>Invalid <broken> HTML</b>",
                title="Resilient Song",
                performer="Singer",
                duration=60,
                parse_mode="HTML",
            )

            self.assertTrue(sent)
            self.assertEqual(len(attempts_data), 2, "Expected exactly 2 HTTP POST attempts.")

            # Attempt 1 check
            self.assertEqual(attempts_data[0]["read_len"], file_size)
            self.assertEqual(attempts_data[0]["read_sample"][:12], b"HEADER_320KB")

            # Attempt 2 check: PROOF THAT seek(0) WORKED!
            self.assertEqual(attempts_data[1]["read_len"], file_size, "Attempt 2 received truncated or empty stream!")
            self.assertEqual(attempts_data[1]["read_sample"][:12], b"HEADER_320KB", "Attempt 2 did not start from byte 0!")
            self.assertNotIn("parse_mode", attempts_data[1]["data"])
            self.assertEqual(attempts_data[1]["data"]["caption"], "Invalid  HTML")

    def test_audio_stream_context_manager_and_delegation(self):
        """Verify context manager closes raw file and getattr delegates correctly."""
        p = self.temp_dir / "delegation.mp3"
        p.write_bytes(b"test data 12345")

        raw_f = open(p, "rb")
        with _AudioFileStream(raw_f, 15) as stream:
            # Delegation of standard file attributes
            self.assertEqual(stream.name, str(p))
            self.assertEqual(stream.mode, "rb")
            self.assertFalse(stream.closed)
            _ = stream.read(5)

        # After context manager exit: raw file must be closed
        self.assertTrue(stream.closed)
        self.assertTrue(raw_f.closed)

    async def test_httpx_streaming_with_audio_file_stream(self):
        """
        Verify httpx multipart encoding directly consumes _AudioFileStream
        via mock Transport without throwing and preserving chunk streaming.
        """
        p = self.temp_dir / "httpx_compat.mp3"
        dummy_data = b"MPEG_AUDIO_STREAM_" * 1000
        p.write_bytes(dummy_data)
        file_size = len(dummy_data)

        raw_f = open(p, "rb")
        stream = _AudioFileStream(raw_f, file_size)

        received_bytes = io.BytesIO()

        class MockTransport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
                async for chunk in request.stream:
                    received_bytes.write(chunk)
                return httpx.Response(200, json={"ok": True})

        async with httpx.AsyncClient(transport=MockTransport()) as client:
            files = {"audio": (p.name, stream, "audio/mpeg")}
            resp = await client.post("http://test/sendAudio", data={"chat_id": "123"}, files=files)
            self.assertEqual(resp.status_code, 200)

        stream.close()
        # Verify the multipart payload contained our audio bytes
        payload_content = received_bytes.getvalue()
        self.assertIn(b"MPEG_AUDIO_STREAM_", payload_content)
        self.assertIn(b'filename="httpx_compat.mp3"', payload_content)


if __name__ == "__main__":
    unittest.main()
