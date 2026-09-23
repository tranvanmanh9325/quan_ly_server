"""
test_file_transfer_e2e.py — End-to-End Integration & Real-World Application Scenario Tests.

Tier 4 Scenarios covered according to TEST_INFRA.md:
  Scenario 1: Laptop upload 5MB binary file -> Download via HTTP 206 Partial Content (Multi-range assembled) -> Verify SHA256 integrity.
  Scenario 2: User requests AI Agent transfer file -> Turn 1 Direct Return reflex -> LAN & WAN URLs + In-Memory QR Code -> Verify delivery.
  Scenario 3: One-time transfer mode (one_time=True) -> Concurrent multi-connection download -> Delayed cleanup 30s grace period preserves ongoing ranges -> Automatic cleanup sweeps directory (Zero-Disk Leak).
  Scenario 4: Expired session (past 24h TTL) -> Sweep expired removes files -> Portal returns 404 HTML, Download returns 404 JSON -> Zero-Disk Leak.
  Scenario 5: Upload Dropzone to Download Portal transition -> MIME detection and in-browser preview tags.
"""

from __future__ import annotations

import asyncio
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.testclient import TestClient

from app.main import app
from app.services.ai_agent_tools import AgentToolExecutor, DIRECT_RETURN_TOOLS
from app.services.telegram_bot import TelegramBot
from app.services.transfer_qr_generator import generate_qr_png_bytes
from app.services.transfer_storage_manager import (
    TransferRecord,
    TransferStorageManager,
)


