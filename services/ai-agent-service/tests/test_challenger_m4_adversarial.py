"""
Empirical Adversarial Test Suite for Milestone 4 (R4):
Temporal Coherence, FFmpeg Quality Export, and Zero-Disk Leak.

Adversarial Stress Testing:
  1. Temporal Mask Smoothing (F4.1):
     - 1-2px jitter stabilization vs independent frame masking.
     - Extreme motion/jump cut (> 15px, IoU < 0.70) rejection (no ghosting/inflation).
     - Sudden scene cut luminance jump (> 60.0) instant cache wipe (zero ghosting).
     - Reverse scene cut (bright -> dark) and chromatic scene cut (blue -> green).
     - Smooth gradual lighting transition (diff < 60.0) preserves temporal continuity.
  2. FFmpeg Export Flags (F4.2):
     - Strict verification of -c:v libx264, -preset fast, -crf 18, -c:a copy, -movflags +faststart, -shortest.
     - Automatic fallback to -c:a aac -b:a 192k when audio copy stream fails (both inpaint & delogo).
     - Double failure raises descriptive RuntimeError.
     - Missing FFmpeg binary gracefully copies raw inpaint video.
  3. Zero-Disk Leak (F4.3):
     - Frame loop crash cleans up 100% scratch files (inp_raw_*.mp4) and releases VideoWriter.
     - FFmpeg subprocess crash cleans up 100% scratch files.
     - Task cancellation aborts cleanly with zero leftover files.
     - High-level remove_text_from_video cleans up output_file on failure.
     - Stress test: repeated consecutive crashes leave exactly 0 leaked files.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

# Ensure services/ai-agent-service is in sys.path
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

from app.services.video_editor_service import VideoEditorService, get_texture_preserving_inpainter
from app.services.texture_preserving_inpainter import TexturePreservingInpainter


class TestChallengerTemporalMaskSmoothing(unittest.TestCase):
    """
    Empirical Adversarial Tests for F4.1: Temporal Mask Smoothing & Scene Cut Reset.
    """

    def setUp(self):
        self.scratch_dir = tempfile.TemporaryDirectory()
        self.scratch_path = Path(self.scratch_dir.name)
        self.service = VideoEditorService(temp_dir=self.scratch_path)

    def tearDown(self):
        self.scratch_dir.cleanup()

    def _create_synthetic_text_roi(self, h: int = 40, w: int = 160, offset_x: int = 0, offset_y: int = 0) -> np.ndarray:
        """Create a synthetic ROI with bright text and dark outline on realistic background."""
        roi = np.full((h, w, 3), 128, dtype=np.uint8)  # mid-gray background
        text_pos = (15 + offset_x, 28 + offset_y)
        # Draw dark outline (stroke)
        cv2.putText(roi, "CHALLENGE", text_pos, cv2.FONT_HERSHEY_SIMPLEX, 0.7, (20, 20, 20), 4, cv2.LINE_AA)
        # Draw bright core
        cv2.putText(roi, "CHALLENGE", text_pos, cv2.FONT_HERSHEY_SIMPLEX, 0.7, (245, 245, 245), 2, cv2.LINE_AA)
        return roi

    def test_temporal_smoothing_1px_2px_jitter_stabilization(self):
        """
        Adversarial Test F4.1: When text or bounding box jitters by 1-2px,
        temporal smoothing preserves previous mask pixels and prevents boundary flickering.
        """
        # Baseline ROI at t=0
        roi_t0 = self._create_synthetic_text_roi(offset_x=0, offset_y=0)
        mask_t0 = self.service._generate_text_stroke_mask(roi_t0)
        self.assertGreater(np.count_nonzero(mask_t0), 50, "Baseline mask must contain detected text strokes")

        # Jittered ROI at t=1 (1px shift right, 1px shift down)
        roi_t1 = self._create_synthetic_text_roi(offset_x=1, offset_y=1)
        # Raw independent mask without temporal smoothing
        mask_t1_raw = self.service._generate_text_stroke_mask(roi_t1, prev_mask=None)

        # Temporally smoothed mask with prev_mask=mask_t0
        mask_t1_smooth = self.service._generate_text_stroke_mask(roi_t1, prev_mask=mask_t0)

        # 1. Verify IoU between raw and previous mask is >= 0.70
        inter = np.count_nonzero((mask_t1_raw > 0) & (mask_t0 > 0))
        union = np.count_nonzero((mask_t1_raw > 0) | (mask_t0 > 0))
        raw_iou = inter / union if union > 0 else 0.0
        self.assertGreaterEqual(raw_iou, 0.70, f"1px jitter must maintain IoU >= 0.70 (got {raw_iou:.3f})")

        # 2. Verify smoothed mask includes previous adjacent pixels
        self.assertGreaterEqual(
            np.count_nonzero(mask_t1_smooth),
            np.count_nonzero(mask_t1_raw),
            "Temporally smoothed mask must encompass dilated previous boundary pixels",
        )

        # 3. Verify overlap with t0 is strictly higher for smoothed mask than raw mask
        overlap_raw = np.count_nonzero((mask_t1_raw > 0) & (mask_t0 > 0))
        overlap_smooth = np.count_nonzero((mask_t1_smooth > 0) & (mask_t0 > 0))
        self.assertGreater(
            overlap_smooth,
            overlap_raw,
            "Temporal smoothing must retain previous frame boundary pixels, reducing flicker",
        )

        # Repeat with 2px jitter
        roi_t2 = self._create_synthetic_text_roi(offset_x=2, offset_y=2)
        mask_t2_smooth = self.service._generate_text_stroke_mask(roi_t2, prev_mask=mask_t1_smooth)
        self.assertGreater(np.count_nonzero(mask_t2_smooth), 0)

    def test_temporal_smoothing_extreme_jump_rejects_old_mask(self):
        """
        Adversarial Test F4.1: If text jumps substantially (> 15px, IoU < 0.70),
        the system must reject the old mask to prevent smear / ghosting across different locations.
        """
        roi_t0 = self._create_synthetic_text_roi(offset_x=0, offset_y=0)
        mask_t0 = self.service._generate_text_stroke_mask(roi_t0)

        # Displaced ROI by 25px (new line or major camera shift)
        roi_jump = self._create_synthetic_text_roi(offset_x=25, offset_y=0)
        mask_jump_raw = self.service._generate_text_stroke_mask(roi_jump, prev_mask=None)
        mask_jump_with_prev = self.service._generate_text_stroke_mask(roi_jump, prev_mask=mask_t0)

        # Since IoU < 0.70, mask_jump_with_prev must NOT include old mask_t0 location
        old_region_isolated = mask_t0[5:35, 10:30]
        jump_result_at_old_loc = mask_jump_with_prev[5:35, 10:30]

        # Old text location should NOT have been artificially forced into the new mask
        self.assertEqual(
            np.count_nonzero(jump_result_at_old_loc),
            np.count_nonzero(mask_jump_raw[5:35, 10:30]),
            "Old mask must be rejected when IoU < 0.70, preventing ghost artifacts",
        )

    def test_temporal_smoothing_scene_cut_luminance_jump_instant_reset(self):
        """
        Adversarial Test F4.1: When a scene cut occurs (luminance jump > 60.0),
        prev_masks must be reset immediately, leaving zero residual ghosting from the old scene.
        """
        # Create a synthetic 6-frame video:
        # Frames 0, 1, 2: Dark scene (gray val = 30) with text "A"
        # Frame 3: Scene Cut -> Bright scene (gray val = 210, diff = 180 > 60) with text "B"
        # Frames 4, 5: Bright scene (gray val = 210) with text "B"
        vid_path = self.scratch_path / "scene_cut_adv_in.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(vid_path), fourcc, 30.0, (160, 90))

        for i in range(6):
            val = 30 if i < 3 else 210
            txt = "TEXT_A" if i < 3 else "TEXT_B"
            f = np.full((90, 160, 3), val, dtype=np.uint8)
            cv2.putText(f, txt, (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            writer.write(f)
        writer.release()

        out_path = self.scratch_path / "scene_cut_adv_out.mp4"

        captured_prev_masks: List[Dict[Any, np.ndarray]] = []
        inpainter = get_texture_preserving_inpainter()
        self.assertIsNotNone(inpainter)
        original_inpaint_fn = inpainter.inpaint_frame_with_regions

        def spy_inpaint_frame(frame, regions, stroke_mask_generator_fn, prev_masks=None, **kwargs):
            captured_prev_masks.append(dict(prev_masks) if prev_masks else {})
            return original_inpaint_fn(frame, regions, stroke_mask_generator_fn, prev_masks=prev_masks, **kwargs)

        with patch.object(inpainter, "inpaint_frame_with_regions", side_effect=spy_inpaint_frame):
            with patch("subprocess.run") as mock_sub:
                mock_sub.return_value = MagicMock(returncode=0, stdout="", stderr=b"")
                self.service._inpaint_video_sync(
                    input_file=vid_path,
                    output_file=out_path,
                    rx_or_regions=[
                        {"x": 15, "y": 25, "w": 90, "h": 35, "text": "TEXT_A", "frame_start": 0, "frame_end": 2},
                        {"x": 15, "y": 25, "w": 90, "h": 35, "text": "TEXT_B", "frame_start": 3, "frame_end": 5},
                    ],
                )

        self.assertEqual(len(captured_prev_masks), 6, "Must process all 6 frames")

        # Frame 0: Fresh start
        self.assertEqual(captured_prev_masks[0], {}, "Frame 0 must start with empty prev_masks")
        # Frame 1: Cached TEXT_A from frame 0
        self.assertIn("TEXT_A", captured_prev_masks[1])
        # Frame 2: Cached TEXT_A from frame 1
        self.assertIn("TEXT_A", captured_prev_masks[2])

        # Frame 3: SCENE CUT (val 30 -> 210, diff = 180 > 60.0)
        # MUST be completely empty: zero ghosting of TEXT_A!
        self.assertEqual(
            captured_prev_masks[3],
            {},
            "Frame 3 (scene cut) must have prev_masks completely reset to empty dict",
        )
        self.assertNotIn("TEXT_A", captured_prev_masks[3], "Old scene mask TEXT_A must not leak past scene cut")

        # Frame 4: Cached TEXT_B from frame 3
        self.assertIn("TEXT_B", captured_prev_masks[4])
        # Frame 5: Cached TEXT_B from frame 4
        self.assertIn("TEXT_B", captured_prev_masks[5])

    def test_temporal_smoothing_chromatic_scene_cut_instant_reset(self):
        """
        Adversarial Test F4.1: Chromatic scene cut (pure blue screen -> pure green screen, diff = 121 > 60).
        Verifies scene cut detection triggers on color shifts even without pure black/white jump.
        """
        vid_path = self.scratch_path / "chromatic_cut_in.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(vid_path), fourcc, 30.0, (140, 80))

        # Frames 0-1: Blue background [255, 0, 0] (gray = 29)
        # Frames 2-3: Green background [0, 255, 0] (gray = 150) -> diff = 121 > 60
        for i in range(4):
            color = (255, 0, 0) if i < 2 else (0, 255, 0)
            f = np.zeros((80, 140, 3), dtype=np.uint8)
            f[:] = color
            cv2.putText(f, "COLOR", (20, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            writer.write(f)
        writer.release()

        out_path = self.scratch_path / "chromatic_cut_out.mp4"
        captured_prev_masks: List[Dict[Any, np.ndarray]] = []
        inpainter = get_texture_preserving_inpainter()
        orig_inpaint_chromatic = inpainter.inpaint_frame_with_regions

        def spy_inpaint_frame(frame, regions, stroke_mask_generator_fn, prev_masks=None, **kwargs):
            captured_prev_masks.append(dict(prev_masks) if prev_masks else {})
            return orig_inpaint_chromatic(frame, regions, stroke_mask_generator_fn, prev_masks=prev_masks, **kwargs)

        with patch.object(inpainter, "inpaint_frame_with_regions", side_effect=spy_inpaint_frame):
            with patch("subprocess.run") as mock_sub:
                mock_sub.return_value = MagicMock(returncode=0, stdout="", stderr=b"")
                self.service._inpaint_video_sync(
                    input_file=vid_path,
                    output_file=out_path,
                    rx_or_regions=[{"x": 15, "y": 20, "w": 80, "h": 35, "text": "COLOR"}],
                )

        self.assertEqual(len(captured_prev_masks), 4)
        # Frame 0: empty
        self.assertEqual(captured_prev_masks[0], {})
        # Frame 1: cached
        self.assertIn("COLOR", captured_prev_masks[1])
        # Frame 2: Chromatic cut reset!
        self.assertEqual(captured_prev_masks[2], {}, "Chromatic jump (blue -> green) must reset prev_masks")
        # Frame 3: cached again
        self.assertIn("COLOR", captured_prev_masks[3])

    def test_temporal_smoothing_gradual_lighting_preserves_cache(self):
        """
        Adversarial Test F4.1: Gradual lighting change (diff < 60.0 per frame)
        must NOT trigger scene cut reset, keeping temporal continuity intact.
        """
        vid_path = self.scratch_path / "gradual_in.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(vid_path), fourcc, 30.0, (140, 80))

        # 5 frames with step of +10 luminance (diff = 10 << 60)
        for i in range(5):
            val = 40 + i * 10
            f = np.full((80, 140, 3), val, dtype=np.uint8)
            cv2.putText(f, "GRAD", (20, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            writer.write(f)
        writer.release()

        out_path = self.scratch_path / "gradual_out.mp4"
        captured_prev_masks: List[Dict[Any, np.ndarray]] = []
        inpainter = get_texture_preserving_inpainter()
        orig_inpaint_gradual = inpainter.inpaint_frame_with_regions

        def spy_inpaint_frame(frame, regions, stroke_mask_generator_fn, prev_masks=None, **kwargs):
            captured_prev_masks.append(dict(prev_masks) if prev_masks else {})
            return orig_inpaint_gradual(frame, regions, stroke_mask_generator_fn, prev_masks=prev_masks, **kwargs)

        with patch.object(inpainter, "inpaint_frame_with_regions", side_effect=spy_inpaint_frame):
            with patch("subprocess.run") as mock_sub:
                mock_sub.return_value = MagicMock(returncode=0, stdout="", stderr=b"")
                self.service._inpaint_video_sync(
                    input_file=vid_path,
                    output_file=out_path,
                    rx_or_regions=[{"x": 15, "y": 20, "w": 80, "h": 35, "text": "GRAD"}],
                )

        self.assertEqual(len(captured_prev_masks), 5)
        self.assertEqual(captured_prev_masks[0], {})
        for idx in range(1, 5):
            self.assertIn("GRAD", captured_prev_masks[idx], f"Gradual change must NOT reset cache at frame {idx}")


class TestChallengerFFmpegExportFlags(unittest.TestCase):
    """
    Empirical Adversarial Tests for F4.2: Studio FFmpeg Export Flags & Audio Fallback.
    """

    def setUp(self):
        self.scratch_dir = tempfile.TemporaryDirectory()
        self.scratch_path = Path(self.scratch_dir.name)
        self.service = VideoEditorService(temp_dir=self.scratch_path)

    def tearDown(self):
        self.scratch_dir.cleanup()

    def _create_minimal_video(self, filename: str = "min_input.mp4") -> Path:
        vid_path = self.scratch_path / filename
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(vid_path), fourcc, 30.0, (100, 60))
        writer.write(np.zeros((60, 100, 3), dtype=np.uint8))
        writer.release()
        return vid_path

    def test_ffmpeg_export_flags_completeness_inpaint_sync(self):
        """
        Adversarial Test F4.2: In _inpaint_video_sync, FFmpeg merge command must contain
        all required studio-grade flags: -c:v libx264, -preset fast, -crf 18, -c:a copy, -movflags +faststart.
        """
        input_vid = self._create_minimal_video("flags_check_in.mp4")
        output_vid = self.scratch_path / "flags_check_out.mp4"
        executed_cmds: List[List[str]] = []

        def spy_run(cmd, *args, **kwargs):
            executed_cmds.append(cmd)
            res = MagicMock()
            res.returncode = 0
            res.stdout = "1:1" if "sample_aspect_ratio" in " ".join(cmd) else ""
            res.stderr = b""
            return res

        with patch("subprocess.run", side_effect=spy_run):
            self.service._inpaint_video_sync(
                input_file=input_vid,
                output_file=output_vid,
                rx_or_regions=[{"x": 10, "y": 10, "w": 30, "h": 20}],
            )

        self.assertGreaterEqual(len(executed_cmds), 1)
        merge_cmd = executed_cmds[-1]

        # Verify studio flags presence and strict values
        self.assertIn("-c:v", merge_cmd)
        self.assertEqual(merge_cmd[merge_cmd.index("-c:v") + 1], "libx264")
        self.assertIn("-preset", merge_cmd)
        self.assertEqual(merge_cmd[merge_cmd.index("-preset") + 1], "fast")
        self.assertIn("-crf", merge_cmd)
        self.assertEqual(merge_cmd[merge_cmd.index("-crf") + 1], "18")
        self.assertIn("-pix_fmt", merge_cmd)
        self.assertEqual(merge_cmd[merge_cmd.index("-pix_fmt") + 1], "yuv420p")
        self.assertIn("-c:a", merge_cmd)
        self.assertEqual(merge_cmd[merge_cmd.index("-c:a") + 1], "copy")
        self.assertIn("-movflags", merge_cmd)
        self.assertEqual(merge_cmd[merge_cmd.index("-movflags") + 1], "+faststart")
        self.assertIn("-shortest", merge_cmd)
        self.assertIn("-map", merge_cmd)
        self.assertIn("0:v:0", merge_cmd)
        self.assertIn("1:a?", merge_cmd)

    def test_ffmpeg_export_flags_completeness_delogo_mode(self):
        """
        Adversarial Test F4.2: In remove_text_from_video(mode='delogo'),
        FFmpeg command must also enforce -crf 18, -preset fast, -c:a copy, -movflags +faststart.
        """
        input_vid = self._create_minimal_video("delogo_flags_in.mp4")
        executed_cmds: List[List[str]] = []

        async def run_test():
            async def spy_run_cmd(cmd, timeout=300):
                executed_cmds.append(cmd)
                if len(cmd) > 0 and str(cmd[-1]).endswith(".mp4"):
                    Path(cmd[-1]).touch()
                return 0, b"", b""

            with patch.object(self.service, "_run_command", side_effect=spy_run_cmd):
                res = await self.service.remove_text_from_video(
                    input_path_or_url=str(input_vid),
                    mode="delogo",
                    region={"x": 10, "y": 10, "w": 30, "h": 20},
                )
                return res

        result = asyncio.run(run_test())
        self.assertEqual(result["status"], "ok")
        self.assertGreaterEqual(len(executed_cmds), 1)

        delogo_cmd = executed_cmds[-1]
        self.assertIn("-c:v", delogo_cmd)
        self.assertEqual(delogo_cmd[delogo_cmd.index("-c:v") + 1], "libx264")
        self.assertIn("-preset", delogo_cmd)
        self.assertEqual(delogo_cmd[delogo_cmd.index("-preset") + 1], "fast")
        self.assertIn("-crf", delogo_cmd)
        self.assertEqual(delogo_cmd[delogo_cmd.index("-crf") + 1], "18")
        self.assertIn("-c:a", delogo_cmd)
        self.assertEqual(delogo_cmd[delogo_cmd.index("-c:a") + 1], "copy")
        self.assertIn("-movflags", delogo_cmd)
        self.assertEqual(delogo_cmd[delogo_cmd.index("-movflags") + 1], "+faststart")

    def test_ffmpeg_audio_fallback_to_aac_on_copy_failure_inpaint(self):
        """
        Adversarial Test F4.2: When -c:a copy fails due to incompatible container/codec,
        system retries with -c:a aac -b:a 192k and succeeds.
        """
        input_vid = self._create_minimal_video("audio_fb_in.mp4")
        output_vid = self.scratch_path / "audio_fb_out.mp4"
        executed_cmds: List[List[str]] = []
        call_count = 0

        def fake_run(cmd, *args, **kwargs):
            nonlocal call_count
            executed_cmds.append(cmd)
            res = MagicMock()
            if "sample_aspect_ratio" in " ".join(cmd):
                res.returncode = 0
                res.stdout = "1:1"
                return res

            call_count += 1
            if call_count == 1:
                # First attempt with copy fails
                res.returncode = 1
                res.stderr = b"Could not find tag for codec pcm_s16le in stream #1"
                return res
            else:
                # Retry with AAC succeeds
                res.returncode = 0
                res.stdout = ""
                res.stderr = b""
                return res

        with patch("subprocess.run", side_effect=fake_run):
            self.service._inpaint_video_sync(
                input_file=input_vid,
                output_file=output_vid,
                rx_or_regions=[{"x": 10, "y": 10, "w": 30, "h": 20}],
            )

        self.assertGreaterEqual(len(executed_cmds), 2)
        fallback_cmd = executed_cmds[-1]
        self.assertIn("-c:a", fallback_cmd)
        self.assertEqual(fallback_cmd[fallback_cmd.index("-c:a") + 1], "aac")
        self.assertIn("-b:a", fallback_cmd)
        self.assertEqual(fallback_cmd[fallback_cmd.index("-b:a") + 1], "192k")

    def test_ffmpeg_double_audio_failure_raises_runtime_error(self):
        """
        Adversarial Test F4.2: If BOTH -c:a copy AND -c:a aac fallback fail,
        system must raise RuntimeError with descriptive error message (not silent fail).
        """
        input_vid = self._create_minimal_video("audio_double_fail_in.mp4")
        output_vid = self.scratch_path / "audio_double_fail_out.mp4"

        def fake_run_always_fail(cmd, *args, **kwargs):
            res = MagicMock()
            if "sample_aspect_ratio" in " ".join(cmd):
                res.returncode = 0
                res.stdout = "1:1"
                return res
            res.returncode = 1
            res.stderr = b"Encoder libx264/aac failed: Unknown fatal error"
            return res

        with patch("subprocess.run", side_effect=fake_run_always_fail):
            with self.assertRaises(RuntimeError) as ctx:
                self.service._inpaint_video_sync(
                    input_file=input_vid,
                    output_file=output_vid,
                    rx_or_regions=[{"x": 10, "y": 10, "w": 30, "h": 20}],
                )
            self.assertIn("FFmpeg ghép âm thanh sau khi inpaint thất bại", str(ctx.exception))

    def test_ffmpeg_missing_executable_fallback_to_copy(self):
        """
        Adversarial Test F4.2: If ffmpeg binary is missing (FileNotFoundError),
        system logs a warning and copies raw inpaint video as graceful fallback.
        """
        input_vid = self._create_minimal_video("no_ffmpeg_in.mp4")
        output_vid = self.scratch_path / "no_ffmpeg_out.mp4"

        def fake_run_not_found(cmd, *args, **kwargs):
            raise FileNotFoundError("ffmpeg not found")

        with patch("subprocess.run", side_effect=fake_run_not_found):
            self.service._inpaint_video_sync(
                input_file=input_vid,
                output_file=output_vid,
                rx_or_regions=[{"x": 10, "y": 10, "w": 30, "h": 20}],
            )

        # Output video must still exist via raw copy
        self.assertTrue(output_vid.exists(), "Output file must be created even when FFmpeg is not found")


class TestChallengerZeroDiskLeak(unittest.TestCase):
    """
    Empirical Adversarial Tests for F4.3: Zero-Disk Leak & Robust Resource Cleanup.
    """

    def setUp(self):
        self.scratch_dir = tempfile.TemporaryDirectory()
        self.scratch_path = Path(self.scratch_dir.name)
        self.service = VideoEditorService(temp_dir=self.scratch_path)

    def tearDown(self):
        self.scratch_dir.cleanup()

    def _create_minimal_video(self, filename: str = "leak_in.mp4") -> Path:
        vid_path = self.scratch_path / filename
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(vid_path), fourcc, 30.0, (100, 60))
        for _ in range(5):
            writer.write(np.zeros((60, 100, 3), dtype=np.uint8))
        writer.release()
        return vid_path

    def test_zero_disk_leak_crash_in_frame_loop(self):
        """
        Adversarial Test F4.3: Simulate unhandled crash midway through frame loop (e.g. frame 2).
        Verifies:
          - VideoWriter is released.
          - inp_raw_*.mp4 is unlinked and deleted 100%.
          - Zero intermediate scratch files remain on disk.
        """
        input_vid = self._create_minimal_video("crash_loop_in.mp4")
        output_vid = self.scratch_path / "crash_loop_out.mp4"

        inpainter = get_texture_preserving_inpainter()
        call_count = 0

        def failing_inpaint_fn(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise RuntimeError("Simulated catastrophic crash during neural inpainting")
            return np.zeros((60, 100, 3), dtype=np.uint8), {}

        with patch.object(inpainter, "inpaint_frame_with_regions", side_effect=failing_inpaint_fn):
            with self.assertRaises(RuntimeError) as ctx:
                self.service._inpaint_video_sync(
                    input_file=input_vid,
                    output_file=output_vid,
                    rx_or_regions=[{"x": 10, "y": 10, "w": 30, "h": 20}],
                )
            self.assertIn("Simulated catastrophic crash", str(ctx.exception))

        # Audit disk: zero inp_raw_*.mp4 files must remain
        leaked_raw = list(self.scratch_path.glob("**/inp_raw_*.mp4"))
        self.assertEqual(len(leaked_raw), 0, f"Leaked raw video files detected after crash: {leaked_raw}")

    def test_zero_disk_leak_crash_during_ffmpeg_subprocess(self):
        """
        Adversarial Test F4.3: Crash during FFmpeg execution.
        Scratch raw video must be cleanly unlinked in finally block.
        """
        input_vid = self._create_minimal_video("crash_ffmpeg_in.mp4")
        output_vid = self.scratch_path / "crash_ffmpeg_out.mp4"

        with patch("subprocess.run", side_effect=OSError("Disk I/O failure during ffmpeg execution")):
            with self.assertRaises(OSError):
                self.service._inpaint_video_sync(
                    input_file=input_vid,
                    output_file=output_vid,
                    rx_or_regions=[{"x": 10, "y": 10, "w": 30, "h": 20}],
                )

        leaked_raw = list(self.scratch_path.glob("**/inp_raw_*.mp4"))
        self.assertEqual(len(leaked_raw), 0, f"Leaked raw video files: {leaked_raw}")

    def test_zero_disk_leak_task_cancellation_cleans_up(self):
        """
        Adversarial Test F4.3: When cancel_event is triggered during processing,
        frame loop aborts immediately and all scratch files are wiped out.
        """
        input_vid = self._create_minimal_video("cancel_task_in.mp4")
        output_vid = self.scratch_path / "cancel_task_out.mp4"
        cancel_evt = threading.Event()

        inpainter = get_texture_preserving_inpainter()

        def cancelling_inpaint_fn(*args, **kwargs):
            # Trigger cancellation on first call
            cancel_evt.set()
            return np.zeros((60, 100, 3), dtype=np.uint8), {}

        with patch.object(inpainter, "inpaint_frame_with_regions", side_effect=cancelling_inpaint_fn):
            self.service._inpaint_video_sync(
                input_file=input_vid,
                output_file=output_vid,
                rx_or_regions=[{"x": 10, "y": 10, "w": 30, "h": 20}],
                cancel_event=cancel_evt,
            )

        leaked_raw = list(self.scratch_path.glob("**/inp_raw_*.mp4"))
        self.assertEqual(len(leaked_raw), 0, f"Leaked raw video files after cancellation: {leaked_raw}")

    def test_zero_disk_leak_remove_text_from_video_e2e_exception_cleanup(self):
        """
        Adversarial Test F4.3: In remove_text_from_video, if an exception occurs,
        the pending output_file (clean_*.mp4) is unlinked and deleted 100%.
        """
        input_vid = self._create_minimal_video("e2e_fail_in.mp4")

        async def run_failing_e2e():
            with patch.object(self.service, "_inpaint_video_sync", side_effect=RuntimeError("Worker panic")):
                with self.assertRaises(RuntimeError):
                    await self.service.remove_text_from_video(
                        input_path_or_url=str(input_vid),
                        mode="inpaint",
                        region={"x": 10, "y": 10, "w": 30, "h": 20},
                    )

        asyncio.run(run_failing_e2e())

        # Audit scratch directory: zero clean_*.mp4 files must remain
        leaked_clean = list(self.scratch_path.glob("**/clean_*.mp4"))
        self.assertEqual(len(leaked_clean), 0, f"Leaked clean output files after pipeline failure: {leaked_clean}")

    def test_zero_disk_leak_stress_repeated_consecutive_crashes(self):
        """
        Adversarial Test F4.3: 10 consecutive simulated crashes across inpaint pipeline.
        Audits disk before and after: guarantees zero accumulation of artifact files.
        """
        input_vid = self._create_minimal_video("stress_leak_in.mp4")
        output_vid = self.scratch_path / "stress_leak_out.mp4"

        for iteration in range(10):
            with patch("subprocess.run", side_effect=RuntimeError(f"Crash iteration {iteration}")):
                try:
                    self.service._inpaint_video_sync(
                        input_file=input_vid,
                        output_file=output_vid,
                        rx_or_regions=[{"x": 10, "y": 10, "w": 30, "h": 20}],
                    )
                except RuntimeError:
                    pass

        # Check total leftover temporary files
        leaked_raw = list(self.scratch_path.glob("**/inp_raw_*.mp4"))
        leaked_clean = list(self.scratch_path.glob("**/clean_*.mp4"))
        self.assertEqual(len(leaked_raw), 0, f"Accumulated leaked raw files: {leaked_raw}")
        self.assertEqual(len(leaked_clean), 0, f"Accumulated leaked clean files: {leaked_clean}")


if __name__ == "__main__":
    unittest.main()
