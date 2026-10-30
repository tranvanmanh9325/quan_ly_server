# -*- coding: utf-8 -*-
"""
services/ai-agent-service/tests/test_temporal_text_detector.py
Unit Test Suite for TemporalTextDetector and MotionInvarianceClassifier (Milestone M2 - Features 11, 12, 13).
Validates:
1. TemporalTextDetector sliding window edge persistence and color constancy.
2. MotionInvarianceClassifier DIS optical flow velocity vector differentiation (scene vs overlay).
3. Negative Controls Integrity: Zero false positive regions on clean moving texture footage.
4. Scene Text Preservation: Scene text candidate is excluded under default target_scope == 'overlay'.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
import unittest

import cv2
import numpy as np

# Ensure service root and repo root are in path
TEST_DIR = Path(__file__).resolve().parent
SERVICE_ROOT = TEST_DIR.parent
REPO_ROOT = SERVICE_ROOT.parent.parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.services.temporal_text_detector import (
    MotionInvarianceClassifier,
    TemporalTextDetector,
    detect_overlay_text_temporal,
)


class TestTemporalTextDetector(unittest.TestCase):
    """Test Suite for Temporal Text Detection & Motion Invariance Classification."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_temporal_det_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_synthetic_video(
        self,
        filename: str,
        num_frames: int = 30,
        width: int = 320,
        height: int = 240,
        fps: float = 30.0,
        pan_speed: float = 2.0,
        overlay_text: str | None = None,
        scene_text: str | None = None,
    ) -> Path:
        """Create a lightweight synthetic video for testing."""
        video_path = self.temp_dir / filename
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(video_path), fourcc, fps, (width, height))

        # Generate large canvas with texture pattern (e.g., alternating blocks)
        canvas_w = width + int(round(pan_speed * num_frames)) + 50
        canvas_h = height
        canvas = np.full((canvas_h, canvas_w, 3), 160, dtype=np.uint8)

        # Draw mesh-like circular grid simulating textured background
        for y in range(10, canvas_h, 15):
            for x in range(10, canvas_w, 15):
                cv2.circle(canvas, (x, y), 2, (50, 50, 50), -1)

        # If scene text is requested, paint it directly onto canvas before camera motion
        if scene_text:
            cv2.putText(canvas, scene_text, (50, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (20, 20, 20), 2)

        for i in range(num_frames):
            offset_x = int(round(i * pan_speed))
            frame = canvas[:, offset_x : offset_x + width].copy()

            # If overlay text is requested, stamp it onto the screen-fixed coordinates
            if overlay_text:
                cv2.putText(frame, overlay_text, (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

            writer.write(frame)

        writer.release()
        return video_path

    def test_negative_control_clean_moving_texture_returns_zero_regions(self):
        """Negative control (moving mesh texture with no text) must return exactly 0 detected regions."""
        clean_vid = self._create_synthetic_video("clean_mesh.mp4", num_frames=25, pan_speed=2.5, overlay_text=None)
        detector = TemporalTextDetector(window_size=15)
        regions = detector.detect_overlay_text_temporal(clean_vid, target_scope="overlay")

        self.assertEqual(len(regions), 0, f"Expected 0 regions on clean texture, got {len(regions)}: {regions}")

    def test_overlay_text_is_detected(self):
        """Screen-fixed overlay text over moving background must be detected."""
        text_vid = self._create_synthetic_video("overlay_clip.mp4", num_frames=25, pan_speed=2.0, overlay_text="SUBTITLE TEXT")
        detector = TemporalTextDetector(window_size=15)
        regions = detector.detect_overlay_text_temporal(text_vid, target_scope="overlay")

        self.assertGreaterEqual(len(regions), 1, "Expected at least 1 detected overlay region")
        first = regions[0]
        self.assertEqual(first["motion_type"], "overlay")
        self.assertIn("bbox", first)
        self.assertIn("start_sec", first)
        self.assertIn("end_sec", first)

    def test_motion_classifier_distinguishes_scene_vs_overlay(self):
        """Unit test for MotionInvarianceClassifier with synthetic flow fields."""
        classifier = MotionInvarianceClassifier(min_bg_motion=0.50, delta_v_threshold=0.45)

        h, w = 100, 200
        # Scenario A: Scene Text moving in sync with background
        flow_scene = np.zeros((h, w, 2), dtype=np.float32)
        flow_scene[..., 0] = 2.0  # Entire scene moving at u = 2.0 px/frame
        flow_scene[..., 1] = 0.0

        bbox = {"x": 50, "y": 30, "w": 60, "h": 20}
        res_scene = classifier.classify_region_motion(bbox, flow_scene)
        self.assertEqual(res_scene["motion_type"], "scene", "In-sync text must be classified as 'scene'")

        # Scenario B: Overlay Text static while background moves
        flow_overlay = np.zeros((h, w, 2), dtype=np.float32)
        flow_overlay[..., 0] = 2.0  # Background moving at u = 2.0
        # Text region is static (u = 0.0)
        flow_overlay[30:50, 50:110, 0] = 0.0

        res_overlay = classifier.classify_region_motion(bbox, flow_overlay)
        self.assertEqual(res_overlay["motion_type"], "overlay", "Screen-fixed text must be classified as 'overlay'")

    def test_scene_text_excluded_in_overlay_mode(self):
        """Scene text that moves with the background should return 0 regions when target_scope == 'overlay'."""
        scene_vid = self._create_synthetic_video(
            "scene_clip.mp4",
            num_frames=25,
            pan_speed=3.0,
            overlay_text=None,
            scene_text="STORE SIGN",
        )
        detector = TemporalTextDetector(window_size=15)
        regions_overlay = detector.detect_overlay_text_temporal(scene_vid, target_scope="overlay")
        self.assertEqual(len(regions_overlay), 0, "Scene text must not be detected as overlay text")

    def test_convenience_entrypoint(self):
        """Test the module-level detect_overlay_text_temporal entrypoint."""
        clean_vid = self._create_synthetic_video("clean_entry.mp4", num_frames=20, pan_speed=2.0)
        res = detect_overlay_text_temporal(clean_vid, window_size=15, target_scope="overlay")
        self.assertIsInstance(res, list)
        self.assertEqual(len(res), 0)


if __name__ == "__main__":
    unittest.main()
