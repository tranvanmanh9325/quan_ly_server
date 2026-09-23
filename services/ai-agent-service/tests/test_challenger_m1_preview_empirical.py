"""
Empirical Challenger Test Suite for Milestone 1: MultiTierMediaPipeline Core Upgrade
Validates edge cases, adversarial inputs, anti-DoS policies, and Universal Extractor routing.
"""

import asyncio
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

_SERVICE_ROOT = str(Path(__file__).resolve().parent.parent)
if _SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _SERVICE_ROOT)

import yt_dlp

from app.services.media_downloader import (
    MediaDurationLimitError,
    MediaItem,
    MediaPipelineError,
    MultiTierMediaPipeline,
    VideoTooLargeError,
    _parse_fps_string,
)


# ==============================================================================
# ADVERSARY GROUP 1: FPS PARSER EDGE CASES & EXTREME INPUTS
# ==============================================================================

class TestFPSParserAdversarialMatrix(unittest.TestCase):
    """Kiểm thử đối kháng hàm _parse_fps_string với các định dạng FPS hiểm hóc."""

    def test_standard_floats_and_ints(self):
        self.assertEqual(_parse_fps_string(59.94), 59.94)
        self.assertEqual(_parse_fps_string(29.97), 29.97)
        self.assertEqual(_parse_fps_string(23.976), 23.98)
        self.assertEqual(_parse_fps_string(60.0), 60.0)
        self.assertEqual(_parse_fps_string(60), 60.0)
        self.assertEqual(_parse_fps_string(30), 30.0)
        self.assertEqual(_parse_fps_string(120), 120.0)
        self.assertEqual(_parse_fps_string(119.88), 119.88)

    def test_string_numbers(self):
        self.assertEqual(_parse_fps_string("60"), 60.0)
        self.assertEqual(_parse_fps_string("30"), 30.0)
        self.assertEqual(_parse_fps_string("59.94"), 59.94)
        self.assertEqual(_parse_fps_string("29.97"), 29.97)
        self.assertEqual(_parse_fps_string(" 60.0 "), 60.0)

    def test_ntsc_fraction_strings(self):
        self.assertEqual(_parse_fps_string("60000/1001"), 59.94)
        self.assertEqual(_parse_fps_string("30000/1001"), 29.97)
        self.assertEqual(_parse_fps_string("24000/1001"), 23.98)
        self.assertEqual(_parse_fps_string("60/1"), 60.0)
        self.assertEqual(_parse_fps_string("30/1"), 30.0)
        self.assertEqual(_parse_fps_string("25/1"), 25.0)
        self.assertEqual(_parse_fps_string("24/1"), 24.0)
        self.assertEqual(_parse_fps_string("120000/1001"), 119.88)

    def test_corrupted_and_edge_inputs(self):
        self.assertIsNone(_parse_fps_string(None))
        self.assertIsNone(_parse_fps_string(0))
        self.assertIsNone(_parse_fps_string(0.0))
        self.assertIsNone(_parse_fps_string("0"))
        self.assertIsNone(_parse_fps_string("0.0"))
        self.assertIsNone(_parse_fps_string("-1"))
        self.assertIsNone(_parse_fps_string(-30.0))
        self.assertIsNone(_parse_fps_string("0/0"))
        self.assertIsNone(_parse_fps_string("N/A"))
        self.assertIsNone(_parse_fps_string("60/0"))       # Mẫu số 0
        self.assertIsNone(_parse_fps_string("60/invalid")) # Mẫu số chuỗi
        self.assertIsNone(_parse_fps_string("1/2/3"))      # Quá nhiều dấu /
        self.assertIsNone(_parse_fps_string("/60"))        # Thiếu tử số
        self.assertIsNone(_parse_fps_string("60/"))        # Thiếu mẫu số
        self.assertIsNone(_parse_fps_string(""))           # Chuỗi rỗng
        self.assertIsNone(_parse_fps_string("   "))        # Khoảng trắng
        self.assertIsNone(_parse_fps_string("not_a_fps"))  # Chữ linh tinh
        self.assertIsNone(_parse_fps_string([]))           # Kiểu dữ liệu list
        self.assertIsNone(_parse_fps_string({}))           # Kiểu dữ liệu dict


