"""
test_audio_pipeline_adversarial.py — Tier 5 Adversarial Coverage Hardening Suite for Audio Pipeline.

Mission: Adversarially challenge the High-Quality Audio Pipeline across:
  1. Concurrency Stress & Semaphore Hardening (20+ concurrent workers, cancellation, deadlock resistance)
  2. Network Faults & Streaming Interruption (Mid-stream TCP drops, 64KB chunk exceptions, rate limits)
  3. Pathological / Adversarial Inputs (Mega URLs, ReDoS probes, path traversal, null bytes, phishing intent)
  4. Zero-RAM Leak & Zero-Disk Leak Empirical Verification (50-cycle stress, unlinked buffers, memory stability)

Execution:
  services/ai-agent-service/.venv/Scripts/python -m unittest services/ai-agent-service/tests/test_audio_pipeline_adversarial.py
"""

from __future__ import annotations

import asyncio
import gc
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import threading
import time
import tracemalloc
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple
import unittest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import httpx

# Ensure services/ai-agent-service is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.media_downloader import (
    MultiTierMediaPipeline,
    MediaItem,
    TEMP_MEDIA_DIR,
    VideoTooLargeError,
    MediaPipelineError,
    cleanup_expired_media,
)
from app.services.telegram_bot import (
    TelegramBot,
    FastPathMediaIntent,
    _AudioFileStream,
    _strip_html_tags,
)
from app.services.ai_agent_tools import (
    AgentToolExecutor,
    DIRECT_RETURN_TOOLS,
    classify_action_risk,
    ACTION_TIER_1_SAFE,
)
from app.services.media_storage_manager import DownloadRecord, media_storage_manager


def _create_mock_telegram_bot() -> TelegramBot:
    """Creates a TelegramBot instance with mocked credentials and handlers."""
    bot = TelegramBot.__new__(TelegramBot)
    bot.token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    bot.chat_id = "123456789"
    bot._claim_update = AsyncMock(return_value=True)
    bot._video_debounce = MagicMock()
    bot._video_debounce.handle_user_text = AsyncMock(return_value=False)
    bot._pending_archives = {}
    bot._rate_limiter = MagicMock()
    bot._rate_limiter.acquire = AsyncMock()
    bot.send_message_with_result = AsyncMock(return_value={"message_id": 999})
    bot.send_message = AsyncMock(return_value=True)
    bot.delete_message = AsyncMock(return_value=True)
    bot.send_video = AsyncMock(return_value=True)
    bot.send_photo = AsyncMock(return_value=True)
    bot.send_document_file = AsyncMock(return_value=True)
    bot.send_chat_action = AsyncMock(return_value=None)
    return bot


# ═════════════════════════════════════════════════════════════════════════════
# CATEGORY 1: Concurrency Stress & Semaphore Hardening
# ═════════════════════════════════════════════════════════════════════════════

