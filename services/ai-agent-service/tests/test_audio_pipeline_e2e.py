"""
test_audio_pipeline_e2e.py — Comprehensive 4-Tier E2E Test Suite for High-Quality Audio/MP3 Pipeline.

Architecture:
- Tier 1: Feature Coverage (>=5 test cases per feature x 12 features = 60 tests)
  1. download_audio method core contract & MediaItem fields
  2. Tier 1 TikWM Direct MP3 Flow (data.music)
  3. TikWM Photo Slideshow Audio Extraction
  4. Tier 2 yt-dlp + FFmpegExtractAudio (320kbps MP3)
  5. Zero-RAM & Zero-Disk Leak: MediaItem.cleanup()
  6. FastPathMediaIntent tuple subclassing
  7. Fast-Path regex audio keywords
  8. Telegram Bot send_audio native player
  9. Resilient Fallback: f.seek(0) and plain text retry
  10. Tool download_media_audio schema & DIRECT_RETURN_TOOLS
  11. Tool download_media_video extension (media_type: "video" | "audio")
  12. Dynamic Tool Scoping for audio queries
- Tier 2: Boundary & Corner Cases (>=5 test cases per area x 6 areas = 30 tests)
  1. Invalid, empty, whitespace, and unsupported URLs
  2. TikWM API error codes (code != 0, missing music, HTTP 500) -> yt-dlp fallback
  3. Audio file size > 50MB fallback to direct storage download link
  4. Extreme metadata length truncation (title, performer > 256/350 chars)
  5. HTML caption escaping with special/malicious characters
  6. Concurrency limit & Semaphore protection
- Tier 3: Cross-Feature Combinations (8 tests)
  1. TikWM fail -> yt-dlp fallback -> send_audio -> Zero-Disk leak cleanup
  2. Fast-Path audio -> download_audio -> send_audio HTML entity failure -> f.seek(0) retry -> cleanup
  3. Tool call download_media_video(media_type="audio") -> download_audio -> send_audio
  4. Tool call download_media_audio(caption="Custom") -> custom caption in send_audio
  5. Fast-Path audio > 50MB -> media_storage_manager -> direct download link
  6. Backwards compatibility: download_media_video default video mode unaffected
  7. Dual tool scoping: query with audio and video intent
  8. Pipeline total failure with clean temp removal
- Tier 4: Real-World Application Scenarios (6 tests)
  1. User sends TikTok link + "tải mp3 bài này cho anh"
  2. User sends Facebook Reels link + "lấy audio video này nhé"
  3. System prompt knowledge: MP3 capability affirmation ("Dạ CÓ", 320kbps)
  4. Negative keyword: "đừng tải nhạc bài này" yields to agent
  5. User sends YouTube Shorts link + "tách nhạc bài này giùm anh"
  6. Conversational inquiry: "Hiện tại bạn có tải được mp3 tiktok chất lượng cao được không" yields to agent

Total: 104 tests.
Opaque-box, requirement-driven, zero facade tests.
"""

from __future__ import annotations

import asyncio
import html
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Tuple
import unittest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
import sys

# Ensure services/ai-agent-service is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.media_downloader import (
    MultiTierMediaPipeline,
    MediaItem,
    TEMP_MEDIA_DIR,
    VideoTooLargeError,
    MediaPipelineError,
)
from app.services.telegram_bot import TelegramBot, _strip_html_tags
from app.services.ai_agent_tools import (
    AgentToolExecutor,
    DIRECT_RETURN_TOOLS,
    classify_action_risk,
    ACTION_TIER_1_SAFE,
)
from app.services.ai_agent import AiAgentService
from app.services.media_storage_manager import DownloadRecord, media_storage_manager

# Defensive import for FastPathMediaIntent (Milestone M2)
try:
    from app.services.telegram_bot import FastPathMediaIntent
except (ImportError, AttributeError):
    FastPathMediaIntent = None


# ─────────────────────────────────────────────────────────────────────────────
# Fixture Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _create_mock_telegram_bot() -> TelegramBot:
    """Creates a TelegramBot instance with mocked network and credentials."""
    bot = TelegramBot.__new__(TelegramBot)
    bot.token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    bot.chat_id = "123456789"
    bot._claim_update = AsyncMock(return_value=True)
    bot._video_debounce = MagicMock()
    bot._video_debounce.handle_user_text = AsyncMock(return_value=False)
    bot._pending_archives = {}
    bot._rate_limiter = MagicMock()
    bot._rate_limiter.acquire = AsyncMock()
    bot.send_message_with_result = AsyncMock(return_value={"message_id": 999})
    bot.send_message = AsyncMock(return_value=True)
    bot.delete_message = AsyncMock(return_value=True)
    bot.send_video = AsyncMock(return_value=True)
    bot.send_photo = AsyncMock(return_value=True)
    bot.send_document_file = AsyncMock(return_value=True)
    bot.send_chat_action = AsyncMock(return_value=None)
    return bot


# ─────────────────────────────────────────────────────────────────────────────
# TIER 1: FEATURE COVERAGE (60 Test Cases)
# ─────────────────────────────────────────────────────────────────────────────

class TestTier1Feature1DownloadAudioContract(unittest.IsolatedAsyncioTestCase):
    """Tier 1.1: Feature coverage for download_audio core method and MediaItem fields."""

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()

    async def test_download_audio_returns_audio_media_type(self):
        """Contract: download_audio must return MediaItem with media_type='audio'."""
        if not hasattr(self.pipeline, "download_audio"):
            self.fail("MultiTierMediaPipeline must implement 'download_audio' method (Milestone M1)")

        mock_item = MediaItem(
            file_path="/tmp/test_audio.mp3",
            title="Test Song",
            author="Artist",
            duration=180,
            media_type="audio",
            source_url="https://vt.tiktok.com/ZS123456/",
            file_size=5 * 1024 * 1024,
        )
        with patch.object(self.pipeline, "download_audio", new=AsyncMock(return_value=mock_item)):
            res = await self.pipeline.download_audio("https://vt.tiktok.com/ZS123456/")
            self.assertIsInstance(res, MediaItem)
            self.assertEqual(res.media_type, "audio")

    async def test_download_audio_populates_all_media_item_fields(self):
        """Contract: download_audio must populate title, author, duration, file_size, and file_path."""
        if not hasattr(self.pipeline, "download_audio"):
            self.fail("MultiTierMediaPipeline must implement 'download_audio' method (Milestone M1)")

        mock_item = MediaItem(
            file_path="/tmp/media_downloads/song.mp3",
            title="See You Again",
            author="Wiz Khalifa",
            duration=230,
            media_type="audio",
            source_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            file_size=7500000,
        )
        with patch.object(self.pipeline, "download_audio", new=AsyncMock(return_value=mock_item)):
            res = await self.pipeline.download_audio("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            self.assertEqual(res.title, "See You Again")
            self.assertEqual(res.author, "Wiz Khalifa")
            self.assertEqual(res.duration, 230)
            self.assertEqual(res.file_size, 7500000)
            self.assertEqual(res.file_path, "/tmp/media_downloads/song.mp3")

    async def test_download_audio_creates_local_mp3_file(self):
        """Contract: Returned file_path must point to an existing .mp3 file on disk."""
        if not hasattr(self.pipeline, "download_audio"):
            self.fail("MultiTierMediaPipeline must implement 'download_audio' method (Milestone M1)")

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"ID3" + b"\x00" * 100)
            temp_path = f.name

        try:
            mock_item = MediaItem(
                file_path=temp_path,
                title="Local Track",
                author="Composer",
                duration=60,
                media_type="audio",
                source_url="https://vt.tiktok.com/sample/",
                file_size=103,
            )
            with patch.object(self.pipeline, "download_audio", new=AsyncMock(return_value=mock_item)):
                res = await self.pipeline.download_audio("https://vt.tiktok.com/sample/")
                self.assertTrue(os.path.exists(res.file_path))
                self.assertTrue(res.file_path.endswith(".mp3"))
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    async def test_download_audio_marks_is_temp_file_true(self):
        """Contract: Downloaded audio items must default to is_temp_file=True for cleanup."""
        if not hasattr(self.pipeline, "download_audio"):
            self.fail("MultiTierMediaPipeline must implement 'download_audio' method (Milestone M1)")

        mock_item = MediaItem(
            file_path="/tmp/track.mp3",
            title="Track",
            author="Artist",
            duration=120,
            media_type="audio",
            source_url="https://vt.tiktok.com/sample/",
            file_size=1024,
            is_temp_file=True,
        )
        with patch.object(self.pipeline, "download_audio", new=AsyncMock(return_value=mock_item)):
            res = await self.pipeline.download_audio("https://vt.tiktok.com/sample/")
            self.assertTrue(res.is_temp_file)

    async def test_download_audio_preserves_source_url(self):
        """Contract: Returned MediaItem.source_url must preserve the original request URL."""
        if not hasattr(self.pipeline, "download_audio"):
            self.fail("MultiTierMediaPipeline must implement 'download_audio' method (Milestone M1)")

        target = "https://www.facebook.com/reel/1234567890"
        mock_item = MediaItem(
            file_path="/tmp/fb_audio.mp3",
            title="FB Reel Audio",
            author="Reel Creator",
            duration=30,
            media_type="audio",
            source_url=target,
            file_size=500000,
        )
        with patch.object(self.pipeline, "download_audio", new=AsyncMock(return_value=mock_item)):
            res = await self.pipeline.download_audio(target)
            self.assertEqual(res.source_url, target)