# ==============================================================================
# ADVERSARY GROUP 2: MEDIAITEM PROPERTIES (is_60fps, resolution_label, fps_label)
# ==============================================================================

class TestMediaItemPropertiesAdversarialMatrix(unittest.TestCase):
    """Kiểm thử ma trận thuộc tính is_60fps, resolution_label, fps_label."""

    def _create_item(
        self,
        width: Optional[int] = None,
        height: Optional[int] = None,
        fps: Optional[float] = None,
    ) -> MediaItem:
        return MediaItem(
            file_path="/tmp/fake.mp4",
            title="Adversarial Video",
            author="Tester",
            duration=60,
            media_type="video",
            source_url="https://example.com/video",
            width=width,
            height=height,
            fps=fps,
            is_temp_file=False,
        )

    def test_is_60fps_boundary_conditions(self):
        # 60fps & 59.94fps
        self.assertTrue(self._create_item(fps=59.94).is_60fps)
        self.assertTrue(self._create_item(fps=60.0).is_60fps)
        # Biên dưới 55.0
        self.assertTrue(self._create_item(fps=55.0).is_60fps)
        self.assertFalse(self._create_item(fps=54.99).is_60fps)
        # Các chuẩn thường và high-fps
        self.assertFalse(self._create_item(fps=30.0).is_60fps)
        self.assertFalse(self._create_item(fps=24.0).is_60fps)
        self.assertTrue(self._create_item(fps=120.0).is_60fps)
        # Invalid / rỗng
        self.assertFalse(self._create_item(fps=None).is_60fps)
        self.assertFalse(self._create_item(fps=0.0).is_60fps)
        self.assertFalse(self._create_item(fps=-60.0).is_60fps)

    def test_resolution_label_landscape_and_portrait(self):
        # Landscape 16:9
        self.assertEqual(self._create_item(width=3840, height=2160).resolution_label, "4K UHD")
        self.assertEqual(self._create_item(width=2560, height=1440).resolution_label, "2K QHD")
        self.assertEqual(self._create_item(width=1920, height=1080).resolution_label, "1080p FHD")
        self.assertEqual(self._create_item(width=1280, height=720).resolution_label, "720p HD")
        self.assertEqual(self._create_item(width=854, height=480).resolution_label, "480p SD")
        self.assertEqual(self._create_item(width=640, height=360).resolution_label, "640x360")
        self.assertEqual(self._create_item(width=320, height=240).resolution_label, "320x240")

        # Portrait 9:16 (TikTok, Shorts, Reels)
        self.assertEqual(self._create_item(width=2160, height=3840).resolution_label, "4K UHD")
        self.assertEqual(self._create_item(width=1440, height=2560).resolution_label, "2K QHD")
        self.assertEqual(self._create_item(width=1080, height=1920).resolution_label, "1080p FHD")
        self.assertEqual(self._create_item(width=720, height=1280).resolution_label, "720p HD")
        self.assertEqual(self._create_item(width=480, height=854).resolution_label, "480p SD")
        self.assertEqual(self._create_item(width=360, height=640).resolution_label, "360x640")

        # Khuyết thiếu hoặc số 0
        self.assertEqual(self._create_item(width=None, height=1080).resolution_label, "")
        self.assertEqual(self._create_item(width=1920, height=None).resolution_label, "")
        self.assertEqual(self._create_item(width=None, height=None).resolution_label, "")
        self.assertEqual(self._create_item(width=0, height=1080).resolution_label, "")
        self.assertEqual(self._create_item(width=1920, height=0).resolution_label, "")
        self.assertEqual(self._create_item(width=0, height=0).resolution_label, "")

    def test_fps_label_matrix(self):
        self.assertEqual(self._create_item(fps=59.94).fps_label, "60fps")
        self.assertEqual(self._create_item(fps=60.0).fps_label, "60fps")
        self.assertEqual(self._create_item(fps=55.0).fps_label, "60fps")
        self.assertEqual(self._create_item(fps=65.0).fps_label, "60fps")
        self.assertEqual(self._create_item(fps=29.97).fps_label, "30fps")
        self.assertEqual(self._create_item(fps=30.0).fps_label, "30fps")
        self.assertEqual(self._create_item(fps=23.98).fps_label, "24fps")
        self.assertEqual(self._create_item(fps=24.0).fps_label, "24fps")
        self.assertEqual(self._create_item(fps=50.0).fps_label, "50fps")
        self.assertEqual(self._create_item(fps=119.88).fps_label, "120fps")
        self.assertEqual(self._create_item(fps=120.0).fps_label, "120fps")
        self.assertEqual(self._create_item(fps=144.0).fps_label, "120fps")
        self.assertEqual(self._create_item(fps=None).fps_label, "")
        self.assertEqual(self._create_item(fps=0.0).fps_label, "")
        self.assertEqual(self._create_item(fps=-30.0).fps_label, "")


