"""
test_media_pipeline_empirical_challenger.py — Empirical Challenger Adversarial Test Harness.
Designed to empirically stress-test edge cases of MultiTierMediaPipeline:
  1. Adversarial URL Permutations (Facebook redirect/share, Threads, YouTube)
  2. Byte range stripping (_clean_fbcdn_stream_url)
  3. Facebook redirect resolver (early abort, login/checkpoint fallback, network errors)
  4. 48MB threshold enforcement (Content-Length and chunked stream)
  5. 100% Zero-Disk-Leak verification (unlink on error, mid-stream abort)
  6. IPv4 binding enforcement (local_address="0.0.0.0" & source_address="0.0.0.0")
  7. yt-dlp duration filter, part-file cleanup, and error classification
"""

import asyncio
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.media_downloader import (
    MultiTierMediaPipeline,
    MediaItem,
    MediaPipelineError,
    VideoTooLargeError,
    TELEGRAM_MAX_FILE_SIZE,
    TEMP_MEDIA_DIR,
    _clean_fbcdn_stream_url,
    cleanup_expired_media,
)


class TestMediaPipelineAdversarialURLs(unittest.TestCase):
    """Kiểm tra ma trận URL đối kháng cho Facebook, Threads, và YouTube."""

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()

    def test_facebook_redirect_regex_adversarial_matrix(self):
        """Thử nghiệm các biến thể URL Facebook redirect / short link."""
        valid_redirect_urls = [
            "https://fb.watch/xyz123/",
            "http://fb.watch/xyz123",
            "https://www.fb.watch/xyz123/",
            "https://facebook.com/share/r/15vTxyz/",
            "https://www.facebook.com/share/r/15vTxyz/",
            "https://m.facebook.com/share/r/15vTxyz/",
            "https://facebook.com/share/v/890abcdef/",
            "https://www.facebook.com/share/v/890abcdef/?mibextid=wwXIfr",
            "https://fb.me/xyz987",
            "https://www.fb.me/xyz987",
            "https://fb.com/share/r/xyz123",
        ]
        for url in valid_redirect_urls:
            with self.subTest(url=url):
                self.assertIsNotNone(
                    self.pipeline._facebook_redirect_regex.search(url),
                    f"Failed to match Facebook redirect URL: {url}"
                )

        non_redirect_urls = [
            "https://www.facebook.com/reel/123456789",
            "https://facebook.com/reel/123456789/",
            "https://www.facebook.com/watch/?v=123456789",
            "https://m.facebook.com/watch/?v=123456789",
            "https://www.facebook.com/username/posts/123456",
            "https://example.com/share/r/123",
        ]
        for url in non_redirect_urls:
            with self.subTest(url=url):
                self.assertIsNone(
                    self.pipeline._facebook_redirect_regex.search(url),
                    f"Incorrectly matched non-redirect URL: {url}"
                )

    def test_threads_regex_adversarial_matrix(self):
        """Thử nghiệm các biến thể URL Threads hợp lệ và dị dạng."""
        valid_threads_urls = [
            "https://www.threads.net/@creators/post/DdEdK-1lDKz",
            "https://threads.net/@creators/post/DdEdK-1lDKz",
            "https://www.threads.com/@creators/post/DdEdK-1lDKz",
            "https://threads.com/@user.name-123_456/post/xyz999?xmt=AQG123",
            "https://www.threads.net/t/C-wwwwww",
            "https://threads.net/t/C-wwwwww?utm_source=copy",
        ]
        for url in valid_threads_urls:
            with self.subTest(url=url):
                self.assertIsNotNone(
                    self.pipeline._threads_regex.search(url),
                    f"Failed to match Threads URL: {url}"
                )

        invalid_threads_urls = [
            "https://threads.net/about",
            "https://threads.net/@creators",
            "https://www.threads.net/settings",
            "https://fake-threads.net/@user/post/123",
            "https://example.com/threads.net/@user/post/123",
        ]
        for url in invalid_threads_urls:
            with self.subTest(url=url):
                self.assertIsNone(
                    self.pipeline._threads_regex.search(url),
                    f"Incorrectly matched invalid Threads URL: {url}"
                )

    def test_youtube_regex_adversarial_matrix(self):
        """Thử nghiệm các định dạng URL YouTube Shorts và Video."""
        valid_youtube_urls = [
            "https://www.youtube.com/shorts/dQw4w9WgXcQ",
            "https://youtube.com/shorts/dQw4w9WgXcQ?feature=share",
            "https://m.youtube.com/shorts/dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123",
        ]
        for url in valid_youtube_urls:
            with self.subTest(url=url):
                self.assertIsNotNone(
                    self.pipeline._youtube_regex.search(url),
                    f"Failed to match YouTube URL: {url}"
                )