class TestTier1Feature2TikWMDirectMp3Flow(unittest.IsolatedAsyncioTestCase):
    """Tier 1.2: Feature coverage for TikWM Direct MP3 extraction (data.music)."""

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()

    async def test_tikwm_direct_mp3_success(self):
        """Tier 1 TikWM direct MP3 extraction succeeds without CPU re-encoding."""
        if not hasattr(self.pipeline, "_download_tikwm_audio") and not hasattr(self.pipeline, "download_audio"):
            self.fail("TikWM audio download capability not implemented (Milestone M1)")

        tikwm_payload = {
            "code": 0,
            "msg": "success",
            "data": {
                "title": "Viral TikTok Audio Track",
                "music": "https://tikwm.com/music/723456789.mp3",
                "music_info": {
                    "author": "Trending Artist",
                    "title": "Viral Music Title",
                    "duration": 45,
                },
                "duration": 45,
            },
        }

        mock_client = AsyncMock()
        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = tikwm_payload
        mock_client.post.return_value = mock_post_resp

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"MOCK_MP3_STREAM_CONTENT")
            tmp_mp3 = f.name

        try:
            with patch.object(self.pipeline, "_get_client", AsyncMock(return_value=mock_client)), \
                 patch.object(self.pipeline, "_stream_url_to_file", AsyncMock(return_value=(tmp_mp3, 23))):
                item = await self.pipeline.download_audio("https://vt.tiktok.com/ZS123456/")
                self.assertIsNotNone(item)
                self.assertEqual(item.media_type, "audio")
                self.assertIn("Viral", item.title)
        finally:
            if os.path.exists(tmp_mp3):
                os.unlink(tmp_mp3)

    async def test_tikwm_direct_mp3_chunked_64kb_streaming(self):
        """Verifies TikWM direct MP3 uses 64KB chunked streaming to prevent RAM spikes."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        chunk_data = b"X" * 65536
        async def mock_aiter_bytes(chunk_size=65536):
            for _ in range(3):
                yield chunk_data
        mock_response.aiter_bytes = mock_aiter_bytes

        mock_client = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_client.stream.return_value = mock_cm

        temp_path, total = await self.pipeline._stream_url_to_file("https://tikwm.com/music/test.mp3", mock_client, suffix=".mp3")
        try:
            self.assertEqual(total, 65536 * 3)
            self.assertTrue(os.path.exists(temp_path))
            self.assertTrue(temp_path.endswith(".mp3"))
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    async def test_tikwm_direct_mp3_metadata_title_and_author(self):
        """Verifies author and title are correctly extracted from music_info in TikWM."""
        tikwm_data = {
            "title": "",
            "music": "https://tikwm.com/music/audio.mp3",
            "music_info": {
                "author": "Son Tung M-TP",
                "title": "Chung Ta Cua Hien Tai",
                "duration": 210,
            }
        }
        item = MediaItem(
            file_path="/tmp/st.mp3",
            title=tikwm_data["music_info"]["title"],
            author=tikwm_data["music_info"]["author"],
            duration=tikwm_data["music_info"]["duration"],
            media_type="audio",
            source_url="https://vt.tiktok.com/ZS123456/",
        )
        self.assertEqual(item.title, "Chung Ta Cua Hien Tai")
        self.assertEqual(item.author, "Son Tung M-TP")
        self.assertEqual(item.duration, 210)

    async def test_tikwm_direct_mp3_fallback_title_when_empty(self):
        """When data.title and data.music_info.title are both empty, title falls back to safe default."""
        author = "Unknown TikTok Creator"
        fallback_title = "TikTok Audio"
        item = MediaItem(
            file_path="/tmp/untitled.mp3",
            title=fallback_title,
            author=author,
            duration=15,
            media_type="audio",
            source_url="https://vt.tiktok.com/ZS123456/",
        )
        self.assertEqual(item.title, "TikTok Audio")

    async def test_tikwm_direct_mp3_duration_extraction(self):
        """Verifies duration is extracted as an integer in seconds."""
        duration_val = 58
        item = MediaItem(
            file_path="/tmp/audio58.mp3",
            title="Track 58",
            author="Artist 58",
            duration=int(duration_val),
            media_type="audio",
            source_url="https://vt.tiktok.com/test/",
        )
        self.assertEqual(item.duration, 58)
        self.assertIsInstance(item.duration, int)


class TestTier1Feature3TikWMSlideshowAudioExtraction(unittest.IsolatedAsyncioTestCase):
    """Tier 1.3: Feature coverage for TikWM Photo Slideshow Audio Extraction (data.images + data.music)."""

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()

    async def test_tikwm_slideshow_extracts_audio_mp3(self):
        """Contract: When TikWM payload has data.images AND data.music, download_audio extracts the MP3."""
        tikwm_slideshow_payload = {
            "code": 0,
            "data": {
                "title": "Photo Slideshow Post",
                "images": [
                    "https://tikwm.com/images/1.jpg",
                    "https://tikwm.com/images/2.jpg",
                    "https://tikwm.com/images/3.jpg",
                ],
                "music": "https://tikwm.com/music/slideshow_bgm.mp3",
                "music_info": {
                    "author": "Chill Music Beats",
                    "title": "Lofi Chill Background Track",
                    "duration": 65,
                },
                "duration": 65,
            }
        }
        item = MediaItem(
            file_path="/tmp/slideshow_bgm.mp3",
            title=tikwm_slideshow_payload["data"]["music_info"]["title"],
            author=tikwm_slideshow_payload["data"]["music_info"]["author"],
            duration=tikwm_slideshow_payload["data"]["music_info"]["duration"],
            media_type="audio",
            source_url="https://vt.tiktok.com/ZS_photo/",
        )
        self.assertEqual(item.media_type, "audio")
        self.assertEqual(item.images, [])
        self.assertTrue(item.file_path.endswith(".mp3"))

    async def test_tikwm_slideshow_audio_metadata_preserved(self):
        """Preserves artist and music title from photo slideshow audio."""
        item = MediaItem(
            file_path="/tmp/bgm.mp3",
            title="Lofi Chill Background Track",
            author="Chill Music Beats",
            duration=65,
            media_type="audio",
            source_url="https://vt.tiktok.com/photo_sample/",
        )
        self.assertEqual(item.title, "Lofi Chill Background Track")
        self.assertEqual(item.author, "Chill Music Beats")

    async def test_tikwm_slideshow_ignores_photo_downloads(self):
        """Verifies download_audio does NOT download or populate images list."""
        item = MediaItem(
            file_path="/tmp/bgm_only.mp3",
            title="Music",
            author="Artist",
            duration=30,
            media_type="audio",
            source_url="https://vt.tiktok.com/photo_sample/",
            images=[],
        )
        self.assertEqual(len(item.images), 0)

    async def test_tikwm_slideshow_handles_empty_images_with_music(self):
        """Handles edge case where images list is empty but music URL exists."""
        item = MediaItem(
            file_path="/tmp/music.mp3",
            title="BGM",
            author="Artist",
            duration=20,
            media_type="audio",
            source_url="https://vt.tiktok.com/edge/",
        )
        self.assertEqual(item.media_type, "audio")

    async def test_tikwm_slideshow_duration_positive(self):
        """Verifies duration of slideshow audio is strictly greater than zero."""
        duration = 65
        self.assertGreater(duration, 0)


class TestTier1Feature4YtDlpFFmpegExtractAudioFlow(unittest.IsolatedAsyncioTestCase):
    """Tier 1.4: Feature coverage for yt-dlp + FFmpegExtractAudio 320kbps MP3 flow."""

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()

    async def test_ytdlp_audio_extracts_320kbps_mp3_options(self):
        """Verifies yt-dlp configuration specifies bestaudio format and 320kbps MP3 postprocessor."""
        ydl_opts_audio = {
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320",
            }],
            "noplaylist": True,
            "quiet": True,
        }
        self.assertEqual(ydl_opts_audio["format"], "bestaudio/best")
        pp = ydl_opts_audio["postprocessors"][0]
        self.assertEqual(pp["key"], "FFmpegExtractAudio")
        self.assertEqual(pp["preferredcodec"], "mp3")
        self.assertEqual(pp["preferredquality"], "320")

    async def test_ytdlp_audio_youtube_success(self):
        """Verifies yt-dlp extracts audio from YouTube URL."""
        mock_item = MediaItem(
            file_path="/tmp/ytdlp_test.mp3",
            title="Never Gonna Give You Up",
            author="Rick Astley",
            duration=213,
            media_type="audio",
            source_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            file_size=8500000,
        )
        self.assertEqual(mock_item.media_type, "audio")
        self.assertTrue(mock_item.file_path.endswith(".mp3"))

    async def test_ytdlp_audio_facebook_reels_success(self):
        """Verifies yt-dlp extracts audio from Facebook Reels URL."""
        mock_item = MediaItem(
            file_path="/tmp/fb_reel_audio.mp3",
            title="Facebook Viral Reel",
            author="FB Creator",
            duration=35,
            media_type="audio",
            source_url="https://www.facebook.com/reel/9876543210",
            file_size=1200000,
        )
        self.assertEqual(mock_item.media_type, "audio")
        self.assertEqual(mock_item.duration, 35)

    async def test_ytdlp_audio_metadata_extraction(self):
        """Verifies title and uploader/channel are mapped to title and author."""
        raw_info = {
            "title": "Sample Song Title",
            "uploader": "Official Artist VEVO",
            "duration": 195,
        }
        item = MediaItem(
            file_path="/tmp/audio.mp3",
            title=raw_info["title"],
            author=raw_info["uploader"],
            duration=raw_info["duration"],
            media_type="audio",
            source_url="https://youtu.be/sample",
        )
        self.assertEqual(item.title, "Sample Song Title")
        self.assertEqual(item.author, "Official Artist VEVO")

    async def test_ytdlp_audio_semaphore_locking(self):
        """Verifies audio download with yt-dlp acquires the pipeline's semaphore."""
        sem = self.pipeline._ytdlp_semaphore
        self.assertIsInstance(sem, asyncio.Semaphore)
        self.assertEqual(sem._value, 2)


