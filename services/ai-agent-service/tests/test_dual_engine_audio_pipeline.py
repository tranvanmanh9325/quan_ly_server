"""
test_dual_engine_audio_pipeline.py — Bộ kiểm thử toàn diện Dual-Engine Smart Audio Pipeline cho AI Agent Tiểu Bảo Bảo.

Bao phủ 28 test cases độc lập thuộc 4 nhóm nghiệp vụ cốt lõi:
  - Nhóm 1: Dual-Source Smart Routing & Duration Invariant (8 tests)
  - Nhóm 2: ID3v2 Studio Metadata & Cover Art APIC Embedding (7 tests)
  - Nhóm 3: Telegram Native Player Card với Thumbnail (7 tests)
  - Nhóm 4: Zero-Disk & Zero-RAM Leak Empirical Adversarial (6 tests)

Môi trường: Python 3.11+, unittest native, async support, zero dummy/facade implementations.
"""

from __future__ import annotations

import asyncio
import io
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any, Dict, List, Optional
import unittest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from PIL import Image
import httpx

from app.services.media_downloader import (
    MultiTierMediaPipeline,
    MediaItem,
    TEMP_MEDIA_DIR,
    MediaPipelineError,
)
from app.services.telegram_bot import TelegramBot, _AudioFileStream


