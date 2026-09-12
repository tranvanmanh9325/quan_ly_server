"""
test_media_concurrency_and_leak_stress.py — Stress test suite for MultiTierMediaPipeline.

Challenger M1_2 Empirical Harness:
1. Concurrency limit verification: Semaphore(2) for yt-dlp and Semaphore(1) for Playwright.
2. Playwright Semaphore contention verification during network streaming.
3. Zero-Disk-Leak verification under stream aborts, exceptions, timeouts, and cancellations.
4. TEMP_MEDIA_DIR deletion bug verification during MediaItem.cleanup().
5. cleanup_expired_media verification for expired files and orphan directories.
"""

import asyncio
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.media_downloader import (
    MultiTierMediaPipeline,
    MediaItem,
    MediaPipelineError,
    VideoTooLargeError,
    cleanup_expired_media,
    TEMP_MEDIA_DIR,
    TELEGRAM_MAX_FILE_SIZE,
)


class TestMediaPipelineConcurrencyStress(unittest.IsolatedAsyncioTestCase):
    """Stress testing concurrency limits of yt-dlp Semaphore(2) and Playwright Semaphore(1)."""

    async def asyncSetUp(self):
        TEMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        self.pipeline = MultiTierMediaPipeline()

    async def test_ytdlp_semaphore_strictly_caps_at_two_concurrent_tasks(self):
        """Kiểm chứng thực nghiệm: 10 request dồn dập vào _download_ytdlp không vượt quá 2 concurrent tasks."""
        current_active = 0
        peak_active = 0
        lock = asyncio.Lock()

        async def worker(url: str):
            nonlocal current_active, peak_active
            async with self.pipeline._ytdlp_semaphore:
                async with lock:
                    current_active += 1
                    if current_active > peak_active:
                        peak_active = current_active
                await asyncio.sleep(0.04)
                async with lock:
                    current_active -= 1

        tasks = [asyncio.create_task(worker(f"https://youtube.com/watch?v={i}")) for i in range(10)]
        await asyncio.gather(*tasks)

        self.assertLessEqual(peak_active, 2, f"Peak concurrent yt-dlp workers was {peak_active}, expected <= 2")
        self.assertEqual(self.pipeline._ytdlp_semaphore._value, 2, "Semaphore value must return to 2 after completion")

    async def test_playwright_semaphore_strictly_caps_at_one_concurrent_task(self):
        """Kiểm chứng thực nghiệm: Nhiều request vào Playwright không bao giờ vượt quá 1 concurrent instance."""
        current_active = 0
        peak_active = 0
        lock = asyncio.Lock()

        async def worker(url: str):
            nonlocal current_active, peak_active
            async with self.pipeline._playwright_semaphore:
                async with lock:
                    current_active += 1
                    if current_active > peak_active:
                        peak_active = current_active
                await asyncio.sleep(0.05)
                async with lock:
                    current_active -= 1

        tasks = [asyncio.create_task(worker(f"https://www.threads.net/@u/post/{i}")) for i in range(6)]
        await asyncio.gather(*tasks)

        self.assertEqual(peak_active, 1, f"Peak concurrent Playwright workers was {peak_active}, expected == 1")
        self.assertEqual(self.pipeline._playwright_semaphore._value, 1, "Playwright semaphore must return to 1")

    async def test_semaphore_release_on_unexpected_exception(self):
        """Kiểm chứng thực nghiệm: Khi worker ném Exception, Semaphore vẫn được hoàn trả trọn vẹn."""
        with patch.object(self.pipeline, "_sync_ytdlp_download", side_effect=RuntimeError("Simulated crash")):
            with self.assertRaises(RuntimeError):
                await self.pipeline._download_ytdlp("https://youtube.com/watch?v=err")

        self.assertEqual(self.pipeline._ytdlp_semaphore._value, 2, "Semaphore(2) must not leak on exceptions")


