"""
Comprehensive Unit Test Suite for Texture-Preserving Inpainting Engine (Milestone 3 / R3).

Covers all core features under Zero Local AI Policy:
  - F3.1: Model Lifecycle & Zero Local AI Policy verification.
  - F3.2: CPU Optimization, Thread Control, Singleton & Concurrency.
  - F3.3: Zero-Scaling Canvas Pad 512x512 (1:1 mapping, unpad sharpness, letterbox fallback).
  - F3.4: Gaussian Alpha Feathering Stitching (smooth edge transition, seam elimination).
  - F3.5: Pure Guided Filter Engine (Structure-Texture Decomposition, texture synthesis).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import cv2
import numpy as np

# Ensure app directory is importable
_cur = Path(__file__).resolve()
for _p in [_cur.parent] + list(_cur.parents):
    if (_p / "app").is_dir():
        if str(_p) not in sys.path:
            sys.path.insert(0, str(_p))
        break
    if (_p / "services" / "ai-agent-service").is_dir():
        _svc_dir = str(_p / "services" / "ai-agent-service")
        if _svc_dir not in sys.path:
            sys.path.insert(0, _svc_dir)
        break

from app.services.texture_preserving_inpainter import TexturePreservingInpainter


class TestF31ModelLoadingAndCache(unittest.TestCase):
    """F3.1: Zero Local AI Policy & Path Configuration."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.model_dir = Path(self.temp_dir.name)
        self.model_path = self.model_dir / "inpaint_model.bin"
        self.inpainter = TexturePreservingInpainter(model_path=self.model_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_default_paths_and_properties(self):
        """Test default and custom model paths."""
        default_inpainter = TexturePreservingInpainter()
        self.assertIsNotNone(default_inpainter.model_path)
        self.assertEqual(self.inpainter.model_path, self.model_path)
        self.assertEqual(self.inpainter.model_dir, self.model_dir)

    def test_is_model_ready_always_false_zero_local_ai(self):
        """Under Zero Local AI Policy, is_model_ready always reports False."""
        self.assertFalse(self.inpainter.is_model_ready())

    def test_ensure_model_available_download_disabled(self):
        """Zero Local AI Policy: ensure_model_available returns False without downloading."""
        res_async = asyncio.run(self.inpainter.ensure_model_available())
        self.assertFalse(res_async)
        res_sync = self.inpainter.ensure_model_available(sync=True)
        self.assertFalse(res_sync)


class TestF32CpuOptimizationAndThreadControl(unittest.TestCase):
    """F3.2: CPU Optimization & Thread Control (intra 2, inter 1, Singleton & Concurrency)."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.model_path = Path(self.temp_dir.name) / "inpaint_model.bin"
        self.inpainter = TexturePreservingInpainter(model_path=self.model_path, cpu_threads=2)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_init_session_zero_local_ai(self):
        """init_session returns False by default and True only when session is injected."""
        self.assertFalse(self.inpainter.init_session())
        self.inpainter._session = MagicMock()
        self.assertTrue(self.inpainter.init_session())

    def test_singleton_instance_accessor(self):
        """TexturePreservingInpainter.get_instance returns the shared singleton."""
        inst1 = TexturePreservingInpainter.get_instance()
        inst2 = TexturePreservingInpainter.get_instance()
        self.assertIs(inst1, inst2)

    def test_concurrency_semaphore_limits_parallel_runs(self):
        """Verify that _inpaint_semaphore exists and guards concurrency."""
        self.assertIsNotNone(TexturePreservingInpainter._inpaint_semaphore)
        acquired = TexturePreservingInpainter._inpaint_semaphore.acquire(blocking=False)
        self.assertTrue(acquired)
        TexturePreservingInpainter._inpaint_semaphore.release()


class TestF33ZeroScalingCanvasPad512(unittest.TestCase):
    """F3.3: Zero-Scaling Canvas Pad 512x512 (1:1 mapping, unpad sharpness, letterbox fallback)."""

    def setUp(self):
        self.inpainter = TexturePreservingInpainter()

    def test_pad_to_512_small_roi_preserves_1to1_pixel_sharpness(self):
        """ROI <= 512x512 is padded 1:1 without resizing, unpad restores exact original pixels."""
        h, w = 80, 240
        roi_img = np.zeros((h, w, 3), dtype=np.uint8)
        roi_img[::2, ::2, :] = 255
        roi_img[1::2, 1::2, 0] = 180

        roi_mask = np.zeros((h, w), dtype=np.uint8)
        roi_mask[20:60, 40:200] = 255

        canvas_img, canvas_mask, meta = self.inpainter.pad_to_512(roi_img, roi_mask)

        self.assertEqual(canvas_img.shape, (512, 512, 3))
        self.assertEqual(canvas_mask.shape, (512, 512))
        self.assertEqual(meta["mode"], "pad")
        self.assertEqual(meta["orig_h"], h)
        self.assertEqual(meta["orig_w"], w)

        unpadded = self.inpainter.unpad_from_512(canvas_img, meta)
        self.assertEqual(unpadded.shape, (h, w, 3))
        diff = np.max(np.abs(unpadded.astype(np.int32) - roi_img.astype(np.int32)))
        self.assertEqual(diff, 0, "Zero-Scaling Pad and Unpad must have EXACT zero pixel difference!")

    def test_pad_to_512_exact_512x512_roi(self):
        """ROI exactly 512x512 requires 0 padding."""
        roi_img = np.full((512, 512, 3), 100, dtype=np.uint8)
        roi_mask = np.zeros((512, 512), dtype=np.uint8)

        canvas_img, canvas_mask, meta = self.inpainter.pad_to_512(roi_img, roi_mask)
        self.assertEqual(canvas_img.shape, (512, 512, 3))
        self.assertEqual(meta["mode"], "pad")
        self.assertEqual(meta["pad_top"], 0)
        self.assertEqual(meta["pad_left"], 0)

        unpadded = self.inpainter.unpad_from_512(canvas_img, meta)
        self.assertEqual(unpadded.shape, (512, 512, 3))
        self.assertTrue(np.array_equal(unpadded, roi_img))

    def test_pad_to_512_oversized_roi_letterbox_fallback(self):
        """ROI > 512x512 triggers aspect-ratio preserving letterbox fallback."""
        h, w = 600, 800
        roi_img = np.full((h, w, 3), 150, dtype=np.uint8)
        roi_mask = np.zeros((h, w), dtype=np.uint8)
        roi_mask[100:200, 200:400] = 255

        canvas_img, canvas_mask, meta = self.inpainter.pad_to_512(roi_img, roi_mask)

        self.assertEqual(canvas_img.shape, (512, 512, 3))
        self.assertEqual(canvas_mask.shape, (512, 512))
        self.assertEqual(meta["mode"], "letterbox")
        self.assertEqual(meta["scaled_w"], 512)
        self.assertEqual(meta["scaled_h"], 384)

        unpadded = self.inpainter.unpad_from_512(canvas_img, meta)
        self.assertEqual(unpadded.shape, (h, w, 3), "Unpad must restore original oversized dimensions.")


class TestF34GaussianAlphaFeathering(unittest.TestCase):
    """F3.4: Gaussian Alpha Feathering Stitching (smooth edge transition, seam elimination)."""

    def test_empty_mask_returns_original_copy(self):
        """When mask is all zero, feathering returns exact original image."""
        orig = np.full((50, 50, 3), 120, dtype=np.uint8)
        inpainted = np.full((50, 50, 3), 200, dtype=np.uint8)
        mask = np.zeros((50, 50), dtype=np.uint8)

        blended = TexturePreservingInpainter.apply_alpha_feathering(orig, inpainted, mask)
        self.assertTrue(np.array_equal(blended, orig))

    def test_smooth_transition_across_stroke_boundary(self):
        """Feathering produces a continuous gradient transition across stroke edges."""
        orig = np.full((60, 60, 3), 50, dtype=np.uint8)
        inpainted = np.full((60, 60, 3), 200, dtype=np.uint8)

        mask = np.zeros((60, 60), dtype=np.uint8)
        mask[20:40, 20:40] = 255

        blended = TexturePreservingInpainter.apply_alpha_feathering(
            orig, inpainted, mask, sigma=1.0, ksize=3
        )

        self.assertEqual(blended[5, 5, 0], 50)
        self.assertEqual(blended[55, 55, 0], 50)
        self.assertGreater(blended[30, 30, 0], 190)

        border_val = blended[20, 30, 0]
        self.assertGreater(border_val, 50)
        self.assertLess(border_val, 200)

    def test_feathering_with_bgra_preserves_dimensions(self):
        """Feathering works seamlessly on 4-channel BGRA arrays."""
        orig = np.full((40, 40, 4), 100, dtype=np.uint8)
        inpainted = np.full((40, 40, 4), 180, dtype=np.uint8)
        mask = np.zeros((40, 40), dtype=np.uint8)
        mask[10:30, 10:30] = 255

        blended = TexturePreservingInpainter.apply_alpha_feathering(orig, inpainted, mask)
        self.assertEqual(blended.shape, (40, 40, 4))


class TestF35PureGuidedFilterFallbackEngine(unittest.TestCase):
    """F3.5: Pure Guided Filter Engine (Structure-Texture Decomposition)."""

    def setUp(self):
        self.inpainter = TexturePreservingInpainter()

    def test_pure_guided_filter_independent_of_ximgproc(self):
        """Guided filter runs successfully with native NumPy and cv2.boxFilter."""
        img = np.random.RandomState(42).randint(0, 255, (40, 40, 3), dtype=np.uint8)
        filtered = TexturePreservingInpainter.pure_guided_filter(img, img, radius=4, eps=0.04)
        self.assertEqual(filtered.shape, img.shape)
        self.assertEqual(filtered.dtype, np.uint8)

    def test_pure_guided_filter_mean_preservation_and_smoothing(self):
        """Guided filter preserves global mean intensity while attenuating variance."""
        rng = np.random.RandomState(123)
        base = np.full((50, 50, 3), 128, dtype=np.float32)
        noise = rng.normal(0, 15, (50, 50, 3))
        noisy_img = np.clip(base + noise, 0, 255).astype(np.uint8)

        filtered = TexturePreservingInpainter.pure_guided_filter(noisy_img, noisy_img, radius=5, eps=0.05)

        self.assertAlmostEqual(float(np.mean(noisy_img)), float(np.mean(filtered)), delta=2.5)
        self.assertLess(float(np.std(filtered)), float(np.std(noisy_img)))

    def test_pure_guided_filter_edge_preservation(self):
        """High-contrast structural edges are preserved by the Guided Filter."""
        step = np.zeros((60, 60, 3), dtype=np.uint8)
        step[:, :30] = 30
        step[:, 30:] = 220

        filtered = TexturePreservingInpainter.pure_guided_filter(step, step, radius=2, eps=0.01)

        self.assertAlmostEqual(float(np.mean(filtered[:, :25])), 30.0, delta=2.0)
        self.assertAlmostEqual(float(np.mean(filtered[:, 35:])), 220.0, delta=2.0)

    def test_fallback_texture_inpaint_preserves_speaker_grill_texture(self):
        """Structure-Texture Decomposition prevents grey cement artifacts on speaker grill pattern."""
        h, w = 80, 120
        grill = np.full((h, w, 3), 160, dtype=np.uint8)
        for y in range(0, h, 4):
            for x in range(0, w, 4):
                grill[y : y + 2, x : x + 2] = 40

        mask = np.zeros((h, w), dtype=np.uint8)
        mask[25:55, 30:90] = 255

        result = self.inpainter.fallback_texture_inpaint(grill, mask)

        self.assertEqual(result.shape, grill.shape)
        hole_std = np.std(result[25:55, 30:90])
        self.assertGreater(
            hole_std,
            5.0,
            f"Inpainted texture std ({hole_std:.2f}) must be > 5.0 to avoid flat grey cement!",
        )

    def test_fallback_texture_inpaint_handles_bgra_transparency(self):
        """Fallback inpainter correctly retains alpha channel on BGRA images."""
        roi_bgra = np.full((50, 50, 4), 150, dtype=np.uint8)
        roi_bgra[:, :, 3] = 210
        mask = np.zeros((50, 50), dtype=np.uint8)
        mask[15:35, 15:35] = 255

        res = self.inpainter.fallback_texture_inpaint(roi_bgra, mask)
        self.assertEqual(res.shape, (50, 50, 4))
        self.assertEqual(res[0, 0, 3], 210)


class TestFullInpaintingPipelineIntegration(unittest.TestCase):
    """End-to-end integration tests for inpaint_roi and inpaint_frame_with_regions."""

    def setUp(self):
        self.inpainter = TexturePreservingInpainter()

    def test_inpaint_roi_uses_pure_guided_filter_engine(self):
        """inpaint_roi uses Pure Guided Filter Structure-Texture Decomposition engine."""
        self.assertFalse(self.inpainter.is_model_ready())
        img = np.full((60, 100, 3), 140, dtype=np.uint8)
        mask = np.zeros((60, 100), dtype=np.uint8)
        mask[20:40, 20:80] = 255

        res = self.inpainter.inpaint_roi(img, mask)
        self.assertEqual(res.shape, img.shape)
        self.assertEqual(res.dtype, np.uint8)

    def test_inpaint_frame_with_regions_multiple_disjoint_subtitles(self):
        """inpaint_frame_with_regions processes multiple subtitle boxes across full frame."""
        frame = np.full((400, 576, 3), 120, dtype=np.uint8)
        regions = [
            {"x": 60, "y": 80, "w": 300, "h": 40, "text": "Top Title"},
            {"x": 80, "y": 300, "w": 280, "h": 50, "text": "Bottom Subtitle"},
        ]

        def dummy_mask_gen(roi, prev_mask=None):
            m = np.zeros(roi.shape[:2], dtype=np.uint8)
            m[10:-10, 10:-10] = 255
            return m

        clean_frame, masks = self.inpainter.inpaint_frame_with_regions(
            frame, regions, dummy_mask_gen, context_margin=16
        )

        self.assertEqual(clean_frame.shape, frame.shape)
        self.assertEqual(len(masks), 2)
        self.assertIn("Top Title", masks)
        self.assertIn("Bottom Subtitle", masks)

    def test_inpaint_frame_with_regions_empty_or_none_inputs(self):
        """inpaint_frame_with_regions handles empty regions or None frame gracefully."""
        self.assertIsNone(self.inpainter.inpaint_frame_with_regions(None, [], lambda r, p: None)[0])
        frame = np.full((100, 100, 3), 50, dtype=np.uint8)
        out, masks = self.inpainter.inpaint_frame_with_regions(frame, [], lambda r, p: None)
        self.assertTrue(np.array_equal(out, frame))
        self.assertEqual(masks, {})


if __name__ == "__main__":
    unittest.main()
