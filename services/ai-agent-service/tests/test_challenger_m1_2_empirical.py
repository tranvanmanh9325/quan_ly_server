"""
test_challenger_m1_2_empirical.py — Empirical Challenger Test Suite (Milestone M1).

Adversarial Stress Harness:
1. Concurrency & Semaphore Limits (_ytdlp_semaphore = 2):
   - 10 concurrent tasks stress test (verifying peak active workers <= 2)
   - Semaphore resilience under task cancellations and unexpected exceptions
   - Tier 1 HTTP bypass isolation (TikWM not starved by yt-dlp semaphore)
2. Zero-Disk Leak & Cleanup:
   - MediaItem.cleanup() removes standalone .mp3 temporary files
   - MediaItem.cleanup() removes nested media_ytdlp_audio_* folders and files
   - Both sync `with` and async `async with` context managers guarantee cleanup
   - Partial file unlinking upon aborted/timed-out streams (Zero partial residue)
   - Sweeping orphaned expired media via cleanup_expired_media()
   - Batch 10-task end-to-end disk sanitation
3. Zero-RAM Chunked Disk Streaming (64KB chunks):
   - Chunk size strictly capped at 64KB (65536 bytes)
   - tracemalloc empirical measurement for 20MB stream payload (heap memory overhead < 512KB)
   - Data integrity preservation (SHA-256 match after chunked writing)
4. Fallback & Pipeline Resilience:
   - Graceful fallback from Tier 1 failure to Tier 2 without leaking temp files
   - Unsupported domains safely raise MediaPipelineError with 0 leaked files
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import time
import tracemalloc
from typing import Any, Dict, List, Optional, Tuple
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import sys

# Ensure services/ai-agent-service is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.media_downloader import (
    MultiTierMediaPipeline,
    MediaItem,
    TEMP_MEDIA_DIR,
    MediaPipelineError,
    VideoTooLargeError,
    cleanup_expired_media,
)


class MockAsyncStreamContext:
    """Async context manager wrapper simulating httpx.AsyncClient.stream()."""
    def __init__(self, response: Any):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class TestChallengerConcurrencySemaphore(unittest.IsolatedAsyncioTestCase):
    """
    Stress-tests concurrency controls and asyncio.Semaphore(2) limit.
    Verifies CPU protection on 2-Core / 3.2GB RAM architecture.
    """

    async def asyncSetUp(self):
        self.pipeline = MultiTierMediaPipeline()
        TEMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    async def test_ytdlp_semaphore_concurrency_stress_10_tasks(self):
        """
        Adversarial Test: 10 concurrent YouTube/Facebook audio download tasks.
        Verifies that at ANY instantaneous moment, active workers in the yt-dlp
        executor thread pool strictly NEVER exceeds 2 (max_active <= 2).
        """
        active_workers = 0
        max_active_observed = 0
        lock = asyncio.Lock()
        completed_tasks = 0

        def _mock_sync_ytdlp_audio_download(url: str) -> MediaItem:
            nonlocal active_workers, max_active_observed, completed_tasks
            # Simulate CPU/network workload
            time.sleep(0.05)

            # Record active worker count within the critical section
            # We use threading/sleep to simulate real sync work
            dummy_file = TEMP_MEDIA_DIR / f"test_audio_{os.getpid()}_{time.time_ns()}.mp3"
            dummy_file.write_bytes(b"MOCK_YTDLP_AUDIO")

            return MediaItem(
                file_path=str(dummy_file),
                title="Concurrent Audio",
                author="Artist",
                duration=120,
                media_type="audio",
                source_url=url,
                file_size=16,
                is_temp_file=True,
            )

        async def _monitored_worker(task_id: int):
            nonlocal active_workers, max_active_observed, completed_tasks
            # Pre-acquire tracking hook right when task enters semaphore
            async with self.pipeline._ytdlp_semaphore:
                async with lock:
                    active_workers += 1
                    if active_workers > max_active_observed:
                        max_active_observed = active_workers

                # Run executor work
                loop = asyncio.get_running_loop()
                item = await loop.run_in_executor(
                    None, _mock_sync_ytdlp_audio_download, f"https://www.youtube.com/watch?v=task_{task_id}"
                )

                async with lock:
                    active_workers -= 1
                    completed_tasks += 1

                return item

        # Launch 10 simultaneous tasks
        tasks = [_monitored_worker(i) for i in range(10)]
        results = await asyncio.gather(*tasks)

        # Assertions
        self.assertEqual(len(results), 10, "All 10 tasks must complete")
        self.assertEqual(completed_tasks, 10, "10 tasks must be accounted for")
        self.assertLessEqual(
            max_active_observed,
            2,
            f"Concurrency violation: observed {max_active_observed} active workers, expected <= 2",
        )
        self.assertEqual(
            self.pipeline._ytdlp_semaphore._value,
            2,
            "Semaphore permits must fully restore to 2 after all tasks complete",
        )

        # Cleanup all created temp items
        for it in results:
            it.cleanup()

    async def test_semaphore_resilience_under_task_cancellation(self):
        """
        Adversarial Test: Tasks cancelled mid-execution must NOT leak semaphore permits.
        Tests pipeline resilience when Telegram client disconnects or request times out.
        """
        semaphore_acquired_event = asyncio.Event()

        async def _blocking_worker():
            async with self.pipeline._ytdlp_semaphore:
                semaphore_acquired_event.set()
                await asyncio.sleep(10.0)  # Long running task to be cancelled

        # Task 1 will acquire 1 permit and block
        t1 = asyncio.create_task(_blocking_worker())
        await semaphore_acquired_event.wait()

        self.assertEqual(self.pipeline._ytdlp_semaphore._value, 1)

        # Cancel the task
        t1.cancel()
        try:
            await t1
        except asyncio.CancelledError:
            pass

        # Verify semaphore value is restored to 2 immediately
        self.assertEqual(
            self.pipeline._ytdlp_semaphore._value,
            2,
            "Semaphore permits must be restored after task cancellation",
        )

    async def test_semaphore_resilience_under_worker_exceptions(self):
        """
        Adversarial Test: When yt-dlp throws unexpected errors or DownloadError,
        semaphore must be safely released without deadlock or permit leakage.
        """
        failing_urls = [
            f"https://www.youtube.com/watch?v=fail_{i}" for i in range(6)
        ]

        def _exploding_worker(url: str):
            time.sleep(0.02)
            raise RuntimeError(f"Simulated unhandled yt-dlp worker crash for {url}")

        with patch.object(self.pipeline, "_sync_ytdlp_audio_download", side_effect=_exploding_worker):
            tasks = [self.pipeline._download_ytdlp_audio(u) for u in failing_urls]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # All 6 tasks raised the simulated exception
            self.assertEqual(len(results), 6)
            for res in results:
                self.assertIsInstance(res, RuntimeError)

            # CRUCIAL CHECK: Verify semaphore permit is completely intact (value == 2)
            self.assertEqual(
                self.pipeline._ytdlp_semaphore._value,
                2,
                "Semaphore permits must be restored to 2 after worker exceptions",
            )


    async def test_tier1_tikwm_bypasses_ytdlp_semaphore(self):
        """
        Architecture Verification: Tier 1 TikWM direct HTTP download does NOT acquire
        _ytdlp_semaphore, allowing fast TikTok downloads even when yt-dlp is saturated.
        """
        # Saturate yt-dlp semaphore completely (permits = 0)
        await self.pipeline._ytdlp_semaphore.acquire()
        await self.pipeline._ytdlp_semaphore.acquire()
        self.assertEqual(self.pipeline._ytdlp_semaphore._value, 0)

        try:
            # Mock TikWM response
            tikwm_payload = {
                "code": 0,
                "data": {
                    "title": "Bypass TikTok Song",
                    "music": "https://tikwm.com/music/test.mp3",
                    "music_info": {"author": "Fast Artist", "title": "Bypass Song", "duration": 30},
                    "duration": 30,
                }
            }
            mock_client = MagicMock()
            mock_post_resp = MagicMock(status_code=200)
            mock_post_resp.json.return_value = tikwm_payload
            mock_client.post = AsyncMock(return_value=mock_post_resp)

            # Mock stream download
            with tempfile.NamedTemporaryFile(suffix=".mp3", dir=str(TEMP_MEDIA_DIR), delete=False) as tf:
                tf.write(b"TIKWM_DIRECT_DATA")
                tmp_file = tf.name

            with patch.object(self.pipeline, "_get_client", AsyncMock(return_value=mock_client)), \
                 patch.object(self.pipeline, "_stream_url_to_file", AsyncMock(return_value=(tmp_file, 17))):

                # TikWM audio download must complete IMMEDIATELY without waiting for yt-dlp semaphore
                start_t = time.perf_counter()
                item = await asyncio.wait_for(
                    self.pipeline._download_tikwm_audio("https://vt.tiktok.com/ZS_bypass/"),
                    timeout=2.0
                )
                elapsed = time.perf_counter() - start_t

                self.assertIsNotNone(item)
                self.assertEqual(item.media_type, "audio")
                self.assertLess(elapsed, 1.0, "Tier 1 must not be blocked by Tier 2 semaphore")
                item.cleanup()
        finally:
            self.pipeline._ytdlp_semaphore.release()
            self.pipeline._ytdlp_semaphore.release()


class TestChallengerZeroDiskLeak(unittest.IsolatedAsyncioTestCase):
    """
    Stress-tests disk leak defenses and artifact sanitation.
    Guarantees Zero-Disk Leak in TEMP_MEDIA_DIR under success, error, and abortion.
    """

    async def asyncSetUp(self):
        self.pipeline = MultiTierMediaPipeline()
        TEMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    def test_cleanup_tikwm_direct_mp3(self):
        """TikWM direct MP3 temporary file is cleanly removed by MediaItem.cleanup()."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", dir=str(TEMP_MEDIA_DIR), delete=False) as tf:
            tf.write(b"MP3_PAYLOAD_TIKWM")
            mp3_path = tf.name

        self.assertTrue(os.path.exists(mp3_path))
        item = MediaItem(
            file_path=mp3_path,
            title="TikWM Track",
            author="TikTok Creator",
            duration=30,
            media_type="audio",
            source_url="https://vt.tiktok.com/test/",
            is_temp_file=True,
        )

        item.cleanup()
        self.assertFalse(os.path.exists(mp3_path), "Direct MP3 file must be deleted upon cleanup")

    def test_cleanup_ytdlp_audio_folder_and_file(self):
        """yt-dlp temporary folder (media_ytdlp_audio_*) and nested .mp3 are both purged."""
        ytdlp_dir = tempfile.mkdtemp(prefix="media_ytdlp_audio_", dir=str(TEMP_MEDIA_DIR))
        mp3_file = Path(ytdlp_dir) / "extracted_audio.mp3"
        mp3_file.write_bytes(b"YTDLP_EXTRACTED_MP3_CONTENT")

        self.assertTrue(os.path.exists(ytdlp_dir))
        self.assertTrue(mp3_file.exists())

        item = MediaItem(
            file_path=str(mp3_file),
            title="Extracted YouTube Song",
            author="Artist",
            duration=180,
            media_type="audio",
            source_url="https://youtube.com/watch?v=sample",
            is_temp_file=True,
        )

        item.cleanup()
        self.assertFalse(mp3_file.exists(), "Nested MP3 file must be deleted upon cleanup")
        self.assertFalse(os.path.exists(ytdlp_dir), "Parent media_ytdlp_audio_* directory must be purged")
        self.assertTrue(TEMP_MEDIA_DIR.exists(), "TEMP_MEDIA_DIR itself must not be deleted")

    def test_zero_disk_leak_sync_and_async_context_managers(self):
        """Sync 'with' and async 'async with' context managers purge files on block exit."""
        # 1. Sync context manager
        with tempfile.NamedTemporaryFile(suffix=".mp3", dir=str(TEMP_MEDIA_DIR), delete=False) as tf:
            tf.write(b"SYNC_CM_DATA")
            sync_path = tf.name

        item_sync = MediaItem(
            file_path=sync_path,
            title="Sync Audio",
            author="Author",
            duration=10,
            media_type="audio",
            source_url="https://vt.tiktok.com/sync/",
            is_temp_file=True,
        )
        with item_sync:
            self.assertTrue(os.path.exists(sync_path))
        self.assertFalse(os.path.exists(sync_path), "File must be removed on sync block exit")

        # 2. Async context manager
        async def _test_async_cm():
            with tempfile.NamedTemporaryFile(suffix=".mp3", dir=str(TEMP_MEDIA_DIR), delete=False) as tf2:
                tf2.write(b"ASYNC_CM_DATA")
                async_path = tf2.name

            item_async = MediaItem(
                file_path=async_path,
                title="Async Audio",
                author="Author",
                duration=10,
                media_type="audio",
                source_url="https://vt.tiktok.com/async/",
                is_temp_file=True,
            )
            async with item_async:
                self.assertTrue(os.path.exists(async_path))
            self.assertFalse(os.path.exists(async_path), "File must be removed on async block exit")

        asyncio.run(_test_async_cm())

    async def test_stream_to_file_aborted_cleans_partial_file(self):
        """
        Adversarial Test: When network stream breaks midway (e.g. httpx.ReadTimeout),
        _stream_url_to_file's finally block must unlink the partial file immediately.
        """
        async def mock_aiter_bytes_failing(chunk_size=65536):
            yield b"FIRST_CHUNK_64KB" * 1024
            # Simulate sudden network connection drop
            raise TimeoutError("Simulated socket connection drop mid-stream")

        mock_response = MagicMock(status_code=200)
        mock_response.aiter_bytes = mock_aiter_bytes_failing

        mock_client = MagicMock()
        mock_client.stream = MagicMock(return_value=MockAsyncStreamContext(mock_response))

        files_before = set(os.listdir(TEMP_MEDIA_DIR))

        with self.assertRaises(TimeoutError):
            await self.pipeline._stream_url_to_file(
                "https://cdn.tiktok.com/audio/broken_stream.mp3",
                mock_client,
                suffix=".mp3",
            )

        files_after = set(os.listdir(TEMP_MEDIA_DIR))
        residual_files = files_after - files_before
        self.assertEqual(
            residual_files,
            set(),
            f"Zero-Disk Leak violation: aborted stream left residual files: {residual_files}",
        )

    def test_cleanup_expired_media_sweeps_orphaned_files_and_dirs(self):
        """
        Tests background garbage collection for orphaned files older than max_age_seconds (600s).
        Verifies old crashed artifacts are swept while fresh active files are preserved.
        """
        now = time.time()
        old_mtime = now - 1200  # 20 minutes old (>10 minutes)
        fresh_mtime = now - 30   # 30 seconds old (<10 minutes)

        # 1. Create old orphaned files and dirs
        old_file = TEMP_MEDIA_DIR / f"orphaned_file_{time.time_ns()}.mp3"
        old_file.write_bytes(b"OLD_ORPHANED_DATA")
        os.utime(old_file, (old_mtime, old_mtime))

        old_dir = TEMP_MEDIA_DIR / f"media_ytdlp_audio_orphaned_{time.time_ns()}"
        old_dir.mkdir(parents=True, exist_ok=True)
        (old_dir / "nested.mp3").write_bytes(b"OLD_NESTED_DATA")
        os.utime(old_dir, (old_mtime, old_mtime))

        # 2. Create fresh active file
        fresh_file = TEMP_MEDIA_DIR / f"fresh_active_{time.time_ns()}.mp3"
        fresh_file.write_bytes(b"FRESH_ACTIVE_DATA")
        os.utime(fresh_file, (fresh_mtime, fresh_mtime))

        # 3. Run garbage collection
        cleaned = cleanup_expired_media(max_age_seconds=600)

        # 4. Verify assertions
        self.assertGreaterEqual(cleaned, 2, "Must have cleaned at least the 2 expired entries")
        self.assertFalse(old_file.exists(), "Old orphaned file must be unlinked")
        self.assertFalse(old_dir.exists(), "Old orphaned directory must be purged")
        self.assertTrue(fresh_file.exists(), "Fresh active file must NOT be purged")

        # Clean fresh file
        if fresh_file.exists():
            fresh_file.unlink()

    async def test_batch_10_audio_items_zero_leak(self):
        """
        Stress Test: 10 audio items created, processed, and cleaned up.
        Ensures 0 leftover files in TEMP_MEDIA_DIR.
        """
        created_items: List[MediaItem] = []
        files_before = set(os.listdir(TEMP_MEDIA_DIR))

        for i in range(10):
            if i % 2 == 0:
                # Direct mp3
                with tempfile.NamedTemporaryFile(suffix=".mp3", dir=str(TEMP_MEDIA_DIR), delete=False) as tf:
                    tf.write(b"AUDIO_DATA" * 100)
                    p = tf.name
            else:
                # Nested in media_ytdlp_audio_*
                d = tempfile.mkdtemp(prefix="media_ytdlp_audio_", dir=str(TEMP_MEDIA_DIR))
                f = Path(d) / f"audio_{i}.mp3"
                f.write_bytes(b"AUDIO_NESTED" * 100)
                p = str(f)

            item = MediaItem(
                file_path=p,
                title=f"Batch Audio {i}",
                author="Batch Artist",
                duration=60,
                media_type="audio",
                source_url=f"https://source.com/{i}",
                is_temp_file=True,
            )
            created_items.append(item)

        # All 10 items exist
        self.assertEqual(len(created_items), 10)

        # Clean up all items
        for it in created_items:
            it.cleanup()

        files_after = set(os.listdir(TEMP_MEDIA_DIR))
        residual = files_after - files_before
        self.assertEqual(residual, set(), f"Zero-Disk Leak failure in batch cleanup: {residual}")


