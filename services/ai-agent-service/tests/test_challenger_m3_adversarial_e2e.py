"""
test_challenger_m3_adversarial_e2e.py — Adversarial Stress Test Harness for Milestone 3.

Empirical Challenger verification suite covering:
  1. Adversarial Platform URLs (24+ platforms):
     - Weird characters, escape sequences (\\r, \\n, \\t, unicode spaces, link enclosures).
     - Nested query parameters, encoded URLs (?redirect=https%3A%2F%2F...), tracking tokens.
     - Vietnamese diacritics, CJK glyphs, emoji and anchors attached to URLs.
  2. Complex Phrasing & Universal Extractor Fallback:
     - Slang, teencode, dialect variations ("tải bài này mp3 giùm tớ", "download clip 4k 60fps").
     - Intent isolation: generic URLs with download keywords trigger fast-path;
       generic URLs without keywords or with negative/analytical intents bypass to LLM.
  3. Audio vs Video Intent Conflict Resolution:
     - URL ending with video extension (.mp4, .mkv) with explicit audio keywords ("tách nhạc", "mp3").
     - Mixed sentences with both video and audio tokens.
     - Enforced audio typing for dedicated music domains (SoundCloud, YouTube Music).
  4. Extreme & Irrational Framerates (FPS) in MediaItem:
     - Irrational numbers (60000/1001, 30000/1001, 24000/1001, 120000/1001).
     - High framerates (144fps, 165fps, 240fps, 360fps, 1000fps).
     - Negative numbers, 0, None, NaN, Infinity, zero-division fractions.
  5. Dual Distribution Resilience under Middle-Part Failures:
     - Video > 50MB split into multiple parts.
     - Simulated network failure / crash on intermediate part.
     - Strict verification of Zero-Disk Leak (parts_dir 100% purged).
     - Ownership transition to media_storage_manager preserved with valid LAN (:8084) & WAN links.
"""

from __future__ import annotations

import asyncio
import math
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.telegram_bot import TelegramBot, FastPathMediaIntent
from app.services.ai_agent_tools import AgentToolExecutor
from app.services.media_downloader import (
    MediaItem,
    _parse_fps_string,
    MultiTierMediaPipeline,
)
from app.services.media_storage_manager import DownloadRecord, media_storage_manager
from app.services.video_chunker import VideoChunker


