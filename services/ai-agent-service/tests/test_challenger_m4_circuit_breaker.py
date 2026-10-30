# -*- coding: utf-8 -*-
"""
Adversarial Fault Injection & Circuit Breaker Robustness Test Suite (Milestone M4 / Challenger M4.1).
Empirical validation of:
1. Fault Injection:
   - HTTP 429 Quota Exceeded consecutive failures -> trips to OPEN -> short-circuits to Tier 3.
   - Network Timeout (> 5.0s) -> no thread hang, zero unhandled exceptions, smooth Tier 3 fallback.
   - HALF_OPEN probe recovery: probe failure -> OPEN with cooldown x2; probe success -> CLOSED.
2. Latency & Overhead Benchmark:
   - Measurement of short-circuit overhead when circuit is OPEN (< 0.1ms).
3. Hostile & Malformed Payload Injections:
   - Remote returning None, empty arrays, wrong shapes, wrong channels, NaNs, non-numpy objects,
     or throwing ConnectionResetError, BrokenPipeError, MemoryError, OSError.
   - Strict 0 unhandled exceptions guarantee.
4. Bit-Exact Invariance Outside Dilated Mask (+15px):
   - Under Tier 3 Fallback, 100% bit-exact outside mask across complex textures and boundary conditions.
5. Concurrent stress and Decision Matrix integrity.
"""

from __future__ import annotations

import concurrent.futures
import logging
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

import cv2
import numpy as np

from app.services.hybrid_inpainting_coordinator import (
    CircuitState,
    HybridInpaintingCoordinator,
    RemoteCircuitBreaker,
)
from app.services.video_reconstruction_engine import VideoReconstructionEngine

# Suppress expected warning logs during hostile fault injection tests
logging.getLogger("app.services.hybrid_inpainting_coordinator").setLevel(logging.ERROR)