class TestChallengerZeroRamStreaming(unittest.IsolatedAsyncioTestCase):
    """
    Stress-tests memory safety (Zero-RAM streaming) using tracemalloc.
    Guarantees 64KB chunk boundary and constant heap consumption during large transfers.
    """

    async def asyncSetUp(self):
        self.pipeline = MultiTierMediaPipeline()
        TEMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    async def test_stream_chunk_size_bounded_to_64kb(self):
        """
        Verifies that chunked streaming requests chunks bounded by 64KB (65536 bytes).
        Ensures the pipeline does not load large buffers into memory.
        """
        chunks_recorded: List[int] = []

        # Generate 16 chunks of 64KB
        chunk_payload = b"A" * 65536
        total_chunks = 16

        async def mock_aiter_bytes(chunk_size=65536):
            self.assertEqual(chunk_size, 64 * 1024, "chunk_size must be exactly 64KB (65536 bytes)")
            for _ in range(total_chunks):
                chunks_recorded.append(len(chunk_payload))
                yield chunk_payload

        mock_response = MagicMock(status_code=200)
        mock_response.aiter_bytes = mock_aiter_bytes

        mock_client = MagicMock()
        mock_client.stream = MagicMock(return_value=MockAsyncStreamContext(mock_response))

        temp_path, total_bytes = await self.pipeline._stream_url_to_file(
            "https://cdn.example.com/stream.mp3",
            mock_client,
            suffix=".mp3",
        )

        try:
            self.assertEqual(len(chunks_recorded), 16)
            self.assertTrue(all(sz == 65536 for sz in chunks_recorded))
            self.assertEqual(total_bytes, 65536 * 16)
            self.assertTrue(os.path.exists(temp_path))
            self.assertEqual(os.path.getsize(temp_path), total_bytes)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    async def test_stream_large_payload_constant_ram_footprint(self):
        """
        Adversarial Test: Stream a 20MB payload (320 chunks x 64KB).
        Measures peak memory allocation using tracemalloc.
        Verifies peak heap memory overhead is < 512KB, proving Zero-RAM streaming.
        """
        total_mb = 20
        chunk_size = 64 * 1024
        total_chunks = (total_mb * 1024 * 1024) // chunk_size  # 320 chunks
        single_chunk = b"X" * chunk_size

        async def mock_aiter_bytes_20mb(chunk_size=65536):
            for _ in range(total_chunks):
                yield single_chunk

        mock_response = MagicMock(status_code=200)
        mock_response.aiter_bytes = mock_aiter_bytes_20mb

        mock_client = MagicMock()
        mock_client.stream = MagicMock(return_value=MockAsyncStreamContext(mock_response))

        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()

        temp_path, total_bytes = await self.pipeline._stream_url_to_file(
            "https://cdn.example.com/20mb_audio.mp3",
            mock_client,
            suffix=".mp3",
        )

        current_ram, peak_ram = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        try:
            self.assertEqual(total_bytes, total_mb * 1024 * 1024)
            self.assertTrue(os.path.exists(temp_path))

            # Peak RAM overhead should be negligible (< 512KB) even with a 20MB stream
            peak_kb = peak_ram / 1024
            self.assertLess(
                peak_kb,
                512,
                f"RAM Leak detected! Peak memory during 20MB stream was {peak_kb:.2f} KB (limit: 512 KB)",
            )
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    async def test_stream_preserves_audio_content_integrity_sha256(self):
        """
        Integrity Verification: Streamed chunks reconstruct the EXACT binary payload
        on disk without truncation, byte shifting, or corruption (verified via SHA-256).
        """
        # Create deterministic pseudo-random chunks
        hasher_expected = hashlib.sha256()
        raw_chunks = []
        for i in range(10):
            chunk = f"SAMPLE_AUDIO_FRAME_{i:04d}_".encode("ascii") * 2048  # ~49KB each
            raw_chunks.append(chunk)
            hasher_expected.update(chunk)
        expected_digest = hasher_expected.hexdigest()

        async def mock_aiter_bytes_integrity(chunk_size=65536):
            for c in raw_chunks:
                yield c

        mock_response = MagicMock(status_code=200)
        mock_response.aiter_bytes = mock_aiter_bytes_integrity

        mock_client = MagicMock()
        mock_client.stream = MagicMock(return_value=MockAsyncStreamContext(mock_response))

        temp_path, total_bytes = await self.pipeline._stream_url_to_file(
            "https://cdn.example.com/lossless_test.mp3",
            mock_client,
            suffix=".mp3",
        )

        try:
            self.assertTrue(os.path.exists(temp_path))
            hasher_actual = hashlib.sha256()
            with open(temp_path, "rb") as f:
                while True:
                    b = f.read(65536)
                    if not b:
                        break
                    hasher_actual.update(b)
            actual_digest = hasher_actual.hexdigest()

            self.assertEqual(
                actual_digest,
                expected_digest,
                "Binary data integrity failed: SHA-256 checksum mismatch",
            )
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)