class TestCleanFBCDNStreamURL(unittest.TestCase):
    """Kiểm tra triệt để hàm loại bỏ byte range parameters từ FBCDN stream URL."""

    def test_clean_fbcdn_stream_url_strips_bytestart_and_byteend(self):
        url = "https://video.xx.fbcdn.net/v/t39.123/video.mp4?bytestart=0&byteend=65535&efg=eyxx&oh=abc&oe=123"
        cleaned = _clean_fbcdn_stream_url(url)
        self.assertNotIn("bytestart", cleaned)
        self.assertNotIn("byteend", cleaned)
        self.assertIn("efg=eyxx", cleaned)
        self.assertIn("oh=abc", cleaned)
        self.assertIn("oe=123", cleaned)

    def test_clean_fbcdn_stream_url_case_insensitivity(self):
        url = "https://video.xx.fbcdn.net/v/t39.123/video.mp4?BYTESTART=100&BYTEEND=200&tag=test"
        cleaned = _clean_fbcdn_stream_url(url)
        self.assertNotIn("BYTESTART", cleaned)
        self.assertNotIn("bytestart", cleaned.lower())
        self.assertNotIn("BYTEEND", cleaned)
        self.assertNotIn("byteend", cleaned.lower())
        self.assertIn("tag=test", cleaned)

    def test_clean_fbcdn_stream_url_without_byte_range(self):
        url = "https://video.xx.fbcdn.net/v/t39.123/video.mp4?oh=abc&oe=123"
        cleaned = _clean_fbcdn_stream_url(url)
        self.assertEqual(cleaned, url)


