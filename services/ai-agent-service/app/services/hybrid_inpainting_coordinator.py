# -*- coding: utf-8 -*-
"""
Hybrid Inpainting Coordinator & Robust Fallback Engine (Milestone M4 / Feature 19).
Architecture:
- Tier 1: Local Optical Flow Forward-Backward Reconstruction when unrevealed_ratio < 0.25 (>= 75% revealed).
- Tier 2: Remote Neural Inpainting for large pockets (>= 24x24 px) with Circuit Breaker FSM (CLOSED -> OPEN -> HALF-OPEN).
- Tier 3: Local Classical Fallback (Alpha Invert Blend + Telea gap-fill) on network fault / timeout (<= 5.0s).
- Strict +15px Cosine Smoothstep Feathering guaranteeing bit-exact outside mask identity (PSNR=100dB).
"""

from __future__ import annotations

import asyncio
from enum import Enum
import logging
import time
from typing import Any, Dict, List, Optional, Tuple, Union

import cv2
import numpy as np

from app.services.video_reconstruction_engine import VideoReconstructionEngine
from app.services.remote_gpu_worker_client import (
    RemoteGpuWorkerClient,
    get_remote_gpu_worker_client,
)

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class RemoteCircuitBreaker:
    """Quản lý máy trạng thái ngắt mạch tự phục hồi cho Remote GPU Worker."""

    def __init__(
        self,
        failure_threshold: int = 3,
        base_cooldown_sec: float = 60.0,
        max_cooldown_sec: float = 300.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.base_cooldown_sec = base_cooldown_sec
        self.max_cooldown_sec = max_cooldown_sec
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.cooldown_until = 0.0
        self.current_cooldown = base_cooldown_sec

    def can_attempt(self) -> bool:
        """Kiểm tra mạch có cho phép thực hiện kết nối hay không."""
        now = time.time()
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if now >= self.cooldown_until:
                self.state = CircuitState.HALF_OPEN
                logger.info("[CircuitBreaker] Transition to HALF-OPEN for probe attempt.")
                return True
            return False
        if self.state == CircuitState.HALF_OPEN:
            return True
        return False

    def record_success(self) -> None:
        """Ghi nhận yêu cầu thành công, đưa mạch về CLOSED và reset bộ đếm."""
        if self.state != CircuitState.CLOSED:
            logger.info("[CircuitBreaker] Probe succeeded. Resetting circuit to CLOSED.")
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.current_cooldown = self.base_cooldown_sec

    def record_failure(self, reason: str = "") -> None:
        """Ghi nhận lỗi, nếu vượt ngưỡng thì chuyển mạch sang OPEN với cooldown tăng dần."""
        self.failure_count += 1
        now = time.time()
        if self.state == CircuitState.HALF_OPEN or self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self.cooldown_until = now + self.current_cooldown
            logger.warning(
                "[CircuitBreaker] Circuit TRIPPED to OPEN (cooldown %.1fs, failures=%d, reason: %s)",
                self.current_cooldown, self.failure_count, reason
            )
            self.current_cooldown = min(self.max_cooldown_sec, self.current_cooldown * 2.0)


class HybridInpaintingCoordinator:
    """
    Bộ điều phối hợp nhất kết nối VideoEditorService với Remote GPU Inpainting
    và Local Classical Inpainting (VideoReconstructionEngine M3).
    """

    def __init__(
        self,
        local_engine: Optional[VideoReconstructionEngine] = None,
        remote_client: Optional[RemoteGpuWorkerClient] = None,
        unrevealed_gating_threshold: float = 0.25,
        min_remote_pocket_size: int = 24,
        remote_timeout_sec: float = 5.0,
    ) -> None:
        self.local_engine = local_engine or VideoReconstructionEngine(
            temporal_radius=20,
            dilation_px=15,
            unrevealed_gating_threshold=unrevealed_gating_threshold,
        )
        self.remote_client = remote_client or get_remote_gpu_worker_client()
        self.unrevealed_gating_threshold = unrevealed_gating_threshold
        self.min_remote_pocket_size = min_remote_pocket_size
        self.remote_timeout_sec = remote_timeout_sec
        self.circuit_breaker = RemoteCircuitBreaker()
        self.stats = {
            "tier1_local_flow_frames": 0,
            "tier2_remote_gpu_frames": 0,
            "tier3_local_fallback_frames": 0,
            "remote_short_circuits": 0,
        }

    def _should_delegate_to_remote(
        self,
        unrevealed_mask: np.ndarray,
        unrevealed_ratio: float,
    ) -> bool:
        """Đánh giá điều kiện cần thiết để kích hoạt Remote GPU theo Decision Matrix."""
        if unrevealed_ratio < self.unrevealed_gating_threshold:
            return False

        if not self.circuit_breaker.can_attempt():
            self.stats["remote_short_circuits"] += 1
            return False

        # Kiểm tra kích thước hình học của cụm unrevealed lớn nhất
        contours, _ = cv2.findContours(unrevealed_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return False

        max_w, max_h = 0, 0
        for cnt in contours:
            _, _, cw, ch = cv2.boundingRect(cnt)
            max_w = max(max_w, cw)
            max_h = max(max_h, ch)

        return (max_w >= self.min_remote_pocket_size and max_h >= self.min_remote_pocket_size)

    def reconstruct_frame_streaming(
        self,
        target_idx: int,
        ring_buffer: Dict[int, Tuple[np.ndarray, np.ndarray]],
        raw_mask: Optional[np.ndarray],
        shot_boundaries: Tuple[int, int],
        target_scope: str = "overlay",
        scene_text_mask: Optional[np.ndarray] = None,
        context: Optional[Any] = None,
    ) -> np.ndarray:
        """
        Tái tạo khung hình hỗ hợp 3 tầng:
        1. Gọi Local Flow Propagator trước để lấy fused_frame và unrevealed_mask.
        2. Nếu tỷ lệ unrevealed < 0.25 -> Tier 1: Local Optical Flow Reconstruction.
        3. Nếu unrevealed >= 0.25 và có cụm lớn >= 24x24 px -> Tier 2: Remote GPU Inpainting.
        4. Nếu Remote lỗi / timeout -> Tier 3: Local Alpha Invert Blend & Telea Fallback.
        5. FrameCompositor bảo tồn 100% ngoài mask +15px với Cosine Smoothstep Feathering.
        """
        frame_t, _ = ring_buffer[target_idx]
        h, w = frame_t.shape[:2]

        effective_mask = raw_mask.copy() if raw_mask is not None else np.zeros((h, w), dtype=np.uint8)

        # Feature 18: Bảo tồn chữ cảnh trong mode 'overlay'
        if target_scope == "overlay" and scene_text_mask is not None and np.count_nonzero(scene_text_mask) > 0:
            effective_mask[scene_text_mask > 0] = 0

        if np.count_nonzero(effective_mask) == 0:
            return frame_t.copy()

        # Bước 1: Lan truyền Optical Flow DIS đa khung hình nội bộ
        fused_frame, unrevealed_mask = self.local_engine.flow_propagator.fuse_multiframe_background(
            target_idx=target_idx,
            ring_buffer=ring_buffer,
            shot_boundaries=shot_boundaries,
        )

        total_mask_pixels = int(np.count_nonzero(effective_mask))
        unrevealed_pixels = int(np.count_nonzero(unrevealed_mask))
        unrevealed_ratio = (unrevealed_pixels / total_mask_pixels) if total_mask_pixels > 0 else 0.0

        # Phân nhánh Tier 1: Nền đã hé lộ >= 75% -> Ghép nối trực tiếp
        if unrevealed_ratio < self.unrevealed_gating_threshold:
            self.stats["tier1_local_flow_frames"] += 1
            core_candidate = fused_frame.copy()
            if unrevealed_pixels > 0:
                unrevealed_dil = cv2.dilate(
                    unrevealed_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
                )
                inpaint_core = cv2.inpaint(core_candidate, unrevealed_dil, inpaintRadius=3, flags=cv2.INPAINT_TELEA)
                core_candidate[unrevealed_mask > 0] = inpaint_core[unrevealed_mask > 0]

            return self.local_engine.compositor.composite(
                frame_in=frame_t,
                frame_inpaint=core_candidate,
                raw_mask=effective_mask,
            )

        # Phân nhánh Tier 2: Thử nghiệm Remote GPU cho mảng unrevealed lớn
        core_candidate = fused_frame.copy()
        remote_success = False

        if self._should_delegate_to_remote(unrevealed_mask, unrevealed_ratio) and self.remote_client:
            ux, uy, uw, uh = cv2.boundingRect(unrevealed_mask)
            pad = 10
            rx1 = max(0, ux - pad)
            ry1 = max(0, uy - pad)
            rx2 = min(w, ux + uw + pad)
            ry2 = min(h, uy + uh + pad)

            roi_img = frame_t[ry1:ry2, rx1:rx2]
            roi_mask = unrevealed_mask[ry1:ry2, rx1:rx2]

            try:
                res_roi = self.remote_client.inpaint_roi_with_failover_sync(
                    roi_img, roi_mask, timeout_sec=self.remote_timeout_sec
                )
                if res_roi is not None and getattr(res_roi, "shape", None) == roi_img.shape:
                    core_candidate[ry1:ry2, rx1:rx2][roi_mask > 0] = res_roi[roi_mask > 0]
                    self.circuit_breaker.record_success()
                    self.stats["tier2_remote_gpu_frames"] += 1
                    remote_success = True
                else:
                    self.circuit_breaker.record_failure("Invalid remote ROI response geometry")
            except Exception as err:
                logger.warning("[HybridCoordinator] Remote GPU inpaint error: %s", err)
                self.circuit_breaker.record_failure(str(err))

        # Phân nhánh Tier 3: Local Fallback khi Remote thất bại hoặc không thỏa mãn điều kiện
        if not remote_success:
            self.stats["tier3_local_fallback_frames"] += 1
            if unrevealed_pixels > 0:
                unrevealed_dil = cv2.dilate(
                    unrevealed_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
                )
                inpaint_core = cv2.inpaint(core_candidate, unrevealed_dil, inpaintRadius=3, flags=cv2.INPAINT_TELEA)
                core_candidate[unrevealed_mask > 0] = inpaint_core[unrevealed_mask > 0]

        # Khử viền thâm đen bằng Physical Alpha Invert Blending
        k_outer = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
        outer_mask = cv2.dilate(effective_mask, k_outer)

        blended_roi = self.local_engine.blend_engine.reconstruct_with_invert_blend(
            roi_img=frame_t,
            core_mask=effective_mask,
            outer_mask=outer_mask,
            core_inpaint_img=core_candidate,
        )

        # Ghép nối bảo toàn nghiêm ngặt ngoài mặt nạ +15px
        return self.local_engine.compositor.composite(
            frame_in=frame_t,
            frame_inpaint=blended_roi,
            raw_mask=effective_mask,
        )
