import asyncio
from io import BytesIO
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.services.universal_downloader import (
    UniversalDownloader,
    download_direct_file,
    sanitize_filename,
    parse_filename_from_headers,
    extract_filename_from_url,
)


class TestUniversalDownloader(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_downloader_")
        self.downloader = UniversalDownloader(download_dir=Path(self.temp_dir))

    async def asyncTearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_sanitize_filename(self):
        self.assertEqual(sanitize_filename("../../etc/passwd"), "passwd")
        self.assertEqual(sanitize_filename(r"..\..\windows\win.ini"), "win.ini")
        self.assertEqual(sanitize_filename("valid_file.zip"), "valid_file.zip")
        self.assertEqual(sanitize_filename("my file (1).tar.gz"), "my file (1).tar.gz")
        self.assertEqual(sanitize_filename(""), "downloaded_file.bin")
        self.assertEqual(sanitize_filename(".."), "downloaded_file.bin")
        self.assertEqual(sanitize_filename("..//.."), "downloaded_file.bin")

    def test_parse_filename_from_headers(self):
        headers1 = httpx.Headers({"content-disposition": 'attachment; filename="archive.zip"'})
        self.assertEqual(parse_filename_from_headers(headers1), "archive.zip")

        headers2 = httpx.Headers({"content-disposition": "attachment; filename*=UTF-8''document%20sample.pdf"})
        self.assertEqual(parse_filename_from_headers(headers2), "document sample.pdf")

        headers3 = httpx.Headers({"content-type": "application/json"})
        self.assertEqual(parse_filename_from_headers(headers3, fallback="default.bin"), "default.bin")

    def test_extract_filename_from_url(self):
        self.assertEqual(extract_filename_from_url("https://example.com/files/release-v1.0.tar.gz"), "release-v1.0.tar.gz")
        self.assertEqual(extract_filename_from_url("https://example.com/files/image.png?version=2"), "image.png")
        self.assertEqual(extract_filename_from_url("https://example.com/"), "downloaded_file.bin")

    async def test_download_direct_file_empty_url(self):
        res = await self.downloader.download_direct_file("")
        self.assertEqual(res["status"], "error")
        self.assertIn("không được để trống", res["message"])

    async def test_download_direct_file_success_streaming(self):
        test_payload = b"Hello, this is chunk 1." + b" And this is chunk 2."
        mock_head_resp = MagicMock()
        mock_head_resp.status_code = 200
        mock_head_resp.headers = httpx.Headers({
            "content-length": str(len(test_payload)),
            "content-type": "application/octet-stream",
            "accept-ranges": "bytes",
            "content-disposition": 'attachment; filename="test_sample.bin"',
        })

        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.headers = mock_head_resp.headers
        mock_get_resp.reason_phrase = "OK"

        async def aiter_chunks(chunk_size=65536):
            yield b"Hello, this is chunk 1."
            yield b" And this is chunk 2."

        mock_get_resp.aiter_bytes = aiter_chunks

        # Mock stream context manager
        stream_cm = AsyncMock()
        stream_cm.__aenter__.return_value = mock_get_resp
        stream_cm.__aexit__.return_value = None

        mock_client = AsyncMock()
        mock_client.head.return_value = mock_head_resp
        mock_client.stream = MagicMock(return_value=stream_cm)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            res = await self.downloader.download_direct_file("https://example.com/test_sample.bin")

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["file_name"], "test_sample.bin")
        self.assertTrue(Path(res["file_path"]).exists())
        self.assertEqual(res["file_size_bytes"], len(test_payload))
        self.assertTrue(res["resume_supported"])
        self.assertFalse(res["resumed"])

        # Verify content written
        with open(res["file_path"], "rb") as fp:
            self.assertEqual(fp.read(), test_payload)

    async def test_download_direct_file_with_custom_filename(self):
        test_payload = b"Custom filename test payload."
        mock_head_resp = MagicMock()
        mock_head_resp.status_code = 200
        mock_head_resp.headers = httpx.Headers({
            "content-length": str(len(test_payload)),
            "content-type": "text/plain",
        })

        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.headers = mock_head_resp.headers
        mock_get_resp.reason_phrase = "OK"

        async def aiter_chunks(chunk_size=65536):
            yield test_payload

        mock_get_resp.aiter_bytes = aiter_chunks
        stream_cm = AsyncMock()
        stream_cm.__aenter__.return_value = mock_get_resp
        stream_cm.__aexit__.return_value = None

        mock_client = AsyncMock()
        mock_client.head.return_value = mock_head_resp
        mock_client.stream = MagicMock(return_value=stream_cm)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            res = await self.downloader.download_direct_file(
                "https://example.com/random.bin",
                custom_filename="my_clean_doc.txt",
            )

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["file_name"], "my_clean_doc.txt")
        self.assertTrue(Path(res["file_path"]).exists())

    async def test_download_direct_file_resume_range_support(self):
        part1 = b"First half of payload."
        part2 = b" Second half of payload."
        total_len = len(part1) + len(part2)

        # Pre-create .part file on disk simulating interrupted download
        target_name = "resumable.dat"
        part_path = Path(self.temp_dir) / f"{target_name}.part"
        with open(part_path, "wb") as f:
            f.write(part1)

        mock_head_resp = MagicMock()
        mock_head_resp.status_code = 200
        mock_head_resp.headers = httpx.Headers({
            "content-length": str(total_len),
            "content-type": "application/octet-stream",
            "accept-ranges": "bytes",
        })

        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 206  # 206 Partial Content
        mock_get_resp.headers = httpx.Headers({
            "content-length": str(len(part2)),
            "content-range": f"bytes {len(part1)}-{total_len-1}/{total_len}",
            "accept-ranges": "bytes",
        })
        mock_get_resp.reason_phrase = "Partial Content"

        async def aiter_chunks(chunk_size=65536):
            yield part2

        mock_get_resp.aiter_bytes = aiter_chunks
        stream_cm = AsyncMock()
        stream_cm.__aenter__.return_value = mock_get_resp
        stream_cm.__aexit__.return_value = None

        mock_client = AsyncMock()
        mock_client.head.return_value = mock_head_resp
        mock_client.stream = MagicMock(return_value=stream_cm)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            res = await self.downloader.download_direct_file(
                f"https://example.com/{target_name}",
            )

        self.assertEqual(res["status"], "success")
        self.assertTrue(res["resumed"])
        self.assertTrue(Path(res["file_path"]).exists())
        self.assertEqual(res["file_size_bytes"], total_len)

        with open(res["file_path"], "rb") as f:
            self.assertEqual(f.read(), part1 + part2)

    async def test_download_direct_file_server_error(self):
        mock_head_resp = MagicMock()
        mock_head_resp.status_code = 200
        mock_head_resp.headers = httpx.Headers({})

        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 404
        mock_get_resp.headers = httpx.Headers({})
        mock_get_resp.reason_phrase = "Not Found"

        stream_cm = AsyncMock()
        stream_cm.__aenter__.return_value = mock_get_resp
        stream_cm.__aexit__.return_value = None

        mock_client = AsyncMock()
        mock_client.head.return_value = mock_head_resp
        mock_client.stream = MagicMock(return_value=stream_cm)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            res = await self.downloader.download_direct_file("https://example.com/notfound.iso")

        self.assertEqual(res["status"], "error")
        self.assertIn("404", res["message"])

    async def test_download_direct_file_timeout(self):
        mock_client = AsyncMock()
        mock_client.head.side_effect = httpx.ReadTimeout("Socket timeout")
        mock_client.stream = MagicMock(side_effect=httpx.ReadTimeout("Socket timeout"))

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            res = await self.downloader.download_direct_file("https://example.com/timeout.iso")

        self.assertEqual(res["status"], "error")
        self.assertIn("thời gian chờ", res["message"].lower())

    async def test_download_direct_file_disk_space_guard(self):
        mock_head_resp = MagicMock()
        mock_head_resp.status_code = 200
        mock_head_resp.headers = httpx.Headers({
            "content-length": str(5 * 1024 * 1024 * 1024),  # 5 GB
        })

        mock_client = AsyncMock()
        mock_client.head.return_value = mock_head_resp

        # Mock disk free space to only 100MB
        mock_usage = MagicMock()
        mock_usage.free = 100 * 1024 * 1024

        with patch("httpx.AsyncClient") as mock_client_cls, patch("shutil.disk_usage", return_value=mock_usage):
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            res = await self.downloader.download_direct_file("https://example.com/huge.iso")

        self.assertEqual(res["status"], "error")
        self.assertIn("Không đủ dung lượng", res["message"])

    def test_cleanup_temp_files(self):
        # Create an old .part file
        old_part = Path(self.temp_dir) / "old.part"
        old_part.write_bytes(b"old")
        # Set mtime to 2 days ago
        two_days_ago = time.time() - (2 * 86400)
        os.utime(old_part, (two_days_ago, two_days_ago))

        # Create a fresh .part file
        fresh_part = Path(self.temp_dir) / "fresh.part"
        fresh_part.write_bytes(b"fresh")

        purged = self.downloader.cleanup_temp_files(max_age_seconds=86400)
        self.assertEqual(purged, 1)
        self.assertFalse(old_part.exists())
        self.assertTrue(fresh_part.exists())


if __name__ == "__main__":
    unittest.main()