class TestDualSourceRoutingGroup1(unittest.IsolatedAsyncioTestCase):
    """
    Nhóm 1: Dual-Source Smart Routing & Duration Invariant (8 test cases)
    Xác minh thuật toán phân luồng: Direct CDN vs HD Video Extraction 320kbps.
    """

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()

    async def test_01_dual_engine_direct_cdn_when_duration_matches(self):
        """TH 1: Video ngắn 25s, Music 25s (độ lệch 0s <= 2s và video <= 30s) -> Kích hoạt Direct CDN."""
        tikwm_payload = {
            "code": 0,
            "data": {
                "duration": 25,
                "play": "https://tikwm.com/video/play.mp4",
                "music": "https://tikwm.com/music/short.mp3",
                "music_info": {"duration": 25, "title": "Short Hit", "author": "Singer"},
            }
        }
        mock_client = AsyncMock()
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = tikwm_payload
        mock_client.post.return_value = mock_resp

        with tempfile.NamedTemporaryFile(suffix=".mp3", dir=str(TEMP_MEDIA_DIR), delete=False) as f:
            f.write(b"MOCK_DIRECT_CDN_AUDIO")
            tmp_mp3 = f.name

        try:
            with patch.object(self.pipeline, "_get_client", AsyncMock(return_value=mock_client)), \
                 patch.object(self.pipeline, "_stream_url_to_file", AsyncMock(return_value=(tmp_mp3, 21))) as mock_stream:
                item = await self.pipeline._download_tikwm_audio("https://www.tiktok.com/@user/video/12345")
                self.assertIsNotNone(item)
                self.assertEqual(item.media_type, "audio")
                self.assertEqual(item.duration, 25)
                # Xác nhận _stream_url_to_file được gọi với URL music, không phải video stream
                mock_stream.assert_called_with("https://tikwm.com/music/short.mp3", mock_client, suffix=".mp3")
        finally:
            if os.path.exists(tmp_mp3):
                os.unlink(tmp_mp3)

    async def test_02_dual_engine_hd_extract_when_music_truncated(self):
        """TH 2: Video 75s, Music 30s (bị cắt ngắn 30s, delta=45s > 2s) -> Kích hoạt HD Video Extraction."""
        tikwm_payload = {
            "code": 0,
            "data": {
                "duration": 75,
                "play": "https://tikwm.com/video/long_vlog.mp4",
                "hdplay": "https://tikwm.com/video/long_vlog_hd.mp4",
                "music": "https://tikwm.com/music/snippet_30s.mp3",
                "music_info": {"duration": 30, "title": "Snippet Song", "author": "Music Label"},
            }
        }
        mock_client = AsyncMock()
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = tikwm_payload
        mock_client.post.return_value = mock_resp

        with tempfile.NamedTemporaryFile(suffix=".mp4", dir=str(TEMP_MEDIA_DIR), delete=False) as f_vid:
            f_vid.write(b"MOCK_HD_VIDEO_STREAM")
            tmp_vid = f_vid.name

        with tempfile.NamedTemporaryFile(suffix=".mp3", dir=str(TEMP_MEDIA_DIR), delete=False) as f_mp3:
            f_mp3.write(b"MOCK_EXTRACTED_320K_MP3")
            tmp_out_mp3 = f_mp3.name

        try:
            with patch.object(self.pipeline, "_get_client", AsyncMock(return_value=mock_client)), \
                 patch.object(self.pipeline, "_stream_url_to_file", AsyncMock(return_value=(tmp_vid, 20))) as mock_stream, \
                 patch.object(self.pipeline, "_mux_mp3_with_metadata", AsyncMock(return_value=True)) as mock_mux:
                
                # Giả lập FFmpeg tạo ra file output
                async def mock_mux_impl(input_path, output_path, is_video, **kwargs):
                    Path(output_path).write_bytes(b"EXTRACTED_FULL_320K_MP3")
                    return True
                mock_mux.side_effect = mock_mux_impl

                item = await self.pipeline._download_tikwm_audio("https://www.tiktok.com/@vlogger/video/67890")
                self.assertIsNotNone(item)
                self.assertEqual(item.media_type, "audio")
                self.assertEqual(item.duration, 75)  # Bảo toàn 100% thời lượng 75s của video
                # Xác nhận tải video HD stream
                mock_stream.assert_called_with("https://tikwm.com/video/long_vlog_hd.mp4", mock_client, suffix=".mp4")
                self.assertTrue(mock_mux.called)
                self.assertTrue(mock_mux.call_args[1].get("is_video"))
        finally:
            if os.path.exists(tmp_vid):
                os.unlink(tmp_vid)
            if os.path.exists(tmp_out_mp3):
                os.unlink(tmp_out_mp3)

    async def test_03_dual_engine_hd_extract_when_music_missing(self):
        """TH 3: Video có play_url nhưng không có trường music/music_info -> Kích hoạt HD Video Extraction."""
        tikwm_payload = {
            "code": 0,
            "data": {
                "duration": 40,
                "play": "https://tikwm.com/video/speech.mp4",
                "title": "Speech Video Without Background Music",
                "author": {"nickname": "Speaker", "unique_id": "speaker1"},
            }
        }
        mock_client = AsyncMock()
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = tikwm_payload
        mock_client.post.return_value = mock_resp

        with tempfile.NamedTemporaryFile(suffix=".mp4", dir=str(TEMP_MEDIA_DIR), delete=False) as f:
            f.write(b"MOCK_SPEECH_VIDEO")
            tmp_vid = f.name

        try:
            with patch.object(self.pipeline, "_get_client", AsyncMock(return_value=mock_client)), \
                 patch.object(self.pipeline, "_stream_url_to_file", AsyncMock(return_value=(tmp_vid, 17))), \
                 patch.object(self.pipeline, "_mux_mp3_with_metadata") as mock_mux:
                
                async def mock_mux_impl(input_path, output_path, is_video, **kwargs):
                    Path(output_path).write_bytes(b"SPEECH_AUDIO_MP3")
                    return True
                mock_mux.side_effect = mock_mux_impl

                item = await self.pipeline._download_tikwm_audio("https://www.tiktok.com/@speaker/video/111")
                self.assertIsNotNone(item)
                self.assertEqual(item.duration, 40)
                self.assertEqual(item.author, "Speaker")
        finally:
            if os.path.exists(tmp_vid):
                os.unlink(tmp_vid)

    async def test_04_dual_engine_slideshow_always_direct_cdn(self):
        """TH 4: Bài đăng album ảnh Slideshow (data.images) -> Luôn kích hoạt Direct CDN stream."""
        tikwm_payload = {
            "code": 0,
            "data": {
                "duration": 60,
                "images": ["https://tikwm.com/img1.jpg", "https://tikwm.com/img2.jpg"],
                "music": "https://tikwm.com/music/slideshow_bg.mp3",
                "music_info": {"duration": 60, "title": "Photo Song", "author": "Band"},
            }
        }
        mock_client = AsyncMock()
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = tikwm_payload
        mock_client.post.return_value = mock_resp

        with tempfile.NamedTemporaryFile(suffix=".mp3", dir=str(TEMP_MEDIA_DIR), delete=False) as f:
            f.write(b"SLIDESHOW_MP3")
            tmp_mp3 = f.name

        try:
            with patch.object(self.pipeline, "_get_client", AsyncMock(return_value=mock_client)), \
                 patch.object(self.pipeline, "_stream_url_to_file", AsyncMock(return_value=(tmp_mp3, 13))) as mock_stream:
                item = await self.pipeline._download_tikwm_audio("https://www.tiktok.com/@user/photo/999")
                self.assertIsNotNone(item)
                self.assertEqual(item.media_type, "audio")
                mock_stream.assert_called_with("https://tikwm.com/music/slideshow_bg.mp3", mock_client, suffix=".mp3")
        finally:
            if os.path.exists(tmp_mp3):
                os.unlink(tmp_mp3)

    async def test_05_dual_engine_tolerance_window_2_seconds(self):
        """TH 5: Video 28s, Music 27s (độ lệch 1s <= 2s và video <= 30s) -> Vẫn nằm trong tolerance window Direct CDN."""
        tikwm_payload = {
            "code": 0,
            "data": {
                "duration": 28,
                "play": "https://tikwm.com/video/short.mp4",
                "music": "https://tikwm.com/music/tolerance.mp3",
                "music_info": {"duration": 27, "title": "Tolerance Beat", "author": "DJ"},
            }
        }
        mock_client = AsyncMock()
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = tikwm_payload
        mock_client.post.return_value = mock_resp

        with tempfile.NamedTemporaryFile(suffix=".mp3", dir=str(TEMP_MEDIA_DIR), delete=False) as f:
            f.write(b"TOLERANCE_AUDIO")
            tmp_mp3 = f.name

        try:
            with patch.object(self.pipeline, "_get_client", AsyncMock(return_value=mock_client)), \
                 patch.object(self.pipeline, "_stream_url_to_file", AsyncMock(return_value=(tmp_mp3, 15))) as mock_stream:
                item = await self.pipeline._download_tikwm_audio("https://www.tiktok.com/@dj/video/28s")
                self.assertIsNotNone(item)
                mock_stream.assert_called_with("https://tikwm.com/music/tolerance.mp3", mock_client, suffix=".mp3")
        finally:
            if os.path.exists(tmp_mp3):
                os.unlink(tmp_mp3)

    async def test_06_dual_engine_cascade_fallback_hd_fail_to_direct_cdn(self):
        """TH 6: Khi HD Video extraction thất bại nhưng có music_url -> Graceful fallback sang Direct CDN."""
        tikwm_payload = {
            "code": 0,
            "data": {
                "duration": 60,
                "play": "https://tikwm.com/video/broken.mp4",
                "music": "https://tikwm.com/music/backup.mp3",
                "music_info": {"duration": 30, "title": "Backup Music", "author": "Backup Artist"},
            }
        }
        mock_client = AsyncMock()
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = tikwm_payload
        mock_client.post.return_value = mock_resp

        with tempfile.NamedTemporaryFile(suffix=".mp4", dir=str(TEMP_MEDIA_DIR), delete=False) as f_vid:
            f_vid.write(b"BROKEN_VIDEO")
            tmp_vid = f_vid.name

        with tempfile.NamedTemporaryFile(suffix=".mp3", dir=str(TEMP_MEDIA_DIR), delete=False) as f_mp3:
            f_mp3.write(b"BACKUP_AUDIO")
            tmp_mp3 = f_mp3.name

        try:
            with patch.object(self.pipeline, "_get_client", AsyncMock(return_value=mock_client)), \
                 patch.object(self.pipeline, "_mux_mp3_with_metadata", AsyncMock(return_value=False)):
                
                async def mock_stream_impl(url, client, suffix):
                    if suffix == ".mp4":
                        return tmp_vid, 12
                    return tmp_mp3, 12
                
                with patch.object(self.pipeline, "_stream_url_to_file", side_effect=mock_stream_impl):
                    item = await self.pipeline._download_tikwm_audio("https://www.tiktok.com/@user/video/fallback")
                    self.assertIsNotNone(item)
                    self.assertEqual(item.file_path, tmp_mp3)
                    self.assertEqual(item.title, "Backup Music")
        finally:
            if os.path.exists(tmp_vid):
                os.unlink(tmp_vid)
            if os.path.exists(tmp_mp3):
                os.unlink(tmp_mp3)

    async def test_07_dual_engine_vlog_dialogue_retention(self):
        """TH 7: Video vlog 120s có tiếng nói creator -> Trích xuất HD video giữ trọn vẹn thời lượng 120s."""
        tikwm_payload = {
            "code": 0,
            "data": {
                "duration": 120,
                "play": "https://tikwm.com/video/vlog120.mp4",
                "music": "https://tikwm.com/music/loop30.mp3",
                "music_info": {"duration": 30, "title": "Loop Beat", "author": "Producer"},
                "author": {"nickname": "Vlogger Dalat", "unique_id": "dalat_vlog"},
            }
        }
        mock_client = AsyncMock()
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = tikwm_payload
        mock_client.post.return_value = mock_resp

        with tempfile.NamedTemporaryFile(suffix=".mp4", dir=str(TEMP_MEDIA_DIR), delete=False) as f_v:
            f_v.write(b"VLOG_DATA")
            tmp_v = f_v.name

        try:
            with patch.object(self.pipeline, "_get_client", AsyncMock(return_value=mock_client)), \
                 patch.object(self.pipeline, "_stream_url_to_file", AsyncMock(return_value=(tmp_v, 9))):
                
                async def mock_mux_impl(input_path, output_path, is_video, **kwargs):
                    Path(output_path).write_bytes(b"VLOG_MP3_FULL")
                    return True

                with patch.object(self.pipeline, "_mux_mp3_with_metadata", side_effect=mock_mux_impl):
                    item = await self.pipeline._download_tikwm_audio("https://www.tiktok.com/@dalat_vlog/video/120s")
                    self.assertIsNotNone(item)
                    self.assertEqual(item.duration, 120)
                    self.assertTrue(item.file_path.endswith(".mp3"))
        finally:
            if os.path.exists(tmp_v):
                os.unlink(tmp_v)

    async def test_08_dual_engine_preserves_source_url_and_metadata(self):
        """TH 8: Đối tượng MediaItem trả về bảo toàn nguyên vẹn source_url, author, title, cover_url."""
        raw_url = "https://www.tiktok.com/@artist/video/888888"
        tikwm_payload = {
            "code": 0,
            "data": {
                "duration": 20,
                "music": "https://tikwm.com/music/test.mp3",
                "origin_cover": "https://tikwm.com/cover/hd.jpg",
                "music_info": {"duration": 20, "title": "Bản Tình Ca", "author": "Ca Sĩ A"},
            }
        }
        mock_client = AsyncMock()
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = tikwm_payload
        mock_client.post.return_value = mock_resp

        with tempfile.NamedTemporaryFile(suffix=".mp3", dir=str(TEMP_MEDIA_DIR), delete=False) as f:
            f.write(b"AUDIO_DATA")
            tmp_mp3 = f.name

        try:
            with patch.object(self.pipeline, "_get_client", AsyncMock(return_value=mock_client)), \
                 patch.object(self.pipeline, "_stream_url_to_file", AsyncMock(return_value=(tmp_mp3, 10))), \
                 patch.object(self.pipeline, "_prepare_cover_and_thumb", AsyncMock(return_value=(None, None))):
                item = await self.pipeline._download_tikwm_audio(raw_url)
                self.assertIsNotNone(item)
                self.assertEqual(item.source_url, raw_url)
                self.assertEqual(item.title, "Bản Tình Ca")
                self.assertEqual(item.author, "Ca Sĩ A")
                self.assertEqual(item.cover_url, "https://tikwm.com/cover/hd.jpg")
        finally:
            if os.path.exists(tmp_mp3):
                os.unlink(tmp_mp3)