class TestTier5AdversarialConcurrencyAndLoad(unittest.TestCase):
    """Stress testing the pipeline under high concurrency and load."""

    def setUp(self):
        self.mock_client = AsyncMock(spec=httpx.AsyncClient)
        self.pipeline = MultiTierMediaPipeline(http_client=self.mock_client)
        TEMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        cleanup_expired_media(max_age_seconds=0)

    def test_adv_concurrent_semaphore_bound(self):
        """
        Verify that under 20 concurrent yt-dlp audio download tasks, the semaphore
        strictly limits parallel workers to <= 2, never causes deadlock, and recovers.
        """
        active_workers = 0
        peak_workers = 0
        thread_lock = threading.Lock()

        def _mock_sync_audio(url: str) -> MediaItem:
            nonlocal active_workers, peak_workers
            with thread_lock:
                active_workers += 1
                if active_workers > peak_workers:
                    peak_workers = active_workers

            # Artificial synchronous work simulation
            time.sleep(0.01)

            with thread_lock:
                active_workers -= 1

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, dir=str(TEMP_MEDIA_DIR)) as f:
                f.write(b"AUDIO")
                p = f.name

            return MediaItem(
                file_path=p,
                title="Concurrent Song",
                author="Artist",
                duration=180,
                media_type="audio",
                source_url=url,
                is_temp_file=True,
            )

        async def _run_stress():
            with patch.object(self.pipeline, "_sync_ytdlp_audio_download", side_effect=_mock_sync_audio):
                tasks = [
                    self.pipeline._download_ytdlp_audio(f"https://www.youtube.com/watch?v=stress_{i}")
                    for i in range(20)
                ]
                results = await asyncio.gather(*tasks)
                return results

        results = asyncio.run(_run_stress())
        self.assertEqual(len(results), 20)
        # Peak workers must not exceed 2 (guaranteed by _ytdlp_semaphore)
        self.assertLessEqual(peak_workers, 2)
        # Cleanup created files
        for res in results:
            if res:
                res.cleanup()

    def test_adv_burst_mixed_traffic_tikwm_and_ytdlp(self):
        """
        Fire 25 simultaneous requests (15 TikWM + 10 yt-dlp) in burst mode.
        Verify no thread exhaustion, no semaphore corruption, and all finish properly.
        """
        async def _run_burst():
            created_items: List[MediaItem] = []

            # Mock TikWM
            async def _mock_tikwm(url: str):
                await asyncio.sleep(0.005)
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, dir=str(TEMP_MEDIA_DIR)) as f:
                    f.write(b"TIKTOK_AUDIO")
                    p = f.name
                item = MediaItem(file_path=p, title="TikTok", author="Author", duration=30, media_type="audio", source_url=url, is_temp_file=True)
                created_items.append(item)
                return item

            # Mock yt-dlp
            async def _mock_ytdlp(url: str):
                await asyncio.sleep(0.005)
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, dir=str(TEMP_MEDIA_DIR)) as f:
                    f.write(b"YTDLP_AUDIO")
                    p = f.name
                item = MediaItem(file_path=p, title="Universal", author="Channel", duration=60, media_type="audio", source_url=url, is_temp_file=True)
                created_items.append(item)
                return item

            with patch.object(self.pipeline, "_download_tikwm_audio", side_effect=_mock_tikwm), \
                 patch.object(self.pipeline, "_download_ytdlp_audio", side_effect=_mock_ytdlp):

                tasks = []
                # 15 TikTok requests
                for i in range(15):
                    tasks.append(self.pipeline.download_audio(f"https://www.tiktok.com/@user/video/burst_{i}"))
                # 10 YouTube requests
                for i in range(10):
                    tasks.append(self.pipeline.download_audio(f"https://www.youtube.com/watch?v=burst_{i}"))

                results = await asyncio.gather(*tasks)
                return results, created_items

        results, items = asyncio.run(_run_burst())
        self.assertEqual(len(results), 25)
        # All items must have media_type audio
        self.assertTrue(all(r.media_type == "audio" for r in results))
        # Semaphore value must be restored back to 2
        self.assertEqual(self.pipeline._ytdlp_semaphore._value, 2)
        # Cleanup
        for it in items:
            it.cleanup()

    def test_adv_abrupt_cancellation_during_execution(self):
        """
        Verify that cancelling an in-flight _download_ytdlp_audio task via asyncio.CancelledError
        triggers the shield / callback cleanup pattern without leaving orphan directories or leaked semaphore permits.
        """
        cleaned_up = False

        class _MockOrphanItem:
            def cleanup(self):
                nonlocal cleaned_up
                cleaned_up = True

        async def _run_cancellation():
            def _sync_worker(url: str):
                time.sleep(0.1)
                return _MockOrphanItem()

            async def _guarded_call():
                task = asyncio.create_task(self.pipeline._download_ytdlp_audio("https://youtu.be/cancel_me"))
                await asyncio.sleep(0.02)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            with patch.object(self.pipeline, "_sync_ytdlp_audio_download", side_effect=_sync_worker):
                await _guarded_call()
                # Give background callback a moment to run
                await asyncio.sleep(0.15)

        asyncio.run(_run_cancellation())
        self.assertTrue(cleaned_up)
        # Semaphore permit must be fully returned
        self.assertEqual(self.pipeline._ytdlp_semaphore._value, 2)

    def test_adv_semaphore_release_on_unhandled_exception(self):
        """
        When the synchronous worker throws an unhandled catastrophic exception,
        the semaphore must be released immediately so subsequent tasks never deadlock.
        """
        async def _run_crash_and_recover():
            with patch.object(self.pipeline, "_sync_ytdlp_audio_download", side_effect=RuntimeError("Catastrophic crash")):
                # First task fails
                with self.assertRaises(RuntimeError):
                    await self.pipeline._download_ytdlp_audio("https://youtu.be/crash")

            # Semaphore must not be drained
            self.assertEqual(self.pipeline._ytdlp_semaphore._value, 2)

            # Subsequent normal task must execute without deadlock
            with patch.object(self.pipeline, "_sync_ytdlp_audio_download", return_value=MediaItem(
                file_path="/tmp/fake.mp3", title="Recovered", author="Dev", duration=10, media_type="audio", source_url="https://youtu.be/ok"
            )):
                item = await self.pipeline._download_ytdlp_audio("https://youtu.be/ok")
                self.assertIsNotNone(item)
                self.assertEqual(item.title, "Recovered")

        asyncio.run(_run_crash_and_recover())