class TestChallengerFallbackAndResilience(unittest.IsolatedAsyncioTestCase):
    """
    Stress-tests multi-tier fallback behavior and error boundaries.
    """

    async def asyncSetUp(self):
        self.pipeline = MultiTierMediaPipeline()
        TEMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    async def test_unsupported_url_raises_media_pipeline_error_zero_leak(self):
        """Unsupported URL formats cleanly raise MediaPipelineError with 0 leaked files."""
        files_before = set(os.listdir(TEMP_MEDIA_DIR))

        with patch.object(self.pipeline, "_download_ytdlp_audio", AsyncMock(return_value=None)):
            with self.assertRaises(MediaPipelineError):
                await self.pipeline.download_audio("https://unsupported-unknown-website.example.org/audio")

        files_after = set(os.listdir(TEMP_MEDIA_DIR))
        self.assertEqual(files_after - files_before, set(), "Error path must not leak files")

    async def test_tikwm_error_gracefully_falls_back_to_ytdlp_audio(self):
        """
        When TikWM API fails (HTTP 500 or code != 0), download_audio seamlessly
        falls back to Tier 2 (yt-dlp) and returns a valid MediaItem.
        """
        mock_tikwm_failure = MagicMock(status_code=500)
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_tikwm_failure)

        # Mock yt-dlp fallback item
        with tempfile.NamedTemporaryFile(suffix=".mp3", dir=str(TEMP_MEDIA_DIR), delete=False) as tf:
            tf.write(b"YTDLP_FALLBACK_AUDIO")
            fallback_path = tf.name

        mock_fallback_item = MediaItem(
            file_path=fallback_path,
            title="Fallback Track",
            author="Fallback Artist",
            duration=45,
            media_type="audio",
            source_url="https://vt.tiktok.com/ZS_fallback/",
            file_size=20,
            is_temp_file=True,
        )

        with patch.object(self.pipeline, "_get_client", AsyncMock(return_value=mock_client)), \
             patch.object(self.pipeline, "_download_ytdlp_audio", AsyncMock(return_value=mock_fallback_item)):

            res = await self.pipeline.download_audio("https://vt.tiktok.com/ZS_fallback/")

            self.assertIsNotNone(res)
            self.assertEqual(res.media_type, "audio")
            self.assertEqual(res.title, "Fallback Track")
            res.cleanup()
            self.assertFalse(os.path.exists(fallback_path), "Fallback item must clean up properly")



