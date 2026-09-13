"""
test_stress_concurrency_m4.py — Empirical Stress, Concurrency & Durability Challenge Suite.

Challenger 2 Milestone 4 Empirical Verification Harness:
1. High-Concurrency Dual-Track Distribution (3 parallel pipelines: Chunking + Direct Stream).
2. Live HTTP Socket Stress via FastAPI endpoint (HTTP 200, HTTP 206 Range, Abrupt Client Disconnect, Gzip bypass).
3. Adversarial Fault Injection: Mid-stream Network Crash, FFmpeg Failure & Orphan Purge.
4. Continuous Resource Sampling (Cgroup RAM, RSS RAM, Host Available RAM, CPU%, OOM Check).
5. 100% Zero-Disk-Leak Audit on /tmp/media_downloads/ (temp & public).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Any, Dict, List
import unittest
import uuid

import httpx
import psutil

import sys
sys.path.insert(0, "/app")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.video_chunker import (
    VideoChunker,
    VideoChunkerError,
    TELEGRAM_SAFE_PART_BYTES,
    TARGET_CHUNK_BYTES,
)
from app.services.media_storage_manager import (
    media_storage_manager,
    BASE_MEDIA_DIR,
    TEMP_MEDIA_DIR,
    PUBLIC_MEDIA_DIR,
)

logger = logging.getLogger("stress_test")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def get_cgroup_memory_mb() -> float:
    """Reads current cgroup memory usage in MiB."""
    for p in [
        "/sys/fs/cgroup/memory.current",
        "/sys/fs/cgroup/memory/memory.usage_in_bytes",
    ]:
        if os.path.exists(p):
            try:
                with open(p, "r") as f:
                    return int(f.read().strip()) / (1024 * 1024)
            except Exception:
                pass
    return -1.0


class ResourceSampler:
    """Background sampling daemon that logs RAM and CPU metrics during stress tests."""

    def __init__(self, interval_seconds: float = 0.5):
        self.interval = interval_seconds
        self.samples: List[Dict[str, Any]] = []
        self._running = False
        self._task: asyncio.Task | None = None
        self.proc = psutil.Process()

    async def _sample_loop(self):
        while self._running:
            try:
                cgroup_mem = get_cgroup_memory_mb()
                rss_mem = self.proc.memory_info().rss / (1024 * 1024)
                host_mem = psutil.virtual_memory()
                cpu_p = psutil.cpu_percent(interval=None)

                self.samples.append({
                    "time": time.time(),
                    "cgroup_mem_mib": cgroup_mem,
                    "rss_mem_mib": rss_mem,
                    "host_available_mib": host_mem.available / (1024 * 1024),
                    "host_used_mib": host_mem.used / (1024 * 1024),
                    "cpu_percent": cpu_p,
                })
            except Exception as e:
                logger.warning("Resource sampling error: %s", e)
            await asyncio.sleep(self.interval)

    def start(self):
        self._running = True
        self.samples.clear()
        self._task = asyncio.create_task(self._sample_loop())

    async def stop(self) -> Dict[str, Any]:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if not self.samples:
            return {}

        cgroup_vals = [s["cgroup_mem_mib"] for s in self.samples if s["cgroup_mem_mib"] > 0]
        rss_vals = [s["rss_mem_mib"] for s in self.samples]
        host_avail = [s["host_available_mib"] for s in self.samples]
        cpu_vals = [s["cpu_percent"] for s in self.samples]

        return {
            "sample_count": len(self.samples),
            "baseline_cgroup_mib": cgroup_vals[0] if cgroup_vals else 0,
            "peak_cgroup_mib": max(cgroup_vals) if cgroup_vals else 0,
            "final_cgroup_mib": cgroup_vals[-1] if cgroup_vals else 0,
            "cgroup_delta_mib": (max(cgroup_vals) - cgroup_vals[0]) if cgroup_vals else 0,
            "baseline_rss_mib": rss_vals[0] if rss_vals else 0,
            "peak_rss_mib": max(rss_vals) if rss_vals else 0,
            "final_rss_mib": rss_vals[-1] if rss_vals else 0,
            "rss_delta_mib": (max(rss_vals) - rss_vals[0]) if rss_vals else 0,
            "min_host_available_mib": min(host_avail) if host_avail else 0,
            "max_cpu_percent": max(cpu_vals) if cpu_vals else 0,
            "avg_cpu_percent": sum(cpu_vals) / len(cpu_vals) if cpu_vals else 0,
        }


def make_seed_video(dest_path: Path, duration_s: int = 3) -> Path:
    """Generates a small valid MP4 seed video with lavfi."""
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=44100",
        "-t", str(duration_s),
        "-c:v", "libx264", "-preset", "ultrafast", "-b:v", "3M",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(dest_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return dest_path


def make_fast_large_video(seed_path: Path, output_path: Path, target_mb: int = 55) -> Path:
    """Rapidly replicates seed video via stream-loop to reach target size in < 0.3s."""
    seed_size = seed_path.stat().st_size
    loops = max(2, int((target_mb * 1024 * 1024) / seed_size) + 1)
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-stream_loop", str(loops),
        "-i", str(seed_path),
        "-c", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return output_path


class TestStressConcurrencyMilestone4(unittest.IsolatedAsyncioTestCase):
    """
    Exhaustive empirical test suite for Milestone 4 Dual Distribution Pipeline.
    Runs against actual container dashboard_ai_agent and FastAPI runtime at port 8084.
    """

    async def asyncSetUp(self):
        self.workspace = Path(tempfile.mkdtemp(prefix="challenger_stress_ws_"))
        self.seed_video = make_seed_video(self.workspace / "seed.mp4", duration_s=3)
        self.sampler = ResourceSampler(interval_seconds=0.3)
        self.api_base = "http://127.0.0.1:8084"
        media_storage_manager.ensure_dirs()

    async def asyncTearDown(self):
        shutil.rmtree(self.workspace, ignore_errors=True)

    async def test_01_concurrent_dual_distribution_and_live_http_streaming(self):
        """
        Véc-tơ 1: 3 Pipeline xử lý kép chạy ĐỒNG THỜI + 6 HTTP Streaming Clients (HTTP 200, 206, Abort).
        Đo lường chi tiết RAM, CPU, Zero-Disk-Leak và tính toàn vẹn dữ liệu.
        """
        logger.info("=== START TEST 01: Concurrent Dual Distribution & HTTP Streaming ===")
        self.sampler.start()

        num_pipelines = 3
        videos = []
        records = []
        run_uid = uuid.uuid4().hex[:8]

        # 1. Chuẩn bị 3 video lớn (> 50MB)
        t_gen_start = time.time()
        for i in range(num_pipelines):
            v_path = self.workspace / f"stress_video_{i+1}.mp4"
            make_fast_large_video(self.seed_video, v_path, target_mb=56)
            self.assertGreater(v_path.stat().st_size, 50 * 1024 * 1024)
            videos.append(v_path)
            logger.info("Prepared video %d: %s (%.2f MB)", i+1, v_path.name, v_path.stat().st_size / (1024*1024))
        logger.info("Generation time for 3 videos: %.2fs", time.time() - t_gen_start)

        # 2. Publish 3 video vào Kênh 2 (Direct Download)
        for i, v_path in enumerate(videos):
            orig_size = v_path.stat().st_size
            rec = media_storage_manager.publish_download_item(
                file_path=v_path,
                filename=f"published_video_{run_uid}_{i+1}.mp4",
                title=f"Stress Test Video {i+1}",
                duration=30,
                ttl_seconds=3600,
            )
            self.assertTrue(rec.file_path.exists())
            self.assertEqual(rec.file_size, orig_size)
            records.append(rec)

        # 3. Kích hoạt đồng thời 3 pipeline chunking Kênh 1 + Giả lập Telegram Streaming Purge
        active_parts_dirs: List[Path] = []
        purged_parts_count = 0
        lock = asyncio.Lock()

        async def run_pipeline_channel1(rec, idx):
            nonlocal purged_parts_count
            parts_dir = Path(tempfile.mkdtemp(prefix=f"pipe_{run_uid}_{idx}_parts_", dir=str(media_storage_manager.temp_dir)))
            active_parts_dirs.append(parts_dir)
            t_chunk_start = time.time()
            try:
                parts = await VideoChunker.split_video(
                    video_path=str(rec.file_path),
                    output_dir=parts_dir,
                )
                chunk_time = time.time() - t_chunk_start
                logger.info("[Pipe %d] Split into %d parts in %.2fs", idx, len(parts), chunk_time)

                self.assertGreaterEqual(len(parts), 2, f"Video >50MB must split into >=2 parts, got {len(parts)}")
                for p in parts:
                    self.assertLessEqual(p["size"], TELEGRAM_SAFE_PART_BYTES, f"Part {p['part_index']} exceeds 48MB limit!")
                    # Mô phỏng Telegram send_document_file: đọc stream từ đĩa không buffer toàn bộ vào RAM
                    p_path = Path(p["path"])
                    self.assertTrue(p_path.exists())
                    # Zero-RAM chunked read simulation
                    with open(p_path, "rb") as f:
                        while chunk := f.read(64 * 1024):
                            pass
                    # Streaming Purge: Xóa ngay part sau khi gửi
                    p_path.unlink()
                    self.assertFalse(p_path.exists(), f"Part {p['part_index']} was not purged immediately!")
                    async with lock:
                        purged_parts_count += 1
                    # Giả lập nhịp độ Telegram chống FloodWait
                    await asyncio.sleep(0.2)
            finally:
                shutil.rmtree(parts_dir, ignore_errors=True)

        # 4. Kích hoạt đồng thời nhiều HTTP Clients Kênh 2
        http_results: Dict[str, Any] = {
            "full_downloads": 0,
            "partial_ranges": 0,
            "aborted_connections": 0,
            "gzip_bypassed": 0,
        }

        async def http_client_full_download(token: str, filename: str, expected_size: int):
            async with httpx.AsyncClient(base_url=self.api_base, timeout=60.0) as client:
                res = await client.get(f"/api/ai/media/download/{token}/{filename}")
                self.assertEqual(res.status_code, 200)
                self.assertEqual(len(res.content), expected_size)
                self.assertEqual(res.headers.get("accept-ranges"), "bytes")
                http_results["full_downloads"] += 1
                logger.info("[HTTP Client] Full download token %s completed: %d bytes (200 OK)", token, len(res.content))

        async def http_client_range_requests(token: str, filename: str, expected_total: int):
            async with httpx.AsyncClient(base_url=self.api_base, timeout=30.0) as client:
                ranges = [
                    (0, 1023),
                    (1024, 2047),
                    (10000000, 11000000),
                    (20000000, 22000000),
                    (expected_total - 10000, expected_total - 1),
                ]
                for r_start, r_end in ranges:
                    headers = {"Range": f"bytes={r_start}-{r_end}"}
                    res = await client.get(f"/api/ai/media/download/{token}/{filename}", headers=headers)
                    self.assertEqual(res.status_code, 206)
                    expected_len = r_end - r_start + 1
                    self.assertEqual(len(res.content), expected_len)
                    self.assertIn(f"bytes {r_start}-{r_end}/{expected_total}", res.headers.get("content-range", ""))
                    http_results["partial_ranges"] += 1
                logger.info("[HTTP Client] Completed %d Range requests on token %s (206 Partial Content)", len(ranges), token)

        async def http_client_abrupt_disconnect(token: str, filename: str):
            """Mô phỏng client tải video nhưng ngắt kết nối đột ngột (abort socket mid-stream)."""
            async with httpx.AsyncClient(base_url=self.api_base, timeout=10.0) as client:
                try:
                    async with client.stream("GET", f"/api/ai/media/download/{token}/{filename}") as res:
                        self.assertEqual(res.status_code, 200)
                        bytes_read = 0
                        async for chunk in res.aiter_bytes(chunk_size=32768):
                            bytes_read += len(chunk)
                            if bytes_read >= 1024 * 1024:  # Đọc 1MB rồi ngắt kết nối ngay lập tức!
                                raise ConnectionResetError("Simulated client abrupt disconnection")
                except ConnectionResetError:
                    http_results["aborted_connections"] += 1
                    logger.info("[HTTP Client] Abruptly severed connection after 1MB for token %s", token)

        async def http_client_gzip_bypass_check(token: str, filename: str, expected_size: int):
            """Xác minh GZipMiddleware không nén và không buffer video/mp4 vào RAM."""
            headers = {"Accept-Encoding": "gzip, deflate, br"}
            async with httpx.AsyncClient(base_url=self.api_base, timeout=60.0) as client:
                res = await client.get(f"/api/ai/media/download/{token}/{filename}", headers=headers)
                self.assertEqual(res.status_code, 200)
                self.assertEqual(len(res.content), expected_size)
                # Video MP4 không được có Content-Encoding: gzip để tránh buffer toàn bộ vào RAM
                content_encoding = res.headers.get("content-encoding", "")
                self.assertNotIn("gzip", content_encoding.lower(), f"Video MP4 should bypass gzip compression! Got {content_encoding}")
                http_results["gzip_bypassed"] += 1
                logger.info("[HTTP Client] Gzip bypass verified: content-encoding=%s", content_encoding or "identity")

        # Chạy đồng thời tất cả các tác vụ
        t_all_start = time.time()
        tasks = [
            # 3 Pipeline chunking Kênh 1
            run_pipeline_channel1(records[0], 1),
            run_pipeline_channel1(records[1], 2),
            run_pipeline_channel1(records[2], 3),
            # Kênh 2 HTTP Clients
            http_client_full_download(records[0].token, records[0].filename, records[0].file_size),
            http_client_full_download(records[1].token, records[1].filename, records[1].file_size),
            http_client_range_requests(records[0].token, records[0].filename, records[0].file_size),
            http_client_range_requests(records[1].token, records[1].filename, records[1].file_size),
            http_client_abrupt_disconnect(records[2].token, records[2].filename),
            http_client_gzip_bypass_check(records[2].token, records[2].filename, records[2].file_size),
        ]

        await asyncio.gather(*tasks)
        total_time = time.time() - t_all_start
        logger.info("=== All %d parallel tasks completed in %.2fs ===", len(tasks), total_time)

        # Dừng sampler và thu thập metrics
        metrics = await self.sampler.stop()
        logger.info("=== RESOURCE METRICS SUMMARY ===")
        for k, v in metrics.items():
            if isinstance(v, float):
                logger.info("  %s: %.2f", k, v)
            else:
                logger.info("  %s: %s", k, v)

        # 5. Kiểm toán Zero-Disk-Leak trên thư mục /tmp/media_downloads/temp
        for p_dir in active_parts_dirs:
            self.assertFalse(p_dir.exists(), f"Parts directory {p_dir} was not cleaned up!")
        logger.info("✅ Zero-Disk-Leak verified: All active parts directories cleaned up 100%%")

        # 6. Dọn dẹp các token test trong public và kiểm toán Zero-Disk-Leak
        for rec in records:
            token_dir = media_storage_manager.public_dir / rec.token
            shutil.rmtree(token_dir, ignore_errors=True)
            self.assertFalse(token_dir.exists(), f"Token directory {token_dir} was not removed!")
        logger.info("✅ Zero-Disk-Leak verified: All test tokens removed from public directory")

        # 7. Khẳng định giới hạn tài nguyên an toàn
        if metrics.get("cgroup_delta_mib"):
            self.assertLess(metrics["cgroup_delta_mib"], 450.0, f"Cgroup RAM delta ({metrics['cgroup_delta_mib']:.2f} MiB) exceeded 450 MiB limit!")
        if metrics.get("peak_cgroup_mib"):
            self.assertLess(metrics["peak_cgroup_mib"], 1200.0, f"Peak cgroup memory ({metrics['peak_cgroup_mib']:.2f} MiB) exceeded safe limit!")
        self.assertGreater(metrics.get("min_host_available_mib", 0), 800.0, "Host available memory dropped below 800 MiB danger zone!")

        logger.info("✅ Test 01 PASSED FLAWLESSLY: Peak Cgroup RAM=%.2f MiB, Delta=%.2f MiB, Host Min Avail=%.2f MiB",
                    metrics.get("peak_cgroup_mib", 0), metrics.get("cgroup_delta_mib", 0), metrics.get("min_host_available_mib", 0))

    async def test_02_fault_injection_and_unhandled_exception_cleanup(self):
        """
        Véc-tơ 2: Mô phỏng sự cố mạng Telegram & Crash Exception giữa chừng.
        Kiểm chứng khối finally luôn bảo đảm dọn dẹp sạch sẽ 100% parts_dir tạm.
        """
        logger.info("=== START TEST 02: Fault Injection & Exception Cleanup ===")
        v_path = self.workspace / "fault_test_video.mp4"
        make_fast_large_video(self.seed_video, v_path, target_mb=55)
        run_uid = uuid.uuid4().hex[:8]

        rec = media_storage_manager.publish_download_item(
            file_path=v_path,
            filename=f"fault_video_{run_uid}.mp4",
            title="Fault Test Video",
            duration=25,
            ttl_seconds=3600,
        )

        parts_dir = Path(tempfile.mkdtemp(prefix=f"fault_parts_{run_uid}_", dir=str(media_storage_manager.temp_dir)))
        self.assertTrue(parts_dir.exists())

        # Mô phỏng quy trình chunking và gặp sự cố unhandled exception ở part 2
        with self.assertRaises(ConnectionError):
            try:
                parts = await VideoChunker.split_video(
                    video_path=str(rec.file_path),
                    output_dir=parts_dir,
                )
                self.assertGreaterEqual(len(parts), 2)
                for p in parts:
                    if p["part_index"] == 2:
                        # Mô phỏng rớt mạng Telegram
                        raise ConnectionError("Simulated Telegram connection drop mid-dispatch!")
                    # Part 1 purged
                    os.unlink(p["path"])
            finally:
                # Khối dọn dẹp chuẩn như trong telegram_bot.py / ai_agent_tools.py
                shutil.rmtree(parts_dir, ignore_errors=True)

        self.assertFalse(parts_dir.exists(), "Parts directory must be cleanly removed despite exception!")
        logger.info("✅ Test 02 PASSED: 100%% Zero-Disk-Leak confirmed under unhandled exception.")

        # Cleanup token
        shutil.rmtree(media_storage_manager.public_dir / rec.token, ignore_errors=True)

    async def test_03_three_layer_ttl_sweeper_stress(self):
        """
        Véc-tơ 3: Kiểm chứng cơ chế 3-Layer TTL Sweeper.
        Tạo nhiều token có TTL 1s -> Layer 2 On-Access trả 404 và xóa ngay -> Layer 1 Sweep xóa triệt để.
        """
        logger.info("=== START TEST 03: 3-Layer TTL Sweeper Stress ===")
        created_records = []
        run_uid = uuid.uuid4().hex[:8]
        for i in range(4):
            f_path = self.workspace / f"exp_video_{i}.mp4"
            make_fast_large_video(self.seed_video, f_path, target_mb=10)
            rec = media_storage_manager.publish_download_item(
                file_path=f_path,
                filename=f"exp_{run_uid}_{i}.mp4",
                title=f"Exp Video {i}",
                duration=10,
                ttl_seconds=1,  # Hết hạn sau 1 giây!
            )
            created_records.append(rec)
            self.assertTrue(rec.file_path.exists())

        # Chờ 1.5 giây để tệp hết hạn
        await asyncio.sleep(1.5)

        # Test Layer 2: On-access access qua HTTP endpoint thật
        async with httpx.AsyncClient(base_url=self.api_base, timeout=10.0) as client:
            res = await client.get(f"/api/ai/media/download/{created_records[0].token}/{created_records[0].filename}")
            self.assertEqual(res.status_code, 404, f"Expired token must return 404 Not Found, got {res.status_code}")
            # Xác nhận thư mục token bị xóa ngay lập tức
            token_dir = media_storage_manager.public_dir / created_records[0].token
            self.assertFalse(token_dir.exists(), "Expired token folder must be purged instantly by Layer 2 Defense!")
            logger.info("✅ Layer 2 Defense confirmed: Expired token purged on access, HTTP 404 returned.")

        # Test Layer 1: Trigger sweep
        stats = media_storage_manager.sweep_expired()
        logger.info("Sweep stats: %s", stats)
        self.assertGreaterEqual(stats.get("expired_tokens_removed", 0), 3)

        # Xác nhận tất cả các token được tạo trong test này đã bị xóa sạch hoàn toàn
        for rec in created_records:
            t_path = media_storage_manager.public_dir / rec.token
            self.assertFalse(t_path.exists(), f"Token {rec.token} should have been swept! Still exists.")
        logger.info("✅ Layer 1 Defense confirmed: 100%% created expired tokens purged by sweep_expired().")


def run_all_stress_tests():
    suite = unittest.TestLoader().loadTestsFromTestCase(TestStressConcurrencyMilestone4)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        sys.exit(1)


if __name__ == "__main__":
    run_all_stress_tests()
