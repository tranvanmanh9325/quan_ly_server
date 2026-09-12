"""
Unit tests using standard library unittest for MediaItem lifecycle and Telegram caption HTML handling.
"""

import asyncio
import html
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.media_downloader import (
    MediaItem,
    cleanup_expired_media,
    TEMP_MEDIA_DIR,
)
from app.services.telegram_bot import _strip_html_tags, TelegramBot


class TestMediaItemLifecycle(unittest.TestCase):
    def test_media_item_cleanup_deletes_file_and_parent_dir(self):
        with tempfile.TemporaryDirectory(dir=str(TEMP_MEDIA_DIR)) as parent_tmp:
            dummy_file = Path(parent_tmp) / "sample_video.mp4"
            dummy_file.write_bytes(b"dummy mp4 content")
            self.assertTrue(dummy_file.exists())

            item = MediaItem(
                file_path=str(dummy_file),
                title="Test Video",
                author="Test Author",
                duration=15,
                media_type="video",
                source_url="https://example.com/video",
                file_size=len(b"dummy mp4 content"),
                is_temp_file=True,
            )

            item.cleanup()
            self.assertFalse(dummy_file.exists(), "File should be deleted by cleanup()")

    def test_media_item_sync_context_manager(self):
        with tempfile.TemporaryDirectory(dir=str(TEMP_MEDIA_DIR)) as parent_tmp:
            dummy_file = Path(parent_tmp) / "context_sync.mp4"
            dummy_file.write_bytes(b"sync content")

            item = MediaItem(
                file_path=str(dummy_file),
                title="Test Video",
                author="Test Author",
                duration=10,
                media_type="video",
                source_url="https://example.com/sync",
                file_size=12,
                is_temp_file=True,
            )

            with item as managed_item:
                self.assertEqual(managed_item.file_path, str(dummy_file))
                self.assertTrue(Path(dummy_file).exists())

            self.assertFalse(Path(dummy_file).exists(), "File should be cleaned up after with block")

    def test_media_item_async_context_manager(self):
        async def run_async_test():
            with tempfile.TemporaryDirectory(dir=str(TEMP_MEDIA_DIR)) as parent_tmp:
                dummy_file = Path(parent_tmp) / "context_async.mp4"
                dummy_file.write_bytes(b"async content")

                item = MediaItem(
                    file_path=str(dummy_file),
                    title="Test Video",
                    author="Test Author",
                    duration=10,
                    media_type="video",
                    source_url="https://example.com/async",
                    file_size=13,
                    is_temp_file=True,
                )

                async with item as managed_item:
                    self.assertEqual(managed_item.file_path, str(dummy_file))
                    self.assertTrue(Path(dummy_file).exists())

                self.assertFalse(Path(dummy_file).exists(), "File should be cleaned up after async with block")

        asyncio.run(run_async_test())

    def test_cleanup_expired_media(self):
        TEMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        old_file = TEMP_MEDIA_DIR / "expired_test_old.mp4"
        old_file.write_bytes(b"expired content")

        # Mock modification time to 15 minutes ago
        fifteen_min_ago = time.time() - 900
        os.utime(str(old_file), (fifteen_min_ago, fifteen_min_ago))

        fresh_file = TEMP_MEDIA_DIR / "fresh_test.mp4"
        fresh_file.write_bytes(b"fresh content")

        cleaned = cleanup_expired_media(max_age_seconds=600)
        self.assertGreaterEqual(cleaned, 1)
        self.assertFalse(old_file.exists(), "Old expired file should have been deleted")
        self.assertTrue(fresh_file.exists(), "Fresh file should remain intact")

        fresh_file.unlink(missing_ok=True)


class TestTelegramCaptionAndFallback(unittest.TestCase):
    def test_strip_html_tags(self):
        raw = "🎬 <b>Title with &amp; entity</b>\n<code>@author_name</code>"
        stripped = _strip_html_tags(raw)
        self.assertEqual(stripped, "🎬 Title with & entity\n@author_name")
        self.assertNotIn("<b>", stripped)
        self.assertNotIn("<code>", stripped)

    def test_html_escape_special_characters(self):
        dirty_title = "Video <Special> & 'Exclusive' \"2026\""
        safe = html.escape(dirty_title)
        self.assertNotIn("<Special>", safe)
        self.assertIn("&lt;Special&gt;", safe)
        self.assertIn("&amp;", safe)

    def test_send_video_includes_parse_mode_html(self):
        async def run():
            bot = TelegramBot.__new__(TelegramBot)
            bot.token = "fake-token"
            bot._http_client = AsyncMock()

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            bot._http_client.post = AsyncMock(return_value=mock_resp)

            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
                f.write(b"fake video")
                tmp_path = f.name

            try:
                caption = "🎬 <b>Test Title</b>\n👤 Kênh: <code>@author</code>"
                sent = await bot.send_video(
                    chat_id="123456",
                    video_path=tmp_path,
                    caption=caption,
                    duration=12,
                )
                self.assertTrue(sent)
                call_args = bot._http_client.post.call_args
                self.assertIsNotNone(call_args)
                data_arg = call_args.kwargs.get("data") or call_args[1].get("data")
                self.assertEqual(data_arg["parse_mode"], "HTML")
                self.assertEqual(data_arg["caption"], caption)
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        asyncio.run(run())

    def test_send_video_resilient_fallback_on_parse_error(self):
        async def run():
            bot = TelegramBot.__new__(TelegramBot)
            bot.token = "fake-token"
            bot._http_client = AsyncMock()

            # First call fails with "can't parse entities", second call succeeds
            mock_fail = MagicMock()
            mock_fail.status_code = 400
            mock_fail.text = "Bad Request: can't parse entities: Character '<' is reserved"

            mock_ok = MagicMock()
            mock_ok.status_code = 200

            bot._http_client.post = AsyncMock(side_effect=[mock_fail, mock_ok])

            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
                f.write(b"fake video")
                tmp_path = f.name

            try:
                caption = "🎬 <b>Broken <Tag</b>"
                sent = await bot.send_video(
                    chat_id="123456",
                    video_path=tmp_path,
                    caption=caption,
                )
                self.assertTrue(sent)
                self.assertEqual(bot._http_client.post.call_count, 2)
                second_call_data = bot._http_client.post.call_args_list[1].kwargs.get("data")
                self.assertNotIn("parse_mode", second_call_data)
                self.assertNotIn("<b>", second_call_data["caption"])
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