# ==============================================================================
# ADVERSARY GROUP 3: URL SCHEME & PROTOCOL INVARIANTS
# ==============================================================================

class TestURLSchemeAdversarialValidation(unittest.TestCase):
    """Kiểm thử từ chối các URL scheme không hợp lệ hoặc tấn công protocol injection."""

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()

    def test_invalid_url_schemes_raise_media_pipeline_error(self):
        bad_urls = [
            "ftp://files.example.com/video.mp4",
            "not_a_url",
            "",
            "   ",
            "javascript:alert(1)",
            "file:///etc/passwd",
            "data:video/mp4;base64,AAAA...",
            "gopher://evil.com/video",
            "smb://server/share/video.mp4",
            "git://github.com/repo/video",
        ]

        async def run():
            for bad_url in bad_urls:
                with self.assertRaises(MediaPipelineError, msg=f"Should reject {bad_url}"):
                    await self.pipeline.download(bad_url)

        asyncio.run(run())


# ==============================================================================
# ADVERSARY GROUP 4: LIVESTREAM & DURATION LIMITS (ANTI-DOS POLICIES)
# ==============================================================================

class TestAntiDoSLivestreamAndDurationEnforcement(unittest.TestCase):
    """Kiểm thử chính sách chặn đứng livestream và video vượt thời lượng > 7200s."""

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()

    def test_match_filter_duration_rejects_livestream(self):
        """Bộ lọc match_filter_duration phải ném ValueError ngay khi gặp livestream."""
        captured_opts = {}

        class DummyYDL:
            def __init__(self, opts):
                captured_opts.update(opts)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

            def extract_info(self, url, download=True):
                return {"id": "dummy", "is_live": False, "duration": 10}

            def prepare_filename(self, info):
                td = os.path.dirname(captured_opts["outtmpl"])
                p = os.path.join(td, "media_dummy.mp4")
                Path(p).write_bytes(b"content")
                return p

        mock_module = MagicMock()
        mock_module.YoutubeDL = DummyYDL

        with patch.dict(sys.modules, {"yt_dlp": mock_module}):
            self.pipeline._sync_ytdlp_download("https://www.youtube.com/watch?v=live123")

        match_filter = captured_opts.get("match_filter")
        self.assertIsNotNone(match_filter)

        # 1. Livestream -> ValueError
        with self.assertRaises(ValueError):
            match_filter({"is_live": True, "duration": 100})

        # 2. Duration > 7200s -> rejection message string
        reject_msg = match_filter({"is_live": False, "duration": 7201})
        self.assertIsNotNone(reject_msg)
        self.assertIn("vượt quá giới hạn an toàn tối đa 2 giờ", reject_msg)

        # 3. Duration = 7200s (boundary) -> ALLOWED (None)
        self.assertIsNone(match_filter({"is_live": False, "duration": 7200}))

        # 4. Duration < 7200s -> ALLOWED (None)
        self.assertIsNone(match_filter({"is_live": False, "duration": 300}))

    def test_sync_ytdlp_download_extract_info_is_live_raises_value_error(self):
        """Nếu info_dict trả về có is_live=True, phải ném ValueError."""
        class LiveYDL:
            def __init__(self, opts):
                self.opts = opts

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

            def extract_info(self, url, download=True):
                return {"id": "live_vid", "is_live": True, "duration": 0}

        mock_module = MagicMock()
        mock_module.YoutubeDL = LiveYDL

        with patch.dict(sys.modules, {"yt_dlp": mock_module}):
            with self.assertRaises(ValueError):
                self.pipeline._sync_ytdlp_download("https://www.youtube.com/watch?v=live_stream")

    def test_sync_ytdlp_download_extract_info_oversized_duration_raises_limit_error(self):
        """Nếu info_dict trả về có duration > 7200, phải ném MediaDurationLimitError."""
        class LongYDL:
            def __init__(self, opts):
                self.opts = opts

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

            def extract_info(self, url, download=True):
                return {"id": "long_vid", "is_live": False, "duration": 7201}

        mock_module = MagicMock()
        mock_module.YoutubeDL = LongYDL

        with patch.dict(sys.modules, {"yt_dlp": mock_module}):
            with self.assertRaises(MediaDurationLimitError):
                self.pipeline._sync_ytdlp_download("https://www.youtube.com/watch?v=long_movie")

    def test_sync_ytdlp_download_download_error_with_duration_string_converted_to_limit_error(self):
        """yt-dlp DownloadError do match_filter từ chối thời lượng phải được chuyển thành MediaDurationLimitError."""
        class DownloadErrorYDL:
            def __init__(self, opts):
                self.opts = opts

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

            def extract_info(self, url, download=True):
                raise yt_dlp.utils.DownloadError(
                    "ERROR: [youtube] 12345: Thời lượng video vượt quá giới hạn an toàn tối đa 2 giờ của hệ thống."
                )

        mock_module = MagicMock()
        mock_module.YoutubeDL = DownloadErrorYDL
        mock_module.utils = yt_dlp.utils

        with patch.dict(sys.modules, {"yt_dlp": mock_module}):
            with self.assertRaises(MediaDurationLimitError):
                self.pipeline._sync_ytdlp_download("https://www.youtube.com/watch?v=too_long")

    def test_download_pipeline_does_not_fallback_to_playwright_on_duration_limit(self):
        """Khi video vượt quá 7200s, pipeline ngắt ngay lập tức, KHÔNG fallback sang Playwright."""
        async def run():
            with patch.object(
                self.pipeline,
                "_download_ytdlp",
                side_effect=MediaDurationLimitError("Thời lượng video vượt quá giới hạn"),
            ), patch.object(
                self.pipeline,
                "_download_playwright_sniff",
                new_callable=AsyncMock,
            ) as mock_playwright:
                with self.assertRaises(MediaDurationLimitError):
                    await self.pipeline.download("https://www.youtube.com/watch?v=excessive_duration")

                mock_playwright.assert_not_called()

        asyncio.run(run())

    def test_download_pipeline_does_not_fallback_to_playwright_on_livestream(self):
        """Khi gặp livestream, pipeline ngắt ngay lập tức, KHÔNG fallback sang Playwright."""
        async def run():
            with patch.object(
                self.pipeline,
                "_download_ytdlp",
                side_effect=ValueError("Livestreams are not supported for offline download"),
            ), patch.object(
                self.pipeline,
                "_download_playwright_sniff",
                new_callable=AsyncMock,
            ) as mock_playwright:
                with self.assertRaises(ValueError):
                    await self.pipeline.download("https://www.twitch.tv/live_channel")

                mock_playwright.assert_not_called()

        asyncio.run(run())


