"""
test_facebook_url_architecture.py — Comprehensive Unit & Integration Test Suite
for Facebook URL Architecture & Normalization Pipeline.

Designed to thoroughly verify:
1. Deterministic Static Normalization (facebook.com/share/r/, facebook.com/share/v/, fb.com, query params).
2. Early Abort HTTP Redirect Resolver with Meta Whitelisted User-Agent without WAF 400 triggers.
3. MultiTierMediaPipeline routing and dispatching to yt-dlp with Canonical URLs.
4. TelegramBot Fast-Path intent regex matching across all Facebook URL permutations.
"""

import asyncio
import os
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import httpx

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.media_downloader import (
    MultiTierMediaPipeline,
    MediaItem,
    MediaPipelineError,
    canonicalize_facebook_url,
    _normalize_facebook_url,
    TEMP_MEDIA_DIR,
)
from app.services.telegram_bot import TelegramBot


class TestFacebookStaticUrlNormalization(unittest.TestCase):
    """Kiểm tra ma trận chuẩn hóa tĩnh các biến thể URL Facebook dạng share sang Canonical."""

    def test_normalize_share_reel_standard_desktop(self):
        url = "https://www.facebook.com/share/r/1195289147628387/"
        self.assertEqual(canonicalize_facebook_url(url), "https://www.facebook.com/reel/1195289147628387/")

    def test_normalize_share_reel_no_trailing_slash(self):
        url = "https://www.facebook.com/share/r/1195289147628387"
        self.assertEqual(canonicalize_facebook_url(url), "https://www.facebook.com/reel/1195289147628387/")

    def test_normalize_share_reel_mobile_subdomain(self):
        url = "https://m.facebook.com/share/r/1195289147628387/"
        self.assertEqual(canonicalize_facebook_url(url), "https://www.facebook.com/reel/1195289147628387/")

    def test_normalize_share_reel_web_subdomain(self):
        url = "https://web.facebook.com/share/r/1195289147628387/"
        self.assertEqual(canonicalize_facebook_url(url), "https://www.facebook.com/reel/1195289147628387/")

    def test_normalize_share_reel_fb_com_short_domain(self):
        url = "https://fb.com/share/r/1195289147628387/"
        self.assertEqual(canonicalize_facebook_url(url), "https://www.facebook.com/reel/1195289147628387/")

    def test_normalize_share_reel_with_query_parameters(self):
        url = "https://www.facebook.com/share/r/1195289147628387/?mibextid=wwXIfr"
        self.assertEqual(canonicalize_facebook_url(url), "https://www.facebook.com/reel/1195289147628387/")

    def test_normalize_share_reel_with_complex_query_and_hash(self):
        url = "https://www.facebook.com/share/r/1195289147628387/?mibextid=wwXIfr&sfnsn=mo#ref=share"
        self.assertEqual(canonicalize_facebook_url(url), "https://www.facebook.com/reel/1195289147628387/")

    def test_normalize_share_reel_alphanumeric_id(self):
        url = "https://www.facebook.com/share/r/AbCdEf12345/"
        self.assertEqual(canonicalize_facebook_url(url), "https://www.facebook.com/reel/AbCdEf12345/")

    def test_normalize_share_reel_alternate_path_variant(self):
        url = "https://www.facebook.com/share/reel/1195289147628387/"
        self.assertEqual(canonicalize_facebook_url(url), "https://www.facebook.com/reel/1195289147628387/")

    def test_normalize_share_video_standard_desktop(self):
        url = "https://www.facebook.com/share/v/890abcdef/"
        self.assertEqual(canonicalize_facebook_url(url), "https://www.facebook.com/watch/?v=890abcdef")

    def test_normalize_share_video_no_trailing_slash(self):
        url = "https://www.facebook.com/share/v/890abcdef"
        self.assertEqual(canonicalize_facebook_url(url), "https://www.facebook.com/watch/?v=890abcdef")

    def test_normalize_share_video_mobile_with_query(self):
        url = "https://m.facebook.com/share/v/890abcdef/?mibextid=wwXIfr"
        self.assertEqual(canonicalize_facebook_url(url), "https://www.facebook.com/watch/?v=890abcdef")

    def test_normalize_share_video_alternate_path_variant(self):
        url = "https://fb.com/share/video/890abcdef/"
        self.assertEqual(canonicalize_facebook_url(url), "https://www.facebook.com/watch/?v=890abcdef")

    def test_normalize_passthrough_canonical_and_other_urls(self):
        """Các URL đã ở định dạng chuẩn hoặc của nền tảng khác phải được giữ nguyên."""
        passthrough_urls = [
            "https://www.facebook.com/reel/1195289147628387/",
            "https://www.facebook.com/reel/1195289147628387",
            "https://www.facebook.com/watch/?v=123456789",
            "https://fb.watch/xyz123/",
            "https://fb.me/xyz987",
            "https://www.facebook.com/user.name/videos/123456789/",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://www.tiktok.com/@user/video/123",
        ]
        for u in passthrough_urls:
            with self.subTest(url=u):
                self.assertEqual(canonicalize_facebook_url(u), u)
                self.assertEqual(_normalize_facebook_url(u), u)