class TestRedirectResolverEmpirical(unittest.TestCase):
    """Kiểm thử thực nghiệm cơ chế Early Abort Redirect Resolver của Facebook."""

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()

    def test_resolve_redirect_successful(self):
        async def run():
            mock_resp = MagicMock()
            mock_resp.url = "https://www.facebook.com/reel/123456789"
            mock_resp.status_code = 200

            mock_stream_ctx = MagicMock()
            mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

            with patch("httpx.AsyncClient.stream", return_value=mock_stream_ctx):
                res = await self.pipeline._resolve_redirect_url("https://fb.watch/xyz123/")
                self.assertEqual(res, "https://www.facebook.com/reel/123456789")
        asyncio.run(run())

    def test_resolve_redirect_login_detection_retains_original(self):
        """Khi bị redirect sang trang /login (video private), phải giữ URL gốc."""
        async def run():
            mock_resp = MagicMock()
            mock_resp.url = "https://www.facebook.com/login/?next=https%3A%2F%2Fwww.facebook.com%2Freel%2F123"
            mock_resp.status_code = 200

            mock_stream_ctx = MagicMock()
            mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

            with patch("httpx.AsyncClient.stream", return_value=mock_stream_ctx):
                res = await self.pipeline._resolve_redirect_url("https://fb.watch/private_video/")
                self.assertEqual(res, "https://fb.watch/private_video/")
        asyncio.run(run())

    def test_resolve_redirect_checkpoint_detection_retains_original(self):
        """Khi bị redirect sang /checkpoint (xác minh bot), phải giữ URL gốc."""
        async def run():
            mock_resp = MagicMock()
            mock_resp.url = "https://www.facebook.com/checkpoint/?next=..."
            mock_resp.status_code = 200

            mock_stream_ctx = MagicMock()
            mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

            with patch("httpx.AsyncClient.stream", return_value=mock_stream_ctx):
                res = await self.pipeline._resolve_redirect_url("https://fb.watch/checkpoint_video/")
                self.assertEqual(res, "https://fb.watch/checkpoint_video/")
        asyncio.run(run())

    def test_resolve_redirect_http_error_retains_original(self):
        """Khi nhận HTTP 404 hoặc 500, không ném exception mà giữ URL gốc."""
        async def run():
            mock_resp = MagicMock()
            mock_resp.url = "https://www.facebook.com/404"
            mock_resp.status_code = 404

            mock_stream_ctx = MagicMock()
            mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

            with patch("httpx.AsyncClient.stream", return_value=mock_stream_ctx):
                res = await self.pipeline._resolve_redirect_url("https://fb.watch/not_found/")
                self.assertEqual(res, "https://fb.watch/not_found/")
        asyncio.run(run())

    def test_resolve_redirect_timeout_retains_original(self):
        """Khi bị timeout, giữ URL gốc một cách an toàn."""
        async def run():
            with patch("httpx.AsyncClient.stream", side_effect=asyncio.TimeoutError()):
                res = await self.pipeline._resolve_redirect_url("https://fb.watch/timeout_video/")
                self.assertEqual(res, "https://fb.watch/timeout_video/")
        asyncio.run(run())


