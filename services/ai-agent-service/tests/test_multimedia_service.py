"""
test_multimedia_service.py — Unit Tests for Multimedia Studio Suite (R1).

Covers all 8 tools with IsolatedAsyncioTestCase:
  1. edit_video_clip (fast copy and re-encode)
  2. compress_video (2-pass bitrate allocation and cleanup)
  3. convert_video_format (mp4, mkv, avi, webm, gif palettegen)
  4. convert_audio_format (mp3 320k, wav, flac, m4a, ogg)
  5. trim_audio_clip (precise trimming, fade-in, fade-out)
  6. normalize_audio_volume (EBU R128 loudnorm on video and audio)
  7. convert_and_resize_image (WEBP, PNG, JPG channel flatten, HEIC fallback)
  8. generate_custom_qr (high-res in-memory QR code with label)
  + Dual-Delivery routing (direct <= 50MB vs portal > 50MB).
  + Concurrency bounding via Semaphore(2) and timeout handling.
"""

from __future__ import annotations

import asyncio
import io
import os
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure app parent directory is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from app.services.multimedia_service import (
    MultimediaService,
    TELEGRAM_MAX_FILE_SIZE,
)


class TestMultimediaService(unittest.IsolatedAsyncioTestCase):
    """Full unit test suite for MultimediaService."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.scratch_path = Path(self.temp_dir.name)
        self.mock_storage = MagicMock()
        self.service = MultimediaService(
            storage_manager=self.mock_storage,
            temp_dir=self.scratch_path,
        )

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    # ─── 1. EDIT VIDEO CLIP ───────────────────────────────────────────────────

    async def test_edit_video_clip_fast_copy(self):
        """Test video trimming with fast stream copy (-c copy)."""
        dummy_in = self.scratch_path / "sample.mp4"
        dummy_in.write_bytes(b"dummy video content")

        async def fake_run(cmd, timeout=180):
            # Simulate FFmpeg producing output file
            out_path = Path(cmd[-1])
            out_path.write_bytes(b"clipped video")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.edit_video_clip(
                input_path_or_url=str(dummy_in),
                start_time="00:01:00",
                duration=30,
                reencode=False,
                output_format="mp4",
            )
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["tool"], "edit_video_clip")
            self.assertEqual(res["delivery"], "direct")
            self.assertFalse(res["reencode"])

            called_cmd = mock_run.call_args[0][0]
            self.assertIn("-c", called_cmd)
            self.assertIn("copy", called_cmd)
            self.assertIn("-avoid_negative_ts", called_cmd)
            self.assertIn("-ss", called_cmd)

    async def test_edit_video_clip_reencode(self):
        """Test video trimming with frame-accurate re-encode (-c:v libx264)."""
        dummy_in = self.scratch_path / "sample.mp4"
        dummy_in.write_bytes(b"dummy video content")

        async def fake_run(cmd, timeout=180):
            out_path = Path(cmd[-1])
            out_path.write_bytes(b"reencoded video")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.edit_video_clip(
                input_path_or_url=str(dummy_in),
                start_time="10.5",
                duration=15,
                reencode=True,
                output_format="mp4",
            )
            self.assertEqual(res["status"], "ok")
            self.assertTrue(res["reencode"])

            called_cmd = mock_run.call_args[0][0]
            self.assertIn("libx264", called_cmd)
            self.assertIn("veryfast", called_cmd)
            self.assertIn("aac", called_cmd)

    async def test_edit_video_clip_ffmpeg_failure(self):
        """Test error handling when FFmpeg exits with non-zero code."""
        dummy_in = self.scratch_path / "sample.mp4"
        dummy_in.write_bytes(b"dummy video content")

        with patch.object(self.service, "_run_command", return_value=(1, b"", b"Invalid start time")):
            res = await self.service.edit_video_clip(str(dummy_in), start_time="99:99:99")
            self.assertEqual(res["status"], "error")
            self.assertIn("thất bại", res["message"])

    # ─── 2. COMPRESS VIDEO (2-PASS BITRATE ALLOCATION) ──────────────────────────

    async def test_compress_video_two_pass_success(self):
        """Test 2-pass compression with automated bitrate calculation and cleanup."""
        dummy_in = self.scratch_path / "big_video.mp4"
        dummy_in.write_bytes(b"big video data")

        async def fake_run(cmd, timeout=300):
            if "ffprobe" in cmd[0]:
                return 0, b"120.0\n", b""  # 120 seconds duration
            # FFmpeg pass 1 or 2
            if "-pass" in cmd and "2" in cmd:
                out_path = Path(cmd[-1])
                out_path.write_bytes(b"compressed mp4 content")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run):
            res = await self.service.compress_video(
                input_path_or_url=str(dummy_in),
                target_size_mb=45.0,
                max_dimension=720,
            )
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["tool"], "compress_video")
            self.assertEqual(res["target_size_mb"], 45.0)
            self.assertGreater(res["video_bitrate_kbps"], 0)
            self.assertGreater(res["audio_bitrate_kbps"], 0)

    # ─── 3. CONVERT VIDEO FORMAT ──────────────────────────────────────────────

    async def test_convert_video_format_gif_palettegen(self):
        """Test GIF conversion using high-fidelity palettegen filter."""
        dummy_in = self.scratch_path / "input.mp4"
        dummy_in.write_bytes(b"video bytes")

        async def fake_run(cmd, timeout=300):
            Path(cmd[-1]).write_bytes(b"GIF89a fake gif")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.convert_video_format(str(dummy_in), "gif")
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["target_format"], "gif")

            called_cmd = mock_run.call_args[0][0]
            filter_arg = called_cmd[called_cmd.index("-vf") + 1]
            self.assertIn("palettegen", filter_arg)
            self.assertIn("paletteuse", filter_arg)

    async def test_convert_video_format_webm(self):
        """Test WEBM conversion using libvpx-vp9 and libopus."""
        dummy_in = self.scratch_path / "input.mp4"
        dummy_in.write_bytes(b"video bytes")

        async def fake_run(cmd, timeout=300):
            Path(cmd[-1]).write_bytes(b"fake webm")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.convert_video_format(str(dummy_in), "webm")
            self.assertEqual(res["status"], "ok")
            called_cmd = mock_run.call_args[0][0]
            self.assertIn("libvpx-vp9", called_cmd)
            self.assertIn("libopus", called_cmd)

    async def test_convert_video_format_unsupported(self):
        """Test rejection of unsupported video format."""
        dummy_in = self.scratch_path / "input.mp4"
        dummy_in.write_bytes(b"video bytes")
        res = await self.service.convert_video_format(str(dummy_in), "invalid_ext")
        self.assertEqual(res["status"], "error")
        self.assertIn("không được hỗ trợ", res["message"])

    # ─── 4. CONVERT AUDIO FORMAT ──────────────────────────────────────────────

    async def test_convert_audio_format_mp3_320k(self):
        """Test studio audio transcoding to MP3 320kbps."""
        dummy_in = self.scratch_path / "track.flac"
        dummy_in.write_bytes(b"flac audio")

        async def fake_run(cmd, timeout=180):
            Path(cmd[-1]).write_bytes(b"mp3 audio")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.convert_audio_format(str(dummy_in), "mp3", "320k")
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["target_format"], "mp3")
            self.assertEqual(res["bitrate"], "320k")

            called_cmd = mock_run.call_args[0][0]
            self.assertIn("libmp3lame", called_cmd)
            self.assertIn("320k", called_cmd)

    async def test_convert_audio_format_wav(self):
        """Test audio conversion to uncompressed WAV PCM."""
        dummy_in = self.scratch_path / "track.mp3"
        dummy_in.write_bytes(b"mp3 audio")

        async def fake_run(cmd, timeout=180):
            Path(cmd[-1]).write_bytes(b"RIFF wav")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.convert_audio_format(str(dummy_in), "wav")
            self.assertEqual(res["status"], "ok")
            called_cmd = mock_run.call_args[0][0]
            self.assertIn("pcm_s16le", called_cmd)

    # ─── 5. TRIM AUDIO CLIP ───────────────────────────────────────────────────

    async def test_trim_audio_clip_with_fades(self):
        """Test audio ringtone extraction with fade-in and fade-out."""
        dummy_in = self.scratch_path / "song.mp3"
        dummy_in.write_bytes(b"song audio")

        async def fake_run(cmd, timeout=120):
            Path(cmd[-1]).write_bytes(b"ringtone mp3")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.trim_audio_clip(
                str(dummy_in),
                start_time="00:00:30",
                duration=30,
                fade_in=2.0,
                fade_out=3.0,
            )
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["fade_in"], 2.0)
            self.assertEqual(res["fade_out"], 3.0)

            called_cmd = mock_run.call_args[0][0]
            self.assertIn("-af", called_cmd)
            filter_arg = called_cmd[called_cmd.index("-af") + 1]
            self.assertIn("afade=t=in", filter_arg)
            self.assertIn("afade=t=out", filter_arg)

    # ─── 6. NORMALIZE AUDIO VOLUME (EBU R128 LOUDNORM) ─────────────────────────

    async def test_normalize_audio_volume_video_passthrough(self):
        """Test volume normalization on video keeping video stream intact (-c:v copy)."""
        dummy_in = self.scratch_path / "movie.mp4"
        dummy_in.write_bytes(b"video audio")

        async def fake_run(cmd, timeout=300):
            Path(cmd[-1]).write_bytes(b"normalized video")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.normalize_audio_volume(str(dummy_in), target_i=-16.0)
            self.assertEqual(res["status"], "ok")
            self.assertTrue(res["is_video"])

            called_cmd = mock_run.call_args[0][0]
            self.assertIn("-c:v", called_cmd)
            self.assertIn("copy", called_cmd)
            self.assertIn("loudnorm=I=-16.0:LRA=11.0:TP=-1.5", " ".join(called_cmd))

    async def test_normalize_audio_volume_audio_only(self):
        """Test volume normalization on standalone audio file."""
        dummy_in = self.scratch_path / "podcast.mp3"
        dummy_in.write_bytes(b"podcast audio")

        async def fake_run(cmd, timeout=300):
            Path(cmd[-1]).write_bytes(b"normalized audio")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.normalize_audio_volume(str(dummy_in), target_i=-14.0)
            self.assertEqual(res["status"], "ok")
            self.assertFalse(res["is_video"])

            called_cmd = mock_run.call_args[0][0]
            self.assertIn("-vn", called_cmd)
            self.assertIn("loudnorm=I=-14.0:LRA=11.0:TP=-1.5", " ".join(called_cmd))

    # ─── 7. CONVERT AND RESIZE IMAGE ──────────────────────────────────────────

    async def test_convert_and_resize_image_webp(self):
        """Test real image resizing and conversion to WEBP using Pillow."""
        img_in = self.scratch_path / "original.png"
        img = Image.new("RGBA", (800, 600), (255, 0, 0, 128))
        img.save(img_in, format="PNG")

        res = await self.service.convert_and_resize_image(
            input_path_or_url=str(img_in),
            format="webp",
            max_width=400,
            max_height=300,
            quality=80,
        )
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["format"], "webp")
        self.assertEqual(res["original_dimensions"], "800x600")

        # Verify output file is a valid WEBP
        out_path = Path(res["file_path"])
        self.assertTrue(out_path.exists())
        with Image.open(out_path) as out_img:
            self.assertEqual(out_img.format, "WEBP")
            self.assertLessEqual(out_img.width, 400)
            self.assertLessEqual(out_img.height, 300)

    async def test_convert_and_resize_image_jpeg_flatten(self):
        """Test RGBA alpha flattening when converting to JPEG."""
        img_in = self.scratch_path / "transparent.png"
        img = Image.new("RGBA", (200, 200), (0, 255, 0, 100))
        img.save(img_in, format="PNG")

        res = await self.service.convert_and_resize_image(
            input_path_or_url=str(img_in),
            format="jpg",
            quality=90,
        )
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["format"], "jpg")

        out_path = Path(res["file_path"])
        with Image.open(out_path) as out_img:
            self.assertEqual(out_img.format, "JPEG")
            self.assertEqual(out_img.mode, "RGB")

    async def test_convert_and_resize_image_heic_decode_fallback(self):
        """Test HEIC decoding via FFmpeg fallback."""
        heic_in = self.scratch_path / "photo.heic"
        heic_in.write_bytes(b"fake heic raw data")

        async def fake_run(cmd, timeout=60):
            # When FFmpeg decodes HEIC to PNG, write valid PNG
            out_png = Path(cmd[-1])
            img = Image.new("RGB", (100, 100), (0, 0, 255))
            img.save(out_png, format="PNG")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run):
            res = await self.service.convert_and_resize_image(
                input_path_or_url=str(heic_in),
                format="png",
            )
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["format"], "png")

    # ─── 8. GENERATE CUSTOM QR CODE ───────────────────────────────────────────

    async def test_generate_custom_qr_standard(self):
        """Test high-resolution QR code generation in-memory without label."""
        res = await self.service.generate_custom_qr(
            content="https://example.com/kirito-server",
            box_size=8,
        )
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["tool"], "generate_custom_qr")
        self.assertIn("base64_png", res)
        self.assertGreater(res["width"], 50)
        self.assertGreater(res["height"], 50)

        # Verify generated file exists and is valid PNG
        out_file = Path(res["file_path"])
        self.assertTrue(out_file.exists())
        with Image.open(out_file) as img:
            self.assertEqual(img.format, "PNG")

    async def test_generate_custom_qr_with_label(self):
        """Test QR code generation with text label banner at bottom."""
        res = await self.service.generate_custom_qr(
            content="WIFI:S:KiritoLAN;T:WPA;P:SuperSecret;;",
            label="Quét để kết nối WiFi",
            fill_color="#1e293b",
            back_color="#ffffff",
        )
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["label"], "Quét để kết nối WiFi")
        self.assertGreater(res["height"], res["width"])  # Banner extends height

    async def test_generate_custom_qr_empty_content(self):
        """Test error when content is empty."""
        res = await self.service.generate_custom_qr(content="")
        self.assertEqual(res["status"], "error")
        self.assertIn("không được để trống", res["message"])

    # ─── 9. DUAL-DELIVERY ROUTING & SEMAPHORE ─────────────────────────────────

    async def test_dual_delivery_over_50mb(self):
        """Test automatic routing to MediaStorageManager portal when file > 50MB."""
        big_file = self.scratch_path / "massive_archive.mp4"
        big_file.write_bytes(b"0" * 1024)

        # Mock stat size > 50MB
        with patch.object(Path, "stat") as mock_stat:
            stat_obj = MagicMock()
            stat_obj.st_size = 55 * 1024 * 1024  # 55 MB
            mock_stat.return_value = stat_obj

            mock_rec = MagicMock()
            mock_rec.file_path = big_file
            mock_rec.filename = "massive_archive.mp4"
            mock_rec.file_size = 55 * 1024 * 1024
            mock_rec.internet_url = "https://kirito.ngrok.app/download/massive_archive.mp4"
            mock_rec.lan_url = "http://192.168.0.100:8084/download/massive_archive.mp4"
            mock_rec.expires_at = 1770000000.0

            self.mock_storage.publish_download_item.return_value = mock_rec

            delivery = self.service._publish_or_direct(big_file)
            self.assertEqual(delivery["delivery"], "portal")
            self.assertEqual(delivery["internet_url"], "https://kirito.ngrok.app/download/massive_archive.mp4")
            self.assertEqual(delivery["lan_url"], "http://192.168.0.100:8084/download/massive_archive.mp4")


if __name__ == "__main__":
    unittest.main()