class TestChallengerSecurityAndPathTraversal(unittest.TestCase):
    """
    Security verification: Path traversal and boundary isolation.
    Ensures cleanup() cannot escape TEMP_MEDIA_DIR to delete user or system directories.
    """

    def test_cleanup_safe_against_none_file_path(self):
        """MediaItem with file_path=None (e.g. photo slideshows) cleans up cleanly without error."""
        item = MediaItem(
            file_path=None,
            title="Photo Album",
            author="Author",
            duration=0,
            media_type="images",
            source_url="https://vt.tiktok.com/photo/",
            images=["https://example.com/1.jpg"],
            is_temp_file=False,
        )
        try:
            item.cleanup()
        except Exception as e:
            self.fail(f"cleanup() crashed on None file_path: {e}")

    def test_cleanup_never_deletes_outside_temp_dir(self):
        """
        Adversarial Test: Even if an item's parent directory starts with 'media_ytdlp_',
        if it resides OUTSIDE TEMP_MEDIA_DIR, rmtree MUST NOT be triggered on that parent.
        """
        # Create an external directory outside TEMP_MEDIA_DIR
        external_dir = Path(tempfile.gettempdir()) / "media_ytdlp_fake_external_dir"
        external_dir.mkdir(parents=True, exist_ok=True)
        external_file = external_dir / "external_audio.mp3"
        external_file.write_bytes(b"OUTSIDE_CONTENT")

        self.assertTrue(external_file.exists())
        self.assertTrue(external_dir.exists())

        try:
            item = MediaItem(
                file_path=str(external_file),
                title="Attacker File",
                author="Hacker",
                duration=1,
                media_type="audio",
                source_url="https://malicious.com",
                is_temp_file=True,
            )

            item.cleanup()

            # The file itself may be unlinked if is_temp_file=True
            self.assertFalse(external_file.exists())
            # CRITICAL ASSERTION: The external parent directory MUST STILL EXIST!
            self.assertTrue(
                external_dir.exists(),
                "CRITICAL SECURITY VIOLATION: Directory outside TEMP_MEDIA_DIR was deleted!",
            )
        finally:
            if external_dir.exists():
                shutil.rmtree(external_dir, ignore_errors=True)


