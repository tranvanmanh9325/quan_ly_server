"""
test_challenger_m1_2_format_faststart.py — Empirical Challenger Test Suite (Milestone 1).

Adversarial Stress & Empirical Verification:
1. Format Sorting & 4K/60fps Priority Matrix:
   - Empirical validation using real yt_dlp.YoutubeDL with configured ydl_opts.
   - 4K60 VP9 vs 1080p60 AV1 vs 1080p30 H.264 vs 720p60 H.264.
   - Resolution dominance over FPS (1080p30 > 720p60).
   - FPS dominance on equal resolution (4K60 > 4K30, 1080p60 > 1080p30).
   - Bitrate/size tie-breakers on equal res and fps.
   - Progressive stream selection fallback.
2. Moov Faststart & Postprocessor Pipeline:
   - Merger postprocessor configuration validation (-movflags +faststart).
   - VideoRemuxer postprocessor configuration validation (-movflags +faststart).
   - Container remuxing target mp4 verification.
3. Zero-Disk Leak & Isolation Stress Harness:
   - Full cleanup of successful download (media file and parent media_ytdlp_* folder).
   - Synchronous context manager auto-cleanup (`with MediaItem:`).
   - Livestream rejection zero-disk leak.
   - Duration limit (>7200s) rejection zero-disk leak.
   - Incomplete download / residual .part file detection and zero-disk leak.
   - Unhandled exception during extraction zero-disk leak.
   - 50-cycle stress harness asserting net disk delta == 0 bytes.
4. MediaItem Metadata & Technical Labels:
   - is_60fps, resolution_label, fps_label verification across edge cases.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Dict, List, Optional
import unittest
from unittest.mock import MagicMock, patch

# Ensure services/ai-agent-service is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yt_dlp
from yt_dlp.postprocessor.ffmpeg import FFmpegMergerPP, FFmpegVideoRemuxerPP, resolve_mapping

from app.services.media_downloader import (
    MultiTierMediaPipeline,
    MediaItem,
    TEMP_MEDIA_DIR,
    MediaPipelineError,
    MediaDurationLimitError,
    VideoTooLargeError,
    cleanup_expired_media,
    _parse_fps_string,
)


class TestEmpiricalFormatSortPriority(unittest.TestCase):
    """Kiểm thử thực nghiệm thuật toán format_sort và lựa chọn định dạng 4K/60fps của yt-dlp."""

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()
        captured_opts = {}

        class OptsCaptureYDL:
            def __init__(self, opts):
                nonlocal captured_opts
                captured_opts = opts
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc_val, exc_tb):
                pass
            def extract_info(self, url, download=True):
                return None

        with patch.object(yt_dlp, "YoutubeDL", OptsCaptureYDL):
            self.pipeline._sync_ytdlp_download("https://www.youtube.com/watch?v=probe_opts")

        self.ydl_opts = captured_opts

    def test_format_sort_configuration_matches_spec(self):
        """Xác thực ydl_opts chứa đúng cấu hình format_sort theo yêu cầu kiến trúc."""
        self.assertEqual(
            self.ydl_opts.get("format_sort"),
            ["res", "fps", "quality", "size", "br"],
            "format_sort phải ưu tiên đúng thứ tự: res -> fps -> quality -> size -> br",
        )
        self.assertEqual(
            self.ydl_opts.get("format"),
            "bestvideo+bestaudio/best",
            "format chain phải là bestvideo+bestaudio/best",
        )
        self.assertEqual(self.ydl_opts.get("merge_output_format"), "mp4")
        self.assertEqual(self.ydl_opts.get("remuxvideo"), "mp4")

    def test_empirical_selection_4k60_vp9_over_all_other_streams(self):
        """
        Kiểm thử thực nghiệm với yt-dlp thực tế:
        Có 4K60 VP9, 1080p60 AV1, 1080p30 H.264, 720p60 H.264.
        yt-dlp BẮT BUỘC phải chọn luồng 4K60 VP9 kết hợp bestaudio.
        """
        formats = [
            {
                "format_id": "1080p30_h264",
                "url": "https://example.com/1080p30.mp4",
                "vcodec": "avc1.640028",
                "acodec": "none",
                "width": 1920,
                "height": 1080,
                "fps": 30,
                "ext": "mp4",
                "tbr": 4500,
            },
            {
                "format_id": "720p60_h264",
                "url": "https://example.com/720p60.mp4",
                "vcodec": "avc1.4d401f",
                "acodec": "none",
                "width": 1280,
                "height": 720,
                "fps": 60,
                "ext": "mp4",
                "tbr": 3200,
            },
            {
                "format_id": "1080p60_av1",
                "url": "https://example.com/1080p60.mp4",
                "vcodec": "av01.0.08M.08",
                "acodec": "none",
                "width": 1920,
                "height": 1080,
                "fps": 60,
                "ext": "mp4",
                "tbr": 6000,
            },
            {
                "format_id": "4k60_vp9",
                "url": "https://example.com/4k60.webm",
                "vcodec": "vp9",
                "acodec": "none",
                "width": 3840,
                "height": 2160,
                "fps": 60,
                "ext": "webm",
                "tbr": 18000,
            },
            {
                "format_id": "audio_opus",
                "url": "https://example.com/audio.opus",
                "vcodec": "none",
                "acodec": "opus",
                "abr": 160,
                "ext": "webm",
            },
            {
                "format_id": "audio_aac",
                "url": "https://example.com/audio.m4a",
                "vcodec": "none",
                "acodec": "mp4a.40.2",
                "abr": 128,
                "ext": "m4a",
            },
        ]

        info = {
            "id": "empirical_4k60_test",
            "title": "Empirical 4K60 Test",
            "formats": [dict(f) for f in formats],
        }

        ydl = yt_dlp.YoutubeDL(self.ydl_opts)
        ydl.sort_formats(info)
        selector = ydl.build_format_selector(self.ydl_opts["format"])
        selected = list(selector(info))

        self.assertTrue(len(selected) > 0, "Format selector phải chọn được ít nhất 1 format")
        selected_id = selected[0].get("format_id")
        self.assertEqual(
            selected_id,
            "4k60_vp9+audio_opus",
            f"yt-dlp phải chọn 4k60_vp9+audio_opus, thực tế chọn: {selected_id}",
        )

    def test_empirical_selection_1080p60_av1_over_1080p30_h264(self):
        """
        Khi không có 4K:
        1080p60 AV1 vs 1080p30 H.264 vs 720p60 H.264.
        yt-dlp BẮT BUỘC phải chọn 1080p60 AV1 vì có fps 60 cao hơn 30fps dù H.264 tương thích hơn.
        """
        formats = [
            {
                "format_id": "1080p30_h264",
                "url": "https://example.com/1080p30.mp4",
                "vcodec": "avc1.640028",
                "acodec": "none",
                "width": 1920,
                "height": 1080,
                "fps": 30,
                "ext": "mp4",
                "tbr": 4500,
            },
            {
                "format_id": "720p60_h264",
                "url": "https://example.com/720p60.mp4",
                "vcodec": "avc1.4d401f",
                "acodec": "none",
                "width": 1280,
                "height": 720,
                "fps": 60,
                "ext": "mp4",
                "tbr": 3200,
            },
            {
                "format_id": "1080p60_av1",
                "url": "https://example.com/1080p60.mp4",
                "vcodec": "av01.0.08M.08",
                "acodec": "none",
                "width": 1920,
                "height": 1080,
                "fps": 60,
                "ext": "mp4",
                "tbr": 6000,
            },
            {
                "format_id": "audio_best",
                "url": "https://example.com/audio.opus",
                "vcodec": "none",
                "acodec": "opus",
                "abr": 160,
                "ext": "webm",
            },
        ]

        info = {
            "id": "empirical_1080p60_test",
            "title": "Empirical 1080p60 Test",
            "formats": [dict(f) for f in formats],
        }

        ydl = yt_dlp.YoutubeDL(self.ydl_opts)
        ydl.sort_formats(info)
        selector = ydl.build_format_selector(self.ydl_opts["format"])
        selected = list(selector(info))

        selected_id = selected[0].get("format_id")
        self.assertEqual(
            selected_id,
            "1080p60_av1+audio_best",
            f"yt-dlp phải ưu tiên 1080p60 thay vì 1080p30, thực tế chọn: {selected_id}",
        )

    def test_empirical_resolution_dominance_over_fps(self):
        """
        Kiểm tra tính thống trị của Độ phân giải (res) trước Tốc độ khung hình (fps):
        Có 1080p30 H.264 và 720p60 H.264.
        Do 'res' đứng trước 'fps' trong format_sort, 1080p30 PHẢI thắng 720p60.
        """
        formats = [
            {
                "format_id": "720p60_h264",
                "url": "https://example.com/720p60.mp4",
                "vcodec": "avc1.4d401f",
                "acodec": "none",
                "width": 1280,
                "height": 720,
                "fps": 60,
                "ext": "mp4",
                "tbr": 3500,
            },
            {
                "format_id": "1080p30_h264",
                "url": "https://example.com/1080p30.mp4",
                "vcodec": "avc1.640028",
                "acodec": "none",
                "width": 1920,
                "height": 1080,
                "fps": 30,
                "ext": "mp4",
                "tbr": 4000,
            },
            {
                "format_id": "audio_aac",
                "url": "https://example.com/audio.m4a",
                "vcodec": "none",
                "acodec": "mp4a.40.2",
                "abr": 128,
                "ext": "m4a",
            },
        ]

        info = {
            "id": "empirical_res_dominance",
            "title": "Empirical Res Dominance",
            "formats": [dict(f) for f in formats],
        }

        ydl = yt_dlp.YoutubeDL(self.ydl_opts)
        ydl.sort_formats(info)
        selector = ydl.build_format_selector(self.ydl_opts["format"])
        selected = list(selector(info))

        selected_id = selected[0].get("format_id")
        self.assertEqual(
            selected_id,
            "1080p30_h264+audio_aac",
            f"1080p30 phải thắng 720p60 do res ưu tiên trước fps, thực tế chọn: {selected_id}",
        )

    def test_empirical_fps_tie_breaker_on_equal_4k_resolution(self):
        """
        Khi cùng độ phân giải 4K (3840x2160):
        4K60 VP9 vs 4K30 H.264.
        4K60 BẮT BUỘC phải thắng 4K30 vì tiêu chí 'fps' đứng ngay sau 'res'.
        """
        formats = [
            {
                "format_id": "4k30_h264",
                "url": "https://example.com/4k30.mp4",
                "vcodec": "avc1.640033",
                "acodec": "none",
                "width": 3840,
                "height": 2160,
                "fps": 30,
                "ext": "mp4",
                "tbr": 20000,
            },
            {
                "format_id": "4k60_vp9",
                "url": "https://example.com/4k60.webm",
                "vcodec": "vp9",
                "acodec": "none",
                "width": 3840,
                "height": 2160,
                "fps": 60,
                "ext": "webm",
                "tbr": 18000,
            },
            {
                "format_id": "audio_best",
                "url": "https://example.com/audio.opus",
                "vcodec": "none",
                "acodec": "opus",
                "abr": 160,
                "ext": "webm",
            },
        ]

        info = {
            "id": "empirical_4k_fps_tie_breaker",
            "title": "Empirical 4K FPS Tie-Breaker",
            "formats": [dict(f) for f in formats],
        }

        ydl = yt_dlp.YoutubeDL(self.ydl_opts)
        ydl.sort_formats(info)
        selector = ydl.build_format_selector(self.ydl_opts["format"])
        selected = list(selector(info))

        selected_id = selected[0].get("format_id")
        self.assertEqual(
            selected_id,
            "4k60_vp9+audio_best",
            f"4K60 phải thắng 4K30 dù 4K30 có tbr cao hơn, thực tế chọn: {selected_id}",
        )

    def test_empirical_progressive_stream_selection(self):
        """
        Khi video chỉ có progressive streams (không có separate video/audio):
        yt-dlp fallback sang 'best' và chọn luồng progressive 1080p60 thay vì 1080p30 hoặc 720p60.
        """
        formats = [
            {
                "format_id": "prog_720p60",
                "url": "https://example.com/prog_720p60.mp4",
                "vcodec": "avc1.4d401f",
                "acodec": "mp4a.40.2",
                "width": 1280,
                "height": 720,
                "fps": 60,
                "ext": "mp4",
                "tbr": 3200,
            },
            {
                "format_id": "prog_1080p30",
                "url": "https://example.com/prog_1080p30.mp4",
                "vcodec": "avc1.640028",
                "acodec": "mp4a.40.2",
                "width": 1920,
                "height": 1080,
                "fps": 30,
                "ext": "mp4",
                "tbr": 4500,
            },
            {
                "format_id": "prog_1080p60",
                "url": "https://example.com/prog_1080p60.mp4",
                "vcodec": "avc1.64002a",
                "acodec": "mp4a.40.2",
                "width": 1920,
                "height": 1080,
                "fps": 60,
                "ext": "mp4",
                "tbr": 6500,
            },
        ]

        info = {
            "id": "empirical_progressive_test",
            "title": "Empirical Progressive Test",
            "formats": [dict(f) for f in formats],
        }

        ydl = yt_dlp.YoutubeDL(self.ydl_opts)
        ydl.sort_formats(info)
        selector = ydl.build_format_selector(self.ydl_opts["format"])
        selected = list(selector(info))

        selected_id = selected[0].get("format_id")
        self.assertEqual(
            selected_id,
            "prog_1080p60",
            f"Progressive stream 1080p60 phải được chọn, thực tế chọn: {selected_id}",
        )


class TestEmpiricalMoovFaststartPostprocessor(unittest.TestCase):
    """Kiểm thử thực nghiệm cơ chế Moov Faststart (+faststart) cho merger và videoremuxer."""

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()
        captured_opts = {}

        class OptsCaptureYDL:
            def __init__(self, opts):
                nonlocal captured_opts
                captured_opts = opts
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc_val, exc_tb):
                pass
            def extract_info(self, url, download=True):
                return None

        with patch.object(yt_dlp, "YoutubeDL", OptsCaptureYDL):
            self.pipeline._sync_ytdlp_download("https://www.youtube.com/watch?v=probe_faststart")

        self.ydl_opts = captured_opts

    def test_postprocessor_args_presence_and_structure(self):
        """Xác thực cả 'merger' và 'videoremuxer' đều có cờ -movflags +faststart."""
        pp_args = self.ydl_opts.get("postprocessor_args")
        self.assertIsInstance(pp_args, dict, "postprocessor_args phải là dict")

        merger_args = pp_args.get("merger")
        self.assertIsNotNone(merger_args, "merger postprocessor_args không được None")
        self.assertIn("-movflags", merger_args)
        self.assertIn("+faststart", merger_args)

        videoremuxer_args = pp_args.get("videoremuxer")
        self.assertIsNotNone(videoremuxer_args, "videoremuxer postprocessor_args không được None")
        self.assertIn("-movflags", videoremuxer_args)
        self.assertIn("+faststart", videoremuxer_args)

    def test_ffmpeg_merger_pp_generates_faststart_args(self):
        """Mô phỏng FFmpegMergerPP thực tế của yt-dlp nhận postprocessor_args từ ydl_opts."""
        dummy_ydl = yt_dlp.YoutubeDL(self.ydl_opts)
        merger = FFmpegMergerPP(dummy_ydl)

        # Kiểm tra _configuration_args sinh ra từ merger cho ffmpeg
        config_args = merger._configuration_args("ffmpeg")
        self.assertIn("-movflags", config_args)
        self.assertIn("+faststart", config_args)

    def test_ffmpeg_videoremuxer_pp_generates_faststart_args(self):
        """Mô phỏng FFmpegVideoRemuxerPP thực tế của yt-dlp nhận postprocessor_args từ ydl_opts."""
        dummy_ydl = yt_dlp.YoutubeDL(self.ydl_opts)
        remuxer = FFmpegVideoRemuxerPP(dummy_ydl)

        # Kiểm tra _configuration_args sinh ra từ videoremuxer cho ffmpeg
        config_args = remuxer._configuration_args("ffmpeg")
        self.assertIn("-movflags", config_args)
        self.assertIn("+faststart", config_args)

    def test_videoremuxer_behavior_on_webm_vs_mp4(self):
        """
        Kiểm thử đối kháng (Adversarial Caveat):
        - Input là .webm -> VideoRemuxer remux sang .mp4 với +faststart.
        - Input đã là .mp4 -> resolve_mapping trả về skip_msg 'already is in target format mp4'.
        """
        target_ext_webm, skip_webm = resolve_mapping("webm", "mp4")
        self.assertEqual(target_ext_webm, "mp4")
        self.assertIsNone(skip_webm, "Webm phải được remux sang mp4 mà không bị skip")

        target_ext_mp4, skip_mp4 = resolve_mapping("mp4", "mp4")
        self.assertEqual(target_ext_mp4, "mp4")
        self.assertIsNotNone(skip_mp4, "yt-dlp chuẩn skip remux khi source_ext == target_ext")
        self.assertIn("already is in target format", skip_mp4)


class TestEmpiricalZeroDiskLeakAndIsolation(unittest.TestCase):
    """Kiểm thử thực nghiệm cô lập đĩa và bảo đảm Zero-Disk Leak trong mọi tình huống lỗi/thành công."""

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()
        self.test_dir = tempfile.mkdtemp(prefix="challenger_test_leak_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_successful_download_cleanup_purges_file_and_temp_directory(self):
        """Khi tải thành công, MediaItem.cleanup() phải xóa sạch cả file mp4 và thư mục media_ytdlp_*."""
        ytdlp_temp_dir = tempfile.mkdtemp(prefix="media_ytdlp_", dir=str(TEMP_MEDIA_DIR))
        final_mp4 = os.path.join(ytdlp_temp_dir, "media_video123.mp4")
        with open(final_mp4, "wb") as f:
            f.write(b"\x00" * (1024 * 1024))  # 1MB dummy video

        item = MediaItem(
            file_path=final_mp4,
            title="Success Video",
            author="Uploader",
            duration=60,
            media_type="video",
            source_url="https://youtube.com/watch?v=success",
            file_size=os.path.getsize(final_mp4),
            is_temp_file=True,
            width=1920,
            height=1080,
            fps=60.0,
        )

        self.assertTrue(os.path.exists(final_mp4))
        self.assertTrue(os.path.exists(ytdlp_temp_dir))

        # Thực thi dọn dẹp
        item.cleanup()

        # Xác thực file và thư mục cha đều bị xóa sạch
        self.assertFalse(os.path.exists(final_mp4), "Tệp MP4 phải bị xóa")
        self.assertFalse(os.path.exists(ytdlp_temp_dir), "Thư mục media_ytdlp_* phải bị xóa sạch khỏi TEMP_MEDIA_DIR")

    def test_context_manager_auto_cleanup(self):
        """Khối `with item:` phải tự động xóa sạch đĩa khi hoàn tất."""
        ytdlp_temp_dir = tempfile.mkdtemp(prefix="media_ytdlp_", dir=str(TEMP_MEDIA_DIR))
        final_mp4 = os.path.join(ytdlp_temp_dir, "media_cm.mp4")
        with open(final_mp4, "wb") as f:
            f.write(b"data")

        with MediaItem(
            file_path=final_mp4,
            title="CM Test",
            author="Uploader",
            duration=30,
            media_type="video",
            source_url="https://example.com/video",
            is_temp_file=True,
        ) as item:
            self.assertTrue(os.path.exists(item.file_path))

        # Ra khỏi khối with -> đĩa phải sạch
        self.assertFalse(os.path.exists(final_mp4))
        self.assertFalse(os.path.exists(ytdlp_temp_dir))

    def test_livestream_rejection_zero_disk_leak(self):
        """Khi phát hiện livestream, _sync_ytdlp_download ném ValueError và dọn sạch thư mục tạm."""
        active_temp_dirs = []

        class LiveYDL:
            def __init__(self, opts):
                self.opts = opts
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc_val, exc_tb):
                pass
            def extract_info(self, url, download=True):
                td = os.path.dirname(self.opts["outtmpl"])
                active_temp_dirs.append(td)
                # Tạo file rác dở dang
                with open(os.path.join(td, "live_stream.part"), "wb") as f:
                    f.write(b"stream_chunk")
                return {"is_live": True, "id": "live_test"}

        with patch.object(yt_dlp, "YoutubeDL", LiveYDL):
            with self.assertRaises(ValueError):
                self.pipeline._sync_ytdlp_download("https://www.youtube.com/watch?v=live_stream")

        self.assertTrue(len(active_temp_dirs) > 0)
        for td in active_temp_dirs:
            self.assertFalse(os.path.exists(td), f"Thư mục tạm {td} phải bị xóa sạch khi từ chối livestream")

    def test_duration_limit_rejection_zero_disk_leak(self):
        """Khi video vượt quá 7200s, ném MediaDurationLimitError và dọn sạch thư mục tạm."""
        active_temp_dirs = []

        class LongVideoYDL:
            def __init__(self, opts):
                self.opts = opts
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc_val, exc_tb):
                pass
            def extract_info(self, url, download=True):
                td = os.path.dirname(self.opts["outtmpl"])
                active_temp_dirs.append(td)
                with open(os.path.join(td, "long_video.mp4"), "wb") as f:
                    f.write(b"long_video_data")
                return {"duration": 7201, "id": "long_video_test"}

        with patch.object(yt_dlp, "YoutubeDL", LongVideoYDL):
            with self.assertRaises(MediaDurationLimitError):
                self.pipeline._sync_ytdlp_download("https://www.youtube.com/watch?v=over_2h")

        for td in active_temp_dirs:
            self.assertFalse(os.path.exists(td), f"Thư mục tạm {td} phải bị xóa sạch khi vượt quá 2 giờ")

    def test_incomplete_part_files_zero_disk_leak(self):
        """Khi download bị gián đoạn sinh file .part, ném MediaPipelineError và dọn sạch thư mục tạm."""
        active_temp_dirs = []

        class BrokenYDL:
            def __init__(self, opts):
                self.opts = opts
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc_val, exc_tb):
                pass
            def extract_info(self, url, download=True):
                td = os.path.dirname(self.opts["outtmpl"])
                active_temp_dirs.append(td)
                with open(os.path.join(td, "media_broken.mp4.part"), "wb") as f:
                    f.write(b"broken_part")
                return {"id": "broken_vid"}
            def prepare_filename(self, info):
                return os.path.join(active_temp_dirs[-1], "media_broken.mp4")

        with patch.object(yt_dlp, "YoutubeDL", BrokenYDL):
            with self.assertRaises(MediaPipelineError):
                self.pipeline._sync_ytdlp_download("https://www.youtube.com/watch?v=broken_dl")

        for td in active_temp_dirs:
            self.assertFalse(os.path.exists(td), f"Thư mục tạm {td} chứa file .part phải bị xóa sạch")

    def test_unhandled_exception_zero_disk_leak(self):
        """Khi xảy ra ngoại lệ không xác định trong lúc tải, thư mục tạm luôn bị xóa trong khối except."""
        active_temp_dirs = []

        class FailingYDL:
            def __init__(self, opts):
                self.opts = opts
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc_val, exc_tb):
                pass
            def extract_info(self, url, download=True):
                td = os.path.dirname(self.opts["outtmpl"])
                active_temp_dirs.append(td)
                with open(os.path.join(td, "junk.bin"), "wb") as f:
                    f.write(b"junk")
                raise RuntimeError("Simulated crash in yt-dlp core")

        with patch.object(yt_dlp, "YoutubeDL", FailingYDL):
            res = self.pipeline._sync_ytdlp_download("https://www.youtube.com/watch?v=crash")
            self.assertIsNone(res)

        for td in active_temp_dirs:
            self.assertFalse(os.path.exists(td), f"Thư mục tạm {td} phải bị xóa sạch khi crash")

    def test_stress_harness_50_cycles_net_disk_delta_is_zero(self):
        """
        Stress harness 50 vòng lặp kiểm tra rò rỉ đĩa:
        Xen kẽ các trường hợp thành công (kèm cleanup), livestream error,
        duration limit error, part file error, và unhandled exception.
        Delta số lượng file và dung lượng thư mục TEMP_MEDIA_DIR phải bằng ĐÚNG 0.
        """
        def get_dir_stats(path: Path):
            files = list(path.glob("**/*"))
            total_size = sum(f.stat().st_size for f in files if f.is_file())
            return len(files), total_size

        initial_count, initial_size = get_dir_stats(TEMP_MEDIA_DIR)

        for cycle in range(50):
            case = cycle % 5
            if case == 0:
                # Thành công kèm cleanup
                td = tempfile.mkdtemp(prefix="media_ytdlp_", dir=str(TEMP_MEDIA_DIR))
                fp = os.path.join(td, f"cycle_{cycle}.mp4")
                with open(fp, "wb") as f:
                    f.write(b"A" * 1024)
                item = MediaItem(file_path=fp, title="T", author="A", duration=10, media_type="video", source_url="url")
                item.cleanup()
            elif case == 1:
                # Livestream
                class S1:
                    def __init__(self, opts): self.opts = opts
                    def __enter__(self): return self
                    def __exit__(self, *args): pass
                    def extract_info(self, url, download=True): return {"is_live": True}
                with patch.object(yt_dlp, "YoutubeDL", S1):
                    try: self.pipeline._sync_ytdlp_download("http://example.com/live")
                    except Exception: pass
            elif case == 2:
                # Long video
                class S2:
                    def __init__(self, opts): self.opts = opts
                    def __enter__(self): return self
                    def __exit__(self, *args): pass
                    def extract_info(self, url, download=True): return {"duration": 9999}
                with patch.object(yt_dlp, "YoutubeDL", S2):
                    try: self.pipeline._sync_ytdlp_download("http://example.com/long")
                    except Exception: pass
            elif case == 3:
                # Part file
                class S3:
                    def __init__(self, opts): self.opts = opts
                    def __enter__(self): return self
                    def __exit__(self, *args): pass
                    def extract_info(self, url, download=True):
                        td = os.path.dirname(self.opts["outtmpl"])
                        with open(os.path.join(td, "c.part"), "wb") as f: f.write(b"part")
                        return {"id": "c"}
                    def prepare_filename(self, info):
                        return os.path.join(os.path.dirname(self.opts["outtmpl"]), "c.mp4")
                with patch.object(yt_dlp, "YoutubeDL", S3):
                    try: self.pipeline._sync_ytdlp_download("http://example.com/part")
                    except Exception: pass
            elif case == 4:
                # Crash
                class S4:
                    def __init__(self, opts): self.opts = opts
                    def __enter__(self): return self
                    def __exit__(self, *args): pass
                    def extract_info(self, url, download=True): raise RuntimeError("Boom")
                with patch.object(yt_dlp, "YoutubeDL", S4):
                    self.pipeline._sync_ytdlp_download("http://example.com/crash")

        final_count, final_size = get_dir_stats(TEMP_MEDIA_DIR)
        delta_count = final_count - initial_count
        delta_size = final_size - initial_size

        self.assertEqual(delta_count, 0, f"Rò rỉ số lượng tệp tạm sau 50 chu kỳ: delta={delta_count}")
        self.assertEqual(delta_size, 0, f"Rò rỉ dung lượng đĩa sau 50 chu kỳ: delta={delta_size} bytes")


class TestMediaItemMetadataAndLabelsEmpirical(unittest.TestCase):
    """Kiểm thử tính chính xác của bóc tách siêu dữ liệu MediaItem và nhãn trực quan."""

    def test_parse_fps_string_edge_cases(self):
        """_parse_fps_string phải xử lý chuẩn xác phân số, số thực, chuỗi số và None."""
        self.assertEqual(_parse_fps_string("60000/1001"), 59.94)
        self.assertEqual(_parse_fps_string("60/1"), 60.0)
        self.assertEqual(_parse_fps_string("30000/1001"), 29.97)
        self.assertEqual(_parse_fps_string("24000/1001"), 23.98)
        self.assertEqual(_parse_fps_string(60), 60.0)
        self.assertEqual(_parse_fps_string(59.94), 59.94)
        self.assertEqual(_parse_fps_string("60"), 60.0)
        self.assertEqual(_parse_fps_string("0/0"), None)
        self.assertEqual(_parse_fps_string("invalid/val"), None)
        self.assertEqual(_parse_fps_string(None), None)

    def test_media_item_is_60fps_boundary_values(self):
        """is_60fps trả về True khi fps >= 55.0."""
        self.assertTrue(MediaItem(None, "T", "A", 0, "video", "u", fps=60.0).is_60fps)
        self.assertTrue(MediaItem(None, "T", "A", 0, "video", "u", fps=59.94).is_60fps)
        self.assertTrue(MediaItem(None, "T", "A", 0, "video", "u", fps=55.0).is_60fps)
        self.assertTrue(MediaItem(None, "T", "A", 0, "video", "u", fps=120.0).is_60fps)
        self.assertFalse(MediaItem(None, "T", "A", 0, "video", "u", fps=54.9).is_60fps)
        self.assertFalse(MediaItem(None, "T", "A", 0, "video", "u", fps=30.0).is_60fps)
        self.assertFalse(MediaItem(None, "T", "A", 0, "video", "u", fps=None).is_60fps)

    def test_media_item_resolution_labels(self):
        """resolution_label phải phân loại đúng theo chiều ngắn nhất của video (hỗ trợ cả video ngang và dọc)."""
        # Video ngang 16:9
        self.assertEqual(MediaItem(None, "T", "A", 0, "video", "u", width=3840, height=2160).resolution_label, "4K UHD")
        self.assertEqual(MediaItem(None, "T", "A", 0, "video", "u", width=2560, height=1440).resolution_label, "2K QHD")
        self.assertEqual(MediaItem(None, "T", "A", 0, "video", "u", width=1920, height=1080).resolution_label, "1080p FHD")
        self.assertEqual(MediaItem(None, "T", "A", 0, "video", "u", width=1280, height=720).resolution_label, "720p HD")
        self.assertEqual(MediaItem(None, "T", "A", 0, "video", "u", width=854, height=480).resolution_label, "480p SD")

        # Video dọc TikTok / Shorts 9:16
        self.assertEqual(MediaItem(None, "T", "A", 0, "video", "u", width=2160, height=3840).resolution_label, "4K UHD")
        self.assertEqual(MediaItem(None, "T", "A", 0, "video", "u", width=1080, height=1920).resolution_label, "1080p FHD")
        self.assertEqual(MediaItem(None, "T", "A", 0, "video", "u", width=720, height=1280).resolution_label, "720p HD")

        # Khuyết thiếu
        self.assertEqual(MediaItem(None, "T", "A", 0, "video", "u", width=None, height=1080).resolution_label, "")
        self.assertEqual(MediaItem(None, "T", "A", 0, "video", "u", width=1920, height=None).resolution_label, "")

    def test_media_item_fps_labels(self):
        """fps_label phải hiển thị đẹp: 60fps, 120fps hoặc làm tròn."""
        self.assertEqual(MediaItem(None, "T", "A", 0, "video", "u", fps=60.0).fps_label, "60fps")
        self.assertEqual(MediaItem(None, "T", "A", 0, "video", "u", fps=59.94).fps_label, "60fps")
        self.assertEqual(MediaItem(None, "T", "A", 0, "video", "u", fps=120.0).fps_label, "120fps")
        self.assertEqual(MediaItem(None, "T", "A", 0, "video", "u", fps=30.0).fps_label, "30fps")
        self.assertEqual(MediaItem(None, "T", "A", 0, "video", "u", fps=24.0).fps_label, "24fps")
        self.assertEqual(MediaItem(None, "T", "A", 0, "video", "u", fps=None).fps_label, "")


if __name__ == "__main__":
    unittest.main()
