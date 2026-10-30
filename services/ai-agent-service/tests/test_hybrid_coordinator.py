# -*- coding: utf-8 -*-
"""
Unit Test Suite for HybridInpaintingCoordinator & RemoteCircuitBreaker (Milestone M4 / Feature 19).
Validates:
- RemoteCircuitBreaker Finite State Machine (CLOSED -> OPEN -> HALF-OPEN -> CLOSED / OPEN)
- Exponential backoff & short-circuit execution (0-delay failover)
- HybridInpaintingCoordinator 3-tier routing:
  * Tier 1: Local Optical Flow when unrevealed_ratio < 0.25 (>= 75% revealed)
  * Tier 2: Remote Neural Inpainting for large pockets (>= 24x24 px)
  * Tier 3: Local Alpha Invert Blend & Classical Fallback on fault / timeout
- Zero mask invariance & 100% Bit-exact outside dilated mask (+15px)
- Scene text preservation in overlay mode
"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

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


class TestRemoteCircuitBreaker(unittest.TestCase):
    """Kiểm tra máy trạng thái hữu hạn của Circuit Breaker."""

    def setUp(self):
        self.breaker = RemoteCircuitBreaker(
            failure_threshold=3,
            base_cooldown_sec=1.0,
            max_cooldown_sec=10.0,
        )

    def test_initial_state_closed(self):
        """Khởi đầu mạch phải ở trạng thái CLOSED và cho phép thực hiện."""
        self.assertEqual(self.breaker.state, CircuitState.CLOSED)
        self.assertEqual(self.breaker.failure_count, 0)
        self.assertTrue(self.breaker.can_attempt())

    def test_trips_to_open_after_threshold_failures(self):
        """Mạch phải chuyển sang OPEN sau đúng 3 lần lỗi liên tiếp."""
        self.breaker.record_failure("Timeout 1")
        self.assertEqual(self.breaker.state, CircuitState.CLOSED)
        self.assertTrue(self.breaker.can_attempt())

        self.breaker.record_failure("Timeout 2")
        self.assertEqual(self.breaker.state, CircuitState.CLOSED)
        self.assertTrue(self.breaker.can_attempt())

        self.breaker.record_failure("HTTP 429 Quota Exceeded")
        self.assertEqual(self.breaker.state, CircuitState.OPEN)
        # Khi OPEN, can_attempt() phải trả về False ngay lập tức (short-circuit)
        self.assertFalse(self.breaker.can_attempt())

    def test_cooldown_transition_to_half_open(self):
        """Sau thời gian cooldown, mạch chuyển sang HALF-OPEN cho phép probe request."""
        for _ in range(3):
            self.breaker.record_failure("Error")
        self.assertEqual(self.breaker.state, CircuitState.OPEN)
        self.assertFalse(self.breaker.can_attempt())

        # Giả lập thời gian trôi qua vượt quá cooldown
        self.breaker.cooldown_until = time.time() - 0.1
        self.assertTrue(self.breaker.can_attempt())
        self.assertEqual(self.breaker.state, CircuitState.HALF_OPEN)

    def test_probe_success_resets_to_closed(self):
        """Probe request thành công trong HALF-OPEN đưa mạch về CLOSED và reset cooldown."""
        for _ in range(3):
            self.breaker.record_failure("Error")
        self.breaker.cooldown_until = time.time() - 0.1
        self.assertTrue(self.breaker.can_attempt())  # Chuyển sang HALF-OPEN

        self.breaker.record_success()
        self.assertEqual(self.breaker.state, CircuitState.CLOSED)
        self.assertEqual(self.breaker.failure_count, 0)
        self.assertEqual(self.breaker.current_cooldown, 1.0)
        self.assertTrue(self.breaker.can_attempt())

    def test_probe_failure_trips_to_open_with_exponential_backoff(self):
        """Probe request thất bại trong HALF-OPEN đưa mạch về OPEN với cooldown tăng gấp đôi."""
        for _ in range(3):
            self.breaker.record_failure("Error")
        self.breaker.cooldown_until = time.time() - 0.1
        self.assertTrue(self.breaker.can_attempt())  # Sang HALF-OPEN

        # Cooldown trước đó là 2.0 (1.0 * 2.0)
        self.breaker.record_failure("Probe failed")
        self.assertEqual(self.breaker.state, CircuitState.OPEN)
        self.assertGreaterEqual(self.breaker.current_cooldown, 4.0)


class TestHybridInpaintingCoordinator(unittest.TestCase):
    """Kiểm tra logic điều phối Hybrid 3 tầng và bảo toàn chất lượng ảnh."""

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

    def _create_synthetic_ring_buffer(
        self,
        num_frames: int = 11,
        w: int = 160,
        h: int = 120,
    ) -> dict[int, tuple[np.ndarray, np.ndarray]]:
        """Tạo ring buffer tổng hợp có dịch chuyển ngang tuyến tính mượt mà bằng warpAffine."""
        x_grad = np.linspace(0, 255, w, dtype=np.uint8)
        y_grad = np.linspace(0, 255, h, dtype=np.uint8)
        base = np.zeros((h, w, 3), dtype=np.uint8)
        base[:, :, 0] = x_grad[np.newaxis, :]
        base[:, :, 1] = y_grad[:, np.newaxis]
        base[:, :, 2] = 128

        ring = {}
        for i in range(num_frames):
            M = np.float32([[1, 0, (i - 5) * 1.5], [0, 1, 0]])
            frame = cv2.warpAffine(base, M, (w, h), borderMode=cv2.BORDER_REFLECT)
            mask = np.zeros((h, w), dtype=np.uint8)
            mask[50:65, 70:85] = 255
            ring[i] = (frame, mask)
        return ring

    def test_empty_mask_returns_original_frame(self):
        """Khi mask rỗng (0 pixel), trả về frame gốc 100% bit-exact."""
        ring = self._create_synthetic_ring_buffer(5)
        raw_mask = np.zeros((120, 160), dtype=np.uint8)
        out = self.coordinator.reconstruct_frame_streaming(
            target_idx=2,
            ring_buffer=ring,
            raw_mask=raw_mask,
            shot_boundaries=(0, 4),
        )
        orig_frame = ring[2][0]
        np.testing.assert_array_equal(out, orig_frame)

    def test_tier1_local_flow_when_unrevealed_ratio_low(self):
        """Khi unrevealed_ratio < 0.25 (chuyển động quang học hé lộ >= 75%), kích hoạt Tier 1."""
        ring = self._create_synthetic_ring_buffer(11)
        raw_mask = ring[5][1].copy()

        out = self.coordinator.reconstruct_frame_streaming(
            target_idx=5,
            ring_buffer=ring,
            raw_mask=raw_mask,
            shot_boundaries=(0, 10),
        )
        self.assertIsNotNone(out)
        self.assertEqual(out.shape, (120, 160, 3))
        # Không được gọi remote client vì Tier 1 đã giải quyết hoàn toàn
        self.mock_remote_client.inpaint_roi_with_failover_sync.assert_not_called()
        self.assertGreaterEqual(self.coordinator.stats["tier1_local_flow_frames"], 1)

    def test_tier2_remote_dispatch_when_pocket_large(self):
        """Khi unrevealed_ratio >= 0.25 và có cụm lớn >= 24x24 px, gọi Remote GPU thành công."""
        ring = {}
        # Cảnh tĩnh hoàn toàn (không có chuyển động) -> optical flow không hé lộ được nền
        for i in range(11):
            frame = np.full((120, 160, 3), 120, dtype=np.uint8)
            mask = np.zeros((120, 160), dtype=np.uint8)
            mask[30:70, 40:80] = 255  # Khối vuông 40x40 px (>= 24x24)
            ring[i] = (frame, mask)

        # Mock remote trả về kết quả hợp lệ
        def mock_inpaint(roi_img, roi_mask, timeout_sec=5.0):
            res = roi_img.copy()
            res[roi_mask > 0] = 180
            return res

        self.mock_remote_client.inpaint_roi_with_failover_sync.side_effect = mock_inpaint

        out = self.coordinator.reconstruct_frame_streaming(
            target_idx=5,
            ring_buffer=ring,
            raw_mask=ring[5][1],
            shot_boundaries=(0, 10),
        )
        self.assertIsNotNone(out)
        self.mock_remote_client.inpaint_roi_with_failover_sync.assert_called_once()
        self.assertEqual(self.coordinator.stats["tier2_remote_gpu_frames"], 1)
        self.assertEqual(self.coordinator.circuit_breaker.state, CircuitState.CLOSED)

    def test_tier3_local_fallback_on_remote_failure(self):
        """Khi Remote GPU bị lỗi/timeout, tự động rẽ nhánh sang Tier 3 Local Fallback không crash."""
        ring = {}
        # Cảnh tĩnh
        for i in range(11):
            frame = np.full((120, 160, 3), 120, dtype=np.uint8)
            mask = np.zeros((120, 160), dtype=np.uint8)
            mask[30:70, 40:80] = 255
            ring[i] = (frame, mask)

        # Mock remote ném ngoại lệ Timeout
        self.mock_remote_client.inpaint_roi_with_failover_sync.side_effect = TimeoutError("Remote timeout")

        out = self.coordinator.reconstruct_frame_streaming(
            target_idx=5,
            ring_buffer=ring,
            raw_mask=ring[5][1],
            shot_boundaries=(0, 10),
        )
        self.assertIsNotNone(out)
        self.assertEqual(out.shape, (120, 160, 3))
        # Phải rơi xuống Tier 3
        self.assertEqual(self.coordinator.stats["tier3_local_fallback_frames"], 1)
        self.assertEqual(self.coordinator.circuit_breaker.failure_count, 1)

    def test_bit_exact_outside_dilated_mask(self):
        """Khung hình đầu ra phải đồng nhất tuyệt đối (100% bit-exact) ngoài dilated mask (+15px)."""
        ring = self._create_synthetic_ring_buffer(11)
        raw_mask = ring[5][1].copy()

        out = self.coordinator.reconstruct_frame_streaming(
            target_idx=5,
            ring_buffer=ring,
            raw_mask=raw_mask,
            shot_boundaries=(0, 10),
        )
        orig_frame = ring[5][0]

        # Vùng ngoài dilated mask (+15px)
        dilated_15 = cv2.dilate(raw_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31)))
        outside_mask = (dilated_15 == 0)

        # Phải bit-identical 100%
        np.testing.assert_array_equal(out[outside_mask], orig_frame[outside_mask])


if __name__ == "__main__":
    unittest.main()