class TestThresholdAndZeroDiskLeak(unittest.TestCase):
    """
    Thách thức đối kháng: Giả lập vi phạm ngưỡng 48MB và lỗi gián đoạn mạng
    để kiểm tra 100% Zero-Disk-Leak và tính đúng đắn của VideoTooLargeError.
    """

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()
        # Đếm số file hiện có trong thư mục tạm trước test
        self.initial_files = set(TEMP_MEDIA_DIR.iterdir()) if TEMP_MEDIA_DIR.exists() else set()

    def tearDown(self):
        # Kiểm tra không có file rác phát sinh sau mỗi test
        current_files = set(TEMP_MEDIA_DIR.iterdir()) if TEMP_MEDIA_DIR.exists() else set()
        leaked_files = current_files - self.initial_files
        for lf in leaked_files:
            try:
                if lf.is_file():
                    lf.unlink(missing_ok=True)
                elif lf.is_dir():
                    shutil.rmtree(lf, ignore_errors=True)
            except Exception:
                pass
        self.assertEqual(
            len(leaked_files), 0,
            f"DISK LEAK DETECTED! Leftover files in {TEMP_MEDIA_DIR}: {leaked_files}"
        )

    def test_content_length_oversized_raises_and_creates_zero_files(self):
        """Kiểm tra Content-Length > 48MB: ngắt ngay lập tức, không tạo bất kỳ file tạm nào."""
        async def run():
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            # Giả lập video 52MB
            mock_resp.headers = {"content-length": str(52 * 1024 * 1024)}

            mock_stream_ctx = MagicMock()
            mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

            mock_client = MagicMock()
            mock_client.stream = MagicMock(return_value=mock_stream_ctx)

            with self.assertRaises(VideoTooLargeError):
                await self.pipeline._stream_url_to_file("https://cdn.example.com/huge.mp4", mock_client)

        asyncio.run(run())

    def test_chunked_streaming_oversized_unlinks_temp_file_immediately(self):
        """
        Kiểm tra stream không có Content-Length nhưng dung lượng thực tế vượt 48MB:
        phải ném VideoTooLargeError VÀ lập tức xóa sạch file tạm (Zero-Disk-Leak).
        """
        async def run():
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.headers = {}  # Không có content-length header

            # Giả lập generator chunk 64KB: 770 chunks * 64KB = 50.46MB (> 48MB)
            chunk_64kb = b"X" * (64 * 1024)

            async def _chunk_gen(*args, **kwargs):
                for _ in range(770):
                    yield chunk_64kb

            mock_resp.aiter_bytes = _chunk_gen

            mock_stream_ctx = MagicMock()
            mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

            mock_client = MagicMock()
            mock_client.stream = MagicMock(return_value=mock_stream_ctx)

            with self.assertRaises(VideoTooLargeError):
                await self.pipeline._stream_url_to_file("https://cdn.example.com/oversized_stream.mp4", mock_client)

        asyncio.run(run())

    def test_mid_stream_network_error_unlinks_temp_file(self):
        """
        Kiểm tra khi đang stream thì gặp lỗi mạng (ConnectionResetError):
        phải re-raise exception VÀ xóa sạch file tạm đã ghi dở (Zero-Disk-Leak).
        """
        async def run():
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.headers = {}

            async def _broken_chunk_gen(*args, **kwargs):
                yield b"A" * (64 * 1024)
                yield b"B" * (64 * 1024)
                raise ConnectionResetError("Connection abruptly closed by peer")

            mock_resp.aiter_bytes = _broken_chunk_gen

            mock_stream_ctx = MagicMock()
            mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

            mock_client = MagicMock()
            mock_client.stream = MagicMock(return_value=mock_stream_ctx)

            with self.assertRaises(ConnectionResetError):
                await self.pipeline._stream_url_to_file("https://cdn.example.com/broken_stream.mp4", mock_client)

        asyncio.run(run())

    def test_stream_non_200_raises_media_pipeline_error(self):
        """Stream trả về HTTP 403/404 phải ném MediaPipelineError và không tạo file."""
        async def run():
            mock_resp = MagicMock()
            mock_resp.status_code = 403
            mock_resp.headers = {}

            mock_stream_ctx = MagicMock()
            mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

            mock_client = MagicMock()
            mock_client.stream = MagicMock(return_value=mock_stream_ctx)

            with self.assertRaises(MediaPipelineError):
                await self.pipeline._stream_url_to_file("https://cdn.example.com/forbidden.mp4", mock_client)

        asyncio.run(run())

    def test_stream_cancellation_zero_disk_leak(self):
        """Kiểm tra khi task bị asyncio.CancelledError, file tạm có bị rò rỉ không."""
        async def run():
            started_event = asyncio.Event()

            async def slow_generator(*args, **kwargs):
                started_event.set()
                while True:
                    yield b"A" * 1024
                    await asyncio.sleep(0.05)

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.headers = {}
            mock_resp.aiter_bytes = slow_generator

            mock_stream_ctx = MagicMock()
            mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

            mock_client = MagicMock()
            mock_client.stream = MagicMock(return_value=mock_stream_ctx)

            task = asyncio.create_task(
                self.pipeline._stream_url_to_file("https://cdn.example.com/stream.mp4", mock_client)
            )
            await started_event.wait()
            await asyncio.sleep(0.02)

            mp4_files = list(TEMP_MEDIA_DIR.glob("*.mp4"))
            self.assertGreaterEqual(len(mp4_files), 1, "File tạm phải tồn tại trong khi stream")
            temp_file = mp4_files[0]

            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

            file_exists = temp_file.exists()
            if file_exists:
                temp_file.unlink(missing_ok=True)
            self.assertFalse(
                file_exists,
                "DISK LEAK: File tạm không được xóa khi gặp asyncio.CancelledError do 'except Exception:' không bắt BaseException!"
            )

        asyncio.run(run())

    def test_media_item_cleanup_must_not_delete_temp_media_dir(self):
        """Kiểm tra MediaItem.cleanup() không được xóa thư mục gốc TEMP_MEDIA_DIR."""
        TEMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix=".mp4", dir=str(TEMP_MEDIA_DIR), delete=False) as tf:
            temp_file_path = tf.name

        item = MediaItem(
            file_path=temp_file_path,
            title="Safety Test",
            author="Author",
            duration=5,
            media_type="video",
            source_url="https://example.com/video",
            is_temp_file=True,
        )

        item.cleanup()
        self.assertFalse(os.path.exists(temp_file_path), "File tạm phải bị xóa")
        self.assertTrue(
            TEMP_MEDIA_DIR.exists(),
            "CRITICAL BUG: MediaItem.cleanup() đã xóa nhầm thư mục gốc TEMP_MEDIA_DIR!"
        )