class TestFacebookRedirectResolverSafety(unittest.TestCase):
    """Kiểm tra độ an toàn của HTTP Redirect Resolver không gây lỗi HTTP 400 và chống lặp redirect."""

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()

    def test_resolve_redirect_chained_with_static_normalization(self):
        """Khi fb.watch redirect sang dạng share/r/, phải tự động chuẩn hóa sang canonical /reel/."""
        async def run():
            mock_resp = MagicMock()
            mock_resp.url = "https://www.facebook.com/share/r/1195289147628387/?mibextid=wwXIfr"
            mock_resp.status_code = 200

            mock_stream_ctx = MagicMock()
            mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

            with patch("httpx.AsyncClient.stream", return_value=mock_stream_ctx):
                res = await self.pipeline._resolve_redirect_url("https://fb.watch/xyz123/")
                self.assertEqual(res, "https://www.facebook.com/reel/1195289147628387/")
        asyncio.run(run())

    def test_resolve_redirect_uses_whitelisted_user_agent(self):
        """Xác nhận request sử dụng User-Agent Meta whitelisted (facebookexternalhit/1.1), không dùng Chrome Desktop HTTP/1.1."""
        async def run():
            captured_headers = {}

            def mock_client_init(*args, **kwargs):
                nonlocal captured_headers
                captured_headers = kwargs.get("headers", {})
                client = MagicMock()
                mock_resp = MagicMock()
                mock_resp.url = "https://www.facebook.com/reel/123"
                mock_resp.status_code = 200
                mock_stream_ctx = MagicMock()
                mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
                mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)
                client.stream = MagicMock(return_value=mock_stream_ctx)
                client.__aenter__ = AsyncMock(return_value=client)
                client.__aexit__ = AsyncMock(return_value=None)
                return client

            with patch("httpx.AsyncClient", side_effect=mock_client_init):
                res = await self.pipeline._resolve_redirect_url("https://fb.watch/xyz123/")
                ua = captured_headers.get("User-Agent", "")
                self.assertIn("facebookexternalhit/1.1", ua)
                self.assertNotIn("Chrome/128", ua)
        asyncio.run(run())

    def test_resolve_redirect_handles_too_many_redirects_gracefully(self):
        """Xác nhận khi gặp vòng lặp redirect (TooManyRedirects), giữ nguyên URL gốc một cách an toàn."""
        async def run():
            with patch("httpx.AsyncClient.stream", side_effect=httpx.TooManyRedirects("Exceeded 5 redirects")):
                res = await self.pipeline._resolve_redirect_url("https://fb.watch/loop_video/")
                self.assertEqual(res, "https://fb.watch/loop_video/")
        asyncio.run(run())


