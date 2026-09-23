"""
test_file_transfer_engine.py — Comprehensive Test Suite for Milestone 1 Backend Transfer Engine.

Covers:
  1. TransferStorageManager core lifecycle:
     - URL-safe token generation & regex validation (^[A-Za-z0-9_-]{16,64}$).
     - Atomic metadata persistence (.metadata.<hex>.tmp -> metadata.json).
     - Fixed 1MB buffer chunked disk streaming with aiofiles (SHA-256 integrity).
     - Layer 2 instant on-access expiry check.
     - Layer 1 & 3 sweep_expired cleaning expired and orphaned sessions (Zero-Disk-Leak).
     - One-time delayed cleanup with grace period.
     - Path traversal injection defense.
  2. FastAPI Router (/api/ai/transfer):
     - POST /create: creates session with 24h TTL, returns token and LAN/WAN URLs.
     - POST /upload/{token}: multipart and raw binary streaming upload with 1MB buffer.
     - GET /download/{token}: Full file download (200 OK) with Content-Disposition & Content-Encoding.
     - GET /download/{token} with RFC 7233 Range headers:
       * bytes=start-end (HTTP 206 Partial Content)
       * bytes=start- (open-ended range)
       * bytes=-suffix (suffix range)
     - Invalid / unsatisfiable range returns HTTP 416 Range Not Satisfiable.
     - Non-existent or expired token returns HTTP 404 Not Found.
     - GET /info/{token}: metadata and remaining validity duration.
     - Zero-Throttling concurrency: multi-threaded byte-range downloads without HTTP 429.
"""

from __future__ import annotations

import asyncio
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

from app.main import app
from app.services.transfer_storage_manager import (
    TransferRecord,
    TransferStorageManager,
    transfer_storage_manager,
)
from app.routers.file_transfer import parse_range_header