class TestIPv4EnforcementAndYtDlpConfig(unittest.TestCase):
    """Kiểm tra cơ chế ép buộc IPv4 0.0.0.0 và cấu hình yt-dlp."""

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()

    def test_get_client_enforces_ipv4(self):
        """_get_client() phải gán local_address='0.0.0.0' trong transport."""
        async def run():
            client = await self.pipeline._get_client()
            transport = client._transport
            self.assertIsNotNone(transport)
            # Kiểm tra transport là AsyncHTTPTransport
            import httpx
            self.assertIsInstance(transport, httpx.AsyncHTTPTransport)
            # Kiểm tra thuộc tính local_address của transport pool
            pool = transport._pool
            self.assertEqual(pool._local_address, "0.0.0.0")
        asyncio.run(run())

    def test_sync_ytdlp_download_options_and_limits(self):
        """_sync_ytdlp_download phải cấu hình source_address 0.0.0.0 và max_filesize."""
        captured_opts = {}

        class DummyYDL:
            def __init__(self, opts):
                nonlocal captured_opts
                captured_opts = opts

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

            def extract_info(self, url, download=True):
                return None

        # Mock yt_dlp trong module
        mock_ytdlp_module = MagicMock()
        mock_ytdlp_module.YoutubeDL = DummyYDL

        with patch.dict(sys.modules, {"yt_dlp": mock_ytdlp_module}):
            self.pipeline._sync_ytdlp_download("https://www.youtube.com/shorts/test123")

        self.assertEqual(captured_opts.get("source_address"), "0.0.0.0")
        self.assertEqual(captured_opts.get("max_filesize"), TELEGRAM_MAX_FILE_SIZE)
        self.assertEqual(captured_opts.get("merge_output_format"), "mp4")
        self.assertIn("filesize<=48M", captured_opts.get("format", ""))

        # Kiểm tra match_filter reject duration > 1800s
        match_filter = captured_opts.get("match_filter")
        self.assertIsNotNone(match_filter)
        with self.assertRaises(VideoTooLargeError):
            match_filter({"duration": 1801})
        self.assertIsNone(match_filter({"duration": 60}))

    def test_ytdlp_part_files_trigger_video_too_large_and_cleanup(self):
        """yt-dlp để lại file .part (do vượt max_filesize) phải ném VideoTooLargeError và xóa thư mục tạm."""
        created_temp_dirs = []

        class PartFileSimYDL:
            def __init__(self, opts):
                self.opts = opts

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

            def extract_info(self, url, download=True):
                # Tạo file .part trong thư mục outtmpl
                outtmpl = self.opts["outtmpl"]
                td = os.path.dirname(outtmpl)
                created_temp_dirs.append(td)
                part_file = os.path.join(td, "media_test.mp4.part")
                with open(part_file, "wb") as f:
                    f.write(b"partial video data")
                return {"id": "test"}

            def prepare_filename(self, info):
                td = created_temp_dirs[-1]
                return os.path.join(td, "media_test.mp4")

        mock_ytdlp_module = MagicMock()
        mock_ytdlp_module.YoutubeDL = PartFileSimYDL

        with patch.dict(sys.modules, {"yt_dlp": mock_ytdlp_module}):
            with self.assertRaises(VideoTooLargeError):
                self.pipeline._sync_ytdlp_download("https://www.youtube.com/watch?v=large")

        # Xác thực thư mục tạm đã bị dọn sạch
        for td in created_temp_dirs:
            self.assertFalse(os.path.exists(td), f"Temporary directory {td} was not cleaned up!")

    def test_ytdlp_download_error_max_filesize_triggers_video_too_large(self):
        """yt-dlp ném DownloadError 'larger than max-filesize' phải chuyển hóa thành VideoTooLargeError."""
        class DummyDownloadError(Exception):
            pass

        class DownloadErrorSimYDL:
            def __init__(self, opts):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

            def extract_info(self, url, download=True):
                raise DummyDownloadError("File is larger than max-filesize (55000000 > 50331648)")

        mock_utils = MagicMock()
        mock_utils.DownloadError = DummyDownloadError
        mock_ytdlp_module = MagicMock()
        mock_ytdlp_module.YoutubeDL = DownloadErrorSimYDL
        mock_ytdlp_module.utils = mock_utils

        with patch.dict(sys.modules, {"yt_dlp": mock_ytdlp_module, "yt_dlp.utils": mock_utils}):
            with self.assertRaises(VideoTooLargeError):
                self.pipeline._sync_ytdlp_download("https://www.youtube.com/watch?v=too_big")


