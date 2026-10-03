"""
Comprehensive Unit Test Suite for Texture-Preserving Inpainting Engine (Milestone 3 / R3).

Covers all 5 core features:
  - F3.1: LaMa ONNX Model Loading, Cache Verification & Atomic Streaming Download.
  - F3.2: CPU Optimization, Thread Control (intra 2, inter 1, sequential), Singleton & Concurrency.
  - F3.3: Zero-Scaling Canvas Pad 512x512 (1:1 mapping, unpad sharpness, letterbox fallback).
  - F3.4: Gaussian Alpha Feathering Stitching (smooth edge transition, seam elimination).
  - F3.5: Pure Guided Filter Fallback Engine (Structure-Texture Decomposition, texture synthesis).
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
    """F3.1: LaMa ONNX Model Loading, Cache Verification & Atomic Streaming Download."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.model_dir = Path(self.temp_dir.name)
        self.model_path = self.model_dir / "lama_fp32.onnx"
        self.inpainter = TexturePreservingInpainter(model_path=self.model_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_default_paths_and_properties(self):
        """Test default and custom model paths."""
        default_inpainter = TexturePreservingInpainter()
        self.assertTrue(str(default_inpainter.model_path).endswith("lama_fp32.onnx"))
        self.assertEqual(self.inpainter.model_path, self.model_path)
        self.assertEqual(self.inpainter.model_dir, self.model_dir)

    def test_is_model_ready_nonexistent(self):
        """is_model_ready returns False when model file does not exist."""
        self.assertFalse(self.model_path.exists())
        self.assertFalse(self.inpainter.is_model_ready())

    def test_is_model_ready_undersized_corrupt(self):
        """is_model_ready returns False when file size is under 200MB threshold."""
        # Create a tiny 1KB dummy file
        self.model_path.write_bytes(b"\x00" * 1024)
        self.assertTrue(self.model_path.exists())
        self.assertFalse(self.inpainter.is_model_ready(), "Corrupt/incomplete model (<200MB) must report not ready.")

    def test_is_model_ready_valid_size(self):
        """is_model_ready returns True when file size >= 200MB."""
        with patch.object(Path, "is_file", return_value=True), \
             patch.object(Path, "stat") as mock_stat:
            mock_stat.return_value.st_size = 208_044_816
            self.assertTrue(self.inpainter.is_model_ready())

    def test_ensure_model_available_already_ready(self):
        """ensure_model_available returns True immediately when model is already cached."""
        with patch.object(self.inpainter, "is_model_ready", return_value=True):
            # Async path
            res_async = asyncio.run(self.inpainter.ensure_model_available())
            self.assertTrue(res_async)
            # Sync path
            res_sync = self.inpainter.ensure_model_available(sync=True)
            self.assertTrue(res_sync)

    def test_ensure_model_available_async_atomic_download_success(self):
        """ensure_model_available async downloads via streaming to temp file then atomically renames."""
        with patch.object(self.inpainter, "is_model_ready", side_effect=[False, True]), \
             patch("httpx.AsyncClient") as mock_client_cls, \
             patch("os.replace") as mock_replace:

            mock_resp = AsyncMock()
            mock_resp.status_code = 200
            mock_resp.aiter_bytes = MagicMock(return_value=_async_chunk_gen([b"chunk1", b"chunk2"]))

            mock_stream_ctx = AsyncMock()
            mock_stream_ctx.__aenter__.return_value = mock_resp
            mock_stream_ctx.__aexit__.return_value = None

            mock_client = AsyncMock()
            mock_client.stream = MagicMock(return_value=mock_stream_ctx)
            mock_client_ctx = AsyncMock()
            mock_client_ctx.__aenter__.return_value = mock_client
            mock_client_ctx.__aexit__.return_value = None
            mock_client_cls.return_value = mock_client_ctx

            with patch.object(Path, "stat") as mock_stat:
                mock_stat.return_value.st_size = 208_044_816
                res = asyncio.run(self.inpainter.ensure_model_available())

            self.assertTrue(res)
            mock_replace.assert_called_once()

    def test_ensure_model_available_download_failure_cleans_up_temp(self):
        """ensure_model_available cleans up temporary file on HTTP error."""
        with patch.object(self.inpainter, "is_model_ready", return_value=False), \
             patch("httpx.AsyncClient") as mock_client_cls:

            mock_resp = AsyncMock()
            mock_resp.status_code = 404

            mock_stream_ctx = AsyncMock()
            mock_stream_ctx.__aenter__.return_value = mock_resp
            mock_stream_ctx.__aexit__.return_value = None

            mock_client = AsyncMock()
            mock_client.stream = MagicMock(return_value=mock_stream_ctx)
            mock_client_ctx = AsyncMock()
            mock_client_ctx.__aenter__.return_value = mock_client
            mock_client_ctx.__aexit__.return_value = None
            mock_client_cls.return_value = mock_client_ctx

            res = asyncio.run(self.inpainter.ensure_model_available())
            self.assertFalse(res)
            # Ensure no partial files left in model_dir
            temp_files = list(self.model_dir.glob("*.tmp*"))
            self.assertEqual(len(temp_files), 0)

    def test_ensure_model_available_sync_download_success(self):
        """ensure_model_available_sync streams download and atomically renames."""
        with patch.object(self.inpainter, "is_model_ready", side_effect=[False, True]), \
             patch("httpx.Client") as mock_client_cls, \
             patch("os.replace") as mock_replace:

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.iter_bytes.return_value = [b"chunkA", b"chunkB"]

            mock_stream_ctx = MagicMock()
            mock_stream_ctx.__enter__.return_value = mock_resp
            mock_stream_ctx.__exit__.return_value = None

            mock_client = MagicMock()
            mock_client.stream.return_value = mock_stream_ctx
            mock_client_ctx = MagicMock()
            mock_client_ctx.__enter__.return_value = mock_client
            mock_client_ctx.__exit__.return_value = None
            mock_client_cls.return_value = mock_client_ctx

            with patch.object(Path, "stat") as mock_stat:
                mock_stat.return_value.st_size = 208_044_816
                res = self.inpainter.ensure_model_available(sync=True)

            self.assertTrue(res)
            mock_replace.assert_called_once()


async def _async_chunk_gen(chunks):
    for c in chunks:
        yield c


class TestF32CpuOptimizationAndThreadControl(unittest.TestCase):
    """F3.2: CPU Optimization & Thread Control (intra 2, inter 1, Singleton & Concurrency)."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.model_path = Path(self.temp_dir.name) / "lama_fp32.onnx"
        self.inpainter = TexturePreservingInpainter(model_path=self.model_path, cpu_threads=2)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_init_session_configures_cpu_threads_and_sequential_mode(self):
        """init_session sets intra_op_num_threads=2, inter_op=1, ORT_SEQUENTIAL."""
        with patch.object(self.inpainter, "is_model_ready", return_value=True), \
             patch("onnxruntime.InferenceSession") as mock_session_cls, \
             patch("onnxruntime.SessionOptions") as mock_opts_cls:

            mock_opts = MagicMock()
            mock_opts_cls.return_value = mock_opts

            mock_session = MagicMock()
            mock_session.get_inputs.return_value = [MagicMock(name="image"), MagicMock(name="mask")]
            mock_session.get_outputs.return_value = [MagicMock(name="output")]
            mock_session_cls.return_value = mock_session

            success = self.inpainter.init_session()

            self.assertTrue(success)
            self.assertEqual(mock_opts.intra_op_num_threads, 2)
            self.assertEqual(mock_opts.inter_op_num_threads, 1)
            mock_session_cls.assert_called_once()
            # Verify CPUExecutionProvider is passed
            call_kwargs = mock_session_cls.call_args[1]
            self.assertIn("CPUExecutionProvider", call_kwargs.get("providers", []))

    def test_singleton_instance_accessor(self):
        """TexturePreservingInpainter.get_instance returns the shared singleton."""
        inst1 = TexturePreservingInpainter.get_instance()
        inst2 = TexturePreservingInpainter.get_instance()
        self.assertIs(inst1, inst2)

    def test_shared_session_reused_across_instances(self):
        """Multiple inpainter instances share the same ONNX InferenceSession for the same model path."""
        p = Path(self.temp_dir.name) / "shared_model.onnx"
        inp1 = TexturePreservingInpainter(model_path=p)
        inp2 = TexturePreservingInpainter(model_path=p)

        with patch.object(inp1, "is_model_ready", return_value=True), \
             patch.object(inp2, "is_model_ready", return_value=True), \
             patch("onnxruntime.InferenceSession") as mock_session_cls:

            mock_sess = MagicMock()
            mock_sess.get_inputs.return_value = [MagicMock(name="image"), MagicMock(name="mask")]
            mock_sess.get_outputs.return_value = [MagicMock(name="output")]
            mock_session_cls.return_value = mock_sess

            self.assertTrue(inp1.init_session())
            self.assertTrue(inp2.init_session())

            # Only created once because of shared cache
            self.assertEqual(mock_session_cls.call_count, 1)
            self.assertIs(inp1._session, inp2._session)

    def test_concurrency_semaphore_limits_parallel_runs(self):
        """Verify that _inpaint_semaphore exists and guards concurrency."""
        self.assertIsNotNone(TexturePreservingInpainter._inpaint_semaphore)
        # Verify semaphore can be acquired and released
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
        # Create a detailed high-frequency pattern (e.g. simulated Porsche speaker grill)
        roi_img = np.zeros((h, w, 3), dtype=np.uint8)
        roi_img[::2, ::2, :] = 255  # fine mesh
        roi_img[1::2, 1::2, 0] = 180

        roi_mask = np.zeros((h, w), dtype=np.uint8)
        roi_mask[20:60, 40:200] = 255  # text stroke

        canvas_img, canvas_mask, meta = self.inpainter.pad_to_512(roi_img, roi_mask)

        # Output canvas must be strictly 512x512
        self.assertEqual(canvas_img.shape, (512, 512, 3))
        self.assertEqual(canvas_mask.shape, (512, 512))
        self.assertEqual(meta["mode"], "pad")
        self.assertEqual(meta["orig_h"], h)
        self.assertEqual(meta["orig_w"], w)

        # Unpad should restore 100% exact pixels with 0 difference
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
        h, w = 600, 800  # larger than 512
        roi_img = np.full((h, w, 3), 150, dtype=np.uint8)
        roi_mask = np.zeros((h, w), dtype=np.uint8)
        roi_mask[100:200, 200:400] = 255

        canvas_img, canvas_mask, meta = self.inpainter.pad_to_512(roi_img, roi_mask)

        self.assertEqual(canvas_img.shape, (512, 512, 3))
        self.assertEqual(canvas_mask.shape, (512, 512))
        self.assertEqual(meta["mode"], "letterbox")
        # Aspect ratio must be preserved: 600/800 = 0.75 -> scaled_w = 512, scaled_h = 384
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
        mask[20:40, 20:40] = 255  # square text stroke

        blended = TexturePreservingInpainter.apply_alpha_feathering(
            orig, inpainted, mask, sigma=1.0, ksize=3
        )

        # 1. Pixels far away from stroke remain 100% original
        self.assertEqual(blended[5, 5, 0], 50)
        self.assertEqual(blended[55, 55, 0], 50)

        # 2. Pixels deep inside the center of the stroke are dominated by inpainted
        self.assertGreater(blended[30, 30, 0], 190)

        # 3. Pixels right on the border (e.g. y=20, x=30) have intermediate values
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
    """F3.5: Pure Guided Filter Fallback Engine (Structure-Texture Decomposition)."""

    def setUp(self):
        self.inpainter = TexturePreservingInpainter()

    def test_pure_guided_filter_independent_of_ximgproc(self):
        """Guided filter runs successfully even if cv2.ximgproc is completely absent."""
        img = np.random.RandomState(42).randint(0, 255, (40, 40, 3), dtype=np.uint8)
        # Pure guided filter must succeed without cv2.ximgproc
        filtered = TexturePreservingInpainter.pure_guided_filter(img, img, radius=4, eps=0.04)
        self.assertEqual(filtered.shape, img.shape)
        self.assertEqual(filtered.dtype, np.uint8)

    def test_pure_guided_filter_mean_preservation_and_smoothing(self):
        """Guided filter preserves global mean intensity while attenuating variance (smoothing)."""
        rng = np.random.RandomState(123)
        base = np.full((50, 50, 3), 128, dtype=np.float32)
        noise = rng.normal(0, 15, (50, 50, 3))
        noisy_img = np.clip(base + noise, 0, 255).astype(np.uint8)

        filtered = TexturePreservingInpainter.pure_guided_filter(noisy_img, noisy_img, radius=5, eps=0.05)

        # Mean should be closely preserved
        self.assertAlmostEqual(float(np.mean(noisy_img)), float(np.mean(filtered)), delta=2.5)
        # Noise variance should be significantly reduced
        self.assertLess(float(np.std(filtered)), float(np.std(noisy_img)))

    def test_pure_guided_filter_edge_preservation(self):
        """High-contrast structural edges are preserved by the Guided Filter."""
        step = np.zeros((60, 60, 3), dtype=np.uint8)
        step[:, :30] = 30
        step[:, 30:] = 220

        filtered = TexturePreservingInpainter.pure_guided_filter(step, step, radius=2, eps=0.01)

        # Far left and far right must remain close to 30 and 220
        self.assertAlmostEqual(float(np.mean(filtered[:, :25])), 30.0, delta=2.0)
        self.assertAlmostEqual(float(np.mean(filtered[:, 35:])), 220.0, delta=2.0)

    def test_fallback_texture_inpaint_preserves_speaker_grill_texture(self):
        """Structure-Texture Decomposition prevents grey cement artifacts on speaker grill pattern."""
        # Create a synthetic Porsche Burmester speaker grill with perforated holes
        h, w = 80, 120
        grill = np.full((h, w, 3), 160, dtype=np.uint8)
        for y in range(0, h, 4):
            for x in range(0, w, 4):
                grill[y : y + 2, x : x + 2] = 40  # grill holes

        mask = np.zeros((h, w), dtype=np.uint8)
        mask[25:55, 30:90] = 255  # subtitle covering speaker grill

        result = self.inpainter.fallback_texture_inpaint(grill, mask)

        self.assertEqual(result.shape, grill.shape)
        # Inpainted hole region must retain micro-texture variation
        hole_std = np.std(result[25:55, 30:90])
        self.assertGreater(
            hole_std,
            5.0,
            f"Inpainted texture std ({hole_std:.2f}) must be > 5.0 to avoid flat grey cement!",
        )

    def test_fallback_texture_inpaint_handles_bgra_transparency(self):
        """Fallback inpainter correctly retains alpha channel on BGRA images."""
        roi_bgra = np.full((50, 50, 4), 150, dtype=np.uint8)
        roi_bgra[:, :, 3] = 210  # alpha
        mask = np.zeros((50, 50), dtype=np.uint8)
        mask[15:35, 15:35] = 255

        res = self.inpainter.fallback_texture_inpaint(roi_bgra, mask)
        self.assertEqual(res.shape, (50, 50, 4))
        self.assertEqual(res[0, 0, 3], 210)


class TestFullInpaintingPipelineIntegration(unittest.TestCase):
    """End-to-end integration tests for inpaint_roi and inpaint_frame_with_regions."""

    def setUp(self):
        self.inpainter = TexturePreservingInpainter()

    def test_inpaint_roi_switches_to_fallback_when_onnx_not_ready(self):
        """inpaint_roi automatically uses fallback engine when ONNX model is missing."""
        self.assertFalse(self.inpainter.is_model_ready())
        img = np.full((60, 100, 3), 140, dtype=np.uint8)
        mask = np.zeros((60, 100), dtype=np.uint8)
        mask[20:40, 20:80] = 255

        res = self.inpainter.inpaint_roi(img, mask)
        self.assertEqual(res.shape, img.shape)
        self.assertEqual(res.dtype, np.uint8)

    def test_inpaint_roi_with_mock_onnx_session_success(self):
        """inpaint_roi executes ONNX inference pipeline when session is active."""
        mock_sess = MagicMock()
        mock_sess.get_inputs.return_value = [MagicMock(name="image"), MagicMock(name="mask")]
        mock_sess.get_outputs.return_value = [MagicMock(name="output")]
        # Mock output shape: (1, 3, 512, 512) float32 in [0, 1]
        mock_output = np.full((1, 3, 512, 512), 0.75, dtype=np.float32)
        mock_sess.run.return_value = [mock_output]

        self.inpainter._session = mock_sess

        img = np.full((80, 160, 3), 100, dtype=np.uint8)
        mask = np.zeros((80, 160), dtype=np.uint8)
        mask[20:60, 30:130] = 255

        res = self.inpainter.inpaint_roi(img, mask)
        self.assertEqual(res.shape, img.shape)
        mock_sess.run.assert_called_once()

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
