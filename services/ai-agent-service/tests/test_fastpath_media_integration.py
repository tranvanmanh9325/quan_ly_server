"""
Integration and regression unit test suite for Fast-Path Media Bot and AI Agent Gateway.
Covers:
1. Multi-platform URL regex and intent detection (YouTube Shorts, Facebook Reels/Watch, Threads, TikTok, Douyin).
2. Trailing punctuation stripping and unaccented Vietnamese keywords.
3. Analysis questions yielding gracefully to the AI Agent (preventing 'tai sao' false triggers).
4. Dynamic scoping of download_media_video in AgentToolExecutor.
5. Tool schema definitions and system prompt synchronization.
6. Zero-Disk-Leak lifecycle assurance and Telegram send_video plain text fallback.
"""

import asyncio
import html
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.telegram_bot import TelegramBot, _strip_html_tags
from app.services.ai_agent_tools import AgentToolExecutor
from app.services.ai_agent import AiAgentService
from app.services.media_downloader import MediaItem, VideoTooLargeError, TEMP_MEDIA_DIR


class TestMediaUrlRegexAndFastPathIntent(unittest.TestCase):
    """Test suite validating URL Regex matching and Fast-path intent classification."""

    def setUp(self):
        self.bot = TelegramBot.__new__(TelegramBot)

    def test_youtube_url_variants(self):
        """Verify all variants of YouTube URLs including Shorts, desktop, short-domain and mobile."""
        urls = [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://www.youtube.com/shorts/3dYx1pB9VvE",
            "https://youtube.com/shorts/3dYx1pB9VvE",
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
            "http://youtu.be/dQw4w9WgXcQ",
        ]
        for url in urls:
            res = self.bot._detect_fastpath_media_download(url)
            self.assertIsNotNone(res, f"Failed on YouTube URL: {url}")
            self.assertEqual(res[0], url)
            self.assertEqual(res[1], "")

    def test_facebook_url_variants(self):
        """Verify Facebook URLs: Reels, desktop web., Watch, fb.watch, fb.me, user videos, share links."""
        urls = [
            "https://www.facebook.com/reel/123456789",
            "https://web.facebook.com/reel/123456789",
            "https://m.facebook.com/reels/123456789",
            "https://facebook.com/share/r/123456789/",
            "https://www.facebook.com/watch/?v=123456789",
            "https://www.facebook.com/watch?v=123456789",
            "https://web.facebook.com/watch?v=123456789",
            "https://fb.watch/abcXYZ123/",
            "https://fb.me/abcXYZ123",
            "https://www.facebook.com/user.name/videos/123456789/",
            "https://web.facebook.com/user.name/videos/123456789/",
        ]
        for url in urls:
            res = self.bot._detect_fastpath_media_download(url)
            self.assertIsNotNone(res, f"Failed on Facebook URL: {url}")
            self.assertEqual(res[0], url)

    def test_threads_url_variants(self):
        """Verify Threads URLs: threads.net posts, /t/ short links, and threads.com."""
        urls = [
            "https://www.threads.net/@zuck/post/DA12345",
            "https://threads.net/@zuck/post/DA12345",
            "https://www.threads.net/t/DA12345",
            "https://threads.net/t/DA12345",
            "https://threads.com/@user/post/xyz123",
        ]
        for url in urls:
            res = self.bot._detect_fastpath_media_download(url)
            self.assertIsNotNone(res, f"Failed on Threads URL: {url}")
            self.assertEqual(res[0], url)

    def test_other_supported_platforms(self):
        """Verify TikTok, Douyin, Instagram, and Twitter/X."""
        urls = [
            "https://www.tiktok.com/@user/video/1234567890",
            "https://vt.tiktok.com/ZS123456/",
            "https://www.douyin.com/video/1234567890",
            "https://v.douyin.com/iABCxyz/",
            "https://www.instagram.com/reel/C123456789/",
            "https://www.instagram.com/p/C123456789/",
            "https://twitter.com/user/status/1234567890",
            "https://x.com/user/status/1234567890",
        ]
        for url in urls:
            res = self.bot._detect_fastpath_media_download(url)
            self.assertIsNotNone(res, f"Failed on platform URL: {url}")
            self.assertEqual(res[0], url)

    def test_unaccented_and_accented_download_keywords(self):
        """Verify fast-path triggers for accented and unaccented Vietnamese download requests."""
        url = "https://www.youtube.com/shorts/3dYx1pB9VvE"
        test_cases = [
            f"tải video {url}",
            f"{url} tải về",
            f"kéo video {url}",
            f"gửi em {url}",
            f"tai video {url}",
            f"{url} tai ve",
            f"keo video {url}",
            f"lay video {url}",
            f"tai clip {url}",
            f"gui em {url}",
            f"chuyển file {url}",
        ]
        for phrase in test_cases:
            res = self.bot._detect_fastpath_media_download(phrase)
            self.assertIsNotNone(res, f"Expected fast-path trigger for: '{phrase}'")
            self.assertEqual(res[0], url)

    def test_trailing_punctuation_stripping(self):
        """Verify trailing punctuation commonly appended in chat is cleaned from URL."""
        base_url = "https://youtu.be/dQw4w9WgXcQ"
        punctuations = [".", ",", ";", "!", "?", ")", '"', "'"]
        for p in punctuations:
            text = f"Tải giúp anh {base_url}{p}"
            res = self.bot._detect_fastpath_media_download(text)
            self.assertIsNotNone(res, f"Failed stripping punctuation '{p}'")
            self.assertEqual(res[0], base_url)

    def test_analysis_and_question_keywords_yield_to_agent(self):
        """Verify conversational questions yield to LLM by returning None (no fast-path intercept)."""
        url = "https://youtu.be/dQw4w9WgXcQ"
        analysis_queries = [
            f"{url} tóm tắt nội dung video này",
            f"dịch giúp anh bài hát trong video {url}",
            f"video này nói về gì {url}",
            f"giải thích clip này {url}",
            f"ai đây {url}",
            f"noi ve gi {url}",
            f"tom tat {url}",
            f"dich clip {url}",
            f"xem gium em clip nay {url}",
            f"tai sao video nay noi ve gi {url}",
            f"tại sao lại như thế {url}",
        ]
        for q in analysis_queries:
            res = self.bot._detect_fastpath_media_download(q)
            self.assertIsNone(res, f"Query '{q}' should yield to AI Agent but got: {res}")