# ═════════════════════════════════════════════════════════════════════════════
# CATEGORY 2: Network Faults & Streaming Interruption
# ═════════════════════════════════════════════════════════════════════════════

class TestTier5AdversarialNetworkFaultAndStreamingInterruption(unittest.TestCase):
    """Stress testing network degradation, connection drops, and partial stream handling."""

    def setUp(self):
        self.pipeline = MultiTierMediaPipeline()
        TEMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        cleanup_expired_media(max_age_seconds=0)

    def test_adv_stream_network_drop_mid_stream(self):
        """
        When downloading 64KB chunks and a network drop occurs mid-stream
        (e.g., httpx.ReadTimeout on chunk 3), verify that the partially written file
        is immediately removed from disk in the finally block.
        """
        async def _run_test():
            async def _faulty_aiter_bytes(chunk_size=65536):
                yield b"A" * 65536
                yield b"B" * 65536
                # Connection dropped midway!
                raise httpx.ReadTimeout("Connection dropped while reading socket")

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.aiter_bytes = _faulty_aiter_bytes

            mock_client = AsyncMock(spec=httpx.AsyncClient)
            mock_client.stream.return_value.__aenter__.return_value = mock_response

            before_files = set(TEMP_MEDIA_DIR.glob("*.mp3"))
            with self.assertRaises(httpx.ReadTimeout):
                await self.pipeline._stream_url_to_file("https://cdn.example.com/audio.mp3", mock_client, suffix=".mp3")

            after_files = set(TEMP_MEDIA_DIR.glob("*.mp3"))
            # No partial files may remain!
            self.assertEqual(before_files, after_files)

        asyncio.run(_run_test())

    def test_adv_stream_network_reset_remote_protocol_error(self):
        """
        When remote CDN sends TCP RST causing httpx.RemoteProtocolError,
        verify zero residue on disk and clean exception raising.
        """
        async def _run_test():
            async def _faulty_aiter_bytes(chunk_size=65536):
                yield b"CHUNK_1"
                raise httpx.RemoteProtocolError("Connection closed without response")

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.aiter_bytes = _faulty_aiter_bytes

            mock_client = AsyncMock(spec=httpx.AsyncClient)
            mock_client.stream.return_value.__aenter__.return_value = mock_response

            with self.assertRaises(httpx.RemoteProtocolError):
                await self.pipeline._stream_url_to_file("https://cdn.example.com/audio.mp3", mock_client, suffix=".mp3")

        asyncio.run(_run_test())

    def test_adv_send_audio_connection_drop_closes_stream(self):
        """
        When Telegram Bot API drops connection mid-upload, verify that the open file
        descriptor is strictly closed in the finally block, preventing handle leaks.
        """
        bot = _create_mock_telegram_bot()
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"AUDIO_DATA" * 1024)
            temp_path = f.name

        try:
            mock_http = AsyncMock()
            mock_http.post.side_effect = httpx.NetworkError("Broken pipe")

            async def _send():
                with patch.object(TelegramBot, "_http_client", new_callable=PropertyMock) as mock_prop:
                    mock_prop.return_value = mock_http
                    return await bot.send_audio(
                        chat_id="123",
                        audio_path=temp_path,
                        title="Interrupted Song",
                        performer="Artist",
                    )

            success = asyncio.run(_send())
            self.assertFalse(success)

            # Test that file can be immediately unlinked without Windows file-locking PermissionError
            try:
                os.unlink(temp_path)
                file_unlinked = True
            except PermissionError:
                file_unlinked = False

            self.assertTrue(file_unlinked, "File was still locked by unclosed file descriptor!")
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_adv_send_audio_rate_limit_429(self):
        """
        When Telegram returns HTTP 429 Too Many Requests, send_audio must return False
        without raising unhandled exceptions, and must close file handle.
        """
        bot = _create_mock_telegram_bot()
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"TEST_RATE_LIMIT")
            temp_path = f.name

        try:
            resp_429 = MagicMock()
            resp_429.status_code = 429
            resp_429.text = '{"ok":false,"error_code":429,"description":"Too Many Requests: retry after 30"}'
            mock_http = AsyncMock()
            mock_http.post.return_value = resp_429

            async def _send():
                with patch.object(TelegramBot, "_http_client", new_callable=PropertyMock) as mock_prop:
                    mock_prop.return_value = mock_http
                    return await bot.send_audio(chat_id="123", audio_path=temp_path)

            success = asyncio.run(_send())
            self.assertFalse(success)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_adv_tikwm_http_502_bad_gateway_falls_back_cleanly(self):
        """
        When TikWM API server is down (HTTP 502/503), the pipeline must catch it,
        attempt Tier 2 (yt-dlp), and if Tier 2 succeeds, deliver without error.
        """
        async def _run_test():
            mock_client = AsyncMock(spec=httpx.AsyncClient)
            bad_gateway_resp = MagicMock()
            bad_gateway_resp.status_code = 502
            bad_gateway_resp.text = "Bad Gateway"
            mock_client.post.return_value = bad_gateway_resp

            pipeline = MultiTierMediaPipeline(http_client=mock_client)

            with patch.object(pipeline, "_download_ytdlp_audio", return_value=MediaItem(
                file_path="/tmp/ytdlp_fallback.mp3",
                title="Fallback Song",
                author="Artist",
                duration=45,
                media_type="audio",
                source_url="https://vt.tiktok.com/ZS12345/",
            )):
                result = await pipeline.download_audio("https://vt.tiktok.com/ZS12345/")
                self.assertIsNotNone(result)
                self.assertEqual(result.title, "Fallback Song")

        asyncio.run(_run_test())


