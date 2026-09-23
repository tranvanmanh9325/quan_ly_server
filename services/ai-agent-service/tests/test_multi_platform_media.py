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

    def test_10a_new_entertainment_and_streaming_platforms_regex(self):
        """Kiểm thử nhận diện URL các nền tảng video giải trí & streaming mới."""
        urls = [
            "https://www.twitch.tv/videos/1234567890",
            "https://clips.twitch.tv/FrailTameGrasshopper",
            "https://twitch.tv/ninja",
            "https://vimeo.com/123456789",
            "https://player.vimeo.com/video/123456789",
            "https://www.dailymotion.com/video/x8abcdef",
            "https://dai.ly/x8abcdef",
            "https://rumble.com/v12345-sample-clip.html",
            "https://streamable.com/abc123xyz",
            "https://www.loom.com/share/1234567890abcdef1234567890abcdef",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match entertainment/streaming URL: {u}")

    def test_10b_new_asian_and_global_social_platforms_regex(self):
        """Kiểm thử nhận diện URL các mạng xã hội châu Á & toàn cầu mới."""
        urls = [
            "https://www.capcut.com/template-detail/123456789",
            "https://capcut.com/watch/12345678",
            "https://www.xiaohongshu.com/explore/64abcdef0000000000000000",
            "https://xhslink.com/a/abcXYZ123",
            "https://weibo.com/1234567890/AbCdEfGhI",
            "https://m.weibo.cn/detail/1234567890123456",
            "https://www.lemon8-app.com/v/123456789",
            "https://likee.video/@creator/video/1234567890123456789",
            "https://l.likee.video/v/abcXYZ",
            "https://bsky.app/profile/alice.bsky.social/post/3kabcde123",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match Asian/global social URL: {u}")


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

    def test_18a_universal_web_extractor_fallback(self):
        """Universal Web Extractor Fallback: URL ngoài danh sách kèm từ khóa tải media rõ ràng."""
        # 1. Có từ khóa tải video -> Kích hoạt fastpath video
        v_intent = self.bot._detect_fastpath_media_download("tải video từ link này https://archive.org/details/sample_video")
        self.assertIsNotNone(v_intent)
        self.assertEqual(v_intent.media_type, "video")
        self.assertEqual(v_intent.media_url, "https://archive.org/details/sample_video")

        # 2. Có từ khóa tải audio -> Kích hoạt fastpath audio
        a_intent = self.bot._detect_fastpath_media_download("tải mp3 podcast https://mypodcast.com/episodes/123.mp3")
        self.assertIsNotNone(a_intent)
        self.assertEqual(a_intent.media_type, "audio")
        self.assertEqual(a_intent.media_url, "https://mypodcast.com/episodes/123.mp3")

        # 3. URL web thông thường không kèm từ khóa tải -> KHÔNG cướp link (trả về None để AI Agent xử lý)
        self.assertIsNone(self.bot._detect_fastpath_media_download("https://github.com/torvalds/linux"))
        self.assertIsNone(self.bot._detect_fastpath_media_download("https://vnexpress.net/thoi-su"))

        # 4. Có URL nhưng chứa từ khóa phủ định -> KHÔNG tải
        self.assertIsNone(self.bot._detect_fastpath_media_download("đừng tải link https://example.com/video"))

    def test_18b_new_platforms_fastpath_audio_and_video_classification(self):
        """Kiểm thử phân loại ý định audio vs video cho 20+ nền tảng mới."""
        audio_cases = [
            ("tải mp3 capcut https://www.capcut.com/template-detail/123456", "audio"),
            ("lấy nhạc xiaohongshu https://xhslink.com/a/abcXYZ123", "audio"),
            ("tách nhạc vimeo https://vimeo.com/123456789", "audio"),
            ("nhạc weibo này hay quá https://weibo.com/1234567890/AbCdEfGhI", "audio"),
            ("audio twitch https://clips.twitch.tv/FrailTameGrasshopper", "audio"),
            ("nhạc lemon8 https://www.lemon8-app.com/v/123456789", "audio"),
            ("tải audio dailymotion https://www.dailymotion.com/video/x8abcdef", "audio"),
        ]
        for text, expected_type in audio_cases:
            intent = self.bot._detect_fastpath_media_download(text)
            self.assertIsNotNone(intent, f"Failed for text: {text}")
            self.assertEqual(intent.media_type, expected_type, f"Expected {expected_type} for: {text}")

        video_cases = [
            ("tải clip capcut https://www.capcut.com/template-detail/123456", "video"),
            ("kéo video twitch 60fps https://www.twitch.tv/videos/1234567890", "video"),
            ("lưu video xiaohongshu https://www.xiaohongshu.com/explore/64abcdef0000000000000000", "video"),
            ("tải video rumble https://rumble.com/v12345-sample-clip.html", "video"),
            ("download video streamable https://streamable.com/abc123xyz", "video"),
            ("tải clip loom https://www.loom.com/share/1234567890abcdef1234567890abcdef", "video"),
            ("lưu clip bluesky https://bsky.app/profile/alice.bsky.social/post/3kabcde123", "video"),
        ]
        for text, expected_type in video_cases:
            intent = self.bot._detect_fastpath_media_download(text)
            self.assertIsNotNone(intent, f"Failed for text: {text}")
            self.assertEqual(intent.media_type, expected_type, f"Expected {expected_type} for: {text}")


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

    def test_22_scoping_activates_for_new_platforms_and_4k60fps_keywords(self):
        """Kiểm thử Dynamic Scoping nhận diện các nền tảng mới và từ khóa chất lượng cao 4K/60fps."""
        queries = [
            ("kéo video capcut https://capcut.com/template-detail/123", "download_media_video"),
            ("tải clip twitch 60fps https://twitch.tv/video/123", "download_media_video"),
            ("lưu video tiểu hồng thư https://xhslink.com/123", "download_media_video"),
            ("tải nhạc weibo https://weibo.com/12345", "download_media_audio"),
            ("tải video vimeo 4k 60fps", "download_media_video"),
            ("tải clip dailymotion https://dai.ly/x123", "download_media_video"),
            ("lưu video rumble https://rumble.com/v123", "download_media_video"),
            ("kéo video streamable https://streamable.com/abc", "download_media_video"),
            ("tải video loom https://loom.com/share/abc", "download_media_video"),
            ("lưu clip lemon8 https://lemon8-app.com/v/123", "download_media_video"),
            ("tải video likee https://likee.video/@user/video/123", "download_media_video"),
            ("tải post bluesky https://bsky.app/profile/user/post/123", "download_media_video"),
        ]
        for query, expected_tool in queries:
            scoped = self.mgr._resolve_scoped_tool_names(query)
            self.assertIn(
                expected_tool,
                scoped,
                f"Scoped tools {scoped} did not include expected {expected_tool} for query: {query}",
            )


class TestMediaStoragePort8084AndDualDistributionGroup(unittest.TestCase):
    """Nhóm 5: Kiểm thử chuẩn hóa cổng LAN port 8084 và cơ chế Dual Distribution."""

    def test_23_lan_base_url_standardized_to_port_8084(self):
        """Xác nhận giá trị mặc định của LAN Base URL được chuẩn hóa sang port 8084 của FastAPI backend."""
        from app.services.media_storage_manager import media_storage_manager
        import app.services.media_storage_manager as msm_mod

        # Reset cache
        msm_mod._cached_internet_url = None
        msm_mod._cached_url_timestamp = 0.0

        import urllib.error
        with patch.dict(os.environ, {}, clear=True), \
             patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")), \
             patch.object(media_storage_manager, "_query_host_ngrok_via_ssh", return_value=None):

            internet, lan = media_storage_manager.resolve_public_download_base_url_sync()
            # Kiểm tra giá trị chuỗi thực tế trỏ tới port 8084
            self.assertIn("8084", str(lan))
            self.assertEqual(lan, "http://192.168.0.100:8084")
            self.assertEqual(internet, "http://192.168.0.100:8084")

    def test_24_download_record_lan_url_contains_port_8084(self):
        """Xác nhận publish_download_item tạo URL nội bộ với port 8084 chuẩn hóa."""
        import tempfile
        import shutil
        from pathlib import Path
        from app.services.media_storage_manager import MediaStorageManager
        import app.services.media_storage_manager as msm_mod

        tdir = Path(tempfile.mkdtemp(prefix="test_pub_8084_"))
        try:
            mgr = MediaStorageManager(
                base_dir=tdir,
                temp_dir=tdir / "temp",
                public_dir=tdir / "public",
            )
            # Reset cache
            msm_mod._cached_internet_url = None
            msm_mod._cached_url_timestamp = 0.0

            src = tdir / "temp" / "test_vid.mp4"
            src.write_bytes(b"TEST_BYTES_FOR_8084" * 100)

            with patch.dict(os.environ, {}, clear=True), \
                 patch("urllib.request.urlopen", side_effect=Exception("offline")), \
                 patch.object(mgr, "_query_host_ngrok_via_ssh", return_value=None):

                rec = mgr.publish_download_item(src, "test_vid.mp4", "Title 8084")
                self.assertIn("8084", rec.lan_url)
                self.assertTrue(rec.lan_url.startswith("http://192.168.0.100:8084/api/ai/media/download/"))
        finally:
            shutil.rmtree(tdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