class TestAdversarial24PlusPlatformUrls(unittest.TestCase):
    """
    Nhóm 1: Bắn các URL của 24+ nền tảng bị chèn ký tự lạ, escape sequences,
    query params lồng nhau, unicode characters, link enclosures.
    """

    def setUp(self):
        self.bot = TelegramBot.__new__(TelegramBot)
        self.regex = TelegramBot._MEDIA_URL_REGEX

    def test_01_all_24_platforms_with_complex_wrappers_and_escapes(self):
        """Bao bọc URL của 24+ nền tảng trong markdown, link enclosures, quote, escape sequence và ký tự lạ."""
        adversarial_samples = [
            # 1. YouTube & Shorts
            ("Tải video: <https://www.youtube.com/watch?v=dQw4w9WgXcQ&feature=emb_title&sub=%7B%22nested%22%3A1%7D>", "https://www.youtube.com/watch?v=dQw4w9WgXcQ&feature=emb_title&sub=%7B%22nested%22%3A1%7D"),
            ("\t\t[Tải Shorts 4K](https://www.youtube.com/shorts/3iCg2c19jGg?si=complex_token_123&t=10s)\n", "https://www.youtube.com/shorts/3iCg2c19jGg?si=complex_token_123&t=10s"),
            # 2. Twitch Clips & VODs
            ("👉 Tải Twitch clip: \"https://clips.twitch.tv/FrailTameGrasshopper?tt_medium=redt&tt_content=share\" 👈", "https://clips.twitch.tv/FrailTameGrasshopper?tt_medium=redt&tt_content=share"),
            ("<<https://www.twitch.tv/videos/1234567890?filter=archives&sort=time>>", "https://www.twitch.tv/videos/1234567890?filter=archives&sort=time"),
            # 3. Vimeo & Dailymotion
            ("Tải video Vimeo: 'https://vimeo.com/123456789?embedded=true&source=vimeo_logo#t=1m20s'!", "https://vimeo.com/123456789?embedded=true&source=vimeo_logo#t=1m20s"),
            ("Tải Dailymotion: (https://dai.ly/x8abcdef?playlist=x123&quality=1080p)...", "https://dai.ly/x8abcdef?playlist=x123&quality=1080p"),
            ("https://www.dailymotion.com/video/x8abcdef?retry=1&signature=abc%2Bdef%3D%3D", "https://www.dailymotion.com/video/x8abcdef?retry=1&signature=abc%2Bdef%3D%3D"),
            # 4. Rumble, Streamable, Loom
            ("Rumble: [https://rumble.com/v12345-sample-clip.html?mref=user&mc=channel], tải nha", "https://rumble.com/v12345-sample-clip.html?mref=user&mc=channel"),
            ("{https://streamable.com/abc123xyz?src=player-page-share};", "https://streamable.com/abc123xyz?src=player-page-share"),
            ("Tải video Loom: \"https://www.loom.com/share/1234567890abcdef1234567890abcdef?sid=nested-uuid-1234\"…", "https://www.loom.com/share/1234567890abcdef1234567890abcdef?sid=nested-uuid-1234"),
            # 5. Facebook Reels, Watch, Videos
            ("(https://www.facebook.com/reel/1234567890/?s=single_unit&mibextid=0FDknk&locale=vi_VN)!", "https://www.facebook.com/reel/1234567890/?s=single_unit&mibextid=0FDknk&locale=vi_VN"),
            ("https://www.facebook.com/watch/?v=9876543210&ref=sharing&_fb_noscript=1;", "https://www.facebook.com/watch/?v=9876543210&ref=sharing&_fb_noscript=1"),
            ("Tải clip FB: \"https://www.facebook.com/page/videos/123456789/?extid=WA-Inc_e\"", "https://www.facebook.com/page/videos/123456789/?extid=WA-Inc_e"),
            ("https://fb.watch/abcdef123/?mibextid=wwXIfr,", "https://fb.watch/abcdef123/?mibextid=wwXIfr"),
            # 6. Instagram Reels, Posts, Stories
            ("[https://www.instagram.com/reel/C123456789/?igsh=MXR5cXZq&utm_source=ig_web_copy_link].", "https://www.instagram.com/reel/C123456789/?igsh=MXR5cXZq&utm_source=ig_web_copy_link"),
            ("'https://www.instagram.com/p/B123456789/?img_index=1&igsh=XYZ'?", "https://www.instagram.com/p/B123456789/?img_index=1&igsh=XYZ"),
            ("https://www.instagram.com/stories/username/1234567890/?utm_source=ig_story_item_share", "https://www.instagram.com/stories/username/1234567890/?utm_source=ig_story_item_share"),
            # 7. Twitter/X, Threads, Reddit, Pinterest
            ("Tải post X: (https://x.com/user/status/1234567890123456789?s=46&t=nested_token_xyz)...", "https://x.com/user/status/1234567890123456789?s=46&t=nested_token_xyz"),
            ("<https://www.threads.net/@user/post/C1234567890?xmt=AQG&s=1>;", "https://www.threads.net/@user/post/C1234567890?xmt=AQG&s=1"),
            ("Tải clip Reddit: https://www.reddit.com/r/funny/comments/123/sample_clip/?utm_source=share&utm_medium=web2x&context=3!", "https://www.reddit.com/r/funny/comments/123/sample_clip/?utm_source=share&utm_medium=web2x&context=3"),
            ("\"https://pin.it/abcXYZ1?invite_code=xyz&sender=9999\"", "https://pin.it/abcXYZ1?invite_code=xyz&sender=9999"),
            # 8. Asian Platforms: TikTok, Douyin, CapCut, Xiaohongshu, Weibo, Bilibili, Kuaishou, Lemon8, Likee, Bluesky
            ("https://www.tiktok.com/@creator/video/1234567890123456789?is_from_webapp=1&sender_device=pc&sub=%7B%22foo%22%3A%22bar%22%7D", "https://www.tiktok.com/@creator/video/1234567890123456789?is_from_webapp=1&sender_device=pc&sub=%7B%22foo%22%3A%22bar%22%7D"),
            ("https://v.douyin.com/abcXYZ1/?utm_campaign=client_share&app=muscle", "https://v.douyin.com/abcXYZ1/?utm_campaign=client_share&app=muscle"),
            ("[https://www.capcut.com/template-detail/123456789?template_id=123&enter_from=template_detail]", "https://www.capcut.com/template-detail/123456789?template_id=123&enter_from=template_detail"),
            ("(https://xhslink.com/a/abcXYZ123?share_id=12345&timestamp=1690000000),", "https://xhslink.com/a/abcXYZ123?share_id=12345&timestamp=1690000000"),
            ("<https://weibo.com/1234567890/AbCdEfGhI?refer_flag=1001030103_>;", "https://weibo.com/1234567890/AbCdEfGhI?refer_flag=1001030103_"),
            ("https://b23.tv/abcXYZ1?fbclid=123456&spm_id_from=333.999.0.0", "https://b23.tv/abcXYZ1?fbclid=123456&spm_id_from=333.999.0.0"),
            ("https://www.kuaishou.com/short-video/1234567?authorId=xyz&utm_source=kuaishou_share", "https://www.kuaishou.com/short-video/1234567?authorId=xyz&utm_source=kuaishou_share"),
            ("https://www.lemon8-app.com/v/123456789?region=vn&pid=feed", "https://www.lemon8-app.com/v/123456789?region=vn&pid=feed"),
            ("https://l.likee.video/v/abcXYZ?share=app&channel=whatsapp", "https://l.likee.video/v/abcXYZ?share=app&channel=whatsapp"),
            ("Tải post Bluesky: https://bsky.app/profile/alice.bsky.social/post/3kabcde123?ref_src=embed&thread=true", "https://bsky.app/profile/alice.bsky.social/post/3kabcde123?ref_src=embed&thread=true"),
        ]

        for raw_wrapper, expected_url in adversarial_samples:
            match = self.regex.search(raw_wrapper)
            self.assertIsNotNone(match, f"Regex failed on adversarial input: {raw_wrapper}")

            intent = self.bot._detect_fastpath_media_download(raw_wrapper)
            self.assertIsNotNone(intent, f"Fastpath failed on: {raw_wrapper}")
            self.assertEqual(intent.media_url, expected_url, f"Extracted URL mismatch for input: {raw_wrapper}")
            self.assertEqual(intent.media_type, "video")

    def test_02_unicode_characters_and_vietnamese_diacritics_around_url(self):
        """URL nằm xen kẽ giữa chuỗi ký tự Unicode tiếng Việt, emoji và ký hiệu đặc biệt."""
        test_cases = [
            ("🇻🇳 Em ơi tải giúp anh video này với: https://www.youtube.com/watch?v=vietnam123 🔥 hay quá!", "https://www.youtube.com/watch?v=vietnam123"),
            ("Bảo Bảo ơi kéo clip nè https://vimeo.com/987654321 ạ, cảm ơn em nhiều nha ❤️", "https://vimeo.com/987654321"),
            ("【Bilibili HD】https://b23.tv/BV1234567 【Siêu mượt 60fps】", "https://b23.tv/BV1234567"),
            ("🌸 Tiểu Hồng Thư review makeup: https://xhslink.com/a/makeup123 ✨ tải clip gốc", "https://xhslink.com/a/makeup123"),
            ("Clip này hài hước quá nè bà con ơi 😆 https://streamable.com/funny123 😂 tải lẹ giùm", "https://streamable.com/funny123"),
        ]
        for prompt, expected_url in test_cases:
            intent = self.bot._detect_fastpath_media_download(prompt)
            self.assertIsNotNone(intent, f"Failed for unicode prompt: {prompt}")
            self.assertEqual(intent.media_url, expected_url)
            self.assertEqual(intent.media_type, "video")