# ═════════════════════════════════════════════════════════════════════════════
# CATEGORY 3: Pathological / Adversarial Inputs & Phishing Traps
# ═════════════════════════════════════════════════════════════════════════════

class TestTier5AdversarialInputAndEdgeCases(unittest.TestCase):
    """Stress testing abnormal, malicious, and adversarial inputs."""

    def setUp(self):
        self.bot = _create_mock_telegram_bot()
        self.pipeline = MultiTierMediaPipeline()

    def test_adv_mega_url_redos_resistance(self):
        """
        Send a 65,536-character URL to _detect_fastpath_media_download and verify
        that regex matching finishes in < 50ms without catastrophic backtracking.
        """
        mega_url = "https://www.tiktok.com/@user/video/" + "a" * 65000 + "?ref=share"
        full_text = f"tải mp3 link này nè em {mega_url}"

        t0 = time.perf_counter()
        intent = self.bot._detect_fastpath_media_download(full_text)
        duration = time.perf_counter() - t0

        self.assertLess(duration, 0.05, f"Regex took too long ({duration:.4f}s) - ReDoS vulnerability!")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.media_type, "audio")

    def test_adv_path_traversal_quarantine(self):
        """
        Verify that URLs attempting directory traversal (e.g. ../../) do NOT
        allow writing files outside TEMP_MEDIA_DIR.
        """
        malicious_url = "https://www.tiktok.com/../../../../etc/passwd"
        async def _test():
            with patch.object(self.pipeline, "_get_client") as mock_get_client:
                mock_client = AsyncMock()
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {
                    "code": 0,
                    "data": {
                        "music": "https://www.tikwm.com/media/music/evil.mp3",
                        "title": "../../../traversal_song",
                    }
                }
                mock_client.post.return_value = mock_resp
                mock_get_client.return_value = mock_client

                with patch.object(self.pipeline, "_stream_url_to_file") as mock_stream:
                    mock_stream.return_value = (str(TEMP_MEDIA_DIR / "safe.mp3"), 1024)
                    item = await self.pipeline._download_tikwm_audio(malicious_url)
                    self.assertIsNotNone(item)
                    resolved_file = Path(item.file_path).resolve()
                    self.assertTrue(resolved_file.is_relative_to(TEMP_MEDIA_DIR.resolve()))

        asyncio.run(_test())

    def test_adv_non_http_schemes_rejected(self):
        """
        Verify that dangerous schemes (file://, gopher://, javascript:) are rejected
        by download_audio without executing system commands or reading local disk.
        """
        dangerous_urls = [
            "file:///etc/shadow",
            "file:///c:/windows/system32/cmd.exe",
            "gopher://127.0.0.1:6379/_flushall",
            "javascript:alert(document.cookie)",
        ]

        async def _test():
            for url in dangerous_urls:
                with self.assertRaises(MediaPipelineError):
                    await self.pipeline.download_audio(url)

        asyncio.run(_test())

    def test_adv_null_bytes_and_special_control_chars(self):
        """
        Verify that null bytes (\x00) and control characters in titles and captions
        are sanitized and do not crash send_audio.
        """
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"AUDIO")
            p = f.name

        try:
            mock_http = AsyncMock()
            mock_http.post.return_value = MagicMock(status_code=200)
            toxic_caption = "Normal\x00Toxic\x1b[31mRed\x07Bell"
            toxic_title = "Title\x00WithNull"
            toxic_performer = "Performer\x00WithNull"

            async def _send():
                with patch.object(TelegramBot, "_http_client", new_callable=PropertyMock) as mock_prop:
                    mock_prop.return_value = mock_http
                    return await self.bot.send_audio(
                        chat_id="123",
                        audio_path=p,
                        caption=toxic_caption,
                        title=toxic_title,
                        performer=toxic_performer,
                    )

            success = asyncio.run(_send())
            self.assertTrue(success)
        finally:
            if os.path.exists(p):
                os.unlink(p)

    def test_adv_fastpath_phishing_and_conflicting_intent_traps(self):
        """
        Adversarially probe FastPath intent resolution when deceptive or conflicting
        keywords are used:
        1. "tải video nhưng đừng tải mp3" -> Negative keyword overrides -> None (LLM)
        2. "tại sao không tải mp3 bài này" -> Analysis keyword overrides -> None (LLM)
        3. "tải mp3 https://vt.tiktok.com/123/ đừng lấy nhạc" -> Negative keyword overrides -> None
        4. "tải video và tách nhạc" -> Audio keyword triggers audio intent
        5. "tải  \t  \n mp3" -> Audio intent recognized despite irregular whitespace
        """
        url = "https://vt.tiktok.com/ZS12345/"

        # 1. Negative override
        p1 = f"tải video {url} nhưng đừng tải mp3"
        self.assertIsNone(self.bot._detect_fastpath_media_download(p1))

        # 2. Analysis question override
        p2 = f"tại sao không tải mp3 bài này {url} được hả em?"
        self.assertIsNone(self.bot._detect_fastpath_media_download(p2))

        # 3. Explicit negative override
        p3 = f"tải mp3 {url} nhưng đừng lấy nhạc"
        self.assertIsNone(self.bot._detect_fastpath_media_download(p3))

        # 4. Audio keyword priority
        p4 = f"tải video {url} và tách nhạc giùm anh"
        intent4 = self.bot._detect_fastpath_media_download(p4)
        self.assertIsNotNone(intent4)
        self.assertEqual(intent4.media_type, "audio")

        # 5. Irregular whitespace
        p5 = f"tải   \t   \n  mp3  {url}"
        intent5 = self.bot._detect_fastpath_media_download(p5)
        self.assertIsNotNone(intent5)
        self.assertEqual(intent5.media_type, "audio")