class TestAdversarialCircuitBreakerFSM(unittest.TestCase):
    """Kịch bản đối kháng 1 & 3: Tiêm lỗi HTTP 429, Timeout và kiểm tra FSM Circuit Breaker."""

    def setUp(self):
        self.breaker = RemoteCircuitBreaker(
            failure_threshold=3,
            base_cooldown_sec=60.0,
            max_cooldown_sec=300.0,
        )

    def test_scenario1_http_429_quota_exceeded_trips_to_open(self):
        """Giả lập lỗi HTTP 429 Quota Exceeded 3 lần liên tiếp -> OPEN, short-circuit tức thì."""
        # Lần 1: HTTP 429
        self.breaker.record_failure("HTTP 429: Too Many Requests (HuggingFace ZeroGPU quota exhausted)")
        self.assertEqual(self.breaker.state, CircuitState.CLOSED)
        self.assertEqual(self.breaker.failure_count, 1)
        self.assertTrue(self.breaker.can_attempt())

        # Lần 2: HTTP 429
        self.breaker.record_failure("HTTP 429: Rate limit exceeded")
        self.assertEqual(self.breaker.state, CircuitState.CLOSED)
        self.assertEqual(self.breaker.failure_count, 2)
        self.assertTrue(self.breaker.can_attempt())

        # Lần 3: HTTP 429 -> Circuit phải TRIPPED sang OPEN
        t_before = time.time()
        self.breaker.record_failure("HTTP 429: Daily quota depleted")
        self.assertEqual(self.breaker.state, CircuitState.OPEN)
        self.assertEqual(self.breaker.failure_count, 3)
        self.assertGreaterEqual(self.breaker.cooldown_until, t_before + 59.0)
        self.assertLessEqual(self.breaker.cooldown_until, t_before + 61.0)

        # 50 yêu cầu tiếp theo phải lập tức bị chặn (short-circuit), không gọi mạng
        for _ in range(50):
            self.assertFalse(self.breaker.can_attempt())

    def test_scenario3_half_open_probe_failure_branch_exponential_backoff(self):
        """Nhánh thăm dò HALF_OPEN thất bại -> OPEN với cooldown nhân đôi liên tiếp, clamp max 300s."""
        # Bước 1: Kích hoạt mạch sang OPEN (3 lần lỗi)
        for i in range(3):
            self.breaker.record_failure(f"Error {i+1}")
        self.assertEqual(self.breaker.state, CircuitState.OPEN)
        # Cooldown kế tiếp được tính sẵn = min(300, 60 * 2) = 120s
        self.assertEqual(self.breaker.current_cooldown, 120.0)

        # Bước 2: Giả lập thời gian trôi qua vượt cooldown_until -> chuyển HALF_OPEN
        self.breaker.cooldown_until = time.time() - 1.0
        self.assertTrue(self.breaker.can_attempt())
        self.assertEqual(self.breaker.state, CircuitState.HALF_OPEN)

        # Bước 3: Probe request thất bại (Lần thử nghiệm 1 thất bại)
        t_fail1 = time.time()
        self.breaker.record_failure("Probe 1 failed: Connection Refused")
        self.assertEqual(self.breaker.state, CircuitState.OPEN)
        self.assertEqual(self.breaker.failure_count, 4)
        # Cooldown áp dụng cho lần này là 120s, và cooldown lần sau nhân đôi lên 240s
        self.assertGreaterEqual(self.breaker.cooldown_until, t_fail1 + 119.0)
        self.assertEqual(self.breaker.current_cooldown, 240.0)

        # Bước 4: Giả lập hết cooldown 120s -> lại vào HALF_OPEN
        self.breaker.cooldown_until = time.time() - 1.0
        self.assertTrue(self.breaker.can_attempt())
        self.assertEqual(self.breaker.state, CircuitState.HALF_OPEN)

        # Bước 5: Probe request thất bại tiếp (Lần thử nghiệm 2 thất bại)
        t_fail2 = time.time()
        self.breaker.record_failure("Probe 2 failed: HTTP 503 Service Unavailable")
        self.assertEqual(self.breaker.state, CircuitState.OPEN)
        self.assertEqual(self.breaker.failure_count, 5)
        # Cooldown áp dụng là 240s, cooldown lần sau clamp trần tại 300s
        self.assertGreaterEqual(self.breaker.cooldown_until, t_fail2 + 239.0)
        self.assertEqual(self.breaker.current_cooldown, 300.0)

        # Bước 6: Giả lập hết cooldown 240s -> HALF_OPEN
        self.breaker.cooldown_until = time.time() - 1.0
        self.assertTrue(self.breaker.can_attempt())
        self.assertEqual(self.breaker.state, CircuitState.HALF_OPEN)

        # Bước 7: Probe thất bại lần 3 -> Cooldown vẫn giữ trần 300s (không tràn vô hạn)
        self.breaker.record_failure("Probe 3 failed: Timeout")
        self.assertEqual(self.breaker.state, CircuitState.OPEN)
        self.assertEqual(self.breaker.current_cooldown, 300.0)

    def test_scenario3_half_open_probe_success_branch_resets_to_closed(self):
        """Nhánh thăm dò HALF_OPEN thành công -> reset hoàn toàn về CLOSED và base cooldown 60s."""
        # Trip mạch sang OPEN
        for i in range(3):
            self.breaker.record_failure(f"Error {i+1}")
        self.assertEqual(self.breaker.state, CircuitState.OPEN)

        # Cooldown trôi qua -> HALF_OPEN
        self.breaker.cooldown_until = time.time() - 1.0
        self.assertTrue(self.breaker.can_attempt())
        self.assertEqual(self.breaker.state, CircuitState.HALF_OPEN)

        # Probe thành công!
        self.breaker.record_success()
        self.assertEqual(self.breaker.state, CircuitState.CLOSED)
        self.assertEqual(self.breaker.failure_count, 0)
        self.assertEqual(self.breaker.current_cooldown, 60.0)
        self.assertTrue(self.breaker.can_attempt())