class TestAiAgentToolsMediaScoping(unittest.TestCase):
    """Test suite ensuring dynamic tool scoping activates download_media_video correctly."""

    def setUp(self):
        self.executor = AgentToolExecutor(MagicMock(), MagicMock())

    def test_scoped_tools_for_threads_and_facebook_urls(self):
        """Verify Threads and Facebook URLs automatically scope download_media_video."""
        queries = [
            "https://www.threads.net/@zuck/post/DA12345",
            "https://threads.net/t/12345",
            "Kiểm tra link https://www.threads.net/@user/post/xyz",
            "Xem link https://threads.net/t/123",
            "https://web.facebook.com/reel/123456789",
            "https://facebook.com/share/r/123456789/",
            "https://fb.watch/abcXYZ123/",
            "https://www.youtube.com/shorts/3dYx1pB9VvE",
            "tai video threads",
            "tai video facebook",
            "lay clip threads",
            "keo video youtube",
        ]
        for q in queries:
            scoped = self.executor._resolve_scoped_tool_names(query=q)
            self.assertIn(
                "download_media_video",
                scoped,
                f"Query '{q}' did not scope 'download_media_video' tool!"
            )

    def test_download_media_video_tool_schema(self):
        """Verify tool schema description includes Threads, YouTube Shorts, and Facebook Reels/Watch."""
        defs = self.executor._build_tools()
        media_tool = next(
            (t for t in defs if t.get("function", {}).get("name") == "download_media_video"),
            None
        )
        self.assertIsNotNone(media_tool, "download_media_video tool not found in schema definitions")
        fn = media_tool["function"]
        desc = fn["description"]
        url_desc = fn["parameters"]["properties"]["url"]["description"]

        self.assertIn("Threads", desc)
        self.assertIn("YouTube Shorts", desc)
        self.assertIn("Facebook Reels", desc)
        self.assertIn("Threads", url_desc)
        self.assertIn("YouTube Shorts", url_desc)


class TestAiAgentSystemPromptIntegration(unittest.TestCase):
    """Test suite ensuring system instruction in ai_agent.py guides the LLM on supported platforms."""

    def test_system_prompt_contains_supported_platforms(self):
        agent = AiAgentService(MagicMock(), MagicMock(), MagicMock())
        prompt = agent._STATIC_SYSTEM_PREFIX
        self.assertIn("Threads", prompt)
        self.assertIn("YouTube Shorts", prompt)
        self.assertIn("Facebook Reels/Watch", prompt)
        self.assertIn("download_media_video", prompt)


