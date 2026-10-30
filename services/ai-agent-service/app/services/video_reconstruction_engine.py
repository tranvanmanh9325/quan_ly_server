# -*- coding: utf-8 -*-
"""
services/ai-agent-service/app/services/video_reconstruction_engine.py
Milestone M3: Unified Video Reconstruction Engine.

Orchestrates:
1. Multi-frame Bidirectional DIS Optical Flow Propagation (Feature 16).
2. Physical Alpha Invert Blending on semi-transparent fringe alpha <= 0.70 (Feature 15).
3. Classical Guided Filter / Navier-Stokes fallback for truly unrevealed pixels.
4. Strict Mask Dilation +15px with C^1 Cosine Alpha Feathering (Feature 17).
5. Zero Collateral Damage & Scene Text Preservation (Feature 18).
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple
import cv2
import numpy as np

from app.services.alpha_invert_blend_engine import AlphaInvertBlendEngine
from app.services.forward_backward_flow_propagator import ForwardBackwardOpticalFlowPropagator
from app.services.frame_compositor import FrameCompositor

logger = logging.getLogger(__name__)


class VideoReconstructionEngine:
    """
    Central Coordinator for Milestone M3 Visually Flawless Video Text Reconstruction.
    """

    def __init__(
        self,
        temporal_radius: int = 20,
        dilation_px: int = 15,
        fb_threshold: float = 1.5,
        photo_threshold: float = 12.0,
        unrevealed_gating_threshold: float = 0.25,
    ) -> None:
        self.flow_propagator = ForwardBackwardOpticalFlowPropagator(
            temporal_radius=temporal_radius,
            fb_threshold=fb_threshold,
            photo_threshold=photo_threshold,
        )
        self.compositor = FrameCompositor(dilation_px=dilation_px)
        self.blend_engine = AlphaInvertBlendEngine()
        self.unrevealed_gating_threshold = unrevealed_gating_threshold

    def reconstruct_frame_streaming(
        self,
        target_idx: int,
        ring_buffer: Dict[int, Tuple[np.ndarray, np.ndarray]],  # idx -> (frame_bgr, raw_mask_u8)
        raw_mask: Optional[np.ndarray],
        shot_boundaries: Tuple[int, int],  # (shot_start, shot_end)
        target_scope: str = "overlay",
        scene_text_mask: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """
        Reconstruct a single frame using streaming multi-frame optical flow,
        alpha invert blend, and strict +15px feathering.

        Args:
            target_idx: Index of current frame.
            ring_buffer: Streaming ring-buffer mapping idx -> (frame_bgr, mask_u8).
            raw_mask: Mask of detected text for current frame.
            shot_boundaries: Tuple of (shot_start, shot_end) for scene cut isolation.
            target_scope: 'overlay' (preserve scene text) or 'all' (remove all text).
            scene_text_mask: Optional mask identifying scene text to be preserved.

        Returns:
            Visually flawless reconstructed BGR frame.
        """
        frame_t, _ = ring_buffer[target_idx]
        h, w = frame_t.shape[:2]

        effective_mask = raw_mask.copy() if raw_mask is not None else np.zeros((h, w), dtype=np.uint8)

        # Feature 18: Scene Text Preservation in default 'overlay' mode
        if target_scope == "overlay" and scene_text_mask is not None and np.count_nonzero(scene_text_mask) > 0:
            effective_mask[scene_text_mask > 0] = 0

        # If effective mask is empty, preserve 100% bit-exact original frame
        if np.count_nonzero(effective_mask) == 0:
            return frame_t.copy()

        # Step 1: Multi-frame temporal background fusion using DIS Optical Flow
        fused_frame, unrevealed_mask = self.flow_propagator.fuse_multiframe_background(
            target_idx=target_idx,
            ring_buffer=ring_buffer,
            shot_boundaries=shot_boundaries,
        )

        # Step 2: Spatial structure-preserving inpainting for truly unrevealed pixels
        core_candidate = fused_frame.copy()
        if np.count_nonzero(unrevealed_mask) > 0:
            # Use cv2.INPAINT_TELEA on small unrevealed pockets to bridge narrow gaps
            unrevealed_dil = cv2.dilate(
                unrevealed_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            )
            inpaint_core = cv2.inpaint(core_candidate, unrevealed_dil, inpaintRadius=3, flags=cv2.INPAINT_TELEA)
            core_candidate[unrevealed_mask > 0] = inpaint_core[unrevealed_mask > 0]

        total_mask_pixels = int(np.count_nonzero(effective_mask))
        unrevealed_pixels = int(np.count_nonzero(unrevealed_mask))
        unrevealed_ratio = (unrevealed_pixels / total_mask_pixels) if total_mask_pixels > 0 else 0.0

        # If at least 75% of true background is revealed via Optical Flow,
        # directly composite the flow-reconstructed background with Telea gap fills
        if unrevealed_ratio < self.unrevealed_gating_threshold:
            return self.compositor.composite(
                frame_in=frame_t,
                frame_inpaint=core_candidate,
                raw_mask=effective_mask,
            )

        # Step 3: Feature 15 - Physical Alpha Invert Blending on semi-transparent transition fringe
        k_outer = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
        outer_mask = cv2.dilate(effective_mask, k_outer)

        blended_roi = self.blend_engine.reconstruct_with_invert_blend(
            roi_img=frame_t,
            core_mask=effective_mask,
            outer_mask=outer_mask,
            core_inpaint_img=core_candidate,
        )

        # Step 4: Feature 17 - Strict +15px Dilated Mask & C^1 Cosine Feathering
        final_frame = self.compositor.composite(
            frame_in=frame_t,
            frame_inpaint=blended_roi,
            raw_mask=effective_mask,
        )

        return final_frame
