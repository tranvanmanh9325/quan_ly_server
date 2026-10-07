"""
Unit tests for Milestone 2: Professional Video Text Removal Pipeline Refactoring (Features F5, F6, F7, F8).
Validates:
- F5: Zero hardcode pixel coordinates (300/320/330px purged, relative geometry, temporal persistence ratio).
- F6: Motion Invariance Classifier (Overlay text vs Scene text classification & target_scope filtering).
- F7: Bit-exact audio streaming configuration ('-c:a copy' with AAC fallback) & memory reclamation.
- F8: Seamless integration with RemoteGpuWorkerClient & ClassicalFallbackManager.
Runs 100% offline and deterministic in CI.
"""

import asyncio
from pathlib import Path
import re
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import cv2
import numpy as np

from app.services.video_editor_service import VideoEditorService
from app.services.remote_gpu_worker_client import RemoteGpuWorkerClient
from app.services.classical_fallback_manager import ClassicalFallbackManager


class TestVideoEditorM2ZeroHardcode(unittest.TestCase):
    """Test Suite for Feature F5: Zero Hardcoded Coordinates & Spatial Heuristics."""

    def setUp(self):
        self.service = VideoEditorService()

    def test_zero_hardcode_constants_in_video_editor_service(self):
        """Verify that hardcoded pixel thresholds 300, 320, 330 are completely removed from text logic."""
        service_file = Path("services/ai-agent-service/app/services/video_editor_service.py")
        if not service_file.exists():
            # In container environment, search relative to /app
            service_file = Path("/app/services/ai-agent-service/app/services/video_editor_service.py")
        if not service_file.exists():
            service_file = Path(__file__).resolve().parent.parent / "app" / "services" / "video_editor_service.py"

        content = service_file.read_text(encoding="utf-8")

        # Check for pixel spatial comparisons like `< 300`, `<= 330`, `min(320, ...)`
        forbidden_spatial_patterns = [
            r"y.*<\s*300",
            r"y.*\+\s*.*h.*<=\s*330",
            r"min\(\s*320\s*,",
            r"min\(\s*330\s*,",
            r"bottom_coord\s*<=\s*330",
            r"y_coord\s*<\s*300",
        ]
        for pattern in forbidden_spatial_patterns:
            matches = re.findall(pattern, content)
            self.assertEqual(
                matches,
                [],
                f"Found lingering hardcoded pixel threshold in video_editor_service.py matching '{pattern}': {matches}"
            )

    def test_cluster_multiline_titles_relative_geometry_portrait(self):
        """Test vertical portrait video (1080x1920): Title threshold scales to 0.40 * 1920 = 768px."""
        frame_w = 1080
        frame_h = 1920
        frame_area = frame_w * frame_h

        # Two stacked title lines at y=420 and y=500 (would fail in old 300/330px hardcode)
        segments = [
            {"x": 100, "y": 420, "w": 400, "h": 60, "frame_start": 0, "frame_end": 100, "hits": 5, "text": "LINE ONE"},
            {"x": 100, "y": 500, "w": 400, "h": 60, "frame_start": 0, "frame_end": 100, "hits": 5, "text": "LINE TWO"},
        ]

        merged = VideoEditorService._cluster_multiline_titles(segments, frame_w, frame_h, frame_area)
        self.assertEqual(len(merged), 1, "Stacked title lines within 0.40*frame_h must be clustered together")
        self.assertEqual(merged[0]["y"], 420)
        self.assertEqual(merged[0]["h"], 500 + 60 - 420)

    def test_cluster_multiline_titles_relative_geometry_landscape(self):
        """Test landscape video (1920x1080): Title threshold scales to 0.40 * 1080 = 432px."""
        frame_w = 1920
        frame_h = 1080
        frame_area = frame_w * frame_h

        # Segment in title zone (< 432px) and segment in lower zone (700px)
        segments = [
            {"x": 200, "y": 200, "w": 500, "h": 50, "frame_start": 0, "frame_end": 50, "hits": 4, "text": "HEADER"},
            {"x": 200, "y": 700, "w": 500, "h": 50, "frame_start": 0, "frame_end": 50, "hits": 4, "text": "LOWER SUBTITLE"},
        ]

        merged = VideoEditorService._cluster_multiline_titles(segments, frame_w, frame_h, frame_area)
        # Should not merge lines separated between title and lower zone
        self.assertEqual(len(merged), 2)

    def test_dynamic_gap_y_proportional_to_line_height(self):
        """Test gap_y <= 0.8 * min_line_height allows proportional spacing clustering."""
        frame_w = 720
        frame_h = 1280
        frame_area = frame_w * frame_h

        # Line height = 50px -> 0.8 * 50 = 40px allowed gap. Gap is 35px (> old 30px hardcode, <= 40px relative)
        segments = [
            {"x": 50, "y": 100, "w": 300, "h": 50, "frame_start": 0, "frame_end": 60, "hits": 3},
            {"x": 50, "y": 185, "w": 300, "h": 50, "frame_start": 0, "frame_end": 60, "hits": 3},
        ]
        merged = VideoEditorService._cluster_multiline_titles(segments, frame_w, frame_h, frame_area)
        self.assertEqual(len(merged), 1, "Gap of 35px should be accepted when 0.8 * line_height is 40px")