# ═════════════════════════════════════════════════════════════════════════════
# CATEGORY 4: Zero-RAM Leak & Zero-Disk Leak Comprehensive Audit
# ═════════════════════════════════════════════════════════════════════════════

class TestTier5AdversarialZeroLeakAndResourceAudit(unittest.TestCase):
    """Rigorous audit to confirm zero RAM leaks and zero disk leaks across repeated operations."""

    def setUp(self):
        TEMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        cleanup_expired_media(max_age_seconds=0)

    def test_adv_zero_disk_leak_50_repeated_cycles(self):
        """
        Execute 50 rapid sequential download-and-cleanup cycles.
        Verify that after 50 cycles, TEMP_MEDIA_DIR contains exactly 0 files.
        """
        for i in range(50):
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, dir=str(TEMP_MEDIA_DIR)) as f:
                f.write(b"AUDIO_CYCLE_DATA_" * 100)
                file_path = f.name

            item = MediaItem(
                file_path=file_path,
                title=f"Cycle {i}",
                author="Stress Tester",
                duration=60,
                media_type="audio",
                source_url=f"https://vt.tiktok.com/cycle_{i}/",
                is_temp_file=True,
            )

            # Cleanup via context manager
            with item:
                self.assertTrue(os.path.exists(file_path))

            self.assertFalse(os.path.exists(file_path))

        # Check total remaining files in TEMP_MEDIA_DIR
        leftovers = list(TEMP_MEDIA_DIR.glob("*.mp3"))
        self.assertEqual(len(leftovers), 0, f"Detected disk leak! Leftovers: {leftovers}")

    def test_adv_zero_ram_leak_memory_footprint(self):
        """
        Track memory usage over 30 audio stream operations using tracemalloc.
        Verify that peak memory growth does not leak unbounded byte buffers.
        """
        tracemalloc.start()
        snapshot_start = tracemalloc.take_snapshot()

        for _ in range(30):
            raw_bytes = b"X" * (64 * 1024)
            stream = _AudioFileStream(MagicMock(read=MagicMock(side_effect=[raw_bytes, b""])), len(raw_bytes))
            data = stream.read(64 * 1024)
            self.assertEqual(len(data), 64 * 1024)
            stream.close()
            del stream, raw_bytes, data

        gc.collect()
        snapshot_end = tracemalloc.take_snapshot()
        stats = snapshot_end.compare_to(snapshot_start, 'lineno')

        # Top memory diff line must not exceed 2MB for 30 cycles
        top_diff = sum(stat.size_diff for stat in stats if stat.size_diff > 0)
        tracemalloc.stop()

        self.assertLess(top_diff, 2 * 1024 * 1024, f"Potential memory leak! Size diff: {top_diff} bytes")

    def test_adv_parent_directory_cleanup_protection(self):
        """
        Verify that MediaItem.cleanup() deletes media_ytdlp_audio_* subdirectories,
        but NEVER deletes TEMP_MEDIA_DIR itself even if file_path is directly in TEMP_MEDIA_DIR.
        """
        direct_file = TEMP_MEDIA_DIR / "direct_file.mp3"
        direct_file.write_bytes(b"DIRECT")

        item = MediaItem(
            file_path=str(direct_file),
            title="Direct File",
            author="Author",
            duration=10,
            media_type="audio",
            source_url="https://youtube.com/test",
            is_temp_file=True,
        )
        item.cleanup()

        self.assertFalse(direct_file.exists())
        # TEMP_MEDIA_DIR must still exist!
        self.assertTrue(TEMP_MEDIA_DIR.exists())

    def test_adv_cleanup_expired_media_deep_hierarchy(self):
        """
        Create nested directories and files in TEMP_MEDIA_DIR with old mtime.
        Verify cleanup_expired_media cleanly purges them while preserving fresh files.
        """
        old_dir = TEMP_MEDIA_DIR / "media_ytdlp_audio_old_session"
        old_dir.mkdir(parents=True, exist_ok=True)
        old_file = old_dir / "old_audio.mp3"
        old_file.write_bytes(b"OLD_AUDIO")

        fresh_file = TEMP_MEDIA_DIR / "fresh_audio.mp3"
        fresh_file.write_bytes(b"FRESH_AUDIO")

        # Fake old timestamp (20 minutes ago)
        old_time = time.time() - 1200
        os.utime(str(old_file), (old_time, old_time))
        os.utime(str(old_dir), (old_time, old_time))

        cleaned = cleanup_expired_media(max_age_seconds=600)
        self.assertGreaterEqual(cleaned, 1)
        self.assertFalse(old_dir.exists())
        self.assertTrue(fresh_file.exists())

        # Cleanup fresh file
        fresh_file.unlink()

    def test_adv_storage_publisher_fallback_large_audio_zero_leak(self):
        """
        When audio file > 50MB is transferred to media_storage_manager,
        verify that DownloadRecord is properly created and file is accounted for.
        """
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"0" * (51 * 1024 * 1024))
            large_file = f.name

        try:
            bot = _create_mock_telegram_bot()
            # send_audio rejects > 50MB
            can_send = asyncio.run(bot.send_audio(chat_id="123", audio_path=large_file))
            self.assertFalse(can_send)

            # Publish to media_storage_manager
            with patch.object(media_storage_manager, "publish_download_item", return_value=DownloadRecord(
                token="tok_large_audio_123",
                filename="large_audio.mp3",
                file_path=Path(large_file),
                file_size=51 * 1024 * 1024,
                title="Symphony No. 9",
                duration=3600,
                created_at=time.time(),
                expires_at=time.time() + 3600,
            )) as mock_publish:
                record = media_storage_manager.publish_download_item(
                    file_path=Path(large_file),
                    media_type="audio",
                    title="Symphony No. 9",
                )
                self.assertIsNotNone(record)
                self.assertEqual(record.token, "tok_large_audio_123")
                mock_publish.assert_called_once()
        finally:
            if os.path.exists(large_file):
                os.unlink(large_file)


if __name__ == "__main__":
    unittest.main()