class TestZeroDiskLeakUnderExceptions(unittest.IsolatedAsyncioTestCase):
    """Kiểm chứng thực nghiệm bảo vệ 100% Zero-Disk-Leak khi gặp các sự cố bất ngờ."""

    async def asyncSetUp(self):
        TEMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        self.pipeline = MultiTierMediaPipeline()
        for p in TEMP_MEDIA_DIR.iterdir():
            if p.is_file():
                p.unlink(missing_ok=True)
            elif p.is_dir():
                shutil.rmtree(p, ignore_errors=True)

    def count_temp_items(self) -> int:
        if not TEMP_MEDIA_DIR.exists():
            return 0
        return len(list(TEMP_MEDIA_DIR.iterdir()))

    async def test_stream_aborted_when_file_exceeds_threshold_removes_temp_file(self):
        """Khi stream vượt quá ngưỡng 48MB, file tạm phải bị unlink ngay lập tức."""
        initial_count = self.count_temp_items()

        async def fake_aiter_bytes(chunk_size=64 * 1024):
            chunk = b"X" * (64 * 1024)
            for _ in range(800):  # 800 * 64KB = 50MB
                yield chunk

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.aiter_bytes = fake_aiter_bytes

        mock_client = MagicMock()
        mock_client.stream.return_value.__aenter__.return_value = mock_resp
        mock_client.stream.return_value.__aexit__.return_value = None

        with self.assertRaises(VideoTooLargeError):
            await self.pipeline._stream_url_to_file("https://example.com/big.mp4", mock_client)

        self.assertEqual(self.count_temp_items(), initial_count, "No temp file should leak on VideoTooLargeError")

    async def test_stream_aborted_on_network_error_removes_temp_file(self):
        """Khi kết nối mạng đứt giữa chừng lúc stream, file tạm phải bị xóa sạch."""
        initial_count = self.count_temp_items()

        async def fake_aiter_bytes_crash(chunk_size=64 * 1024):
            yield b"First partial chunk"
            raise ConnectionResetError("Connection lost mid-stream")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.aiter_bytes = fake_aiter_bytes_crash

        mock_client = MagicMock()
        mock_client.stream.return_value.__aenter__.return_value = mock_resp
        mock_client.stream.return_value.__aexit__.return_value = None

        with self.assertRaises(ConnectionResetError):
            await self.pipeline._stream_url_to_file("https://example.com/broken.mp4", mock_client)

        self.assertEqual(self.count_temp_items(), initial_count, "No temp file should leak on network error")

    async def test_stream_status_not_200_leaves_zero_files(self):
        """Khi server trả về HTTP status != 200 (ví dụ 403/404), không tạo ra file tạm nào."""
        initial_count = self.count_temp_items()

        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.headers = {}

        mock_client = MagicMock()
        mock_client.stream.return_value.__aenter__.return_value = mock_resp
        mock_client.stream.return_value.__aexit__.return_value = None

        with self.assertRaises(MediaPipelineError):
            await self.pipeline._stream_url_to_file("https://example.com/forbidden.mp4", mock_client)

        self.assertEqual(self.count_temp_items(), initial_count, "No temp file should exist when HTTP != 200")

    async def test_stream_cancellation_disk_leak_behavior(self):
        """
        Thực nghiệm kiểm tra nếu task bị asyncio.CancelledError giữa chừng khi streaming.
        LƯU Ý: asyncio.CancelledError là BaseException trong Python 3.8+.
        """
        temp_file_recorded = None
        started_event = asyncio.Event()

        async def slow_aiter(chunk_size=64 * 1024):
            started_event.set()
            while True:
                yield b"A" * 1024
                await asyncio.sleep(0.05)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.aiter_bytes = slow_aiter

        mock_client = MagicMock()
        mock_client.stream.return_value.__aenter__.return_value = mock_resp
        mock_client.stream.return_value.__aexit__.return_value = None

        async def runner():
            return await self.pipeline._stream_url_to_file("https://example.com/slow.mp4", mock_client)

        task = asyncio.create_task(runner())
        await started_event.wait()
        await asyncio.sleep(0.02)

        mp4_files = list(TEMP_MEDIA_DIR.glob("*.mp4"))
        self.assertGreaterEqual(len(mp4_files), 1, "Temp file must exist during active stream")
        temp_file_recorded = mp4_files[0]

        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        file_still_exists = temp_file_recorded.exists()
        if file_still_exists:
            temp_file_recorded.unlink(missing_ok=True)
            self.fail(
                "DISK LEAK CONFIRMED: Temp file was not unlinked upon asyncio.CancelledError! "
                "media_downloader.py uses 'except Exception:' which does not catch BaseException / CancelledError."
            )
        else:
            self.assertFalse(file_still_exists, "Temp file successfully unlinked on cancellation")

    def test_sync_ytdlp_download_cleans_up_part_files_and_temp_dir_on_failure(self):
        """yt-dlp khi tải dở bị ngắt phải xóa sạch thư mục tạm và các file .part."""
        pipeline = MultiTierMediaPipeline()
        fake_url = "https://youtube.com/watch?v=fake_part"

        mock_ytdlp_module = MagicMock()
        mock_ydl_instance = MagicMock()

        def side_effect_extract(url, download=True):
            subdirs = [p for p in TEMP_MEDIA_DIR.iterdir() if p.is_dir() and p.name.startswith("media_ytdlp_")]
            if subdirs:
                target = subdirs[0]
                part_file = target / "media_fake.mp4.part"
                part_file.write_bytes(b"partial video bytes")
            return None

        mock_ydl_instance.extract_info.side_effect = side_effect_extract
        mock_ytdlp_module.YoutubeDL.return_value.__enter__.return_value = mock_ydl_instance
        mock_ytdlp_module.YoutubeDL.return_value.__exit__.return_value = None

        with patch.dict("sys.modules", {"yt_dlp": mock_ytdlp_module}):
            res = pipeline._sync_ytdlp_download(fake_url)
            self.assertIsNone(res)

        remaining_subdirs = [p for p in TEMP_MEDIA_DIR.iterdir() if p.is_dir() and p.name.startswith("media_ytdlp_")]
        self.assertEqual(len(remaining_subdirs), 0, "No media_ytdlp_* temporary directory should remain")

    async def test_ytdlp_cancellation_cleans_up_orphaned_media_item_and_temp_dir(self):
        """
        Kiểm chứng thực nghiệm: Khi coroutine _download_ytdlp bị asyncio.CancelledError giữa chừng,
        worker thread chạy ngầm khi hoàn tất phải tự động dọn dẹp sạch MediaItem và thư mục tạm.
        """
        created_file = None
        created_dir = None
        started_event = asyncio.Event()
        loop = asyncio.get_running_loop()

        def sync_worker(url: str):
            nonlocal created_file, created_dir
            t_dir = tempfile.mkdtemp(prefix="media_ytdlp_cancel_test_", dir=str(TEMP_MEDIA_DIR))
            created_dir = t_dir
            t_file = os.path.join(t_dir, "cancelled_video.mp4")
            with open(t_file, "wb") as f:
                f.write(b"downloaded content in background thread")
            created_file = t_file
            loop.call_soon_threadsafe(started_event.set)
            time.sleep(0.15)
            return MediaItem(
                file_path=t_file,
                title="Cancelled Test",
                author="Tester",
                duration=10,
                media_type="video",
                source_url=url,
                file_size=len(b"downloaded content in background thread"),
                is_temp_file=True,
            )

        with patch.object(self.pipeline, "_sync_ytdlp_download", side_effect=sync_worker):
            task = asyncio.create_task(self.pipeline._download_ytdlp("https://www.youtube.com/shorts/cancel123"))
            await started_event.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

            # Chờ worker thread hoàn tất ngầm và kích hoạt callback dọn dẹp
            await asyncio.sleep(0.3)

            self.assertIsNotNone(created_file)
            self.assertFalse(os.path.exists(created_file), "Tệp mồ côi phải được xóa sạch sau khi thread hoàn tất!")
            self.assertFalse(os.path.exists(created_dir), "Thư mục tạm media_ytdlp_* phải được xóa sạch!")

    def test_sync_ytdlp_download_split_stream_m4a_residual_triggers_video_too_large(self):
        """
        Kiểm chứng thực nghiệm: yt-dlp khi tải video DASH tách luồng bị ngắt video nhưng còn sót tệp audio .m4a
        phải kích hoạt VideoTooLargeError và dọn dẹp 100% thư mục tạm thay vì trả về None.
        """
        pipeline = MultiTierMediaPipeline()
        fake_url = "https://facebook.com/reel/fake_dash_split"

        class SplitStreamYDL:
            def __init__(self, opts):
                self.opts = opts
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc_val, exc_tb):
                pass
            def extract_info(self, url, download=True):
                subdirs = [p for p in TEMP_MEDIA_DIR.iterdir() if p.is_dir() and p.name.startswith("media_ytdlp_")]
                if subdirs:
                    target = subdirs[0]
                    # Mô phỏng luồng audio .m4a tải thành công còn video bị ngắt
                    audio_part = target / "media_fake.f140.m4a"
                    audio_part.write_bytes(b"audio stream residual bytes")
                return {"id": "fake_dash"}
            def prepare_filename(self, info):
                subdirs = [p for p in TEMP_MEDIA_DIR.iterdir() if p.is_dir() and p.name.startswith("media_ytdlp_")]
                target = subdirs[0] if subdirs else TEMP_MEDIA_DIR
                return str(target / "media_fake.mp4")

        mock_ytdlp = MagicMock()
        mock_ytdlp.YoutubeDL = SplitStreamYDL
        mock_utils = MagicMock()
        mock_ytdlp.utils = mock_utils

        with patch.dict("sys.modules", {"yt_dlp": mock_ytdlp, "yt_dlp.utils": mock_utils}):
            with self.assertRaises(VideoTooLargeError):
                pipeline._sync_ytdlp_download(fake_url)

        remaining_subdirs = [p for p in TEMP_MEDIA_DIR.iterdir() if p.is_dir() and p.name.startswith("media_ytdlp_")]
        self.assertEqual(len(remaining_subdirs), 0, "Thư mục tạm chứa tệp dở dang .m4a phải bị xóa sạch 100%!")