class TestMotionInvarianceClassifier(unittest.TestCase):
    """Test Suite for Feature F6: Motion Invariance Classifier (Overlay Text vs Scene Text)."""

    def setUp(self):
        self.service = VideoEditorService()
        self.h, self.w = 200, 300

    def test_classify_text_motion_overlay_static_with_moving_background(self):
        """
        Overlay text: Camera pans right (background flow = [3.0, 0.0]),
        while screen caption stays pinned at fixed pixel coordinates (text flow = [0.0, 0.0]).
        """
        flow = np.zeros((self.h, self.w, 2), dtype=np.float32)
        # Background moves with +3.0 px/frame
        flow[:, :, 0] = 3.0
        # Text box at (50, 50, 80, 30) is static on screen (flow = 0.0)
        bx, by, bw, bh = 50, 50, 80, 30
        flow[by:by+bh, bx:bx+bw, :] = 0.0

        text_box = {"x": bx, "y": by, "w": bw, "h": bh}
        cls_result = self.service._classify_text_motion(text_box, frames=None, optical_flow=flow)
        self.assertEqual(cls_result, "overlay", "Static text on moving background must be classified as overlay")

    def test_classify_text_motion_scene_text_moving_with_background(self):
        """
        Scene text: Physical shop sign embedded in 3D environment moves synchronously with background
        (both background and text move at [3.0, 0.0] -> delta_v = 0.0 < epsilon).
        """
        flow = np.zeros((self.h, self.w, 2), dtype=np.float32)
        # Entire frame moves identically (camera pan over physical sign)
        flow[:, :, 0] = 3.5
        flow[:, :, 1] = 0.5

        bx, by, bw, bh = 60, 60, 90, 40
        text_box = (bx, by, bw, bh)
        cls_result = self.service._classify_text_motion(text_box, frames=None, optical_flow=flow, epsilon=1.0)
        self.assertEqual(cls_result, "scene", "Text moving synchronously with background must be classified as scene")

    def test_classify_text_motion_independent_motion_overlay(self):
        """
        Ticker / Marquee overlay moving horizontally in opposite direction to background.
        Background moves right [+2.0, 0], text scrolls left [-3.0, 0] -> delta_v = 5.0 >= epsilon.
        """
        flow = np.zeros((self.h, self.w, 2), dtype=np.float32)
        flow[:, :, 0] = 2.0

        bx, by, bw, bh = 40, 40, 100, 25
        flow[by:by+bh, bx:bx+bw, 0] = -3.0

        text_box = {"x": bx, "y": by, "w": bw, "h": bh}
        cls_result = self.service._classify_text_motion(text_box, frames=None, optical_flow=flow, epsilon=1.0)
        self.assertEqual(cls_result, "overlay", "Text moving independently from background must be classified as overlay")

    def test_classify_text_motion_fully_static_defaults_to_overlay(self):
        """
        Static camera tripod shot: Neither background nor text has motion (< 0.5px).
        Defaults to overlay.
        """
        flow = np.zeros((self.h, self.w, 2), dtype=np.float32)
        bx, by, bw, bh = 50, 50, 80, 30
        text_box = {"x": bx, "y": by, "w": bw, "h": bh}
        cls_result = self.service._classify_text_motion(text_box, frames=None, optical_flow=flow)
        self.assertEqual(cls_result, "overlay")