# ==============================================================================
# ADVERSARY GROUP 5: UNIVERSAL EXTRACTOR ROUTING
# ==============================================================================

class TestUniversalExtractorRoutingMatrix(unittest.TestCase):
    """Kiểm thử cơ chế Universal Web Extractor tiếp nhận mọi URL không thuộc TikTok/Facebook/Threads."""

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()

    def test_universal_extractor_routes_20plus_platforms_to_tier2_ytdlp(self):
        platforms = [
            "https://vimeo.com/76979871",
            "https://clips.twitch.tv/FrailGloriousCurlewPupper",
            "https://www.twitch.tv/videos/123456789",
            "https://streamable.com/abcde",
            "https://www.dailymotion.com/video/x7tgad0",
            "https://www.reddit.com/r/videos/comments/xyz123/great_video/",
            "https://pin.it/7xK9L2",
            "https://twitter.com/user/status/1234567890",
            "https://x.com/user/status/1234567890",
            "https://www.capcut.com/template-detail/12345",
            "https://www.xiaohongshu.com/explore/64a123",
            "https://weibo.com/123456/abcdef",
            "https://www.bilibili.com/video/BV1xx411c7mD",
            "https://www.kuaishou.com/short-video/3x123",
            "https://v.lemon8-app.com/s/12345",
            "https://likee.video/@user/video/123",
            "https://bsky.app/profile/user/post/123",
            "https://rumble.com/v1234-video.html",
            "https://www.loom.com/share/abc123xyz",
            "https://arbitrary-custom-domain.org/media/lecture.mp4",
        ]

        async def run():
            for platform_url in platforms:
                fake_item = MediaItem(
                    file_path="/tmp/fake_universal.mp4",
                    title="Universal Video",
                    author="Author",
                    duration=45,
                    media_type="video",
                    source_url=platform_url,
                    is_temp_file=False,
                    width=1920,
                    height=1080,
                    fps=60.0,
                )

                with patch.object(
                    self.pipeline,
                    "_download_ytdlp",
                    new_callable=AsyncMock,
                    return_value=fake_item,
                ) as mock_ytdlp, patch.object(
                    self.pipeline,
                    "_download_tikwm",
                    new_callable=AsyncMock,
                ) as mock_tikwm, patch.object(
                    self.pipeline,
                    "_download_threads_playwright",
                    new_callable=AsyncMock,
                ) as mock_threads:
                    result = await self.pipeline.download(platform_url)

                    self.assertIs(result, fake_item)
                    mock_ytdlp.assert_awaited_once_with(platform_url)
                    mock_tikwm.assert_not_called()
                    mock_threads.assert_not_called()

        asyncio.run(run())


