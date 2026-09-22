"""
test_multi_platform_media.py — Comprehensive Unit & Integration Tests for Multi-Platform Media & Audio Pipeline.

Validates universal media extraction across 11+ major social platforms:
  - YouTube (Watch, Shorts, Live, Music, youtu.be)
  - Facebook (Reels, Watch, Share, fb.watch, fb.me)
  - Instagram (Reels, Posts, TV, Share, Stories, instagr.am)
  - Twitter / X (x.com, twitter.com, t.co)
  - Threads (threads.net, threads.com)
  - SoundCloud (soundcloud.com, on.soundcloud.com, m.soundcloud.com)
  - Reddit (reddit.com/r/..., redd.it, v.redd.it)
  - Bilibili (bilibili.com/video, b23.tv)
  - Pinterest (pinterest.com/pin, pin.it)
  - Kuaishou (kuaishou.com, v.kuaishou.com, gifshow.com)
  - TikTok & Douyin (tiktok.com, douyin.com, iesdouyin.com)
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.media_downloader import (
    MultiTierMediaPipeline,
    MediaItem,
    TEMP_MEDIA_DIR,
)
from app.services.telegram_bot import TelegramBot, FastPathMediaIntent
from app.services.ai_agent_tools import AgentToolExecutor


class TestMultiPlatformRegexGroup(unittest.TestCase):
    """Nhóm 1: Kiểm thử regex nhận diện URL trên toàn bộ 11+ nền tảng mạng xã hội."""

    def setUp(self):
        self.regex = TelegramBot._MEDIA_URL_REGEX

    def test_01_youtube_url_variants(self):
        urls = [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://www.youtube.com/shorts/3iCg2c19jGg",
            "https://music.youtube.com/watch?v=kffacxfA7G4",
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtube.com/live/5qap5aO4i9A",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match YouTube URL: {u}")

    def test_02_facebook_url_variants(self):
        urls = [
            "https://www.facebook.com/reel/1234567890",
            "https://fb.watch/xyzABC123/",
            "https://www.facebook.com/watch/?v=9876543210",
            "https://www.facebook.com/share/r/AbCdEf123/",
            "https://www.facebook.com/share/v/XyZ123456/",
            "https://fb.me/shortlink123",
            "https://m.facebook.com/watch?v=123",
            "https://www.facebook.com/user/videos/123456789",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match Facebook URL: {u}")

    def test_03_instagram_url_variants(self):
        urls = [
            "https://www.instagram.com/reel/C123456789/",
            "https://www.instagram.com/reels/C123456789/",
            "https://www.instagram.com/p/B123456789/",
            "https://www.instagram.com/tv/A123456789/",
            "https://www.instagram.com/share/reel/ABC123xyz/",
            "https://www.instagram.com/stories/username/1234567890/",
            "https://instagr.am/p/ABCxyz123/",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match Instagram URL: {u}")

    def test_04_twitter_and_x_url_variants(self):
        urls = [
            "https://twitter.com/OpenAI/status/1234567890123456789",
            "https://x.com/elonmusk/status/9876543210987654321",
            "https://t.co/abcXYZ1234",
            "https://mobile.twitter.com/user/status/11223344",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match Twitter/X URL: {u}")

    def test_05_threads_url_variants(self):
        urls = [
            "https://www.threads.net/@zuck/post/C1234567890",
            "https://threads.net/t/C1234567890",
            "https://threads.com/@user/post/ABC123xyz",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match Threads URL: {u}")

    def test_06_soundcloud_url_variants(self):
        urls = [
            "https://soundcloud.com/artist-name/track-name-2026",
            "https://on.soundcloud.com/abcXYZ123",
            "https://m.soundcloud.com/artist/title",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match SoundCloud URL: {u}")

    def test_07_reddit_url_variants(self):
        urls = [
            "https://www.reddit.com/r/funny/comments/1d82xev/kitten_playing_with_a_puppy/",
            "https://redd.it/1d82xev",
            "https://v.redd.it/12345abcdefg",
            "https://reddit.com/r/aww/comments/abc123/cute_cat",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match Reddit URL: {u}")

    def test_08_bilibili_url_variants(self):
        urls = [
            "https://www.bilibili.com/video/BV1xx411c7mD",
            "https://b23.tv/abcXYZ1",
            "https://m.bilibili.com/video/BV1xx411c7mD",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match Bilibili URL: {u}")

    def test_09_pinterest_and_kuaishou_url_variants(self):
        urls = [
            "https://www.pinterest.com/pin/123456789012345678/",
            "https://pin.it/abcXYZ1",
            "https://www.kuaishou.com/short-video/1234567",
            "https://v.kuaishou.com/abcXYZ1",
            "https://gifshow.com/s/abcXYZ1",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match Pinterest/Kuaishou URL: {u}")

    def test_10_tiktok_and_douyin_url_variants(self):
        urls = [
            "https://www.tiktok.com/@creator/video/1234567890123456789",
            "https://vt.tiktok.com/ZS1234567/",
            "https://vm.tiktok.com/ZM1234567/",
            "https://www.douyin.com/video/1234567890123456789",
            "https://v.douyin.com/abcXYZ1/",
            "https://www.iesdouyin.com/share/video/123456789/",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match TikTok/Douyin URL: {u}")


class TestFastPathIntentRoutingGroup(unittest.TestCase):
    """Nhóm 2: Kiểm thử bộ định tuyến Fast-path ý định tải Media & Audio."""

    def setUp(self):
        self.bot = TelegramBot.__new__(TelegramBot)

    def test_11_raw_video_url_defaults_to_video(self):
        intent = self.bot._detect_fastpath_media_download("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.media_type, "video")
        self.assertEqual(intent.media_url, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    def test_12_raw_soundcloud_url_defaults_to_audio(self):
        """SoundCloud là nền tảng thuần âm nhạc -> Mặc định tải Audio ngay cả khi gửi link trần."""
        intent = self.bot._detect_fastpath_media_download("https://soundcloud.com/artist/song-title")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.media_type, "audio")
        self.assertEqual(intent.media_url, "https://soundcloud.com/artist/song-title")

    def test_13_raw_youtube_music_url_defaults_to_audio(self):
        """music.youtube.com là nền tảng chuyên audio -> Mặc định tải Audio."""
        intent = self.bot._detect_fastpath_media_download("https://music.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.media_type, "audio")

    def test_14_explicit_audio_request_across_platforms(self):
        cases = [
            ("tải mp3 bài này giúp em https://www.youtube.com/watch?v=dQw4w9WgXcQ", "audio"),
            ("https://www.facebook.com/reel/123456 lấy nhạc reels này", "audio"),
            ("https://www.instagram.com/reel/C123/ tách âm thanh nhé", "audio"),
            ("xin audio bài này https://x.com/user/status/123", "audio"),
            ("chuyển sang mp3 https://www.reddit.com/r/music/comments/123/song", "audio"),
            ("nhạc soundcloud này hay quá https://soundcloud.com/artist/song", "audio"),
        ]
        for text, expected_type in cases:
            intent = self.bot._detect_fastpath_media_download(text)
            self.assertIsNotNone(intent, f"Failed to detect intent for: {text}")
            self.assertEqual(intent.media_type, expected_type)

    def test_15_explicit_video_request_across_platforms(self):
        cases = [
            ("tải video này https://www.youtube.com/watch?v=dQw4w9WgXcQ", "video"),
            ("kéo clip https://www.facebook.com/watch/?v=123456 về máy", "video"),
            ("lưu video instagram https://www.instagram.com/reel/C123/ giùm anh", "video"),
            ("tải về máy https://v.redd.it/12345abc", "video"),
            ("download video https://www.bilibili.com/video/BV1xx411c7mD", "video"),
        ]
        for text, expected_type in cases:
            intent = self.bot._detect_fastpath_media_download(text)
            self.assertIsNotNone(intent, f"Failed to detect intent for: {text}")
            self.assertEqual(intent.media_type, expected_type)

    def test_16_negative_keywords_bypass_fastpath(self):
        negative_messages = [
            "đừng tải video https://www.youtube.com/watch?v=123",
            "không tải nhạc link này https://soundcloud.com/artist/track nhé",
            "chưa tải đâu https://www.instagram.com/reel/C123/ chỉ hỏi thôi",
            "ko cần tải https://fb.watch/xyz",
        ]
        for msg in negative_messages:
            intent = self.bot._detect_fastpath_media_download(msg)
            self.assertIsNone(intent, f"Should NOT intercept negative message: {msg}")

    def test_17_analysis_questions_bypass_fastpath(self):
        questions = [
            "https://www.youtube.com/watch?v=123 video này nói về gì vậy em?",
            "tóm tắt nội dung video https://www.facebook.com/reel/123 giúp anh",
            "tại sao không tải được link https://x.com/status/123",
            "hát bài gì vậy https://soundcloud.com/artist/track",
        ]
        for q in questions:
            intent = self.bot._detect_fastpath_media_download(q)
            self.assertIsNone(intent, f"Should NOT intercept analytical question: {q}")

    def test_18_trailing_punctuation_stripping(self):
        test_inputs = [
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ.", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            ("[https://soundcloud.com/artist/song]", "https://soundcloud.com/artist/song"),
            ("Tải giúp link https://fb.watch/xyzABC! nha", "https://fb.watch/xyzABC"),
            ("Tải link này: \"https://www.instagram.com/reel/C123/\">", "https://www.instagram.com/reel/C123/"),
        ]
        for raw, expected_url in test_inputs:
            intent = self.bot._detect_fastpath_media_download(raw)
            self.assertIsNotNone(intent, f"Failed for input: {raw}")
            self.assertEqual(intent.media_url, expected_url)


class TestMediaDownloaderRoutingGroup(unittest.IsolatedAsyncioTestCase):
    """Nhóm 3: Kiểm thử định tuyến MultiTierMediaPipeline cho các nền tảng âm nhạc và video."""

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()

    async def test_19_soundcloud_in_download_routes_to_download_audio(self):
        """Khi gọi download(soundcloud_url) -> Phải tự động điều hướng sang download_audio."""
        fake_item = MediaItem(
            file_path="/tmp/test.mp3",
            title="SoundCloud Hit",
            author="SoundCloud Artist",
            duration=180,
            media_type="audio",
            source_url="https://soundcloud.com/artist/song",
            file_size=5 * 1024 * 1024,
        )
        with patch.object(self.pipeline, "download_audio", new_callable=AsyncMock) as mock_download_audio:
            mock_download_audio.return_value = fake_item
            result = await self.pipeline.download("https://soundcloud.com/artist/song")
            mock_download_audio.assert_awaited_once_with("https://soundcloud.com/artist/song")
            self.assertEqual(result.media_type, "audio")
            self.assertEqual(result.title, "SoundCloud Hit")

    async def test_20_youtube_music_in_download_routes_to_download_audio(self):
        """Khi gọi download(music.youtube.com) -> Phải tự động điều hướng sang download_audio."""
        fake_item = MediaItem(
            file_path="/tmp/music.mp3",
            title="YT Music Song",
            author="YT Artist",
            duration=210,
            media_type="audio",
            source_url="https://music.youtube.com/watch?v=123",
            file_size=6 * 1024 * 1024,
        )
        with patch.object(self.pipeline, "download_audio", new_callable=AsyncMock) as mock_download_audio:
            mock_download_audio.return_value = fake_item
            result = await self.pipeline.download("https://music.youtube.com/watch?v=123")
            mock_download_audio.assert_awaited_once_with("https://music.youtube.com/watch?v=123")
            self.assertEqual(result.media_type, "audio")


class TestDynamicScopingAndToolSchemasGroup(unittest.TestCase):
    """Nhóm 4: Kiểm thử dynamic scoping và schema công cụ của AI Agent Tools."""

    def setUp(self):
        self.mgr = AgentToolExecutor.__new__(AgentToolExecutor)

    def test_21_scoping_activates_media_cluster_for_social_keywords(self):
        queries = [
            ("tải video youtube này https://youtu.be/123", "download_media_video"),
            ("tải nhạc soundcloud https://soundcloud.com/abc", "download_media_audio"),
            ("lưu reel instagram https://instagram.com/reel/123", "download_media_video"),
            ("tách nhạc từ video reddit https://reddit.com/r/funny/123", "download_media_audio"),
            ("tải video x twitter https://x.com/status/123", "download_media_video"),
            ("kéo clip bilibili https://bilibili.com/video/BV123", "download_media_video"),
        ]
        for query, expected_tool in queries:
            scoped = self.mgr._resolve_scoped_tool_names(query)
            self.assertIn(
                expected_tool,
                scoped,
                f"Scoped tools {scoped} did not include expected {expected_tool} for query: {query}",
            )


if __name__ == "__main__":
    unittest.main()