class TestPipelineDownloadRouting(unittest.TestCase):
    """Kiểm tra điều phối luồng (Routing Gateway) trong pipeline.download()."""

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()

    def test_threads_routing_direct_to_playwright(self):
        async def run():
            fake_item = MediaItem(
                file_path="/tmp/fake.mp4",
                title="Threads Post",
                author="creator",
                duration=10,
                media_type="video",
                source_url="https://www.threads.net/@creator/post/123",
                is_temp_file=False,
            )
            with patch.object(self.pipeline, "_download_threads_playwright", new_callable=AsyncMock) as mock_threads:
                mock_threads.return_value = fake_item
                item = await self.pipeline.download("https://www.threads.net/@creator/post/123")
                self.assertEqual(item.source_url, "https://www.threads.net/@creator/post/123")
                mock_threads.assert_called_once_with("https://www.threads.net/@creator/post/123")
        asyncio.run(run())

    def test_facebook_redirect_routing_resolves_and_calls_ytdlp(self):
        async def run():
            fake_item = MediaItem(
                file_path="/tmp/fake_fb.mp4",
                title="FB Reel",
                author="fb_creator",
                duration=30,
                media_type="video",
                source_url="https://fb.watch/xyz/",
                is_temp_file=False,
            )
            with patch.object(self.pipeline, "_resolve_redirect_url", new_callable=AsyncMock) as mock_resolve:
                mock_resolve.return_value = "https://www.facebook.com/reel/999"
                with patch.object(self.pipeline, "_download_ytdlp", new_callable=AsyncMock) as mock_ytdlp:
                    mock_ytdlp.return_value = fake_item
                    item = await self.pipeline.download("https://fb.watch/xyz/")
                    mock_resolve.assert_called_once_with("https://fb.watch/xyz/")
                    mock_ytdlp.assert_called_once_with("https://www.facebook.com/reel/999")
                    self.assertEqual(item.source_url, "https://fb.watch/xyz/")
        asyncio.run(run())

    def test_video_too_large_in_ytdlp_bubbles_up_without_falling_back(self):
        """Khi yt-dlp báo VideoTooLargeError, pipeline KHÔNG ĐƯỢC fallback sang Playwright."""
        async def run():
            with patch.object(self.pipeline, "_download_ytdlp", new_callable=AsyncMock) as mock_ytdlp:
                mock_ytdlp.side_effect = VideoTooLargeError("Video > 50MB")
                with patch.object(self.pipeline, "_download_playwright_sniff", new_callable=AsyncMock) as mock_playwright:
                    with self.assertRaises(VideoTooLargeError):
                        await self.pipeline.download("https://www.youtube.com/watch?v=gigantic")
                    mock_playwright.assert_not_called()
        asyncio.run(run())