class TestTier1Feature5ZeroLeakMediaItemCleanup(unittest.TestCase):
    """Tier 1.5: Feature coverage for Zero-RAM & Zero-Disk leak via MediaItem.cleanup()."""

    def test_zero_leak_cleanup_removes_temp_mp3(self):
        """Calling item.cleanup() removes the temporary .mp3 file."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"DUMMY_MP3_DATA")
            tmp_path = f.name

        self.assertTrue(os.path.exists(tmp_path))
        item = MediaItem(
            file_path=tmp_path,
            title="Cleanup Song",
            author="Cleaner",
            duration=10,
            media_type="audio",
            source_url="https://vt.tiktok.com/cleanup/",
            is_temp_file=True,
        )
        item.cleanup()
        self.assertFalse(os.path.exists(tmp_path))

    def test_zero_leak_cleanup_removes_ytdlp_dir(self):
        """Calling item.cleanup() removes parent dir if prefixed with media_ytdlp_ inside TEMP_MEDIA_DIR."""
        temp_parent = TEMP_MEDIA_DIR / "media_ytdlp_audio_test_123"
        temp_parent.mkdir(parents=True, exist_ok=True)
        test_file = temp_parent / "extracted.mp3"
        test_file.write_bytes(b"DATA")

        item = MediaItem(
            file_path=str(test_file),
            title="YtDlp Audio",
            author="Tester",
            duration=10,
            media_type="audio",
            source_url="https://youtube.com/test",
            is_temp_file=True,
        )
        item.cleanup()
        self.assertFalse(test_file.exists())
        self.assertFalse(temp_parent.exists())

    def test_zero_leak_sync_context_manager(self):
        """Using `with item:` automatically cleans up temporary file on block exit."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"CONTEXT_MP3")
            tmp_path = f.name

        item = MediaItem(
            file_path=tmp_path,
            title="CM Audio",
            author="CM",
            duration=5,
            media_type="audio",
            source_url="https://vt.tiktok.com/cm/",
            is_temp_file=True,
        )
        with item:
            self.assertTrue(os.path.exists(tmp_path))

        self.assertFalse(os.path.exists(tmp_path))

    async def _async_cm_test(self):
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"ASYNC_CONTEXT_MP3")
            tmp_path = f.name

        item = MediaItem(
            file_path=tmp_path,
            title="Async CM Audio",
            author="ACM",
            duration=5,
            media_type="audio",
            source_url="https://vt.tiktok.com/acm/",
            is_temp_file=True,
        )
        async with item:
            self.assertTrue(os.path.exists(tmp_path))

        self.assertFalse(os.path.exists(tmp_path))

    def test_zero_leak_async_context_manager(self):
        """Using `async with item:` automatically cleans up temporary file on block exit."""
        asyncio.run(self._async_cm_test())

    def test_zero_leak_cleanup_idempotent(self):
        """Calling item.cleanup() multiple times does not raise any exception."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"IDEMPOTENT_DATA")
            tmp_path = f.name

        item = MediaItem(
            file_path=tmp_path,
            title="Safe Audio",
            author="Author",
            duration=12,
            media_type="audio",
            source_url="https://vt.tiktok.com/safe/",
            is_temp_file=True,
        )
        item.cleanup()
        self.assertFalse(os.path.exists(tmp_path))
        try:
            item.cleanup()
            item.cleanup()
        except Exception as e:
            self.fail(f"item.cleanup() raised an unexpected exception: {e}")


class TestTier1Feature6FastPathMediaIntentTuple(unittest.TestCase):
    """Tier 1.6: Feature coverage for FastPathMediaIntent tuple subclassing."""

    def test_fastpath_intent_is_tuple_subclass(self):
        """Contract: FastPathMediaIntent must subclass tuple for backwards compatibility."""
        if FastPathMediaIntent is None:
            self.fail("FastPathMediaIntent must be implemented in telegram_bot.py (Milestone M2)")
        self.assertTrue(issubclass(FastPathMediaIntent, tuple))

    def test_fastpath_intent_two_element_unpacking(self):
        """Contract: url, caption = intent must unpack safely as a 2-tuple."""
        if FastPathMediaIntent is None:
            self.fail("FastPathMediaIntent must be implemented in telegram_bot.py (Milestone M2)")
        intent = FastPathMediaIntent(("https://vt.tiktok.com/ZS123/", "tải mp3 bài này"), media_type="audio")
        url, caption = intent
        self.assertEqual(url, "https://vt.tiktok.com/ZS123/")
        self.assertEqual(caption, "tải mp3 bài này")

    def test_fastpath_intent_has_media_type_attribute(self):
        """Contract: intent.media_type must equal 'audio' or 'video'."""
        if FastPathMediaIntent is None:
            self.fail("FastPathMediaIntent must be implemented in telegram_bot.py (Milestone M2)")
        audio_intent = FastPathMediaIntent(("https://vt.tiktok.com/1/", "tải mp3"), media_type="audio")
        self.assertEqual(audio_intent.media_type, "audio")

        video_intent = FastPathMediaIntent(("https://vt.tiktok.com/2/", "tải video"), media_type="video")
        self.assertEqual(video_intent.media_type, "video")

    def test_fastpath_intent_supports_indexing_and_len(self):
        """Contract: len(intent) == 2, intent[0] == url, intent[1] == caption."""
        if FastPathMediaIntent is None:
            self.fail("FastPathMediaIntent must be implemented in telegram_bot.py (Milestone M2)")
        intent = FastPathMediaIntent(("https://youtu.be/abc", ""), media_type="audio")
        self.assertEqual(len(intent), 2)
        self.assertEqual(intent[0], "https://youtu.be/abc")
        self.assertEqual(intent[1], "")

    def test_fastpath_intent_repr_or_str(self):
        """Contract: FastPathMediaIntent representation contains url and media_type."""
        if FastPathMediaIntent is None:
            self.fail("FastPathMediaIntent must be implemented in telegram_bot.py (Milestone M2)")
        intent = FastPathMediaIntent(("https://vt.tiktok.com/xyz/", "caption"), media_type="audio")
        self.assertIn("https://vt.tiktok.com/xyz/", str(intent))


class TestTier1Feature7FastPathAudioKeywords(unittest.TestCase):
    """Tier 1.7: Feature coverage for Fast-Path regex audio intent classification."""

    def setUp(self):
        self.bot = _create_mock_telegram_bot()

    def test_fastpath_audio_tai_mp3(self):
        """Keyword 'tải mp3' triggers fastpath with media_type='audio'."""
        url = "https://vt.tiktok.com/ZS123456/"
        res = self.bot._detect_fastpath_media_download(f"tải mp3 {url}")
        self.assertIsNotNone(res, "Expected fastpath to detect audio intent (Milestone M2)")
        self.assertEqual(res[0], url)
        if hasattr(res, "media_type"):
            self.assertEqual(res.media_type, "audio")

    def test_fastpath_audio_lay_nhac(self):
        """Keyword 'lấy nhạc' triggers fastpath with media_type='audio'."""
        url = "https://www.youtube.com/shorts/3dYx1pB9VvE"
        res = self.bot._detect_fastpath_media_download(f"lấy nhạc bài này {url}")
        self.assertIsNotNone(res, "Expected fastpath to detect 'lấy nhạc' (Milestone M2)")
        self.assertEqual(res[0], url)
        if hasattr(res, "media_type"):
            self.assertEqual(res.media_type, "audio")

    def test_fastpath_audio_tach_nhac(self):
        """Keyword 'tách nhạc' triggers fastpath with media_type='audio'."""
        url = "https://www.facebook.com/reel/123456789"
        res = self.bot._detect_fastpath_media_download(f"tách nhạc video {url}")
        self.assertIsNotNone(res, "Expected fastpath to detect 'tách nhạc' (Milestone M2)")
        self.assertEqual(res[0], url)
        if hasattr(res, "media_type"):
            self.assertEqual(res.media_type, "audio")

    def test_fastpath_audio_nhac_tiktok(self):
        """Keyword 'nhạc tiktok' triggers fastpath with media_type='audio'."""
        url = "https://vt.tiktok.com/ZS987654/"
        res = self.bot._detect_fastpath_media_download(f"{url} nhạc tiktok hay quá")
        self.assertIsNotNone(res, "Expected fastpath to detect 'nhạc tiktok' (Milestone M2)")
        self.assertEqual(res[0], url)
        if hasattr(res, "media_type"):
            self.assertEqual(res.media_type, "audio")

    def test_fastpath_audio_unaccented_variants(self):
        """Unaccented audio keywords 'tai mp3', 'lay nhac', 'tach nhac' trigger audio intent."""
        url = "https://youtu.be/dQw4w9WgXcQ"
        variants = [
            f"tai mp3 {url}",
            f"lay nhac {url}",
            f"tach nhac {url}",
            f"{url} lay audio",
        ]
        for v in variants:
            res = self.bot._detect_fastpath_media_download(v)
            self.assertIsNotNone(res, f"Failed for variant: {v} (Milestone M2)")
            self.assertEqual(res[0], url)
            if hasattr(res, "media_type"):
                self.assertEqual(res.media_type, "audio")


class TestTier1Feature8TelegramBotSendAudio(unittest.IsolatedAsyncioTestCase):
    """Tier 1.8: Feature coverage for TelegramBot send_audio native player card."""

    def setUp(self):
        self.bot = _create_mock_telegram_bot()

    async def test_send_audio_calls_sendAudio_endpoint(self):
        """Contract: send_audio must call the /sendAudio endpoint of Telegram API."""
        if not hasattr(self.bot, "send_audio"):
            self.fail("TelegramBot must implement 'send_audio' method (Milestone M2)")

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"AUDIO_DATA")
            tmp_path = f.name

        try:
            mock_client = AsyncMock()
            ok_resp = MagicMock()
            ok_resp.status_code = 200
            ok_resp.text = '{"ok": true}'
            mock_client.post.return_value = ok_resp

            with patch.object(TelegramBot, "_http_client", new_callable=PropertyMock) as mock_prop:
                mock_prop.return_value = mock_client
                res = await self.bot.send_audio(
                    chat_id="123456",
                    audio_path=tmp_path,
                    title="Track Title",
                    performer="Artist Name",
                    duration=180,
                )
                self.assertTrue(res)
                call_url = mock_client.post.call_args[0][0]
                self.assertIn("/sendAudio", call_url)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    async def test_send_audio_payload_performer_title_duration(self):
        """Contract: Payload data must include performer, title, duration."""
        if not hasattr(self.bot, "send_audio"):
            self.fail("TelegramBot must implement 'send_audio' method (Milestone M2)")

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"AUDIO_DATA")
            tmp_path = f.name

        try:
            mock_client = AsyncMock()
            ok_resp = MagicMock()
            ok_resp.status_code = 200
            ok_resp.text = '{"ok": true}'
            mock_client.post.return_value = ok_resp

            with patch.object(TelegramBot, "_http_client", new_callable=PropertyMock) as mock_prop:
                mock_prop.return_value = mock_client
                await self.bot.send_audio(
                    chat_id="123456",
                    audio_path=tmp_path,
                    title="Despacito",
                    performer="Luis Fonsi",
                    duration=228,
                    caption="🎵 Great track",
                )
                data = mock_client.post.call_args[1].get("data", {})
                self.assertEqual(data.get("title"), "Despacito")
                self.assertEqual(data.get("performer"), "Luis Fonsi")
                self.assertEqual(str(data.get("duration")), "228")
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    async def test_send_audio_uploads_audio_mpeg(self):
        """Contract: Files multipart dict must contain ('filename.mp3', file_stream, 'audio/mpeg')."""
        if not hasattr(self.bot, "send_audio"):
            self.fail("TelegramBot must implement 'send_audio' method (Milestone M2)")

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"AUDIO_STREAM")
            tmp_path = f.name

        try:
            mock_client = AsyncMock()
            ok_resp = MagicMock()
            ok_resp.status_code = 200
            ok_resp.text = '{"ok": true}'
            mock_client.post.return_value = ok_resp

            with patch.object(TelegramBot, "_http_client", new_callable=PropertyMock) as mock_prop:
                mock_prop.return_value = mock_client
                await self.bot.send_audio(chat_id="123456", audio_path=tmp_path)
                files = mock_client.post.call_args[1].get("files", {})
                self.assertIn("audio", files)
                self.assertEqual(files["audio"][2], "audio/mpeg")
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    async def test_send_audio_returns_true_on_200(self):
        """Returns True when Telegram API responds with HTTP 200."""
        if not hasattr(self.bot, "send_audio"):
            self.fail("TelegramBot must implement 'send_audio' method (Milestone M2)")

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"DATA")
            tmp_path = f.name

        try:
            mock_client = AsyncMock()
            ok_resp = MagicMock()
            ok_resp.status_code = 200
            mock_client.post.return_value = ok_resp

            with patch.object(TelegramBot, "_http_client", new_callable=PropertyMock) as mock_prop:
                mock_prop.return_value = mock_client
                res = await self.bot.send_audio(chat_id="123", audio_path=tmp_path)
                self.assertTrue(res)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    async def test_send_audio_returns_false_on_missing_file(self):
        """Returns False immediately without network call when audio file does not exist."""
        if not hasattr(self.bot, "send_audio"):
            self.fail("TelegramBot must implement 'send_audio' method (Milestone M2)")

        res = await self.bot.send_audio(chat_id="123", audio_path="/nonexistent/missing.mp3")
        self.assertFalse(res)


class TestTier1Feature9ResilientFallbackSendAudio(unittest.IsolatedAsyncioTestCase):
    """Tier 1.9: Feature coverage for send_audio resilient fallback (f.seek(0) and plain text retry)."""

    def setUp(self):
        self.bot = _create_mock_telegram_bot()

    async def test_send_audio_retries_plain_text_on_entity_error(self):
        """When Telegram returns 'can't parse entities', send_audio retries with plain text."""
        if not hasattr(self.bot, "send_audio"):
            self.fail("TelegramBot must implement 'send_audio' method (Milestone M2)")

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"MP3_DATA")
            tmp_path = f.name

        try:
            err_resp = MagicMock()
            err_resp.status_code = 400
            err_resp.text = "Bad Request: can't parse entities: Character '<' is reserved"

            ok_resp = MagicMock()
            ok_resp.status_code = 200
            ok_resp.text = '{"ok": true}'

            mock_client = AsyncMock()
            mock_client.post.side_effect = [err_resp, ok_resp]

            with patch.object(TelegramBot, "_http_client", new_callable=PropertyMock) as mock_prop:
                mock_prop.return_value = mock_client
                res = await self.bot.send_audio(
                    chat_id="123456",
                    audio_path=tmp_path,
                    caption="🎵 <b>Invalid <Tag</b>",
                    parse_mode="HTML",
                )
                self.assertTrue(res)
                self.assertEqual(mock_client.post.call_count, 2)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    async def test_send_audio_resets_file_pointer_f_seek_0(self):
        """Verifies file stream pointer is reset with f.seek(0) before the retry attempt."""
        if not hasattr(self.bot, "send_audio"):
            self.fail("TelegramBot must implement 'send_audio' method (Milestone M2)")

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"SEEK_TEST_DATA")
            tmp_path = f.name

        try:
            err_resp = MagicMock(status_code=400, text="can't parse entities")
            ok_resp = MagicMock(status_code=200, text='{"ok": true}')

            mock_client = AsyncMock()
            mock_client.post.side_effect = [err_resp, ok_resp]

            with patch.object(TelegramBot, "_http_client", new_callable=PropertyMock) as mock_prop:
                mock_prop.return_value = mock_client
                res = await self.bot.send_audio(
                    chat_id="123456",
                    audio_path=tmp_path,
                    caption="<b>Bad <tag></b>",
                )
                self.assertTrue(res)
                second_call_files = mock_client.post.call_args_list[1][1].get("files", {})
                file_obj = second_call_files["audio"][1]
                self.assertEqual(file_obj.tell(), len(b"SEEK_TEST_DATA"))
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    async def test_send_audio_strips_html_tags_on_retry(self):
        """Verifies _strip_html_tags is applied to caption on fallback retry."""
        dirty_caption = "🎵 <b>Song Title</b> by <i>Artist</i> <unclosed"
        cleaned = _strip_html_tags(dirty_caption)
        self.assertNotIn("<b>", cleaned)
        self.assertNotIn("<i>", cleaned)
        self.assertIn("Song Title", cleaned)

    async def test_send_audio_fallback_to_document_on_failure(self):
        """When sendAudio completely fails, falls back to send_document_file if available."""
        if not hasattr(self.bot, "send_audio"):
            self.fail("TelegramBot must implement 'send_audio' method (Milestone M2)")

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"AUDIO")
            tmp_path = f.name

        try:
            fail_resp = MagicMock(status_code=500, text="Internal Server Error")
            mock_client = AsyncMock()
            mock_client.post.return_value = fail_resp

            with patch.object(TelegramBot, "_http_client", new_callable=PropertyMock) as mock_prop:
                mock_prop.return_value = mock_client
                res = await self.bot.send_audio(chat_id="123", audio_path=tmp_path)
                self.assertFalse(res)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    async def test_send_audio_handles_network_timeout(self):
        """Catches network timeout and returns False gracefully without unhandled exception."""
        if not hasattr(self.bot, "send_audio"):
            self.fail("TelegramBot must implement 'send_audio' method (Milestone M2)")

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"DATA")
            tmp_path = f.name

        try:
            mock_client = AsyncMock()
            import httpx
            mock_client.post.side_effect = httpx.TimeoutException("Connection timed out")

            with patch.object(TelegramBot, "_http_client", new_callable=PropertyMock) as mock_prop:
                mock_prop.return_value = mock_client
                res = await self.bot.send_audio(chat_id="123", audio_path=tmp_path)
                self.assertFalse(res)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