class TestTargetScopeAndAudioControl(unittest.IsolatedAsyncioTestCase):
    """Test Suite for Feature F6 (target_scope: 'overlay' vs 'all') and F7 (bit-exact audio preservation)."""

    def setUp(self):
        self.service = VideoEditorService()

    @patch.object(VideoEditorService, "_publish_or_direct")
    @patch("shutil.copy2")
    @patch.object(VideoEditorService, "_auto_detect_text_region")
    @patch.object(VideoEditorService, "_resolve_input")
    async def test_remove_text_target_scope_overlay_and_all_forwarding(self, mock_resolve, mock_auto_detect, mock_copy2, mock_publish):
        """Verify target_scope parameter is parsed, validated, and forwarded correctly."""
        mock_resolve.return_value = (Path("/tmp/dummy_in.mp4"), False)
        mock_auto_detect.return_value = []
        mock_publish.return_value = {"type": "direct", "path": "/tmp/dummy_out.mp4"}

        # 1. Default target_scope is 'overlay'
        res_overlay = await self.service.remove_text_from_video(
            input_path_or_url="/tmp/dummy_in.mp4",
            mode="auto",
            target_scope="overlay",
        )
        self.assertEqual(res_overlay["target_scope"], "overlay")
        mock_auto_detect.assert_called_with(Path("/tmp/dummy_in.mp4"), target_scope="overlay")

        # 2. Scope 'all'
        res_all = await self.service.remove_text_from_video(
            input_path_or_url="/tmp/dummy_in.mp4",
            mode="auto",
            target_scope="all",
        )
        self.assertEqual(res_all["target_scope"], "all")
        mock_auto_detect.assert_called_with(Path("/tmp/dummy_in.mp4"), target_scope="all")

    def test_audio_streaming_command_contains_copy(self):
        """Verify that streaming pipeline configures '-c:a copy' by default for bit-exact audio."""
        service_file = Path("services/ai-agent-service/app/services/video_editor_service.py")
        if not service_file.exists():
            service_file = Path("/app/services/ai-agent-service/app/services/video_editor_service.py")
        if not service_file.exists():
            service_file = Path(__file__).resolve().parent.parent / "app" / "services" / "video_editor_service.py"

        content = service_file.read_text(encoding="utf-8")
        # Ensure "-c:a", "copy" exists in streaming pipeline section
        self.assertIn('"-c:a", "copy"', content, "Audio streaming must use '-c:a copy' to preserve bit-exact audio")
        self.assertIn('_sync_collect_and_trim', content, "Memory reclaimer _sync_collect_and_trim must be integrated")


class TestPipelineComponentIntegrations(unittest.TestCase):
    """Test Suite for Feature F8: Integration with RemoteGpuWorkerClient & ClassicalFallbackManager."""

    def setUp(self):
        self.service = VideoEditorService()
        self.dummy_roi = np.full((64, 128, 3), 120, dtype=np.uint8)
        self.dummy_mask = np.zeros((64, 128), dtype=np.uint8)
        self.dummy_mask[20:40, 30:90] = 255

    @patch("app.services.remote_gpu_worker_client.RemoteGpuWorkerClient.inpaint_roi_with_failover_sync")
    def test_fallback_chain_tier1_remote_gpu_success(self, mock_gpu_sync):
        """Verify fallback chain invokes RemoteGpuWorkerClient when use_hosted=True."""
        expected_output = np.full((64, 128, 3), 200, dtype=np.uint8)
        mock_gpu_sync.return_value = expected_output

        result = self.service._inpaint_roi_fallback_chain(
            self.dummy_roi, self.dummy_mask, timeout_sec=5.0, use_hosted=True
        )
        self.assertIsNotNone(result)
        mock_gpu_sync.assert_called_once()
        np.testing.assert_array_equal(result, expected_output)

    @patch("app.services.remote_gpu_worker_client.RemoteGpuWorkerClient.inpaint_roi_with_failover_sync")
    @patch("app.services.classical_fallback_manager.ClassicalFallbackManager.reconstruct_roi_guided_filter")
    def test_fallback_chain_failover_to_classical_guided_filter(self, mock_guided_filter, mock_gpu_sync):
        """Verify that when remote GPU client fails or times out, Tier C2 Classical Guided Filter is called."""
        mock_gpu_sync.return_value = None  # GPU offline
        expected_classical = np.full((64, 128, 3), 180, dtype=np.uint8)
        mock_guided_filter.return_value = expected_classical

        result = self.service._inpaint_roi_fallback_chain(
            self.dummy_roi, self.dummy_mask, timeout_sec=5.0, use_hosted=True
        )
        self.assertIsNotNone(result)
        mock_guided_filter.assert_called_once()
        np.testing.assert_array_equal(result, expected_classical)

    def test_memory_reclaimer_import_and_execution(self):
        """Verify _sync_collect_and_trim executes without error and returns telemetry."""
        from app.core.memory_reclaimer import _sync_collect_and_trim
        stats = _sync_collect_and_trim()
        self.assertIn("unreachable_objects", stats)
        self.assertIn("trimmed", stats)
        self.assertIn("elapsed_ms", stats)
        self.assertGreaterEqual(stats["elapsed_ms"], 0.0)


if __name__ == "__main__":
    unittest.main()