class TestThreadsSnifferAndAdvancedEdgeCases(unittest.TestCase):
    """Kiểm thử chuyên sâu các cơ chế nội bộ của Threads Playwright Sniffer và Dọn dẹp Thư mục."""

    def test_threads_json_hydration_regex_extraction(self):
        """Kiểm tra regex bóc tách video_versions từ HTML chứa JSON hydration phức tạp."""
        import json, re

        sample_html = r"""
        <!DOCTYPE html>
        <html>
        <head><title>Threads Post</title></head>
        <body>
        <script>
        var data = {"post":{"caption":"Cool video","video_versions":[{"url":"https:\/\/video.xx.fbcdn.net\/v\/t39.123\/v1.mp4?bytestart=0&byteend=65535&efg=123","width":720,"height":1280}]}};
        </script>
        </body>
        </html>
        """
        extracted_stream_url = None
        matches = re.finditer(r'\"video_versions\"\s*:\s*(\[[^\]]+\])', sample_html)
        for m in matches:
            clean_json = m.group(1).replace(r"\/", "/")
            items = json.loads(clean_json)
            for it in items:
                candidate = it.get("url")
                if candidate and ("fbcdn.net" in candidate or "cdninstagram.com" in candidate):
                    extracted_stream_url = candidate
                    break
            if extracted_stream_url:
                break

        self.assertIsNotNone(extracted_stream_url)
        self.assertIn("video.xx.fbcdn.net", extracted_stream_url)
        cleaned = _clean_fbcdn_stream_url(extracted_stream_url)
        self.assertNotIn("bytestart", cleaned)
        self.assertNotIn("byteend", cleaned)
        self.assertIn("efg=123", cleaned)

    def test_threads_author_extraction_regex(self):
        """Kiểm tra regex trích xuất tác giả từ URL Threads."""
        import re
        urls_and_expected_authors = [
            ("https://www.threads.net/@cristiano/post/C-12345", "cristiano"),
            ("https://threads.net/@user.official_99/post/123?utm_source=copy", "user.official_99"),
            ("https://www.threads.com/@someone-special/post/xyz", "someone-special"),
        ]
        for url, expected in urls_and_expected_authors:
            m = re.search(r"/@([^/\?]+)", url)
            self.assertIsNotNone(m, f"Failed extracting author from {url}")
            self.assertEqual(m.group(1), expected)

    def test_concurrency_semaphores_configuration(self):
        """Xác nhận cấu hình Semaphore: yt-dlp = 2, Playwright = 1 để bảo vệ RAM 3.2GB."""
        pipeline = MultiTierMediaPipeline()
        self.assertEqual(pipeline._ytdlp_semaphore._value, 2)
        self.assertEqual(pipeline._playwright_semaphore._value, 1)

    def test_cleanup_expired_directories(self):
        """Xác nhận cleanup_expired_media dọn sạch cả thư mục tạm media_ytdlp_ con bị mồ côi."""
        import time
        TEMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        expired_dir = TEMP_MEDIA_DIR / "media_ytdlp_orphan_test"
        expired_dir.mkdir(exist_ok=True)
        dummy_file = expired_dir / "partial.mp4"
        dummy_file.write_bytes(b"orphaned data")

        # Mock thời gian sửa đổi cũ hơn 10 phút (900 giây)
        fifteen_min_ago = time.time() - 900
        os.utime(str(expired_dir), (fifteen_min_ago, fifteen_min_ago))

        cleaned = cleanup_expired_media(max_age_seconds=600)
        self.assertGreaterEqual(cleaned, 1)
        self.assertFalse(expired_dir.exists(), "Thư mục tạm mồ côi phải bị rmtree hoàn toàn!")


if __name__ == "__main__":
    unittest.main()