class TestComplexPhrasingAndUniversalExtractor(unittest.TestCase):
    """
    Nhóm 2: Bắn các biến thể câu lệnh phức tạp (tiếng Việt nói suồng sã, teencode,
    đa từ khóa, tiếng Anh) và kiểm thử cơ chế Universal Web Extractor Fallback.
    """

    def setUp(self):
        self.bot = TelegramBot.__new__(TelegramBot)

    def test_03_slang_and_dialect_download_keywords(self):
        """Nhận diện các cách nói đời thường: 'tải bài này mp3 giùm tớ', 'download clip 4k 60fps'."""
        queries = [
            # Biến thể MP3 / Audio
            ("tải bài này mp3 giùm tớ https://generic-host.net/songs/summer_hit.ogg", "audio", "https://generic-host.net/songs/summer_hit.ogg"),
            ("lấy nhạc giùm tớ với https://audio-archive.org/track/123", "audio", "https://audio-archive.org/track/123"),
            ("xin file mp3 bài hát này https://music-space.vn/ballad/01", "audio", "https://music-space.vn/ballad/01"),
            ("tách âm thanh clip https://vids.me/presentation.mp4 giùm anh nha", "audio", "https://vids.me/presentation.mp4"),
            ("bồ ơi down mp3 https://podcast.io/ep99 về máy giùm", "audio", "https://podcast.io/ep99"),
            # Biến thể Video 4K/60fps
            ("download clip 4k 60fps https://streaming-archive.org/video/uhd60.mkv", "video", "https://streaming-archive.org/video/uhd60.mkv"),
            ("kéo clip 60fps này về https://open-video.org/gameplay/clip.mp4", "video", "https://open-video.org/gameplay/clip.mp4"),
            ("tải video 4k link https://cdn-fast.io/renders/demo_4k.mp4 hộ em", "video", "https://cdn-fast.io/renders/demo_4k.mp4"),
            ("lưu clip 1080p https://mycloud.io/share/footage.mov về giúp", "video", "https://mycloud.io/share/footage.mov"),
            ("tải hộ https://custom-vod.tv/v/999999 này với nhé em", "video", "https://custom-vod.tv/v/999999"),
        ]

        for query, expected_type, expected_url in queries:
            intent = self.bot._detect_fastpath_media_download(query)
            self.assertIsNotNone(intent, f"Fastpath failed for complex query: {query}")
            self.assertEqual(intent.media_type, expected_type, f"Intent type mismatch for query: {query}")
            self.assertEqual(intent.media_url, expected_url, f"URL extraction mismatch for query: {query}")

    def test_04_universal_extractor_boundary_and_negative_filtration(self):
        """Đảm bảo URL web thông thường không bị chiếm quyền nếu không có từ khóa tải rõ ràng."""
        non_media_queries = [
            "Anh đang đọc báo https://tuoitre.vn/kinh-doanh/thi-truong.htm nè em",
            "Xem tài liệu này giúp anh https://fastapi.tiangolo.com/tutorial/bigger-applications/",
            "https://stackoverflow.com/questions/4314/how-do-i-check-if-a-file-exists",
            "Đừng tải link này https://dangerous-site.org/malware.mp4 nha em",
            "Không tải video https://storage.net/huge_file.mkv đâu nhé",
            "https://myvideo-host.net/clip123 video này có ý nghĩa gì vậy em?",
            "Tại sao video https://myvideo-host.net/clip123 lại không tải được thế em?",
            "Làm sao để tải được https://myvideo-host.net/clip123 trên điện thoại?",
        ]

        for q in non_media_queries:
            intent = self.bot._detect_fastpath_media_download(q)
            self.assertIsNone(
                intent,
                f"Query should NOT trigger fastpath (must yield to LLM/Agent): {q}"
            )


