"""
test_challenger_it2_edge_cases.py — Empirical Verification Suite for Challenger It2-2.
Deep Negative Edge Cases & Zero-Disk Leak Verifier:
1. send_video_file with non-existent files (must return False, never call send_video, no crash).
2. send_video_file with files <= 50MB (must unlink from real disk after transmission, Zero-Disk Leak).
3. send_video_file with files > 50MB (must activate portal with ttl_seconds, never call send_video).
4. Concurrency stress testing and ResourceWarning checks.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

_SERVICE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _SERVICE_DIR not in sys.path:
    sys.path.insert(0, _SERVICE_DIR)

from app.services.telegram_bot import TelegramBot
from app.services.media_storage_manager import MediaStorageManager


class TestSendVideoFileNonExistentNegative(unittest.IsolatedAsyncioTestCase):
    """Negative testing: non-existent files, invalid paths, and directories."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="challenger_it2_neg_")
        self.bot = TelegramBot.__new__(TelegramBot)
        self.bot.token = "mock_token"
        self.bot.send_message = AsyncMock(return_value=True)
        self.bot.send_video = AsyncMock(return_value=True)
        self.bot.send_document_file = AsyncMock(return_value=True)

    async def asyncTearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_nonexistent_random_file_returns_false_no_calls(self):
        """File does not exist: returns False immediately, 0 calls to send_video/document/message."""
        missing = os.path.join(self.temp_dir, "non_existent_xyz_987654.mp4")
        self.assertFalse(os.path.exists(missing))

        res = await self.bot.send_video_file(
            chat_id="chat_123",
            video_path=missing,
            caption="Test missing file",
        )

        self.assertFalse(res, "send_video_file MUST return False for non-existent file")
        self.bot.send_video.assert_not_called()
        self.bot.send_document_file.assert_not_called()
        self.bot.send_message.assert_not_called()

    async def test_empty_and_none_paths_return_false(self):
        """Empty string or None video_path returns False without crashing."""
        res_empty = await self.bot.send_video_file(chat_id="chat_123", video_path="")
        self.assertFalse(res_empty)
        self.bot.send_video.assert_not_called()

        res_none = await self.bot.send_video_file(chat_id="chat_123", video_path=None)  # type: ignore[arg-type]
        self.assertFalse(res_none)
        self.bot.send_video.assert_not_called()

    async def test_directory_path_returns_false_gracefully(self):
        """Passing a directory path should gracefully return False without crashing on unmocked send_video."""
        sub_dir = os.path.join(self.temp_dir, "fake_video_dir")
        os.makedirs(sub_dir, exist_ok=True)

        real_bot = TelegramBot.__new__(TelegramBot)
        real_bot.token = "mock_token"
        real_bot.send_document_file = AsyncMock(return_value=False)

        with patch("app.services.telegram_bot.http_client_manager.get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client

            res = await real_bot.send_video_file(chat_id="chat_123", video_path=sub_dir)
            # Directory cannot be opened as a file by open(p, 'rb'), so send_video fails and returns False
            self.assertFalse(res)

    async def test_special_characters_nonexistent_returns_false(self):
        """Paths with Vietnamese diacritics, spaces, emojis that don't exist return False cleanly."""
        weird_path = os.path.join(self.temp_dir, "tập tin không tồn tại 🔥 [test].mp4")
        res = await self.bot.send_video_file(chat_id="chat_123", video_path=weird_path)
        self.assertFalse(res)
        self.bot.send_video.assert_not_called()

    async def test_real_bot_instance_without_mocks_nonexistent_returns_false(self):
        """Test on an unmocked TelegramBot instance to guarantee zero production crash."""
        real_bot = TelegramBot.__new__(TelegramBot)
        real_bot.token = "real_mock_token"
        missing = os.path.join(self.temp_dir, "missing_on_real_bot.mp4")

        res = await real_bot.send_video_file(chat_id="chat_123", video_path=missing)
        self.assertFalse(res)


class TestSendVideoFileZeroDiskLeakUnder50MB(unittest.IsolatedAsyncioTestCase):
    """Zero-Disk Leak verification for files <= 50MB on real filesystem."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="challenger_it2_zdl_")
        self.bot = TelegramBot.__new__(TelegramBot)
        self.bot.token = "mock_token"
        self.bot.send_message = AsyncMock(return_value=True)
        self.bot.send_video = AsyncMock(return_value=True)
        self.bot.send_document_file = AsyncMock(return_value=True)

    async def asyncTearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_normal_video_under_50mb_unlinks_on_real_disk(self):
        """Direct transmission unlinks the file from disk (Zero-Disk Leak verified)."""
        video_file = os.path.join(self.temp_dir, "clip_under_50mb.mp4")
        with open(video_file, "wb") as f:
            f.write(b"SAMPLE_VIDEO_DATA" * 500)  # ~8.5KB

        self.assertTrue(os.path.exists(video_file), "File must exist before sending")

        res = await self.bot.send_video_file(
            chat_id="chat_123",
            video_path=video_file,
            caption="Test normal video",
            cleanup_after_send=True,
        )

        self.assertTrue(res)
        self.bot.send_video.assert_called_once()
        self.assertFalse(os.path.exists(video_file), "CRITICAL: File MUST be unlinked after send!")

    async def test_zero_byte_video_under_50mb_unlinks_on_real_disk(self):
        """0-byte file <= 50MB is sent and unlinked from disk."""
        zero_file = os.path.join(self.temp_dir, "zero_byte.mp4")
        with open(zero_file, "wb") as f:
            pass

        self.assertEqual(os.path.getsize(zero_file), 0)
        res = await self.bot.send_video_file(
            chat_id="chat_123",
            video_path=zero_file,
            cleanup_after_send=True,
        )

        self.assertTrue(res)
        self.bot.send_video.assert_called_once()
        self.assertFalse(os.path.exists(zero_file), "0-byte file MUST be unlinked from disk")

    async def test_exact_50mb_boundary_unlinks_on_real_disk(self):
        """Exact 50*1024*1024 byte file is treated as <= 50MB and unlinked."""
        boundary_file = os.path.join(self.temp_dir, "boundary_50mb.mp4")
        with open(boundary_file, "wb") as f:
            f.seek(50 * 1024 * 1024 - 1)
            f.write(b"\x00")

        self.assertEqual(os.path.getsize(boundary_file), 50 * 1024 * 1024)

        res = await self.bot.send_video_file(
            chat_id="chat_123",
            video_path=boundary_file,
            cleanup_after_send=True,
        )

        self.assertTrue(res)
        self.bot.send_video.assert_called_once()
        self.assertFalse(os.path.exists(boundary_file), "Exact 50MB file MUST be unlinked from disk")

    async def test_fallback_document_send_unlinks_on_real_disk(self):
        """When send_video fails, send_document_file is called and file is unlinked."""
        fallback_file = os.path.join(self.temp_dir, "fallback_clip.mp4")
        with open(fallback_file, "wb") as f:
            f.write(b"FALLBACK_DATA" * 200)

        self.bot.send_video = AsyncMock(return_value=False)
        self.bot.send_document_file = AsyncMock(return_value=True)

        res = await self.bot.send_video_file(
            chat_id="chat_123",
            video_path=fallback_file,
            cleanup_after_send=True,
        )

        self.assertTrue(res)
        self.bot.send_video.assert_called_once()
        self.bot.send_document_file.assert_called_once()
        self.assertFalse(os.path.exists(fallback_file), "File MUST be unlinked after document fallback")

    async def test_fallback_document_failure_still_unlinks_on_real_disk(self):
        """Even if both send_video and send_document_file fail, transient file is unlinked."""
        dead_file = os.path.join(self.temp_dir, "dead_clip.mp4")
        with open(dead_file, "wb") as f:
            f.write(b"DEAD_DATA" * 200)

        self.bot.send_video = AsyncMock(return_value=False)
        self.bot.send_document_file = AsyncMock(return_value=False)

        res = await self.bot.send_video_file(
            chat_id="chat_123",
            video_path=dead_file,
            cleanup_after_send=True,
        )

        self.assertFalse(res)
        # Even on failure, disk must NOT leak dead temporary files
        self.assertFalse(os.path.exists(dead_file), "File MUST be unlinked to prevent disk leak on failure")

    async def test_cleanup_after_send_false_preserves_file_on_real_disk(self):
        """When cleanup_after_send=False, file is strictly preserved."""
        keep_file = os.path.join(self.temp_dir, "preserve_clip.mp4")
        with open(keep_file, "wb") as f:
            f.write(b"PRESERVE_DATA" * 200)

        res = await self.bot.send_video_file(
            chat_id="chat_123",
            video_path=keep_file,
            cleanup_after_send=False,
        )

        self.assertTrue(res)
        self.assertTrue(os.path.exists(keep_file), "File MUST remain on disk when cleanup_after_send=False")

    async def test_unlink_exception_resilience_does_not_crash(self):
        """If unlink throws an unexpected error, send_video_file catches it and returns sent status."""
        test_file = os.path.join(self.temp_dir, "locked_clip.mp4")
        with open(test_file, "wb") as f:
            f.write(b"DATA" * 100)

        with patch.object(Path, "unlink", side_effect=PermissionError("Simulated file lock")):
            res = await self.bot.send_video_file(
                chat_id="chat_123",
                video_path=test_file,
                cleanup_after_send=True,
            )
            # Must return True (since send_video succeeded) and not crash
            self.assertTrue(res)


class TestSendVideoFileOver50MBPortal(unittest.IsolatedAsyncioTestCase):
    """Portal delivery verification for files > 50MB."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="challenger_it2_portal_")
        self.bot = TelegramBot.__new__(TelegramBot)
        self.bot.token = "mock_token"
        self.bot.send_message = AsyncMock(return_value=True)
        self.bot.send_video = AsyncMock(return_value=True)
        self.bot.send_document_file = AsyncMock(return_value=True)

    async def asyncTearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_boundary_50mb_plus_1_byte_activates_portal(self):
        """Boundary: 50MB + 1 byte strictly routes to portal delivery."""
        file_path = os.path.join(self.temp_dir, "over_boundary.mp4")
        with open(file_path, "wb") as f:
            f.seek(50 * 1024 * 1024)  # 50MB + 1 byte
            f.write(b"\x01")

        self.assertEqual(os.path.getsize(file_path), 50 * 1024 * 1024 + 1)

        with patch("app.services.telegram_bot.media_storage_manager.publish_download_item") as mock_pub:
            mock_record = MagicMock()
            mock_record.internet_url = "https://ngrok.example.com/boundary.mp4"
            mock_record.lan_url = "http://192.168.1.10:8084/boundary.mp4"
            mock_pub.return_value = mock_record

            res = await self.bot.send_video_file(
                chat_id="chat_123",
                video_path=file_path,
                caption="Boundary test",
            )

            self.assertTrue(res)
            mock_pub.assert_called_once()
            self.bot.send_video.assert_not_called()
            self.bot.send_document_file.assert_not_called()
            self.bot.send_message.assert_called_once()

    async def test_large_file_calls_publish_download_item_with_correct_ttl_seconds(self):
        """Large file calls publish_download_item with exact ttl_seconds=14400 (4 hours)."""
        file_path = os.path.join(self.temp_dir, "large_video.mp4")
        with open(file_path, "wb") as f:
            f.seek(75 * 1024 * 1024)  # 75MB
            f.write(b"\x00")

        with patch("app.services.telegram_bot.media_storage_manager.publish_download_item") as mock_pub:
            mock_record = MagicMock()
            mock_record.internet_url = "https://ngrok.example.com/large.mp4"
            mock_record.lan_url = "http://192.168.1.10:8084/large.mp4"
            mock_pub.return_value = mock_record

            res = await self.bot.send_video_file(
                chat_id="chat_123",
                video_path=file_path,
                title="My Custom Video",
                duration=120,
            )

            self.assertTrue(res)
            mock_pub.assert_called_once()
            call_kw = mock_pub.call_args.kwargs
            self.assertEqual(call_kw.get("ttl_seconds"), 14400)
            self.assertEqual(call_kw.get("title"), "My Custom Video")
            self.assertEqual(call_kw.get("duration"), 120)
            self.assertEqual(call_kw.get("filename"), "large_video.mp4")

    async def test_large_file_preserves_file_on_disk_for_portal_downloads(self):
        """Portal delivery must NOT delete the file because it needs to be served to the user."""
        file_path = os.path.join(self.temp_dir, "portal_preserve.mp4")
        with open(file_path, "wb") as f:
            f.seek(60 * 1024 * 1024)
            f.write(b"\x00")

        with patch("app.services.telegram_bot.media_storage_manager.publish_download_item") as mock_pub:
            mock_pub.return_value = MagicMock(
                internet_url="https://ngrok.test/p.mp4",
                lan_url="http://lan.test/p.mp4",
            )

            res = await self.bot.send_video_file(
                chat_id="chat_123",
                video_path=file_path,
                cleanup_after_send=True,
            )

            self.assertTrue(res)
            # The file must remain on disk for portal downloads
            self.assertTrue(os.path.exists(file_path), "File for portal MUST NOT be prematurely deleted")

    async def test_portal_publishing_exception_sends_polite_error_and_returns_false(self):
        """When publish_download_item raises an exception, send polite error and return False."""
        file_path = os.path.join(self.temp_dir, "err_large.mp4")
        with open(file_path, "wb") as f:
            f.seek(55 * 1024 * 1024)
            f.write(b"\x00")

        with patch("app.services.telegram_bot.media_storage_manager.publish_download_item", side_effect=OSError("Disk full on portal volume")):
            res = await self.bot.send_video_file(
                chat_id="chat_123",
                video_path=file_path,
            )

            self.assertFalse(res)
            self.bot.send_message.assert_called_once()
            msg = self.bot.send_message.call_args[0][1]
            self.assertIn("vượt quá giới hạn 50MB", msg)
            self.assertIn("Disk full on portal volume", msg)

    async def test_real_media_storage_manager_integration(self):
        """Live integration with real MediaStorageManager instance."""
        storage_dir = os.path.join(self.temp_dir, "live_storage")
        storage_mgr = MediaStorageManager(base_dir=storage_dir)

        large_file = os.path.join(self.temp_dir, "live_large_video.mp4")
        with open(large_file, "wb") as f:
            f.seek(51 * 1024 * 1024)
            f.write(b"END")

        with patch("app.services.telegram_bot.media_storage_manager", storage_mgr), \
             patch.object(storage_mgr, "resolve_public_download_base_url_sync", return_value=("https://live-ngrok.test", "http://live-lan:8084")):

            res = await self.bot.send_video_file(
                chat_id="chat_123",
                video_path=large_file,
                caption="Live storage test",
            )

            self.assertTrue(res)
            self.bot.send_message.assert_called_once()
            portal_text = self.bot.send_message.call_args[0][1]
            self.assertIn("https://live-ngrok.test", portal_text)
            self.assertIn("http://live-lan:8084", portal_text)
            self.assertIn("51.0 MB", portal_text)


class TestSendVideoFileConcurrencyAndStress(unittest.IsolatedAsyncioTestCase):
    """Concurrency & stress testing to uncover race conditions and unclosed descriptors."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="challenger_it2_stress_")
        self.bot = TelegramBot.__new__(TelegramBot)
        self.bot.token = "mock_token"
        self.bot.send_message = AsyncMock(return_value=True)
        self.bot.send_video = AsyncMock(return_value=True)
        self.bot.send_document_file = AsyncMock(return_value=True)

    async def asyncTearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_concurrent_send_video_file_pipeline_no_race_no_leak(self):
        """Run 20 concurrent send_video_file tasks across small, large, and nonexistent files."""
        tasks = []

        # 10 small files (<=50MB) -> must all be unlinked cleanly
        small_files = []
        for i in range(10):
            p = os.path.join(self.temp_dir, f"small_{i}.mp4")
            with open(p, "wb") as f:
                f.write(b"CONCURRENT_SMALL" * 50)
            small_files.append(p)
            tasks.append(self.bot.send_video_file(chat_id=f"chat_{i}", video_path=p, cleanup_after_send=True))

        # 5 non-existent files -> must return False cleanly
        for i in range(5):
            p = os.path.join(self.temp_dir, f"nonexistent_{i}.mp4")
            tasks.append(self.bot.send_video_file(chat_id=f"chat_missing_{i}", video_path=p))

        # 5 large files (>50MB) -> must call portal
        large_files = []
        for i in range(5):
            p = os.path.join(self.temp_dir, f"large_{i}.mp4")
            with open(p, "wb") as f:
                f.seek(51 * 1024 * 1024)
                f.write(b"\x00")
            large_files.append(p)

        with patch("app.services.telegram_bot.media_storage_manager.publish_download_item") as mock_pub:
            mock_pub.return_value = MagicMock(
                internet_url="https://ngrok.test/stress.mp4",
                lan_url="http://lan.test/stress.mp4",
            )
            for i, p in enumerate(large_files):
                tasks.append(self.bot.send_video_file(chat_id=f"chat_large_{i}", video_path=p))

            results = await asyncio.gather(*tasks)

        # 10 small: True
        for r in results[:10]:
            self.assertTrue(r)
        # 5 nonexistent: False
        for r in results[10:15]:
            self.assertFalse(r)
        # 5 large: True
        for r in results[15:]:
            self.assertTrue(r)

        # Verify all 10 small files are completely unlinked (Zero-Disk Leak under concurrency)
        for p in small_files:
            self.assertFalse(os.path.exists(p), f"File {p} should have been unlinked under concurrency!")

    async def test_no_unclosed_file_descriptor_resource_warnings(self):
        """Ensure send_video does not leak unclosed file handles (0 ResourceWarning)."""
        video_path = os.path.join(self.temp_dir, "res_warning_test.mp4")
        with open(video_path, "wb") as f:
            f.write(b"\x00" * 1024)

        # Test real send_video logic with mocked http_client
        real_bot = TelegramBot.__new__(TelegramBot)
        real_bot.token = "mock_token"

        with patch("app.services.telegram_bot.http_client_manager.get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            with warnings.catch_warnings(record=True) as captured_warnings:
                warnings.simplefilter("always", ResourceWarning)

                sent = await real_bot.send_video(
                    chat_id="chat_123",
                    video_path=video_path,
                )
                self.assertTrue(sent)

            # Filter for ResourceWarning
            rw = [w for w in captured_warnings if issubclass(w.category, ResourceWarning)]
            self.assertEqual(len(rw), 0, f"Expected 0 ResourceWarnings, got: {rw}")


if __name__ == "__main__":
    unittest.main()