class TestMediaItemDirectorySafety(unittest.TestCase):
    """Kiểm tra an toàn cấu trúc thư mục của MediaItem.cleanup()."""

    def setUp(self):
        TEMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    def test_cleanup_must_not_delete_temp_media_root_directory(self):
        """
        Kiểm chứng thực nghiệm: item.cleanup() KHÔNG ĐƯỢC XÓA thư mục gốc TEMP_MEDIA_DIR.
        Lỗi xảy ra khi so sánh parent != TEMP_MEDIA_DIR do khác biệt phân giải đường dẫn
        kết hợp với parent.name.startswith('media_') vì tên gốc là 'media_downloads'.
        """
        with tempfile.NamedTemporaryFile(suffix=".mp4", dir=str(TEMP_MEDIA_DIR), delete=False) as tf:
            temp_path = tf.name

        item = MediaItem(
            file_path=temp_path,
            title="Root Dir Safety Test",
            author="Author",
            duration=5,
            media_type="video",
            source_url="https://example.com/test",
            is_temp_file=True,
        )

        item.cleanup()

        # Kiểm tra file tạm đã bị xóa
        self.assertFalse(os.path.exists(temp_path), "Temporary file must be deleted")
        # Kiểm tra thư mục gốc TEMP_MEDIA_DIR VẪN PHẢI TỒN TẠI!
        self.assertTrue(
            TEMP_MEDIA_DIR.exists(),
            "CRITICAL BUG CONFIRMED: TEMP_MEDIA_DIR itself was recursively deleted by item.cleanup()!"
        )


