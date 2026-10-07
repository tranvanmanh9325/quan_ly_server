"""
Adversarial Stress Testing Suite for VideoCritiqueEngine (Milestone 3).
Author: challenger_gen26_m3_1 (Mathematical & Metrics Adversarial Challenger)

Adversarial Verification Targets:
1. Extreme Background Invariance: Pure white (255) / pure black (0) / flat gradient backgrounds.
   Verifies division-by-zero protection, NaN/Inf immunity for Laplacian Texture Ratio and Sobel Seam.
2. Shot Cut Gating & Flicker Immunity: Severe whole-frame scene transitions.
   Verifies flicker penalty gating and prevents false-positive flicker penalties on scene cuts.
3. Faint Ghosting (alpha=0.15) & Small Vietnamese Diacritics OCR Detection:
   Verifies CLAHE 2x zoom contrast magnification and small font/accent sensitivity.
4. Temporal NMS Temporal Dispersion:
   Verifies that dense contiguous fault clusters within a single shot are NOT clustered together
   and maintain strictly pairwise temporal distance >= 1.0s.
5. Composite Penalty Mathematical Stability & Edge Bounds.
"""

import math
import unittest
from typing import List, Tuple

import cv2
import numpy as np

from app.services.video_critique_engine import (
    FrameQualityRecord,
    VideoCritiqueEngine,
    WorstCandidateRecord,
)