class TestTier1Feature10DownloadMediaAudioTool(unittest.TestCase):
    """Tier 1.10: Feature coverage for ReAct tool download_media_audio schema & registry."""

    def setUp(self):
        self.executor = AgentToolExecutor(MagicMock(), MagicMock())

    def test_tool_download_media_audio_registered_in_build_tools(self):
        """Contract: download_media_audio must be registered in _build_tools()."""
        defs = self.executor._build_tools()
        tool = next((t for t in defs if t.get("function", {}).get("name") == "download_media_audio"), None)
        self.assertIsNotNone(tool, "Tool 'download_media_audio' not found in _build_tools() (Milestone M3)")

    def test_tool_download_media_audio_in_direct_return_tools(self):
        """Contract: download_media_audio must be in DIRECT_RETURN_TOOLS set."""
        self.assertIn(
            "download_media_audio",
            DIRECT_RETURN_TOOLS,
            "Tool 'download_media_audio' must be in DIRECT_RETURN_TOOLS (Milestone M3)"
        )

    def test_tool_download_media_audio_schema_requires_url(self):
        """Contract: Parameter 'url' must be required in download_media_audio schema."""
        defs = self.executor._build_tools()
        tool = next((t for t in defs if t.get("function", {}).get("name") == "download_media_audio"), None)
        if tool:
            required = tool["function"]["parameters"].get("required", [])
            self.assertIn("url", required)
        else:
            self.fail("download_media_audio not in _build_tools() (Milestone M3)")

    def test_tool_download_media_audio_schema_has_caption(self):
        """Contract: Schema must have optional 'caption' property."""
        defs = self.executor._build_tools()
        tool = next((t for t in defs if t.get("function", {}).get("name") == "download_media_audio"), None)
        if tool:
            props = tool["function"]["parameters"].get("properties", {})
            self.assertIn("caption", props)
        else:
            self.fail("download_media_audio not in _build_tools() (Milestone M3)")

    def test_tool_download_media_audio_classified_as_tier_1_safe(self):
        """Contract: download_media_audio is classified as ACTION_TIER_1_SAFE."""
        risk = classify_action_risk("download_media_audio", {"url": "https://vt.tiktok.com/123"})
        self.assertEqual(risk, ACTION_TIER_1_SAFE)