class TestPipelineFacebookRouting(unittest.TestCase):
    """Kiểm tra luồng định tuyến của MultiTierMediaPipeline khi tải link Facebook."""

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()

    def test_download_share_reel_bypasses_network_redirect_and_calls_ytdlp(self):
        """Link share/r/ phải được chuyển đổi tĩnh sang /reel/<id>/ và đưa thẳng vào yt-dlp mà không gọi network resolver."""
        async def run():
            dummy_item = MediaItem(
                file_path="/tmp/media_downloads/dummy.mp4",
                title="Facebook Reel",
                author="Creator",
                duration=15,
                media_type="video",
                source_url="",
                file_size=1024,
            )

            with patch.object(self.pipeline, "_resolve_redirect_url", new_callable=AsyncMock) as mock_resolve:
                with patch.object(self.pipeline, "_download_ytdlp", new_callable=AsyncMock, return_value=dummy_item) as mock_ytdlp:
                    raw_url = "https://www.facebook.com/share/r/1195289147628387/?mibextid=wwXIfr"
                    item = await self.pipeline.download(raw_url)

                    # Xác nhận _resolve_redirect_url KHÔNG bị gọi nhờ chuẩn hóa tĩnh 0ms
                    mock_resolve.assert_not_called()
                    # Xác nhận _download_ytdlp được gọi với Canonical URL
                    mock_ytdlp.assert_awaited_once_with("https://www.facebook.com/reel/1195289147628387/")
                    # Xác nhận source_url ban đầu vẫn được bảo toàn
                    self.assertEqual(item.source_url, raw_url)
        asyncio.run(run())

    def test_download_share_video_calls_ytdlp_with_watch_canonical(self):
        """Link share/v/ phải được chuyển đổi tĩnh sang /watch/?v=<id> và đưa vào yt-dlp."""
        async def run():
            dummy_item = MediaItem(
                file_path="/tmp/media_downloads/dummy.mp4",
                title="Facebook Watch Video",
                author="Creator",
                duration=60,
                media_type="video",
                source_url="",
                file_size=2048,
            )

            with patch.object(self.pipeline, "_resolve_redirect_url", new_callable=AsyncMock) as mock_resolve:
                with patch.object(self.pipeline, "_download_ytdlp", new_callable=AsyncMock, return_value=dummy_item) as mock_ytdlp:
                    raw_url = "https://www.facebook.com/share/v/890abcdef/?mibextid=wwXIfr"
                    item = await self.pipeline.download(raw_url)

                    mock_resolve.assert_not_called()
                    mock_ytdlp.assert_awaited_once_with("https://www.facebook.com/watch/?v=890abcdef")
                    self.assertEqual(item.source_url, raw_url)
        asyncio.run(run())

    def test_download_fb_watch_calls_redirect_and_passes_to_ytdlp(self):
        """Link fb.watch/ không chứa ID phải gọi redirect resolver trước khi đưa vào yt-dlp."""
        async def run():
            dummy_item = MediaItem(
                file_path="/tmp/media_downloads/dummy.mp4",
                title="Facebook Watch Short",
                author="Creator",
                duration=30,
                media_type="video",
                source_url="",
                file_size=1024,
            )

            with patch.object(self.pipeline, "_resolve_redirect_url", new_callable=AsyncMock) as mock_resolve:
                mock_resolve.return_value = "https://www.facebook.com/reel/1195289147628387/"
                with patch.object(self.pipeline, "_download_ytdlp", new_callable=AsyncMock, return_value=dummy_item) as mock_ytdlp:
                    raw_url = "https://fb.watch/xyz123/"
                    item = await self.pipeline.download(raw_url)

                    mock_resolve.assert_awaited_once_with("https://fb.watch/xyz123/")
                    mock_ytdlp.assert_awaited_once_with("https://www.facebook.com/reel/1195289147628387/")
                    self.assertEqual(item.source_url, raw_url)
        asyncio.run(run())


class TestTelegramBotFacebookVariants(unittest.TestCase):
    """Kiểm tra TelegramBot Fast-Path nhận diện đầy đủ tất cả các biến thể Facebook URL."""

    def setUp(self):
        self.bot = TelegramBot.__new__(TelegramBot)

    def test_fastpath_detects_all_facebook_share_formats(self):
        test_urls = [
            "https://www.facebook.com/share/r/1195289147628387/",
            "https://facebook.com/share/r/1195289147628387",
            "https://m.facebook.com/share/r/1195289147628387/",
            "https://web.facebook.com/share/r/1195289147628387/",
            "https://fb.com/share/r/1195289147628387/",
            "https://www.facebook.com/share/v/890abcdef/",
            "https://m.facebook.com/share/v/890abcdef/?mibextid=wwXIfr",
            "https://fb.com/share/v/890abcdef",
        ]
        for url in test_urls:
            with self.subTest(url=url):
                res = self.bot._detect_fastpath_media_download(url)
                self.assertIsNotNone(res, f"Fast-path failed to detect URL: {url}")
                self.assertEqual(res[0], url)

    def test_fastpath_strips_brackets_and_trailing_punctuation(self):
        """Tin nhắn chứa link trong ngoặc hoặc dấu câu phải được bóc tách chính xác."""
        cases = [
            ("<https://www.facebook.com/share/r/1195289147628387/>", "https://www.facebook.com/share/r/1195289147628387/"),
            ("[https://www.facebook.com/share/r/1195289147628387/]", "https://www.facebook.com/share/r/1195289147628387/"),
            ("(https://www.facebook.com/share/r/1195289147628387/)", "https://www.facebook.com/share/r/1195289147628387/"),
            ("tải clip này giúp anh https://www.facebook.com/share/r/1195289147628387/!", "https://www.facebook.com/share/r/1195289147628387/"),
        ]
        for text, expected_url in cases:
            with self.subTest(text=text):
                res = self.bot._detect_fastpath_media_download(text)
                self.assertIsNotNone(res, f"Failed on text: {text}")
                self.assertEqual(res[0], expected_url)


if __name__ == "__main__":
    unittest.main()