class TestAdversarialHybridInpaintingCoordinator(unittest.TestCase):
    """Kiểm tra đối kháng tầng Hybrid Inpainting Coordinator với các loại lỗi tiêm vào."""

    def setUp(self):
        self.local_engine = VideoReconstructionEngine(
            temporal_radius=5,
            dilation_px=15,
            unrevealed_gating_threshold=0.25,
        )
        self.mock_remote_client = MagicMock()
        self.coordinator = HybridInpaintingCoordinator(
            local_engine=self.local_engine,
            remote_client=self.mock_remote_client,
            unrevealed_gating_threshold=0.25,
            min_remote_pocket_size=24,
            remote_timeout_sec=5.0,
        )

    def _create_static_scene_ring_buffer(
        self,
        num_frames: int = 11,
        w: int = 160,
        h: int = 120,
        pocket_size: int = 40,
    ) -> dict[int, tuple[np.ndarray, np.ndarray]]:
        """Tạo ring buffer cảnh tĩnh hoàn toàn với khối che phủ lớn >= 24x24 px."""
        np.random.seed(42)
        bg = np.full((h, w, 3), 110, dtype=np.uint8)
        # Thêm vân texture để kiểm tra tính bảo toàn ảnh
        cv2.circle(bg, (80, 60), 30, (200, 50, 50), -1)
        cv2.rectangle(bg, (20, 20), (140, 100), (40, 180, 40), 2)

        ring = {}
        for i in range(num_frames):
            frame = bg.copy()
            mask = np.zeros((h, w), dtype=np.uint8)
            # Khối che phủ kích thước pocket_size x pocket_size ở chính giữa
            y1 = (h - pocket_size) // 2
            x1 = (w - pocket_size) // 2
            mask[y1 : y1 + pocket_size, x1 : x1 + pocket_size] = 255
            ring[i] = (frame, mask)
        return ring

    def test_scenario1_e2e_429_quota_exceeded_trips_to_tier3_short_circuit(self):
        """E2E Test: Tiêm 3 lỗi HTTP 429 -> Circuit trips sang OPEN -> 15 frames tiếp theo 0-delay sang Tier 3."""
        ring = self._create_static_scene_ring_buffer(pocket_size=40)
        raw_mask = ring[5][1]

        # Giả lập remote client ném HTTP 429
        self.mock_remote_client.inpaint_roi_with_failover_sync.side_effect = RuntimeError(
            "HTTP 429: Too Many Requests - Rate limit exceeded on endpoint"
        )

        # 3 frames đầu tiên: Gọi remote, lỗi, ghi nhận failure
        for f_idx in range(3):
            out = self.coordinator.reconstruct_frame_streaming(
                target_idx=5,
                ring_buffer=ring,
                raw_mask=raw_mask,
                shot_boundaries=(0, 10),
            )
            self.assertIsNotNone(out)
            self.assertEqual(out.shape, (120, 160, 3))

        self.assertEqual(self.mock_remote_client.inpaint_roi_with_failover_sync.call_count, 3)
        self.assertEqual(self.coordinator.circuit_breaker.state, CircuitState.OPEN)
        self.assertEqual(self.coordinator.circuit_breaker.failure_count, 3)
        self.assertEqual(self.coordinator.stats["tier3_local_fallback_frames"], 3)
        self.assertEqual(self.coordinator.stats["remote_short_circuits"], 0)

        # 15 frames tiếp theo: Phải short-circuit 100% sang Tier 3, KHÔNG ĐƯỢC GỌI REMOTE NỮA!
        for f_idx in range(15):
            out = self.coordinator.reconstruct_frame_streaming(
                target_idx=5,
                ring_buffer=ring,
                raw_mask=raw_mask,
                shot_boundaries=(0, 10),
            )
            self.assertIsNotNone(out)
            self.assertEqual(out.shape, (120, 160, 3))

        # Số lần gọi remote vẫn giữ nguyên là 3 (0 cuộc gọi mạng mới!)
        self.assertEqual(self.mock_remote_client.inpaint_roi_with_failover_sync.call_count, 3)
        # Số lần short-circuit tăng đúng 15
        self.assertEqual(self.coordinator.stats["remote_short_circuits"], 15)
        # Toàn bộ 15 frame rơi xuống Tier 3 (tổng cộng 3 + 15 = 18)
        self.assertEqual(self.coordinator.stats["tier3_local_fallback_frames"], 18)

    def test_scenario2_network_timeout_injection_clean_fallback(self):
        """Kịch bản 2: Tiêm lỗi Timeout (> 5.0s), kiểm chứng không treo tiến trình và rơi xuống Tier 3 sạch sẽ."""
        ring = self._create_static_scene_ring_buffer(pocket_size=40)
        raw_mask = ring[5][1]

        # Giả lập timeout mạng ném TimeoutError
        self.mock_remote_client.inpaint_roi_with_failover_sync.side_effect = TimeoutError(
            "Gateway Timeout: Remote GPU worker did not respond within 5.0s"
        )

        t0 = time.perf_counter()
        out = self.coordinator.reconstruct_frame_streaming(
            target_idx=5,
            ring_buffer=ring,
            raw_mask=raw_mask,
            shot_boundaries=(0, 10),
        )
        t_elapsed = time.perf_counter() - t0

        self.assertIsNotNone(out)
        self.assertEqual(out.shape, (120, 160, 3))
        # Quá trình fallback cục bộ phải tức thì (< 0.5s trên CPU cho frame 160x120)
        self.assertLess(t_elapsed, 0.5)
        self.assertEqual(self.coordinator.stats["tier3_local_fallback_frames"], 1)
        self.assertEqual(self.coordinator.circuit_breaker.failure_count, 1)

    def test_adversarial_hostile_malformed_payloads_zero_crash(self):
        """Kiểm chứng 100% không có Unhandled Exception khi Remote trả về các payload đối kháng dị dạng."""
        ring = self._create_static_scene_ring_buffer(pocket_size=40)
        raw_mask = ring[5][1]

        hostile_responses_and_exceptions = [
            None,                                     # Trả về None
            np.array([]),                             # Mảng rỗng 0 chiều
            np.zeros((10, 10, 3), dtype=np.uint8),    # Kích thước sai lệch hoàn toàn
            np.zeros((50, 50), dtype=np.uint8),       # Thiếu kênh màu (2D thay vì 3D)
            np.full((50, 50, 3), np.nan),             # Chứa NaN
            np.full((50, 50, 3), np.inf),             # Chứa Inf
            "ERROR_MALFORMED_STRING",                 # Chuỗi ký tự thay vì ndarray
            {"status": "failed", "code": 500},        # Dict thay vì ndarray
            12345,                                    # Số nguyên
            ConnectionResetError("Peer reset connection"),
            BrokenPipeError("Broken socket pipe"),
            MemoryError("CUDA out of memory on remote worker"),
            OSError("Network unreachable"),
            RuntimeError("Unexpected remote internal crash"),
            ValueError("Invalid base64 payload"),
        ]

        for idx, hostile in enumerate(hostile_responses_and_exceptions):
            # Tạo coordinator mới cho mỗi payload để test độc lập
            coord = HybridInpaintingCoordinator(
                local_engine=self.local_engine,
                remote_client=self.mock_remote_client,
                unrevealed_gating_threshold=0.25,
                min_remote_pocket_size=24,
            )

            if isinstance(hostile, Exception):
                self.mock_remote_client.inpaint_roi_with_failover_sync.side_effect = hostile
            else:
                self.mock_remote_client.inpaint_roi_with_failover_sync.side_effect = None
                self.mock_remote_client.inpaint_roi_with_failover_sync.return_value = hostile

            try:
                out = coord.reconstruct_frame_streaming(
                    target_idx=5,
                    ring_buffer=ring,
                    raw_mask=raw_mask,
                    shot_boundaries=(0, 10),
                )
                self.assertIsNotNone(out, f"Payload #{idx} produced None output")
                self.assertEqual(out.shape, (120, 160, 3), f"Payload #{idx} altered frame shape")
                self.assertEqual(out.dtype, np.uint8, f"Payload #{idx} altered frame dtype")
                self.assertEqual(coord.stats["tier3_local_fallback_frames"], 1)
                self.assertEqual(coord.circuit_breaker.failure_count, 1)
            except Exception as e:
                self.fail(f"CRITICAL FAULT: Payload #{idx} ({hostile}) caused unhandled crash: {type(e).__name__}: {e}")

    def test_bit_exact_outside_dilated_mask_under_tier3_fallback(self):
        """Kiểm chứng 100% Bit-exact ngoài dilated mask (+15px) ngay cả khi kích hoạt Tier 3 Fallback."""
        np.random.seed(1337)
        w, h = 320, 240
        # Tạo khung hình nền có gradient phức tạp và nhiễu hạt ngẫu nhiên
        x = np.linspace(0, 1, w, dtype=np.float32)
        y = np.linspace(0, 1, h, dtype=np.float32)
        xv, yv = np.meshgrid(x, y)
        frame_base = np.zeros((h, w, 3), dtype=np.uint8)
        frame_base[:, :, 0] = np.clip((np.sin(xv * 10) * 0.5 + 0.5) * 255, 0, 255).astype(np.uint8)
        frame_base[:, :, 1] = np.clip((np.cos(yv * 10) * 0.5 + 0.5) * 255, 0, 255).astype(np.uint8)
        frame_base[:, :, 2] = np.random.randint(50, 200, (h, w), dtype=np.uint8)

        # Tạo mask với nhiều hình dạng: 1 hình chữ nhật, 1 hình tròn, và 1 khối chạm biên
        raw_mask = np.zeros((h, w), dtype=np.uint8)
        raw_mask[40:80, 50:120] = 255  # Rectangular pocket
        cv2.circle(raw_mask, (220, 150), 30, 255, -1)  # Circular pocket
        raw_mask[0:30, 0:40] = 255  # Border touching pocket (chạm góc trên cùng bên trái)

        ring = {}
        for i in range(11):
            ring[i] = (frame_base.copy(), raw_mask.copy())

        # Ép buộc rơi xuống Tier 3 bằng cách đóng circuit hoặc remote failure
        self.mock_remote_client.inpaint_roi_with_failover_sync.side_effect = TimeoutError("Force Tier 3")

        out = self.coordinator.reconstruct_frame_streaming(
            target_idx=5,
            ring_buffer=ring,
            raw_mask=raw_mask,
            shot_boundaries=(0, 10),
        )

        orig_frame = ring[5][0]

        # Xác định vùng ngoài dilated mask (+15px)
        dilated_15 = cv2.dilate(raw_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31)))
        outside_mask = (dilated_15 == 0)

        # 1. Khẳng định số pixel ngoài mask
        num_outside_pixels = np.count_nonzero(outside_mask)
        self.assertGreater(num_outside_pixels, 0)

        # 2. Sai phân tuyệt đối lớn nhất phải bằng đúng 0 (0 byte sai lệch!)
        max_diff = np.max(np.abs(out[outside_mask].astype(int) - orig_frame[outside_mask].astype(int)))
        self.assertEqual(max_diff, 0, f"Collateral damage detected: max diff = {max_diff}")

        # 3. Mảng numpy bit-identical
        np.testing.assert_array_equal(
            out[outside_mask],
            orig_frame[outside_mask],
            err_msg="Pixel mismatch outside +15px dilated mask under Tier 3 Fallback!",
        )

        # 4. Đo đạc PSNR ngoài mask: Phải đạt tuyệt đối (vô hạn hoặc > 100 dB)
        mse_outside = np.mean((out[outside_mask].astype(float) - orig_frame[outside_mask].astype(float)) ** 2)
        self.assertEqual(mse_outside, 0.0)

    def test_open_circuit_short_circuit_overhead_benchmark(self):
        """Đo đạc độ trễ overhead khi mạch OPEN: Kiểm chứng thời gian chuyển nhánh < 0.1ms."""
        ring = self._create_static_scene_ring_buffer(pocket_size=40)
        unrevealed_mask = ring[5][1]

        # Đưa mạch vào trạng thái OPEN
        for _ in range(3):
            self.coordinator.circuit_breaker.record_failure("Error")
        self.assertEqual(self.coordinator.circuit_breaker.state, CircuitState.OPEN)

        # Đo đạc 10,000 lần gọi can_attempt()
        iterations = 10000
        latencies_ns = []

        for _ in range(iterations):
            t0 = time.perf_counter_ns()
            allowed = self.coordinator.circuit_breaker.can_attempt()
            t1 = time.perf_counter_ns()
            latencies_ns.append(t1 - t0)
            self.assertFalse(allowed)

        latencies_ms = np.array(latencies_ns) / 1_000_000.0
        mean_ms = float(np.mean(latencies_ms))
        median_ms = float(np.median(latencies_ms))
        p99_ms = float(np.percentile(latencies_ms, 99))
        max_ms = float(np.max(latencies_ms))

        print(
            f"\n[BENCHMARK] Circuit Breaker OPEN Overhead (10,000 iterations): "
            f"Mean={mean_ms:.6f}ms, Median={median_ms:.6f}ms, P99={p99_ms:.6f}ms, Max={max_ms:.6f}ms"
        )

        # Kiểm chứng tiêu chí < 0.1ms
        self.assertLess(
            median_ms, 0.1,
            f"Circuit Breaker OPEN median overhead {median_ms:.6f}ms exceeds 0.1ms SLA!"
        )
        self.assertLess(
            mean_ms, 0.1,
            f"Circuit Breaker OPEN mean overhead {mean_ms:.6f}ms exceeds 0.1ms SLA!"
        )

        # Đồng thời đo hàm điều phối _should_delegate_to_remote khi OPEN
        coord_latencies_ns = []
        for _ in range(iterations):
            t0 = time.perf_counter_ns()
            should = self.coordinator._should_delegate_to_remote(unrevealed_mask, 0.5)
            t1 = time.perf_counter_ns()
            coord_latencies_ns.append(t1 - t0)
            self.assertFalse(should)

        coord_latencies_ms = np.array(coord_latencies_ns) / 1_000_000.0
        coord_mean_ms = float(np.mean(coord_latencies_ms))
        coord_median_ms = float(np.median(coord_latencies_ms))

        print(
            f"[BENCHMARK] _should_delegate_to_remote OPEN Overhead: "
            f"Mean={coord_mean_ms:.6f}ms, Median={coord_median_ms:.6f}ms"
        )
        self.assertLess(
            coord_median_ms, 0.1,
            f"_should_delegate_to_remote median overhead {coord_median_ms:.6f}ms exceeds 0.1ms SLA!"
        )

    def test_concurrent_circuit_breaker_stress(self):
        """Stress test: 50 luồng đồng thời gọi can_attempt(), record_failure(), record_success()."""
        breaker = RemoteCircuitBreaker(failure_threshold=3, base_cooldown_sec=0.1, max_cooldown_sec=1.0)
        num_threads = 50
        num_ops_per_thread = 200

        def worker_task(tid: int):
            for op in range(num_ops_per_thread):
                action = (tid + op) % 3
                if action == 0:
                    breaker.can_attempt()
                elif action == 1:
                    breaker.record_failure(f"Thread {tid} error")
                else:
                    breaker.record_success()

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker_task, i) for i in range(num_threads)]
            for fut in concurrent.futures.as_completed(futures):
                fut.result()

        # Kiểm chứng sau stress test: máy trạng thái vẫn ở trong các trạng thái hợp lệ
        self.assertIn(breaker.state, [CircuitState.CLOSED, CircuitState.OPEN, CircuitState.HALF_OPEN])
        self.assertGreaterEqual(breaker.failure_count, 0)
        self.assertGreaterEqual(breaker.current_cooldown, 0.1)