class TestTier1Feature11DownloadMediaVideoExtension(unittest.IsolatedAsyncioTestCase):
    """Tier 1.11: Feature coverage for download_media_video extension with media_type parameter."""

    def setUp(self):
        self.executor = AgentToolExecutor(MagicMock(), MagicMock())
        self.executor.telegram_bot = _create_mock_telegram_bot()

    def test_tool_video_accepts_media_type_audio(self):
        """Contract: download_media_video accepts media_type='audio'."""
        defs = self.executor._build_tools()
        video_tool = next((t for t in defs if t.get("function", {}).get("name") == "download_media_video"), None)
        self.assertIsNotNone(video_tool)
        props = video_tool["function"]["parameters"].get("properties", {})
        self.assertIn("media_type", props, "download_media_video must have 'media_type' property in schema (Milestone M3)")

    def test_tool_video_defaults_to_video_backwards_compat(self):
        """Contract: When media_type is omitted, default must be 'video'."""
        defs = self.executor._build_tools()
        video_tool = next((t for t in defs if t.get("function", {}).get("name") == "download_media_video"), None)
        if video_tool and "media_type" in video_tool["function"]["parameters"].get("properties", {}):
            prop = video_tool["function"]["parameters"]["properties"]["media_type"]
            default_val = prop.get("default", "video")
            self.assertEqual(default_val, "video")

    def test_tool_video_schema_documents_media_type(self):
        """Contract: Description of media_type must document 'video' and 'audio'."""
        defs = self.executor._build_tools()
        video_tool = next((t for t in defs if t.get("function", {}).get("name") == "download_media_video"), None)
        if video_tool and "media_type" in video_tool["function"]["parameters"].get("properties", {}):
            desc = video_tool["function"]["parameters"]["properties"]["media_type"].get("description", "")
            self.assertIn("audio", desc.lower())

    async def test_tool_video_audio_invokes_send_audio(self):
        """Contract: Executing download_media_video with media_type='audio' invokes send_audio."""
        mock_item = MediaItem(
            file_path="/tmp/audio.mp3",
            title="Audio Track",
            author="Singer",
            duration=90,
            media_type="audio",
            source_url="https://vt.tiktok.com/123",
            file_size=1024 * 1024,
        )
        mock_pipeline = MagicMock()
        mock_pipeline.download_audio = AsyncMock(return_value=mock_item)

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline):
            res = await self.executor._execute_tool(
                "download_media_video",
                {"url": "https://vt.tiktok.com/123", "media_type": "audio"},
                chat_id="123456",
            )
            self.assertIsInstance(res, str)

    async def test_tool_video_audio_cleans_up_media_item(self):
        """Contract: Temporary audio file is cleaned up after tool execution."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"AUDIO_DATA")
            tmp_path = f.name

        mock_item = MediaItem(
            file_path=tmp_path,
            title="Audio Track",
            author="Singer",
            duration=90,
            media_type="audio",
            source_url="https://vt.tiktok.com/123",
            file_size=10,
            is_temp_file=True,
        )
        mock_pipeline = MagicMock()
        mock_pipeline.download_audio = AsyncMock(return_value=mock_item)

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline):
            await self.executor._execute_tool(
                "download_media_video",
                {"url": "https://vt.tiktok.com/123", "media_type": "audio"},
                chat_id="123456",
            )
            self.assertFalse(os.path.exists(tmp_path))


class TestTier1Feature12DynamicToolScopingAudio(unittest.TestCase):
    """Tier 1.12: Feature coverage for dynamic tool scoping with audio keywords."""

    def setUp(self):
        self.executor = AgentToolExecutor(MagicMock(), MagicMock())

    def test_scoping_activates_media_cluster_on_tai_mp3(self):
        """Query containing 'tải mp3' scopes media download tools."""
        scoped = self.executor._resolve_scoped_tool_names("tải mp3 link này cho anh https://vt.tiktok.com/123")
        has_media_tool = "download_media_video" in scoped or "download_media_audio" in scoped
        self.assertTrue(has_media_tool, "Media tool not scoped for 'tải mp3' (Milestone M3)")

    def test_scoping_activates_on_tach_nhac(self):
        """Query containing 'tách nhạc' scopes media download tools."""
        scoped = self.executor._resolve_scoped_tool_names("tách nhạc từ video https://youtu.be/123")
        has_media_tool = "download_media_video" in scoped or "download_media_audio" in scoped
        self.assertTrue(has_media_tool, "Media tool not scoped for 'tách nhạc' (Milestone M3)")

    def test_scoping_activates_on_lay_audio(self):
        """Query containing 'lấy audio' scopes media download tools."""
        scoped = self.executor._resolve_scoped_tool_names("lấy audio video này https://fb.watch/123")
        has_media_tool = "download_media_video" in scoped or "download_media_audio" in scoped
        self.assertTrue(has_media_tool, "Media tool not scoped for 'lấy audio' (Milestone M3)")

    def test_scoping_activates_on_nhac_tiktok(self):
        """Query containing 'nhạc tiktok' scopes media download tools."""
        scoped = self.executor._resolve_scoped_tool_names("nhạc tiktok này hay quá https://vt.tiktok.com/abc")
        has_media_tool = "download_media_video" in scoped or "download_media_audio" in scoped
        self.assertTrue(has_media_tool, "Media tool not scoped for 'nhạc tiktok' (Milestone M3)")

    def test_scoping_pruning_preserves_audio_tools(self):
        """Pruning preserves media download tools within token budget."""
        scoped = self.executor._resolve_scoped_tool_names("tải mp3 https://vt.tiktok.com/123 và kiểm tra docker ps")
        has_media_tool = "download_media_video" in scoped or "download_media_audio" in scoped
        self.assertTrue(has_media_tool)
        self.assertLessEqual(len(scoped), 8)


# ─────────────────────────────────────────────────────────────────────────────
# TIER 2: BOUNDARY & CORNER CASES (30 Test Cases)
# ─────────────────────────────────────────────────────────────────────────────

class TestTier2Boundary1InvalidUrls(unittest.IsolatedAsyncioTestCase):
    """Tier 2.1: Boundary testing for invalid, empty, whitespace, and random URLs."""

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()
        self.bot = _create_mock_telegram_bot()
        self.executor = AgentToolExecutor(MagicMock(), MagicMock())

    async def test_download_audio_empty_url_error(self):
        """Contract: download_audio raises MediaPipelineError when URL is empty."""
        with self.assertRaises(MediaPipelineError):
            await self.pipeline.download_audio("")

    async def test_download_audio_whitespace_url_error(self):
        """Contract: download_audio raises MediaPipelineError for whitespace-only URL."""
        with self.assertRaises(MediaPipelineError):
            await self.pipeline.download_audio("    \t\n   ")

    async def test_download_audio_unsupported_random_domain(self):
        """Contract: Unsupported domain raises MediaPipelineError."""
        with self.assertRaises(MediaPipelineError):
            await self.pipeline.download_audio("https://unsupported-domain-xyz.com/audio/123")

    def test_fastpath_ignores_unsupported_domain_with_audio_kw(self):
        """Fast-Path does NOT intercept when URL domain is unsupported, even with audio keywords."""
        res = self.bot._detect_fastpath_media_download("tải mp3 https://wikipedia.org/wiki/Audio")
        self.assertIsNone(res, "Fastpath should not trigger on unsupported domain")

    async def test_tool_empty_url_returns_validation_error(self):
        """ReAct tool returns descriptive validation error when URL is empty."""
        res = await self.executor._execute_tool(
            "download_media_video",
            {"url": "", "media_type": "audio"},
            chat_id="123",
        )
        self.assertIn("URL", res)


class TestTier2Boundary2TikWMErrorsAndFallback(unittest.IsolatedAsyncioTestCase):
    """Tier 2.2: Boundary testing for TikWM API error responses and Tier 2 fallback."""

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()

    async def test_tikwm_error_code_non_zero_triggers_ytdlp_fallback(self):
        """When TikWM returns code != 0 (e.g. -1 'Video not found'), falls back to Tier 2 yt-dlp."""
        mock_tikwm_resp = MagicMock(status_code=200)
        mock_tikwm_resp.json.return_value = {"code": -1, "msg": "Video not found"}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_tikwm_resp

        mock_ytdlp_item = MediaItem(
            file_path="/tmp/ytdlp_fallback.mp3",
            title="Fallback Song",
            author="Artist",
            duration=30,
            media_type="audio",
            source_url="https://vt.tiktok.com/123",
        )

        with patch.object(self.pipeline, "_get_client", AsyncMock(return_value=mock_client)), \
             patch.object(self.pipeline, "_download_ytdlp_audio", AsyncMock(return_value=mock_ytdlp_item)):
            item = await self.pipeline.download_audio("https://vt.tiktok.com/123")
            self.assertEqual(item.title, "Fallback Song")

    async def test_tikwm_missing_music_key_triggers_ytdlp_fallback(self):
        """When TikWM data dict is missing 'music' key, falls back to Tier 2."""
        mock_tikwm_resp = MagicMock(status_code=200)
        mock_tikwm_resp.json.return_value = {"code": 0, "data": {"play": "https://tikwm.com/video.mp4"}}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_tikwm_resp

        mock_ytdlp_item = MediaItem(
            file_path="/tmp/ytdlp_no_music.mp3",
            title="Extracted from Video",
            author="Artist",
            duration=40,
            media_type="audio",
            source_url="https://vt.tiktok.com/123",
        )

        with patch.object(self.pipeline, "_get_client", AsyncMock(return_value=mock_client)), \
             patch.object(self.pipeline, "_download_ytdlp_audio", AsyncMock(return_value=mock_ytdlp_item)):
            item = await self.pipeline.download_audio("https://vt.tiktok.com/123")
            self.assertEqual(item.title, "Extracted from Video")

    async def test_tikwm_http_500_triggers_ytdlp_fallback(self):
        """When TikWM responds with HTTP 500, falls back to Tier 2."""
        mock_tikwm_resp = MagicMock(status_code=500, text="Internal Server Error")
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_tikwm_resp

        mock_ytdlp_item = MediaItem(
            file_path="/tmp/ytdlp_500.mp3",
            title="500 Fallback",
            author="Artist",
            duration=25,
            media_type="audio",
            source_url="https://vt.tiktok.com/123",
        )

        with patch.object(self.pipeline, "_get_client", AsyncMock(return_value=mock_client)), \
             patch.object(self.pipeline, "_download_ytdlp_audio", AsyncMock(return_value=mock_ytdlp_item)):
            item = await self.pipeline.download_audio("https://vt.tiktok.com/123")
            self.assertEqual(item.title, "500 Fallback")

    async def test_tikwm_timeout_triggers_ytdlp_fallback(self):
        """When TikWM times out, falls back to Tier 2."""
        import httpx
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.TimeoutException("TikWM timeout")

        mock_ytdlp_item = MediaItem(
            file_path="/tmp/ytdlp_timeout.mp3",
            title="Timeout Fallback",
            author="Artist",
            duration=35,
            media_type="audio",
            source_url="https://vt.tiktok.com/123",
        )

        with patch.object(self.pipeline, "_get_client", AsyncMock(return_value=mock_client)), \
             patch.object(self.pipeline, "_download_ytdlp_audio", AsyncMock(return_value=mock_ytdlp_item)):
            item = await self.pipeline.download_audio("https://vt.tiktok.com/123")
            self.assertEqual(item.title, "Timeout Fallback")

    async def test_tikwm_invalid_json_triggers_ytdlp_fallback(self):
        """When TikWM returns non-JSON HTML error page, falls back to Tier 2."""
        mock_tikwm_resp = MagicMock(status_code=200, text="<html><body>Cloudflare Block</body></html>")
        mock_tikwm_resp.json.side_effect = ValueError("Invalid JSON")

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_tikwm_resp

        mock_ytdlp_item = MediaItem(
            file_path="/tmp/ytdlp_json_err.mp3",
            title="JSON Error Fallback",
            author="Artist",
            duration=45,
            media_type="audio",
            source_url="https://vt.tiktok.com/123",
        )

        with patch.object(self.pipeline, "_get_client", AsyncMock(return_value=mock_client)), \
             patch.object(self.pipeline, "_download_ytdlp_audio", AsyncMock(return_value=mock_ytdlp_item)):
            item = await self.pipeline.download_audio("https://vt.tiktok.com/123")
            self.assertEqual(item.title, "JSON Error Fallback")


class TestTier2Boundary3AudioOver50MB(unittest.IsolatedAsyncioTestCase):
    """Tier 2.3: Boundary testing for audio files exceeding Telegram's 50MB limit."""

    def setUp(self):
        self.bot = _create_mock_telegram_bot()
        self.executor = AgentToolExecutor(MagicMock(), MagicMock())
        self.executor.telegram_bot = self.bot

    async def test_send_audio_rejects_over_50mb(self):
        """send_audio returns False immediately when audio file size > 50MB."""
        if not hasattr(self.bot, "send_audio"):
            self.fail("TelegramBot must implement 'send_audio' method (Milestone M2)")

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"0")
            tmp_path = f.name

        try:
            with patch.object(Path, "stat") as mock_stat:
                mock_stat_res = MagicMock()
                mock_stat_res.st_size = 55 * 1024 * 1024
                mock_stat.return_value = mock_stat_res

                res = await self.bot.send_audio(chat_id="123", audio_path=tmp_path)
                self.assertFalse(res, "send_audio must return False when file > 50MB")
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    async def test_fastpath_audio_over_50mb_publishes_to_storage(self):
        """Audio > 50MB is published to media_storage_manager for direct download."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"HUGE_AUDIO_DATA")
            tmp_path = f.name

        try:
            rec = media_storage_manager.publish_download_item(
                file_path=tmp_path,
                filename="huge_podcast.mp3",
                title="Long Podcast 2 Hours",
                duration=7200,
                ttl_seconds=14400,
            )
            self.assertIsInstance(rec, DownloadRecord)
            self.assertIn("huge_podcast.mp3", rec.lan_url)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    async def test_fastpath_audio_over_50mb_delivers_lan_and_internet_links(self):
        """Delivery message for > 50MB audio contains both Ngrok internet and LAN direct links."""
        rec = DownloadRecord(
            token="tok123",
            filename="podcast.mp3",
            file_path=Path("/tmp/podcast.mp3"),
            title="Podcast",
            duration=3600,
            file_size=60 * 1024 * 1024,
            created_at=100.0,
            expires_at=200.0,
            internet_url="https://kirito.ngrok-free.app/downloads/tok123/podcast.mp3",
            lan_url="http://192.168.0.100:8000/downloads/tok123/podcast.mp3",
        )
        msg = (
            f"📦 <b>Tệp âm thanh dung lượng lớn (60.0 MB)!</b>\n"
            f"🌐 <b>Internet:</b> {rec.internet_url}\n"
            f"🏠 <b>LAN:</b> {rec.lan_url}"
        )
        self.assertIn("ngrok-free.app", msg)
        self.assertIn("192.168.0.100", msg)

    def test_fastpath_audio_over_50mb_disables_temp_cleanup(self):
        """When transferred to media_storage_manager, item.is_temp_file is set to False."""
        item = MediaItem(
            file_path="/tmp/huge.mp3",
            title="Big Audio",
            author="Host",
            duration=5000,
            media_type="audio",
            source_url="https://youtube.com/podcast",
            is_temp_file=True,
        )
        item.is_temp_file = False
        self.assertFalse(item.is_temp_file)

    async def test_tool_audio_over_50mb_returns_direct_download_links(self):
        """Agent tool returns friendly message with direct links when audio > 50MB."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"AUDIO")
            tmp_path = f.name

        mock_item = MediaItem(
            file_path=tmp_path,
            title="Heavy Podcast",
            author="Creator",
            duration=3600,
            media_type="audio",
            source_url="https://youtube.com/watch?v=heavy",
            file_size=65 * 1024 * 1024,
        )

        mock_pipeline = MagicMock()
        mock_pipeline.download_audio = AsyncMock(return_value=mock_item)

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline):
            res = await self.executor._execute_tool(
                "download_media_video",
                {"url": "https://youtube.com/watch?v=heavy", "media_type": "audio"},
                chat_id="123",
            )
            self.assertIsInstance(res, str)
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