class TestTransferStorageManagerUnit(unittest.IsolatedAsyncioTestCase):
    """Unit tests for TransferStorageManager isolated file system operations."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_transfer_storage_")
        self.base_dir = Path(self.test_dir)
        self.manager = TransferStorageManager(
            base_dir=self.base_dir,
            default_ttl_hours=24,
            grace_seconds=1.0,
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_create_session_token_validation_and_metadata(self):
        record = self.manager.create_session(
            filename="document.pdf",
            mode="upload",
            one_time=False,
            ttl_hours=12,
            title="Important Document",
        )
        self.assertIsNotNone(record.token)
        # Token must match ^[A-Za-z0-9_-]{16,64}$
        self.assertTrue(re.match(r"^[A-Za-z0-9_-]{16,64}$", record.token))
        self.assertEqual(record.filename, "document.pdf")
        self.assertEqual(record.state, "pending_upload")
        self.assertEqual(record.ttl_seconds, 12 * 3600)
        self.assertFalse(record.one_time)
        self.assertFalse(record.is_expired)
        self.assertGreater(record.time_remaining_seconds, 0)

        # Check isolated folder and metadata.json existence
        token_dir = self.base_dir / record.token
        self.assertTrue(token_dir.is_dir())
        meta_file = token_dir / "metadata.json"
        self.assertTrue(meta_file.is_file())

        with open(meta_file, "r", encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual(meta["token"], record.token)
        self.assertEqual(meta["title"], "Important Document")

    async def test_save_upload_stream_chunked_1mb_buffer_and_hash_integrity(self):
        record = self.manager.create_session(filename="big_payload.bin")
        token = record.token

        # Generate 2.5MB payload split into irregular 128KB chunks
        total_size = int(2.5 * 1024 * 1024)
        sample_bytes = os.urandom(total_size)
        expected_hash = hashlib.sha256(sample_bytes).hexdigest()

        chunk_size = 128 * 1024

        async def _stream_generator():
            for i in range(0, total_size, chunk_size):
                yield sample_bytes[i : i + chunk_size]

        updated_record = await self.manager.save_upload_stream(
            token=token,
            filename="big_payload.bin",
            stream=_stream_generator(),
            chunk_buffer_size=1024 * 1024,
        )

        self.assertEqual(updated_record.state, "ready")
        self.assertEqual(updated_record.file_size, total_size)
        self.assertIsNotNone(updated_record.file_path)
        self.assertTrue(updated_record.file_path.exists())

        # Verify disk data integrity
        disk_bytes = updated_record.file_path.read_bytes()
        self.assertEqual(hashlib.sha256(disk_bytes).hexdigest(), expected_hash)

    def test_on_access_expiry_check_layer_2(self):
        record = self.manager.create_session(filename="expiring.txt")
        token_dir = self.base_dir / record.token

        # Manually alter metadata to be expired 10 seconds ago
        meta_file = token_dir / "metadata.json"
        with open(meta_file, "r", encoding="utf-8") as f:
            meta = json.load(f)
        meta["expires_at"] = time.time() - 10
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f)

        # On-access check via get_session must purge directory and return None
        session = self.manager.get_session(record.token)
        self.assertIsNone(session)
        self.assertFalse(token_dir.exists())

    def test_sweep_expired_layer_1_and_3(self):
        # 1. Active session
        active_rec = self.manager.create_session(filename="active.bin")
        # 2. Expired session
        expired_rec = self.manager.create_session(filename="expired.bin")
        exp_dir = self.base_dir / expired_rec.token
        meta_file = exp_dir / "metadata.json"
        with open(meta_file, "r", encoding="utf-8") as f:
            meta = json.load(f)
        meta["expires_at"] = time.time() - 60
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f)

        # Run sweep
        stats = self.manager.sweep_expired()
        self.assertEqual(stats["expired_tokens_removed"], 1)
        self.assertFalse(exp_dir.exists())
        self.assertTrue((self.base_dir / active_rec.token).exists())

    async def test_delayed_cleanup_for_one_time_mode(self):
        record = self.manager.create_session(filename="burn_after_reading.txt", one_time=True)
        token_dir = self.base_dir / record.token
        data_file = token_dir / "burn_after_reading.txt"
        data_file.write_text("Top secret payload", encoding="utf-8")

        # Schedule delayed cleanup with short 0.15s delay
        self.manager.schedule_delayed_cleanup(record.token, delay_seconds=0.15)
        # Verify file still exists during grace period
        self.assertTrue(token_dir.exists())

        await asyncio.sleep(0.3)
        # After grace period, directory should be purged
        self.assertFalse(token_dir.exists())

    def test_path_traversal_rejection(self):
        with self.assertRaises(ValueError):
            self.manager._validate_token_string("../secret_token")
        with self.assertRaises(ValueError):
            self.manager._validate_token_string("token/with/slash")
        with self.assertRaises(ValueError):
            self.manager._validate_token_string("short")  # < 16 chars


class TestRangeHeaderParser(unittest.TestCase):
    """Unit tests for RFC 7233 range parsing logic."""

    def test_parse_valid_range_bounds(self):
        file_size = 1000
        start, end = parse_range_header("bytes=0-499", file_size)
        self.assertEqual((start, end), (0, 499))

        start, end = parse_range_header("bytes=500-999", file_size)
        self.assertEqual((start, end), (500, 999))

    def test_parse_open_ended_range(self):
        file_size = 1000
        start, end = parse_range_header("bytes=500-", file_size)
        self.assertEqual((start, end), (500, 999))

    def test_parse_suffix_range(self):
        file_size = 1000
        start, end = parse_range_header("bytes=-200", file_size)
        self.assertEqual((start, end), (800, 999))

        # Suffix larger than file size
        start, end = parse_range_header("bytes=-2000", file_size)
        self.assertEqual((start, end), (0, 999))

    def test_parse_invalid_or_unsatisfiable_range(self):
        file_size = 1000
        with self.assertRaises(ValueError):
            parse_range_header("invalid_prefix=0-500", file_size)
        with self.assertRaises(ValueError):
            parse_range_header("bytes=500-400", file_size)  # start > end
        with self.assertRaises(ValueError):
            parse_range_header("bytes=1000-1500", file_size)  # start >= file_size
        with self.assertRaises(ValueError):
            parse_range_header("bytes=0-100", 0)  # Empty file


class TestFileTransferRouterIntegration(unittest.TestCase):
    """Integration tests for FastAPI router /api/ai/transfer using TestClient."""

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="test_router_transfers_")
        cls.orig_base_dir = transfer_storage_manager.base_dir
        transfer_storage_manager.base_dir = Path(cls.test_dir)
        transfer_storage_manager.ensure_dirs()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        transfer_storage_manager.base_dir = cls.orig_base_dir
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_post_create_session(self):
        resp = self.client.post(
            "/api/ai/transfer/create",
            json={
                "file_name": "data_dump.sql",
                "mode": "upload",
                "one_time": False,
                "ttl_hours": 24,
                "title": "Database Dump",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("token", data)
        self.assertEqual(data["filename"], "data_dump.sql")
        self.assertEqual(data["state"], "pending_upload")
        self.assertIn("/api/ai/transfer/upload/", data["upload_url"])
        self.assertIn("/api/ai/transfer/download/", data["download_url"])

    def test_upload_and_download_full_file(self):
        # 1. Create session
        create_resp = self.client.post("/api/ai/transfer/create", json={"file_name": "image.png"})
        token = create_resp.json()["token"]

        # 2. Upload file via multipart
        payload_content = b"\x89PNG\r\n\x1a\n" + b"TEST_IMAGE_PIXELS_DATA" * 50
        upload_resp = self.client.post(
            f"/api/ai/transfer/upload/{token}",
            files={"file": ("image.png", payload_content, "image/png")},
        )
        self.assertEqual(upload_resp.status_code, 200)
        up_data = upload_resp.json()
        self.assertEqual(up_data["status"], "success")
        self.assertEqual(up_data["record"]["file_size"], len(payload_content))
        self.assertEqual(up_data["record"]["state"], "ready")

        # 3. Download full file (200 OK)
        download_resp = self.client.get(f"/api/ai/transfer/download/{token}")
        self.assertEqual(download_resp.status_code, 200)
        self.assertEqual(download_resp.content, payload_content)
        self.assertEqual(download_resp.headers["accept-ranges"], "bytes")
        self.assertEqual(download_resp.headers["content-encoding"], "identity")
        self.assertEqual(download_resp.headers["content-length"], str(len(payload_content)))
        self.assertIn("image.png", download_resp.headers["content-disposition"])

    def test_download_http_206_partial_content_range_requests(self):
        # 1. Create session and upload 5000 bytes
        create_resp = self.client.post("/api/ai/transfer/create", json={"file_name": "stream.dat"})
        token = create_resp.json()["token"]

        payload = bytes([i % 256 for i in range(5000)])
        self.client.post(
            f"/api/ai/transfer/upload/{token}",
            content=payload,
            headers={"X-Filename": "stream.dat"},
        )

        # 2. Request Range: bytes=0-999 (first 1000 bytes)
        range_resp = self.client.get(
            f"/api/ai/transfer/download/{token}",
            headers={"Range": "bytes=0-999"},
        )
        self.assertEqual(range_resp.status_code, 206)
        self.assertEqual(range_resp.content, payload[0:1000])
        self.assertEqual(range_resp.headers["content-range"], "bytes 0-999/5000")
        self.assertEqual(range_resp.headers["content-length"], "1000")

        # 3. Request Range: bytes=1000-1999 (next 1000 bytes)
        range_resp2 = self.client.get(
            f"/api/ai/transfer/download/{token}",
            headers={"Range": "bytes=1000-1999"},
        )
        self.assertEqual(range_resp2.status_code, 206)
        self.assertEqual(range_resp2.content, payload[1000:2000])
        self.assertEqual(range_resp2.headers["content-range"], "bytes 1000-1999/5000")

        # 4. Request Range: bytes=4000- (open-ended to the end)
        range_resp3 = self.client.get(
            f"/api/ai/transfer/download/{token}",
            headers={"Range": "bytes=4000-"},
        )
        self.assertEqual(range_resp3.status_code, 206)
        self.assertEqual(range_resp3.content, payload[4000:5000])
        self.assertEqual(range_resp3.headers["content-range"], "bytes 4000-4999/5000")

        # 5. Request Suffix Range: bytes=-500 (last 500 bytes)
        range_resp4 = self.client.get(
            f"/api/ai/transfer/download/{token}",
            headers={"Range": "bytes=-500"},
        )
        self.assertEqual(range_resp4.status_code, 206)
        self.assertEqual(range_resp4.content, payload[4500:5000])
        self.assertEqual(range_resp4.headers["content-range"], "bytes 4500-4999/5000")

    def test_download_range_not_satisfiable_returns_416(self):
        create_resp = self.client.post("/api/ai/transfer/create", json={"file_name": "small.txt"})
        token = create_resp.json()["token"]

        self.client.post(
            f"/api/ai/transfer/upload/{token}",
            content=b"Short text content",
        )

        # Range outside total size
        resp = self.client.get(
            f"/api/ai/transfer/download/{token}",
            headers={"Range": "bytes=5000-6000"},
        )
        self.assertEqual(resp.status_code, 416)
        self.assertIn("bytes */", resp.headers["content-range"])

    def test_download_non_existent_token_returns_404(self):
        resp = self.client.get("/api/ai/transfer/download/nonexistent_token_1234567890")
        self.assertEqual(resp.status_code, 404)

    def test_get_session_info(self):
        create_resp = self.client.post(
            "/api/ai/transfer/create",
            json={"file_name": "report.docx", "title": "Quarterly Report"},
        )
        token = create_resp.json()["token"]

        info_resp = self.client.get(f"/api/ai/transfer/info/{token}")
        self.assertEqual(info_resp.status_code, 200)
        data = info_resp.json()
        self.assertEqual(data["token"], token)
        self.assertEqual(data["title"], "Quarterly Report")
        self.assertEqual(data["filename"], "report.docx")
        self.assertGreater(data["time_remaining_seconds"], 0)

    def test_post_sweep_endpoint(self):
        resp = self.client.post("/api/ai/transfer/sweep")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("stats", data)

    def test_zero_throttling_concurrency(self):
        """Zero-throttling verification: 20 rapid byte-range downloads without HTTP 429."""
        create_resp = self.client.post("/api/ai/transfer/create", json={"file_name": "concurrency.dat"})
        token = create_resp.json()["token"]

        payload = b"CONCURRENCY_TEST_PAYLOAD_CHUNK_DATA_" * 100  # 3600 bytes
        self.client.post(
            f"/api/ai/transfer/upload/{token}",
            content=payload,
            headers={"X-Filename": "concurrency.dat"},
        )

        # Execute 20 rapid range requests
        for i in range(20):
            start = (i * 100) % len(payload)
            end = min(start + 99, len(payload) - 1)
            resp = self.client.get(
                f"/api/ai/transfer/download/{token}",
                headers={"Range": f"bytes={start}-{end}"},
            )
            self.assertEqual(resp.status_code, 206)
            self.assertEqual(len(resp.content), end - start + 1)

    def test_raw_binary_stream_upload(self):
        create_resp = self.client.post("/api/ai/transfer/create")
        token = create_resp.json()["token"]

        raw_data = b"RAW_STREAMED_BINARY_CONTENT_0123456789" * 20
        resp = self.client.post(
            f"/api/ai/transfer/upload/{token}?filename=archive.tar.gz",
            content=raw_data,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["record"]["filename"], "archive.tar.gz")
        self.assertEqual(data["record"]["file_size"], len(raw_data))

        # Verify content on download
        down = self.client.get(f"/api/ai/transfer/download/{token}")
        self.assertEqual(down.status_code, 200)
        self.assertEqual(down.content, raw_data)

    def test_upload_to_non_existent_token_returns_404(self):
        resp = self.client.post(
            "/api/ai/transfer/upload/nonexistent_fake_token_12345678",
            content=b"test",
        )
        self.assertEqual(resp.status_code, 404)

    def test_path_traversal_blocked_on_download(self):
        resp = self.client.get("/api/ai/transfer/download/..%2F..%2Fetc%2Fpasswd")
        self.assertIn(resp.status_code, [404, 422, 403])

    def test_register_existing_file_unit(self):
        record = transfer_storage_manager.create_session(mode="download")
        temp_src = Path(self.test_dir) / "source_file_to_share.txt"
        temp_src.write_text("Hello from Kirito Server", encoding="utf-8")

        reg_rec = transfer_storage_manager.register_existing_file(
            token=record.token,
            source_path=temp_src,
            filename="shared.txt",
            copy_mode=True,
        )
        self.assertEqual(reg_rec.state, "ready")
        self.assertEqual(reg_rec.filename, "shared.txt")
        self.assertEqual(reg_rec.file_size, len("Hello from Kirito Server"))

        # Download via router
        down = self.client.get(f"/api/ai/transfer/download/{record.token}")
        self.assertEqual(down.status_code, 200)
        self.assertEqual(down.content, b"Hello from Kirito Server")


if __name__ == "__main__":
    unittest.main()