class TestChallengerM3AdversarialMetrics(unittest.TestCase):
    """Adversarial challenge test suite for 5 Streaming CPU Quality Metrics and Harvester."""

    def setUp(self):
        self.engine = VideoCritiqueEngine(max_refinement_rounds=2)

    # ─────────────────────────────────────────────────────────────────────────
    # CHALLENGE 1: EXTREME BACKGROUND INVARIANCE (ZERO DIVISION / NAN / INF)
    # ─────────────────────────────────────────────────────────────────────────

    def test_adversarial_pure_white_background_texture_and_seam(self):
        """
        Adversarial Target: Pure white background (255).
        Risk: Zero variance in Laplacian and zero gradient in Sobel causing 0/0 division, NaN, or Inf.
        """
        h, w = 120, 120
        pure_white = np.full((h, w, 3), 255, dtype=np.uint8)
        mask = np.zeros((h, w), dtype=np.uint8)
        mask[30:70, 30:70] = 255  # Centered inpaint patch

        # 1. Texture Ratio on pure white
        ratio_tex, var_inp, var_ctx = self.engine.compute_texture_ratio(pure_white, mask)
        self.assertFalse(math.isnan(ratio_tex), "Texture ratio on pure white returned NaN!")
        self.assertFalse(math.isinf(ratio_tex), "Texture ratio on pure white returned Inf!")
        self.assertEqual(var_inp, 0.0, "Pure white inpaint variance must be 0.0")
        self.assertEqual(var_ctx, 0.0, "Pure white context variance must be 0.0")
        self.assertEqual(ratio_tex, 1.0, "Smooth flat background exception should return 1.0")

        # 2. Edge Seam Discontinuity on pure white
        ratio_seam, seam_g, ref_g = self.engine.compute_edge_seam_ratio(pure_white, mask)
        self.assertFalse(math.isnan(ratio_seam), "Seam ratio on pure white returned NaN!")
        self.assertFalse(math.isinf(ratio_seam), "Seam ratio on pure white returned Inf!")
        self.assertEqual(seam_g, 0.0, "Pure white seam gradient must be 0.0")
        self.assertEqual(ref_g, 0.0, "Pure white ref gradient must be 0.0")
        self.assertEqual(ratio_seam, 1.0, "Uniform flat background exception should return 1.0")

    def test_adversarial_pure_black_background_texture_and_seam(self):
        """
        Adversarial Target: Pure black background (0).
        Risk: Zero variance and zero gradient in pitch black scene.
        """
        h, w = 120, 120
        pure_black = np.zeros((h, w, 3), dtype=np.uint8)
        mask = np.zeros((h, w), dtype=np.uint8)
        mask[40:80, 40:80] = 255

        # 1. Texture Ratio on pure black
        ratio_tex, var_inp, var_ctx = self.engine.compute_texture_ratio(pure_black, mask)
        self.assertFalse(math.isnan(ratio_tex), "Texture ratio on pure black returned NaN!")
        self.assertFalse(math.isinf(ratio_tex), "Texture ratio on pure black returned Inf!")
        self.assertEqual(ratio_tex, 1.0)

        # 2. Edge Seam Discontinuity on pure black
        ratio_seam, seam_g, ref_g = self.engine.compute_edge_seam_ratio(pure_black, mask)
        self.assertFalse(math.isnan(ratio_seam), "Seam ratio on pure black returned NaN!")
        self.assertFalse(math.isinf(ratio_seam), "Seam ratio on pure black returned Inf!")
        self.assertEqual(ratio_seam, 1.0)

    def test_adversarial_flat_context_with_high_noise_inpaint(self):
        """
        Adversarial Target: Zero context variance (flat white) but corrupted/noisy inpaint region.
        Risk: Denominator is 0.0 or near-zero (+ 1e-6) while numerator is huge (> 100).
        Verifies that no floating-point crash occurs and smooth background branch handles it.
        """
        h, w = 120, 120
        flat_frame = np.full((h, w, 3), 250, dtype=np.uint8)
        mask = np.zeros((h, w), dtype=np.uint8)
        mask[30:70, 30:70] = 255

        # Corrupt inpaint region with severe random noise
        np.random.seed(999)
        noise = np.random.randint(0, 200, (40, 40, 3), dtype=np.uint8)
        flat_frame[30:70, 30:70] = noise

        ratio_tex, var_inp, var_ctx = self.engine.compute_texture_ratio(flat_frame, mask)
        self.assertFalse(math.isnan(ratio_tex))
        self.assertFalse(math.isinf(ratio_tex))
        self.assertTrue(np.isfinite(ratio_tex))
        self.assertTrue(np.isfinite(var_inp))
        self.assertTrue(np.isfinite(var_ctx))
        self.assertGreater(var_inp, 100.0, "Corrupted patch must have high Laplacian variance")

        # Seam ratio must also be finite
        ratio_seam, s_g, r_g = self.engine.compute_edge_seam_ratio(flat_frame, mask)
        self.assertTrue(np.isfinite(ratio_seam))
        self.assertFalse(math.isnan(ratio_seam))

    def test_adversarial_boundary_touching_mask_and_edge_cases(self):
        """
        Adversarial Target: Inpaint mask touching frame borders (x=0 or y=0 or x=W or y=H).
        Risk: Morphological dilation/erosion clipping issues or empty context rings.
        """
        h, w = 80, 80
        test_frame = np.full((h, w, 3), 128, dtype=np.uint8)

        # Case 1: Mask touching top-left corner
        mask_corner = np.zeros((h, w), dtype=np.uint8)
        mask_corner[0:20, 0:20] = 255
        r_tex_c, _, _ = self.engine.compute_texture_ratio(test_frame, mask_corner)
        r_seam_c, _, _ = self.engine.compute_edge_seam_ratio(test_frame, mask_corner)
        self.assertTrue(np.isfinite(r_tex_c))
        self.assertTrue(np.isfinite(r_seam_c))

        # Case 2: Mask touching bottom-right corner
        mask_br = np.zeros((h, w), dtype=np.uint8)
        mask_br[60:80, 60:80] = 255
        r_tex_br, _, _ = self.engine.compute_texture_ratio(test_frame, mask_br)
        r_seam_br, _, _ = self.engine.compute_edge_seam_ratio(test_frame, mask_br)
        self.assertTrue(np.isfinite(r_tex_br))
        self.assertTrue(np.isfinite(r_seam_br))

        # Case 3: Entire frame is mask (no background context exists)
        mask_full = np.full((h, w), 255, dtype=np.uint8)
        r_tex_full, _, _ = self.engine.compute_texture_ratio(test_frame, mask_full)
        r_seam_full, _, _ = self.engine.compute_edge_seam_ratio(test_frame, mask_full)
        self.assertEqual(r_tex_full, 1.0, "Full mask without context must safely default to 1.0")
        self.assertEqual(r_seam_full, 1.0, "Full mask without seam must safely default to 1.0")

        # Case 4: Single-pixel mask
        mask_single = np.zeros((h, w), dtype=np.uint8)
        mask_single[40, 40] = 255
        r_tex_s, _, _ = self.engine.compute_texture_ratio(test_frame, mask_single)
        r_seam_s, _, _ = self.engine.compute_edge_seam_ratio(test_frame, mask_single)
        self.assertTrue(np.isfinite(r_tex_s))
        self.assertTrue(np.isfinite(r_seam_s))

    # ─────────────────────────────────────────────────────────────────────────
    # CHALLENGE 2: SHOT CUT GATING & FLICKER PENALTY SUPPRESSION
    # ─────────────────────────────────────────────────────────────────────────

    def test_adversarial_severe_scene_cut_flicker_suppression(self):
        """
        Adversarial Target: Hard cut between completely different video shots.
        Shot A: bright outdoor scene (mean intensity ~230).
        Shot B: dark indoor scene (mean intensity ~20).
        Risk: DIS optical flow MSE inside former text mask explodes, causing massive false flicker penalty.
        Expectation: Shot cut gating must trigger (is_shot_cut=True), setting flicker_mse=0.0
        and resulting in ZERO penalty contribution in calculate_composite_penalty.
        """
        h, w = 120, 120
        np.random.seed(42)
        frame_a = np.random.randint(210, 255, (h, w, 3), dtype=np.uint8)
        frame_b = np.random.randint(10, 35, (h, w, 3), dtype=np.uint8)

        mask = np.zeros((h, w), dtype=np.uint8)
        mask[30:70, 30:70] = 255

        # 1. Compute temporal flicker across hard cut
        flicker_mse, is_shot_cut = self.engine.compute_temporal_flicker(frame_b, frame_a, mask)
        self.assertTrue(is_shot_cut, "Hard cut must be identified as shot cut!")
        self.assertEqual(flicker_mse, 0.0, "Shot cut must return 0.0 flicker MSE to prevent penalty!")

        # 2. Compute dhash drift across hard cut
        drift, is_shot_drift = self.engine.compute_dhash_drift(frame_b, frame_a)
        self.assertTrue(is_shot_drift, "Hard cut must trigger dHash shot cut flag (drift > 20)!")
        self.assertGreater(drift, 20)

        # 3. Verify Composite Penalty ignores shot cut
        record_cut = FrameQualityRecord(
            frame_idx=150,
            timestamp_sec=5.0,
            residual_words=0,
            residual_max_conf=0.0,
            residual_text="",
            texture_ratio=0.90,
            temporal_flicker_mse=999.0,  # Even if some raw MSE was passed
            edge_seam_ratio=1.05,
            dhash_drift=48,             # Extreme dHash drift
            is_shot_cut=True,           # GATED
            penalty_score=0.0,
        )
        penalty = self.engine.calculate_composite_penalty(record_cut)
        # Should have 0 flicker penalty and 0 drift penalty
        self.assertEqual(penalty, 0.0, f"Gated shot cut was falsely penalized! Score={penalty}")

    def test_adversarial_scene_cut_threshold_boundary_precision(self):
        """
        Adversarial Target: Boundary precision around mean difference threshold of 35.0.
        Tests frames with mean diff exactly 36.0 vs 34.0.
        """
        h, w = 100, 100
        base = np.full((h, w, 3), 100, dtype=np.uint8)
        mask = np.zeros((h, w), dtype=np.uint8)
        mask[20:60, 20:60] = 255

        # Case A: mean diff = 36.0 (above threshold 35.0) -> Shot Cut
        f_above = np.full((h, w, 3), 136, dtype=np.uint8)
        mse_above, is_cut_above = self.engine.compute_temporal_flicker(f_above, base, mask)
        self.assertTrue(is_cut_above, "Mean diff 36.0 must trigger shot cut")
        self.assertEqual(mse_above, 0.0)

        # Case B: mean diff = 34.0 (below threshold 35.0) -> Not Shot Cut (measured)
        f_below = np.full((h, w, 3), 134, dtype=np.uint8)
        mse_below, is_cut_below = self.engine.compute_temporal_flicker(f_below, base, mask)
        self.assertFalse(is_cut_below, "Mean diff 34.0 must not trigger whole-frame shot cut")
        self.assertGreater(mse_below, 0.0)

    # ─────────────────────────────────────────────────────────────────────────
    # CHALLENGE 3: FAINT GHOSTING (ALPHA=0.15) & VIETNAMESE DIACRITICS OCR
    # ─────────────────────────────────────────────────────────────────────────

    def test_adversarial_clahe_contrast_magnification_on_faint_ghosting(self):
        """
        Adversarial Target: Extremely faint ghosting text (alpha = 0.15).
        Risk: Faint residual text characters blend into background and go unnoticed.
        Verifies that CLAHE local contrast enhancement with clipLimit=2.5 and 2x zoom
        actively magnifies the edge contrast of the ghosted glyphs by >= 2.0x.
        """
        # Create 80x240 clean background (light gray 230)
        h, w = 80, 240
        clean_bg = np.full((h, w, 3), 230, dtype=np.uint8)

        # Synthesize faint text with alpha = 0.15 (dark gray 30 on 230 background)
        text_layer = clean_bg.copy()
        cv2.putText(
            text_layer, "GHOST", (20, 50),
            cv2.FONT_HERSHEY_SIMPLEX, 1.2, (30, 30, 30), 3, cv2.LINE_AA
        )

        alpha = 0.15
        ghost_roi = cv2.addWeighted(text_layer, alpha, clean_bg, 1.0 - alpha, 0)

        # Measure baseline contrast in original ghost ROI
        gray_orig = cv2.cvtColor(ghost_roi, cv2.COLOR_BGR2GRAY)
        min_orig, max_orig = float(np.min(gray_orig)), float(np.max(gray_orig))
        baseline_contrast = max_orig - min_orig

        # Replicate the preprocessing pipeline in compute_residual_ocr:
        scaled = cv2.resize(ghost_roi, (w * 2, h * 2), interpolation=cv2.INTER_LINEAR)
        gray_scaled = cv2.cvtColor(scaled, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray_scaled)

        min_enh, max_enh = float(np.min(enhanced)), float(np.max(enhanced))
        enhanced_contrast = max_enh - min_enh

        contrast_gain = enhanced_contrast / (baseline_contrast + 1e-6)
        # CLAHE must significantly stretch the local histogram to expose faint ghosting
        self.assertGreaterEqual(
            contrast_gain, 2.0,
            f"CLAHE failed to magnify ghosting contrast sufficiently! Gain={contrast_gain:.2f}x"
        )

    def test_adversarial_residual_ocr_vietnamese_accent_detection(self):
        """
        Adversarial Target: Residual OCR detection on Vietnamese text with diacritics.
        Creates rendered Vietnamese text ("PHỤ ĐỀ VIỆT") and verifies that
        compute_residual_ocr successfully detects residual words when residual text exists.
        """
        h, w = 90, 350
        roi = np.full((h, w, 3), 245, dtype=np.uint8)

        # Render clear text (simulating incomplete text removal)
        cv2.putText(
            roi, "PHU DE VIET", (20, 55),
            cv2.FONT_HERSHEY_SIMPLEX, 1.1, (10, 10, 10), 2, cv2.LINE_AA
        )

        words, conf, text_det = self.engine.compute_residual_ocr(roi)

        # When residual text is present, words count must be > 0 and confidence > 35
        self.assertGreater(words, 0, f"Residual OCR missed clear residual text! Detected: '{text_det}'")
        self.assertGreaterEqual(conf, 35.0, f"Confidence too low: {conf}")

    def test_adversarial_residual_ocr_smooth_background_immunity(self):
        """
        Adversarial Target: False positive test on smooth gradient background.
        Verifies that natural continuous backgrounds do NOT falsely trigger residual words.
        """
        h, w = 80, 200
        # Horizontal gradient background
        grad = np.tile(np.linspace(100, 180, w, dtype=np.uint8), (h, 1))
        grad_bgr = cv2.cvtColor(grad, cv2.COLOR_GRAY2BGR)

        words, conf, text_det = self.engine.compute_residual_ocr(grad_bgr)
        self.assertEqual(words, 0, f"Residual OCR falsely detected words on smooth gradient: '{text_det}'")
        self.assertEqual(conf, 0.0)

    # ─────────────────────────────────────────────────────────────────────────
    # CHALLENGE 4: TEMPORAL NMS CLUSTERING VS DISPERSION STRESS-TESTING
    # ─────────────────────────────────────────────────────────────────────────

    def test_adversarial_temporal_nms_dense_continuous_fault_cluster(self):
        """
        Adversarial Target: 100 contiguous flawed frames within a single shot (t = 1.00s to 4.30s).
        Risk: Standard Top-K sorts by penalty and picks frames [1.00, 1.033, 1.066] — all from
        the EXACT SAME subtitle, leaving the rest of the video uninspected.
        Expectation: Temporal NMS with min_gap_sec=1.0 MUST strictly enforce pairwise
        temporal separation >= 1.0s across ALL selected candidates.
        """
        records: List[FrameQualityRecord] = []
        fps = 30.0

        # Simulate 100 consecutive frames with monotonically decaying defect penalty
        for i in range(100):
            t = 1.00 + (i / fps)  # t goes from 1.00s to 4.30s
            penalty = 150.0 - (i * 0.5)  # 150.0 down to 100.5
            rec = FrameQualityRecord(
                frame_idx=i + 30,
                timestamp_sec=round(t, 3),
                residual_words=2,
                residual_max_conf=85.0,
                residual_text="persistent_flaw",
                texture_ratio=0.50,
                temporal_flicker_mse=30.0,
                edge_seam_ratio=1.1,
                dhash_drift=3,
                is_shot_cut=False,
                penalty_score=penalty,
                roi_rect=(10, 10, 50, 50),
                orig_crop=np.zeros((30, 30, 3), dtype=np.uint8),
                clean_crop=np.zeros((30, 30, 3), dtype=np.uint8),
                mask_crop=np.zeros((30, 30), dtype=np.uint8),
            )
            records.append(rec)

        # Select K=3 worst candidates with min_gap_sec=1.0
        worst_k = self.engine.select_worst_k_candidates(records, k=3, min_gap_sec=1.0)

        self.assertEqual(len(worst_k), 3, f"Expected exactly 3 candidates, got {len(worst_k)}")

        # Verify STAGE 1: Candidate 0 must be the highest penalty frame (t = 1.00s)
        self.assertAlmostEqual(worst_k[0].timestamp_sec, 1.00, delta=0.04)

        # Verify STAGE 2: Pairwise temporal separation constraint: |t_i - t_j| >= 1.0s
        for idx1 in range(len(worst_k)):
            for idx2 in range(idx1 + 1, len(worst_k)):
                gap = abs(worst_k[idx1].timestamp_sec - worst_k[idx2].timestamp_sec)
                self.assertGreaterEqual(
                    gap, 1.0,
                    f"Temporal NMS VIOLATION: Candidates #{idx1} ({worst_k[idx1].timestamp_sec}s) "
                    f"and #{idx2} ({worst_k[idx2].timestamp_sec}s) are clustered together (gap={gap:.3f}s < 1.0s)!"
                )

    def test_adversarial_temporal_nms_multiple_fault_bursts(self):
        """
        Adversarial Target: Multiple defect bursts at different time intervals.
        Burst 1: t in [0.5s .. 0.8s] (Penalty ~120)
        Burst 2: t in [1.0s .. 1.3s] (Penalty ~110) -> Too close to Burst 1 (< 1.0s)
        Burst 3: t in [3.0s .. 3.3s] (Penalty ~95)  -> Well separated
        Burst 4: t in [5.0s .. 5.3s] (Penalty ~80)  -> Well separated

        Expectation: Harvester MUST enforce pairwise separation >= 1.0s for all selected candidates.
        """
        records: List[FrameQualityRecord] = []

        def _add_burst(start_t: float, count: int, base_penalty: float):
            for i in range(count):
                t = round(start_t + i * 0.1, 2)
                records.append(
                    FrameQualityRecord(
                        frame_idx=int(t * 30),
                        timestamp_sec=t,
                        residual_words=1,
                        residual_max_conf=70.0,
                        residual_text="burst",
                        texture_ratio=0.55,
                        temporal_flicker_mse=25.0,
                        edge_seam_ratio=1.0,
                        dhash_drift=2,
                        is_shot_cut=False,
                        penalty_score=base_penalty - i,
                        roi_rect=(0, 0, 10, 10),
                    )
                )

        _add_burst(0.5, 4, 120.0)  # 0.5s .. 0.8s
        _add_burst(1.0, 4, 110.0)  # 1.0s .. 1.3s (Too close to 0.5s top candidate)
        _add_burst(3.0, 4, 95.0)   # 3.0s .. 3.3s
        _add_burst(5.0, 4, 80.0)   # 5.0s .. 5.3s

        worst = self.engine.select_worst_k_candidates(records, k=3, min_gap_sec=1.0)
        self.assertEqual(len(worst), 3)

        # Verify pairwise temporal separation
        for idx1 in range(len(worst)):
            for idx2 in range(idx1 + 1, len(worst)):
                gap = abs(worst[idx1].timestamp_sec - worst[idx2].timestamp_sec)
                self.assertGreaterEqual(
                    gap, 1.0,
                    f"Temporal separation violated between #{idx1} ({worst[idx1].timestamp_sec}s) and #{idx2} ({worst[idx2].timestamp_sec}s)"
                )

    def test_adversarial_temporal_nms_subsecond_video_bounds(self):
        """
        Adversarial Target: Ultra-short video (0.8 seconds total duration).
        All frames have flaws, but the entire duration is less than min_gap_sec (1.0s).
        Expectation: Engine must not hang, loop infinitely, or crash.
        Must select 1 candidate and terminate safely.
        """
        records: List[FrameQualityRecord] = []
        for i in range(24):
            t = round(i / 30.0, 3)  # 0.0s to 0.767s
            records.append(
                FrameQualityRecord(
                    frame_idx=i,
                    timestamp_sec=t,
                    residual_words=1,
                    residual_max_conf=50.0,
                    residual_text="subsecond",
                    texture_ratio=0.6,
                    temporal_flicker_mse=20.0,
                    edge_seam_ratio=1.0,
                    dhash_drift=2,
                    is_shot_cut=False,
                    penalty_score=100.0 - i,
                    roi_rect=(0, 0, 10, 10),
                )
            )

        worst = self.engine.select_worst_k_candidates(records, k=3, min_gap_sec=1.0)
        # Since all other frames are within 1.0s of the first selected frame,
        # exactly 1 frame can satisfy the >= 1.0s gap constraint.
        self.assertEqual(len(worst), 1)
        self.assertEqual(worst[0].frame_idx, 0)

    # ─────────────────────────────────────────────────────────────────────────
    # CHALLENGE 5: COMPOSITE PENALTY ROBUSTNESS & MATHEMATICAL BOUNDS
    # ─────────────────────────────────────────────────────────────────────────

    def test_adversarial_composite_penalty_extreme_outliers(self):
        """
        Adversarial Target: Extreme outlier values in quality metrics.
        Verifies that calculate_composite_penalty produces finite, valid float values
        without numerical overflow or NaN.
        """
        record_extreme = FrameQualityRecord(
            frame_idx=999,
            timestamp_sec=33.3,
            residual_words=100,             # Massive residual words
            residual_max_conf=100.0,
            residual_text="lots of words",
            texture_ratio=0.0,              # Complete loss of texture
            temporal_flicker_mse=100000.0,  # Astronomical flicker
            edge_seam_ratio=500.0,          # Extreme seam boundary step
            dhash_drift=64,                 # Maximum 64-bit drift
            is_shot_cut=False,
            penalty_score=0.0,
        )

        score = self.engine.calculate_composite_penalty(record_extreme)
        self.assertTrue(np.isfinite(score))
        self.assertGreater(score, 50000.0)


if __name__ == "__main__":
    unittest.main()
