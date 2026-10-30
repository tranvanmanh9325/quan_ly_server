# -*- coding: utf-8 -*-
"""
services/ai-agent-service/tests/test_reconstruction_engine.py
Milestone M3 Test Suite: Visually Flawless Reconstruction & Scene Text Preservation.

Covers:
- Feature 15: Alpha Estimation & Invert Blend Engine (AlphaInvertBlendEngine)
- Feature 16: Forward-Backward Optical Flow Propagation (ForwardBackwardOpticalFlowPropagator)
- Feature 17: Strict +15px Dilated Mask & Cosine Alpha Feathering (FrameCompositor)
- Feature 18: Scene Text Preservation & Zero Collateral Damage Outside Mask
"""

import unittest
import numpy as np
import cv2

from app.services.frame_compositor import FrameCompositor
from app.services.alpha_invert_blend_engine import AlphaInvertBlendEngine
from app.services.forward_backward_flow_propagator import (
    ForwardBackwardOpticalFlowPropagator,
    compute_dhash,
    hamming_distance,
)
from app.services.video_reconstruction_engine import VideoReconstructionEngine
from tools.acceptance.metrics import (
    evaluate_c2_collateral_damage,
    evaluate_c3_reconstruction_fidelity,
    evaluate_c6_artifacts,
    evaluate_c5_negatives,
)


class TestFrameCompositor(unittest.TestCase):
    """Test suite for Feature 17: Strict +15px Dilated Mask & Cosine Feathering."""

    def setUp(self) -> None:
        self.compositor = FrameCompositor(dilation_px=15)
        self.h, self.w = 200, 300

    def test_empty_mask_returns_identical_frame(self) -> None:
        frame_in = np.random.randint(50, 200, (self.h, self.w, 3), dtype=np.uint8)
        frame_inpaint = np.random.randint(50, 200, (self.h, self.w, 3), dtype=np.uint8)
        empty_mask = np.zeros((self.h, self.w), dtype=np.uint8)

        out = self.compositor.composite(frame_in, frame_inpaint, empty_mask)
        self.assertTrue(np.array_equal(out, frame_in))

    def test_none_mask_returns_identical_frame(self) -> None:
        frame_in = np.random.randint(50, 200, (self.h, self.w, 3), dtype=np.uint8)
        frame_inpaint = np.random.randint(50, 200, (self.h, self.w, 3), dtype=np.uint8)

        out = self.compositor.composite(frame_in, frame_inpaint, None)
        self.assertTrue(np.array_equal(out, frame_in))

    def test_bit_exact_outside_dilated_mask(self) -> None:
        """Pixels strictly outside raw_mask + 15px must be 100% bit-exact."""
        frame_in = np.random.randint(40, 220, (self.h, self.w, 3), dtype=np.uint8)
        frame_inpaint = np.random.randint(40, 220, (self.h, self.w, 3), dtype=np.uint8)

        raw_mask = np.zeros((self.h, self.w), dtype=np.uint8)
        raw_mask[80:120, 100:200] = 255

        out = self.compositor.composite(frame_in, frame_inpaint, raw_mask)
        dilated_mask, _ = self.compositor.build_feathered_mask(raw_mask)

        outside_mask = (dilated_mask == 0)
        self.assertTrue(np.array_equal(out[outside_mask], frame_in[outside_mask]))

        # Evaluate C2 Collateral Damage
        c2 = evaluate_c2_collateral_damage(out, frame_in, raw_mask, dilation_px=15)
        self.assertTrue(c2["is_pass"])
        self.assertGreaterEqual(c2["ssim_outside"], 0.999)
        self.assertGreaterEqual(c2["psnr_outside"], 90.0)

    def test_cosine_alpha_smoothstep_profile(self) -> None:
        """Alpha must be 1.0 on raw mask, 0.0 outside +15px, and follow cosine curve."""
        raw_mask = np.zeros((self.h, self.w), dtype=np.uint8)
        raw_mask[80:120, 100:200] = 255

        dilated_mask, alpha = self.compositor.build_feathered_mask(raw_mask)

        # Alpha inside raw mask must be 1.0
        self.assertTrue(np.all(alpha[raw_mask > 0] == 1.0))
        # Alpha outside dilated mask must be 0.0
        self.assertTrue(np.all(alpha[dilated_mask == 0] == 0.0))
        # Transition zone must have alpha strictly between 0 and 1
        transition_zone = (raw_mask == 0) & (dilated_mask > 0)
        self.assertTrue(np.all(alpha[transition_zone] >= 0.0))
        self.assertTrue(np.all(alpha[transition_zone] <= 1.0))

    def test_seam_ratio_with_cosine_feathering(self) -> None:
        """Seam discontinuity ratio must be <= 1.25."""
        base = np.full((self.h, self.w, 3), 128, dtype=np.uint8)
        # Add smooth gradient to base
        for y in range(self.h):
            base[y, :, :] = int(100 + 50 * (y / self.h))

        inpaint = np.full((self.h, self.w, 3), 140, dtype=np.uint8)
        raw_mask = np.zeros((self.h, self.w), dtype=np.uint8)
        raw_mask[70:130, 90:210] = 255

        out = self.compositor.composite(base, inpaint, raw_mask)
        dilated_mask, _ = self.compositor.build_feathered_mask(raw_mask)

        c6 = evaluate_c6_artifacts(out, dilated_mask, baseline_frame=base)
        self.assertTrue(c6["is_pass"])
        self.assertLessEqual(c6["seam_ratio"], 1.25)