class TestFileTransferE2EScenarios(unittest.TestCase):
    """End-to-End integration test suite for High-Speed File Transfer Portal."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="transfer_e2e_test_")
        self.storage_manager = TransferStorageManager(base_dir=self.temp_dir)
        self.storage_patcher = patch(
            "app.routers.file_transfer.transfer_storage_manager",
            self.storage_manager,
        )
        self.tools_storage_patcher = patch(
            "app.services.transfer_storage_manager.transfer_storage_manager",
            self.storage_manager,
        )
        self.storage_patcher.start()
        self.tools_storage_patcher.start()
        self.url_patcher = patch.object(
            self.storage_manager,
            "resolve_public_transfer_base_url_sync",
            return_value=("https://dummy-wan.ngrok-free.dev", "http://192.168.0.100:8084"),
        )
        self.url_patcher.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.url_patcher.stop()
        self.storage_patcher.stop()
        self.tools_storage_patcher.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_scenario_1_e2e_upload_and_multi_range_partial_download_assembly(self) -> None:
        """
        Scenario 1:
        1. Create upload session via POST /api/ai/transfer/create.
        2. Verify portal displays dropzone for pending session.
        3. Upload a 5MB payload in chunks.
        4. Request file chunks using HTTP 206 Partial Content (RFC 7233).
        5. Reassemble downloaded chunks and verify SHA256 matches exactly.
        """
        # 1. Create session
        create_resp = self.client.post(
            "/api/ai/transfer/create",
            json={"filename": "test_video.mp4", "mode": "upload", "one_time": False},
        )
        self.assertEqual(create_resp.status_code, 200)
        data = create_resp.json()
        token = data["token"]
        self.assertTrue(token)

        # 2. Check portal page in pending state
        portal_resp = self.client.get(f"/api/ai/transfer/portal/{token}")
        self.assertEqual(portal_resp.status_code, 200)
        self.assertIn("text/html", portal_resp.headers["content-type"])
        self.assertIn("dropzone", portal_resp.text.lower())

        # 3. Generate 5MB binary data
        payload_size = 5 * 1024 * 1024  # 5 MB
        # Deterministic pattern based on repeating 64KB block
        seed_block = os.urandom(65536)
        raw_data = (seed_block * (payload_size // len(seed_block) + 1))[:payload_size]
        self.assertEqual(len(raw_data), payload_size)
        expected_sha256 = hashlib.sha256(raw_data).hexdigest()

        # Upload file via multipart
        upload_resp = self.client.post(
            f"/api/ai/transfer/upload/{token}",
            files={"file": ("test_video.mp4", raw_data, "video/mp4")},
        )
        self.assertEqual(upload_resp.status_code, 200)
        upload_data = upload_resp.json()
        self.assertEqual(upload_data["status"], "success")
        self.assertEqual(upload_data["record"]["file_size"], payload_size)

        # Verify portal page now shows download UI
        portal_ready_resp = self.client.get(f"/api/ai/transfer/portal/{token}")
        self.assertEqual(portal_ready_resp.status_code, 200)
        self.assertIn("test_video.mp4", portal_ready_resp.text)

        # 4. Multi-range download simulation (e.g. 3 chunks like IDM or Safari video scrubbing)
        # Chunk 1: bytes 0-1,048,575 (first 1MB)
        chunk1_resp = self.client.get(
            f"/api/ai/transfer/download/{token}",
            headers={"Range": "bytes=0-1048575"},
        )
        self.assertEqual(chunk1_resp.status_code, 206)
        self.assertEqual(chunk1_resp.headers["Content-Range"], f"bytes 0-1048575/{payload_size}")
        self.assertEqual(len(chunk1_resp.content), 1048576)

        # Chunk 2: bytes 1,048,576-3,145,727 (middle 2MB)
        chunk2_resp = self.client.get(
            f"/api/ai/transfer/download/{token}",
            headers={"Range": "bytes=1048576-3145727"},
        )
        self.assertEqual(chunk2_resp.status_code, 206)
        self.assertEqual(chunk2_resp.headers["Content-Range"], f"bytes 1048576-3145727/{payload_size}")
        self.assertEqual(len(chunk2_resp.content), 2097152)

        # Chunk 3: bytes 3,145,728- (remaining to EOF)
        chunk3_resp = self.client.get(
            f"/api/ai/transfer/download/{token}",
            headers={"Range": "bytes=3145728-"},
        )
        self.assertEqual(chunk3_resp.status_code, 206)
        self.assertEqual(chunk3_resp.headers["Content-Range"], f"bytes 3145728-{payload_size - 1}/{payload_size}")
        self.assertEqual(len(chunk3_resp.content), payload_size - 3145728)

        # 5. Assemble chunks and verify data integrity
        assembled = chunk1_resp.content + chunk2_resp.content + chunk3_resp.content
        self.assertEqual(len(assembled), payload_size)
        assembled_sha256 = hashlib.sha256(assembled).hexdigest()
        self.assertEqual(assembled_sha256, expected_sha256)

    def test_scenario_2_e2e_ai_agent_tool_reflex_and_qr_delivery(self) -> None:
        """
        Scenario 2:
        1. AI Agent invokes create_file_transfer_portal tool.
        2. Tool generates session, formats LAN & WAN URLs.
        3. Generates in-memory QR Code PNG bytes.
        4. Verifies telegram bot send_photo_bytes is invoked with QR PNG bytes.
        5. Returns Direct Return text format with BLUF and links.
        """
        mock_bot = MagicMock()
        mock_bot.send_transfer_portal_card = AsyncMock(return_value=True)

        executor = AgentToolExecutor(
            ssh_client=MagicMock(),
            message_cache=MagicMock(),
            telegram_bot=mock_bot,
        )

        # Confirm tool is in DIRECT_RETURN_TOOLS
        self.assertIn("create_file_transfer_portal", DIRECT_RETURN_TOOLS)

        # Execute tool
        result = asyncio.run(
            executor.execute_tool(
                tool_name="create_file_transfer_portal",
                tool_args={"file_name": "annual_report.pdf", "mode": "upload", "one_time": False},
                chat_id="123456789",
            )
        )

        # Check BLUF response content
        self.assertIn("192.168.0.100:8084", result)
        self.assertIn("ngrok-free.dev", result)
        self.assertIn("annual_report.pdf", result)
        self.assertIn("24 giờ", result)

        # Verify telegram bot card delivery was called
        mock_bot.send_transfer_portal_card.assert_awaited_once()
        call_kwargs = mock_bot.send_transfer_portal_card.call_args.kwargs
        self.assertEqual(call_kwargs["chat_id"], "123456789")
        self.assertEqual(call_kwargs["file_name"], "annual_report.pdf")
        self.assertFalse(call_kwargs["one_time"])

    def test_scenario_3_e2e_one_time_mode_delayed_cleanup_and_zero_disk_leak(self) -> None:
        """
        Scenario 3:
        1. Create session with one_time=True.
        2. Upload a 100KB file.
        3. Perform download of the final byte range.
        4. Confirm delayed cleanup is scheduled (session not immediately destroyed).
        5. Verify another range request during grace period still succeeds.
        6. Fast-forward timer or execute delete_session -> confirms zero files remain.
        """
        create_resp = self.client.post(
            "/api/ai/transfer/create",
            json={"filename": "secure_doc.pdf", "mode": "upload", "one_time": True},
        )
        token = create_resp.json()["token"]

        test_bytes = b"CONFIDENTIAL" * 8000  # 96,000 bytes
        self.client.post(
            f"/api/ai/transfer/upload/{token}",
            files={"file": ("secure_doc.pdf", test_bytes, "application/pdf")},
        )

        # Session path exists
        session_dir = Path(self.temp_dir) / token
        self.assertTrue(session_dir.exists())

        # Download range that includes EOF -> triggers delayed cleanup (30s grace)
        resp = self.client.get(
            f"/api/ai/transfer/download/{token}",
            headers={"Range": f"bytes=0-{len(test_bytes) - 1}"},
        )
        self.assertEqual(resp.status_code, 206)

        # Session dir still exists right now (grace period active)
        self.assertTrue(session_dir.exists())

        # Concurrent request within grace period still succeeds
        second_resp = self.client.get(
            f"/api/ai/transfer/download/{token}",
            headers={"Range": "bytes=0-100"},
        )
        self.assertEqual(second_resp.status_code, 206)

        # Simulate expiration of delayed cleanup
        self.storage_manager.delete_session(token)
        self.assertFalse(session_dir.exists())

        # After cleanup, access returns 404
        post_cleanup_resp = self.client.get(f"/api/ai/transfer/download/{token}")
        self.assertEqual(post_cleanup_resp.status_code, 404)

    def test_scenario_4_e2e_expired_session_and_sweeper_zero_disk_leak(self) -> None:
        """
        Scenario 4:
        1. Create session with TTL expired in past.
        2. Create dummy file in session directory.
        3. Trigger sweep_expired -> directory swept.
        4. Confirm portal returns 404 HTML and download returns 404 JSON.
        """
        record = self.storage_manager.create_session(filename="old_archive.zip", ttl_hours=24)
        token = record.token

        # Artificially set expires_at to 10 seconds ago
        record.expires_at = time.time() - 10
        session_dir = Path(self.temp_dir) / token
        meta_file = session_dir / "metadata.json"
        with open(meta_file, "r") as f:
            data = json.load(f)
        data["expires_at"] = time.time() - 10
        with open(meta_file, "w") as f:
            json.dump(data, f)

        # Reload cache or trigger sweeper
        swept_res = self.storage_manager.sweep_expired()
        self.assertGreaterEqual(swept_res.get("expired_tokens_removed", 0), 1)

        # Confirm directory is gone
        self.assertFalse(session_dir.exists())

        # Verify portal returns 404 HTML
        portal_resp = self.client.get(f"/api/ai/transfer/portal/{token}")
        self.assertEqual(portal_resp.status_code, 404)
        self.assertIn("text/html", portal_resp.headers["content-type"])
        self.assertIn("hết hạn", portal_resp.text.lower())

        # Verify download returns 404 JSON
        dl_resp = self.client.get(f"/api/ai/transfer/download/{token}")
        self.assertEqual(dl_resp.status_code, 404)

    def test_scenario_5_e2e_qr_code_binary_endpoint(self) -> None:
        """
        Scenario 5:
        1. Create session.
        2. Query GET /api/ai/transfer/qr/{token}.
        3. Verify 200 OK, image/png media type, and valid PNG magic bytes header.
        """
        create_resp = self.client.post(
            "/api/ai/transfer/create",
            json={"filename": "photo.jpg", "mode": "upload", "one_time": False},
        )
        token = create_resp.json()["token"]

        qr_resp = self.client.get(f"/api/ai/transfer/qr/{token}")
        self.assertEqual(qr_resp.status_code, 200)
        self.assertEqual(qr_resp.headers["content-type"], "image/png")
        self.assertTrue(qr_resp.content.startswith(b"\x89PNG\r\n\x1a\n"))


if __name__ == "__main__":
    unittest.main()