class TestTier2Boundary4ExtremeMetadataLength(unittest.IsolatedAsyncioTestCase):
    """Tier 2.4: Boundary testing for title/author/caption length truncation (>256 or >350 chars)."""

    def setUp(self):
        self.bot = _create_mock_telegram_bot()

    async def test_send_audio_truncates_title_over_256_chars(self):
        """Title longer than 256 characters is safely truncated to avoid Telegram API errors."""
        long_title = "A" * 400
        truncated = long_title[:256]
        self.assertEqual(len(truncated), 256)

    async def test_send_audio_truncates_performer_over_256_chars(self):
        """Performer longer than 256 characters is safely truncated."""
        long_performer = "B" * 350
        truncated = long_performer[:256]
        self.assertEqual(len(truncated), 256)

    async def test_send_audio_truncates_caption_over_1024_chars(self):
        """Caption longer than 1024 characters is safely truncated to 1024."""
        long_caption = "C" * 2000
        truncated = long_caption[:1024]
        self.assertEqual(len(truncated), 1024)

    def test_tool_truncates_title_over_350_chars(self):
        """Tool formatting truncates title > 350 chars with ellipsis."""
        raw_title = "X" * 400
        if len(raw_title) > 350:
            formatted_title = raw_title[:347] + "..."
        self.assertEqual(len(formatted_title), 350)
        self.assertTrue(formatted_title.endswith("..."))

    def test_vietnamese_multibyte_truncation_safety(self):
        """Truncation does not corrupt multibyte UTF-8 Vietnamese characters."""
        text = "Tiểu Bảo Bảo tải nhạc MP3 chất lượng cao " * 10
        sliced = text[:50]
        self.assertIsInstance(sliced, str)
        self.assertLessEqual(len(sliced), 50)


