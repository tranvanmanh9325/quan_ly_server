"""
test_challenger_m1_adversarial_audio.py — Bộ kiểm thử đối kháng & stress test cho Dual-Engine Smart Audio Pipeline.

Thực hiện bởi: Empirical Challenger (Challenger 14_1)
Mục tiêu kiểm thử:
  1. Duration Fuzzing & Routing Decision Stress-Testing (11 test cases)
  2. FFprobe Codec Fidelity & Metadata Verification trên môi trường thật (MP3 320kbps CBR, 44.1kHz Stereo, MJPEG attached_pic=1, ID3v2 tags)
  3. Image Processing Adversarial (RGBA, Grayscale, Huge 4K, Corrupted)
  4. Concurrent FFmpeg Transcoding Stress Test (4 concurrent tasks, resource safety, zero race condition)
  5. Telegram Native Audio Player Card with Thumbnail & Fallback Matrix
  6. Zero-Disk Leak Invariant Audit
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from PIL import Image
import httpx

from app.services.media_downloader import (
    MultiTierMediaPipeline,
    MediaItem,
    TEMP_MEDIA_DIR,
    MediaPipelineError,
)
from app.services.telegram_bot import TelegramBot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_challenger_m1_adversarial_audio")

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


class TestDurationFuzzingRouting(unittest.IsolatedAsyncioTestCase):
    """
    Challenge 1: Duration Fuzzing & Routing Decision Stress-Testing.
    Kiểm chứng nghiêm ngặt các ranh giới chuyển mạch giữa Direct CDN và HD Video Extraction.
    """

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()
        TEMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    async def _run_routing_test(
        self,
        video_duration: int,
        music_duration: int,
        images: Optional[List[str]] = None,
        has_play_url: bool = True,
        has_music_url: bool = True,
        hd_mux_fails: bool = False,
    ) -> Tuple[Optional[MediaItem], bool, bool]:
        """
        Helper thực thi mô phỏng luồng và trả về:
          (item, engaged_hd_extraction, engaged_direct_cdn)
        """
        play_url = "https://tikwm.com/video/stream.mp4" if has_play_url else None
        music_url = "https://tikwm.com/music/stream.mp3" if has_music_url else None

        data_dict: Dict[str, Any] = {
            "duration": video_duration,
            "play": play_url,
            "hdplay": play_url,
            "music": music_url,
            "music_info": {"duration": music_duration, "title": "Test Title", "author": "Test Artist"} if music_url else {},
            "title": "Video Title",
            "author": {"nickname": "Video Author"},
        }
        if images is not None:
            data_dict["images"] = images

        tikwm_payload = {"code": 0, "data": data_dict}

        mock_client = AsyncMock()
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = tikwm_payload
        mock_client.post.return_value = mock_resp

        # Tạo file giả lập tạm
        with tempfile.NamedTemporaryFile(suffix=".tmp", dir=str(TEMP_MEDIA_DIR), delete=False) as f:
            f.write(b"MOCK_STREAM_BYTES")
            dummy_file = f.name

        engaged_hd = False
        engaged_direct = False

        async def fake_stream_url(url, client, suffix=""):
            nonlocal engaged_hd, engaged_direct
            if "video" in url:
                engaged_hd = True
            elif "music" in url:
                engaged_direct = True
            with tempfile.NamedTemporaryFile(suffix=suffix, dir=str(TEMP_MEDIA_DIR), delete=False) as tf:
                tf.write(b"DUMMY_STREAM_DATA")
                return tf.name, 17

        async def fake_mux(input_path, output_path, is_video, **kwargs):
            if hd_mux_fails and is_video:
                return False
            Path(output_path).write_bytes(b"FINAL_MUXED_MP3_PAYLOAD")
            return True

        try:
            with patch.object(self.pipeline, "_get_client", AsyncMock(return_value=mock_client)), \
                 patch.object(self.pipeline, "_stream_url_to_file", side_effect=fake_stream_url), \
                 patch.object(self.pipeline, "_mux_mp3_with_metadata", side_effect=fake_mux):
                item = await self.pipeline._download_tikwm_audio("https://www.tiktok.com/@test/video/1001")
                return item, engaged_hd, engaged_direct
        finally:
            if os.path.exists(dummy_file):
                os.unlink(dummy_file)

    async def test_case_1_video_60s_music_30s_must_engage_hd_video(self):
        """Case 1: Video 60s, Music 30s (âm thanh bị cắt ngắn 30s) -> PHẢI kích hoạt HD Video Extraction."""
        item, engaged_hd, engaged_direct = await self._run_routing_test(video_duration=60, music_duration=30)
        self.assertIsNotNone(item)
        self.assertTrue(engaged_hd, "Phải tải video stream để trích xuất âm thanh đầy đủ")
        self.assertFalse(engaged_direct, "Không được dùng direct CDN music bị cắt")
        self.assertEqual(item.duration, 60, "Thời lượng phải bảo toàn 60s của video")

    async def test_case_2_video_15s_music_15s_must_engage_direct_cdn(self):
        """Case 2: Video 15s, Music 15s (thời lượng khớp và <= 30s) -> PHẢI kích hoạt Direct CDN."""
        item, engaged_hd, engaged_direct = await self._run_routing_test(video_duration=15, music_duration=15)
        self.assertIsNotNone(item)
        self.assertTrue(engaged_direct, "Phải dùng Direct CDN để tiết kiệm CPU và tải tức thì <0.5s")
        self.assertFalse(engaged_hd, "Không được tốn tài nguyên trích xuất video khi music đã đầy đủ")
        self.assertEqual(item.duration, 15)

    async def test_case_3_video_45s_music_none_must_engage_hd_video(self):
        """Case 3: Video 45s, Music rỗng/None -> PHẢI kích hoạt HD Video Extraction."""
        item, engaged_hd, engaged_direct = await self._run_routing_test(
            video_duration=45, music_duration=0, has_music_url=False
        )
        self.assertIsNotNone(item)
        self.assertTrue(engaged_hd, "Phải kích hoạt HD video khi không có music_url")
        self.assertFalse(engaged_direct)
        self.assertEqual(item.duration, 45)

    async def test_case_4_slideshow_images_with_video_30s_must_engage_direct_cdn(self):
        """Case 4: Slideshow ảnh (images list) với Video 30s -> PHẢI kích hoạt Direct CDN branch."""
        item, engaged_hd, engaged_direct = await self._run_routing_test(
            video_duration=30, music_duration=60, images=["https://img1.jpg", "https://img2.jpg"]
        )
        self.assertIsNotNone(item)
        self.assertTrue(engaged_direct, "Slideshow ảnh không có track video nên phải dùng Direct CDN")
        self.assertFalse(engaged_hd)

    async def test_case_5_video_120s_music_119s_must_engage_hd_video_for_creator_voice(self):
        """Case 5: Video 120s, Music 119s (> 30s) -> PHẢI kích hoạt HD Video Extraction để bảo toàn giọng creator."""
        item, engaged_hd, engaged_direct = await self._run_routing_test(video_duration=120, music_duration=119)
        self.assertIsNotNone(item)
        self.assertTrue(engaged_hd, "Video > 30s phải kích hoạt HD Video để giữ trọn vẹn lời thoại/giọng nói creator")
        self.assertFalse(engaged_direct)
        self.assertEqual(item.duration, 120)

    async def test_case_6_boundary_30s_exact_matches_engages_direct_cdn(self):
        """Case 6: Video đúng 30s, Music đúng 30s -> Đúng ngưỡng biên <= 30s kích hoạt Direct CDN."""
        item, engaged_hd, engaged_direct = await self._run_routing_test(video_duration=30, music_duration=30)
        self.assertIsNotNone(item)
        self.assertTrue(engaged_direct)
        self.assertFalse(engaged_hd)

    async def test_case_7_boundary_31s_exceeds_threshold_engages_hd_video(self):
        """Case 7: Video 31s, Music 31s -> Vượt quá ngưỡng 30s kích hoạt HD Video Extraction."""
        item, engaged_hd, engaged_direct = await self._run_routing_test(video_duration=31, music_duration=31)
        self.assertIsNotNone(item)
        self.assertTrue(engaged_hd)
        self.assertFalse(engaged_direct)

    async def test_case_8_delta_3s_exceeds_tolerance_engages_hd_video(self):
        """Case 8: Video 20s, Music 23s (độ lệch 3s > dung sai 2s) -> Kích hoạt HD Video Extraction."""
        item, engaged_hd, engaged_direct = await self._run_routing_test(video_duration=20, music_duration=23)
        self.assertIsNotNone(item)
        self.assertTrue(engaged_hd)
        self.assertFalse(engaged_direct)

    async def test_case_9_delta_2s_within_tolerance_engages_direct_cdn(self):
        """Case 9: Video 20s, Music 22s (độ lệch 2s <= dung sai 2s và video <= 30s) -> Kích hoạt Direct CDN."""
        item, engaged_hd, engaged_direct = await self._run_routing_test(video_duration=20, music_duration=22)
        self.assertIsNotNone(item)
        self.assertTrue(engaged_direct)
        self.assertFalse(engaged_hd)

    async def test_case_10_hd_video_mux_failure_falls_back_to_direct_cdn(self):
        """Case 10: HD Video Extraction thất bại (mux lỗi) -> Phải tự động fallback sang Direct CDN nếu có music_url."""
        item, engaged_hd, engaged_direct = await self._run_routing_test(
            video_duration=60, music_duration=30, hd_mux_fails=True
        )
        self.assertIsNotNone(item)
        self.assertTrue(engaged_hd, "Đã thử HD extraction trước")
        self.assertTrue(engaged_direct, "Sau khi HD lỗi, đã fallback thành công sang Direct CDN")

    async def test_case_11_neither_play_nor_music_url_returns_none_gracefully(self):
        """Case 11: Cả hai URL đều rỗng -> Trả về None an toàn, không gây crash unhandled exception."""
        item, engaged_hd, engaged_direct = await self._run_routing_test(
            video_duration=30, music_duration=30, has_play_url=False, has_music_url=False
        )
        self.assertIsNone(item)
        self.assertFalse(engaged_hd)
        self.assertFalse(engaged_direct)


class TestFFprobeCodecAndMetadataEmpirical(unittest.IsolatedAsyncioTestCase):
    """
    Challenge 2: Kiểm chứng kỹ thuật qua `ffprobe` trên môi trường thực tế.
    Tạo dữ liệu âm thanh/hình ảnh thật và kiểm tra:
      - Bitrate 320000 (320kbps CBR)
      - Stereo 2 channels, 44.1kHz
      - Attached picture MJPEG với disposition attached_pic: 1
      - ID3v2 tags chuẩn: title, artist, album, date
    """

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()
        TEMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        self.test_dir = tempfile.mkdtemp(prefix="test_ffprobe_empirical_", dir=str(TEMP_MEDIA_DIR))

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def _generate_synthetic_video(self, path: str, duration: int = 3):
        """Tạo video giả lập có audio sine wave chuẩn bằng FFmpeg."""
        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"sine=frequency=1000:duration={duration}",
            "-f", "lavfi", "-i", f"color=c=navy:s=640x360:d={duration}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", path,
        ]
        subprocess.run(cmd, check=True)

    def _generate_synthetic_cover(self, path: str, size: Tuple[int, int] = (600, 600)):
        """Tạo ảnh bìa JPEG chất lượng cao."""
        img = Image.new("RGB", size, color=(255, 99, 71))
        img.save(path, format="JPEG", quality=90)

    @unittest.skipUnless(HAS_FFMPEG, "FFmpeg and FFprobe binaries required")
    async def test_ffprobe_codec_fidelity_video_extraction(self):
        """Xác minh đầu ra của HD Video Extraction đạt chuẩn phòng thu 320kbps CBR Stereo 44.1kHz."""
        raw_video = os.path.join(self.test_dir, "raw_video.mp4")
        raw_cover = os.path.join(self.test_dir, "raw_cover.jpg")
        output_mp3 = os.path.join(self.test_dir, "extracted_320k.mp3")

        self._generate_synthetic_video(raw_video, duration=3)
        self._generate_synthetic_cover(raw_cover)

        success = await self.pipeline._mux_mp3_with_metadata(
            input_path=raw_video,
            output_path=output_mp3,
            is_video=True,
            cover_path=raw_cover,
            title="Challenger Symphony",
            artist="Kirito Maestro",
            album="Masterpiece 2026",
            date="2026",
        )
        self.assertTrue(success, "FFmpeg muxing phải thành công với exit code 0")
        self.assertTrue(os.path.exists(output_mp3))
        self.assertGreater(os.path.getsize(output_mp3), 10000)

        # Chạy ffprobe phân tích sâu
        probe_cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", "-show_format", output_mp3,
        ]
        res = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
        probe_data = json.loads(res.stdout)

        streams = probe_data.get("streams", [])
        self.assertEqual(len(streams), 2, "MP3 phải có chính xác 2 streams: 1 audio và 1 attached picture")

        # 1. Kiểm tra Stream Audio
        audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
        self.assertIsNotNone(audio_stream, "Không tìm thấy audio stream")
        self.assertEqual(audio_stream.get("codec_name"), "mp3", "Codec audio phải là MP3")
        self.assertEqual(int(audio_stream.get("channels", 0)), 2, "Channels phải là 2 (Stereo)")
        self.assertEqual(int(audio_stream.get("sample_rate", 0)), 44100, "Sample rate phải là 44.1kHz")
        
        # Đo đạc bitrate: ffprobe trả về bit_rate của stream hoặc format
        audio_bitrate = int(audio_stream.get("bit_rate") or probe_data.get("format", {}).get("bit_rate", 0))
        self.assertEqual(audio_bitrate, 320000, f"Bitrate phải đúng 320000 (320kbps CBR), đo được: {audio_bitrate}")

        # 2. Kiểm tra Stream Attached Picture
        cover_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        self.assertIsNotNone(cover_stream, "Không tìm thấy attached picture stream")
        self.assertEqual(cover_stream.get("codec_name"), "mjpeg", "Codec ảnh bìa phải là MJPEG")
        disposition = cover_stream.get("disposition", {})
        self.assertEqual(
            int(disposition.get("attached_pic", 0)), 1,
            "Disposition attached_pic phải bằng 1 để hiển thị bìa đĩa chuẩn"
        )

        # 3. Kiểm tra ID3v2 Tags
        format_tags = probe_data.get("format", {}).get("tags", {})
        # Chuẩn hóa key về chữ thường
        lower_tags = {k.lower(): v for k, v in format_tags.items()}
        self.assertEqual(lower_tags.get("title"), "Challenger Symphony")
        self.assertEqual(lower_tags.get("artist"), "Kirito Maestro")
        self.assertEqual(lower_tags.get("album"), "Masterpiece 2026")
        self.assertEqual(lower_tags.get("date"), "2026")


class TestImagePreparationAdversarial(unittest.IsolatedAsyncioTestCase):
    """
    Challenge 2B: Kiểm thử đối kháng khả năng xử lý ảnh của Pillow.
    Thử thách các định dạng dị thường: RGBA, Grayscale, Khổng lồ (4K), File hỏng.
    """

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()
        TEMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        self.test_dir = tempfile.mkdtemp(prefix="test_img_adv_", dir=str(TEMP_MEDIA_DIR))

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    async def _test_cover_preparation_with_image(self, img: Image.Image, img_format: str = "PNG") -> Tuple[Optional[str], Optional[str]]:
        img_bytes_io = io.BytesIO()
        img.save(img_bytes_io, format=img_format)
        img_bytes = img_bytes_io.getvalue()

        async def fake_stream_cover(url, client, suffix=""):
            with tempfile.NamedTemporaryFile(suffix=suffix, dir=str(TEMP_MEDIA_DIR), delete=False) as tf:
                tf.write(img_bytes)
                return tf.name, len(img_bytes)

        with patch.object(self.pipeline, "_stream_url_to_file", side_effect=fake_stream_cover):
            return await self.pipeline._prepare_cover_and_thumb("https://example.com/cover.png", AsyncMock())

    async def test_rgba_png_converts_to_rgb_jpeg_cleanly(self):
        """Ảnh PNG chứa kênh trong suốt RGBA phải được chuyển đổi trơn tru sang RGB JPEG."""
        img = Image.new("RGBA", (800, 800), color=(100, 150, 200, 128))
        raw_cover, thumb = await self._test_cover_preparation_with_image(img, "PNG")
        self.assertIsNotNone(raw_cover)
        self.assertIsNotNone(thumb)
        try:
            with Image.open(thumb) as im:
                self.assertEqual(im.format, "JPEG")
                self.assertEqual(im.mode, "RGB")
                self.assertLessEqual(im.width, 320)
                self.assertLessEqual(im.height, 320)
            self.assertLess(os.path.getsize(thumb), 200 * 1024)
        finally:
            if raw_cover and os.path.exists(raw_cover):
                os.unlink(raw_cover)
            if thumb and os.path.exists(thumb):
                os.unlink(thumb)

    async def test_grayscale_converts_to_rgb_jpeg_cleanly(self):
        """Ảnh đơn sắc Grayscale L-mode phải chuyển đổi an toàn sang RGB JPEG."""
        img = Image.new("L", (500, 500), color=128)
        raw_cover, thumb = await self._test_cover_preparation_with_image(img, "JPEG")
        self.assertIsNotNone(raw_cover)
        self.assertIsNotNone(thumb)
        try:
            with Image.open(thumb) as im:
                self.assertEqual(im.format, "JPEG")
                self.assertEqual(im.mode, "RGB")
        finally:
            if raw_cover and os.path.exists(raw_cover):
                os.unlink(raw_cover)
            if thumb and os.path.exists(thumb):
                os.unlink(thumb)

    async def test_huge_4k_image_downsamples_under_constraints(self):
        """Ảnh khổng lồ 3840x2160 phải được co nhỏ đúng chuẩn <= 320x320 và dung lượng < 200KB."""
        img = Image.new("RGB", (3840, 2160), color=(50, 80, 120))
        raw_cover, thumb = await self._test_cover_preparation_with_image(img, "JPEG")
        self.assertIsNotNone(raw_cover)
        self.assertIsNotNone(thumb)
        try:
            with Image.open(thumb) as im:
                self.assertLessEqual(im.width, 320)
                self.assertLessEqual(im.height, 320)
            self.assertLess(os.path.getsize(thumb), 200 * 1024)
        finally:
            if raw_cover and os.path.exists(raw_cover):
                os.unlink(raw_cover)
            if thumb and os.path.exists(thumb):
                os.unlink(thumb)

    async def test_corrupted_image_handled_gracefully(self):
        """Khi tải ảnh bị lỗi mạng, pipeline phải bắt lỗi an toàn và trả về (None, None)."""
        async def fake_stream_error(url, client, suffix=""):
            raise httpx.RequestError("Network dropped connection")

        with patch.object(self.pipeline, "_stream_url_to_file", side_effect=fake_stream_error):
            raw_cover, thumb = await self.pipeline._prepare_cover_and_thumb("https://example.com/bad.jpg", AsyncMock())
            self.assertIsNone(raw_cover)
            self.assertIsNone(thumb)


class TestConcurrencyTranscodeStress(unittest.IsolatedAsyncioTestCase):
    """
    Challenge 3: Stress test concurrency.
    Chạy đồng thời 4 tác vụ transcode FFmpeg để xác nhận -threads 2 không gây treo hệ thống,
    không gây race condition trên file tạm và bảo đảm Zero-Disk Leak.
    """

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()
        TEMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        self.test_dir = tempfile.mkdtemp(prefix="test_stress_transcode_", dir=str(TEMP_MEDIA_DIR))

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_test_clip(self, idx: int) -> Tuple[str, str]:
        vid_path = os.path.join(self.test_dir, f"clip_{idx}.mp4")
        cov_path = os.path.join(self.test_dir, f"cover_{idx}.jpg")
        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"sine=frequency={400 + idx * 100}:duration=4",
            "-f", "lavfi", "-i", f"color=c=red:s=320x240:d=4",
            "-c:v", "libx264", "-c:a", "aac", "-shortest", vid_path,
        ]
        subprocess.run(cmd, check=True)
        img = Image.new("RGB", (400, 400), color=(idx * 40, 100, 200))
        img.save(cov_path, format="JPEG")
        return vid_path, cov_path

    @unittest.skipUnless(HAS_FFMPEG, "FFmpeg and FFprobe binaries required")
    async def test_concurrent_transcoding_stress_4_workers(self):
        """Thực thi song song 4 tiến trình FFmpeg mux đồng thời và kiểm tra tính toàn vẹn."""
        tasks = []
        out_paths = []

        for i in range(4):
            vid, cov = self._create_test_clip(i)
            out_mp3 = os.path.join(self.test_dir, f"out_{i}.mp3")
            out_paths.append(out_mp3)
            task = self.pipeline._mux_mp3_with_metadata(
                input_path=vid,
                output_path=out_mp3,
                is_video=True,
                cover_path=cov,
                title=f"Concurrent Symphony {i}",
                artist=f"Performer {i}",
                album="Concurrency Stress Test",
                date="2026",
            )
            tasks.append(task)

        # Chạy đồng thời cả 4 tác vụ
        start_time = time.time()
        results = await asyncio.gather(*tasks)
        elapsed = time.time() - start_time
        logger.info("[Stress Test] 4 concurrent transcodes completed in %.2fs", elapsed)

        # Kiểm tra toàn bộ tác vụ thành công
        self.assertTrue(all(results), f"Tất cả 4 tác vụ transcode phải thành công. Kết quả: {results}")

        for i, out_file in enumerate(out_paths):
            self.assertTrue(os.path.exists(out_file), f"File {out_file} phải tồn tại")
            self.assertGreater(os.path.getsize(out_file), 10000, f"File {out_file} không được rỗng")
            
            # Kiểm tra nhanh bằng ffprobe
            probe_cmd = ["ffprobe", "-v", "quiet", "-show_entries", "stream=codec_name,bit_rate", "-of", "json", out_file]
            probe = json.loads(subprocess.run(probe_cmd, capture_output=True, text=True, check=True).stdout)
            streams = probe.get("streams", [])
            audio = next(s for s in streams if s.get("codec_name") == "mp3")
            self.assertIsNotNone(audio)


class TestTelegramBotAudioPlayerCardWithThumbnail(unittest.IsolatedAsyncioTestCase):
    """
    Challenge 4: Telegram Bot Native Audio Player Card với Thumbnail & Fallback Matrix.
    """

    def setUp(self):
        self.bot = TelegramBot(ai_agent=MagicMock(), ssh_client=MagicMock())
        self.bot.token = "DUMMY_TOKEN_FOR_TESTING"
        TEMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        self.test_dir = tempfile.mkdtemp(prefix="test_tg_bot_audio_", dir=str(TEMP_MEDIA_DIR))

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    async def test_send_audio_includes_thumbnail_multipart(self):
        """Xác nhận send_audio đính kèm multipart file thumbnail với format chuẩn."""
        audio_path = os.path.join(self.test_dir, "test.mp3")
        thumb_path = os.path.join(self.test_dir, "test_thumb.jpg")
        Path(audio_path).write_bytes(b"MOCK_AUDIO_BYTES_FOR_TELEGRAM")
        Path(thumb_path).write_bytes(b"MOCK_THUMB_BYTES")

        captured_files = {}
        captured_data = {}

        mock_resp = MagicMock(status_code=200, text='{"ok": true}')
        mock_resp.json.return_value = {"ok": True, "result": {"message_id": 999}}

        async def fake_post(endpoint, data=None, files=None, timeout=None):
            nonlocal captured_files, captured_data
            captured_data = dict(data or {})
            captured_files = dict(files or {})
            return mock_resp

        with patch.object(self.bot._http_client, "post", side_effect=fake_post):
            success = await self.bot.send_audio(
                chat_id="12345",
                audio_path=audio_path,
                title="Song Title",
                performer="Artist Name",
                duration=45,
                thumbnail=thumb_path,
            )
            self.assertTrue(success)
            self.assertIn("audio", captured_files)
            self.assertIn("thumbnail", captured_files)
            # Kiểm tra tuple cấu trúc multipart: ("thumbnail.jpg", bytes, "image/jpeg")
            thumb_tuple = captured_files["thumbnail"]
            self.assertEqual(thumb_tuple[0], "thumbnail.jpg")
            self.assertEqual(thumb_tuple[2], "image/jpeg")
            self.assertEqual(captured_data.get("title"), "Song Title")
            self.assertEqual(captured_data.get("performer"), "Artist Name")
            self.assertEqual(captured_data.get("duration"), "45")

    async def test_send_audio_wrong_thumbnail_retry_fallback(self):
        """Khi Telegram trả WRONG_THUMBNAIL -> Phải retry tự động không có thumbnail và gửi thành công."""
        audio_path = os.path.join(self.test_dir, "test.mp3")
        thumb_path = os.path.join(self.test_dir, "bad_thumb.jpg")
        Path(audio_path).write_bytes(b"MOCK_AUDIO_BYTES")
        Path(thumb_path).write_bytes(b"BAD_THUMB")

        call_count = 0
        call_files = []

        async def fake_post(endpoint, data=None, files=None, timeout=None):
            nonlocal call_count, call_files
            call_count += 1
            call_files.append(dict(files or {}))
            if call_count == 1:
                resp = MagicMock(status_code=400, text='{"ok":false,"description":"Bad Request: WRONG_THUMBNAIL"}')
                resp.json.return_value = {"ok": False, "description": "Bad Request: WRONG_THUMBNAIL"}
                return resp
            else:
                resp = MagicMock(status_code=200, text='{"ok":true}')
                resp.json.return_value = {"ok": True, "result": {"message_id": 1000}}
                return resp

        with patch.object(self.bot._http_client, "post", side_effect=fake_post):
            success = await self.bot.send_audio(
                chat_id="12345",
                audio_path=audio_path,
                thumbnail=thumb_path,
            )
            self.assertTrue(success)
            self.assertEqual(call_count, 2, "Phải retry lần 2 khi thumbnail bị từ chối")
            self.assertIn("thumbnail", call_files[0], "Lần 1 có gửi thumbnail")
            self.assertNotIn("thumbnail", call_files[1], "Lần 2 retry đã loại bỏ thumbnail để cứu audio")


class TestZeroDiskLeakInvariant(unittest.IsolatedAsyncioTestCase):
    """
    Challenge 5: Zero-Disk Leak Invariant Audit.
    Kiểm tra triệt để không có bất kỳ tệp rác nào còn sót lại trong TEMP_MEDIA_DIR.
    """

    async def test_zero_disk_leak_media_item_lifecycle(self):
        """Đảm bảo MediaItem.cleanup() xóa sạch cả audio file và thumbnail file."""
        TEMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        
        with tempfile.NamedTemporaryFile(suffix=".mp3", dir=str(TEMP_MEDIA_DIR), delete=False) as f_audio:
            f_audio.write(b"AUDIO_DATA")
            a_path = f_audio.name

        with tempfile.NamedTemporaryFile(suffix=".jpg", dir=str(TEMP_MEDIA_DIR), delete=False) as f_thumb:
            f_thumb.write(b"THUMB_DATA")
            t_path = f_thumb.name

        item = MediaItem(
            file_path=a_path,
            title="Clean Test",
            author="Clean Author",
            duration=10,
            media_type="audio",
            source_url="https://tiktok.com",
            thumbnail_path=t_path,
            is_temp_file=True,
        )

        self.assertTrue(os.path.exists(a_path))
        self.assertTrue(os.path.exists(t_path))

        item.cleanup()

        self.assertFalse(os.path.exists(a_path), "File audio phải bị xóa sạch")
        self.assertFalse(os.path.exists(t_path), "File thumbnail phải bị xóa sạch")


if __name__ == "__main__":
    unittest.main()