class TestAudioVsVideoIntentConflictResolution(unittest.TestCase):
    """
    Nhóm 3: Kiểm tra xung đột giữa video intent và audio intent khi URL vừa có
    đuôi video vừa có từ khóa 'nhạc/mp3' hoặc link từ nền tảng nhạc chuyên biệt.
    """

    def setUp(self):
        self.bot = TelegramBot.__new__(TelegramBot)

    def test_05_url_with_video_extension_overridden_by_audio_intent(self):
        """URL kết thúc bằng .mp4, .mkv, .avi nhưng người dùng yêu cầu MP3/nhạc -> media_type='audio'."""
        audio_override_cases = [
            ("tải bài này mp3 giùm tớ https://generic-host.net/video_clip.mp4", "audio"),
            ("lấy nhạc từ video https://my-server.com/live_concert.mkv", "audio"),
            ("tách nhạc từ file https://storage.io/sample_presentation.mp4 giùm anh", "audio"),
            ("chuyển sang mp3 https://video-vault.org/trailer.avi", "audio"),
            ("xin file audio từ link https://custom-stream.com/podcast_video.mp4", "audio"),
            ("tải audio bài này https://www.youtube.com/watch?v=dQw4w9WgXcQ.mp4", "audio"),
        ]

        for text, expected_type in audio_override_cases:
            intent = self.bot._detect_fastpath_media_download(text)
            self.assertIsNotNone(intent, f"Fastpath failed for: {text}")
            self.assertEqual(
                intent.media_type,
                expected_type,
                f"Expected audio override for '{text}', got '{intent.media_type}'"
            )

    def test_06_mixed_keywords_video_and_audio_in_same_prompt(self):
        """Khi câu có cả từ khóa video lẫn audio ('tải video ca nhạc mp3 hot nhất') -> ưu tiên audio."""
        mixed_cases = [
            ("tải video ca nhạc mp3 này https://youtube.com/watch?v=123", "audio"),
            ("lấy nhạc video clip này https://tiktok.com/@u/video/456", "audio"),
            ("tách audio từ video clip 4k https://vimeo.com/789", "audio"),
            ("tải mp3 từ clip 60fps https://clips.twitch.tv/abc", "audio"),
        ]
        for query, expected_type in mixed_cases:
            intent = self.bot._detect_fastpath_media_download(query)
            self.assertIsNotNone(intent, f"Fastpath failed for mixed query: {query}")
            self.assertEqual(
                intent.media_type,
                expected_type,
                f"Audio intent must take precedence in mixed query: {query}"
            )

    def test_07_dedicated_music_domains_always_enforce_audio(self):
        """Các domain chuyên nhạc (SoundCloud, YouTube Music) luôn trả về audio kể cả khi prompt chứa 'tải video'."""
        music_domain_cases = [
            ("https://soundcloud.com/artist/hit-track", "audio"),
            ("https://music.youtube.com/watch?v=music123", "audio"),
            ("tải video https://soundcloud.com/artist/hit-track", "audio"),
            ("download clip https://music.youtube.com/watch?v=music123", "audio"),
        ]
        for query, expected_type in music_domain_cases:
            intent = self.bot._detect_fastpath_media_download(query)
            self.assertIsNotNone(intent, f"Failed for music domain: {query}")
            self.assertEqual(
                intent.media_type,
                expected_type,
                f"Music domain must strictly enforce audio: {query}"
            )