# ==============================================================================
# ADVERSARY GROUP 6: METADATA EXTRACTION & FFPROBE FALLBACK
# ==============================================================================

class TestMetadataExtractionAndProbeFallback(unittest.TestCase):
    """Kiểm thử bóc tách metadata từ requested_formats và fallback FFprobe."""

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()

    def test_extract_media_item_from_requested_formats_separated_streams(self):
        """Khi yt-dlp trả về requested_formats tách rời video + audio, phải bóc tách đúng video stream."""
        info = {
            "title": "4K60 Test Video",
            "uploader": "Test Channel",
            "duration": 120,
            "width": None,
            "height": None,
            "fps": None,
            "requested_formats": [
                {
                    "format_id": "140",
                    "vcodec": "none",
                    "acodec": "mp4a.40.2",
                    "width": None,
                    "height": None,
                    "fps": None,
                },
                {
                    "format_id": "313",
                    "vcodec": "vp9",
                    "acodec": "none",
                    "width": 3840,
                    "height": 2160,
                    "fps": "60000/1001",
                },
            ],
        }

        item = self.pipeline._extract_media_item(
            info=info,
            file_path="/tmp/non_existent_4k.mp4",
            source_url="https://youtube.com/watch?v=4k60",
        )

        self.assertEqual(item.width, 3840)
        self.assertEqual(item.height, 2160)
        self.assertEqual(item.fps, 59.94)
        self.assertTrue(item.is_60fps)
        self.assertEqual(item.resolution_label, "4K UHD")
        self.assertEqual(item.fps_label, "60fps")

    def test_probe_video_metadata_sync_corrupted_or_missing_file_safe(self):
        """ffprobe probe file không tồn tại hoặc lỗi không được phép ném ngoại lệ."""
        res = self.pipeline._probe_video_metadata_sync("/path/to/definitely_not_existing_file_12345.mp4")
        self.assertIsNone(res)

    def test_extract_media_item_uses_ffprobe_when_info_lacks_dimensions(self):
        """Khi root info và requested_formats đều thiếu width/height/fps, ffprobe bù đắp thành công."""
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            dummy_path = f.name
            f.write(b"\x00" * 1024)

        try:
            info = {
                "title": "Probed Video",
                "uploader": "Camera Man",
                "duration": 0,
                "width": None,
                "height": None,
                "fps": None,
            }

            probe_output = {
                "width": 1920,
                "height": 1080,
                "fps": 60.0,
                "duration": 35.0,
            }

            with patch.object(self.pipeline, "_probe_video_metadata_sync", return_value=probe_output) as mock_probe:
                item = self.pipeline._extract_media_item(
                    info=info,
                    file_path=dummy_path,
                    source_url="https://example.com/video.mp4",
                )

                mock_probe.assert_called_once_with(dummy_path)
                self.assertEqual(item.width, 1920)
                self.assertEqual(item.height, 1080)
                self.assertEqual(item.fps, 60.0)
                self.assertEqual(item.duration, 35)
                self.assertTrue(item.is_60fps)
                self.assertEqual(item.resolution_label, "1080p FHD")
                self.assertEqual(item.fps_label, "60fps")
        finally:
            if os.path.exists(dummy_path):
                os.unlink(dummy_path)