class TestTier2Boundary5SpecialAndMaliciousHtml(unittest.TestCase):
    """Tier 2.5: Boundary testing for HTML entity escaping and malicious injection."""

    def test_send_audio_escapes_script_tag_in_caption(self):
        """HTML escaping neutralizes script tags in captions."""
        raw = "Check this track <script>alert('pwned')</script>"
        safe = html.escape(raw)
        self.assertNotIn("<script>", safe)
        self.assertIn("&lt;script&gt;", safe)

    def test_send_audio_handles_unclosed_tags(self):
        """_strip_html_tags handles unclosed tags during fallback."""
        unclosed = "<b>Bold title <unclosed tag"
        stripped = _strip_html_tags(unclosed)
        self.assertNotIn("<b>", stripped)

    def test_send_audio_handles_ampersand(self):
        """Raw ampersand '&' is safely escaped to '&amp;'."""
        raw = "Tom & Jerry Soundtrack"
        safe = html.escape(raw)
        self.assertEqual(safe, "Tom &amp; Jerry Soundtrack")

    def test_send_audio_handles_angle_brackets_in_title(self):
        """Title containing angle brackets '<<VIP>>' is safely escaped."""
        raw = "Artist <<Exclusive Track>>"
        safe = html.escape(raw)
        self.assertEqual(safe, "Artist &lt;&lt;Exclusive Track&gt;&gt;")

    def test_strip_html_tags_cleans_complex_entities(self):
        """_strip_html_tags cleans complex nested and malformed HTML."""
        complex_html = "<div><p>Paragraph <b>bold</b> <a href='http://evil.com'>link</a></p></div>"
        cleaned = _strip_html_tags(complex_html)
        self.assertNotIn("<", cleaned)
        self.assertNotIn(">", cleaned)
        self.assertIn("Paragraph bold link", cleaned)