class TestFastpathExecutionAndLifecycle(unittest.IsolatedAsyncioTestCase):
    """Test suite verifying end-to-end send_video streaming, HTML captioning, and Zero-Disk-Leak."""

    async def test_send_video_resilient_fallback_on_parse_error(self):
        """Test send_video retries as plain text with f.seek(0) when Telegram rejects HTML entities."""
        bot = TelegramBot.__new__(TelegramBot)
        bot.token = "dummy_token"

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"dummy mp4 data content")
            tmp_path = f.name

        try:
            mock_client = MagicMock()
            # First request: 400 Bad Request: can't parse entities
            err_resp = MagicMock()
            err_resp.status_code = 400
            err_resp.text = "Bad Request: can't parse entities: Character '<' is reserved"

            # Second request (plain text retry): 200 OK
            ok_resp = MagicMock()
            ok_resp.status_code = 200
            ok_resp.text = '{"ok": true}'

            mock_client.post = AsyncMock(side_effect=[err_resp, ok_resp])
            with patch.object(TelegramBot, "_http_client", new_callable=PropertyMock) as mock_prop:
                mock_prop.return_value = mock_client

                success = await bot.send_video(
                    chat_id="123456",
                    video_path=tmp_path,
                    caption="🎬 <b>Test Title with <unclosed></b>",
                    parse_mode="HTML",
                )

                self.assertTrue(success, "send_video should succeed via plain text fallback")
                self.assertEqual(mock_client.post.call_count, 2)

                # Verify second request payload stripped parse_mode and HTML tags
                call2_kwargs = mock_client.post.call_args_list[1][1]
                data2 = call2_kwargs.get("data", {})
                self.assertNotIn("parse_mode", data2)
                self.assertEqual(data2.get("caption"), "🎬 Test Title with ")
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    async def test_fastpath_process_update_zero_disk_leak_on_success(self):
        """Test _process_update ensures media_item.cleanup() is called in finally block on success."""
        bot = TelegramBot.__new__(TelegramBot)
        bot.token = "dummy_token"
        bot.chat_id = "123456"
        bot._claim_update = AsyncMock(return_value=True)
        bot._video_debounce = MagicMock()
        bot._video_debounce.handle_user_text = AsyncMock(return_value=False)
        bot._pending_archives = {}
        bot._rate_limiter = MagicMock()
        bot._rate_limiter.acquire = AsyncMock()
        bot.send_message_with_result = AsyncMock(return_value={"message_id": 999})
        bot.delete_message = AsyncMock(return_value=True)
        bot.send_video = AsyncMock(return_value=True)

        mock_media_item = MagicMock(spec=MediaItem)
        mock_media_item.media_type = "video"
        mock_media_item.file_path = "/tmp/media_downloads/test.mp4"
        mock_media_item.title = "Sample Video"
        mock_media_item.author = "Creator"
        mock_media_item.duration = 30
        mock_media_item.file_size = 10 * 1024 * 1024
        mock_media_item.cleanup = MagicMock()

        mock_pipeline_inst = MagicMock()
        mock_pipeline_inst.download = AsyncMock(return_value=mock_media_item)

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline_inst):
            update = {
                "update_id": 1001,
                "message": {
                    "chat": {"id": 123456},
                    "text": "https://www.youtube.com/shorts/3dYx1pB9VvE",
                    "message_id": 1,
                }
            }
            await bot._process_update(update)

            # Verification: send_video was called and cleanup() was strictly executed
            bot.send_video.assert_awaited_once()
            mock_media_item.cleanup.assert_called_once()

    async def test_fastpath_process_update_handles_video_too_large(self):
        """Test _process_update notifies user when VideoTooLargeError occurs and cleans up."""
        bot = TelegramBot.__new__(TelegramBot)
        bot.token = "dummy_token"
        bot.chat_id = "123456"
        bot._claim_update = AsyncMock(return_value=True)
        bot._video_debounce = MagicMock()
        bot._video_debounce.handle_user_text = AsyncMock(return_value=False)
        bot._pending_archives = {}
        bot._rate_limiter = MagicMock()
        bot._rate_limiter.acquire = AsyncMock()
        bot.send_message_with_result = AsyncMock(return_value={"message_id": 999})
        bot.send_message = AsyncMock(return_value=True)
        bot.delete_message = AsyncMock(return_value=True)

        mock_pipeline_inst = MagicMock()
        mock_pipeline_inst.download = AsyncMock(
            side_effect=VideoTooLargeError("Video 75.0 MB exceeds 50MB limit")
        )

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline_inst):
            update = {
                "update_id": 1002,
                "message": {
                    "chat": {"id": 123456},
                    "text": "tải video https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "message_id": 2,
                }
            }
            await bot._process_update(update)

            # Verification: user received 50MB warning message
            bot.send_message.assert_awaited_once()
            call_text = bot.send_message.call_args[0][1]
            self.assertIn("50MB", call_text)
            self.assertIn("https://www.youtube.com/watch?v=dQw4w9WgXcQ", call_text)


if __name__ == "__main__":
    unittest.main()