# ==============================================================================
# ADVERSARY GROUP 7: YT-DLP CONFIGURATION INVARIANTS
# ==============================================================================

class TestYtDlpConfigurationInvariants(unittest.TestCase):
    """Kiểm tra bất biến cấu hình ydl_opts (format_sort, faststart, remux)."""

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()

    def test_sync_ytdlp_download_opts_strict_compliance(self):
        captured_opts = {}

        class DummyYDL:
            def __init__(self, opts):
                captured_opts.update(opts)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

            def extract_info(self, url, download=True):
                return {"id": "dummy_inv", "is_live": False, "duration": 10}

            def prepare_filename(self, info):
                td = os.path.dirname(captured_opts["outtmpl"])
                p = os.path.join(td, "media_dummy_inv.mp4")
                Path(p).write_bytes(b"content")
                return p

        mock_module = MagicMock()
        mock_module.YoutubeDL = DummyYDL

        with patch.dict(sys.modules, {"yt_dlp": mock_module}):
            self.pipeline._sync_ytdlp_download("https://www.youtube.com/watch?v=invariants")

        # 1. Format Sort
        self.assertEqual(captured_opts.get("format_sort"), ["res", "fps", "quality", "size", "br"])
        # 2. Format
        self.assertEqual(captured_opts.get("format"), "bestvideo+bestaudio/best")
        # 3. Remux Video
        self.assertEqual(captured_opts.get("remuxvideo"), "mp4")
        # 4. Merge Output Format
        self.assertEqual(captured_opts.get("merge_output_format"), "mp4")
        # 5. Faststart Postprocessor Args
        post_args = captured_opts.get("postprocessor_args", {})
        self.assertEqual(post_args.get("merger"), ["-movflags", "+faststart"])
        self.assertEqual(post_args.get("videoremuxer"), ["-movflags", "+faststart"])


# ==============================================================================
# ADVERSARY GROUP 8: CONCURRENCY STRESS & SEMAPHORE INVARIANTS
# ==============================================================================