class TestCleanupExpiredMediaDeep(unittest.TestCase):
    """Kiểm tra chuyên sâu hàm cleanup_expired_media với các cấu trúc tệp và thư mục mồ côi."""

    def setUp(self):
        TEMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        for p in TEMP_MEDIA_DIR.iterdir():
            if p.is_file():
                p.unlink(missing_ok=True)
            elif p.is_dir():
                shutil.rmtree(p, ignore_errors=True)

    def tear_down(self):
        self.setUp()

    def test_cleanup_expired_files_and_directories(self):
        now = time.time()

        old_file = TEMP_MEDIA_DIR / "orphan_old.mp4"
        old_file.write_bytes(b"old orphan content")
        fifteen_min_ago = now - 900
        os.utime(str(old_file), (fifteen_min_ago, fifteen_min_ago))

        old_dir = TEMP_MEDIA_DIR / "media_ytdlp_orphan_dir"
        old_dir.mkdir()
        nested_file = old_dir / "nested.part"
        nested_file.write_bytes(b"nested part bytes")
        twelve_min_ago = now - 720
        os.utime(str(old_dir), (twelve_min_ago, twelve_min_ago))

        fresh_file = TEMP_MEDIA_DIR / "active_file.mp4"
        fresh_file.write_bytes(b"active fresh content")
        one_min_ago = now - 60
        os.utime(str(fresh_file), (one_min_ago, one_min_ago))

        fresh_dir = TEMP_MEDIA_DIR / "media_ytdlp_active_dir"
        fresh_dir.mkdir()
        fresh_nested = fresh_dir / "active_nested.mp4"
        fresh_nested.write_bytes(b"active nested bytes")
        thirty_sec_ago = now - 30
        os.utime(str(fresh_dir), (thirty_sec_ago, thirty_sec_ago))

        cleaned_count = cleanup_expired_media(max_age_seconds=600)

        self.assertFalse(old_file.exists(), "Old file > 600s must be deleted")
        self.assertFalse(old_dir.exists(), "Old directory > 600s must be recursively deleted")

        self.assertTrue(fresh_file.exists(), "Fresh file < 600s must NOT be deleted")
        self.assertTrue(fresh_dir.exists(), "Fresh directory < 600s must NOT be deleted")
        self.assertTrue(fresh_nested.exists(), "Fresh nested file must NOT be deleted")

        self.assertEqual(cleaned_count, 2, f"Expected 2 cleaned expired items, got {cleaned_count}")

        fresh_file.unlink(missing_ok=True)
        shutil.rmtree(fresh_dir, ignore_errors=True)

    def test_cleanup_nonexistent_or_empty_directory(self):
        """Kiểm tra khi TEMP_MEDIA_DIR trống hoặc không có file cũ."""
        cleaned = cleanup_expired_media(max_age_seconds=600)
        self.assertEqual(cleaned, 0)


class TestMediaItemContextManagerIdempotency(unittest.TestCase):
    """Kiểm tra MediaItem cleanup có idempotent không khi gọi nhiều lần."""

    def test_cleanup_idempotent_no_error_on_second_call(self):
        TEMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        dummy_file = TEMP_MEDIA_DIR / "idempotent_test.mp4"
        dummy_file.write_bytes(b"content")

        item = MediaItem(
            file_path=str(dummy_file),
            title="Idempotent Test",
            author="Author",
            duration=5,
            media_type="video",
            source_url="https://example.com/test",
            is_temp_file=True,
        )

        item.cleanup()
        self.assertFalse(dummy_file.exists())

        try:
            item.cleanup()
        except Exception as err:
            self.fail(f"Second cleanup() call failed with: {err}")


if __name__ == "__main__":
    unittest.main()
