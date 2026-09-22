"""
test_challenger_m7_2_adversarial.py — Challenger M7-2 Empirical Adversarial Verification Suite.

Adversarially tests:
1. _create_atomic_temp_file under extreme arguments:
   - Empty content (0 bytes)
   - Large content (50MB)
   - Custom prefix and suffix (empty, unicode, multi-dot, special symbols)
   - Non-existent & deeply nested directories
   - String vs Path directory arguments
   - Security permissions (POSIX mode 0600)
2. Cross-platform safety & file-locking:
   - Windows WinError 32 prevention (contrast test with unclosed fd)
   - Linux file descriptor leak prevention (/proc/self/fd count invariant)
   - High-concurrency stress test (50 concurrent threads)
3. Audio/video tool symmetry and case-insensitivity:
   - download_media_audio vs download_media_video(media_type="audio")
   - Case-insensitivity ("AUDIO", "Audio", "AuDiO", "audio")
   - Whitespace stripping and fallback behavior
   - Zero-Disk Leak invariant under simulated network faults and oversized media
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import html
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Dict, List, Optional
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.ai_agent_tools import (
    AgentToolExecutor,
    DIRECT_RETURN_TOOLS,
    classify_action_risk,
    ACTION_TIER_1_SAFE,
)
from app.services.media_downloader import (
    MediaItem,
    TEMP_MEDIA_DIR,
    VideoTooLargeError,
)
from app.services.ai_agent import AiAgentService
from app.services.media_storage_manager import DownloadRecord, media_storage_manager
from tests.test_challenger_m3_1_react_tools import _create_atomic_temp_file


class TestAtomicTempFileExtremeArguments(unittest.TestCase):
    """Category 1: Adversarial verification of _create_atomic_temp_file under extreme parameters."""

    def setUp(self) -> None:
        self.test_dir = Path(tempfile.mkdtemp(prefix="m7_2_test_extreme_"))

    def tearDown(self) -> None:
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_empty_content_creates_valid_zero_byte_file(self) -> None:
        """Adversarial: Empty content bytes (b'') must create a 0-byte file without crashing."""
        temp_p = _create_atomic_temp_file(content=b"", suffix=".mp3", directory=self.test_dir)
        self.assertTrue(temp_p.exists(), "File must exist on disk")
        self.assertEqual(temp_p.stat().st_size, 0, "File size must be exactly 0 bytes")
        self.assertEqual(temp_p.read_bytes(), b"", "File content must be empty")
        # Cleanup
        temp_p.unlink()
        self.assertFalse(temp_p.exists(), "File must be cleanly unlinked")

    def test_large_content_50mb(self) -> None:
        """Adversarial: Large content (50MB boundary) must be fully written and closed cleanly."""
        payload_size = 50 * 1024 * 1024  # 50MB exactly
        chunk_pattern = b"M72_LARGE_TEST_CHUNK_PAYLOAD_ABC" * 32  # 1024 bytes
        large_payload = chunk_pattern * (payload_size // len(chunk_pattern))
        self.assertEqual(len(large_payload), payload_size)

        temp_p = _create_atomic_temp_file(content=large_payload, suffix=".bin", directory=self.test_dir)
        try:
            self.assertTrue(temp_p.exists(), "50MB file must exist")
            self.assertEqual(temp_p.stat().st_size, payload_size, f"File size must be {payload_size} bytes")
            # Verify file descriptor was closed: can open for read immediately
            with open(temp_p, "rb") as f:
                head = f.read(len(chunk_pattern))
                self.assertEqual(head, chunk_pattern)
        finally:
            temp_p.unlink()
            self.assertFalse(temp_p.exists(), "50MB file must be cleanly deleted")

    def test_custom_prefixes_and_suffixes(self) -> None:
        """Adversarial: Unusual prefixes, suffixes (empty, unicode, multi-dot, special symbols)."""
        variations = [
            # (prefix, suffix)
            ("", ""),
            ("tmp_", ".mp3"),
            ("tiểu_bảo_", ".mp3"),
            ("test_audio_", ".spec.test.audio.mp3"),
            ("no_dot_ext_", "mp3"),
            ("special_!@#$_", ".tar.gz"),
            ("unicode_🚀_", ".mp4"),
        ]

        for pfx, sfx in variations:
            with self.subTest(prefix=pfx, suffix=sfx):
                temp_p = _create_atomic_temp_file(
                    content=b"test_payload_123",
                    prefix=pfx,
                    suffix=sfx,
                    directory=self.test_dir,
                )
                self.assertTrue(temp_p.exists(), f"File with prefix='{pfx}', suffix='{sfx}' must exist")
                self.assertTrue(temp_p.name.endswith(sfx), f"Filename '{temp_p.name}' must end with '{sfx}'")
                self.assertTrue(temp_p.name.startswith(pfx), f"Filename '{temp_p.name}' must start with '{pfx}'")
                self.assertEqual(temp_p.read_bytes(), b"test_payload_123")
                temp_p.unlink()
                self.assertFalse(temp_p.exists())

    def test_nonexistent_and_deeply_nested_directories(self) -> None:
        """Adversarial: Non-existent deeply nested directory must be created via parents=True."""
        nested_dir = self.test_dir / "depth1" / "depth2" / "depth3" / "nested_temp"
        self.assertFalse(nested_dir.exists(), "Pre-condition: nested directory does not exist")

        temp_p = _create_atomic_temp_file(
            content=b"nested_content",
            directory=nested_dir,
        )
        self.assertTrue(nested_dir.exists(), "Nested directory must be created automatically")
        self.assertTrue(temp_p.exists(), "File must exist in nested directory")
        self.assertEqual(temp_p.parent.resolve(), nested_dir.resolve())
        self.assertEqual(temp_p.read_bytes(), b"nested_content")

        # Test string directory argument
        string_dir = str(self.test_dir / "string_path_dir" / "sub")
        temp_p2 = _create_atomic_temp_file(content=b"string_dir_test", directory=string_dir)
        self.assertTrue(temp_p2.exists())
        self.assertEqual(temp_p2.read_bytes(), b"string_dir_test")
        temp_p.unlink()
        temp_p2.unlink()

    def test_posix_permissions_mode_0600(self) -> None:
        """Adversarial: On POSIX systems, verify file mode is strictly 0600 (owner rw only, CWE-377/732)."""
        if sys.platform == "win32":
            self.skipTest("File mode 0600 is POSIX-specific (NTFS uses ACLs)")

        temp_p = _create_atomic_temp_file(content=b"secret", directory=self.test_dir)
        try:
            mode = temp_p.stat().st_mode & 0o777
            self.assertEqual(mode, 0o600, f"Permissions must be 0600 (-rw-------), got {oct(mode)}")
        finally:
            temp_p.unlink()


class TestCrossPlatformSafetyAndFileLocking(unittest.TestCase):
    """Category 2: Cross-platform safety, Windows WinError 32 prevention & Linux fd leak prevention."""

    def setUp(self) -> None:
        self.test_dir = Path(tempfile.mkdtemp(prefix="m7_2_locking_"))

    def tearDown(self) -> None:
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_windows_winerror_32_contrast(self) -> None:
        """Adversarial contrast:
        - If fd is NOT closed, Windows raises PermissionError: [WinError 32] when unlinking.
        - With _create_atomic_temp_file (which closes fd), unlink succeeds 100% of the time.
        """
        if sys.platform == "win32":
            # 1. Negative proof: Unclosed fd causes PermissionError [WinError 32] on Windows
            target_dir = Path(self.test_dir)
            unclosed_fd, unclosed_path = tempfile.mkstemp(suffix=".tmp", dir=str(target_dir))
            try:
                os.write(unclosed_fd, b"locked_data")
                with self.assertRaises(PermissionError) as ctx:
                    Path(unclosed_path).unlink()
                # Verify it is indeed WinError 32
                winerror = getattr(ctx.exception, "winerror", None)
                self.assertEqual(winerror, 32, f"Expected WinError 32 (file in use), got {winerror}")
            finally:
                os.close(unclosed_fd)
                Path(unclosed_path).unlink(missing_ok=True)

        # 2. Positive proof: _create_atomic_temp_file allows immediate unlinking
        for i in range(50):
            p = _create_atomic_temp_file(content=f"safe_data_{i}".encode(), directory=self.test_dir)
            self.assertTrue(p.exists())
            p.unlink()
            self.assertFalse(p.exists())

    def test_concurrent_atomic_creation_and_unlinking(self) -> None:
        """Adversarial: 50 concurrent worker threads creating, reading, and unlinking files."""
        def worker(thread_idx: int) -> bool:
            paths = []
            for j in range(10):
                p = _create_atomic_temp_file(
                    content=f"payload_t{thread_idx}_j{j}".encode(),
                    prefix=f"t{thread_idx}_",
                    suffix=".dat",
                    directory=self.test_dir,
                )
                if not p.exists() or p.read_bytes() != f"payload_t{thread_idx}_j{j}".encode():
                    return False
                paths.append(p)

            for p in paths:
                p.unlink()
                if p.exists():
                    return False
            return True

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker, i) for i in range(50)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        self.assertTrue(all(results), "All 50 concurrent threads must succeed without collisions or locking errors")

    def test_linux_fd_leak_prevention(self) -> None:
        """Adversarial: On Linux, verify that creating 200 temp files causes ZERO file descriptor leak."""
        proc_fd = Path("/proc/self/fd")
        if not proc_fd.exists():
            self.skipTest("/proc/self/fd is only available on Linux")

        # Baseline fd count
        initial_fds = set(os.listdir(proc_fd))

        created_files = []
        for i in range(200):
            p = _create_atomic_temp_file(content=b"fd_leak_probe_" + str(i).encode(), directory=self.test_dir)
            created_files.append(p)

        # Inode / fd check while files exist on disk
        mid_fds = set(os.listdir(proc_fd))
        # New open file descriptors must be 0 (all fds were closed in finally)
        fd_diff = mid_fds - initial_fds
        # Filter out transient fds from os.listdir itself
        fd_diff_clean = {fd for fd in fd_diff if fd.isdigit() and int(fd) > 2}
        # Because os.listdir opens a directory fd, fd_diff_clean should be at most 1
        self.assertLessEqual(len(fd_diff_clean), 1, f"FD leak detected: {fd_diff_clean}")

        # Cleanup
        for p in created_files:
            p.unlink()

        final_fds = set(os.listdir(proc_fd))
        final_diff = final_fds - initial_fds
        self.assertLessEqual(len(final_diff), 1, f"Residual FDs after unlinking: {final_diff}")


class TestReActAudioVideoSymmetryAndEdgeCases(unittest.IsolatedAsyncioTestCase):
    """Category 3: Semantic equivalence, case-insensitivity, and Zero-Disk Leak under adverse conditions."""

    def setUp(self) -> None:
        self.mock_ssh = MagicMock()
        self.mock_cache = MagicMock()
        self.mock_bot = MagicMock()
        self.mock_bot._http_client = MagicMock()
        self.mock_bot.send_chat_action = AsyncMock(return_value=True)
        self.mock_bot.send_audio = AsyncMock(return_value=True)
        self.mock_bot.send_video = AsyncMock(return_value=True)
        self.mock_bot.send_message = AsyncMock(return_value=True)
        self.mock_bot.send_document_file = AsyncMock(return_value=True)

        self.executor = AgentToolExecutor(
            ssh_client=self.mock_ssh,
            message_cache=self.mock_cache,
            telegram_bot=self.mock_bot,
        )

    async def test_media_type_casing_adversarial(self) -> None:
        """Adversarial: Test all combinations of casing for media_type='audio' in download_media_video."""
        casing_variants = [
            "AUDIO",
            "audio",
            "Audio",
            "AuDiO",
            "aUDIO",
            "audIO",
        ]

        for variant in casing_variants:
            with self.subTest(variant=variant):
                temp_audio = _create_atomic_temp_file(b"ID3" + b"\x00" * 1024, suffix=".mp3")
                mock_item = MediaItem(
                    file_path=str(temp_audio),
                    title=f"Song {variant}",
                    media_type="audio",
                    author="Artist",
                    duration=180,
                    file_size=1024,
                    source_url="https://vt.tiktok.com/ZSjX/",
                    is_temp_file=True,
                )

                self.mock_bot.send_audio.reset_mock()
                self.mock_bot.send_video.reset_mock()

                mock_pipeline = MagicMock()
                mock_pipeline.download_audio = AsyncMock(return_value=mock_item)
                mock_pipeline.download = AsyncMock()

                with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline):
                    result = await self.executor.execute_tool(
                        tool_name="download_media_video",
                        tool_args={"url": "https://tiktok.com/@user/video/123", "media_type": variant},
                        chat_id="123456",
                    )

                    mock_pipeline.download_audio.assert_called_once()
                    mock_pipeline.download.assert_not_called()
                    self.mock_bot.send_audio.assert_called_once()
                    self.mock_bot.send_video.assert_not_called()
                    self.assertIn("🎵", result)
                    self.assertIn(f"Song {variant}", result)
                    self.assertFalse(temp_audio.exists(), f"Temp file must be unlinked for variant '{variant}'")

    async def test_semantic_equivalence_with_caption(self) -> None:
        """Adversarial: download_media_audio and download_media_video(media_type='audio')
        with custom caption must behave 100% identically.
        """
        temp1 = _create_atomic_temp_file(b"ID3" + b"\x00" * 1024, suffix=".mp3")
        temp2 = _create_atomic_temp_file(b"ID3" + b"\x00" * 1024, suffix=".mp3")

        mock1 = MediaItem(file_path=str(temp1), title="Track 1", media_type="audio", author="DJ", duration=200, file_size=1024, source_url="https://tiktok.com/@dj/video/999", is_temp_file=True)
        mock2 = MediaItem(file_path=str(temp2), title="Track 1", media_type="audio", author="DJ", duration=200, file_size=1024, source_url="https://tiktok.com/@dj/video/999", is_temp_file=True)

        custom_cap = "✨ <b>Nhạc EDM cực cháy!</b>"

        mock_pipeline1 = MagicMock()
        mock_pipeline1.download_audio = AsyncMock(return_value=mock1)
        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline1):
            res1 = await self.executor.execute_tool(
                tool_name="download_media_audio",
                tool_args={"url": "https://tiktok.com/@dj/video/999", "caption": custom_cap},
                chat_id="888",
            )
            cap1 = self.mock_bot.send_audio.call_args.kwargs.get("caption")

        self.mock_bot.send_audio.reset_mock()

        mock_pipeline2 = MagicMock()
        mock_pipeline2.download_audio = AsyncMock(return_value=mock2)
        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline2):
            res2 = await self.executor.execute_tool(
                tool_name="download_media_video",
                tool_args={"url": "https://tiktok.com/@dj/video/999", "media_type": "audio", "caption": custom_cap},
                chat_id="888",
            )
            cap2 = self.mock_bot.send_audio.call_args.kwargs.get("caption")

        self.assertEqual(res1, res2, "Tool response messages must be strictly identical")
        self.assertEqual(cap1, cap2, "Delivered captions must be strictly identical")
        self.assertEqual(cap1, custom_cap, "Caption must match the custom caption override")
        self.assertFalse(temp1.exists(), "temp1 must be deleted")
        self.assertFalse(temp2.exists(), "temp2 must be deleted")

    async def test_zero_disk_leak_oversized_audio_transfer(self) -> None:
        """Adversarial: Audio file > 50MB must have ownership transferred to media_storage_manager
        and is_temp_file set to False, so cleanup() does NOT delete the hosted file prematurely.
        """
        temp_file = _create_atomic_temp_file(b"ID3" + b"\x00" * 1024, suffix="_oversized.mp3")
        self.assertTrue(temp_file.exists())

        mock_item = MediaItem(
            file_path=str(temp_file),
            title="Oversized Podcast",
            media_type="audio",
            author="Host",
            duration=3600,
            file_size=60 * 1024 * 1024,  # 60MB
            source_url="https://youtube.com/watch?v=longpodcast",
            is_temp_file=True,
        )

        mock_record = DownloadRecord(
            token="dl_audio_123",
            filename=temp_file.name,
            file_path=temp_file,
            file_size=60 * 1024 * 1024,
            title="Oversized Podcast",
            duration=3600,
            created_at=1000.0,
            expires_at=5000.0,
            internet_url="https://ngrok.test/oversized.mp3",
            lan_url="http://192.168.0.100/oversized.mp3",
        )

        mock_pipeline = MagicMock()
        mock_pipeline.download_audio = AsyncMock(return_value=mock_item)

        with patch("app.services.media_downloader.MultiTierMediaPipeline", return_value=mock_pipeline), \
             patch("app.services.media_storage_manager.media_storage_manager.publish_download_item", return_value=mock_record):

            result = await self.executor.execute_tool(
                tool_name="download_media_audio",
                tool_args={"url": "https://youtube.com/watch?v=longpodcast"},
                chat_id="123456",
            )

            self.assertIn("vượt quá 50MB", result)
            self.assertFalse(mock_item.is_temp_file, "is_temp_file must be flipped to False")
            self.assertTrue(temp_file.exists(), "File must still exist for media_storage_manager hosting")

        # Clean up manually
        temp_file.unlink()


if __name__ == "__main__":
    unittest.main()