class TestConcurrencyStressAndSemaphore(unittest.TestCase):
    """Kiểm tra độ an toàn đa luồng và bảo vệ CPU 2 cores bằng asyncio.Semaphore(2)."""

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()

    def test_ytdlp_semaphore_strictly_limits_peak_concurrency_to_two(self):
        """Khi có nhiều yêu cầu đồng thời, số tác vụ chạy đồng thời không bao giờ vượt quá 2."""
        current_running = 0
        peak_running = 0
        lock = asyncio.Lock()

        async def _mock_sync_worker(url: str):
            nonlocal current_running, peak_running
            async with lock:
                current_running += 1
                if current_running > peak_running:
                    peak_running = current_running
            await asyncio.sleep(0.05)
            async with lock:
                current_running -= 1
            return MediaItem(
                file_path=None,
                title="Concurrent Item",
                author="Tester",
                duration=10,
                media_type="video",
                source_url=url,
                is_temp_file=False,
            )

        async def run():
            # Thay thế executor bằng giả lập async
            with patch.object(self.pipeline, "_sync_ytdlp_download", side_effect=lambda url: None):
                # Mock run_in_executor để đo concurrency thực tế qua semaphore
                orig_download_ytdlp = self.pipeline._download_ytdlp

                async def _tracked_download(url: str):
                    async with self.pipeline._ytdlp_semaphore:
                        return await _mock_sync_worker(url)

                with patch.object(self.pipeline, "_download_ytdlp", side_effect=_tracked_download):
                    urls = [f"https://vimeo.com/{i}" for i in range(8)]
                    tasks = [self.pipeline.download(u) for u in urls]
                    results = await asyncio.gather(*tasks)

                    self.assertEqual(len(results), 8)
                    self.assertLessEqual(peak_running, 2, f"Peak concurrency {peak_running} exceeded limit of 2!")

        asyncio.run(run())


# ==============================================================================
# ADVERSARY GROUP 9: ZERO DISK LEAK & LIFECYCLE MANAGEMENT
# ==============================================================================

class TestZeroDiskLeakAndLifecycle(unittest.TestCase):
    """Kiểm tra cơ chế dọn dẹp đĩa tự động, không rò rỉ tệp tạm (Zero-Disk Leak)."""

    def test_media_item_cleanup_cleans_file_and_parent_dir(self):
        """MediaItem.cleanup() phải xóa sạch cả tệp mp4 và thư mục cha media_ytdlp_xxx."""
        from app.services.media_downloader import TEMP_MEDIA_DIR

        sub_dir = tempfile.mkdtemp(prefix="media_ytdlp_", dir=str(TEMP_MEDIA_DIR))
        fake_file = os.path.join(sub_dir, "test_vid.mp4")
        Path(fake_file).write_bytes(b"dummy video data")

        item = MediaItem(
            file_path=fake_file,
            title="Temp Video",
            author="Author",
            duration=10,
            media_type="video",
            source_url="https://example.com/vid",
            is_temp_file=True,
        )

        self.assertTrue(os.path.exists(fake_file))
        self.assertTrue(os.path.exists(sub_dir))

        item.cleanup()

        self.assertFalse(os.path.exists(fake_file), "File was not removed!")
        self.assertFalse(os.path.exists(sub_dir), "Parent media_ytdlp_ dir was not removed!")
        # TEMP_MEDIA_DIR phải còn nguyên
        self.assertTrue(TEMP_MEDIA_DIR.exists(), "TEMP_MEDIA_DIR must never be deleted!")

    def test_media_item_context_manager_cleanup(self):
        """MediaItem dùng trong 'with' block phải tự động gọi cleanup khi thoát."""
        from app.services.media_downloader import TEMP_MEDIA_DIR

        sub_dir = tempfile.mkdtemp(prefix="media_ytdlp_", dir=str(TEMP_MEDIA_DIR))
        fake_file = os.path.join(sub_dir, "test_ctx.mp4")
        Path(fake_file).write_bytes(b"dummy")

        with MediaItem(
            file_path=fake_file,
            title="Context Video",
            author="Author",
            duration=10,
            media_type="video",
            source_url="https://example.com/vid",
            is_temp_file=True,
        ) as item:
            self.assertTrue(os.path.exists(item.file_path))

        self.assertFalse(os.path.exists(fake_file))
        self.assertFalse(os.path.exists(sub_dir))

    def test_media_item_async_context_manager_cleanup(self):
        """MediaItem dùng trong 'async with' block phải tự động gọi cleanup khi thoát."""
        from app.services.media_downloader import TEMP_MEDIA_DIR

        async def run():
            sub_dir = tempfile.mkdtemp(prefix="media_ytdlp_", dir=str(TEMP_MEDIA_DIR))
            fake_file = os.path.join(sub_dir, "test_actx.mp4")
            Path(fake_file).write_bytes(b"dummy")

            async with MediaItem(
                file_path=fake_file,
                title="Async Context Video",
                author="Author",
                duration=10,
                media_type="video",
                source_url="https://example.com/vid",
                is_temp_file=True,
            ) as item:
                self.assertTrue(os.path.exists(item.file_path))

            self.assertFalse(os.path.exists(fake_file))
            self.assertFalse(os.path.exists(sub_dir))

        asyncio.run(run())

    def test_sync_ytdlp_download_failure_zero_disk_leak(self):
        """Khi _sync_ytdlp_download gặp ngoại lệ, delta thư mục rác trong TEMP_MEDIA_DIR phải bằng 0."""
        from app.services.media_downloader import TEMP_MEDIA_DIR

        pipeline = MultiTierMediaPipeline()
        before_dirs = set(Path(TEMP_MEDIA_DIR).glob("media_ytdlp_*"))

        class CrashingYDL:
            def __init__(self, opts):
                self.opts = opts

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

            def extract_info(self, url, download=True):
                raise RuntimeError("Catastrophic network partition during extraction")

        mock_module = MagicMock()
        mock_module.YoutubeDL = CrashingYDL
        mock_module.utils = yt_dlp.utils

        with patch.dict(sys.modules, {"yt_dlp": mock_module}):
            res = pipeline._sync_ytdlp_download("https://www.youtube.com/watch?v=crash")
            self.assertIsNone(res)

        after_dirs = set(Path(TEMP_MEDIA_DIR).glob("media_ytdlp_*"))
        leaked = after_dirs - before_dirs
        self.assertEqual(len(leaked), 0, f"Detected leaked temporary directories: {leaked}")


