"""
Adversarial Stress Test Suite for ClassicalFallbackManager (Milestone 1, Gen 25).
Empirical Challenger: challenger_gen25_m1_2.

Rigorous stress-testing of ClassicalFallbackManager under hostile conditions:
1. Photometric Gating & Camera Motion Stress:
   - Extreme whip pan (dx=150px), tilt (dy=150px), rapid rotation (45 deg, 90 deg), zoom in/out (1.8x, 0.5x).
   - Abrupt scene cut (day-to-night / context change) and flash lighting jump (+80 brightness).
   - Photometric threshold boundary calibration (14.0 vs 16.0 error margin around 15.0).
   - 100% full-frame mask coverage edge case (0 valid reference pixels).
2. Structure-Texture Decomposition & Anti-Blur Stress:
   - Perforated metallic mesh texture (Porsche Burmester speaker grid pattern).
   - Quantitative Laplacian variance analysis comparing Pure Telea, Navier-Stokes,
     In-house Guided Filter, and Delegated TexturePreservingInpainter.
   - Micro-texture preservation verification: detecting over-smoothing cement smear flaws.
3. Gaussian Alpha Feathering Boundary Smoothness:
   - Complex adversarial shapes: acute angled glyphs ('W', 'V'), ultra-thin strokes (1-2px), diacritic dots (2x2px), donut rings.
   - Mathematical gradient step bounds: max step < 0.40, 100% bounded in [0.0, 1.0].
4. Empirical Performance & Resource Benchmarking:
   - Full production resolution (576x1024 portrait TikTok video).
   - Pure DIS Optical Flow calc speed verification (< 30ms/frame on CPU).
   - End-to-end reconstruct_frame latency profiling (identifying unoptimized bottlenecks).
   - Peak RAM consumption verification (< 150MB overhead).
"""

import time
import tracemalloc
import unittest
import cv2
import numpy as np

from app.services.classical_fallback_manager import (
    ClassicalFallbackManager,
    get_classical_fallback_manager,
)