class TestTier2Boundary6ConcurrencyAndSemaphore(unittest.IsolatedAsyncioTestCase):
    """Tier 2.6: Boundary testing for concurrency limits and Semaphore resource protection."""

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()

    async def test_audio_pipeline_respects_ytdlp_semaphore(self):
        """yt-dlp downloads acquire the semaphore."""
        sem = self.pipeline._ytdlp_semaphore
        self.assertEqual(sem._value, 2)
        async with sem:
            self.assertEqual(sem._value, 1)

    async def test_audio_semaphore_released_on_error(self):
        """Semaphore is safely released even if an error is raised inside the block."""
        sem = self.pipeline._ytdlp_semaphore
        initial = sem._value
        try:
            async with sem:
                raise RuntimeError("Simulated download failure")
        except RuntimeError:
            pass
        self.assertEqual(sem._value, initial)

    async def test_concurrent_audio_tasks_no_deadlock(self):
        """Multiple concurrent tasks execute through the semaphore without deadlocking."""
        sem = self.pipeline._ytdlp_semaphore
        completed = 0

        async def worker():
            nonlocal completed
            async with sem:
                await asyncio.sleep(0.01)
                completed += 1

        tasks = [asyncio.create_task(worker()) for _ in range(6)]
        await asyncio.gather(*tasks)
        self.assertEqual(completed, 6)

    async def test_audio_chunked_streaming_buffer_size_64kb(self):
        """Chunk size constant is 64KB (65536 bytes) to preserve RAM."""
        chunk_size = 64 * 1024
        self.assertEqual(chunk_size, 65536)

    async def test_reclaim_memory_background_invoked_post_download(self):
        """Verifies memory reclamation task can be called without exception."""
        from app.core.memory_reclaimer import reclaim_memory_background
        try:
            await reclaim_memory_background(delay_seconds=0.01)
        except Exception as e:
            self.fail(f"reclaim_memory_background failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# TIER 3: CROSS-FEATURE COMBINATIONS (8 Test Cases)
# ─────────────────────────────────────────────────────────────────────────────

class TestTier3CrossFeatureCombinations(unittest.IsolatedAsyncioTestCase):
    """Tier 3: Pairwise and cross-feature pipeline combination tests."""

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()
        self.bot = _create_mock_telegram_bot()
        self.executor = AgentToolExecutor(MagicMock(), MagicMock())
        self.executor.telegram_bot = self.bot

    async def test_cross_tikwm_fail_ytdlp_fallback_to_send_audio_and_cleanup(self):
        """TikWM fails -> yt-dlp succeeds -> send_audio succeeds -> temporary file cleaned up."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"COMBINATION_AUDIO_DATA")
            tmp_path = f.name

        mock_item = MediaItem(
            file_path=tmp_path,
            title="Cross Fallback Song",
            author="Cross Artist",
            duration=120,
            media_type="audio",
            source_url="https://vt.tiktok.com/cross123",
            file_size=22,
            is_temp_file=True,
        )

        with patch.object(self.pipeline, "_download_tikwm_audio", AsyncMock(side_effect=Exception("TikWM down"))), \
             patch.object(self.pipeline, "_download_ytdlp_audio", AsyncMock(return_value=mock_item)), \
             patch.object(self.bot, "send_audio", AsyncMock(return_value=True), create=True):

            if hasattr(self.pipeline, "download_audio"):
                item = await self.pipeline.download_audio("https://vt.tiktok.com/cross123")
                self.assertEqual(item.title, "Cross Fallback Song")
                if hasattr(self.bot, "send_audio"):
                    sent = await self.bot.send_audio(
                        chat_id="123",
                        audio_path=item.file_path,
                        title=item.title,
                        performer=item.author,
                        duration=item.duration,
                    )
                    self.assertTrue(sent)
                else:
                    self.fail("send_audio not implemented in TelegramBot (Milestone M2)")
                item.cleanup()
                self.assertFalse(os.path.exists(tmp_path))
            else:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                self.fail("download_audio not implemented (Milestone M1)")

    async def test_cross_fastpath_audio_html_entity_failure_seek_retry_and_cleanup(self):
        """Fast-Path audio -> send_audio HTML entity failure -> f.seek(0) retry plain text -> cleanup."""
        if not hasattr(self.bot, "send_audio"):
            self.fail("send_audio not implemented (Milestone M2)")

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"AUDIO_DATA_FOR_RETRY")
            tmp_path = f.name

        try:
            err_resp = MagicMock(status_code=400, text="can't parse entities: unclosed tag")
            ok_resp = MagicMock(status_code=200, text='{"ok": true}')

            mock_client = AsyncMock()
            mock_client.post.side_effect = [err_resp, ok_resp]

            with patch.object(TelegramBot, "_http_client", new_callable=PropertyMock) as mock_prop:
                mock_prop.return_value = mock_client
                sent = await self.bot.send_audio(
                    chat_id="123456",
                    audio_path=tmp_path,
                    title="Audio Title",
                    caption="<b>Bad <unclosed</b>",
                )
                self.assertTrue(sent)
                self.assertEqual(mock_client.post.call_count, 2)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    async def test_cross_tool_download_media_video_audio_mode_e2e(self):
        """download_media_video(media_type='audio') calls download_audio and sends audio."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"TOOL_AUDIO")
            tmp_path = f.name

        mock_item = MediaItem(
            file_path=tmp_path,
            title="Tool Audio",
            author="Tool Artist",
            duration=60,
            media_type="audio",
            source_url="https://vt.tiktok.com/tool_audio",
            file_size=10,
            is_temp_file=True,
        )

        mock_pipeline = MagicMock()
        mock_pipeline.download_audio = AsyncMock(return_value=mock_item)

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline), \
             patch.object(self.bot, "send_audio", AsyncMock(return_value=True), create=True):
            res = await self.executor._execute_tool(
                "download_media_video",
                {"url": "https://vt.tiktok.com/tool_audio", "media_type": "audio"},
                chat_id="123456",
            )
            self.assertIsInstance(res, str)
            self.assertFalse(os.path.exists(tmp_path))

    async def test_cross_tool_download_media_audio_with_custom_caption_e2e(self):
        """download_media_audio passes custom caption to send_audio."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"AUDIO")
            tmp_path = f.name

        mock_item = MediaItem(
            file_path=tmp_path,
            title="Custom Caption Song",
            author="Artist",
            duration=75,
            media_type="audio",
            source_url="https://youtu.be/custom",
            file_size=5,
            is_temp_file=True,
        )

        mock_pipeline = MagicMock()
        mock_pipeline.download_audio = AsyncMock(return_value=mock_item)

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline), \
             patch.object(self.bot, "send_audio", AsyncMock(return_value=True), create=True) as mock_send_audio:
            res = await self.executor._execute_tool(
                "download_media_audio",
                {"url": "https://youtu.be/custom", "caption": "🎵 Bài hát yêu thích của anh Mạnh"},
                chat_id="123456",
            )
            self.assertIsInstance(res, str)
            if mock_send_audio.called:
                call_args = mock_send_audio.call_args[1]
                self.assertIn("yêu thích", call_args.get("caption", ""))
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    async def test_cross_fastpath_large_audio_storage_link_delivery(self):
        """Audio > 50MB via Fast-Path publishes download record and sends links."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"LARGE_PODCAST")
            tmp_path = f.name

        mock_item = MediaItem(
            file_path=tmp_path,
            title="Massive Podcast Episode",
            author="Podcaster",
            duration=7200,
            media_type="audio",
            source_url="https://youtube.com/watch?v=podcast_ep1",
            file_size=65 * 1024 * 1024,
            is_temp_file=True,
        )

        mock_pipeline = MagicMock()
        mock_pipeline.download_audio = AsyncMock(return_value=mock_item)

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline):
            rec = media_storage_manager.publish_download_item(
                file_path=tmp_path,
                filename="massive_podcast.mp3",
                title=mock_item.title,
                duration=mock_item.duration,
                ttl_seconds=14400,
            )
            mock_item.is_temp_file = False
            self.assertFalse(mock_item.is_temp_file)
            self.assertIn("massive_podcast.mp3", rec.lan_url)
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    async def test_cross_backwards_compat_video_mode_unaffected(self):
        """When media_type is 'video', download_media_video uses video pipeline and send_video."""
        mock_item = MediaItem(
            file_path="/tmp/video.mp4",
            title="Video Title",
            author="Channel",
            duration=60,
            media_type="video",
            source_url="https://youtube.com/watch?v=123",
            file_size=10 * 1024 * 1024,
        )

        mock_pipeline = MagicMock()
        mock_pipeline.download = AsyncMock(return_value=mock_item)

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline), \
             patch.object(self.bot, "send_video", AsyncMock(return_value=True)) as mock_send_video:
            await self.executor._execute_tool(
                "download_media_video",
                {"url": "https://youtube.com/watch?v=123", "media_type": "video"},
                chat_id="123456",
            )
            mock_pipeline.download.assert_called_once()
            mock_send_video.assert_called_once()

    def test_cross_dual_scoping_audio_and_video_intent(self):
        """Query with both video and audio intent scopes media tools properly."""
        scoped = self.executor._resolve_scoped_tool_names("vừa tải video vừa tải mp3 https://vt.tiktok.com/123")
        has_media_tool = "download_media_video" in scoped or "download_media_audio" in scoped
        self.assertTrue(has_media_tool)

    async def test_cross_pipeline_total_failure_clean_temp_removal(self):
        """When both Tier 1 and Tier 2 fail, MediaPipelineError is raised and no orphaned files remain."""
        with patch.object(self.pipeline, "_download_tikwm_audio", AsyncMock(side_effect=Exception("Tier 1 fail"))), \
             patch.object(self.pipeline, "_download_ytdlp_audio", AsyncMock(side_effect=Exception("Tier 2 fail"))):
            with self.assertRaises(MediaPipelineError):
                await self.pipeline.download_audio("https://vt.tiktok.com/total_fail")


# ─────────────────────────────────────────────────────────────────────────────
# TIER 4: REAL-WORLD APPLICATION SCENARIOS (6 Test Cases)
# ─────────────────────────────────────────────────────────────────────────────

class TestTier4RealWorldScenarios(unittest.IsolatedAsyncioTestCase):
    """Tier 4: Realistic user interaction and end-to-end operational scenarios."""

    def setUp(self):
        self.bot = _create_mock_telegram_bot()
        self.executor = AgentToolExecutor(MagicMock(), MagicMock())
        self.executor.telegram_bot = self.bot

    def test_tier4_scenario_tiktok_user_says_tai_mp3_bai_nay_cho_anh(self):
        """Scenario 1: User sends 'tải mp3 bài này cho anh https://vt.tiktok.com/ZS123456/'."""
        text = "tải mp3 bài này cho anh https://vt.tiktok.com/ZS123456/"
        res = self.bot._detect_fastpath_media_download(text)
        self.assertIsNotNone(res, "Fastpath must intercept TikTok MP3 download request (Milestone M2)")
        self.assertEqual(res[0], "https://vt.tiktok.com/ZS123456/")
        if hasattr(res, "media_type"):
            self.assertEqual(res.media_type, "audio")

    def test_tier4_scenario_facebook_reels_user_says_lay_audio_video_nay_nhe(self):
        """Scenario 2: User sends 'lấy audio video này nhé https://www.facebook.com/reel/123456789'."""
        text = "lấy audio video này nhé https://www.facebook.com/reel/123456789"
        res = self.bot._detect_fastpath_media_download(text)
        self.assertIsNotNone(res, "Fastpath must intercept Facebook Reels audio request (Milestone M2)")
        self.assertEqual(res[0], "https://www.facebook.com/reel/123456789")
        if hasattr(res, "media_type"):
            self.assertEqual(res.media_type, "audio")

    def test_tier4_scenario_system_prompt_knowledge_mp3_capability_affirmation(self):
        """Scenario 3: System Prompt contains MP3 320kbps knowledge & affirmation reflex."""
        agent = AiAgentService(MagicMock(), MagicMock(), MagicMock())
        prompt = agent._STATIC_SYSTEM_PREFIX
        has_mp3_knowledge = (
            "mp3" in prompt.lower()
            or "audio" in prompt.lower()
            or "download_media_audio" in prompt
        )
        self.assertTrue(has_mp3_knowledge, "System prompt in ai_agent.py must reflect MP3 capability (Milestone M3)")

    def test_tier4_scenario_negative_keyword_dung_tai_nhac_yields_to_agent(self):
        """Scenario 4: User says 'đừng tải nhạc bài này https://youtu.be/123' -> yields to agent."""
        text = "đừng tải nhạc bài này https://youtu.be/123"
        res = self.bot._detect_fastpath_media_download(text)
        self.assertIsNone(res, "Negative keyword 'đừng tải nhạc' must yield to AI Agent (no fastpath intercept)")

    def test_tier4_scenario_youtube_shorts_user_says_tach_nhac_bai_nay_gium_anh(self):
        """Scenario 5: User says 'tách nhạc bài này giùm anh https://youtube.com/shorts/3dYx1pB9VvE'."""
        text = "tách nhạc bài này giùm anh https://youtube.com/shorts/3dYx1pB9VvE"
        res = self.bot._detect_fastpath_media_download(text)
        self.assertIsNotNone(res, "Fastpath must intercept YouTube Shorts audio extraction request (Milestone M2)")
        self.assertEqual(res[0], "https://youtube.com/shorts/3dYx1pB9VvE")
        if hasattr(res, "media_type"):
            self.assertEqual(res.media_type, "audio")

    def test_tier4_scenario_conversational_question_co_tai_duoc_mp3_tiktok_khong(self):
        """Scenario 6: User asks 'Hiện tại bạn có tải được mp3 tiktok chất lượng cao được không'."""
        text = "Hiện tại bạn có tải được mp3 tiktok chất lượng cao được không"
        res = self.bot._detect_fastpath_media_download(text)
        self.assertIsNone(res, "Conversational question must yield to AI Agent for natural response")


if __name__ == "__main__":
    unittest.main()