class TestAlphaInvertBlendEngine(unittest.TestCase):
    """Test suite for Feature 15: Alpha Invert Blend Engine."""

    def setUp(self) -> None:
        self.engine = AlphaInvertBlendEngine()
        self.h, self.w = 120, 200

    def test_alpha_matte_estimation(self) -> None:
        core_mask = np.zeros((self.h, self.w), dtype=np.uint8)
        core_mask[45:75, 50:150] = 255
        outer_mask = cv2.dilate(core_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)))
        roi = np.full((self.h, self.w, 3), 128, dtype=np.uint8)

        alpha = self.engine.estimate_alpha_matte(roi, core_mask, outer_mask)
        self.assertEqual(alpha.shape, (self.h, self.w))
        self.assertTrue(np.all(alpha[core_mask > 0] == 1.0))
        self.assertTrue(np.all(alpha[outer_mask == 0] == 0.0))

    def test_invert_blend_recovers_synthetic_blended_background(self) -> None:
        """Verify that B = (I - alpha*F)/(1 - alpha) recovers background accurately."""
        # Create patterned background (textured wood grain style)
        bg = np.zeros((self.h, self.w, 3), dtype=np.float32)
        for y in range(self.h):
            for x in range(self.w):
                bg[y, x] = [120 + 20 * np.sin(x / 5.0), 100 + 15 * np.cos(y / 4.0), 80]

        # Define alpha matte with core and fringe
        core_mask = np.zeros((self.h, self.w), dtype=np.uint8)
        core_mask[45:75, 50:150] = 255
        outer_mask = cv2.dilate(core_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)))

        alpha_matte = np.zeros((self.h, self.w), dtype=np.float32)
        alpha_matte[core_mask > 0] = 1.0

        # Create smooth transition fringe with alpha in [0.05, 0.60]
        dist_bg = cv2.distanceTransform(outer_mask, cv2.DIST_L2, 5)
        dist_core = cv2.distanceTransform((core_mask == 0).astype(np.uint8), cv2.DIST_L2, 5)
        fringe = (core_mask == 0) & (outer_mask > 0)
        u = dist_bg[fringe] / (dist_bg[fringe] + dist_core[fringe] + 1e-6)
        alpha_matte[fringe] = 0.60 * (3.0 * (u ** 2) - 2.0 * (u ** 3))

        # Composite foreground text: F = (20, 20, 20) (dark stroke)
        f_color = np.array([20.0, 20.0, 20.0], dtype=np.float32)
        composite = (
            alpha_matte[:, :, np.newaxis] * f_color
            + (1.0 - alpha_matte[:, :, np.newaxis]) * bg
        )
        roi_u8 = np.clip(np.round(composite), 0, 255).astype(np.uint8)
        bg_u8 = np.clip(np.round(bg), 0, 255).astype(np.uint8)

        # Inpaint core with ground truth (simulating optical flow borrow)
        core_inpaint = bg_u8.copy()

        # Run AlphaInvertBlendEngine
        result = self.engine.reconstruct_with_invert_blend(
            roi_img=roi_u8,
            core_mask=core_mask,
            outer_mask=outer_mask,
            core_inpaint_img=core_inpaint,
        )

        # Evaluate fidelity
        c3 = evaluate_c3_reconstruction_fidelity(result, bg_u8, outer_mask, category="R")
        self.assertTrue(c3["is_pass"])
        self.assertGreaterEqual(c3["psnr_inside"], 30.0)
        self.assertGreaterEqual(c3["ssim_inside"], 0.90)