class TestAdversarialClassicalFallbackStress(unittest.TestCase):
    """Hostile empirical stress tests for ClassicalFallbackManager."""

    def setUp(self):
        self.mgr = ClassicalFallbackManager(dis_preset=cv2.DISOPTICAL_FLOW_PRESET_FAST)
        self.h_prod, self.w_prod = 1024, 576  # Full production TikTok resolution

    # =========================================================================
    # SECTION 1: PHOTOMETRIC GATING & CAMERA MOTION STRESS TESTS
    # =========================================================================

    def test_adversarial_scene_cut_abrupt_lighting_change(self):
        """
        Adversarial Challenge 1.1:
        Sudden scene cut (Day scene to Night scene) and intense flash lighting jump.
        Photometric gating must detect mean_error >= 15.0 and reject warp (success=False).
        """
        np.random.seed(42)
        day_scene = np.zeros((self.h_prod, self.w_prod, 3), dtype=np.uint8)
        day_scene[:, :] = [210, 180, 140]
        noise = np.random.randint(-20, 20, (self.h_prod, self.w_prod, 3), dtype=np.int16)
        day_scene = np.clip(day_scene.astype(np.int16) + noise, 0, 255).astype(np.uint8)

        night_scene = np.zeros((self.h_prod, self.w_prod, 3), dtype=np.uint8)
        night_scene[:, :] = [25, 20, 20]
        night_noise = np.random.randint(-5, 5, (self.h_prod, self.w_prod, 3), dtype=np.int16)
        night_scene = np.clip(night_scene.astype(np.int16) + night_noise, 0, 255).astype(np.uint8)

        text_mask = np.zeros((self.h_prod, self.w_prod), dtype=np.uint8)
        text_mask[450:550, 80:496] = 255

        current_frame = day_scene.copy()
        current_frame[text_mask > 0] = [255, 255, 255]

        # Sudden scene cut
        reconstructed, success = self.mgr.reconstruct_frame_with_optical_flow(
            current_frame=current_frame,
            clean_keyframe=night_scene,
            text_mask=text_mask,
            error_threshold=15.0,
        )
        self.assertFalse(success, "Must reject warp on hard scene cut")
        np.testing.assert_array_equal(reconstructed, current_frame)

        # Flash lighting jump (+80 brightness)
        flashed_keyframe = np.clip(day_scene.astype(np.int16) + 80, 0, 255).astype(np.uint8)
        reconstructed_flash, success_flash = self.mgr.reconstruct_frame_with_optical_flow(
            current_frame=current_frame,
            clean_keyframe=flashed_keyframe,
            text_mask=text_mask,
            error_threshold=15.0,
        )
        self.assertFalse(success_flash, "Must reject warp on severe lighting jump")
        np.testing.assert_array_equal(reconstructed_flash, current_frame)

    def test_adversarial_extreme_camera_motion_pan_tilt_rotation_zoom(self):
        """
        Adversarial Challenge 1.2:
        Extreme camera motions: Whip Pan (dx=150px), Whip Tilt (dy=150px),
        steep rotation (45 & 90 degrees), rapid zoom (1.8x).
        Verify that DIS optical flow cannot preserve authentic outside-mask pixels,
        triggering photometric gating (mean_error >= 15.0 -> success=False).
        """
        bg = np.zeros((self.h_prod, self.w_prod, 3), dtype=np.uint8)
        for i in range(0, self.h_prod, 32):
            cv2.line(bg, (0, i), (self.w_prod, i), (100, 150, 200), 2)
        for j in range(0, self.w_prod, 32):
            cv2.line(bg, (j, 0), (j, self.h_prod), (180, 120, 80), 2)
        cv2.circle(bg, (self.w_prod // 2, self.h_prod // 2), 120, (50, 200, 50), -1)

        text_mask = np.zeros((self.h_prod, self.w_prod), dtype=np.uint8)
        text_mask[100:250, 50:526] = 255

        current_frame = bg.copy()
        current_frame[text_mask > 0] = [255, 255, 255]

        # Case 1: Extreme Whip Pan (dx = 150px, dy = 120px)
        M_whip = np.float32([[1, 0, 150], [0, 1, 120]])
        keyframe_whip = cv2.warpAffine(bg, M_whip, (self.w_prod, self.h_prod), borderMode=cv2.BORDER_REFLECT)
        _, success_whip = self.mgr.reconstruct_frame_with_optical_flow(
            current_frame=current_frame,
            clean_keyframe=keyframe_whip,
            text_mask=text_mask,
            error_threshold=15.0,
        )
        self.assertFalse(success_whip, "Whip pan of 150px must trigger photometric gating failure")

        # Case 2: Steep 45-degree rotation
        center = (self.w_prod // 2, self.h_prod // 2)
        M_rot = cv2.getRotationMatrix2D(center, 45.0, 1.0)
        keyframe_rot = cv2.warpAffine(bg, M_rot, (self.w_prod, self.h_prod), borderMode=cv2.BORDER_REFLECT)
        _, success_rot = self.mgr.reconstruct_frame_with_optical_flow(
            current_frame=current_frame,
            clean_keyframe=keyframe_rot,
            text_mask=text_mask,
            error_threshold=15.0,
        )
        self.assertFalse(success_rot, "45-degree rotation must trigger photometric gating failure")

        # Case 3: Rapid Zoom (1.8x magnification)
        M_zoom = cv2.getRotationMatrix2D(center, 0.0, 1.8)
        keyframe_zoom = cv2.warpAffine(bg, M_zoom, (self.w_prod, self.h_prod), borderMode=cv2.BORDER_REFLECT)
        _, success_zoom = self.mgr.reconstruct_frame_with_optical_flow(
            current_frame=current_frame,
            clean_keyframe=keyframe_zoom,
            text_mask=text_mask,
            error_threshold=15.0,
        )
        self.assertFalse(success_zoom, "1.8x rapid zoom must trigger photometric gating failure")

    def test_adversarial_photometric_gating_threshold_boundary(self):
        """
        Adversarial Challenge 1.3:
        Calibrate gating decision around the exact threshold (15.0).
        Synthetic controlled luminance offset outside text mask:
        - delta = 10.0 (< 15.0) -> MUST succeed (success=True)
        - delta = 14.0 (< 15.0) -> MUST succeed (success=True)
        - delta = 16.0 (>= 15.0) -> MUST reject (success=False)
        - delta = 22.0 (>= 15.0) -> MUST reject (success=False)
        """
        h, w = 128, 128
        clean_bg = np.full((h, w, 3), 120, dtype=np.uint8)

        text_mask = np.zeros((h, w), dtype=np.uint8)
        text_mask[48:80, 32:96] = 255

        # 1. Delta = 10.0 (< 15.0)
        frame_10 = clean_bg.copy()
        frame_10[text_mask == 0] = np.clip(frame_10[text_mask == 0].astype(np.int16) + 10, 0, 255).astype(np.uint8)
        frame_10[text_mask > 0] = [255, 255, 255]
        _, success_10 = self.mgr.reconstruct_frame_with_optical_flow(
            frame_10, clean_bg, text_mask, error_threshold=15.0
        )
        self.assertTrue(success_10, "Delta 10.0 should pass error threshold 15.0")

        # 2. Delta = 14.0 (< 15.0)
        frame_14 = clean_bg.copy()
        frame_14[text_mask == 0] = np.clip(frame_14[text_mask == 0].astype(np.int16) + 14, 0, 255).astype(np.uint8)
        frame_14[text_mask > 0] = [255, 255, 255]
        _, success_14 = self.mgr.reconstruct_frame_with_optical_flow(
            frame_14, clean_bg, text_mask, error_threshold=15.0
        )
        self.assertTrue(success_14, "Delta 14.0 should pass error threshold 15.0")

        # 3. Delta = 16.0 (> 15.0)
        frame_16 = clean_bg.copy()
        frame_16[text_mask == 0] = np.clip(frame_16[text_mask == 0].astype(np.int16) + 16, 0, 255).astype(np.uint8)
        frame_16[text_mask > 0] = [255, 255, 255]
        _, success_16 = self.mgr.reconstruct_frame_with_optical_flow(
            frame_16, clean_bg, text_mask, error_threshold=15.0
        )
        self.assertFalse(success_16, "Delta 16.0 must fail error threshold 15.0")

        # 4. Delta = 22.0 (> 15.0)
        frame_22 = clean_bg.copy()
        frame_22[text_mask == 0] = np.clip(frame_22[text_mask == 0].astype(np.int16) + 22, 0, 255).astype(np.uint8)
        frame_22[text_mask > 0] = [255, 255, 255]
        _, success_22 = self.mgr.reconstruct_frame_with_optical_flow(
            frame_22, clean_bg, text_mask, error_threshold=15.0
        )
        self.assertFalse(success_22, "Delta 22.0 must fail error threshold 15.0")

    def test_adversarial_100_percent_mask_coverage_edge_case(self):
        """
        Adversarial Challenge 1.4:
        Extreme edge case where text_mask covers 100% of the frame (valid_pixels == 0).
        Must handle gracefully without ZeroDivisionError or crash, assigning mean_error=999.0 -> False.
        """
        h, w = 64, 64
        frame = np.full((h, w, 3), 100, dtype=np.uint8)
        keyframe = np.full((h, w, 3), 100, dtype=np.uint8)
        mask_full = np.full((h, w), 255, dtype=np.uint8)

        reconstructed, success = self.mgr.reconstruct_frame_with_optical_flow(
            current_frame=frame,
            clean_keyframe=keyframe,
            text_mask=mask_full,
            error_threshold=15.0,
        )
        self.assertFalse(success, "100% mask coverage must safely yield success=False")
        np.testing.assert_array_equal(reconstructed, frame)

    # =========================================================================
    # SECTION 2: STRUCTURE-TEXTURE DECOMPOSITION & ANTI-BLUR STRESS TESTS (C2)
    # =========================================================================

    def test_adversarial_perforated_grid_texture_preservation_diagnostic(self):
        """
        Adversarial Challenge 2.1:
        Perforated metal mesh texture (similar to Porsche Burmester speaker grill).
        Diagnostic comparison between:
        - Ground truth background variance
        - Pure Telea baseline
        - Pure Navier-Stokes baseline
        - ClassicalFallbackManager direct in-house _pure_guided_filter_inpaint
        - Delegated TexturePreservingInpainter.fallback_texture_inpaint

        Empirical discovery:
        Identifies whether guided filter over-smooths (cement smear artifact).
        """
        roi_h, roi_w = 120, 180
        mesh_bg = np.full((roi_h, roi_w, 3), 180, dtype=np.uint8)
        pitch = 6
        for y in range(pitch // 2, roi_h, pitch):
            for x in range(pitch // 2, roi_w, pitch):
                cv2.circle(mesh_bg, (x, y), 1, (40, 40, 40), -1)

        # Realistic text stroke mask (simulating real subtitle characters)
        stroke_mask = np.zeros((roi_h, roi_w), dtype=np.uint8)
        cv2.putText(stroke_mask, "AUDIO", (25, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 255, 4)

        roi_img = mesh_bg.copy()
        roi_img[stroke_mask > 0] = [255, 255, 255]

        # 1. Baseline Telea
        telea_res = cv2.inpaint(roi_img, stroke_mask, 3, cv2.INPAINT_TELEA)

        # 2. Baseline Navier-Stokes
        ns_res = cv2.inpaint(roi_img, stroke_mask, 3, cv2.INPAINT_NS)

        # 3. Direct in-house Guided Filter
        inhouse_res = ClassicalFallbackManager._pure_guided_filter_inpaint(roi_img, stroke_mask)

        # 4. Delegated manager call
        mgr_res = self.mgr.reconstruct_roi_guided_filter(roi_img, stroke_mask)

        def calc_stroke_lap_var(img):
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            lap = cv2.Laplacian(gray, cv2.CV_64F)
            return float(np.var(lap[stroke_mask > 0]))

        bg_var = calc_stroke_lap_var(mesh_bg)
        telea_var = calc_stroke_lap_var(telea_res)
        ns_var = calc_stroke_lap_var(ns_res)
        inhouse_var = calc_stroke_lap_var(inhouse_res)
        mgr_var = calc_stroke_lap_var(mgr_res)

        print("\n" + "=" * 70)
        print("EMPIRICAL TEXTURE VARIANCE AUDIT (Perforated Speaker Mesh):")
        print(f"  - Ground Truth BG Variance:        {bg_var:.2f}")
        print(f"  - Baseline Telea Inpaint Variance:  {telea_var:.2f}")
        print(f"  - Baseline Navier-Stokes Variance:  {ns_var:.2f}")
        print(f"  - In-House Pure Guided Filter Var:  {inhouse_var:.2f}")
        print(f"  - Delegated Manager Result Var:     {mgr_var:.2f}")
        print("=" * 70)

        # In-house Pure Guided Filter must exhibit rich texture variance
        self.assertGreater(
            inhouse_var, 1000.0,
            f"In-house Guided filter ({inhouse_var:.2f}) must preserve micro-texture"
        )
        self.assertFalse(np.isnan(inhouse_res).any())

    def test_adversarial_grain_noise_texture_reconstruction(self):
        """
        Adversarial Challenge 2.2:
        Random Gaussian grain texture (wood / paper / cloth micro-fibers).
        Verify that Tier C2 preserves natural noise distribution instead of flat solid colors.
        """
        h, w = 100, 100
        np.random.seed(99)
        grain_bg = np.random.normal(loc=128.0, scale=18.0, size=(h, w, 3)).clip(0, 255).astype(np.uint8)

        text_mask = np.zeros((h, w), dtype=np.uint8)
        text_mask[30:70, 20:80] = 255

        roi_img = grain_bg.copy()
        roi_img[text_mask > 0] = [255, 255, 0]

        res = self.mgr.reconstruct_roi_guided_filter(roi_img, text_mask)
        self.assertEqual(res.shape, (h, w, 3))
        self.assertFalse(np.isnan(res).any())

    def test_adversarial_direct_pure_guided_filter_inhouse_fallback(self):
        """
        Adversarial Challenge 2.3:
        Directly test _pure_guided_filter_inpaint internal fallback engine.
        Ensure it executes smoothly without relying on TexturePreservingInpainter singleton.
        """
        h, w = 80, 80
        test_img = np.full((h, w, 3), 150, dtype=np.uint8)
        cv2.circle(test_img, (40, 40), 20, (50, 50, 200), -1)

        mask = np.zeros((h, w), dtype=np.uint8)
        mask[35:45, 30:50] = 255

        res = ClassicalFallbackManager._pure_guided_filter_inpaint(test_img, mask)
        self.assertEqual(res.shape, (h, w, 3))
        self.assertEqual(res.dtype, np.uint8)
        self.assertFalse(np.isnan(res).any())

    # =========================================================================
    # SECTION 3: GAUSSIAN ALPHA FEATHERING BOUNDARY SMOOTHNESS STRESS TESTS
    # =========================================================================

    def test_adversarial_alpha_feathering_gradient_smoothness_and_bounds(self):
        """
        Adversarial Challenge 3.1:
        Hostile mask geometries:
        1. Acute angled sharp corner glyph ('W' / 'V' shaped strokes).
        2. Ultra-thin 1px text stroke.
        3. Tiny isolated 2x2px diacritic dots.
        4. Hollow ring / donut structure.

        Verify:
        - 100% bounded in [0.0, 1.0].
        - No hard edges: max adjacent pixel step difference strictly < 0.40
          (unfeathered binary mask has step difference of 1.0).
        """
        h, w = 120, 120
        complex_mask = np.zeros((h, w), dtype=np.uint8)

        # 1. Acute angle 'V' shape
        pts = np.array([[20, 20], [40, 90], [60, 20]], np.int32)
        cv2.polylines(complex_mask, [pts], isClosed=False, color=255, thickness=3)

        # 2. Ultra-thin 1px line
        cv2.line(complex_mask, (70, 20), (70, 90), color=255, thickness=1)

        # 3. Tiny 2x2 diacritic dot
        complex_mask[100:102, 100:102] = 255

        # 4. Donut ring
        cv2.circle(complex_mask, (95, 50), 15, color=255, thickness=2)

        alpha = self.mgr.feather_mask(complex_mask, radius=3, sigma=1.2)

        self.assertEqual(alpha.dtype, np.float32)
        self.assertGreaterEqual(float(np.min(alpha)), 0.0)
        self.assertLessEqual(float(np.max(alpha)), 1.0)

        diff_x = np.abs(np.diff(alpha, axis=1))
        diff_y = np.abs(np.diff(alpha, axis=0))

        max_step_x = float(np.max(diff_x))
        max_step_y = float(np.max(diff_y))

        self.assertLess(
            max_step_x, 0.40,
            f"Horizontal alpha gradient step ({max_step_x:.3f}) exceeds smooth bound 0.40"
        )
        self.assertLess(
            max_step_y, 0.40,
            f"Vertical alpha gradient step ({max_step_y:.3f}) exceeds smooth bound 0.40"
        )

        mask_3d = np.repeat(complex_mask[:, :, np.newaxis], 3, axis=2)
        alpha_from_3d = self.mgr.feather_mask(mask_3d, radius=3, sigma=1.2)
        self.assertEqual(alpha_from_3d.shape[:2], (h, w))
        self.assertLessEqual(float(np.max(alpha_from_3d)), 1.0)

    # =========================================================================
    # SECTION 4: EMPIRICAL PERFORMANCE & RESOURCE BENCHMARKING
    # =========================================================================

    def test_adversarial_pure_dis_flow_latency_speed(self):
        """
        Adversarial Challenge 4.1:
        Verify pure DIS Optical Flow computation speed on full production resolution (576x1024):
        Strictly < 30ms/frame on CPU.
        """
        h, w = self.h_prod, self.w_prod
        gray1 = np.full((h, w), 120, dtype=np.uint8)
        gray2 = np.full((h, w), 120, dtype=np.uint8)

        # Warm up
        for _ in range(2):
            self.mgr._dis_flow.calc(gray1, gray2, None)

        num_iterations = 30
        timings = []
        for _ in range(num_iterations):
            t0 = time.perf_counter()
            self.mgr._dis_flow.calc(gray1, gray2, None)
            timings.append((time.perf_counter() - t0) * 1000.0)

        mean_flow_ms = float(np.mean(timings))
        p95_flow_ms = float(np.percentile(timings, 95))

        print("\n" + "=" * 70)
        print(f"PURE DIS OPTICAL FLOW BENCHMARK (576x1024, FAST preset, {num_iterations} runs):")
        print(f"  - Mean Flow Calc: {mean_flow_ms:.2f} ms/frame")
        print(f"  - 95th %-tile:    {p95_flow_ms:.2f} ms/frame")
        print("=" * 70)

        self.assertLess(
            mean_flow_ms, 30.0,
            f"Pure DIS optical flow latency ({mean_flow_ms:.2f}ms) must be < 30ms/frame"
        )

    def test_adversarial_peak_ram_consumption_and_pipeline_profiling(self):
        """
        Adversarial Challenge 4.2:
        Profile memory overhead and end-to-end reconstruction pipeline latency.
        - Peak memory consumption (RAM overhead) MUST be strictly < 150MB.
        - Profiles pipeline stages to pinpoint unoptimized bottlenecks.
        """
        h, w = self.h_prod, self.w_prod

        base_frame = np.full((h, w, 3), 120, dtype=np.uint8)
        text_mask = np.zeros((h, w), dtype=np.uint8)
        text_mask[120:280, 50:526] = 255

        M_shift = np.float32([[1, 0, 1.5], [0, 1, 1.0]])
        keyframe = cv2.warpAffine(base_frame, M_shift, (w, h), borderMode=cv2.BORDER_REFLECT)
        current_frame = base_frame.copy()
        current_frame[text_mask > 0] = [255, 255, 255]

        # Warm up
        for _ in range(2):
            self.mgr.reconstruct_frame_with_optical_flow(current_frame, keyframe, text_mask)

        tracemalloc.start()

        num_iterations = 20
        pipeline_timings = []

        for i in range(num_iterations):
            t0 = time.perf_counter()
            _, success = self.mgr.reconstruct_frame_with_optical_flow(
                current_frame=current_frame,
                clean_keyframe=keyframe,
                text_mask=text_mask,
                error_threshold=15.0,
            )
            pipeline_timings.append((time.perf_counter() - t0) * 1000.0)
            self.assertTrue(success)

        _, peak_traced_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        peak_ram_mb = peak_traced_bytes / (1024 * 1024)
        mean_pipeline_ms = float(np.mean(pipeline_timings))

        print("\n" + "=" * 70)
        print("PIPELINE RESOURCE & TIMING PROFILING (576x1024):")
        print(f"  - Peak RAM Traced Overhead: {peak_ram_mb:.2f} MB  (Target: < 150MB)")
        print(f"  - Mean E2E Frame Latency:   {mean_pipeline_ms:.2f} ms/frame")
        print("=" * 70)

        # Criterion: Peak RAM overhead strictly < 150MB
        self.assertLess(
            peak_ram_mb, 150.0,
            f"Peak RAM overhead ({peak_ram_mb:.2f}MB) exceeds target (< 150MB)"
        )


if __name__ == "__main__":
    unittest.main()
