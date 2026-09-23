"""
test_format_sort_60fps.py — Deep Unit & Behavioral Tests for 4K/60fps Format Selection & MediaItem.

Verifies:
  1. ydl_opts configuration in _sync_ytdlp_download:
     - format_sort priority: ["res", "fps", "quality", "size", "br"]
     - format: "bestvideo+bestaudio/best"
     - postprocessor_args containing both 'merger' and 'videoremuxer' with ['-movflags', '+faststart']
     - remuxvideo: 'mp4' and merge_output_format: 'mp4'
  2. MediaItem dataclass:
     - width, height, fps fields
     - helper properties: is_60fps, resolution_label, fps_label
     - 60fps validation (59.94, 60, 60.0) -> is_60fps=True, fps_label='60fps'
     - 120fps validation (120, 119.88) -> is_60fps=True, fps_label='120fps'
     - 30fps validation (29.97, 30) -> is_60fps=False, fps_label='30fps'
     - 4K (2160p), 2K (1440p), 1080p, 720p, 480p resolution labels
  3. DoS Safety & Policy Protection:
     - Livestreams (is_live=True) blocked via ValueError and no Playwright Tier 3 fallback
     - Video duration > 7200s (2 hours) blocked via MediaDurationLimitError / ValueError
  4. MP4 container remuxing and moov faststart flag validation
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.media_downloader import (
    MediaDurationLimitError,
    MediaItem,
    MediaPipelineError,
    MultiTierMediaPipeline,
    TEMP_MEDIA_DIR,
    VideoTooLargeError,
)


class TestMediaItem60FpsAndResolution(unittest.TestCase):
    """Kiểm thử chi tiết MediaItem dataclass với 60fps/120fps và nhãn độ phân giải."""

    def test_01_media_item_fields_and_defaults(self):
        """Khởi tạo MediaItem với đầy đủ thông số width, height, fps."""
        item = MediaItem(
            file_path="/tmp/test.mp4",
            title="Video Test 4K60",
            author="Author Test",
            duration=120,
            media_type="video",
            source_url="https://youtube.com/watch?v=123",
            width=3840,
            height=2160,
            fps=60.0,
            file_size=25 * 1024 * 1024,
        )
        self.assertEqual(item.width, 3840)
        self.assertEqual(item.height, 2160)
        self.assertEqual(item.fps, 60.0)
        self.assertTrue(item.is_60fps)
        self.assertEqual(item.fps_label, "60fps")
        self.assertEqual(item.resolution_label, "4K UHD")

    def test_02_is_60fps_high_framerate_validation(self):
        """Xác thực chuẩn 60fps với các giá trị thực tế (59.94, 60, 60.0)."""
        valid_60fps_values = [59.94, 60, 60.0, 59.94006, 60.0001]
        for fps_val in valid_60fps_values:
            item = MediaItem(
                file_path=None,
                title="60fps clip",
                author="Creator",
                duration=60,
                media_type="video",
                source_url="https://example.com/video",
                fps=fps_val,
            )
            self.assertTrue(
                item.is_60fps,
                f"fps={fps_val} should be recognized as is_60fps=True"
            )
            self.assertEqual(
                item.fps_label,
                "60fps",
                f"fps={fps_val} should have fps_label='60fps'"
            )

    def test_03_is_120fps_high_framerate_validation(self):
        """Xác thực chuẩn 120fps (119.88, 120, 120.0)."""
        valid_120fps_values = [119.88, 120, 120.0, 144.0]
        for fps_val in valid_120fps_values:
            item = MediaItem(
                file_path=None,
                title="120fps clip",
                author="Gamer",
                duration=30,
                media_type="video",
                source_url="https://twitch.tv/clip/123",
                fps=fps_val,
            )
            self.assertTrue(
                item.is_60fps,
                f"fps={fps_val} (>= 55.0) should be is_60fps=True"
            )
            self.assertEqual(
                item.fps_label,
                "120fps",
                f"fps={fps_val} should have fps_label='120fps'"
            )

    def test_04_standard_and_low_framerate_validation(self):
        """Xác thực các chuẩn 30fps, 24fps, 25fps thông thường không được coi là 60fps."""
        cases = [
            (30.0, False, "30fps"),
            (29.97, False, "30fps"),
            (25.0, False, "25fps"),
            (24.0, False, "24fps"),
            (23.976, False, "24fps"),
            (50.0, False, "50fps"),  # < 55.0 fps threshold
        ]
        for fps_val, expected_is_60, expected_label in cases:
            item = MediaItem(
                file_path=None,
                title="Standard FPS",
                author="Creator",
                duration=60,
                media_type="video",
                source_url="https://example.com/video",
                fps=fps_val,
            )
            self.assertEqual(
                item.is_60fps,
                expected_is_60,
                f"fps={fps_val} expected is_60fps={expected_is_60}"
            )
            self.assertEqual(
                item.fps_label,
                expected_label,
                f"fps={fps_val} expected fps_label={expected_label}"
            )

    def test_05_framerate_edge_cases(self):
        """Xác thực các trường hợp biên fps: None, 0, số âm."""
        for invalid_fps in [None, 0, 0.0, -1.0, -60.0]:
            item = MediaItem(
                file_path=None,
                title="Invalid FPS",
                author="Unknown",
                duration=60,
                media_type="video",
                source_url="https://example.com/video",
                fps=invalid_fps,
            )
            self.assertFalse(item.is_60fps)
            self.assertEqual(item.fps_label, "")

    def test_06_resolution_label_landscape_and_portrait(self):
        """Xác thực các nhãn độ phân giải 4K, 2K, 1080p, 720p, 480p cho cả khung hình ngang và dọc."""
        cases = [
            # 4K UHD
            (3840, 2160, "4K UHD"),
            (2160, 3840, "4K UHD"),  # Shorts 4K dọc
            (4096, 2160, "4K UHD"),  # DCI 4K
            # 2K QHD
            (2560, 1440, "2K QHD"),
            (1440, 2560, "2K QHD"),  # Shorts 2K dọc
            # 1080p FHD
            (1920, 1080, "1080p FHD"),
            (1080, 1920, "1080p FHD"),  # Shorts 1080p dọc
            # 720p HD
            (1280, 720, "720p HD"),
            (720, 1280, "720p HD"),
            # 480p SD
            (854, 480, "480p SD"),
            (640, 480, "480p SD"),
            (480, 854, "480p SD"),
            # Dưới 480p
            (320, 240, "320x240"),
            (640, 360, "640x360"),
        ]
        for w, h, expected_label in cases:
            item = MediaItem(
                file_path=None,
                title="Resolution Test",
                author="Author",
                duration=10,
                media_type="video",
                source_url="https://example.com/res",
                width=w,
                height=h,
            )
            self.assertEqual(
                item.resolution_label,
                expected_label,
                f"Failed for dimensions {w}x{h}"
            )

    def test_07_resolution_label_missing_dimensions(self):
        """Xác thực nhãn độ phân giải trả về rỗng khi thiếu width hoặc height."""
        missing_cases = [
            (None, None),
            (1920, None),
            (None, 1080),
            (0, 1080),
            (1920, 0),
            (0, 0),
        ]
        for w, h in missing_cases:
            item = MediaItem(
                file_path=None,
                title="Missing Res",
                author="Author",
                duration=10,
                media_type="video",
                source_url="https://example.com/res",
                width=w,
                height=h,
            )
            self.assertEqual(item.resolution_label, "")


class TestFormatSortYtdlpOptions(unittest.TestCase):
    """Kiểm thử cấu hình format_sort, merger, videoremuxer trong _sync_ytdlp_download."""

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()

    def test_08_ydl_opts_format_sort_and_postprocessor_args(self):
        """Kiểm tra cấu hình ydl_opts được truyền vào YoutubeDL chứa đầy đủ format_sort và faststart."""
        captured_opts = {}

        class DummyYoutubeDL:
            def __init__(self, opts):
                nonlocal captured_opts
                captured_opts.update(opts)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                return False

            def extract_info(self, url, download=True):
                # Giả lập trả về info hợp lệ
                return {
                    "id": "abc12345",
                    "title": "4K60 Video Sample",
                    "uploader": "Uploader",
                    "duration": 180,
                    "width": 3840,
                    "height": 2160,
                    "fps": 60.0,
                    "ext": "mp4",
                }

            def prepare_filename(self, info):
                tmpl = captured_opts.get("outtmpl", "/tmp/media_%(id)s.%(ext)s")
                parent = os.path.dirname(tmpl)
                fpath = os.path.join(parent, f"media_{info['id']}.mp4")
                Path(fpath).write_bytes(b"DUMMY_MP4_CONTENT")
                return fpath

        with patch("yt_dlp.YoutubeDL", side_effect=DummyYoutubeDL):
            item = self.pipeline._sync_ytdlp_download("https://www.youtube.com/watch?v=abc12345")

        self.assertIsNotNone(item)
        self.assertEqual(item.width, 3840)
        self.assertEqual(item.height, 2160)
        self.assertEqual(item.fps, 60.0)
        self.assertTrue(item.is_60fps)

        # 1. format_sort: ["res", "fps", "quality", "size", "br"]
        self.assertIn("format_sort", captured_opts)
        self.assertEqual(
            captured_opts["format_sort"],
            ["res", "fps", "quality", "size", "br"],
            "format_sort must strictly prioritize resolution, fps, quality, size, bitrate"
        )

        # 2. format: "bestvideo+bestaudio/best"
        self.assertEqual(
            captured_opts.get("format"),
            "bestvideo+bestaudio/best",
            "format must be 'bestvideo+bestaudio/best'"
        )

        # 3. postprocessor_args: merger & videoremuxer có '-movflags', '+faststart'
        postprocessor_args = captured_opts.get("postprocessor_args", {})
        self.assertIn("merger", postprocessor_args)
        self.assertIn("videoremuxer", postprocessor_args)
        self.assertEqual(postprocessor_args["merger"], ["-movflags", "+faststart"])
        self.assertEqual(postprocessor_args["videoremuxer"], ["-movflags", "+faststart"])

        # 4. remuxvideo và merge_output_format
        self.assertEqual(captured_opts.get("remuxvideo"), "mp4")
        self.assertEqual(captured_opts.get("merge_output_format"), "mp4")

        # 5. Các cờ an toàn mạng
        self.assertTrue(captured_opts.get("noplaylist"))
        self.assertEqual(captured_opts.get("socket_timeout"), 30)
        self.assertEqual(captured_opts.get("source_address"), "0.0.0.0")

        # Dọn dẹp item
        if item:
            item.cleanup()

    def test_09_match_filter_duration_policy(self):
        """Kiểm tra match_filter từ chối livestream và video > 7200s."""
        captured_opts = {}

        class DummyYoutubeDL:
            def __init__(self, opts):
                nonlocal captured_opts
                captured_opts.update(opts)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                return False

            def extract_info(self, url, download=True):
                return None

        with patch("yt_dlp.YoutubeDL", side_effect=DummyYoutubeDL):
            self.pipeline._sync_ytdlp_download("https://www.youtube.com/watch?v=dummy")

        match_filter = captured_opts.get("match_filter")
        self.assertIsNotNone(match_filter, "match_filter callback must be defined")

        # Case A: Livestream -> ValueError
        with self.assertRaises(ValueError) as ctx_live:
            match_filter({"is_live": True})
        self.assertIn("Livestreams are not supported", str(ctx_live.exception))

        # Case B: Duration > 7200s (ví dụ 7201s) -> Trả về thông báo lỗi
        rejection_msg = match_filter({"duration": 7201, "is_live": False})
        self.assertIsNotNone(rejection_msg)
        self.assertIn("2 giờ", str(rejection_msg))

        # Case C: Duration <= 7200s (ví dụ 7200s) -> Hợp lệ (None)
        self.assertIsNone(match_filter({"duration": 7200, "is_live": False}))
        self.assertIsNone(match_filter({"duration": 3600, "is_live": False}))


class TestDosSafetyAndNoPlaywrightFallback(unittest.IsolatedAsyncioTestCase):
    """Kiểm thử phòng vệ DoS: Chặn Livestream và Video > 2 giờ, không fallback Playwright."""

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()

    def test_10_sync_ytdlp_download_blocks_livestream(self):
        """_sync_ytdlp_download phát hiện livestream và raise ValueError."""
        class DummyLiveDL:
            def __init__(self, opts):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                return False

            def extract_info(self, url, download=True):
                return {
                    "id": "live_stream_id",
                    "title": "Live Stream Video",
                    "is_live": True,
                }

        with patch("yt_dlp.YoutubeDL", side_effect=DummyLiveDL):
            with self.assertRaises(ValueError) as ctx:
                self.pipeline._sync_ytdlp_download("https://www.youtube.com/watch?v=live_stream_id")
            self.assertIn("Livestreams are not supported", str(ctx.exception))

    def test_11_sync_ytdlp_download_blocks_duration_over_7200s(self):
        """_sync_ytdlp_download phát hiện duration > 7200s và raise MediaDurationLimitError."""
        class DummyLongVideoDL:
            def __init__(self, opts):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                return False

            def extract_info(self, url, download=True):
                return {
                    "id": "long_video_id",
                    "title": "10 Hours Relaxation",
                    "duration": 36000,
                    "is_live": False,
                }

        with patch("yt_dlp.YoutubeDL", side_effect=DummyLongVideoDL):
            with self.assertRaises(MediaDurationLimitError) as ctx:
                self.pipeline._sync_ytdlp_download("https://www.youtube.com/watch?v=long_video_id")
            self.assertIn("2 giờ", str(ctx.exception))

    async def test_12_download_does_not_fallback_playwright_on_livestream(self):
        """Khi gặp livestream (ValueError), download() BẮT BUỘC re-raise ValueError và KHÔNG gọi Playwright Tier 3."""
        with patch.object(self.pipeline, "_download_ytdlp", side_effect=ValueError("Livestreams are not supported for offline download")), \
             patch.object(self.pipeline, "_download_playwright_sniff", new_callable=AsyncMock) as mock_playwright:

            with self.assertRaises(ValueError) as ctx:
                await self.pipeline.download("https://www.youtube.com/watch?v=livestream123")

            self.assertIn("Livestreams are not supported", str(ctx.exception))
            # Đảm bảo KHÔNG fallback sang Playwright Tier 3
            mock_playwright.assert_not_awaited()

    async def test_13_download_does_not_fallback_playwright_on_duration_limit(self):
        """Khi thời lượng vượt quá 2 giờ (MediaDurationLimitError), download() re-raise và KHÔNG fallback Playwright."""
        with patch.object(self.pipeline, "_download_ytdlp", side_effect=MediaDurationLimitError("Thời lượng video vượt quá 2 giờ")), \
             patch.object(self.pipeline, "_download_playwright_sniff", new_callable=AsyncMock) as mock_playwright:

            with self.assertRaises(MediaDurationLimitError):
                await self.pipeline.download("https://www.youtube.com/watch?v=longvid123")

            # Đảm bảo KHÔNG fallback sang Playwright Tier 3
            mock_playwright.assert_not_awaited()


class TestMp4ContainerRemuxingAndCleanup(unittest.TestCase):
    """Kiểm thử chuẩn hóa MP4 container và dọn dẹp thư mục tạm."""

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()

    def test_14_mp4_candidate_preference_over_raw_ext(self):
        """Khi yt-dlp prepare_filename trả về .mkv hoặc .webm, pipeline tự nhận diện mp4_candidate nếu có."""
        created_files = []

        class DummyRemuxDL:
            def __init__(self, opts):
                self.opts = opts

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                return False

            def extract_info(self, url, download=True):
                return {
                    "id": "remux_test",
                    "title": "Remuxed Title",
                    "duration": 60,
                    "ext": "webm",
                    "width": 1920,
                    "height": 1080,
                    "fps": 60.0,
                }

            def prepare_filename(self, info):
                tmpl = self.opts.get("outtmpl")
                parent = os.path.dirname(tmpl)
                # Giả lập FFmpeg đã remux sang file .mp4
                mp4_file = os.path.join(parent, "media_remux_test.mp4")
                Path(mp4_file).write_bytes(b"FASTSTART_MP4_DATA")
                created_files.append(mp4_file)
                # prepare_filename vẫn trả về .webm
                return os.path.join(parent, "media_remux_test.webm")

        with patch("yt_dlp.YoutubeDL", side_effect=DummyRemuxDL):
            item = self.pipeline._sync_ytdlp_download("https://www.youtube.com/watch?v=remux_test")

        self.assertIsNotNone(item)
        self.assertTrue(item.file_path.endswith(".mp4"), f"Expected .mp4 candidate, got {item.file_path}")
        self.assertEqual(item.width, 1920)
        self.assertEqual(item.height, 1080)
        self.assertEqual(item.fps, 60.0)

        # Dọn dẹp
        item.cleanup()
        for f in created_files:
            if os.path.exists(f):
                os.unlink(f)

    def test_15_temp_dir_cleaned_up_on_download_error(self):
        """Khi quá trình tải gặp lỗi (DownloadError / Exception), thư mục tạm media_ytdlp_ được dọn dẹp sạch sẽ."""
        temp_dirs_created = []

        import tempfile
        original_mkdtemp = tempfile.mkdtemp

        def tracking_mkdtemp(*args, **kwargs):
            td = original_mkdtemp(*args, **kwargs)
            temp_dirs_created.append(td)
            return td

        class FailingDL:
            def __init__(self, opts):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                return False

            def extract_info(self, url, download=True):
                raise RuntimeError("Network disconnected abruptly during yt-dlp download")

        with patch("tempfile.mkdtemp", side_effect=tracking_mkdtemp), \
             patch("yt_dlp.YoutubeDL", side_effect=FailingDL):
            item = self.pipeline._sync_ytdlp_download("https://www.youtube.com/watch?v=fail123")

        self.assertIsNone(item)
        self.assertTrue(len(temp_dirs_created) > 0)
        for td in temp_dirs_created:
            self.assertFalse(
                os.path.exists(td),
                f"Temporary directory was not cleaned up after error: {td}"
            )


if __name__ == "__main__":
    unittest.main()
