# -*- coding: utf-8 -*-
"""
services/ai-agent-service/tests/test_video_text_removal_regression.py
Regression Test Suite for Video Text Removal Architecture & AV Integrity (Milestone M4 Iteration 2).

Verifies the fix for critical architectural defects discovered by Challenger m4_2:
1. `test_video_job_context_does_not_register_or_delete_output_file`:
   Guarantees `VideoJobContext` NEVER registers `output_file` into `RemoteSessionRegistry.temp_files`.
   When `context.cleanup()` executes, `output_file` remains intact on disk while transient files are unlinked.
2. `test_remove_text_streaming_pipeline_preserves_output_file`:
   Guarantees `_remove_text_streaming_pipeline_sync` preserves `output_file` upon successful completion.
   The `finally:` block cleans up only local caches and never deletes the deliverable target video.
3. `test_remove_text_from_video_e2e_hybrid_success`:
   Guarantees public `remove_text_from_video` executes the high-grade hybrid streaming pipeline,
   returns `mode_used != "inpaint_fallback_legacy"`, and outputs a decodable video with 100% bit-exact audio (C7).

Designed for 100% offline, deterministic CI execution with synthetic media fixtures.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure service root and repo root are in sys.path
_cur = Path(__file__).resolve()
_svc_root = None
_repo_root = None
for _p in [_cur.parent] + list(_cur.parents):
    if (_p / "app").is_dir() and (_p / "requirements.txt").is_file():
        _svc_root = _p
    if (_p / "services" / "ai-agent-service").is_dir() and (_p / "tools" / "acceptance").is_dir():
        _repo_root = _p
        break

if _svc_root and str(_svc_root) not in sys.path:
    sys.path.insert(0, str(_svc_root))
if _repo_root and str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

import cv2
import numpy as np

from app.services.session_lifecycle_manager import get_session_registry
from app.services.video_editor_service import VideoEditorService, VideoJobContext

try:
    from tools.acceptance.metrics import evaluate_c7_av_integrity
except ImportError:
    evaluate_c7_av_integrity = None


class TestVideoTextRemovalRegression(unittest.IsolatedAsyncioTestCase):
    """Regression test suite preventing premature output deletion and silent legacy fallback."""

    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.scratch_path = Path(self.test_dir.name)
        self.service = VideoEditorService(temp_dir=self.scratch_path)

    def tearDown(self):
        try:
            self.test_dir.cleanup()
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────────────────
    # SYNTHETIC VIDEO & AUDIO FIXTURE GENERATORS
    # ──────────────────────────────────────────────────────────────────────────

    def _create_synthetic_video_with_audio(
        self,
        filename: str = "test_synthetic.mp4",
        width: int = 320,
        height: int = 180,
        fps: float = 30.0,
        num_frames: int = 30,
        has_text_overlay: bool = True,
        include_audio: bool = True,
    ) -> Path:
        """
        Generates a lightweight, deterministic synthetic MP4 video with text overlay and AAC audio track.
        Runs purely with OpenCV and FFmpeg lavfi sine audio generator.
        """
        raw_vid_path = self.scratch_path / f"raw_{filename}"
        final_vid_path = self.scratch_path / filename

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(raw_vid_path), fourcc, fps, (width, height))

        for f_idx in range(num_frames):
            # Dynamic gradient background
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            x_shift = int((f_idx * 3) % width)
            frame[:, :, 0] = np.linspace(20, 180, width, dtype=np.uint8)
            frame[:, :, 1] = np.linspace(180, 40, height, dtype=np.uint8)[:, np.newaxis]
            frame[:, :, 2] = np.roll(np.linspace(50, 220, width, dtype=np.uint8), x_shift)

            if has_text_overlay:
                # Add text subtitle with dark border and bright core
                text = "REGRESSION TEST"
                pos = (int(width * 0.15), int(height * 0.60))
                cv2.putText(frame, text, pos, cv2.FONT_HERSHEY_SIMPLEX, 0.6, (10, 10, 10), 3, cv2.LINE_AA)
                cv2.putText(frame, text, pos, cv2.FONT_HERSHEY_SIMPLEX, 0.6, (245, 245, 245), 1, cv2.LINE_AA)

            writer.write(frame)
        writer.release()

        # Check if ffmpeg is available for audio multiplexing
        ffmpeg_bin = shutil.which("ffmpeg")
        if include_audio and ffmpeg_bin:
            dur = num_frames / fps
            temp_audio = self.scratch_path / f"sine_{filename}.aac"
            cmd_audio = [
                ffmpeg_bin, "-y", "-v", "error",
                "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur:.3f}",
                "-c:a", "aac", "-b:a", "128k", str(temp_audio),
            ]
            subprocess.run(cmd_audio, check=True, timeout=15)

            cmd_mux = [
                ffmpeg_bin, "-y", "-v", "error",
                "-i", str(raw_vid_path), "-i", str(temp_audio),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy",
                "-movflags", "+faststart", str(final_vid_path),
            ]
            subprocess.run(cmd_mux, check=True, timeout=20)
            raw_vid_path.unlink(missing_ok=True)
            temp_audio.unlink(missing_ok=True)
        else:
            # Fallback to plain video if ffmpeg is absent
            if raw_vid_path.exists():
                shutil.move(str(raw_vid_path), str(final_vid_path))

        return final_vid_path

    # ──────────────────────────────────────────────────────────────────────────
    # TEST CASE 1: VideoJobContext Lifecycle Safety
    # ──────────────────────────────────────────────────────────────────────────

    def test_video_job_context_does_not_register_or_delete_output_file(self):
        """
        Verify that VideoJobContext does NOT register `output_file` into RemoteSessionRegistry.temp_files.
        When `context.cleanup()` executes, `output_file` remains intact while transient files are cleaned.
        """
        in_file = self.scratch_path / "dummy_in.mp4"
        out_file = self.scratch_path / "deliverable_product.mp4"

        # Create dummy target deliverable file on disk
        payload = b"CRITICAL_DELIVERABLE_VIDEO_DATA_DO_NOT_DELETE" * 100
        out_file.write_bytes(payload)
        self.assertTrue(out_file.exists())
        self.assertEqual(out_file.stat().st_size, len(payload))

        # Instantiate VideoJobContext with output_file specified
        context = VideoJobContext(
            input_file=in_file,
            output_file=out_file,
            mode_requested="auto",
        )
        cache_dir = self.scratch_path / f"kf_cache_{context.job_id}"
        cache_dir.mkdir(parents=True, exist_ok=True)
        context.cache_dir = cache_dir

        # Inspect session registry
        registry = get_session_registry()
        session_rec = registry.get_or_create(context.job_id)

        # 1. ASSERTION: output_file must NOT be registered in temp_files
        self.assertNotIn(
            out_file,
            session_rec.temp_files,
            "CRITICAL FLAW: output_file was registered in temp_files! It will be deleted by cleanup().",
        )

        # 2. Register a genuine transient scratch file to verify cleanup works for real temp assets
        transient_file = self.scratch_path / f"transient_scratch_{context.job_id}.tmp"
        transient_file.write_text("transient_content")
        registry.register_temp_path(context.job_id, transient_file, is_dir=False)
        self.assertIn(transient_file, session_rec.temp_files)

        # 3. Execute context.cleanup()
        context.cleanup()

        # 4. ASSERTION: Deliverable output_file MUST remain 100% intact
        self.assertTrue(
            out_file.exists(),
            "REGRESSION BUG: output_file was deleted by context.cleanup()!",
        )
        self.assertEqual(
            out_file.read_bytes(),
            payload,
            "REGRESSION BUG: output_file content was altered or truncated during cleanup()!",
        )

        # 5. ASSERTION: True transient files and cache dirs must be safely removed (Zero-Disk Leak)
        self.assertFalse(transient_file.exists(), "Transient file should have been deleted by cleanup()")
        self.assertFalse(cache_dir.exists(), "Cache dir should have been deleted by cleanup()")

    # ──────────────────────────────────────────────────────────────────────────
    # TEST CASE 2: Streaming Pipeline Output File Preservation
    # ──────────────────────────────────────────────────────────────────────────

    def test_remove_text_streaming_pipeline_preserves_output_file(self):
        """
        Verify that `_remove_text_streaming_pipeline_sync` preserves `output_file` when complete.
        Its `finally:` block must clean only transient caches and never unlink the delivered MP4.
        """
        # Create a small 15-frame input video
        in_video = self._create_synthetic_video_with_audio(
            filename="stream_input.mp4",
            width=160,
            height=120,
            fps=30.0,
            num_frames=15,
            has_text_overlay=True,
            include_audio=False,
        )
        out_video = self.scratch_path / "stream_output.mp4"

        cancel_event = None
        context = VideoJobContext(
            input_file=in_video,
            output_file=out_video,
            mode_requested="auto",
        )
        cache_dir = self.scratch_path / f"kf_cache_{context.job_id}"
        cache_dir.mkdir(parents=True, exist_ok=True)
        context.cache_dir = cache_dir

        target_regions = [{"x": 10, "y": 60, "w": 140, "h": 30}]

        # Run streaming pipeline synchronously
        self.service._remove_text_streaming_pipeline_sync(
            input_file=in_video,
            output_file=out_video,
            progress_callback=None,
            cancel_event=cancel_event,
            target_regions=target_regions,
            enable_critique=False,
            context=context,
            target_scope="overlay",
        )

        # 1. ASSERTION: output_file must exist on disk after completion
        self.assertTrue(
            out_video.exists(),
            "REGRESSION DEFECT: out_video was destroyed by the finally: block of _remove_text_streaming_pipeline_sync!",
        )

        # 2. ASSERTION: output_file must be a valid non-empty media file
        file_size = out_video.stat().st_size
        self.assertGreater(
            file_size,
            1000,
            f"Output file size ({file_size} bytes) is suspiciously small or corrupted.",
        )

        # 3. ASSERTION: Decodable via OpenCV VideoCapture
        cap = cv2.VideoCapture(str(out_video))
        self.assertTrue(cap.isOpened(), "Output video cannot be opened by cv2.VideoCapture")
        fc = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        self.assertGreaterEqual(fc, 14, f"Output video frame count ({fc}) is incomplete")

    # ──────────────────────────────────────────────────────────────────────────
    # TEST CASE 3: Public End-to-End Hybrid Success (No Legacy Fallback & C7 AV Match)
    # ──────────────────────────────────────────────────────────────────────────

    async def test_remove_text_from_video_e2e_hybrid_success(self):
        """
        Verify that public `remove_text_from_video` executes the high-grade hybrid streaming pipeline,
        returns `mode_used != 'inpaint_fallback_legacy'`, does not trigger silent legacy fallback,
        and outputs a playable video preserving 100% bit-exact audio (C7).
        """
        # Create a synthetic video with AAC audio track and text overlay (30 frames, 320x180)
        in_video = self._create_synthetic_video_with_audio(
            filename="e2e_hybrid_input.mp4",
            width=320,
            height=180,
            fps=30.0,
            num_frames=30,
            has_text_overlay=True,
            include_audio=True,
        )

        target_region = {"x": 40, "y": 90, "w": 240, "h": 40}

        # Call public business API remove_text_from_video
        result = await self.service.remove_text_from_video(
            input_path_or_url=str(in_video),
            mode="auto",
            target_scope="overlay",
            region=target_region,
        )

        # 1. ASSERTION: API execution status
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("status"), "ok")

        # 2. CRITICAL ASSERTION: Must NOT fall back to legacy Telea worker!
        is_fallback = result.get("is_fallback", False)
        mode_used = result.get("mode_used", "")
        self.assertFalse(
            is_fallback,
            f"REGRESSION DEFECT: Pipeline fell back unexpectedly! Reason: {result.get('fallback_reason')}",
        )
        self.assertNotEqual(
            mode_used,
            "inpaint_fallback_legacy",
            "CRITICAL DEFECT: mode_used is 'inpaint_fallback_legacy'! The system quietly reverted to Telea.",
        )

        # 3. ASSERTION: Output file exists and is decodable
        out_path = Path(result["output_path"])
        self.assertTrue(out_path.exists(), f"Output file does not exist at {out_path}")
        self.assertGreater(out_path.stat().st_size, 2000)

        cap_in = cv2.VideoCapture(str(in_video))
        cap_out = cv2.VideoCapture(str(out_path))
        src_frames = int(cap_in.get(cv2.CAP_PROP_FRAME_COUNT))
        out_frames = int(cap_out.get(cv2.CAP_PROP_FRAME_COUNT))
        cap_in.release()
        cap_out.release()

        self.assertEqual(
            src_frames,
            out_frames,
            f"Frame count mismatch: input had {src_frames} frames but output has {out_frames} frames!",
        )

        # 4. ASSERTION: Bit-exact audio and A/V integrity (C7)
        if evaluate_c7_av_integrity is not None:
            c7_report = evaluate_c7_av_integrity(in_video, out_path)
            # If source has audio, audio MD5 must match 100%
            if c7_report.get("src_meta", {}).get("has_audio"):
                self.assertTrue(
                    c7_report.get("is_audio_md5_match"),
                    f"C7 VIOLATION: Audio MD5 mismatch! Report: {c7_report}",
                )
            self.assertTrue(
                c7_report.get("frame_count_match"),
                f"C7 VIOLATION: Frame count dropped! Report: {c7_report}",
            )
            self.assertTrue(
                c7_report.get("resolution_match"),
                f"C7 VIOLATION: Resolution mismatch! Report: {c7_report}",
            )


if __name__ == "__main__":
    unittest.main()