# ==============================================================================
# ADVERSARY GROUP 10: INFO DICT DATA TYPES & ROBUSTNESS
# ==============================================================================

class TestInfoDictDataTypesRobustness(unittest.TestCase):
    """Kiểm tra khả năng chịu lỗi của _extract_media_item trước các kiểu dữ liệu dị thường."""

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()

    def test_extract_media_item_with_string_and_float_numbers(self):
        """Xử lý đúng khi width/height/duration/fps là các kiểu chuỗi hoặc số thực."""
        info = {
            "title": "Robust Types Video",
            "uploader": "Uploader",
            "duration": 125.7,  # Float duration
            "width": 1920,
            "height": 1080,
            "fps": 59.94,
            "filesize_approx": "10485760",
        }

        item = self.pipeline._extract_media_item(
            info=info,
            file_path="/tmp/fake_types.mp4",
            source_url="https://example.com/test",
        )

        self.assertEqual(item.duration, 125)
        self.assertEqual(item.width, 1920)
        self.assertEqual(item.height, 1080)
        self.assertEqual(item.fps, 59.94)
        self.assertTrue(item.is_60fps)
        self.assertEqual(item.resolution_label, "1080p FHD")
        self.assertEqual(item.fps_label, "60fps")

    def test_extract_media_item_audio_detection_via_vcodec_acodec(self):
        """Phát hiện chuẩn xác media_type='audio' khi video có vcodec='none' và acodec!='none'."""
        info = {
            "title": "Pure Audio Stream",
            "uploader": "Podcaster",
            "duration": 300,
            "vcodec": "none",
            "acodec": "opus",
            "fps": None,
        }

        item = self.pipeline._extract_media_item(
            info=info,
            file_path="/tmp/fake_podcast.opus",
            source_url="https://example.com/podcast",
            default_media_type="video",
        )

        self.assertEqual(item.media_type, "audio")

