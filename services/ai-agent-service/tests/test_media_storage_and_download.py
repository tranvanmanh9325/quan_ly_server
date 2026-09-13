"""
test_media_storage_and_download.py — Comprehensive Test Suite for Milestone 3.

Validates:
  1. MediaStorageManager item publishing with zero-copy inode moves and metadata generation.
  2. Direct Download Endpoints with Starlette FileResponse HTTP 206 Range requests (Partial Content).
  3. Layer 2 Defense: Instant On-Access Expiry Check (purging folder upon access).
  4. Layer 1 & Layer 3: 3-Layer TTL Sweeper cleaning 100% expired items and orphaned temp files (Zero-Disk-Leak).
  5. Multi-Tier Base URL resolution (Static Env -> Ngrok auto-discovery -> LAN fallback).
"""

import asyncio
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from starlette.testclient import TestClient

from app.main import app, media_ttl_sweeper_loop
from app.services.media_storage_manager import (
    MediaStorageManager,
    DownloadRecord,
    DEFAULT_TTL_SECONDS,
    DEFAULT_TEMP_MAX_AGE_SECONDS,
)


class TestMediaStorageManager(unittest.TestCase):
    """Unit tests for the MediaStorageManager core lifecycle engine."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_media_mgr_")
        self.base_dir = Path(self.test_dir)
        self.temp_dir = self.base_dir / "temp"
        self.public_dir = self.base_dir / "public"
        self.manager = MediaStorageManager(
            base_dir=self.base_dir,
            temp_dir=self.temp_dir,
            public_dir=self.public_dir,
            default_ttl=14400,
            temp_max_age=600,
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_publish_download_item_moves_file_and_writes_metadata(self):
        # Create a dummy source video file in temp
        src_file = self.temp_dir / "sample_video_1080p.mp4"
        sample_bytes = b"SAMPLE_VIDEO_CONTENT_BYTES_0123456789" * 100
        src_file.write_bytes(sample_bytes)
        self.assertTrue(src_file.exists())

        record = self.manager.publish_download_item(
            file_path=src_file,
            filename="my_clean_video.mp4",
            title="Clean Video Title",
            duration=42,
            ttl_seconds=3600,
        )

        # 1. Verify original file moved (zero-copy inode move)
        self.assertFalse(src_file.exists(), "Source file should have been moved, not copied.")

        # 2. Verify target file exists in public token directory
        token_dir = self.public_dir / record.token
        self.assertTrue(token_dir.is_dir(), "Token directory must exist.")
        dest_file = token_dir / "my_clean_video.mp4"
        self.assertTrue(dest_file.is_file(), "Destination file must exist in token directory.")
        self.assertEqual(dest_file.read_bytes(), sample_bytes)

        # 3. Verify metadata.json contents
        meta_file = token_dir / "metadata.json"
        self.assertTrue(meta_file.is_file(), "metadata.json must be persisted.")
        with open(meta_file, "r", encoding="utf-8") as f:
            meta = json.load(f)

        self.assertEqual(meta["token"], record.token)
        self.assertEqual(meta["filename"], "my_clean_video.mp4")
        self.assertEqual(meta["file_size"], len(sample_bytes))
        self.assertEqual(meta["title"], "Clean Video Title")
        self.assertEqual(meta["duration"], 42)
        self.assertEqual(meta["download_count"], 0)
        self.assertAlmostEqual(meta["expires_at"] - meta["created_at"], 3600, delta=2)

        # 4. Verify URL structure
        self.assertIn(record.token, record.internet_url)
        self.assertIn("my_clean_video.mp4", record.internet_url)
        self.assertIn(record.token, record.lan_url)

    def test_get_download_file_increments_download_counter(self):
        src_file = self.temp_dir / "count_test.mp4"
        src_file.write_bytes(b"TEST_COUNT_DATA")
        record = self.manager.publish_download_item(
            file_path=src_file,
            filename="count_test.mp4",
            title="Count Test",
        )

        # First retrieval
        fpath1, meta1 = self.manager.get_download_file(record.token)
        self.assertEqual(fpath1, record.file_path)
        self.assertEqual(meta1["download_count"], 1)

        # Second retrieval
        fpath2, meta2 = self.manager.get_download_file(record.token)
        self.assertEqual(fpath2, record.file_path)
        self.assertEqual(meta2["download_count"], 2)

        # Confirm persisted metadata file also reflects count
        meta_file = self.public_dir / record.token / "metadata.json"
        with open(meta_file, "r", encoding="utf-8") as f:
            persisted = json.load(f)
        self.assertEqual(persisted["download_count"], 2)

    def test_layer_2_on_access_expiry_purges_folder_instantly(self):
        src_file = self.temp_dir / "expired_target.mp4"
        src_file.write_bytes(b"EXPIRED_DATA")

        # Publish with negative TTL so it is already expired immediately
        record = self.manager.publish_download_item(
            file_path=src_file,
            filename="expired_target.mp4",
            title="Expired Video",
            ttl_seconds=-5,
        )

        token_dir = self.public_dir / record.token
        self.assertTrue(token_dir.exists(), "Folder should initially exist after publish.")

        # On-Access retrieval must trigger Layer 2 instant cleanup and raise FileNotFoundError
        with self.assertRaises(FileNotFoundError):
            self.manager.get_download_file(record.token)

        # Verify folder was instantly purged from disk (Zero-Disk-Leak)
        self.assertFalse(token_dir.exists(), "Expired folder must be purged instantly upon access attempt.")

    def test_security_token_path_traversal_rejection(self):
        malicious_tokens = [
            "../../etc/passwd",
            "../other_folder",
            "validtoken/../../root",
            "invalid*char",
            "",
            "short",
        ]
        for bad_token in malicious_tokens:
            with self.assertRaises(FileNotFoundError):
                self.manager.get_download_file(bad_token)

    def test_sweep_expired_removes_expired_tokens_and_orphaned_temp_files(self):
        # 1. Expired token item (ttl = -10s)
        f_exp = self.temp_dir / "item_exp.mp4"
        f_exp.write_bytes(b"A" * 1024)
        rec_exp = self.manager.publish_download_item(f_exp, "item_exp.mp4", "Expired", ttl_seconds=-10)

        # 2. Valid token item (ttl = 3600s)
        f_val = self.temp_dir / "item_val.mp4"
        f_val.write_bytes(b"B" * 2048)
        rec_val = self.manager.publish_download_item(f_val, "item_val.mp4", "Valid", ttl_seconds=3600)

        # 3. Orphaned temp file older than 600s
        orphaned_temp = self.temp_dir / "old_orphaned_chunk.part"
        orphaned_temp.write_bytes(b"C" * 512)
        old_mtime = time.time() - 700
        os.utime(orphaned_temp, (old_mtime, old_mtime))

        # 4. Fresh temp file (active download in progress)
        fresh_temp = self.temp_dir / "active_download_chunk.part"
        fresh_temp.write_bytes(b"D" * 256)

        # Execute Layer 1/3 sweep
        stats = self.manager.sweep_expired()

        self.assertEqual(stats["expired_tokens_removed"], 1)
        self.assertEqual(stats["temp_files_removed"], 1)
        # bytes_freed includes the media file (1024), temp file (512), plus token's metadata.json (~354 bytes)
        self.assertGreaterEqual(stats["bytes_freed"], 1024 + 512)

        # Expired token folder must be removed
        self.assertFalse((self.public_dir / rec_exp.token).exists())

        # Valid token folder must remain untouched
        self.assertTrue((self.public_dir / rec_val.token).exists())
        self.assertTrue((self.public_dir / rec_val.token / "item_val.mp4").exists())

        # Orphaned temp file must be removed
        self.assertFalse(orphaned_temp.exists())

        # Fresh temp file must be preserved
        self.assertTrue(fresh_temp.exists())

    def test_sweep_expired_grace_period_protects_fresh_incomplete_folder(self):
        """
        Validates that a fresh token folder (< 60s) without metadata.json is protected by grace period,
        preventing race conditions while a large file is being published.
        Folders older than 60s without metadata are swept.
        """
        now = time.time()

        # 1. Fresh folder (< 60s) without metadata.json: MUST BE PRESERVED
        fresh_token_dir = self.public_dir / "fresh_in_progress_token_12345"
        fresh_token_dir.mkdir(parents=True, exist_ok=True)
        fresh_file = fresh_token_dir / "large_video.mp4"
        fresh_file.write_bytes(b"LARGE_VIDEO_IN_TRANSIT" * 50)
        fresh_mtime = now - 10.0  # 10 seconds old
        os.utime(fresh_token_dir, (fresh_mtime, fresh_mtime))

        # 2. Old orphaned folder (> 60s) without metadata.json: MUST BE SWEPT
        old_orphaned_dir = self.public_dir / "old_orphaned_token_67890"
        old_orphaned_dir.mkdir(parents=True, exist_ok=True)
        old_file = old_orphaned_dir / "abandoned.mp4"
        old_file.write_bytes(b"ABANDONED_BYTES")
        old_mtime = now - 120.0  # 120 seconds old (> 60s grace)
        os.utime(old_orphaned_dir, (old_mtime, old_mtime))

        stats = self.manager.sweep_expired()

        # Old orphaned folder swept
        self.assertFalse(old_orphaned_dir.exists(), "Old orphaned folder older than 60s must be swept.")
        self.assertEqual(stats["expired_tokens_removed"], 1)

        # Fresh folder protected by grace period
        self.assertTrue(fresh_token_dir.exists(), "Fresh folder (< 60s) must be preserved by grace period.")
        self.assertTrue(fresh_file.exists())

    def test_sweep_expired_corrupted_metadata_respects_grace_period(self):
        """
        Validates that folders with unreadable/corrupted metadata also respect the 60s grace period.
        """
        now = time.time()

        # 1. Fresh folder (< 60s) with corrupt metadata (e.g. midway writing)
        fresh_corrupt_dir = self.public_dir / "fresh_corrupt_12345"
        fresh_corrupt_dir.mkdir(parents=True, exist_ok=True)
        (fresh_corrupt_dir / "metadata.json").write_text("{corrupt_json...", encoding="utf-8")
        fresh_mtime = now - 15.0
        os.utime(fresh_corrupt_dir, (fresh_mtime, fresh_mtime))

        # 2. Old folder (> 60s) with corrupt metadata
        old_corrupt_dir = self.public_dir / "old_corrupt_67890"
        old_corrupt_dir.mkdir(parents=True, exist_ok=True)
        (old_corrupt_dir / "metadata.json").write_text("{unparseable...", encoding="utf-8")
        old_mtime = now - 200.0
        os.utime(old_corrupt_dir, (old_mtime, old_mtime))

        stats = self.manager.sweep_expired()

        self.assertTrue(fresh_corrupt_dir.exists(), "Fresh folder with corrupt metadata must be preserved within grace period.")
        self.assertFalse(old_corrupt_dir.exists(), "Old folder with corrupt metadata (> 60s) must be purged.")

    def test_multi_tier_url_resolution(self):
        # Tier 1: Static environment variable override
        with patch.dict(os.environ, {"PUBLIC_DOWNLOAD_BASE_URL": "https://custom.domain.com"}):
            internet, lan = self.manager.resolve_public_download_base_url_sync()
            self.assertEqual(internet, "https://custom.domain.com")
            self.assertTrue(lan.startswith("http"))

        # Tier 2: Ngrok API discovery simulation
        mock_ngrok_response = {
            "tunnels": [
                {
                    "name": "web",
                    "public_url": "https://discovered-subdomain.ngrok-free.dev",
                    "proto": "https",
                }
            ]
        }
        with patch.dict(os.environ, {}, clear=True), \
             patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.read.return_value = json.dumps(mock_ngrok_response).encode("utf-8")
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            # Clear cached url to force fresh probe
            import app.services.media_storage_manager as msm_mod
            msm_mod._cached_internet_url = None
            msm_mod._cached_url_timestamp = 0.0

            internet, _ = self.manager.resolve_public_download_base_url_sync()
            self.assertEqual(internet, "https://discovered-subdomain.ngrok-free.dev")

    def test_resolve_url_tier2_docker_host_candidates(self):
        """
        Tests Tier 2 Strategy A: Direct HTTP probe on Docker Host candidate IPs.
        """
        import app.services.media_storage_manager as msm_mod
        msm_mod._cached_internet_url = None
        msm_mod._cached_url_timestamp = 0.0

        mock_payload = {
            "tunnels": [
                {
                    "name": "web",
                    "public_url": "https://docker-host-tunnel.ngrok-free.dev",
                    "proto": "https",
                }
            ]
        }

        with patch.dict(os.environ, {}, clear=True), \
             patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            internet, lan = self.manager.resolve_public_download_base_url_sync()
            self.assertEqual(internet, "https://docker-host-tunnel.ngrok-free.dev")

    def test_resolve_url_tier2_ssh_host_fallback(self):
        """
        Tests Tier 2 Strategy B: Fallback to querying host ngrok API via SshClient
        when direct HTTP candidate connections fail (Connection Refused).
        """
        import app.services.media_storage_manager as msm_mod
        msm_mod._cached_internet_url = None
        msm_mod._cached_url_timestamp = 0.0

        import urllib.error
        with patch.dict(os.environ, {}, clear=True), \
             patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")), \
             patch.object(self.manager, "_query_host_ngrok_via_ssh", return_value="https://ssh-fallback.ngrok-free.dev"):

            internet, _ = self.manager.resolve_public_download_base_url_sync()
            self.assertEqual(internet, "https://ssh-fallback.ngrok-free.dev")
            self.assertEqual(msm_mod._cached_internet_url, "https://ssh-fallback.ngrok-free.dev")

    def test_resolve_url_tier3_lan_fallback_when_all_fail(self):
        """
        Tests Tier 3: When neither HTTP probe nor SSH query finds an active Ngrok tunnel,
        system falls back gracefully to the LAN URL.
        """
        import app.services.media_storage_manager as msm_mod
        msm_mod._cached_internet_url = None
        msm_mod._cached_url_timestamp = 0.0

        import urllib.error
        with patch.dict(os.environ, {}, clear=True), \
             patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")), \
             patch.object(self.manager, "_query_host_ngrok_via_ssh", return_value=None):

            internet, lan = self.manager.resolve_public_download_base_url_sync()
            self.assertEqual(internet, "http://192.168.0.100:5173")
            self.assertEqual(lan, "http://192.168.0.100:5173")

    def test_query_host_ngrok_via_ssh_executes_curl_and_parses(self):
        """
        Validates internal logic of _query_host_ngrok_via_ssh with mock SshClient.
        """
        mock_ssh_output = json.dumps({
            "tunnels": [
                {"name": "ssh", "public_url": "tcp://0.tcp.ap.ngrok.io:25823", "proto": "tcp"},
                {"name": "web", "public_url": "https://real-time-host.ngrok-free.dev", "proto": "https"}
            ]
        })
        mock_ssh = AsyncMock()
        mock_ssh.execute_command = AsyncMock(return_value=mock_ssh_output)

        with patch("app.core.ssh_client.SshClient", return_value=mock_ssh):
            url = self.manager._query_host_ngrok_via_ssh()
            self.assertEqual(url, "https://real-time-host.ngrok-free.dev")

    def test_media_ttl_sweeper_loop_execution_and_cancellation(self):
        """Validates that media_ttl_sweeper_loop periodically calls sweep_expired and handles cancellation cleanly."""
        async def run_loop_test():
            call_count = 0
            def mock_sweep():
                nonlocal call_count
                call_count += 1
                return {"expired_tokens_removed": 1, "temp_files_removed": 0, "bytes_freed": 100, "freed_mb": 0.0}

            with patch("app.main.media_storage_manager.sweep_expired", side_effect=mock_sweep):
                task = asyncio.create_task(media_ttl_sweeper_loop(interval_sec=0.05))
                await asyncio.sleep(0.12)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                self.assertGreaterEqual(call_count, 1)

        asyncio.run(run_loop_test())


class TestMediaDownloadEndpoints(unittest.TestCase):
    """Integration tests for FastAPI media download HTTP endpoints."""

    def setUp(self):
        self.client = TestClient(app)
        # Point global media_storage_manager to a temporary test directory
        self.test_dir = tempfile.mkdtemp(prefix="test_router_media_")
        self.base_dir = Path(self.test_dir)
        self.temp_dir = self.base_dir / "temp"
        self.public_dir = self.base_dir / "public"

        import app.services.media_storage_manager as msm_mod
        self.original_manager = msm_mod.media_storage_manager
        self.test_manager = MediaStorageManager(
            base_dir=self.base_dir,
            temp_dir=self.temp_dir,
            public_dir=self.public_dir,
            default_ttl=14400,
        )
        msm_mod.media_storage_manager = self.test_manager

        # Also patch router's imported reference
        import app.routers.media_download as md_router
        md_router.media_storage_manager = self.test_manager

    def tearDown(self):
        import app.services.media_storage_manager as msm_mod
        import app.routers.media_download as md_router
        msm_mod.media_storage_manager = self.original_manager
        md_router.media_storage_manager = self.original_manager
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_download_endpoint_full_file(self):
        dummy_content = b"TEST_VIDEO_BYTES_HEADER_BODY_EOF" * 50
        src = self.temp_dir / "router_test.mp4"
        src.write_bytes(dummy_content)

        record = self.test_manager.publish_download_item(
            file_path=src,
            filename="router_test.mp4",
            title="Router Test Video",
        )

        resp = self.client.get(f"/api/ai/media/download/{record.token}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, dummy_content)
        self.assertEqual(resp.headers.get("content-type"), "video/mp4")
        self.assertEqual(resp.headers.get("cache-control"), "private, max-age=14400")
        self.assertEqual(resp.headers.get("ngrok-skip-browser-warning"), "1")
        self.assertEqual(resp.headers.get("accept-ranges"), "bytes")

    def test_download_endpoint_http_206_range_request(self):
        """
        Validates native Starlette FileResponse HTTP 206 Range Request support.
        Allows download resumption, seeking, and multi-threaded acceleration.
        """
        # Create a predictable 1000-byte sequence
        total_size = 1000
        raw_data = bytes([i % 256 for i in range(total_size)])
        src = self.temp_dir / "range_test.mp4"
        src.write_bytes(raw_data)

        record = self.test_manager.publish_download_item(
            file_path=src,
            filename="range_test.mp4",
            title="Range Test Video",
        )

        # 1. Request first 10 bytes (0-9)
        headers = {"Range": "bytes=0-9"}
        resp = self.client.get(f"/api/ai/media/download/{record.token}", headers=headers)
        self.assertEqual(resp.status_code, 206, "Should return HTTP 206 Partial Content")
        self.assertEqual(len(resp.content), 10)
        self.assertEqual(resp.content, raw_data[0:10])
        self.assertEqual(resp.headers.get("content-range"), f"bytes 0-9/{total_size}")
        self.assertEqual(resp.headers.get("content-length"), "10")

        # 2. Request middle slice (100-199)
        headers_mid = {"Range": "bytes=100-199"}
        resp_mid = self.client.get(f"/api/ai/media/download/{record.token}", headers=headers_mid)
        self.assertEqual(resp_mid.status_code, 206)
        self.assertEqual(len(resp_mid.content), 100)
        self.assertEqual(resp_mid.content, raw_data[100:200])
        self.assertEqual(resp_mid.headers.get("content-range"), f"bytes 100-199/{total_size}")

        # 3. Request suffix (bytes=900-)
        headers_suffix = {"Range": "bytes=900-"}
        resp_suffix = self.client.get(f"/api/ai/media/download/{record.token}", headers=headers_suffix)
        self.assertEqual(resp_suffix.status_code, 206)
        self.assertEqual(len(resp_suffix.content), 100)
        self.assertEqual(resp_suffix.content, raw_data[900:1000])
        self.assertEqual(resp_suffix.headers.get("content-range"), f"bytes 900-999/{total_size}")

    def test_download_endpoint_expired_token_returns_404(self):
        src = self.temp_dir / "expired_endpoint.mp4"
        src.write_bytes(b"EXPIRED")

        record = self.test_manager.publish_download_item(
            file_path=src,
            filename="expired_endpoint.mp4",
            title="Expired Video",
            ttl_seconds=-10,
        )

        resp = self.client.get(f"/api/ai/media/download/{record.token}")
        self.assertEqual(resp.status_code, 404)
        self.assertIn("expired", resp.json().get("detail", "").lower())

    def test_download_info_endpoint(self):
        src = self.temp_dir / "info_test.mp4"
        src.write_bytes(b"INFO_DATA_PAYLOAD")

        record = self.test_manager.publish_download_item(
            file_path=src,
            filename="info_test.mp4",
            title="Informative Title",
            duration=99,
            ttl_seconds=7200,
        )

        resp = self.client.get(f"/api/ai/media/info/{record.token}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["token"], record.token)
        self.assertEqual(data["title"], "Informative Title")
        self.assertEqual(data["file_size"], len(b"INFO_DATA_PAYLOAD"))
        self.assertEqual(data["duration"], 99)
        self.assertEqual(data["download_count"], 0)
        self.assertFalse(data["is_expired"])
        self.assertGreater(data["time_remaining_seconds"], 7100)

    def test_trigger_sweep_endpoint(self):
        resp = self.client.post("/api/ai/media/sweep")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("stats", data)
        self.assertIn("expired_tokens_removed", data["stats"])


if __name__ == "__main__":
    unittest.main()