class TestMediaItemExtremeFramerateAndIrrationalFps(unittest.TestCase):
    """
    Nhóm 4: Kiểm tra MediaItem và _parse_fps_string với fps là số vô tỉ,
    fps cực đại (144fps, 240fps), fps âm, None, NaN, Infinity.
    """

    def test_08_irrational_and_fractional_fps_parsing(self):
        """Xác thực phân tích FPS dạng phân số vô tỉ từ ffprobe/yt-dlp."""
        cases = [
            # NTSC 60fps: 60000/1001 ≈ 59.94005994... -> 59.94
            ("60000/1001", 59.94),
            ("60/1", 60.0),
            # NTSC 30fps: 30000/1001 ≈ 29.97002997... -> 29.97
            ("30000/1001", 29.97),
            # Film 24fps: 24000/1001 ≈ 23.97602397... -> 23.98
            ("24000/1001", 23.98),
            # High 120fps: 120000/1001 ≈ 119.8801198... -> 119.88
            ("120000/1001", 119.88),
            # Float trực tiếp
            (59.94005994005994, 59.94),
            (144.0, 144.0),
        ]
        for raw_val, expected_parsed in cases:
            parsed = _parse_fps_string(raw_val)
            self.assertIsNotNone(parsed, f"Failed to parse fps string: {raw_val}")
            self.assertAlmostEqual(parsed, expected_parsed, places=2)

    def test_09_invalid_and_adversarial_fps_strings_survive_safely(self):
        """Xác thực hàm parse và MediaItem an toàn tuyệt đối trước chia 0, NaN, số âm, chuỗi dị biệt."""
        adversarial_fps = [
            "0/0",
            "30/0",       # ZeroDivisionError resilience
            "N/A",
            "-60/1",      # Negative fraction defect test
            "invalid_str",
            None,
            0,
            0.0,
            -1.0,
            -144.0,
            float("nan"),
            float("-inf"),
            "1e-9",       # Tiny float
            "9999999/0",  # Div zero
        ]
        for val in adversarial_fps:
            try:
                parsed = _parse_fps_string(val)
            except Exception as e:
                self.fail(f"_parse_fps_string raised unexpected exception on {val!r}: {e}")

            # Đưa parsed value vào MediaItem để kiểm tra khả năng miễn nhiễm lỗi tầng 2
            item = MediaItem(
                file_path=None,
                title="Adversarial FPS",
                author="Tester",
                duration=10,
                media_type="video",
                source_url="https://example.com/adv",
                fps=parsed,
            )
            # Với mọi giá trị không hợp lệ hoặc <= 0, MediaItem không được gắn nhãn 60fps sai
            if parsed is None or parsed <= 0.0 or math.isnan(parsed):
                self.assertFalse(item.is_60fps, f"is_60fps should be False for fps={parsed}")
                self.assertEqual(item.fps_label, "", f"fps_label should be empty for fps={parsed}")

        # Kiểm tra riêng trường hợp đặc biệt float('inf')
        item_inf = MediaItem(file_path=None, title="Inf", author="Tester", duration=1, media_type="video", source_url="", fps=float("inf"))
        self.assertTrue(item_inf.is_60fps)
        self.assertEqual(item_inf.fps_label, "120fps")

    def test_10_media_item_properties_under_extreme_and_abnormal_fps(self):
        """MediaItem.is_60fps và MediaItem.fps_label hoạt động chính xác dưới các giá trị FPS cực đoan."""
        # 1. FPS cực đại (Gaming 144Hz, 165Hz, 240Hz, 360Hz, High-speed 1000Hz)
        extreme_high_fps = [115.0, 120.0, 144.0, 165.0, 240.0, 360.0, 1000.0]
        for fps_val in extreme_high_fps:
            item = MediaItem(
                file_path=None,
                title="Extreme FPS Video",
                author="Gamer",
                duration=60,
                media_type="video",
                source_url="https://twitch.tv/clip/123",
                fps=fps_val,
            )
            self.assertTrue(item.is_60fps, f"fps={fps_val} must be is_60fps=True")
            self.assertEqual(item.fps_label, "120fps", f"fps={fps_val} must have fps_label='120fps'")

        # 2. FPS trung bình giữa 55 và 65 -> "60fps"
        standard_60fps = [55.0, 59.94, 60.0, 60.001, 64.99, 65.0]
        for fps_val in standard_60fps:
            item = MediaItem(
                file_path=None,
                title="60fps",
                author="Author",
                duration=60,
                media_type="video",
                source_url="https://youtube.com/watch?v=123",
                fps=fps_val,
            )
            self.assertTrue(item.is_60fps)
            self.assertEqual(item.fps_label, "60fps")

        # 3. FPS khác thường giữa 66 và 114 (ví dụ 75fps, 90fps, 100fps)
        custom_fps = [(75.0, "75fps"), (90.0, "90fps"), (100.0, "100fps")]
        for fps_val, expected_label in custom_fps:
            item = MediaItem(
                file_path=None,
                title="Custom FPS",
                author="Author",
                duration=60,
                media_type="video",
                source_url="https://example.com/v",
                fps=fps_val,
            )
            self.assertTrue(item.is_60fps)
            self.assertEqual(item.fps_label, expected_label)

        # 4. FPS bất thường: None, 0, âm
        for invalid_val in [None, 0, -1.0, -60.0, -144.0]:
            item = MediaItem(
                file_path=None,
                title="Invalid FPS",
                author="Author",
                duration=60,
                media_type="video",
                source_url="https://example.com/v",
                fps=invalid_val,
            )
            self.assertFalse(item.is_60fps)
            self.assertEqual(item.fps_label, "")