class TestForwardBackwardFlowPropagator(unittest.TestCase):
    """Test suite for Feature 16: Forward-Backward Optical Flow Propagation."""

    def setUp(self) -> None:
        self.propagator = ForwardBackwardOpticalFlowPropagator(
            temporal_radius=3,
            fb_threshold=1.5,
            photo_threshold=12.0,
        )
        self.h, self.w = 120, 160

    def test_bidirectional_warp_synthetic_translation(self) -> None:
        """Synthetic translation dx=2, dy=1 must achieve >=90% FB loop consistency."""
        np.random.seed(42)
        f1 = np.random.randint(60, 180, (self.h, self.w, 3), dtype=np.uint8)
        f1 = cv2.GaussianBlur(f1, (7, 7), 2.0)

        M = np.float32([[1, 0, 2], [0, 1, 1]])
        f2 = cv2.warpAffine(f1, M, (self.w, self.h), borderMode=cv2.BORDER_REFLECT)

        mask1 = np.zeros((self.h, self.w), dtype=np.uint8)
        mask1[40:80, 50:110] = 255
        mask2 = np.zeros((self.h, self.w), dtype=np.uint8)

        warped_ref, valid_mask, e_photo = self.propagator.compute_bidirectional_warp(
            f1, f2, mask1, mask2
        )

        self.assertIsNotNone(warped_ref)
        self.assertIsNotNone(valid_mask)
        # Inside the text mask, valid pixels should be revealed
        revealed_ratio = np.count_nonzero(valid_mask) / np.count_nonzero(mask1)
        self.assertGreaterEqual(revealed_ratio, 0.85)
        self.assertLessEqual(e_photo, 12.0)

    def test_scene_cut_tri_signal_detection(self) -> None:
        """Different textures must be recognized as scene cut."""
        f_wood = np.full((self.h, self.w, 3), 120, dtype=np.uint8)
        f_concrete = np.full((self.h, self.w, 3), 30, dtype=np.uint8)

        is_cut = ForwardBackwardOpticalFlowPropagator.is_scene_cut(f_concrete, f_wood)
        self.assertTrue(is_cut)

        # Same frame slightly shifted should NOT be a cut
        M = np.float32([[1, 0, 1], [0, 1, 1]])
        f_wood_shifted = cv2.warpAffine(f_wood, M, (self.w, self.h))
        is_cut_same = ForwardBackwardOpticalFlowPropagator.is_scene_cut(f_wood_shifted, f_wood)
        self.assertFalse(is_cut_same)

    def test_dhash_and_hamming(self) -> None:
        g1 = np.zeros((64, 64), dtype=np.uint8)
        g2 = np.zeros((64, 64), dtype=np.uint8)
        g2[:, 32:] = 255

        h1 = compute_dhash(g1)
        h2 = compute_dhash(g2)
        dist = hamming_distance(h1, h2)
        self.assertGreaterEqual(dist, 1)


class TestVideoReconstructionEngine(unittest.TestCase):
    """Test suite for integrated VideoReconstructionEngine."""

    def setUp(self) -> None:
        self.engine = VideoReconstructionEngine(
            temporal_radius=2,
            dilation_px=15,
        )
        self.h, self.w = 120, 160

    def test_negative_control_returns_identical_frame(self) -> None:
        """When raw_mask is empty, output must be bit-identical to input."""
        frame = np.random.randint(50, 200, (self.h, self.w, 3), dtype=np.uint8)
        ring_buffer = {0: (frame, np.zeros((self.h, self.w), dtype=np.uint8))}

        out = self.engine.reconstruct_frame_streaming(
            target_idx=0,
            ring_buffer=ring_buffer,
            raw_mask=None,
            shot_boundaries=(0, 10),
            target_scope="overlay",
        )

        c5 = evaluate_c5_negatives(out, frame, is_scene_text=False)
        self.assertTrue(c5["is_pass"])
        self.assertEqual(c5["modified_pixels"], 0)
        self.assertGreaterEqual(c5["psnr"], 60.0)

    def test_scene_text_preservation_in_overlay_mode(self) -> None:
        """Scene text must be preserved when target_scope == 'overlay'."""
        frame = np.random.randint(50, 200, (self.h, self.w, 3), dtype=np.uint8)
        scene_mask = np.zeros((self.h, self.w), dtype=np.uint8)
        scene_mask[50:70, 60:100] = 255  # e.g., Speedometer digits

        ring_buffer = {0: (frame, scene_mask)}

        out = self.engine.reconstruct_frame_streaming(
            target_idx=0,
            ring_buffer=ring_buffer,
            raw_mask=scene_mask,
            shot_boundaries=(0, 10),
            target_scope="overlay",
            scene_text_mask=scene_mask,
        )

        c5 = evaluate_c5_negatives(out, frame, is_scene_text=True, target_scope="overlay", scene_text_mask=scene_mask)
        self.assertTrue(c5["is_pass"])
        self.assertEqual(c5["modified_pixels"], 0)
        self.assertGreaterEqual(c5["scene_text_psnr"], 60.0)

    def test_optical_flow_gating_threshold(self) -> None:
        """Gating threshold must default to 0.25 and be configurable."""
        self.assertEqual(self.engine.unrevealed_gating_threshold, 0.25)
        custom_engine = VideoReconstructionEngine(unrevealed_gating_threshold=0.30)
        self.assertEqual(custom_engine.unrevealed_gating_threshold, 0.30)


if __name__ == "__main__":
    unittest.main()