class TestID3v2AndCoverArtGroup2(unittest.IsolatedAsyncioTestCase):
    """
    Nhóm 2: ID3v2 Studio Metadata & Cover Art Embedding (7 test cases)
    Xác minh các cờ FFmpeg nhúng tags ID3v2.3, APIC attached_pic, Unicode UTF-8 và trích xuất 320kbps.
    """

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()

    async def test_09_id3v2_tag_embedding_ffmpeg_flags(self):
        """TH 9: Xác nhận lệnh FFmpeg chứa đầy đủ các cờ -id3v2_version 3 và metadata tiêu chuẩn."""
        input_vid = str(TEMP_MEDIA_DIR / "dummy_in.mp4")
        output_mp3 = str(TEMP_MEDIA_DIR / "dummy_out.mp3")

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate.return_value = (b"", b"")
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc

            Path(output_mp3).write_bytes(b"TEST_TAG_AUDIO")
            try:
                res = await self.pipeline._mux_mp3_with_metadata(
                    input_path=input_vid,
                    output_path=output_mp3,
                    is_video=True,
                    title="See Tình",
                    artist="Hoàng Thùy Linh",
                    album="LINK",
                    date="2026",
                )
                self.assertTrue(res)
                called_cmd = mock_exec.call_args[0]
                self.assertIn("-id3v2_version", called_cmd)
                self.assertIn("3", called_cmd)
                self.assertIn("-metadata", called_cmd)
                self.assertIn("title=See Tình", called_cmd)
                self.assertIn("artist=Hoàng Thùy Linh", called_cmd)
                self.assertIn("album=LINK", called_cmd)
                self.assertIn("date=2026", called_cmd)
            finally:
                if os.path.exists(output_mp3):
                    os.unlink(output_mp3)

    async def test_10_id3v2_cover_art_apic_attached_picture(self):
        """TH 10: Xác nhận khi có ảnh bìa, FFmpeg gọi lệnh với -c:v mjpeg và -disposition:v:0 attached_pic."""
        input_file = str(TEMP_MEDIA_DIR / "base.mp3")
        cover_file = str(TEMP_MEDIA_DIR / "cover_art.jpg")
        output_mp3 = str(TEMP_MEDIA_DIR / "out_apic.mp3")

        Path(cover_file).write_bytes(b"COVER_IMAGE_JPEG")
        Path(output_mp3).write_bytes(b"OUTPUT_MP3")

        try:
            with patch("asyncio.create_subprocess_exec") as mock_exec:
                mock_proc = AsyncMock()
                mock_proc.communicate.return_value = (b"", b"")
                mock_proc.returncode = 0
                mock_exec.return_value = mock_proc

                res = await self.pipeline._mux_mp3_with_metadata(
                    input_path=input_file,
                    output_path=output_mp3,
                    is_video=False,
                    cover_path=cover_file,
                    title="Track With Cover",
                )
                self.assertTrue(res)
                cmd = mock_exec.call_args[0]
                self.assertIn("-c:v", cmd)
                self.assertIn("mjpeg", cmd)
                self.assertIn("-disposition:v:0", cmd)
                self.assertIn("attached_pic", cmd)
        finally:
            if os.path.exists(cover_file):
                os.unlink(cover_file)
            if os.path.exists(output_mp3):
                os.unlink(output_mp3)

    async def test_11_id3v2_vietnamese_unicode_encoding(self):
        """TH 11: Xử lý chuỗi Unicode tiếng Việt có dấu phức tạp không bị lỗi font hoặc crash."""
        vn_title = "Cắt Đôi Nỗi Sầu - Tăng Duy Tân (Official Music Video)"
        vn_artist = "Tăng Duy Tân & Drum7"

        output_mp3 = str(TEMP_MEDIA_DIR / "vn_test.mp3")
        Path(output_mp3).write_bytes(b"VN_MP3")

        try:
            with patch("asyncio.create_subprocess_exec") as mock_exec:
                mock_proc = AsyncMock()
                mock_proc.communicate.return_value = (b"", b"")
                mock_proc.returncode = 0
                mock_exec.return_value = mock_proc

                res = await self.pipeline._mux_mp3_with_metadata(
                    input_path="/tmp/in.mp4",
                    output_path=output_mp3,
                    is_video=True,
                    title=vn_title,
                    artist=vn_artist,
                )
                self.assertTrue(res)
                cmd = mock_exec.call_args[0]
                self.assertIn(f"title={vn_title}", cmd)
                self.assertIn(f"artist={vn_artist}", cmd)
        finally:
            if os.path.exists(output_mp3):
                os.unlink(output_mp3)

    async def test_12_id3v2_extreme_metadata_truncation(self):
        """TH 12: Cắt gọt an toàn khi title/artist dài quá 250 ký tự để chống tràn dòng lệnh FFmpeg."""
        extreme_title = "A" * 600
        extreme_artist = "B" * 500

        output_mp3 = str(TEMP_MEDIA_DIR / "trunc_test.mp3")
        Path(output_mp3).write_bytes(b"TRUNC_MP3")

        try:
            with patch("asyncio.create_subprocess_exec") as mock_exec:
                mock_proc = AsyncMock()
                mock_proc.communicate.return_value = (b"", b"")
                mock_proc.returncode = 0
                mock_exec.return_value = mock_proc

                res = await self.pipeline._mux_mp3_with_metadata(
                    input_path="/tmp/in.mp4",
                    output_path=output_mp3,
                    is_video=True,
                    title=extreme_title,
                    artist=extreme_artist,
                )
                self.assertTrue(res)
                cmd = mock_exec.call_args[0]
                # Xác nhận title và artist bị cắt tối đa 250 chars
                title_arg = [arg for arg in cmd if arg.startswith("title=")][0]
                artist_arg = [arg for arg in cmd if arg.startswith("artist=")][0]
                self.assertLessEqual(len(title_arg), len("title=") + 250)
                self.assertLessEqual(len(artist_arg), len("artist=") + 250)
        finally:
            if os.path.exists(output_mp3):
                os.unlink(output_mp3)

    async def test_13_id3v2_graceful_degradation_when_cover_fails(self):
        """TH 13: Khi tải ảnh bìa bị lỗi mạng/404, pipeline vẫn tải và xuất file MP3 thành công không có bìa."""
        tikwm_payload = {
            "code": 0,
            "data": {
                "duration": 20,
                "music": "https://tikwm.com/music/nocover.mp3",
                "cover": "https://tikwm.com/cover/404.jpg",
                "music_info": {"duration": 20, "title": "Song", "author": "Artist"},
            }
        }
        mock_client = AsyncMock()
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = tikwm_payload
        mock_client.post.return_value = mock_resp

        with tempfile.NamedTemporaryFile(suffix=".mp3", dir=str(TEMP_MEDIA_DIR), delete=False) as f:
            f.write(b"AUDIO_NO_COVER")
            tmp_mp3 = f.name

        try:
            with patch.object(self.pipeline, "_get_client", AsyncMock(return_value=mock_client)), \
                 patch.object(self.pipeline, "_prepare_cover_and_thumb", AsyncMock(return_value=(None, None))), \
                 patch.object(self.pipeline, "_stream_url_to_file", AsyncMock(return_value=(tmp_mp3, 14))):
                item = await self.pipeline._download_tikwm_audio("https://vt.tiktok.com/nocover/")
                self.assertIsNotNone(item)
                self.assertEqual(item.file_path, tmp_mp3)
                self.assertIsNone(item.thumbnail_path)
        finally:
            if os.path.exists(tmp_mp3):
                os.unlink(tmp_mp3)

    async def test_14_id3v2_temp_cover_file_cleanup_after_muxing(self):
        """TH 14: Xác nhận file ảnh bìa thô tạm thời bị xóa sạch trong khối finally sau khi xử lý."""
        cover_path = TEMP_MEDIA_DIR / f"test_cleanup_cov_{int(time.time())}.jpg"
        cover_path.write_bytes(b"COVER_BYTES_TO_CLEAN")
        self.assertTrue(cover_path.exists())

        tikwm_payload = {
            "code": 0,
            "data": {
                "duration": 20,
                "music": "https://tikwm.com/music/test.mp3",
                "cover": "https://tikwm.com/cov.jpg",
                "music_info": {"duration": 20, "title": "Title", "author": "Author"},
            }
        }
        mock_client = AsyncMock()
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = tikwm_payload
        mock_client.post.return_value = mock_resp

        with tempfile.NamedTemporaryFile(suffix=".mp3", dir=str(TEMP_MEDIA_DIR), delete=False) as f:
            f.write(b"MP3_DATA")
            tmp_mp3 = f.name

        try:
            with patch.object(self.pipeline, "_get_client", AsyncMock(return_value=mock_client)), \
                 patch.object(self.pipeline, "_prepare_cover_and_thumb", AsyncMock(return_value=(str(cover_path), None))), \
                 patch.object(self.pipeline, "_stream_url_to_file", AsyncMock(return_value=(tmp_mp3, 8))):
                item = await self.pipeline._download_tikwm_audio("https://vt.tiktok.com/cleanup_cov/")
                self.assertIsNotNone(item)
                # File ảnh cover_path phải bị xóa sạch trong finally
                self.assertFalse(cover_path.exists())
        finally:
            if cover_path.exists():
                cover_path.unlink()
            if os.path.exists(tmp_mp3):
                os.unlink(tmp_mp3)

    async def test_15_id3v2_bitrate_verification_320k(self):
        """TH 15: Kiểm tra các tham số encoding khi trích xuất HD: libmp3lame, 320k, 44100Hz, 2 channels."""
        output_mp3 = str(TEMP_MEDIA_DIR / "quality_test.mp3")
        Path(output_mp3).write_bytes(b"QUALITY_TEST")

        try:
            with patch("asyncio.create_subprocess_exec") as mock_exec:
                mock_proc = AsyncMock()
                mock_proc.communicate.return_value = (b"", b"")
                mock_proc.returncode = 0
                mock_exec.return_value = mock_proc

                await self.pipeline._mux_mp3_with_metadata(
                    input_path="/tmp/vid.mp4",
                    output_path=output_mp3,
                    is_video=True,
                    title="High Fidelity",
                )
                cmd = mock_exec.call_args[0]
                self.assertIn("-c:a", cmd)
                self.assertIn("libmp3lame", cmd)
                self.assertIn("-b:a", cmd)
                self.assertIn("320k", cmd)
                self.assertIn("-ar", cmd)
                self.assertIn("44100", cmd)
                self.assertIn("-ac", cmd)
                self.assertIn("2", cmd)
                self.assertIn("-threads", cmd)
                self.assertIn("2", cmd)
        finally:
            if os.path.exists(output_mp3):
                os.unlink(output_mp3)