class TestDecisionMatrixAndPocketsAdversarial(unittest.TestCase):
    """Kiểm tra đối kháng Ma trận Quyết định (Decision Matrix) và Ngưỡng 24x24 px."""

    def setUp(self):
        self.local_engine = VideoReconstructionEngine(
            temporal_radius=5,
            dilation_px=15,
            unrevealed_gating_threshold=0.25,
        )
        self.mock_remote_client = MagicMock()
        self.coordinator = HybridInpaintingCoordinator(
            local_engine=self.local_engine,
            remote_client=self.mock_remote_client,
            unrevealed_gating_threshold=0.25,
            min_remote_pocket_size=24,
            remote_timeout_sec=5.0,
        )

    def test_p0_zero_mask_guarantees_bit_exact_copy(self):
        """P0: Khi mask không có pixel nào (count_nonzero == 0), trả về frame gốc 100% bit-exact."""
        frame = np.random.randint(0, 255, (120, 160, 3), dtype=np.uint8)
        ring = {0: (frame, np.zeros((120, 160), dtype=np.uint8))}

        out = self.coordinator.reconstruct_frame_streaming(
            target_idx=0,
            ring_buffer=ring,
            raw_mask=np.zeros((120, 160), dtype=np.uint8),
            shot_boundaries=(0, 0),
        )
        np.testing.assert_array_equal(out, frame)
        self.mock_remote_client.inpaint_roi_with_failover_sync.assert_not_called()

    def test_p1_scene_text_protection_overlay_mode(self):
        """P1: Chữ trong cảnh (scene_text_mask) được loại bỏ khỏi mask can thiệp trong mode overlay."""
        frame = np.full((120, 160, 3), 100, dtype=np.uint8)
        raw_mask = np.zeros((120, 160), dtype=np.uint8)
        raw_mask[30:70, 30:70] = 255  # Text detector báo cả vùng này

        # Nhưng toàn bộ vùng này được xác định là Scene Text (chữ cảnh)
        scene_text_mask = raw_mask.copy()
        ring = {0: (frame, raw_mask)}

        out = self.coordinator.reconstruct_frame_streaming(
            target_idx=0,
            ring_buffer=ring,
            raw_mask=raw_mask,
            shot_boundaries=(0, 0),
            target_scope="overlay",
            scene_text_mask=scene_text_mask,
        )
        # Vì effective_mask bị trừ triệt để -> 0 pixel -> trả về frame gốc bit-exact
        np.testing.assert_array_equal(out, frame)
        self.mock_remote_client.inpaint_roi_with_failover_sync.assert_not_called()

    def test_p3_pocket_size_boundary_conditions(self):
        """P3 vs P4: Kiểm chứng ngưỡng kích thước túi unrevealed 24x24 px."""
        h, w = 120, 160
        # Trường hợp 1: Túi kích thước 23x23 px (< 24) -> P3: KHÔNG ĐƯỢC gọi Remote GPU
        mask_23 = np.zeros((h, w), dtype=np.uint8)
        mask_23[40:63, 40:63] = 255  # 23x23 px
        self.assertFalse(self.coordinator._should_delegate_to_remote(mask_23, unrevealed_ratio=0.5))

        # Trường hợp 2: Túi kích thước 23x50 px (một chiều < 24) -> KHÔNG ĐƯỢC gọi Remote GPU
        mask_uneven = np.zeros((h, w), dtype=np.uint8)
        mask_uneven[40:63, 40:90] = 255  # 23x50 px (max_h = 23 < 24)
        # Theo code: max_w >= 24 and max_h >= 24
        self.assertFalse(self.coordinator._should_delegate_to_remote(mask_uneven, unrevealed_ratio=0.5))

        # Trường hợp 3: Túi kích thước 24x24 px (chính xác ngưỡng) -> P4: ĐƯỢC PHÉP gọi Remote GPU
        mask_24 = np.zeros((h, w), dtype=np.uint8)
        mask_24[40:64, 40:64] = 255  # 24x24 px
        self.assertTrue(self.coordinator._should_delegate_to_remote(mask_24, unrevealed_ratio=0.5))

        # Trường hợp 4: Túi kích thước 50x50 px (> 24) -> P4: ĐƯỢC PHÉP gọi Remote GPU
        mask_50 = np.zeros((h, w), dtype=np.uint8)
        mask_50[30:80, 30:80] = 255  # 50x50 px
        self.assertTrue(self.coordinator._should_delegate_to_remote(mask_50, unrevealed_ratio=0.5))

    def test_streaming_500_frames_stability_and_memory_sanity(self):
        """Kiểm chứng độ ổn định và tài nguyên khi xử lý streaming 500 frames liên tục."""
        ring = {}
        for i in range(11):
            frame = np.full((60, 80, 3), 128, dtype=np.uint8)
            mask = np.zeros((60, 80), dtype=np.uint8)
            mask[20:45, 25:50] = 255
            ring[i] = (frame, mask)

        # Giả lập remote thành công
        self.mock_remote_client.inpaint_roi_with_failover_sync.side_effect = lambda img, m, timeout_sec=5.0: img.copy()

        for f_idx in range(500):
            out = self.coordinator.reconstruct_frame_streaming(
                target_idx=5,
                ring_buffer=ring,
                raw_mask=ring[5][1],
                shot_boundaries=(0, 10),
            )
            self.assertIsNotNone(out)

        # Đảm bảo hoàn thành 500 frame mà không có crash, stats tăng lũy kế chính xác
        self.assertEqual(self.coordinator.stats["tier2_remote_gpu_frames"], 500)
        self.assertEqual(self.coordinator.circuit_breaker.state, CircuitState.CLOSED)



if __name__ == "__main__":
    unittest.main()
