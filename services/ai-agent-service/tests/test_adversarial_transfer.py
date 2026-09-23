"""
test_adversarial_transfer.py — Empirical Adversarial & Stress Testing Suite for Milestone 1.

Adversarial Verification Vectors & Diagnostic Harness:
  Vector 1: Bizarre / Malformed RFC 7233 Range Headers:
    - Range beyond file_size (e.g. 5000-6000 on 1000B file) -> HTTP 416
    - Inverted Range (start > end, e.g. 500-100, 999-0) -> HTTP 416
    - Suffix 0 byte (bytes=-0, bytes=-) -> HTTP 416
    - Malformed suffix and strange characters (bytes=abc-def, bytes=10-abc, bytes=--10, bytes=,, bytes= - ) -> HTTP 416
    - Huge range bound (bytes=0-999999999999999999999999999999) -> clips to file_size - 1 (HTTP 206)
    - Single-byte boundary ranges (bytes=0-0, bytes=999-999) -> HTTP 206, 1 byte
    - Range request on 0-byte file (bytes=0-0, bytes=0-) -> HTTP 416
    - Full download on 0-byte file -> HTTP 200 OK, Content-Length: 0

  Vector 2: Path Traversal & Injection Attacks:
    - Path traversal in token string: ../, ..\\, %2e%2e%2f, null bytes (%00), shell injection (; rm -rf /)
    - Path traversal in upload filename: ../../evil.sh, ..\\..\\evil.exe -> isolated within token_dir
    - [EMPIRICAL BUG 3]: Malformed / traversal tokens in GET /download/{token} cause unhandled 500 Internal Server Error instead of 400/404!
    - [EMPIRICAL BUG 4]: Path traversal in GET /download/{token}/{filename} leaks unsanitized path into Content-Disposition!

  Vector 3: Concurrency Race Conditions & Delayed Cleanup:
    - High concurrency multi-threaded downloads on one_time=True file.
    - Slower threads complete successfully because of 30s grace delayed cleanup.
    - Multiple overlapping delayed cleanup triggers reschedule cleanly.

  Vector 4: Edge Uploads, Zero-Byte Files & Interrupted Streams:
    - Uploading 0-byte file via multipart form-data and direct binary stream -> HTTP 200 OK
    - [EMPIRICAL BUG 1]: Premature GET /download/{token} on pending_upload session destructively purges token_dir, causing subsequent upload to fail with 404!
    - [EMPIRICAL BUG 2]: get_download_file() serves incomplete / aborted partial files because it does not verify state == 'ready'!

  Vector 5: Zero-Disk Leak Stress Harness:
    - Mass session generation (50 sessions: active, expired, corrupt).
    - Lifecycle churn: verify 100% disk reclamation for expired/deleted sessions with zero dangling files.
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
from unittest.mock import patch

from starlette.testclient import TestClient

from app.main import app
from app.services.transfer_storage_manager import (
    TransferRecord,
    TransferStorageManager,
    transfer_storage_manager,
)
from app.routers.file_transfer import parse_range_header


class TestAdversarialRangeHeaders(unittest.TestCase):
    """Adversarial stress-testing of Range header parsing and router responses."""

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="test_adv_range_")
        cls.orig_base_dir = transfer_storage_manager.base_dir
        transfer_storage_manager.base_dir = Path(cls.test_dir)
        transfer_storage_manager.ensure_dirs()
        cls.client = TestClient(app)

        # Create a standard 1000-byte test session
        create_resp = cls.client.post("/api/ai/transfer/create", json={"file_name": "range_test.dat"})
        cls.token = create_resp.json()["token"]
        cls.payload = bytes([i % 256 for i in range(1000)])
        cls.client.post(
            f"/api/ai/transfer/upload/{cls.token}",
            content=cls.payload,
            headers={"X-Filename": "range_test.dat"},
        )

        # Create a 0-byte test session
        create_zero = cls.client.post("/api/ai/transfer/create", json={"file_name": "empty.dat"})
        cls.zero_token = create_zero.json()["token"]
        cls.client.post(
            f"/api/ai/transfer/upload/{cls.zero_token}",
            content=b"",
            headers={"X-Filename": "empty.dat"},
        )

    @classmethod
    def tearDownClass(cls):
        transfer_storage_manager.base_dir = cls.orig_base_dir
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_range_beyond_file_size_returns_416(self):
        """Range start >= file_size or start-end entirely beyond file_size must return 416."""
        for range_hdr in ["bytes=1000-2000", "bytes=5000-6000", "bytes=1000-", "bytes=99999-100000"]:
            resp = self.client.get(
                f"/api/ai/transfer/download/{self.token}",
                headers={"Range": range_hdr},
            )
            self.assertEqual(
                resp.status_code, 416, f"Expected 416 for '{range_hdr}', got {resp.status_code}"
            )
            self.assertEqual(resp.headers.get("content-range"), "bytes */1000")

    def test_inverted_range_returns_416(self):
        """Inverted range where start > end must return 416."""
        for range_hdr in ["bytes=500-100", "bytes=999-0", "bytes=1-0", "bytes=800-200"]:
            resp = self.client.get(
                f"/api/ai/transfer/download/{self.token}",
                headers={"Range": range_hdr},
            )
            self.assertEqual(
                resp.status_code, 416, f"Expected 416 for inverted range '{range_hdr}', got {resp.status_code}"
            )
            self.assertEqual(resp.headers.get("content-range"), "bytes */1000")

    def test_suffix_zero_and_malformed_suffix_returns_416(self):
        """Suffix range of 0 byte (bytes=-0) or malformed suffix must return 416."""
        for range_hdr in ["bytes=-0", "bytes=-", "bytes=--10", "bytes=-abc", "bytes=--"]:
            resp = self.client.get(
                f"/api/ai/transfer/download/{self.token}",
                headers={"Range": range_hdr},
            )
            self.assertEqual(
                resp.status_code, 416, f"Expected 416 for suffix range '{range_hdr}', got {resp.status_code}"
            )

    def test_strange_and_non_numeric_characters_returns_416(self):
        """Range headers containing non-numeric strings, random characters or weird formats."""
        for range_hdr in [
            "bytes=abc-def",
            "bytes=10-abc",
            "bytes=abc-10",
            "bytes=10-20-30",
            "bytes=",
            "bytes=   ",
            "bytes=,",
            "bytes= - ",
            "bytes=None",
            "bytes=undefined",
            "items=0-100",
            "seconds=0-10",
        ]:
            resp = self.client.get(
                f"/api/ai/transfer/download/{self.token}",
                headers={"Range": range_hdr},
            )
            self.assertEqual(
                resp.status_code, 416, f"Expected 416 for strange range '{range_hdr}', got {resp.status_code}"
            )

    def test_range_with_internal_spaces_tolerated(self):
        """Python int() strips leading/trailing spaces, tolerating 'bytes=0 - 500'."""
        resp = self.client.get(
            f"/api/ai/transfer/download/{self.token}",
            headers={"Range": "bytes=0 - 500"},
        )
        self.assertEqual(resp.status_code, 206)
        self.assertEqual(len(resp.content), 501)
        self.assertEqual(resp.headers.get("content-range"), "bytes 0-500/1000")

    def test_huge_end_range_clips_to_file_size_returns_206(self):
        """RFC 7233: When end >= file_size, server clips end to file_size - 1 and returns 206."""
        huge_end = "9" * 30
        resp = self.client.get(
            f"/api/ai/transfer/download/{self.token}",
            headers={"Range": f"bytes=0-{huge_end}"},
        )
        self.assertEqual(resp.status_code, 206)
        self.assertEqual(len(resp.content), 1000)
        self.assertEqual(resp.content, self.payload)
        self.assertEqual(resp.headers.get("content-range"), "bytes 0-999/1000")

    def test_single_byte_boundary_ranges(self):
        """Exact single-byte requests at start (0-0) and end (999-999)."""
        # First byte
        resp_first = self.client.get(
            f"/api/ai/transfer/download/{self.token}",
            headers={"Range": "bytes=0-0"},
        )
        self.assertEqual(resp_first.status_code, 206)
        self.assertEqual(len(resp_first.content), 1)
        self.assertEqual(resp_first.content, self.payload[0:1])
        self.assertEqual(resp_first.headers.get("content-range"), "bytes 0-0/1000")
        self.assertEqual(resp_first.headers.get("content-length"), "1")

        # Last byte
        resp_last = self.client.get(
            f"/api/ai/transfer/download/{self.token}",
            headers={"Range": "bytes=999-999"},
        )
        self.assertEqual(resp_last.status_code, 206)
        self.assertEqual(len(resp_last.content), 1)
        self.assertEqual(resp_last.content, self.payload[999:1000])
        self.assertEqual(resp_last.headers.get("content-range"), "bytes 999-999/1000")

    def test_range_on_zero_byte_file_returns_416(self):
        """Any Range request on an empty (0-byte) file cannot be satisfied and must return 416."""
        for range_hdr in ["bytes=0-0", "bytes=0-", "bytes=-1", "bytes=0-10"]:
            resp = self.client.get(
                f"/api/ai/transfer/download/{self.zero_token}",
                headers={"Range": range_hdr},
            )
            self.assertEqual(
                resp.status_code, 416, f"Expected 416 for range on 0-byte file '{range_hdr}', got {resp.status_code}"
            )
            self.assertEqual(resp.headers.get("content-range"), "bytes */0")

    def test_full_download_on_zero_byte_file_returns_200(self):
        """Full download on a 0-byte file without Range header must return 200 OK with empty body."""
        resp = self.client.get(f"/api/ai/transfer/download/{self.zero_token}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.content), 0)
        self.assertEqual(resp.headers.get("content-length"), "0")


class TestPathTraversalAndInjection(unittest.TestCase):
    """Adversarial testing against directory traversal, token injection and filename tampering."""

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="test_adv_traversal_")
        cls.orig_base_dir = transfer_storage_manager.base_dir
        transfer_storage_manager.base_dir = Path(cls.test_dir)
        transfer_storage_manager.ensure_dirs()
        cls.client = TestClient(app)

        # Create a valid session to use as baseline
        create_resp = cls.client.post("/api/ai/transfer/create", json={"file_name": "target.txt"})
        cls.valid_token = create_resp.json()["token"]
        cls.client.post(f"/api/ai/transfer/upload/{cls.valid_token}", content=b"SECRET_DATA")

    @classmethod
    def tearDownClass(cls):
        transfer_storage_manager.base_dir = cls.orig_base_dir
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_token_regex_validation_blocks_malicious_tokens(self):
        """Test that _validate_token_string strictly blocks traversal, null bytes, and script injection."""
        manager = transfer_storage_manager
        malicious_tokens = [
            "../etc/passwd",
            "..\\..\\windows\\system32",
            "%2e%2e%2fetc%2fpasswd",
            "token/with/slash",
            "token\\with\\backslash",
            "token\x00with_null",
            "validtoken123456789\x00extra",
            "validtoken123456789;rm -rf /",
            "validtoken123456789' OR '1'='1",
            "<script>alert(1)</script>",
            "validtoken123456789$(whoami)",
            "validtoken123456789`id`",
            "validtoken 123456789",  # contains space
            "validtoken\t123456789",  # tab
            "validtoken\n123456789",  # newline
            "short",  # < 16 chars
            "a" * 65,  # > 64 chars
            "",  # empty
            "   ",  # spaces
            "../../../",
            "..\\..\\..\\",
        ]
        for bad_token in malicious_tokens:
            with self.subTest(bad_token=bad_token):
                with self.assertRaises(ValueError, msg=f"Token '{bad_token}' should have been rejected!"):
                    manager._validate_token_string(bad_token)

    def test_bug_malformed_token_causes_500_instead_of_4xx(self):
        """
        Adversarial test:
        In download_transfer_file, ValueError from _validate_token_string must be caught
        and return HTTP 404/400 instead of crashing into HTTP 500 Internal Server Error.
        """
        resp = self.client.get("/api/ai/transfer/download/..%5c..%5cwindows%5cwin.ini")
        self.assertIn(resp.status_code, [400, 404], f"Expected 400 or 404, got {resp.status_code}")
        self.assertNotEqual(resp.status_code, 500, "Malformed token crashed server with 500!")

    def test_bug_download_semantic_filename_traversal_leak_in_content_disposition(self):
        """
        Adversarial test:
        In /download/{token}/{filename}, 'filename' must be sanitized with Path(filename).name
        so traversal paths are never reflected into Content-Disposition.
        """
        traversal_filename = "..\\..\\windows\\win.ini"
        resp = self.client.get(f"/api/ai/transfer/download/{self.valid_token}/{traversal_filename}")
        self.assertEqual(resp.status_code, 200)

        # Check Content-Disposition header
        cd_header = resp.headers.get("content-disposition", "")
        self.assertNotIn("..", cd_header)
        self.assertNotIn("windows", cd_header)
        self.assertIn("win.ini", cd_header)

    def test_upload_filename_traversal_defense(self):
        """Ensure malicious filenames in upload cannot escape the isolated token directory."""
        create_resp = self.client.post("/api/ai/transfer/create")
        token = create_resp.json()["token"]
        token_dir = transfer_storage_manager.base_dir / token

        malicious_filenames = [
            "../../escaped_file.txt",
            "..\\..\\escaped_file_win.txt",
            "/etc/evil.sh",
            "C:\\Windows\\evil.exe",
            "....//....//evil.txt",
        ]

        for fname in malicious_filenames:
            with self.subTest(fname=fname):
                resp = self.client.post(
                    f"/api/ai/transfer/upload/{token}?filename={fname}",
                    content=b"ATTACK_PAYLOAD",
                )
                self.assertEqual(resp.status_code, 200)

                # Verify NO file was created outside the token directory
                parent_files = list(transfer_storage_manager.base_dir.glob("escaped*"))
                self.assertEqual(len(parent_files), 0, f"File escaped into base_dir: {parent_files}")

                # The uploaded file must reside strictly inside token_dir
                token_files = [f for f in token_dir.iterdir() if f.name != "metadata.json"]
                for f in token_files:
                    self.assertTrue(
                        str(f.resolve()).startswith(str(token_dir.resolve())),
                        f"File {f} is not inside {token_dir}",
                    )


class TestConcurrencyRaceConditions(unittest.IsolatedAsyncioTestCase):
    """Stress-testing concurrent downloads, one_time delayed cleanup and race conditions."""

    async def asyncSetUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_adv_concurrency_")
        self.orig_base_dir = transfer_storage_manager.base_dir
        transfer_storage_manager.base_dir = Path(self.test_dir)
        transfer_storage_manager.ensure_dirs()
        self.client = TestClient(app)

    async def asyncTearDown(self):
        transfer_storage_manager.base_dir = self.orig_base_dir
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_bug_concurrent_multi_connection_download_race_condition(self):
        """
        [EMPIRICAL BUG 2 REPORT]:
        When multiple concurrent threads / connections (e.g. IDM 8-16 connections) download byte-ranges,
        increment_count=True triggers un-synchronized _write_metadata_atomic (os.replace).
        Concurrent read/write collisions cause exceptions in _read_metadata (WinError 5 or JSONDecodeError).
        get_download_file() catches this and executes self.delete_session(token), causing concurrent threads
        to fail with 404 Not Found in the middle of active download streams!
        """
        create_resp = self.client.post(
            "/api/ai/transfer/create",
            json={"file_name": "shared_one_time.bin", "one_time": True},
        )
        token = create_resp.json()["token"]
        payload = os.urandom(100 * 1024)  # 100 KB
        expected_hash = hashlib.sha256(payload).hexdigest()

        self.client.post(
            f"/api/ai/transfer/upload/{token}",
            content=payload,
            headers={"X-Filename": "shared_one_time.bin"},
        )

        import concurrent.futures

        results = []
        errors = []

        def _download_worker(worker_id: int):
            try:
                if worker_id % 2 == 0:
                    resp = self.client.get(f"/api/ai/transfer/download/{token}")
                    if resp.status_code != 200:
                        errors.append((worker_id, resp.status_code, "non-200 full download"))
                    elif hashlib.sha256(resp.content).hexdigest() != expected_hash:
                        errors.append((worker_id, resp.status_code, "hash mismatch"))
                    else:
                        results.append((worker_id, 200))
                else:
                    time.sleep(0.02)
                    resp = self.client.get(
                        f"/api/ai/transfer/download/{token}",
                        headers={"Range": "bytes=0-51199"},
                    )
                    if resp.status_code != 206:
                        errors.append((worker_id, resp.status_code, "non-206 range download"))
                    elif resp.content != payload[:51200]:
                        errors.append((worker_id, resp.status_code, "range chunk mismatch"))
                    else:
                        results.append((worker_id, 206))
            except Exception as exc:
                errors.append((worker_id, -1, str(exc)))

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(_download_worker, i) for i in range(20)]
            concurrent.futures.wait(futures)

        print(f"CONCURRENCY TEST RESULTS: {len(results)} succeeded, {len(errors)} failed with errors: {errors}")
        self.assertEqual(len(errors), 0, f"Concurrent download errors encountered: {errors}")
        self.assertEqual(len(results), 20, f"Expected 20 successful downloads, got {len(results)}")

    test_concurrent_downloads_with_one_time_grace_period = test_bug_concurrent_multi_connection_download_race_condition

    def test_delayed_cleanup_grace_period_retention(self):
        """Verify delayed cleanup retains file on disk during grace period for sequential downloads."""
        create_resp = self.client.post(
            "/api/ai/transfer/create",
            json={"file_name": "grace_retention.bin", "one_time": True},
        )
        token = create_resp.json()["token"]
        payload = b"GRACE_TEST_PAYLOAD" * 50
        self.client.post(f"/api/ai/transfer/upload/{token}", content=payload)

        # First full download triggers delayed cleanup (30s)
        resp1 = self.client.get(f"/api/ai/transfer/download/{token}")
        self.assertEqual(resp1.status_code, 200)

        # File must STILL exist immediately after first download completes
        token_dir = transfer_storage_manager.base_dir / token
        self.assertTrue(token_dir.exists(), "Session was deleted immediately instead of waiting for 30s grace!")

        # Second download during grace period must still succeed
        resp2 = self.client.get(f"/api/ai/transfer/download/{token}")
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.content, payload)

    async def test_delayed_cleanup_task_cancellation_and_reschedule(self):
        """
        Verify that multiple concurrent or rapid stream completions cleanly cancel and reschedule
        the delayed cleanup task without leaving dangling tasks or unhandled task exceptions.
        """
        record = transfer_storage_manager.create_session(filename="reschedule.txt", one_time=True)
        token = record.token
        token_dir = transfer_storage_manager.base_dir / token
        (token_dir / "reschedule.txt").write_text("Grace Reschedule Test", encoding="utf-8")

        # Rapidly trigger schedule_delayed_cleanup 5 times with 0.2s delay
        for _ in range(5):
            transfer_storage_manager.schedule_delayed_cleanup(token, delay_seconds=0.2)
            await asyncio.sleep(0.02)

        # Ensure task is tracked
        self.assertIn(token, transfer_storage_manager._cleanup_tasks)
        self.assertTrue(token_dir.exists())

        # Wait for the final delayed cleanup to complete
        await asyncio.sleep(0.35)

        # Directory should now be purged
        self.assertFalse(token_dir.exists())
        self.assertNotIn(token, transfer_storage_manager._cleanup_tasks)


class TestEdgeUploadsAndInterruptedStreams(unittest.TestCase):
    """Adversarial testing on zero-byte uploads, interrupted streams and pending session states."""

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="test_adv_edge_")
        cls.orig_base_dir = transfer_storage_manager.base_dir
        transfer_storage_manager.base_dir = Path(cls.test_dir)
        transfer_storage_manager.ensure_dirs()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        transfer_storage_manager.base_dir = cls.orig_base_dir
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_upload_zero_byte_file_multipart_and_binary(self):
        """Zero-byte uploads via both multipart/form-data and direct binary stream must succeed."""
        # 1. Multipart zero-byte upload
        c1 = self.client.post("/api/ai/transfer/create", json={"file_name": "empty_multi.dat"})
        t1 = c1.json()["token"]
        up1 = self.client.post(
            f"/api/ai/transfer/upload/{t1}",
            files={"file": ("empty_multi.dat", b"", "application/octet-stream")},
        )
        self.assertEqual(up1.status_code, 200)
        self.assertEqual(up1.json()["record"]["file_size"], 0)
        self.assertEqual(up1.json()["record"]["state"], "ready")

        # Download zero-byte file
        down1 = self.client.get(f"/api/ai/transfer/download/{t1}")
        self.assertEqual(down1.status_code, 200)
        self.assertEqual(len(down1.content), 0)

        # 2. Binary raw stream zero-byte upload
        c2 = self.client.post("/api/ai/transfer/create", json={"file_name": "empty_raw.dat"})
        t2 = c2.json()["token"]
        up2 = self.client.post(f"/api/ai/transfer/upload/{t2}", content=b"")
        self.assertEqual(up2.status_code, 200)
        self.assertEqual(up2.json()["record"]["file_size"], 0)
        self.assertEqual(up2.json()["record"]["state"], "ready")

    def test_bug_premature_download_purges_pending_upload_session(self):
        """
        Adversarial test:
        When a session is in state='pending_upload' (upload hasn't started yet),
        a premature GET /download/{token} must return 404 but MUST NOT delete the session directory!
        Subsequent upload attempt must succeed (200 OK) and file can then be downloaded properly.
        """
        create_resp = self.client.post(
            "/api/ai/transfer/create",
            json={"file_name": "pending_test.bin", "mode": "upload"},
        )
        token = create_resp.json()["token"]
        token_dir = transfer_storage_manager.base_dir / token

        self.assertTrue(token_dir.is_dir())
        self.assertTrue((token_dir / "metadata.json").is_file())

        # Client / crawler calls GET /download/{token} prematurely
        premature_get = self.client.get(f"/api/ai/transfer/download/{token}")
        self.assertEqual(premature_get.status_code, 404)

        # Check that token_dir was NOT destroyed
        self.assertTrue(
            token_dir.exists(),
            "Violation: token_dir was deleted by premature GET /download/{token}!",
        )

        # Subsequent upload must succeed
        payload = b"REAL_PAYLOAD_AFTER_PREMATURE_GET"
        upload_resp = self.client.post(
            f"/api/ai/transfer/upload/{token}",
            content=payload,
        )
        self.assertEqual(upload_resp.status_code, 200)

        # Downloader can now download the ready file
        dl_resp = self.client.get(f"/api/ai/transfer/download/{token}")
        self.assertEqual(dl_resp.status_code, 200)
        self.assertEqual(dl_resp.content, payload)

    def test_bug_get_download_file_serves_partial_unready_file(self):
        """
        Adversarial test:
        get_download_file() must check whether metadata['state'] == 'ready'.
        If a file is in state='pending_upload' (e.g. streaming or aborted),
        get_download_file() must raise FileNotFoundError and never serve the unready partial file.
        """
        rec = transfer_storage_manager.create_session(filename="partial_leak.bin", mode="upload")
        token_dir = transfer_storage_manager.base_dir / rec.token

        # Simulate aborted upload leaving 512 bytes on disk while metadata is pending_upload
        partial_file = token_dir / "partial_leak.bin"
        partial_file.write_bytes(b"X" * 512)

        # Calling get_download_file must raise FileNotFoundError
        with self.assertRaises(FileNotFoundError):
            transfer_storage_manager.get_download_file(rec.token)

        # The session directory must remain intact
        self.assertTrue(token_dir.exists())

    def test_aborted_upload_stream_state(self):
        """
        Simulate an upload stream that throws an exception midway (socket abort).
        Verify that the server handles the error gracefully and doesn't leave the session in 'ready' state.
        """
        create_resp = self.client.post("/api/ai/transfer/create", json={"file_name": "abort.bin"})
        token = create_resp.json()["token"]

        async def _corrupted_stream():
            yield b"PARTIAL_CHUNK_1"
            yield b"PARTIAL_CHUNK_2"
            raise ConnectionResetError("Client aborted upload")

        with self.assertRaises(ConnectionResetError):
            asyncio.run(
                transfer_storage_manager.save_upload_stream(
                    token=token,
                    filename="abort.bin",
                    stream=_corrupted_stream(),
                )
            )

        # Check session state in metadata
        session = transfer_storage_manager.get_session(token)
        if session is not None:
            # Must NOT be marked as 'ready'
            self.assertNotEqual(session.state, "ready", "Aborted upload should never be marked as 'ready'")

    def test_corrupted_metadata_json_recovery(self):
        """When metadata.json is corrupted with invalid JSON syntax, get_session should clean up."""
        create_resp = self.client.post("/api/ai/transfer/create", json={"file_name": "corrupt_meta.dat"})
        token = create_resp.json()["token"]
        token_dir = transfer_storage_manager.base_dir / token

        # Overwrite metadata.json with garbage
        (token_dir / "metadata.json").write_text("{NOT_VALID_JSON: true,,,", encoding="utf-8")

        # get_session should purge corrupt directory and return None
        session = transfer_storage_manager.get_session(token)
        self.assertIsNone(session)
        self.assertFalse(token_dir.exists())


class TestZeroDiskLeakStressHarness(unittest.TestCase):
    """Stress test the 3-Layer Zero-Disk-Leak engine across 50 sessions."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_adv_disk_leak_")
        self.base_dir = Path(self.test_dir)
        self.manager = TransferStorageManager(
            base_dir=self.base_dir,
            default_ttl_hours=24,
            grace_seconds=0.05,  # Short grace for testing
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_mass_session_sweep_stress_harness(self):
        """
        Create 50 sessions:
          - 20 active sessions
          - 20 expired sessions (expires_at in past)
          - 10 corrupted sessions (broken metadata)
        Execute sweep_expired() and verify 100% of expired & corrupt sessions are cleaned up,
        active sessions remain intact, and disk space is accurately accounted for.
        """
        active_tokens = []
        expired_tokens = []
        corrupted_tokens = []

        # 1. 20 Active sessions
        for i in range(20):
            rec = self.manager.create_session(filename=f"active_{i}.bin", ttl_hours=10)
            data_file = self.base_dir / rec.token / f"active_{i}.bin"
            data_file.write_bytes(b"A" * 1024)
            active_tokens.append(rec.token)

        # 2. 20 Expired sessions
        for i in range(20):
            rec = self.manager.create_session(filename=f"expired_{i}.bin", ttl_hours=1)
            t_dir = self.base_dir / rec.token
            data_file = t_dir / f"expired_{i}.bin"
            data_file.write_bytes(b"E" * 2048)
            # Alter metadata expires_at to 10s in past
            meta_file = t_dir / "metadata.json"
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            meta["expires_at"] = time.time() - 10
            meta_file.write_text(json.dumps(meta), encoding="utf-8")
            expired_tokens.append(rec.token)

        # 3. 10 Corrupted sessions
        for i in range(10):
            rec = self.manager.create_session(filename=f"corrupt_{i}.bin")
            t_dir = self.base_dir / rec.token
            data_file = t_dir / f"corrupt_{i}.bin"
            data_file.write_bytes(b"C" * 512)
            meta_file = t_dir / "metadata.json"
            meta_file.write_text("INVALID_JSON", encoding="utf-8")
            corrupted_tokens.append(rec.token)

        # Let grace_seconds pass for corrupt folders
        time.sleep(0.1)

        # Execute sweep
        stats = self.manager.sweep_expired()

        self.assertEqual(stats["expired_tokens_removed"], 20)
        self.assertEqual(stats["corrupt_tokens_removed"], 10)
        self.assertGreater(stats["bytes_freed"], 0)

        # Verify all expired directories are gone
        for token in expired_tokens:
            self.assertFalse((self.base_dir / token).exists(), f"Expired session {token} was not swept!")

        # Verify all corrupt directories are gone
        for token in corrupted_tokens:
            self.assertFalse((self.base_dir / token).exists(), f"Corrupt session {token} was not swept!")

        # Verify all active directories are intact
        for token in active_tokens:
            self.assertTrue((self.base_dir / token).exists(), f"Active session {token} was incorrectly deleted!")

    def test_rapid_session_creation_and_purge_cycle(self):
        """Rapidly create and delete 50 sessions; verify exactly 0 directories left behind."""
        for i in range(50):
            rec = self.manager.create_session(filename=f"rapid_{i}.txt")
            (self.base_dir / rec.token / f"rapid_{i}.txt").write_text("temp", encoding="utf-8")
            deleted = self.manager.delete_session(rec.token)
            self.assertTrue(deleted)

        remaining = [d for d in self.base_dir.iterdir() if d.is_dir()]
        self.assertEqual(len(remaining), 0, f"Zero-disk leak violated! Remaining: {remaining}")


if __name__ == "__main__":
    unittest.main()