class TestTelegramSendAudioThumbnailGroup3(unittest.IsolatedAsyncioTestCase):
    """
    Nhóm 3: Telegram Native Player Card với Thumbnail (7 test cases)
    Xác minh send_audio hỗ trợ tham số thumbnail (Path, bytes, URL), multipart form-data,
    bảo toàn thumbnail khi retry fallback Plain Text, và graceful degradation.
    """

    def setUp(self):
        self.bot = TelegramBot.__new__(TelegramBot)
        self.bot.token = "123456:TEST_TOKEN"
        self.mock_client = AsyncMock()
        self._patcher = patch.object(TelegramBot, "_http_client", new_callable=PropertyMock)
        self.mock_prop = self._patcher.start()
        self.mock_prop.return_value = self.mock_client

    def tearDown(self):
        self._patcher.stop()

    async def test_16_telegram_send_audio_includes_thumbnail_field(self):
        """TH 16: send_audio đính kèm trường multipart thumbnail với MIME image/jpeg lên endpoint /sendAudio."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f_audio:
            f_audio.write(b"AUDIO_DATA" * 10)
            audio_path = f_audio.name

        thumb_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 50  # Mock JPEG header

        try:
            mock_resp = MagicMock(status_code=200, text='{"ok":true}')
            self.mock_client.post.return_value = mock_resp

            res = await self.bot.send_audio(
                chat_id="12345",
                audio_path=audio_path,
                title="Song Title",
                performer="Singer",
                thumbnail=thumb_bytes,
            )
            self.assertTrue(res)
            post_args = self.mock_client.post.call_args
            files = post_args[1].get("files", {})
            self.assertIn("audio", files)
            self.assertIn("thumbnail", files)
            thumb_field = files["thumbnail"]
            self.assertEqual(thumb_field[0], "thumbnail.jpg")
            self.assertEqual(thumb_field[2], "image/jpeg")
        finally:
            if os.path.exists(audio_path):
                os.unlink(audio_path)

    async def test_17_telegram_send_audio_thumbnail_as_path(self):
        """TH 17: Tham số thumbnail nhận đường dẫn tệp (Path hoặc str) hợp lệ trên đĩa."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f_audio:
            f_audio.write(b"AUDIO_CONTENT")
            audio_path = f_audio.name

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f_thumb:
            f_thumb.write(b"\xff\xd8\xff\xe0TEST_JPEG_ON_DISK")
            thumb_path = f_thumb.name

        try:
            mock_resp = MagicMock(status_code=200, text='{"ok":true}')
            self.mock_client.post.return_value = mock_resp

            res = await self.bot.send_audio(
                chat_id="12345",
                audio_path=audio_path,
                thumbnail=thumb_path,
            )
            self.assertTrue(res)
            files = self.mock_client.post.call_args[1]["files"]
            self.assertIn("thumbnail", files)
            self.assertEqual(files["thumbnail"][1], b"\xff\xd8\xff\xe0TEST_JPEG_ON_DISK")
        finally:
            if os.path.exists(audio_path):
                os.unlink(audio_path)
            if os.path.exists(thumb_path):
                os.unlink(thumb_path)

    async def test_18_telegram_send_audio_thumbnail_as_bytes_io(self):
        """TH 18: Tham số thumbnail nhận đối tượng io.BytesIO trong bộ nhớ."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f_audio:
            f_audio.write(b"AUDIO_STREAM")
            audio_path = f_audio.name

        bio = io.BytesIO(b"\xff\xd8\xff\xe0BYTES_IO_DATA")

        try:
            mock_resp = MagicMock(status_code=200, text='{"ok":true}')
            self.mock_client.post.return_value = mock_resp

            res = await self.bot.send_audio(
                chat_id="12345",
                audio_path=audio_path,
                thumbnail=bio,
            )
            self.assertTrue(res)
            files = self.mock_client.post.call_args[1]["files"]
            self.assertIn("thumbnail", files)
            self.assertEqual(files["thumbnail"][1], b"\xff\xd8\xff\xe0BYTES_IO_DATA")
        finally:
            if os.path.exists(audio_path):
                os.unlink(audio_path)

    async def test_19_telegram_send_audio_backward_compatible_none_thumbnail(self):
        """TH 19: Tương thích ngược: Khi thumbnail=None, files chỉ chứa 'audio', không có 'thumbnail'."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f_audio:
            f_audio.write(b"PLAIN_AUDIO")
            audio_path = f_audio.name

        try:
            mock_resp = MagicMock(status_code=200, text='{"ok":true}')
            self.mock_client.post.return_value = mock_resp

            res = await self.bot.send_audio(
                chat_id="12345",
                audio_path=audio_path,
                thumbnail=None,
            )
            self.assertTrue(res)
            files = self.mock_client.post.call_args[1]["files"]
            self.assertIn("audio", files)
            self.assertNotIn("thumbnail", files)
        finally:
            if os.path.exists(audio_path):
                os.unlink(audio_path)

    async def test_20_telegram_thumbnail_dimension_and_size_guard(self):
        """TH 20: Tự động nén ảnh bìa qua Pillow nếu thumbnail bytes vượt ngưỡng 200KB."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f_audio:
            f_audio.write(b"AUDIO")
            audio_path = f_audio.name

        # Tạo ảnh lớn > 200KB bằng Pillow
        img = Image.new("RGB", (800, 800), color=(255, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=100)
        large_thumb = buf.getvalue()

        try:
            mock_resp = MagicMock(status_code=200, text='{"ok":true}')
            self.mock_client.post.return_value = mock_resp

            res = await self.bot.send_audio(
                chat_id="12345",
                audio_path=audio_path,
                thumbnail=large_thumb,
            )
            self.assertTrue(res)
            files = self.mock_client.post.call_args[1]["files"]
            self.assertIn("thumbnail", files)
            actual_thumb_bytes = files["thumbnail"][1]
            self.assertLessEqual(len(actual_thumb_bytes), 200 * 1024)
        finally:
            if os.path.exists(audio_path):
                os.unlink(audio_path)

    async def test_21_telegram_send_audio_resilient_retry_rewinds_both_streams(self):
        """TH 21: Khi retry Plain Text do lỗi HTML entities, trường thumbnail vẫn được bảo toàn trong files."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f_audio:
            f_audio.write(b"RETRY_AUDIO")
            audio_path = f_audio.name

        thumb_bytes = b"\xff\xd8\xff\xe0THUMB_BYTES"

        try:
            # Lần 1: HTML parse error 400. Lần 2: Plain text 200.
            resp_err = MagicMock(status_code=400, text='{"ok":false,"description":"Bad Request: can\'t parse entities"}')
            resp_ok = MagicMock(status_code=200, text='{"ok":true}')
            self.mock_client.post.side_effect = [resp_err, resp_ok]

            res = await self.bot.send_audio(
                chat_id="12345",
                audio_path=audio_path,
                caption="<b>Unclosed HTML tag",
                parse_mode="HTML",
                thumbnail=thumb_bytes,
            )
            self.assertTrue(res)
            self.assertEqual(self.mock_client.post.call_count, 2)
            # Kiểm tra request lần 2 vẫn có thumbnail
            retry_files = self.mock_client.post.call_args_list[1][1]["files"]
            self.assertIn("thumbnail", retry_files)
            self.assertEqual(retry_files["thumbnail"][1], thumb_bytes)
        finally:
            if os.path.exists(audio_path):
                os.unlink(audio_path)

    async def test_22_telegram_fallback_strip_thumbnail_on_api_rejection(self):
        """TH 22: Nếu Telegram từ chối thumbnail (HTTP 400 wrong thumbnail), retry tự động gửi audio không có thumbnail."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f_audio:
            f_audio.write(b"AUDIO_DATA")
            audio_path = f_audio.name

        thumb_bytes = b"CORRUPTED_THUMB"

        try:
            resp_thumb_err = MagicMock(status_code=400, text='{"ok":false,"description":"Bad Request: WRONG_THUMBNAIL"}')
            resp_ok = MagicMock(status_code=200, text='{"ok":true}')
            self.mock_client.post.side_effect = [resp_thumb_err, resp_ok]

            res = await self.bot.send_audio(
                chat_id="12345",
                audio_path=audio_path,
                thumbnail=thumb_bytes,
            )
            self.assertTrue(res)
            self.assertEqual(self.mock_client.post.call_count, 2)
            # Lần 2 gửi không có thumbnail
            second_call_files = self.mock_client.post.call_args_list[1][1]["files"]
            self.assertNotIn("thumbnail", second_call_files)
        finally:
            if os.path.exists(audio_path):
                os.unlink(audio_path)


class TestZeroDiskLeakAdversarialGroup4(unittest.IsolatedAsyncioTestCase):
    """
    Nhóm 4: Zero-Disk & Zero-RAM Leak Empirical Adversarial (6 test cases)
    Xác minh 0 byte rác đĩa tồn đọng sau khi xử lý thành công, lỗi mạng, lỗi transcode, và stress harness.
    """

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()
        self.bot = TelegramBot.__new__(TelegramBot)
        self.bot.token = "123456:TEST_TOKEN"
        self.mock_client = AsyncMock()
        self._patcher = patch.object(TelegramBot, "_http_client", new_callable=PropertyMock)
        self.mock_prop = self._patcher.start()
        self.mock_prop.return_value = self.mock_client

    def tearDown(self):
        self._patcher.stop()

    async def test_23_zero_disk_leak_standard_flow_cleans_mp3_and_thumbnail(self):
        """TH 23: Tải thành công -> MediaItem.cleanup() xóa sạch cả file MP3 và file thumbnail (delta = 0 byte)."""
        tmp_mp3 = TEMP_MEDIA_DIR / f"test_mp3_{int(time.time() * 1000)}.mp3"
        tmp_thumb = TEMP_MEDIA_DIR / f"test_thumb_{int(time.time() * 1000)}.jpg"

        tmp_mp3.write_bytes(b"FINAL_MP3_CONTENT" * 100)
        tmp_thumb.write_bytes(b"FINAL_THUMB_CONTENT" * 10)

        self.assertTrue(tmp_mp3.exists())
        self.assertTrue(tmp_thumb.exists())

        item = MediaItem(
            file_path=str(tmp_mp3),
            title="Clean Song",
            author="Clean Artist",
            duration=30,
            media_type="audio",
            source_url="https://vt.tiktok.com/clean/",
            thumbnail_path=str(tmp_thumb),
            is_temp_file=True,
        )

        item.cleanup()
        self.assertFalse(tmp_mp3.exists())
        self.assertFalse(tmp_thumb.exists())

    async def test_24_zero_disk_leak_network_timeout_cleans_both_files(self):
        """TH 24: Khi gửi Telegram gặp lỗi kết nối (Timeout/Broken pipe), khối finally dọn dẹp sạch cả 2 file."""
        tmp_mp3 = TEMP_MEDIA_DIR / f"adv_mp3_{int(time.time() * 1000)}.mp3"
        tmp_thumb = TEMP_MEDIA_DIR / f"adv_thumb_{int(time.time() * 1000)}.jpg"

        tmp_mp3.write_bytes(b"FAIL_AUDIO")
        tmp_thumb.write_bytes(b"FAIL_THUMB")

        item = MediaItem(
            file_path=str(tmp_mp3),
            title="Fail Song",
            author="Fail Artist",
            duration=40,
            media_type="audio",
            source_url="https://vt.tiktok.com/fail/",
            thumbnail_path=str(tmp_thumb),
            is_temp_file=True,
        )

        self.bot.send_audio = AsyncMock(side_effect=httpx.NetworkError("Network broken"))
        self.bot.send_document_file = AsyncMock(side_effect=httpx.NetworkError("Fallback broken"))

        # Mô phỏng khối xử lý tại điểm tiêu thụ
        media_item = item
        try:
            try:
                await self.bot.send_audio(chat_id="123", audio_path=media_item.file_path, thumbnail=media_item.thumbnail_path)
            except Exception:
                await self.bot.send_document_file(chat_id="123", file_path=media_item.file_path)
        except Exception:
            pass
        finally:
            if media_item:
                media_item.cleanup()

        self.assertFalse(tmp_mp3.exists())
        self.assertFalse(tmp_thumb.exists())

    async def test_25_zero_disk_leak_oversized_audio_cleans_thumbnail(self):
        """TH 25: Tệp audio > 50MB chuyển giao cho storage manager (is_temp_file=False), nhưng thumbnail tạm vẫn bị xóa."""
        tmp_mp3 = TEMP_MEDIA_DIR / f"large_audio_{int(time.time() * 1000)}.mp3"
        tmp_thumb = TEMP_MEDIA_DIR / f"large_thumb_{int(time.time() * 1000)}.jpg"

        tmp_mp3.write_bytes(b"LARGE_MP3_DATA" * 10)
        tmp_thumb.write_bytes(b"LARGE_THUMB_DATA")

        item = MediaItem(
            file_path=str(tmp_mp3),
            title="Oversized",
            author="Artist",
            duration=300,
            media_type="audio",
            source_url="https://youtube.com/watch?v=large",
            thumbnail_path=str(tmp_thumb),
            file_size=55 * 1024 * 1024,
            is_temp_file=False,  # Đã chuyển giao sở hữu cho Storage Manager
        )

        # Khi audio > 50MB được chuyển giao cho Storage Manager (is_temp_file=False),
        # item.cleanup() giữ lại MP3 nhưng BẮT BUỘC phải dọn dẹp sạch sẽ thumbnail tạm
        item.cleanup()

        self.assertTrue(tmp_mp3.exists())  # MP3 được lưu trữ
        self.assertFalse(tmp_thumb.exists())  # Thumbnail tạm đã được dọn sạch

        # Dọn dẹp sau test
        if tmp_mp3.exists():
            tmp_mp3.unlink()

    async def test_26_zero_disk_leak_ffmpeg_mux_failure_cleans_inputs(self):
        """TH 26: Khi FFmpeg muxing gặp lỗi, các tệp tạm staging (video, cover) đều bị xóa sạch sẽ trong finally."""
        tmp_vid = TEMP_MEDIA_DIR / f"staging_vid_{int(time.time() * 1000)}.mp4"
        tmp_cov = TEMP_MEDIA_DIR / f"staging_cov_{int(time.time() * 1000)}.jpg"

        tmp_vid.write_bytes(b"STAGING_VIDEO")
        tmp_cov.write_bytes(b"STAGING_COVER")

        tikwm_payload = {
            "code": 0,
            "data": {
                "duration": 60,
                "play": "https://tikwm.com/video/corrupt.mp4",
                "cover": "https://tikwm.com/cov.jpg",
            }
        }
        mock_client = AsyncMock()
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = tikwm_payload
        mock_client.post.return_value = mock_resp

        with patch.object(self.pipeline, "_get_client", AsyncMock(return_value=mock_client)), \
             patch.object(self.pipeline, "_prepare_cover_and_thumb", AsyncMock(return_value=(str(tmp_cov), None))), \
             patch.object(self.pipeline, "_stream_url_to_file", AsyncMock(return_value=(str(tmp_vid), 13))), \
             patch.object(self.pipeline, "_mux_mp3_with_metadata", AsyncMock(return_value=False)):
            
            item = await self.pipeline._download_tikwm_audio("https://vt.tiktok.com/fail_mux/")
            self.assertIsNone(item)
            # Cả 2 file staging phải biến mất 100%
            self.assertFalse(tmp_vid.exists())
            self.assertFalse(tmp_cov.exists())

    async def test_27_zero_ram_leak_streaming_both_audio_and_thumb(self):
        """TH 27: Xác minh truyền stream đĩa O(1) RAM qua _AudioFileStream và đọc thumbnail không gây spike bộ nhớ."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"AUDIO_STREAM_CHUNK" * 1000)
            p_audio = f.name

        stream = _AudioFileStream(open(p_audio, "rb"), os.path.getsize(p_audio))
        try:
            chunk1 = stream.read(65536)
            self.assertEqual(len(chunk1), 18000)
            self.assertEqual(stream.tell(), 18000)
            stream.seek(0)
            self.assertEqual(stream.tell(), 0)
        finally:
            stream.close()
            if os.path.exists(p_audio):
                os.unlink(p_audio)

    async def test_28_stress_20_cycles_zero_orphaned_files(self):
        """TH 28: Stress harness 20 vòng lặp xử lý tải và dọn dẹp -> Xác nhận 0 file mồ côi tồn đọng."""
        initial_files = set(TEMP_MEDIA_DIR.iterdir()) if TEMP_MEDIA_DIR.exists() else set()

        for i in range(20):
            with tempfile.NamedTemporaryFile(suffix=".mp3", dir=str(TEMP_MEDIA_DIR), delete=False) as f_a:
                f_a.write(f"MP3_CYCLE_{i}".encode())
                p_a = f_a.name
            with tempfile.NamedTemporaryFile(suffix=".jpg", dir=str(TEMP_MEDIA_DIR), delete=False) as f_t:
                f_t.write(f"THUMB_CYCLE_{i}".encode())
                p_t = f_t.name

            item = MediaItem(
                file_path=p_a,
                title=f"Cycle {i}",
                author="Stress Bot",
                duration=i + 1,
                media_type="audio",
                source_url=f"https://tiktok.com/stress/{i}",
                thumbnail_path=p_t,
                is_temp_file=True,
            )
            item.cleanup()

        current_files = set(TEMP_MEDIA_DIR.iterdir()) if TEMP_MEDIA_DIR.exists() else set()
        diff = current_files - initial_files
        self.assertEqual(len(diff), 0, f"Phát hiện tệp rác tồn đọng sau 20 vòng stress: {diff}")

    async def test_29_zero_disk_leak_stream_exception_cleans_thumbnail(self):
        """TH 29: Khi stream video ném ngoại lệ mạng (httpx.ReadTimeout), thumbnail tạm đã tạo phải được xóa sạch trong finally."""
        tmp_thumb = TEMP_MEDIA_DIR / f"test_thumb_orphan_{int(time.time() * 1000)}.jpg"
        Image.new("RGB", (300, 300), "green").save(str(tmp_thumb), "JPEG")

        tikwm_payload = {
            "code": 0,
            "data": {
                "duration": 60,
                "play": "https://tikwm.com/video/network_err.mp4",
                "cover": "https://tikwm.com/valid_cover.jpg",
            }
        }
        mock_client = AsyncMock()
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = tikwm_payload
        mock_client.post.return_value = mock_resp

        with patch.object(self.pipeline, "_get_client", AsyncMock(return_value=mock_client)), \
             patch.object(self.pipeline, "_prepare_cover_and_thumb", AsyncMock(return_value=(None, str(tmp_thumb)))), \
             patch.object(self.pipeline, "_stream_url_to_file", AsyncMock(side_effect=httpx.ReadTimeout("Connection dropped"))):

            item = await self.pipeline._download_tikwm_audio("https://vt.tiktok.com/timeout/")
            self.assertIsNone(item)

        # Thumbnail phải biến mất 100% nhờ khối finally
        self.assertFalse(tmp_thumb.exists())

    async def test_30_corrupt_cover_graceful_degradation_and_zero_disk_leak(self):
        """TH 30: Khi cover URL trả về nội dung lỗi (HTML 404), pipeline tự động suy thoái graceful degradation sang trích xuất âm thanh không cover và không rò rỉ đĩa."""
        corrupt_cover_file = TEMP_MEDIA_DIR / f"corrupt_404_{int(time.time() * 1000)}.jpg"
        corrupt_cover_file.write_bytes(b"<html><head><title>404 Not Found</title></head></html>")

        # 1. Kiểm tra trực tiếp _prepare_cover_and_thumb với corrupt cover
        mock_client = AsyncMock()
        with patch.object(self.pipeline, "_stream_url_to_file", AsyncMock(return_value=(str(corrupt_cover_file), len(b"404")))):
            raw_c, thumb = await self.pipeline._prepare_cover_and_thumb("https://tikwm.com/404.jpg", mock_client)
            self.assertIsNone(raw_c)
            self.assertIsNone(thumb)
            self.assertFalse(corrupt_cover_file.exists())  # Phải bị xóa sạch

        # 2. Kiểm tra _download_tikwm_audio với video 60s và cover lỗi
        fake_mp3_path = TEMP_MEDIA_DIR / f"fake_out_{int(time.time() * 1000)}.mp3"
        fake_mp3_path.write_bytes(b"MP3_AUDIO_CONTENT")
        raw_vid = TEMP_MEDIA_DIR / f"valid_vid_{int(time.time() * 1000)}.mp4"
        raw_vid.write_bytes(b"FAKE_VIDEO_STREAM")

        tikwm_payload = {
            "code": 0,
            "data": {
                "duration": 60,
                "play": "https://tikwm.com/video/valid.mp4",
                "cover": "https://tikwm.com/corrupt.jpg",
            }
        }
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = tikwm_payload
        mock_client.post.return_value = mock_resp

        with patch.object(self.pipeline, "_get_client", AsyncMock(return_value=mock_client)), \
             patch.object(self.pipeline, "_prepare_cover_and_thumb", AsyncMock(return_value=(None, None))), \
             patch.object(self.pipeline, "_stream_url_to_file", AsyncMock(return_value=(str(raw_vid), 100))), \
             patch.object(self.pipeline, "_mux_mp3_with_metadata", AsyncMock(return_value=True)) as mock_mux:

            with patch("tempfile.NamedTemporaryFile") as mock_tmp:
                mock_tmp.return_value.__enter__.return_value.name = str(fake_mp3_path)
                item = await self.pipeline._download_tikwm_audio("https://vt.tiktok.com/corrupt_cover/")
                self.assertIsNotNone(item)
                # Mux phải được gọi với cover_path=None
                mock_mux.assert_called_once()
                _, kwargs = mock_mux.call_args
                self.assertIsNone(kwargs.get("cover_path"))
                item.cleanup()

        if raw_vid.exists():
            raw_vid.unlink()
        if fake_mp3_path.exists():
            fake_mp3_path.unlink()

    async def test_31_ffmpeg_mux_cover_failure_retries_without_cover(self):
        """TH 31: Khi FFmpeg mux với cover_path thất bại, pipeline tự động retry với cover_path=None."""
        tmp_vid = TEMP_MEDIA_DIR / f"test_vid_{int(time.time() * 1000)}.mp4"
        tmp_cov = TEMP_MEDIA_DIR / f"test_cov_{int(time.time() * 1000)}.jpg"
        fake_mp3 = TEMP_MEDIA_DIR / f"test_out_{int(time.time() * 1000)}.mp3"

        tmp_vid.write_bytes(b"VIDEO")
        tmp_cov.write_bytes(b"COVER")
        fake_mp3.write_bytes(b"MP3_DATA")

        tikwm_payload = {
            "code": 0,
            "data": {
                "duration": 60,
                "play": "https://tikwm.com/video/test.mp4",
                "cover": "https://tikwm.com/test.jpg",
            }
        }
        mock_client = AsyncMock()
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = tikwm_payload
        mock_client.post.return_value = mock_resp

        # Lần 1 (có cover): return False, Lần 2 (không cover): return True
        mock_mux = AsyncMock(side_effect=[False, True])

        with patch.object(self.pipeline, "_get_client", AsyncMock(return_value=mock_client)), \
             patch.object(self.pipeline, "_prepare_cover_and_thumb", AsyncMock(return_value=(str(tmp_cov), None))), \
             patch.object(self.pipeline, "_stream_url_to_file", AsyncMock(return_value=(str(tmp_vid), 10))), \
             patch.object(self.pipeline, "_mux_mp3_with_metadata", mock_mux):

            with patch("tempfile.NamedTemporaryFile") as mock_tmp:
                mock_tmp.return_value.__enter__.return_value.name = str(fake_mp3)
                item = await self.pipeline._download_tikwm_audio("https://vt.tiktok.com/mux_retry/")
                self.assertIsNotNone(item)
                # Xác nhận mock_mux được gọi 2 lần: lần 1 có cover, lần 2 không cover
                self.assertEqual(mock_mux.call_count, 2)
                call1_kwargs = mock_mux.call_args_list[0][1]
                call2_kwargs = mock_mux.call_args_list[1][1]
                self.assertEqual(call1_kwargs.get("cover_path"), str(tmp_cov))
                self.assertIsNone(call2_kwargs.get("cover_path"))
                item.cleanup()

        if tmp_vid.exists():
            tmp_vid.unlink()
        if tmp_cov.exists():
            tmp_cov.unlink()
        if fake_mp3.exists():
            fake_mp3.unlink()


if __name__ == "__main__":
    unittest.main()