class TestDualDistributionMiddlePartFailureAndZeroDiskLeak(unittest.IsolatedAsyncioTestCase):
    """
    Nhóm 5: Kiểm tra cơ chế Phân phối kép (Dual Distribution) khi video chunking
    hoặc quá trình dispatch từng Part gặp lỗi bất ngờ giữa chừng.
    Bảo đảm:
      - 100% Zero-Disk Leak: parts_dir và các file part tạm thời bị dọn sạch trong finally.
      - Quyền sở hữu tệp gốc chuyển giao sang media_storage_manager không bị xóa nhầm.
      - Direct Links (LAN port 8084 & WAN Ngrok) đã publish an toàn.
    """

    def setUp(self):
        self.bot = TelegramBot.__new__(TelegramBot)
        self.bot.token = "test_token"
        self.bot.chat_id = "123456"
        self.bot._claim_update = AsyncMock(return_value=True)
        self.bot._video_debounce = MagicMock()
        self.bot._video_debounce.handle_user_text = AsyncMock(return_value=False)
        self.bot._pending_archives = {}
        self.bot._rate_limiter = MagicMock()
        self.bot._rate_limiter.acquire = AsyncMock()
        self.bot.send_message = AsyncMock(return_value=True)
        self.bot.delete_message = AsyncMock(return_value=True)

    async def test_11_middle_part_dispatch_failure_triggers_complete_cleanup_in_telegram_bot(self):
        """Khi gửi Part 2 gặp Network Error (Exception), parts_dir BẮT BUỘC bị xóa sạch 100%."""
        temp_dir = Path(tempfile.mkdtemp(prefix="test_adv_part_fail_"))
        try:
            # Tạo file gốc 80MB (> 50MB)
            orig_file = temp_dir / "large_source.mp4"
            orig_file.write_bytes(b"L" * (80 * 1024 * 1024))

            media_item = MediaItem(
                file_path=str(orig_file),
                title="80MB Concert",
                author="RockBand",
                duration=400,
                media_type="video",
                source_url="https://youtube.com/watch?v=rock80",
                file_size=80 * 1024 * 1024,
                is_temp_file=True,
            )

            # Tạo 3 file part giả lập
            p1 = temp_dir / "part_01.mp4"
            p2 = temp_dir / "part_02.mp4"
            p3 = temp_dir / "part_03.mp4"
            p1.write_bytes(b"P1_DATA" * 50)
            p2.write_bytes(b"P2_DATA" * 50)
            p3.write_bytes(b"P3_DATA" * 50)

            simulated_parts = [
                {"part_index": 1, "path": str(p1), "duration": 133, "size": 27 * 1024 * 1024, "width": 1920, "height": 1080},
                {"part_index": 2, "path": str(p2), "duration": 133, "size": 27 * 1024 * 1024, "width": 1920, "height": 1080},
                {"part_index": 3, "path": str(p3), "duration": 134, "size": 26 * 1024 * 1024, "width": 1920, "height": 1080},
            ]

            mock_pipeline = MagicMock()
            mock_pipeline.download = AsyncMock(return_value=media_item)

            mock_rec = DownloadRecord(
                token="tok_adv_fail",
                file_path=orig_file,
                filename="large_source.mp4",
                title="80MB Concert",
                duration=400,
                file_size=80 * 1024 * 1024,
                created_at=0.0,
                expires_at=14400.0,
                internet_url="https://ngrok-wan.dev/api/ai/media/download/tok_adv_fail",
                lan_url="http://192.168.0.100:8084/api/ai/media/download/tok_adv_fail",
            )

            # Mô phỏng: Part 1 gửi thành công, Part 2 ném RuntimeError (lỗi mạng Telegram gián đoạn)
            call_count = 0

            async def mock_send_video_failing(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return True
                raise RuntimeError("Telegram API connection timeout on Part 2")

            self.bot.send_video = AsyncMock(side_effect=mock_send_video_failing)

            created_part_dirs = []
            orig_mkdtemp = tempfile.mkdtemp

            def tracking_mkdtemp(*args, **kwargs):
                d = orig_mkdtemp(*args, **kwargs)
                created_part_dirs.append(d)
                return d

            with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline), \
                 patch("app.services.video_chunker.VideoChunker.split_video", new_callable=AsyncMock, return_value=simulated_parts), \
                 patch("app.services.media_storage_manager.media_storage_manager.publish_download_item", return_value=mock_rec), \
                 patch("tempfile.mkdtemp", side_effect=tracking_mkdtemp), \
                 patch("asyncio.sleep", new_callable=AsyncMock):

                update = {
                    "update_id": 9999,
                    "message": {
                        "chat": {"id": 123456},
                        "text": "https://youtube.com/watch?v=rock80",
                        "message_id": 999,
                    }
                }

                # Quá trình xử lý update phải bắt exception hoặc hoàn tất khối finally
                try:
                    await self.bot._process_update(update)
                except Exception:
                    pass

                # Khẳng định 1: Thư mục parts_dir BẮT BUỘC bị xóa hoàn toàn khỏi đĩa (Zero-Disk Leak)
                self.assertTrue(len(created_part_dirs) > 0, "A temporary parts_dir must have been created")
                for pdir in created_part_dirs:
                    self.assertFalse(
                        os.path.exists(pdir),
                        f"CRITICAL: Temporary parts_dir {pdir} was leaked after middle part failure!"
                    )

                # Khẳng định 2: Quyền sở hữu file gốc đã được chuyển giao an toàn
                self.assertFalse(
                    media_item.is_temp_file,
                    "media_item.is_temp_file must be False to preserve published file in storage"
                )
                self.assertTrue(orig_file.exists(), "Original file must be kept safe in storage manager")

                # Khẳng định 3: Part 1 đã bị unlink ngay sau khi gửi (Streaming Purge)
                self.assertFalse(p1.exists(), "Part 1 should have been purged immediately after dispatch")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    async def test_12_video_chunker_failure_in_tool_executor_cleans_up_safely(self):
        """Khi VideoChunker.split_video ném ngoại lệ trong AgentToolExecutor, thư mục parts_dir vẫn được dọn sạch."""
        temp_dir = Path(tempfile.mkdtemp(prefix="test_adv_tool_fail_"))
        try:
            large_file = temp_dir / "broken_chunk.mp4"
            large_file.write_bytes(b"DATA" * (15 * 1024 * 1024))

            media_item = MediaItem(
                file_path=str(large_file),
                title="Faulty Video",
                author="Creator",
                duration=200,
                media_type="video",
                source_url="https://vimeo.com/faulty",
                file_size=60 * 1024 * 1024,
            )

            mock_pipeline = MagicMock()
            mock_pipeline.download = AsyncMock(return_value=media_item)

            mock_rec = DownloadRecord(
                token="tok_chunk_fail",
                file_path=large_file,
                filename="broken_chunk.mp4",
                title="Faulty Video",
                duration=200,
                file_size=60 * 1024 * 1024,
                created_at=0.0,
                expires_at=14400.0,
                internet_url="https://ngrok/tok_chunk_fail",
                lan_url="http://192.168.0.100:8084/tok_chunk_fail",
            )

            created_dirs = []
            orig_mkdtemp = tempfile.mkdtemp

            def tracking_mkdtemp(*args, **kwargs):
                d = orig_mkdtemp(*args, **kwargs)
                created_dirs.append(d)
                return d

            executor = AgentToolExecutor.__new__(AgentToolExecutor)
            executor.telegram_bot = None

            # Mô phỏng split_video ném RuntimeError (ví dụ FFmpeg thiếu dung lượng đĩa hoặc corrupt header)
            with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline), \
                 patch("app.services.media_storage_manager.media_storage_manager.publish_download_item", return_value=mock_rec), \
                 patch("app.services.video_chunker.VideoChunker.split_video", new_callable=AsyncMock, side_effect=RuntimeError("FFmpeg segmentation fault")), \
                 patch("tempfile.mkdtemp", side_effect=tracking_mkdtemp):

                result = await executor.execute_tool(
                    "download_media_video",
                    {"url": "https://vimeo.com/faulty"},
                    chat_id=None,
                )

                # Tool executor xử lý lỗi an toàn và trả về thông báo lỗi cho agent
                self.assertIn("sự cố", result)
                self.assertIn("FFmpeg segmentation fault", result)

                # Khẳng định: Thư mục tạm parts_dir BẮT BUỘC bị xóa trong khối finally
                self.assertTrue(len(created_dirs) > 0)
                for cd in created_dirs:
                    self.assertFalse(
                        os.path.exists(cd),
                        f"CRITICAL: parts_dir {cd} was leaked when split_video raised RuntimeError!"
                    )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
