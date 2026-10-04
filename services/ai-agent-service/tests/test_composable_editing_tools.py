"""
Unit tests for the 8 Composable Video/Image Editing Tools (Milestone 2).
Covers OpenAI schema compliance, parameter validation, successful execution, and error handling for:
1. video_probe_tool
2. text_detection_tool
3. mask_generation_tool
4. image_inpaint_tool
5. video_inpaint_tool
6. ffmpeg_process_tool
7. quality_verify_tool
8. temporal_compare_tool
"""

import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import cv2
import numpy as np

from app.services.ai_agent_tools import AgentToolExecutor
from app.services.video_editor_service import VideoEditorService


class TestComposableEditingTools(unittest.IsolatedAsyncioTestCase):
    """Test suite for the 8 Composable Video & Image Editing Tools."""

    def setUp(self):
        self.mock_ssh = MagicMock()
        self.mock_cache = MagicMock()
        self.executor = AgentToolExecutor(ssh_client=self.mock_ssh, message_cache=self.mock_cache)
        self.all_tools = self.executor._build_tools(force_all=True)
        self.tool_map = {t["function"]["name"]: t["function"] for t in self.all_tools}

        # Create temporary working directory for test media
        self.temp_dir = tempfile.TemporaryDirectory()
        self.td_path = Path(self.temp_dir.name)

        # Create synthetic test image
        self.test_img_path = self.td_path / "test_img.png"
        img = np.full((120, 160, 3), 180, dtype=np.uint8)
        cv2.putText(img, "SAMPLE", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
        cv2.imwrite(str(self.test_img_path), img)

        # Create synthetic mask
        self.test_mask_path = self.td_path / "test_mask.png"
        mask = np.zeros((120, 160), dtype=np.uint8)
        mask[40:80, 15:140] = 255
        cv2.imwrite(str(self.test_mask_path), mask)

        # Create synthetic test video (10 frames, 160x120)
        self.test_vid_path = self.td_path / "test_vid.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out_vid = cv2.VideoWriter(str(self.test_vid_path), fourcc, 10.0, (160, 120))
        for i in range(10):
            f = np.full((120, 160, 3), 150 + i * 5, dtype=np.uint8)
            cv2.putText(f, f"F{i}", (30, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            out_vid.write(f)
        out_vid.release()

    def tearDown(self):
        self.temp_dir.cleanup()

    # ─── 1. SCHEMA COMPLIANCE TESTS ──────────────────────────────────────────

    def test_all_8_composable_tools_registered_in_schemas(self):
        """Verify that all 8 tools are registered with proper names and descriptions."""
        expected_tools = [
            "video_probe_tool",
            "text_detection_tool",
            "mask_generation_tool",
            "image_inpaint_tool",
            "video_inpaint_tool",
            "ffmpeg_process_tool",
            "quality_verify_tool",
            "temporal_compare_tool",
        ]
        for name in expected_tools:
            self.assertIn(name, self.tool_map, f"Tool '{name}' must be present in tool registry")
            fn = self.tool_map[name]
            self.assertTrue(bool(fn.get("description")), f"Tool '{name}' must have a description")
            self.assertEqual(fn.get("parameters", {}).get("type"), "object")
            self.assertIsInstance(fn.get("parameters", {}).get("properties"), dict)

    # ─── 2. TOOL 1: video_probe_tool ─────────────────────────────────────────

    async def test_video_probe_tool_valid(self):
        """Verify video_probe_tool extracts metadata accurately on synthetic video."""
        res = await self.executor._execute_tool(
            "video_probe_tool",
            {"video_path": str(self.test_vid_path)},
        )
        self.assertIn("THÔNG SỐ KỸ THUẬT VIDEO", res)
        self.assertIn("160x120", res)
        self.assertIn("fps", res.lower())

    async def test_video_probe_tool_invalid_path(self):
        """Verify video_probe_tool returns error when file does not exist."""
        res = await self.executor._execute_tool(
            "video_probe_tool",
            {"video_path": "/nonexistent/video_path.mp4"},
        )
        self.assertIn("Lỗi", res)

    # ─── 3. TOOL 2: text_detection_tool ──────────────────────────────────────

    async def test_text_detection_tool_valid_image(self):
        """Verify text_detection_tool detects regions on image."""
        res = await self.executor._execute_tool(
            "text_detection_tool",
            {"image_or_video_path": str(self.test_img_path)},
        )
        self.assertIn("KẾT QUẢ QUÉT TEXT", res)

    async def test_text_detection_tool_valid_video(self):
        """Verify text_detection_tool works on video input."""
        res = await self.executor._execute_tool(
            "text_detection_tool",
            {"image_or_video_path": str(self.test_vid_path), "sample_frames": 2},
        )
        self.assertIn("KẾT QUẢ QUÉT TEXT", res)

    async def test_text_detection_tool_invalid_file(self):
        """Verify text_detection_tool handles non-existent file gracefully."""
        res = await self.executor._execute_tool(
            "text_detection_tool",
            {"image_or_video_path": "/missing/file.png"},
        )
        self.assertIn("Lỗi", res)

    # ─── 4. TOOL 3: mask_generation_tool ─────────────────────────────────────

    async def test_mask_generation_tool_valid(self):
        """Verify mask_generation_tool creates binary mask and dilates appropriately."""
        out_mask_path = self.td_path / "gen_mask.png"
        res = await self.executor._execute_tool(
            "mask_generation_tool",
            {
                "dimensions": [160, 120],
                "regions": [{"x": 20, "y": 30, "w": 40, "h": 20}],
                "dilation": 5,
                "output_path": str(out_mask_path),
            },
        )
        self.assertIn("SINH MẶT NẠ INPAINT THÀNH CÔNG", res)
        self.assertTrue(out_mask_path.exists())
        loaded = cv2.imread(str(out_mask_path), cv2.IMREAD_GRAYSCALE)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.shape, (120, 160))
        self.assertGreater(np.count_nonzero(loaded), 0)

    async def test_mask_generation_tool_invalid_dimensions(self):
        """Verify mask_generation_tool raises or returns error on zero/negative dimensions."""
        res = await self.executor._execute_tool(
            "mask_generation_tool",
            {
                "dimensions": [0, -100],
                "regions": [{"x": 10, "y": 10, "w": 10, "h": 10}],
            },
        )
        self.assertIn("Lỗi", res)

    # ─── 5. TOOL 4: image_inpaint_tool ───────────────────────────────────────

    async def test_image_inpaint_tool_valid_with_mock(self):
        """Verify image_inpaint_tool inpaints image and writes output."""
        out_inp_path = self.td_path / "inp_out.png"
        # Mock client to return cleaned ndarray
        with patch("app.services.video_editor_service.get_hosted_inpainter_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.inpaint_roi = AsyncMock(return_value=np.full((120, 160, 3), 180, dtype=np.uint8))
            mock_get_client.return_value = mock_client

            res = await self.executor._execute_tool(
                "image_inpaint_tool",
                {
                    "image_path": str(self.test_img_path),
                    "mask_path": str(self.test_mask_path),
                    "output_path": str(out_inp_path),
                },
            )
            self.assertIn("INPAINT ẢNH THÀNH CÔNG", res)
            self.assertTrue(out_inp_path.exists())

    async def test_image_inpaint_tool_missing_mask_returns_error(self):
        """Verify image_inpaint_tool returns error when mask file is missing."""
        res = await self.executor._execute_tool(
            "image_inpaint_tool",
            {
                "image_path": str(self.test_img_path),
                "mask_path": "/missing/mask.png",
            },
        )
        self.assertIn("Lỗi", res)

    # ─── 6. TOOL 5: video_inpaint_tool ───────────────────────────────────────

    async def test_video_inpaint_tool_valid(self):
        """Verify video_inpaint_tool invokes video inpainting pipeline."""
        with patch.object(self.executor.video_editor_service, "remove_text_from_video", new_callable=AsyncMock) as mock_rm:
            mock_rm.return_value = {
                "status": "ok",
                "mode_used": "inpaint",
                "output_path": str(self.test_vid_path),
                "file_size_formatted": "1.2 MB",
                "delivery": "direct",
            }
            res = await self.executor._execute_tool(
                "video_inpaint_tool",
                {
                    "video_path": str(self.test_vid_path),
                    "target_regions": [{"x": 10, "y": 20, "w": 40, "h": 20}],
                    "method": "inpaint",
                },
            )
            self.assertIn("INPAINT VIDEO THÀNH CÔNG", res)
            mock_rm.assert_called_once()

    # ─── 7. TOOL 6: ffmpeg_process_tool ──────────────────────────────────────

    async def test_ffmpeg_process_tool_cut_clip_valid(self):
        """Verify ffmpeg_process_tool handles cut_clip command."""
        out_cut = self.td_path / "cut.mp4"
        with patch.object(self.executor.video_editor_service, "_run_command", new_callable=AsyncMock) as mock_run:
            async def fake_run(*args, **kwargs):
                out_cut.write_bytes(b"\x00" * 200)
                return (0, b"", b"")
            mock_run.side_effect = fake_run
            res = await self.executor._execute_tool(
                "ffmpeg_process_tool",
                {
                    "command_type": "cut_clip",
                    "input_path": str(self.test_vid_path),
                    "output_path": str(out_cut),
                    "start_time": "00:00:01",
                    "duration": "2",
                },
            )
            self.assertIn("THAO TÁC FFMPEG THÀNH CÔNG", res)

    async def test_ffmpeg_process_tool_invalid_command_type(self):
        """Verify ffmpeg_process_tool rejects unknown command_type."""
        res = await self.executor._execute_tool(
            "ffmpeg_process_tool",
            {
                "command_type": "unsupported_command",
                "input_path": str(self.test_vid_path),
            },
        )
        self.assertIn("Lỗi", res)

    # ─── 8. TOOL 7: quality_verify_tool ──────────────────────────────────────

    async def test_quality_verify_tool_valid(self):
        """Verify quality_verify_tool measures PSNR, SSIM and returns report."""
        res = await self.executor._execute_tool(
            "quality_verify_tool",
            {
                "original_path": str(self.test_img_path),
                "result_path": str(self.test_img_path),
                "sample_frames": 1,
            },
        )
        self.assertIn("QUALITY VERIFY", res)
        self.assertIn("PSNR", res)
        self.assertIn("SSIM", res)

    async def test_quality_verify_tool_missing_file_returns_error(self):
        """Verify quality_verify_tool returns error when original file missing."""
        res = await self.executor._execute_tool(
            "quality_verify_tool",
            {
                "original_path": "/missing/original.mp4",
                "result_path": str(self.test_img_path),
            },
        )
        self.assertIn("Lỗi", res)

    # ─── 9. TOOL 8: temporal_compare_tool ────────────────────────────────────

    async def test_temporal_compare_tool_valid(self):
        """Verify temporal_compare_tool evaluates consistency MAD across frames."""
        out_dir = self.td_path / "artifacts"
        res = await self.executor._execute_tool(
            "temporal_compare_tool",
            {
                "video_path": str(self.test_vid_path),
                "frame_indices": [0, 3, 6],
                "output_dir": str(out_dir),
            },
        )
        self.assertIn("TEMPORAL CONSISTENCY", res)
        self.assertIn("Temporal MAD", res)
        self.assertTrue(out_dir.exists())

    async def test_temporal_compare_tool_missing_video_returns_error(self):
        """Verify temporal_compare_tool returns error when video file is missing."""
        res = await self.executor._execute_tool(
            "temporal_compare_tool",
            {"video_path": "/nonexistent/video.mp4"},
        )
        self.assertIn("Lỗi", res)


if __name__ == "__main__":
    unittest.main()