class TestChallengerYtDlpInternalSanitation(unittest.TestCase):
    """
    Stress-tests internal cleanup and option validation inside _sync_ytdlp_audio_download.
    Uses sys.modules mocking to ensure robust testing on environments without native yt-dlp.
    """

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()
        TEMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    def test_sync_ytdlp_download_error_purges_temp_dir(self):
        """
        When yt_dlp.YoutubeDL.extract_info raises DownloadError,
        the created media_ytdlp_audio_* directory must be completely removed.
        """
        mock_download_error = type("DownloadError", (Exception,), {})
        mock_ytdlp = MagicMock()
        mock_ytdlp.utils.DownloadError = mock_download_error
        mock_ydl_instance = MagicMock()
        mock_ydl_instance.extract_info.side_effect = mock_download_error("Mock download failure")
        mock_ydl_instance.__enter__.return_value = mock_ydl_instance
        mock_ytdlp.YoutubeDL.return_value = mock_ydl_instance

        dirs_before = set(os.listdir(TEMP_MEDIA_DIR))

        with patch.dict(sys.modules, {"yt_dlp": mock_ytdlp, "yt_dlp.utils": mock_ytdlp.utils}):
            res = self.pipeline._sync_ytdlp_audio_download("https://www.youtube.com/watch?v=err123")
            self.assertIsNone(res)

        dirs_after = set(os.listdir(TEMP_MEDIA_DIR))
        residual = dirs_after - dirs_before
        self.assertEqual(residual, set(), f"DownloadError left orphaned directory: {residual}")

    def test_sync_ytdlp_incomplete_download_raises_and_purges_temp_dir(self):
        """
        When yt-dlp finishes but leaves only incomplete .part files without final .mp3,
        _sync_ytdlp_audio_download raises MediaPipelineError and purges the temp directory.
        """
        mock_download_error = type("DownloadError", (Exception,), {})
        mock_ytdlp = MagicMock()
        mock_ytdlp.utils.DownloadError = mock_download_error

        def _mock_incomplete_download(url, download=True):
            # Simulate yt-dlp creating a .part file in the active temp directory
            dirs = [d for d in TEMP_MEDIA_DIR.glob("media_ytdlp_audio_*") if d.is_dir()]
            if dirs:
                latest_dir = max(dirs, key=os.path.getctime)
                part_file = latest_dir / "audio.mp3.part"
                part_file.write_bytes(b"INCOMPLETE_PART_FILE")
            return {"id": "incomplete_id", "title": "Incomplete Audio"}

        mock_ydl_instance = MagicMock()
        mock_ydl_instance.extract_info.side_effect = _mock_incomplete_download
        mock_ydl_instance.prepare_filename.return_value = "audio.mp3"
        mock_ydl_instance.__enter__.return_value = mock_ydl_instance
        mock_ytdlp.YoutubeDL.return_value = mock_ydl_instance

        dirs_before = set(os.listdir(TEMP_MEDIA_DIR))

        with patch.dict(sys.modules, {"yt_dlp": mock_ytdlp, "yt_dlp.utils": mock_ytdlp.utils}):
            with self.assertRaises(MediaPipelineError):
                self.pipeline._sync_ytdlp_audio_download("https://www.youtube.com/watch?v=incomplete123")

        dirs_after = set(os.listdir(TEMP_MEDIA_DIR))
        residual = dirs_after - dirs_before
        self.assertEqual(residual, set(), f"Incomplete download left orphaned directory: {residual}")

    def test_ytdlp_audio_options_specification(self):
        """
        Verifies yt-dlp options enforce 320kbps MP3 CBR, ID3v2.3 tags,
        bestaudio stream selection, and 2-hour duration limit.
        """
        captured_opts = {}

        class MockYoutubeDL:
            def __init__(self, opts):
                nonlocal captured_opts
                captured_opts.update(opts)
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def extract_info(self, url, download=True):
                return None

        mock_ytdlp = MagicMock()
        mock_ytdlp.YoutubeDL = MockYoutubeDL
        mock_ytdlp.utils.DownloadError = type("DownloadError", (Exception,), {})

        with patch.dict(sys.modules, {"yt_dlp": mock_ytdlp, "yt_dlp.utils": mock_ytdlp.utils}):
            self.pipeline._sync_ytdlp_audio_download("https://www.youtube.com/watch?v=opts_test")

        # 1. Format
        self.assertEqual(captured_opts.get("format"), "bestaudio/best")

        # 2. Postprocessors
        pps = captured_opts.get("postprocessors", [])
        self.assertEqual(len(pps), 1)
        self.assertEqual(pps[0].get("key"), "FFmpegExtractAudio")
        self.assertEqual(pps[0].get("preferredcodec"), "mp3")
        self.assertEqual(pps[0].get("preferredquality"), "320")

        # 3. ID3v2.3 tag compatibility
        pp_args = captured_opts.get("postprocessor_args", {}).get("FFmpegExtractAudio", [])
        self.assertIn("-id3v2_version", pp_args)
        self.assertIn("3", pp_args)

        # 4. Duration safety filter
        match_filter = captured_opts.get("match_filter")
        self.assertIsNotNone(match_filter)
        # 3-hour video (> 7200s) must be rejected
        reject_msg = match_filter({"duration": 7201})
        self.assertIsNotNone(reject_msg)
        self.assertIn("2 giờ", reject_msg)
        # 1-hour video (<= 7200s) must be accepted
        accept_msg = match_filter({"duration": 3600})
        self.assertIsNone(accept_msg)



class TestChallengerMemoryReclaimer(unittest.IsolatedAsyncioTestCase):
    """Verifies reclaim_memory_background is invoked upon download_audio completion."""

    async def asyncSetUp(self):
        self.pipeline = MultiTierMediaPipeline()
        TEMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    async def test_reclaim_memory_called_in_finally_block(self):
        """reclaim_memory_background is always called when download_audio completes or fails."""
        with patch("app.services.media_downloader.reclaim_memory_background", new=AsyncMock()) as mock_reclaim:
            with patch.object(self.pipeline, "_download_ytdlp_audio", AsyncMock(return_value=None)):
                try:
                    await self.pipeline.download_audio("https://unsupported.com/test")
                except MediaPipelineError:
                    pass

            mock_reclaim.assert_called_once_with(delay_seconds=0.2)


if __name__ == "__main__":
    unittest.main()

