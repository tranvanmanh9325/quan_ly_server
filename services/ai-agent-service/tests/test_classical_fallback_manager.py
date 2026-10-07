"""
Unit tests for ClassicalFallbackManager (Milestone 1, Feature F3 & F4).
Tests DIS Optical Flow pixel borrowing, photometric gating, Guided Filter structure-texture
decomposition, Navier-Stokes alpha feathering, zero-local-AI constraints, and memory safety.
"""

import unittest
import cv2
import numpy as np

from app.services.classical_fallback_manager import (
    ClassicalFallbackManager,
    get_classical_fallback_manager,
)


class TestClassicalFallbackManager(unittest.TestCase):
    """Test suite for ClassicalFallbackManager."""

    def setUp(self):
        self.mgr = ClassicalFallbackManager()
        self.h, self.w = 64, 64

        # Base background: smooth 2D gradient
        x = np.linspace(0, 255, self.w, dtype=np.float32)
        y = np.linspace(0, 255, self.h, dtype=np.float32)
        xx, yy = np.meshgrid(x, y)
        self.base_bg = ((xx + yy) / 2.0).astype(np.uint8)
        self.base_bg_bgr = cv2.cvtColor(self.base_bg, cv2.COLOR_GRAY2BGR)

        # Text mask: centered 16x16 box
        self.text_mask = np.zeros((self.h, self.w), dtype=np.uint8)
        self.text_mask[24:40, 24:40] = 255

    def test_feather_mask_shape_and_bounds(self):
        """Verify Gaussian Alpha Feathering produces smooth float32 [0.0, 1.0] transitions."""
        alpha = self.mgr.feather_mask(self.text_mask, radius=3, sigma=1.2)
        self.assertEqual(alpha.shape, (self.h, self.w))
        self.assertEqual(alpha.dtype, np.float32)
        self.assertGreaterEqual(float(np.min(alpha)), 0.0)
        self.assertLessEqual(float(np.max(alpha)), 1.0)

        # Center should be high alpha, border should be zero
        self.assertGreater(alpha[32, 32], 0.8)
        self.assertEqual(alpha[0, 0], 0.0)

    def test_c1_optical_flow_reconstruction_success_low_motion(self):
        """
        Verify Tier C1 successfully borrows pixels from keyframe when motion is small
        and photometric error is strictly below threshold (< 15.0).
        """
        clean_keyframe = self.base_bg_bgr.copy()

        # Shift current frame slightly by 1 pixel (small rigid motion)
        M = np.float32([[1, 0, 1], [0, 1, 1]])
        current_frame = cv2.warpAffine(clean_keyframe, M, (self.w, self.h))

        # Add text overlay on current frame
        current_frame[self.text_mask > 0] = [255, 255, 255]

        reconstructed, success = self.mgr.reconstruct_frame_with_optical_flow(
            current_frame=current_frame,
            clean_keyframe=clean_keyframe,
            text_mask=self.text_mask,
            error_threshold=15.0,
        )

        self.assertTrue(success, "Optical flow warp should succeed under low motion")
        self.assertEqual(reconstructed.shape, current_frame.shape)

        # Text pixels should be replaced (no longer 255 white)
        center_val = reconstructed[32, 32]
        self.assertFalse(np.array_equal(center_val, [255, 255, 255]))

        stats = self.mgr.get_stats()
        self.assertGreaterEqual(stats["c1_flow_invocations"], 1)
        self.assertGreaterEqual(stats["c1_flow_successes"], 1)

    def test_c1_optical_flow_reconstruction_failure_scene_cut(self):
        """
        Verify Tier C1 safely rejects reconstruction and signals fallback (success=False)
        when camera angle changes or scene cuts occur (photometric error >= 15.0).
        """
        clean_keyframe = np.full((self.h, self.w, 3), 240, dtype=np.uint8)  # White scene
        current_frame = np.full((self.h, self.w, 3), 20, dtype=np.uint8)   # Dark scene
        current_frame[self.text_mask > 0] = [255, 255, 255]

        reconstructed, success = self.mgr.reconstruct_frame_with_optical_flow(
            current_frame=current_frame,
            clean_keyframe=clean_keyframe,
            text_mask=self.text_mask,
            error_threshold=15.0,
        )

        self.assertFalse(success, "Optical flow should fail on scene cut / high discrepancy")
        # Should return copy of current frame without crash
        self.assertEqual(reconstructed.shape, current_frame.shape)

    def test_c2_guided_filter_reconstruction_preserves_structure(self):
        """
        Verify Tier C2 Structure-Texture Decomposition preserves gradient and sharpness.
        """
        roi_img = self.base_bg_bgr[16:48, 16:48].copy()
        roi_mask = np.zeros(roi_img.shape[:2], dtype=np.uint8)
        roi_mask[8:24, 8:24] = 255

        # Place artificial text into ROI
        roi_img[roi_mask > 0] = [255, 255, 255]

        result = self.mgr.reconstruct_roi_guided_filter(roi_img, roi_mask)
        self.assertIsNotNone(result)
        self.assertEqual(result.shape, roi_img.shape)

        # Inpainted region should blend smoothly into gradient
        center_color = result[16, 16]
        self.assertFalse(np.array_equal(center_color, [255, 255, 255]))

        stats = self.mgr.get_stats()
        self.assertGreaterEqual(stats["c2_guided_filter_invocations"], 1)

    def test_c3_emergency_telea_ns(self):
        """Verify Tier C3 emergency Navier-Stokes inpainting executes smoothly."""
        roi_img = self.base_bg_bgr[16:48, 16:48].copy()
        roi_mask = np.zeros(roi_img.shape[:2], dtype=np.uint8)
        roi_mask[10:20, 10:20] = 255

        roi_img[roi_mask > 0] = [0, 255, 0]

        res = self.mgr.reconstruct_roi_emergency_telea_ns(roi_img, roi_mask)
        self.assertIsNotNone(res)
        self.assertEqual(res.shape, roi_img.shape)
        self.assertEqual(res.dtype, np.uint8)

        stats = self.mgr.get_stats()
        self.assertGreaterEqual(stats["c3_emergency_invocations"], 1)

    def test_zero_local_ai_weights_constraint(self):
        """
        Integrity constraint test:
        Verify ClassicalFallbackManager uses strictly 0MB neural network weights.
        """
        # Ensure no torch / onnxruntime modules are imported by this manager
        import sys
        self.assertNotIn("torch", sys.modules, "Zero Local AI violation: torch must not be imported")
        self.assertNotIn("onnxruntime", sys.modules, "Zero Local AI violation: onnxruntime must not be imported")

    def test_empty_or_none_inputs_handled_gracefully(self):
        """Verify boundary inputs (empty masks, None) are safely handled."""
        roi_img = self.base_bg_bgr.copy()
        empty_mask = np.zeros((self.h, self.w), dtype=np.uint8)

        # Empty mask should return original image unchanged
        res_c2 = self.mgr.reconstruct_roi_guided_filter(roi_img, empty_mask)
        np.testing.assert_array_equal(res_c2, roi_img)

        res_c3 = self.mgr.reconstruct_roi_emergency_telea_ns(roi_img, empty_mask)
        np.testing.assert_array_equal(res_c3, roi_img)

        # None input to optical flow should raise ValueError
        with self.assertRaises(ValueError):
            self.mgr.reconstruct_frame_with_optical_flow(None, roi_img, empty_mask)

    def test_singleton_factory(self):
        """Verify singleton factory accessor."""
        m1 = get_classical_fallback_manager()
        m2 = get_classical_fallback_manager()
        self.assertIs(m1, m2)

    def test_c2_guided_filter_preserves_perforated_texture_variance(self):
        """
        Verify reconstruct_roi_guided_filter retains rich micro-texture variance (>= 2500)
        on perforated grid surfaces instead of over-smoothing to flat blur.
        """
        roi_h, roi_w = 120, 180
        mesh_bg = np.full((roi_h, roi_w, 3), 180, dtype=np.uint8)
        pitch = 6
        for y in range(pitch // 2, roi_h, pitch):
            for x in range(pitch // 2, roi_w, pitch):
                cv2.circle(mesh_bg, (x, y), 1, (40, 40, 40), -1)

        stroke_mask = np.zeros((roi_h, roi_w), dtype=np.uint8)
        cv2.putText(stroke_mask, "AUDIO", (25, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 255, 4)

        roi_img = mesh_bg.copy()
        roi_img[stroke_mask > 0] = [255, 255, 255]

        res = self.mgr.reconstruct_roi_guided_filter(roi_img, stroke_mask)
        self.assertEqual(res.shape, (roi_h, roi_w, 3))

        gray = cv2.cvtColor(res, cv2.COLOR_BGR2GRAY)
        lap = cv2.Laplacian(gray, cv2.CV_64F)
        var = float(np.var(lap[stroke_mask > 0]))

        self.assertGreaterEqual(
            var,
            2500.0,
            f"Manager guided filter texture variance ({var:.2f}) must be >= 2500 to preserve mesh structure",
        )

    def test_c1_optical_flow_meshgrid_caching_and_fast_empty_mask(self):
        """Verify grid caching and immediate return on empty mask."""
        clean_keyframe = self.base_bg_bgr.copy()
        current_frame = self.base_bg_bgr.copy()
        empty_mask = np.zeros((self.h, self.w), dtype=np.uint8)

        # Empty mask returns immediately
        reconstructed, success = self.mgr.reconstruct_frame_with_optical_flow(
            current_frame=current_frame,
            clean_keyframe=clean_keyframe,
            text_mask=empty_mask,
        )
        self.assertTrue(success)
        np.testing.assert_array_equal(reconstructed, current_frame)

        # Non-empty mask triggers cache creation
        text_mask = np.zeros((self.h, self.w), dtype=np.uint8)
        text_mask[10:20, 10:20] = 255
        self.mgr.reconstruct_frame_with_optical_flow(current_frame, clean_keyframe, text_mask)
        self.assertEqual(self.mgr._grid_h, self.h)
        self.assertEqual(self.mgr._grid_w, self.w)
        cached_x = self.mgr._grid_map_x
        cached_y = self.mgr._grid_map_y
        self.assertIsNotNone(cached_x)
        self.assertIsNotNone(cached_y)

        # Next call with same resolution must reuse cached arrays
        self.mgr.reconstruct_frame_with_optical_flow(current_frame, clean_keyframe, text_mask)
        self.assertIs(self.mgr._grid_map_x, cached_x)
        self.assertIs(self.mgr._grid_map_y, cached_y)

    def test_c1_optical_flow_local_bounding_box_blending(self):
        """Verify blending is applied strictly within padded bounding box of text mask."""
        clean_keyframe = self.base_bg_bgr.copy()
        current_frame = self.base_bg_bgr.copy()
        text_mask = np.zeros((self.h, self.w), dtype=np.uint8)
        # Small box in center
        text_mask[30:34, 30:34] = 255
        current_frame[text_mask > 0] = [255, 255, 255]

        reconstructed, success = self.mgr.reconstruct_frame_with_optical_flow(
            current_frame=current_frame,
            clean_keyframe=clean_keyframe,
            text_mask=text_mask,
        )
        self.assertTrue(success)
        # Pixels far outside bounding box (+16px pad) must be bit-exact identical to current_frame
        np.testing.assert_array_equal(reconstructed[:10, :10], current_frame[:10, :10])
        np.testing.assert_array_equal(reconstructed[54:, 54:], current_frame[54:, 54:])


if __name__ == "__main__":
    unittest.main()
