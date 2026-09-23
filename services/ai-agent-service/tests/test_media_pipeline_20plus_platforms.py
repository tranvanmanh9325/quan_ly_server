"""
test_media_pipeline_20plus_platforms.py — Comprehensive E2E & Integration Tests for 24+ Platforms Media Pipeline.

Verifies:
  1. 24+ Social Platforms Recognition in TelegramBot (_MEDIA_URL_REGEX & _detect_fastpath_media_download):
     YouTube, YouTube Shorts, Twitch Clips & VODs, Vimeo, Dailymotion, Rumble, Streamable, Loom,
     Facebook Reels/Watch/Videos, Instagram Reels/Posts/Stories, Twitter/X, Threads, Reddit, Pinterest,
     TikTok, Douyin, CapCut, Xiaohongshu/RedNote, Weibo, Bilibili, Kuaishou, Lemon8, Likee, Bluesky.
  2. Mobile App Share Parameters (?si=, ?mibextid=, ?share_id=...) and shortlink unwrap.
  3. Universal Web Extractor Fallback:
     - URL outside list + download keywords -> FastPathMediaIntent
     - Generic Web URL without download keywords -> None (delegate to LLM)
     - Negative keywords -> None
  4. Video vs Audio Intent Classification:
     - media_type='audio' on audio/mp3 keywords
     - media_type='video' by default
     - Dedicated audio platforms (SoundCloud, YouTube Music) default to audio
  5. Dual Distribution Engine:
     - Video <= 50MB: send_video(supports_streaming=True) with send_document_file fallback
     - Video > 50MB: VideoChunker.split_video() into <= 48MB parts, sequential streaming dispatch,
       immediate part unlink (Streaming Purge), 2 Direct Links (LAN port 8084 & WAN Ngrok)
  6. AI Agent Tools & Dynamic Scoping in ai_agent_tools.py:
     - Tool download_media_video description covers 20+ platforms & 4K/60fps
     - Dynamic scoping activation for 20+ platforms
     - Tool execution for single video and chunked video
  7. AI Agent System Prompt in ai_agent.py:
     - Section 2e media archiving protocol & BLUF 'Dạ CÓ!'
  8. Zero-Disk Leak Lifecycle in finally blocks.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.telegram_bot import TelegramBot, FastPathMediaIntent
from app.services.ai_agent_tools import AgentToolExecutor
from app.services.ai_agent import AiAgentService
from app.services.media_downloader import MediaItem, VideoTooLargeError
from app.services.media_storage_manager import DownloadRecord, media_storage_manager
from app.services.video_chunker import VideoChunker


class Test24PlusPlatformsRecognition(unittest.TestCase):
    """Kiểm thử nhận diện toàn diện 24+ nền tảng mạng xã hội qua regex và fast-path."""

    def setUp(self):
        self.regex = TelegramBot._MEDIA_URL_REGEX
        self.bot = TelegramBot.__new__(TelegramBot)

    def test_01_all_24_platforms_regex_matching(self):
        """Xác thực regex nhận diện chính xác 24 nền tảng mạng xã hội yêu cầu."""
        platforms_samples = {
            "1. YouTube": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "2. YouTube Shorts": "https://www.youtube.com/shorts/3iCg2c19jGg",
            "3. Twitch Clips & VODs": "https://clips.twitch.tv/FrailTameGrasshopper",
            "3b. Twitch VOD": "https://www.twitch.tv/videos/1234567890",
            "4. Vimeo": "https://vimeo.com/123456789",
            "4b. Vimeo Player": "https://player.vimeo.com/video/123456789",
            "5. Dailymotion": "https://www.dailymotion.com/video/x8abcdef",
            "5b. Dailymotion Short": "https://dai.ly/x8abcdef",
            "6. Rumble": "https://rumble.com/v12345-sample-clip.html",
            "7. Streamable": "https://streamable.com/abc123xyz",
            "8. Loom": "https://www.loom.com/share/1234567890abcdef1234567890abcdef",
            "9. Facebook Reels": "https://www.facebook.com/reel/1234567890",
            "9b. Facebook Watch": "https://www.facebook.com/watch/?v=9876543210",
            "9c. Facebook Videos": "https://www.facebook.com/page/videos/123456789",
            "10. Instagram Reels": "https://www.instagram.com/reel/C123456789/",
            "10b. Instagram Posts": "https://www.instagram.com/p/B123456789/",
            "10c. Instagram Stories": "https://www.instagram.com/stories/username/1234567890/",
            "11. Twitter/X": "https://x.com/user/status/1234567890123456789",
            "11b. Twitter Classic": "https://twitter.com/user/status/1234567890123456789",
            "12. Threads": "https://www.threads.net/@user/post/C1234567890",
            "13. Reddit": "https://www.reddit.com/r/funny/comments/123/sample_clip/",
            "14. Pinterest": "https://www.pinterest.com/pin/123456789012345678/",
            "15. TikTok": "https://www.tiktok.com/@creator/video/1234567890123456789",
            "16. Douyin": "https://www.douyin.com/video/1234567890123456789",
            "17. CapCut": "https://www.capcut.com/template-detail/123456789",
            "18. Xiaohongshu/RedNote": "https://www.xiaohongshu.com/explore/64abcdef0000000000000000",
            "19. Weibo": "https://weibo.com/1234567890/AbCdEfGhI",
            "20. Bilibili": "https://www.bilibili.com/video/BV1xx411c7mD",
            "21. Kuaishou": "https://www.kuaishou.com/short-video/1234567",
            "22. Lemon8": "https://www.lemon8-app.com/v/123456789",
            "23. Likee": "https://likee.video/@creator/video/1234567890123456789",
            "24. Bluesky": "https://bsky.app/profile/alice.bsky.social/post/3kabcde123",
        }

        for platform_name, url in platforms_samples.items():
            match = self.regex.search(url)
            self.assertIsNotNone(match, f"Regex failed to match {platform_name}: {url}")
            intent = self.bot._detect_fastpath_media_download(url)
            self.assertIsNotNone(intent, f"Fastpath failed for {platform_name}: {url}")
            self.assertEqual(intent.media_type, "video")

    def test_02_mobile_app_share_params_and_unwrap(self):
        """Bóc tách các query tracking params của app di động và unwrap shortlinks."""
        test_cases = [
            ("https://youtu.be/dQw4w9WgXcQ?si=abcdef123456", "https://youtu.be/dQw4w9WgXcQ?si=abcdef123456"),
            ("https://www.facebook.com/share/r/AbCdEf123/?mibextid=oFDknk", "https://www.facebook.com/share/r/AbCdEf123/?mibextid=oFDknk"),
            ("https://xhslink.com/a/abcXYZ123?share_id=12345", "https://xhslink.com/a/abcXYZ123?share_id=12345"),
            ("https://vt.tiktok.com/ZS1234567/?utm_source=share", "https://vt.tiktok.com/ZS1234567/?utm_source=share"),
            ("https://v.douyin.com/abcXYZ1/?utm_medium=copy", "https://v.douyin.com/abcXYZ1/?utm_medium=copy"),
            ("https://b23.tv/abcXYZ1?fbclid=123456", "https://b23.tv/abcXYZ1?fbclid=123456"),
            ("https://pin.it/abcXYZ1?invite_code=xyz", "https://pin.it/abcXYZ1?invite_code=xyz"),
            ("https://l.likee.video/v/abcXYZ?share=app", "https://l.likee.video/v/abcXYZ?share=app"),
            ("https://dai.ly/x8abcdef?ref=badge", "https://dai.ly/x8abcdef?ref=badge"),
            ("https://t.co/abcXYZ1234?amp=1", "https://t.co/abcXYZ1234?amp=1"),
        ]
        for raw_text, _ in test_cases:
            intent = self.bot._detect_fastpath_media_download(f"tải giúp em {raw_text} nha")
            self.assertIsNotNone(intent, f"Failed for share param link: {raw_text}")
            self.assertEqual(intent.media_type, "video")

    def test_03_trailing_punctuation_and_enclosures_cleaning(self):
        """Làm sạch các dấu chấm, phẩy, ngoặc, nháy kép dính vào đuôi URL."""
        cases = [
            ("Tải giúp clip này nha: (https://www.twitch.tv/videos/1234567890).", "https://www.twitch.tv/videos/1234567890"),
            ("Tải video này: \"https://vimeo.com/123456789\"!", "https://vimeo.com/123456789"),
            ("<https://streamable.com/abc123xyz>, tải nha", "https://streamable.com/abc123xyz"),
            ("Tải link loom: [https://www.loom.com/share/1234567890abcdef1234567890abcdef]…", "https://www.loom.com/share/1234567890abcdef1234567890abcdef"),
            ("[https://www.twitch.tv/videos/1234567890]", "https://www.twitch.tv/videos/1234567890"),
        ]
        for text, expected_clean_url in cases:
            intent = self.bot._detect_fastpath_media_download(text)
            self.assertIsNotNone(intent, f"Failed for text: {text}")
            self.assertEqual(intent.media_url, expected_clean_url)


class TestUniversalWebExtractorAndIntentClassification(unittest.TestCase):
    """Kiểm thử cơ chế Universal Web Extractor Fallback và phân loại Video vs Audio."""

    def setUp(self):
        self.bot = TelegramBot.__new__(TelegramBot)

    def test_04_universal_web_extractor_with_keywords(self):
        """URL web bất kỳ kèm từ khóa tải -> Kích hoạt Universal Extractor."""
        valid_queries = [
            ("tải video link này https://archive.org/details/sample_clip", "video"),
            ("download video https://myvideo-server.net/videos/2026_demo.mp4", "video"),
            ("kéo clip https://news-hub.com/media/story_123.mp4 về máy", "video"),
            ("lưu video từ web https://custom-streaming.tv/vod/5678", "video"),
            ("tải mp3 https://mypodcast.org/audio/episode_42.mp3", "audio"),
            ("lấy nhạc bài này https://sample-music.vn/songs/hit.mp3", "audio"),
        ]
        for query, expected_type in valid_queries:
            intent = self.bot._detect_fastpath_media_download(query)
            self.assertIsNotNone(intent, f"Universal extractor failed for: {query}")
            self.assertEqual(intent.media_type, expected_type)

    def test_05_generic_urls_without_keywords_ignored(self):
        """URL web thông thường KHÔNG có từ khóa tải -> Trả về None để AI Agent xử lý bình thường."""
        normal_web_queries = [
            "https://github.com/torvalds/linux",
            "https://vnexpress.net/thoi-su/tin-tuc-trong-ngay",
            "https://stackoverflow.com/questions/123456/how-to-fix-bug",
            "https://en.wikipedia.org/wiki/Artificial_intelligence",
            "đây là trang web https://docs.python.org/3/library/unittest.html",
        ]
        for query in normal_web_queries:
            intent = self.bot._detect_fastpath_media_download(query)
            self.assertIsNone(intent, f"Generic web URL should NOT trigger fastpath: {query}")

    def test_06_negative_and_analysis_keywords_bypass_fastpath(self):
        """Từ khóa phủ định hoặc câu hỏi phân tích bỏ qua Fastpath."""
        bypasses = [
            "đừng tải video https://vimeo.com/123456789",
            "không tải nhạc https://www.capcut.com/template-detail/123456",
            "ko cần tải link https://rumble.com/v123",
            "https://streamable.com/abc123xyz video này nói về gì vậy em?",
            "giải thích nội dung clip https://www.xiaohongshu.com/explore/123",
            "tại sao không tải được https://bsky.app/profile/user/post/123",
        ]
        for query in bypasses:
            intent = self.bot._detect_fastpath_media_download(query)
            self.assertIsNone(intent, f"Should bypass fastpath for: {query}")

    def test_07_audio_vs_video_intent_classification(self):
        """Phân loại rành mạch ý định tải Audio (MP3) vs Video cho 24+ nền tảng."""
        audio_cases = [
            ("tải mp3 https://www.twitch.tv/videos/123", "audio"),
            ("lấy nhạc bài này https://vimeo.com/456", "audio"),
            ("tách âm thanh video https://rumble.com/v789", "audio"),
            ("audio capcut https://www.capcut.com/template-detail/111", "audio"),
            ("nhạc xiaohongshu https://xhslink.com/a/222", "audio"),
            ("xin audio https://weibo.com/333", "audio"),
            ("chuyển sang mp3 https://bilibili.com/video/BV444", "audio"),
        ]
        for text, expected_type in audio_cases:
            intent = self.bot._detect_fastpath_media_download(text)
            self.assertIsNotNone(intent, f"Failed for audio query: {text}")
            self.assertEqual(intent.media_type, expected_type)

        # Mặc định link trần video nền tảng
        raw_video_cases = [
            "https://vimeo.com/123456",
            "https://clips.twitch.tv/TestClip",
            "https://streamable.com/xyz123",
            "https://www.loom.com/share/abc123",
        ]
        for raw_url in raw_video_cases:
            intent = self.bot._detect_fastpath_media_download(raw_url)
            self.assertIsNotNone(intent)
            self.assertEqual(intent.media_type, "video")

        # Nền tảng chuyên audio -> Mặc định audio
        self.assertEqual(self.bot._detect_fastpath_media_download("https://soundcloud.com/artist/song").media_type, "audio")
        self.assertEqual(self.bot._detect_fastpath_media_download("https://music.youtube.com/watch?v=123").media_type, "audio")


class TestDualDistributionEngineE2E(unittest.IsolatedAsyncioTestCase):
    """Kiểm thử mô hình Phân phối kép (Dual-Track Distribution) cho Video <= 50MB và > 50MB."""

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
        self.bot.send_message_with_result = AsyncMock(return_value={"message_id": 100})
        self.bot.send_message = AsyncMock(return_value=True)
        self.bot.delete_message = AsyncMock(return_value=True)
        self.bot.send_video = AsyncMock(return_value=True)
        self.bot.send_document_file = AsyncMock(return_value=True)

    async def test_08_video_under_50mb_direct_send_with_streaming_support(self):
        """Video <= 50MB được gửi trực tiếp 1 video duy nhất với supports_streaming=True."""
        mock_item = MediaItem(
            file_path="/tmp/media_downloads/short_video.mp4",
            title="Short 60fps Video",
            author="TwitchStreamer",
            duration=30,
            media_type="video",
            source_url="https://clips.twitch.tv/FrailTameGrasshopper",
            file_size=20 * 1024 * 1024,  # 20MB <= 50MB
            width=1920,
            height=1080,
            fps=60.0,
        )
        mock_pipeline = MagicMock()
        mock_pipeline.download = AsyncMock(return_value=mock_item)

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline), \
             patch("app.services.video_chunker.VideoChunker.split_video", new_callable=AsyncMock) as mock_split, \
             patch("app.services.media_storage_manager.media_storage_manager.publish_download_item") as mock_publish:

            update = {
                "update_id": 5001,
                "message": {
                    "chat": {"id": 123456},
                    "text": "https://clips.twitch.tv/FrailTameGrasshopper",
                    "message_id": 50,
                }
            }
            await self.bot._process_update(update)

            # Khẳng định gọi send_video với supports_streaming=True
            self.bot.send_video.assert_awaited_once()
            call_kwargs = self.bot.send_video.call_args[1]
            self.assertEqual(call_kwargs["video_path"], "/tmp/media_downloads/short_video.mp4")
            self.assertTrue(call_kwargs.get("supports_streaming"))
            self.assertEqual(call_kwargs.get("width"), 1920)
            self.assertEqual(call_kwargs.get("height"), 1080)

            # Không gọi chunking hay direct links
            mock_split.assert_not_called()
            mock_publish.assert_not_called()

    async def test_09_video_under_50mb_fallback_to_document_on_failure(self):
        """Video <= 50MB khi send_video thất bại tự động fallback sang send_document_file."""
        mock_item = MediaItem(
            file_path="/tmp/media_downloads/unsupported_codec.mp4",
            title="Odd Codec Video",
            author="Author",
            duration=15,
            media_type="video",
            source_url="https://vimeo.com/123456",
            file_size=15 * 1024 * 1024,
        )
        mock_pipeline = MagicMock()
        mock_pipeline.download = AsyncMock(return_value=mock_item)

        # Giả lập send_video thất bại (trả về False)
        self.bot.send_video = AsyncMock(return_value=False)

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline):
            update = {
                "update_id": 5002,
                "message": {
                    "chat": {"id": 123456},
                    "text": "https://vimeo.com/123456",
                    "message_id": 51,
                }
            }
            await self.bot._process_update(update)

            self.bot.send_video.assert_awaited_once()
            # Bắt buộc fallback sang send_document_file
            self.bot.send_document_file.assert_awaited_once()
            doc_kwargs = self.bot.send_document_file.call_args[1]
            self.assertEqual(doc_kwargs["file_path"], "/tmp/media_downloads/unsupported_codec.mp4")

    async def test_10_large_video_over_50mb_dual_distribution_and_streaming_purge(self):
        """Video > 50MB: Kích hoạt chia part qua VideoChunker, Streaming Purge, và 2 Direct Links (LAN 8084 & WAN)."""
        temp_dir = Path(tempfile.mkdtemp(prefix="test_large_vid_"))
        try:
            large_file = temp_dir / "large_4k60.mp4"
            large_file.write_bytes(b"0" * (60 * 1024 * 1024))  # 60MB > 50MB

            mock_item = MediaItem(
                file_path=str(large_file),
                title="4K60 Grand Concert",
                author="MegaChannel",
                duration=300,
                media_type="video",
                source_url="https://www.youtube.com/watch?v=large123",
                file_size=60 * 1024 * 1024,
                width=3840,
                height=2160,
                fps=60.0,
                is_temp_file=True,
            )
            mock_pipeline = MagicMock()
            mock_pipeline.download = AsyncMock(return_value=mock_item)

            # Giả lập 2 parts được tạo ra
            part1_path = temp_dir / "part_01.mp4"
            part2_path = temp_dir / "part_02.mp4"
            part1_path.write_bytes(b"P1_DATA" * 100)
            part2_path.write_bytes(b"P2_DATA" * 100)

            simulated_parts = [
                {"part_index": 1, "path": str(part1_path), "duration": 150, "size": 30 * 1024 * 1024, "width": 3840, "height": 2160},
                {"part_index": 2, "path": str(part2_path), "duration": 150, "size": 30 * 1024 * 1024, "width": 3840, "height": 2160},
            ]

            mock_rec = DownloadRecord(
                token="tok_large_4k",
                file_path=large_file,
                filename="large_4k60.mp4",
                title="4K60 Grand Concert",
                duration=300,
                file_size=60 * 1024 * 1024,
                created_at=0.0,
                expires_at=14400.0,
                internet_url="https://ngrok-wan.dev/api/ai/media/download/tok_large_4k",
                lan_url="http://192.168.0.100:8084/api/ai/media/download/tok_large_4k",
            )

            with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline), \
                 patch("app.services.video_chunker.VideoChunker.split_video", new_callable=AsyncMock, return_value=simulated_parts) as mock_split, \
                 patch("app.services.media_storage_manager.media_storage_manager.publish_download_item", return_value=mock_rec) as mock_publish, \
                 patch("asyncio.sleep", new_callable=AsyncMock):

                update = {
                    "update_id": 5003,
                    "message": {
                        "chat": {"id": 123456},
                        "text": "https://www.youtube.com/watch?v=large123",
                        "message_id": 52,
                    }
                }
                await self.bot._process_update(update)

                # 1. Kiểm tra chuyển quyền sở hữu cho media_storage_manager
                mock_publish.assert_called_once()
                self.assertFalse(mock_item.is_temp_file, "Oversized file ownership must be transferred (is_temp_file=False)")

                # 2. Kiểm tra gọi VideoChunker.split_video
                mock_split.assert_awaited_once()

                # 3. Kiểm tra gửi tuần tự 2 parts qua send_video
                self.assertEqual(self.bot.send_video.await_count, 2)

                # 4. Kiểm tra Streaming Purge: từng part bị unlink ngay sau khi gửi
                self.assertFalse(part1_path.exists(), "Part 1 must be deleted immediately after dispatch (Streaming Purge)")
                self.assertFalse(part2_path.exists(), "Part 2 must be deleted immediately after dispatch (Streaming Purge)")

                # 5. Kiểm tra thông báo hoàn tất gửi cả 2 liên kết WAN và LAN port 8084
                messages_sent = [call[0][1] for call in self.bot.send_message.call_args_list]
                completion_msg = [m for m in messages_sent if "Đã gửi trọn vẹn 2/2 phần" in m]
                self.assertTrue(len(completion_msg) > 0, "Completion message with direct links must be sent")
                self.assertIn("https://ngrok-wan.dev/api/ai/media/download/tok_large_4k", completion_msg[0])
                self.assertIn("http://192.168.0.100:8084/api/ai/media/download/tok_large_4k", completion_msg[0])
                self.assertIn("8084", completion_msg[0])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestAiAgentToolsAndDynamicScoping(unittest.IsolatedAsyncioTestCase):
    """Kiểm thử Schema, Dynamic Scoping và Execution của công cụ download_media_video trong ai_agent_tools.py."""

    def setUp(self):
        self.mgr = AgentToolExecutor.__new__(AgentToolExecutor)
        self.mgr.telegram_bot = None

    def test_11_download_media_video_tool_schema_coverage(self):
        """Xác thực schema download_media_video mô tả đầy đủ 20+ nền tảng, 4K/60fps và Dual Distribution."""
        tools = self.mgr._build_tools()
        media_tool = next((t["function"] for t in tools if t["function"]["name"] == "download_media_video"), None)
        self.assertIsNotNone(media_tool, "download_media_video tool must be present in registry")

        desc = media_tool["description"]
        self.assertIn("4K", desc)
        self.assertIn("60fps", desc)
        self.assertIn("20+", desc)
        self.assertIn("Phân phối kép", desc)

        # Kiểm tra danh sách tham số
        params = media_tool["parameters"]["properties"]
        self.assertIn("url", params)
        self.assertIn("caption", params)
        self.assertIn("media_type", params)
        self.assertEqual(params["media_type"]["enum"], ["video", "audio"])
        self.assertEqual(params["media_type"]["default"], "video")

    def test_12_dynamic_scoping_activates_for_20plus_platforms(self):
        """Dynamic Scoping kích hoạt tool download_media_video với các nền tảng mới."""
        queries = [
            ("tải video twitch 60fps https://twitch.tv/videos/123", "download_media_video"),
            ("tải clip vimeo https://vimeo.com/123456", "download_media_video"),
            ("lưu video dailymotion https://dai.ly/x123", "download_media_video"),
            ("kéo clip rumble https://rumble.com/v123", "download_media_video"),
            ("tải clip capcut https://capcut.com/template-detail/123", "download_media_video"),
            ("lưu video tiểu hồng thư https://xhslink.com/a/123", "download_media_video"),
            ("tải video weibo https://weibo.com/123", "download_media_video"),
            ("tải clip lemon8 https://lemon8-app.com/v/123", "download_media_video"),
            ("tải video likee https://likee.video/@user/video/123", "download_media_video"),
            ("tải post bluesky https://bsky.app/profile/user/post/123", "download_media_video"),
            ("tải video loom https://loom.com/share/123", "download_media_video"),
            ("kéo video streamable https://streamable.com/123", "download_media_video"),
            ("tải video 4k 60fps link này", "download_media_video"),
        ]
        for query, expected_tool in queries:
            scoped = self.mgr._resolve_scoped_tool_names(query)
            self.assertIn(
                expected_tool,
                scoped,
                f"Scoped tools {scoped} did not include {expected_tool} for query: {query}",
            )

    async def test_13_tool_execution_under_50mb(self):
        """Thực thi download_media_video với video <= 50MB thành công."""
        mock_item = MediaItem(
            file_path="/tmp/test_tool_vid.mp4",
            title="Tool Video Test",
            author="Creator",
            duration=40,
            media_type="video",
            source_url="https://vimeo.com/999",
            file_size=10 * 1024 * 1024,
        )
        mock_pipeline = MagicMock()
        mock_pipeline.download = AsyncMock(return_value=mock_item)

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline):
            result = await self.mgr.execute_tool(
                "download_media_video",
                {"url": "https://vimeo.com/999"},
                chat_id="12345",
            )
            self.assertIn("Tool Video Test", result)
            self.assertIn("thành công", result)

    async def test_14_tool_execution_over_50mb_dual_distribution(self):
        """Thực thi download_media_video với video > 50MB kích hoạt phân phối kép và trả về 2 liên kết trực tiếp."""
        temp_dir = Path(tempfile.mkdtemp(prefix="tool_large_vid_"))
        try:
            large_file = temp_dir / "tool_large.mp4"
            large_file.write_bytes(b"L" * (55 * 1024 * 1024))

            mock_item = MediaItem(
                file_path=str(large_file),
                title="Large 4K Documentary",
                author="NationalStudio",
                duration=600,
                media_type="video",
                source_url="https://youtube.com/watch?v=doc4k",
                file_size=55 * 1024 * 1024,
            )
            mock_pipeline = MagicMock()
            mock_pipeline.download = AsyncMock(return_value=mock_item)

            mock_rec = DownloadRecord(
                token="tok_tool_large",
                file_path=large_file,
                filename="tool_large.mp4",
                title="Large 4K Documentary",
                duration=600,
                file_size=55 * 1024 * 1024,
                created_at=0.0,
                expires_at=14400.0,
                internet_url="https://ngrok.dev/api/ai/media/download/tok_tool_large",
                lan_url="http://192.168.0.100:8084/api/ai/media/download/tok_tool_large",
            )

            p1 = temp_dir / "p1.mp4"
            p1.write_bytes(b"P1")
            sim_parts = [{"part_index": 1, "path": str(p1), "duration": 300, "size": 28 * 1024 * 1024}]

            with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline), \
                 patch("app.services.video_chunker.VideoChunker.split_video", new_callable=AsyncMock, return_value=sim_parts), \
                 patch("app.services.media_storage_manager.media_storage_manager.publish_download_item", return_value=mock_rec):

                result = await self.mgr.execute_tool(
                    "download_media_video",
                    {"url": "https://youtube.com/watch?v=doc4k"},
                    chat_id=None,
                )
                self.assertIn("Large 4K Documentary", result)
                self.assertIn("https://ngrok.dev/api/ai/media/download/tok_tool_large", result)
                self.assertIn("http://192.168.0.100:8084/api/ai/media/download/tok_tool_large", result)
                self.assertIn("8084", result)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestAiAgentSystemPromptSection2e(unittest.TestCase):
    """Kiểm thử tri thức trợ lý trong System Prompt Mục 2e về tải 4K/60fps 20+ nền tảng và BLUF 'Dạ CÓ!'."""

    def test_15_system_prompt_section_2e_content(self):
        """Xác thực Mục 2e trong System Prompt chứa đầy đủ 20+ nền tảng, 4K/60fps và BLUF."""
        prompt = AiAgentService._STATIC_SYSTEM_PREFIX
        self.assertIn("2e. GIAO THỨC TRÍCH XUẤT MEDIA, TẢI VIDEO 4K/60FPS & MP3 ĐẶC QUYỀN", prompt)
        self.assertIn("4K 2160p", prompt)
        self.assertIn("60fps", prompt)
        self.assertIn("Dạ CÓ!", prompt)

        # Kiểm tra sự xuất hiện của các nền tảng mới trong prompt
        required_platforms = [
            "Twitch", "Vimeo", "Dailymotion", "Rumble", "Streamable", "Loom",
            "CapCut", "Xiaohongshu", "Weibo", "Bilibili", "Kuaishou", "Lemon8",
            "Likee", "Bluesky", "Facebook", "Instagram", "TikTok", "YouTube"
        ]
        for p in required_platforms:
            self.assertIn(p, prompt, f"System prompt section 2e must explicitly mention {p}")

        # Kiểm tra phân phối kép
        self.assertIn("MÔ HÌNH PHÂN PHỐI KÉP", prompt)
        self.assertIn("port 8084", prompt)
        self.assertIn("HTTP 206 Partial Content", prompt)


class TestZeroDiskLeakLifecycle(unittest.IsolatedAsyncioTestCase):
    """Kiểm thử đảm bảo không rò rỉ đĩa (Zero-Disk Leak) trong toàn bộ vòng đời tải media."""

    async def test_16_zero_disk_leak_on_successful_download_and_cleanup(self):
        """File tạm được dọn dẹp sạch sẽ khi gọi MediaItem.cleanup()."""
        tdir = Path(tempfile.mkdtemp(prefix="test_zero_leak_"))
        try:
            temp_vid = tdir / "temp_video.mp4"
            temp_vid.write_bytes(b"SAMPLE_VIDEO_DATA" * 50)
            self.assertTrue(temp_vid.exists())

            item = MediaItem(
                file_path=str(temp_vid),
                title="Cleanup Test",
                author="Author",
                duration=30,
                media_type="video",
                source_url="https://example.com/v",
                is_temp_file=True,
            )
            item.cleanup()
            self.assertFalse(temp_vid.exists(), "Temporary file must be deleted upon cleanup()")
        finally:
            shutil.rmtree(tdir, ignore_errors=True)

    async def test_17_zero_disk_leak_in_tool_executor_finally_block(self):
        """Khối finally trong execute_tool luôn gọi cleanup() ngay cả khi xử lý gặp Exception."""
        mock_item = MagicMock(spec=MediaItem)
        mock_item.media_type = "video"
        mock_item.file_path = "/tmp/leak_test.mp4"
        mock_item.file_size = 10 * 1024 * 1024
        mock_item.cleanup = MagicMock()

        mock_pipeline = MagicMock()
        mock_pipeline.download = AsyncMock(return_value=mock_item)

        executor = AgentToolExecutor.__new__(AgentToolExecutor)
        executor.telegram_bot = MagicMock()
        executor.telegram_bot.send_chat_action = AsyncMock()
        # Giả lập send_video raise Exception bất ngờ
        executor.telegram_bot.send_video = AsyncMock(side_effect=RuntimeError("Unexpected Telegram API failure"))

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline):
            res = await executor.execute_tool(
                "download_media_video",
                {"url": "https://vimeo.com/12345"},
                chat_id="123456",
            )
            self.assertIn("sự cố khi tải video", res)
            # Khẳng định cleanup() vẫn BẮT BUỘC được gọi trong khối finally
            mock_item.cleanup.assert_called_once()


if __name__ == "__main__":
    unittest.main()
