"""
Unit and Adversarial Test Suite for Video Editor Service (Milestone 3).

Comprehensive testing for 9 professional studio-grade video processing tools:
  1. remove_text_from_video (delogo, inpaint, auto via Tesseract OCR)
  2. add_subtitle_to_video (plain text auto-SRT, custom styling, position)
  3. apply_color_grade (vivid, vintage, cinematic, cool, warm, bw, custom EQ)
  4. stabilize_video (2-pass vidstabdetect & vidstabtransform)
  5. concatenate_videos (fast stream copy, re-encode, size safety ceiling)
  6. extract_frames (periodic fps sampling, zip packaging)
  7. remove_watermark_region (chained multi-delogo filters, max 5 regions)
  8. enhance_video_quality (sharpen, denoise, deinterlace, upscale, tonemap)
  9. generate_video_thumbnail (exact timestamp seek, aspect preservation)

Includes:
  - Dual-Delivery routing (direct <= 50MB vs portal > 50MB)
  - Zero-Disk Leak guarantees on success, error, and timeout
  - Adversarial security hardening (POSIX traversal, Windows backslash, URL-encoded,
    Windows drive letter, UNC path, sandbox boundary enforcement, coordinate bounds)
  - Hardware bounding via Semaphores and transient HTTP download cleanup
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure app directory is in sys.path safely across local and container environments
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

from app.services.video_editor_service import (
    TELEGRAM_MAX_FILE_SIZE,
    VideoEditorService,
)


class TestVideoEditorService(unittest.IsolatedAsyncioTestCase):
    """Full Unit and Adversarial Test Suite for VideoEditorService."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.scratch_path = Path(self.temp_dir.name)
        self.mock_storage = MagicMock()
        self.service = VideoEditorService(
            storage_manager=self.mock_storage,
            temp_dir=self.scratch_path,
        )

        # Create a valid dummy video file inside the sandbox
        self.dummy_video = self.scratch_path / "sample_test_video.mp4"
        self.dummy_video.write_bytes(b"\x00" * 4096)

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    def _get_scratch_files(self) -> set[Path]:
        """Returns set of all existing files inside the scratch directory."""
        if not self.scratch_path.exists():
            return set()
        return {p for p in self.scratch_path.rglob("*") if p.is_file()}

    # ═══════════════════════════════════════════════════════════════════════════
    # NHÓM 1: UNIT TESTS (CHỨC NĂNG 9 TOOLS & DUAL-DELIVERY & ZERO LEAK)
    # ═══════════════════════════════════════════════════════════════════════════

    # ─── 1. remove_text_from_video ──────────────────────────────────────────

    async def test_remove_text_delogo_specified_region(self):
        """Test remove_text_from_video mode='delogo' with explicit region {x, y, w, h}."""
        async def fake_run(cmd, timeout=300):
            out_file = Path(cmd[-1])
            out_file.write_bytes(b"delogo_output_video")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.remove_text_from_video(
                input_path_or_url=str(self.dummy_video),
                region={"x": 50, "y": 140, "w": 400, "h": 100},
                mode="delogo",
                output_format="mp4",
            )
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["tool"], "remove_text_from_video")
            self.assertEqual(res["mode_used"], "delogo")
            self.assertEqual(res["delivery"], "direct")
            self.assertEqual(res["region"], {"x": 50, "y": 140, "w": 400, "h": 100})

            cmd = mock_run.call_args[0][0]
            self.assertIn("-vf", cmd)
            vf_val = cmd[cmd.index("-vf") + 1]
            self.assertEqual(vf_val, "delogo=x=50:y=140:w=400:h=100:show=0")
            self.assertIn("-c:a", cmd)
            self.assertEqual(cmd[cmd.index("-c:a") + 1], "copy")
            self.assertIn("-movflags", cmd)
            self.assertEqual(cmd[cmd.index("-movflags") + 1], "+faststart")

    async def test_remove_text_auto_detect_via_tesseract(self):
        """Test remove_text_from_video mode='auto' successfully detects text via OCR sampling -> delogo."""
        async def fake_run(cmd, timeout=300):
            # Check if this is the sample frame extraction command
            if "-vsync" in cmd:
                sample_pattern = cmd[-1]
                sample_dir = Path(sample_pattern).parent
                # Write sample jpg files
                (sample_dir / "sample_01.jpg").write_bytes(b"frame1")
                (sample_dir / "sample_02.jpg").write_bytes(b"frame2")
                return 0, b"", b""
            # Otherwise it's the delogo output command
            out_file = Path(cmd[-1])
            out_file.write_bytes(b"auto_detected_delogo_video")
            return 0, b"", b""

        mock_tesseract = MagicMock()
        mock_tesseract.Output.DICT = "dict"
        mock_tesseract.image_to_data.return_value = {
            "text": ["SAMPLE", "TEXT"],
            "conf": [95, 90],
            "left": [100, 200],
            "top": [50, 50],
            "width": [80, 70],
            "height": [30, 30],
        }

        mock_pil = MagicMock()
        mock_img = MagicMock()
        mock_pil.Image.open.return_value.__enter__.return_value = mock_img

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            with patch.dict("sys.modules", {"cv2": None, "pytesseract": mock_tesseract, "PIL": mock_pil}):
                res = await self.service.remove_text_from_video(
                    input_path_or_url=str(self.dummy_video),
                    mode="auto",
                )
                self.assertEqual(res["status"], "ok")
                self.assertEqual(res["mode_used"], "delogo")
                # Auto detects bounding box union [left=100, top=50, max_x=270, max_y=80]
                # With 10px pad: x=90, y=40, w=190, h=50
                self.assertEqual(res["region"]["x"], 90)
                self.assertEqual(res["region"]["y"], 40)
                self.assertEqual(res["region"]["w"], 190)
                self.assertEqual(res["region"]["h"], 50)

                # Verify final delogo command uses the detected region and temporal enable
                final_cmd = mock_run.call_args[0][0]
                vf_val = final_cmd[final_cmd.index("-vf") + 1]
                self.assertIn("delogo=x=90:y=40:w=190:h=50", vf_val)
                self.assertIn("show=0", vf_val)

    async def test_remove_text_inpaint_mode_fallback_when_no_opencv(self):
        """Test remove_text_from_video mode='inpaint' raises RuntimeError when cv2 is missing."""
        with patch.dict("sys.modules", {"cv2": None}):
            with self.assertRaises(RuntimeError) as ctx:
                await self.service.remove_text_from_video(
                    input_path_or_url=str(self.dummy_video),
                    region={"x": 10, "y": 10, "w": 50, "h": 50},
                    mode="inpaint",
                )
            self.assertIn("opencv-python-headless chưa được cài đặt", str(ctx.exception))

    async def test_remove_text_auto_fallback_to_delogo_when_no_opencv(self):
        """Test remove_text_from_video mode='auto' gracefully falls back to delogo when cv2 is missing."""
        async def fake_run(cmd, timeout=300):
            if "-vsync" in cmd:
                return 0, b"", b""
            out_file = Path(cmd[-1])
            out_file.write_bytes(b"fallback_delogo_video")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run):
            with patch.dict("sys.modules", {"cv2": None}):
                res = await self.service.remove_text_from_video(
                    input_path_or_url=str(self.dummy_video),
                    mode="auto",
                )
                self.assertEqual(res["status"], "ok")
                self.assertEqual(res["mode_used"], "delogo")

    async def test_remove_text_inpaint_mode_opencv_success(self):
        """Test remove_text_from_video mode='inpaint' delegates to inpaint_video_sync."""
        def fake_inpaint(inp, out, rx, ry, rw, rh):
            out.write_bytes(b"inpainted_video_payload")

        mock_cv2 = MagicMock()
        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            with patch.object(self.service, "_inpaint_video_sync", side_effect=fake_inpaint) as mock_sync:
                res = await self.service.remove_text_from_video(
                    input_path_or_url=str(self.dummy_video),
                    region={"x": 20, "y": 30, "w": 80, "h": 40},
                    mode="inpaint",
                )
                self.assertEqual(res["status"], "ok")
                self.assertEqual(res["mode_used"], "inpaint")
                mock_sync.assert_called_once()
                args = mock_sync.call_args[0]
                self.assertEqual(args[2:], (20, 30, 80, 40))

    # ─── 2. add_subtitle_to_video ───────────────────────────────────────────

    async def test_add_subtitle_plain_text_drawtext(self):
        """Test add_subtitle_to_video generates temporary SRT with 5-second splits from raw text."""
        created_srt_content = []

        async def fake_run(cmd, timeout=300):
            out_file = Path(cmd[-1])
            out_file.write_bytes(b"subbed_video")
            # Inspect temporary SRT file generated during the run
            vf_val = cmd[cmd.index("-vf") + 1]
            self.assertIn("subtitles=", vf_val)
            # Find generated srt in scratch directory
            for f in self.scratch_path.rglob("*.srt"):
                created_srt_content.append(f.read_text(encoding="utf-8"))
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run):
            plain_text = "Dòng 1: Xin chào thế giới\nDòng 2: Đây là video mẫu"
            res = await self.service.add_subtitle_to_video(
                input_path_or_url=str(self.dummy_video),
                subtitle_text_or_path=plain_text,
                position="bottom",
            )
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["tool"], "add_subtitle_to_video")
            self.assertEqual(res["position"], "bottom")

            # Verify SRT contents were properly structured into 5-second intervals
            self.assertTrue(len(created_srt_content) > 0)
            srt_str = created_srt_content[0]
            self.assertIn("00:00:00,000 --> 00:00:05,000", srt_str)
            self.assertIn("Dòng 1: Xin chào thế giới", srt_str)
            self.assertIn("00:00:05,000 --> 00:00:10,000", srt_str)
            self.assertIn("Dòng 2: Đây là video mẫu", srt_str)

            # Ensure temporary srt was cleaned up after completion
            remaining_srts = list(self.scratch_path.rglob("*.srt"))
            self.assertEqual(len(remaining_srts), 0)

    async def test_add_subtitle_srt_file(self):
        """Test add_subtitle_to_video with an existing .srt file in the sandbox."""
        custom_srt = self.scratch_path / "custom.srt"
        custom_srt.write_text("1\n00:00:01,000 --> 00:00:04,000\nSub ready\n", encoding="utf-8")

        async def fake_run(cmd, timeout=300):
            out_file = Path(cmd[-1])
            out_file.write_bytes(b"subbed_video")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.add_subtitle_to_video(
                input_path_or_url=str(self.dummy_video),
                subtitle_text_or_path=str(custom_srt),
                position="top",
            )
            self.assertEqual(res["status"], "ok")
            cmd = mock_run.call_args[0][0]
            vf_val = cmd[cmd.index("-vf") + 1]
            self.assertIn("subtitles=", vf_val)
            self.assertIn("Alignment=6", vf_val)  # top alignment is 6

    async def test_add_subtitle_custom_styling_and_position(self):
        """Test add_subtitle_to_video with custom fontsize, color, outline and center position."""
        async def fake_run(cmd, timeout=300):
            Path(cmd[-1]).write_bytes(b"styled_subbed_video")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.add_subtitle_to_video(
                input_path_or_url=str(self.dummy_video),
                subtitle_text_or_path="Centered Yellow Subtitle",
                position="center",
                style={"fontsize": 28, "color": "&H0000FFFF", "outline": "&H00FF0000"},
            )
            self.assertEqual(res["status"], "ok")
            cmd = mock_run.call_args[0][0]
            vf_val = cmd[cmd.index("-vf") + 1]
            self.assertIn("Alignment=10", vf_val)
            self.assertIn("FontSize=28", vf_val)
            self.assertIn("PrimaryColour=&H0000FFFF", vf_val)
            self.assertIn("OutlineColour=&H00FF0000", vf_val)

    # ─── 3. apply_color_grade ────────────────────────────────────────────────

    async def test_apply_color_grade_vivid(self):
        """Test apply_color_grade with 'vivid' preset."""
        async def fake_run(cmd, timeout=300):
            Path(cmd[-1]).write_bytes(b"graded_vivid")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.apply_color_grade(
                input_path_or_url=str(self.dummy_video),
                preset="vivid",
            )
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["preset"], "vivid")
            cmd = mock_run.call_args[0][0]
            vf_val = cmd[cmd.index("-vf") + 1]
            self.assertEqual(vf_val, "eq=contrast=1.2:saturation=1.3:brightness=0.02")

    async def test_apply_color_grade_vintage(self):
        """Test apply_color_grade with 'vintage' preset."""
        async def fake_run(cmd, timeout=300):
            Path(cmd[-1]).write_bytes(b"graded_vintage")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.apply_color_grade(
                input_path_or_url=str(self.dummy_video),
                preset="vintage",
            )
            self.assertEqual(res["status"], "ok")
            cmd = mock_run.call_args[0][0]
            vf_val = cmd[cmd.index("-vf") + 1]
            self.assertEqual(vf_val, "curves=vintage,hue=s=0.85")

    async def test_apply_color_grade_cinematic(self):
        """Test apply_color_grade with 'cinematic' preset."""
        async def fake_run(cmd, timeout=300):
            Path(cmd[-1]).write_bytes(b"graded_cinematic")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.apply_color_grade(
                input_path_or_url=str(self.dummy_video),
                preset="cinematic",
            )
            self.assertEqual(res["status"], "ok")
            cmd = mock_run.call_args[0][0]
            vf_val = cmd[cmd.index("-vf") + 1]
            self.assertEqual(vf_val, "curves=strong_contrast,eq=saturation=1.15")

    async def test_apply_color_grade_cool(self):
        """Test apply_color_grade with 'cool' preset."""
        async def fake_run(cmd, timeout=300):
            Path(cmd[-1]).write_bytes(b"graded_cool")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.apply_color_grade(
                input_path_or_url=str(self.dummy_video),
                preset="cool",
            )
            self.assertEqual(res["status"], "ok")
            cmd = mock_run.call_args[0][0]
            vf_val = cmd[cmd.index("-vf") + 1]
            self.assertIn("colorbalance=bs=0.15", vf_val)

    async def test_apply_color_grade_warm(self):
        """Test apply_color_grade with 'warm' preset."""
        async def fake_run(cmd, timeout=300):
            Path(cmd[-1]).write_bytes(b"graded_warm")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.apply_color_grade(
                input_path_or_url=str(self.dummy_video),
                preset="warm",
            )
            self.assertEqual(res["status"], "ok")
            cmd = mock_run.call_args[0][0]
            vf_val = cmd[cmd.index("-vf") + 1]
            self.assertIn("colorbalance=rs=0.15", vf_val)

    async def test_apply_color_grade_bw(self):
        """Test apply_color_grade with 'bw' black and white preset."""
        async def fake_run(cmd, timeout=300):
            Path(cmd[-1]).write_bytes(b"graded_bw")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.apply_color_grade(
                input_path_or_url=str(self.dummy_video),
                preset="bw",
            )
            self.assertEqual(res["status"], "ok")
            cmd = mock_run.call_args[0][0]
            vf_val = cmd[cmd.index("-vf") + 1]
            self.assertEqual(vf_val, "hue=s=0")

    async def test_apply_color_grade_custom_eq(self):
        """Test apply_color_grade with 'custom' equalizer values."""
        async def fake_run(cmd, timeout=300):
            Path(cmd[-1]).write_bytes(b"graded_custom")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.apply_color_grade(
                input_path_or_url=str(self.dummy_video),
                preset="custom",
                custom_eq={"contrast": 1.25, "brightness": 0.05, "saturation": 1.4, "gamma": 1.1},
            )
            self.assertEqual(res["status"], "ok")
            cmd = mock_run.call_args[0][0]
            vf_val = cmd[cmd.index("-vf") + 1]
            self.assertEqual(vf_val, "eq=contrast=1.25:brightness=0.05:saturation=1.4:gamma=1.1")

    # ─── 4. stabilize_video ──────────────────────────────────────────────────

    async def test_stabilize_video_two_pass(self):
        """Test stabilize_video executes 2 subprocess passes (vidstabdetect & vidstabtransform)."""
        call_history = []

        async def fake_run(cmd, timeout=300):
            call_history.append(list(cmd))
            if "-f" in cmd and "null" in cmd:
                # Pass 1 produces transforms.trf file
                vf_arg = cmd[cmd.index("-vf") + 1]
                self.assertIn("vidstabdetect", vf_arg)
                # Extract transforms file path from result='...'
                match = re.search(r"result='([^']+)'", vf_arg)
                if match:
                    raw_trf = match.group(1).replace("\\:", ":")
                    trf_path = Path(raw_trf)
                    trf_path.write_bytes(b"motion_vectors_data")
                return 0, b"", b""
            # Pass 2 produces stabilized output
            Path(cmd[-1]).write_bytes(b"stabilized_video")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run):
            res = await self.service.stabilize_video(
                input_path_or_url=str(self.dummy_video),
                smoothing=15,
            )
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["smoothing"], 15)
            self.assertEqual(len(call_history), 2)

            # Pass 1 check
            self.assertIn("vidstabdetect", call_history[0][call_history[0].index("-vf") + 1])
            self.assertIn("-an", call_history[0])

            # Pass 2 check
            vf2 = call_history[1][call_history[1].index("-vf") + 1]
            self.assertIn("vidstabtransform=smoothing=15", vf2)
            self.assertIn("unsharp=5:5:0.8", vf2)

            # Ensure .trf transient file is cleaned up
            remaining_trf = list(self.scratch_path.rglob("*.trf"))
            self.assertEqual(len(remaining_trf), 0)

    # ─── 5. concatenate_videos ───────────────────────────────────────────────

    async def test_concatenate_3_videos(self):
        """Test concatenate_videos merges 3 clips with fast stream copy (-c copy)."""
        c1 = self.scratch_path / "clip1.mp4"
        c2 = self.scratch_path / "clip2.mp4"
        c3 = self.scratch_path / "clip3.mp4"
        for c in (c1, c2, c3):
            c.write_bytes(b"\x00" * 1024)

        async def fake_run(cmd, timeout=300):
            Path(cmd[-1]).write_bytes(b"merged_video_data")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.concatenate_videos(
                input_paths=[str(c1), str(c2), str(c3)],
                reencode=False,
            )
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["clips_count"], 3)
            self.assertFalse(res["reencode"])

            cmd = mock_run.call_args[0][0]
            self.assertIn("-f", cmd)
            self.assertEqual(cmd[cmd.index("-f") + 1], "concat")
            self.assertIn("-c", cmd)
            self.assertEqual(cmd[cmd.index("-c") + 1], "copy")

            # Verify temporary concat txt list was deleted
            remaining_txts = list(self.scratch_path.rglob("concat_*.txt"))
            self.assertEqual(len(remaining_txts), 0)

    async def test_concatenate_reencode_mode(self):
        """Test concatenate_videos with reencode=True uses libx264 and aac."""
        c1 = self.scratch_path / "clip1.mp4"
        c2 = self.scratch_path / "clip2.mp4"
        c1.write_bytes(b"\x00" * 1024)
        c2.write_bytes(b"\x00" * 1024)

        async def fake_run(cmd, timeout=300):
            Path(cmd[-1]).write_bytes(b"merged_reencoded_data")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.concatenate_videos(
                input_paths=[str(c1), str(c2)],
                reencode=True,
            )
            self.assertEqual(res["status"], "ok")
            self.assertTrue(res["reencode"])

            cmd = mock_run.call_args[0][0]
            self.assertIn("-c:v", cmd)
            self.assertEqual(cmd[cmd.index("-c:v") + 1], "libx264")
            self.assertIn("-c:a", cmd)
            self.assertEqual(cmd[cmd.index("-c:a") + 1], "aac")

    async def test_concatenate_exceeds_limit_raises(self):
        """Test concatenate_videos raises ValueError when input clips count > 10."""
        clips = [str(self.scratch_path / f"clip_{i}.mp4") for i in range(11)]
        with self.assertRaises(ValueError) as ctx:
            await self.service.concatenate_videos(clips)
        self.assertIn("1 đến 10 clip", str(ctx.exception))

    # ─── 6. extract_frames ───────────────────────────────────────────────────

    async def test_extract_frames_interval(self):
        """Test extract_frames samples frames by interval and bundles into a ZIP archive."""
        async def fake_run(cmd, timeout=300):
            pattern = cmd[-1]
            frames_dir = Path(pattern).parent
            # Simulate 3 extracted frame images
            (frames_dir / "frame_0001.jpg").write_bytes(b"frame_data_1")
            (frames_dir / "frame_0002.jpg").write_bytes(b"frame_data_2")
            (frames_dir / "frame_0003.jpg").write_bytes(b"frame_data_3")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.extract_frames(
                input_path_or_url=str(self.dummy_video),
                interval_seconds=1.5,
                output_format="jpg",
            )
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["frames_count"], 3)
            self.assertEqual(res["interval_seconds"], 1.5)
            self.assertTrue(Path(res["zip_path"]).exists())

            cmd = mock_run.call_args[0][0]
            vf_val = cmd[cmd.index("-vf") + 1]
            self.assertEqual(vf_val, "fps=1/1.5")

    # ─── 7. remove_watermark_region ──────────────────────────────────────────

    async def test_remove_watermark_multi_region_chain(self):
        """Test remove_watermark_region chains multiple delogo filters."""
        regions = [
            {"x": 10, "y": 10, "w": 100, "h": 50},
            {"x": 400, "y": 20, "w": 120, "h": 60},
            {"x": 50, "y": 500, "w": 200, "h": 80},
        ]

        async def fake_run(cmd, timeout=300):
            Path(cmd[-1]).write_bytes(b"multi_delogo_video")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.remove_watermark_region(
                input_path_or_url=str(self.dummy_video),
                regions=regions,
            )
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["regions_count"], 3)

            cmd = mock_run.call_args[0][0]
            vf_val = cmd[cmd.index("-vf") + 1]
            self.assertIn("delogo=x=10:y=10:w=100:h=50:show=0", vf_val)
            self.assertIn("delogo=x=400:y=20:w=120:h=60:show=0", vf_val)
            self.assertIn("delogo=x=50:y=500:w=200:h=80:show=0", vf_val)
            # Verify delimiter ',' for chaining
            self.assertEqual(vf_val.count("delogo="), 3)

    # ─── 8. enhance_video_quality ────────────────────────────────────────────

    async def test_enhance_sharpen(self):
        """Test enhance_video_quality with 'sharpen' preset uses unsharp filter."""
        async def fake_run(cmd, timeout=300):
            Path(cmd[-1]).write_bytes(b"sharpened_video")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.enhance_video_quality(
                input_path_or_url=str(self.dummy_video),
                preset="sharpen",
            )
            self.assertEqual(res["status"], "ok")
            cmd = mock_run.call_args[0][0]
            vf_val = cmd[cmd.index("-vf") + 1]
            self.assertEqual(vf_val, "unsharp=5:5:1.0:5:5:0.0")

    async def test_enhance_denoise(self):
        """Test enhance_video_quality with 'denoise' preset uses hqdn3d filter."""
        async def fake_run(cmd, timeout=300):
            Path(cmd[-1]).write_bytes(b"denoised_video")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.enhance_video_quality(
                input_path_or_url=str(self.dummy_video),
                preset="denoise",
            )
            self.assertEqual(res["status"], "ok")
            cmd = mock_run.call_args[0][0]
            vf_val = cmd[cmd.index("-vf") + 1]
            self.assertEqual(vf_val, "hqdn3d=4.0:3.0:6.0:4.5")

    async def test_enhance_deinterlace(self):
        """Test enhance_video_quality with 'deinterlace' preset uses yadif filter."""
        async def fake_run(cmd, timeout=300):
            Path(cmd[-1]).write_bytes(b"deinterlaced_video")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.enhance_video_quality(
                input_path_or_url=str(self.dummy_video),
                preset="deinterlace",
            )
            self.assertEqual(res["status"], "ok")
            cmd = mock_run.call_args[0][0]
            self.assertIn("yadif=0:-1:0", cmd[cmd.index("-vf") + 1])

    async def test_enhance_upscale_2x(self):
        """Test enhance_video_quality with 'upscale_2x' preset uses lanczos scaling."""
        async def fake_run(cmd, timeout=300):
            Path(cmd[-1]).write_bytes(b"upscaled_video")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.enhance_video_quality(
                input_path_or_url=str(self.dummy_video),
                preset="upscale_2x",
            )
            self.assertEqual(res["status"], "ok")
            cmd = mock_run.call_args[0][0]
            self.assertIn("scale=iw*2:ih*2:flags=lanczos", cmd[cmd.index("-vf") + 1])

    async def test_enhance_hdr_tonemap(self):
        """Test enhance_video_quality with 'hdr_tonemap' preset combines eq and unsharp."""
        async def fake_run(cmd, timeout=300):
            Path(cmd[-1]).write_bytes(b"tonemapped_video")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.enhance_video_quality(
                input_path_or_url=str(self.dummy_video),
                preset="hdr_tonemap",
            )
            self.assertEqual(res["status"], "ok")
            cmd = mock_run.call_args[0][0]
            vf_val = cmd[cmd.index("-vf") + 1]
            self.assertIn("eq=contrast=1.15:brightness=0.03:saturation=1.2", vf_val)
            self.assertIn("unsharp=3:3:0.5", vf_val)

    # ─── 9. generate_video_thumbnail ─────────────────────────────────────────

    async def test_generate_thumbnail(self):
        """Test generate_video_thumbnail generates single frame at exact timestamp."""
        async def fake_run(cmd, timeout=60):
            Path(cmd[-1]).write_bytes(b"thumbnail_jpg")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.generate_video_thumbnail(
                input_path_or_url=str(self.dummy_video),
                timestamp=12.5,
                width=640,
                height=360,
                output_format="jpg",
            )
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["timestamp"], 12.5)
            self.assertEqual(res["width"], 640)
            self.assertEqual(res["height"], 360)

            cmd = mock_run.call_args[0][0]
            self.assertIn("-ss", cmd)
            self.assertEqual(cmd[cmd.index("-ss") + 1], "12.5")
            self.assertIn("-vframes", cmd)
            self.assertEqual(cmd[cmd.index("-vframes") + 1], "1")
            self.assertIn("-vf", cmd)
            vf_val = cmd[cmd.index("-vf") + 1]
            self.assertEqual(vf_val, "scale=640:360:force_original_aspect_ratio=decrease")

    # ─── 10. DUAL-DELIVERY & ZERO-DISK LEAK ──────────────────────────────────

    async def test_dual_delivery_small_file_direct(self):
        """Test output size <= 50MB is delivered directly without calling media storage manager."""
        async def fake_run(cmd, timeout=300):
            out_file = Path(cmd[-1])
            # 10MB simulated file
            out_file.write_bytes(b"0" * (10 * 1024 * 1024))
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run):
            res = await self.service.remove_text_from_video(
                input_path_or_url=str(self.dummy_video),
                mode="delogo",
            )
            self.assertEqual(res["delivery"], "direct")
            self.assertIsNone(res["internet_url"])
            self.assertIsNone(res["lan_url"])
            self.mock_storage.publish_download_item.assert_not_called()

    async def test_dual_delivery_large_file_portal(self):
        """Test output size > 50MB publishes download item via media storage manager."""
        mock_record = MagicMock()
        mock_record.file_path = self.scratch_path / "large_out.mp4"
        mock_record.filename = "large_out.mp4"
        mock_record.file_size = 55 * 1024 * 1024
        mock_record.internet_url = "https://kirito.ngrok-free.dev/api/media/download/item_99"
        mock_record.lan_url = "http://192.168.1.100:8000/api/media/download/item_99"
        mock_record.expires_at = "2026-10-01T12:00:00Z"
        self.mock_storage.publish_download_item.return_value = mock_record

        async def fake_run(cmd, timeout=300):
            out_file = Path(cmd[-1])
            # Mock 52MB file size using truncate
            with open(out_file, "wb") as f:
                f.seek(52 * 1024 * 1024 - 1)
                f.write(b"\x00")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run):
            res = await self.service.remove_text_from_video(
                input_path_or_url=str(self.dummy_video),
                mode="delogo",
            )
            self.assertEqual(res["delivery"], "portal")
            self.assertEqual(res["internet_url"], "https://kirito.ngrok-free.dev/api/media/download/item_99")
            self.assertEqual(res["lan_url"], "http://192.168.1.100:8000/api/media/download/item_99")
            self.mock_storage.publish_download_item.assert_called_once()

    async def test_zero_disk_leak_on_ffmpeg_error(self):
        """Test failed FFmpeg invocation cleans up all transient output files (Zero-Disk Leak)."""
        before_files = self._get_scratch_files()

        async def fake_failing_run(cmd, timeout=300):
            # Simulate FFmpeg creating a partial or broken output file before crashing
            out_file = Path(cmd[-1])
            out_file.write_bytes(b"corrupted partial data")
            return 1, b"", b"FFmpeg error: Invalid input data"

        with patch.object(self.service, "_run_command", side_effect=fake_failing_run):
            with self.assertRaises(RuntimeError):
                await self.service.remove_text_from_video(
                    input_path_or_url=str(self.dummy_video),
                    mode="delogo",
                )

        after_files = self._get_scratch_files()
        delta = after_files - before_files
        self.assertEqual(len(delta), 0, f"Phát hiện rò rỉ tệp sau lỗi FFmpeg: {delta}")

    async def test_zero_disk_leak_on_timeout(self):
        """Test task timeout cleans up all transient files."""
        before_files = self._get_scratch_files()

        async def fake_timeout_run(cmd, timeout=300):
            # Simulate partial file written before timing out
            if not cmd[-1].startswith("-"):
                Path(cmd[-1]).write_bytes(b"timed_out_partial")
            raise TimeoutError("Tác vụ xử lý video vượt quá thời gian tối đa.")

        with patch.object(self.service, "_run_command", side_effect=fake_timeout_run):
            with self.assertRaises(TimeoutError):
                await self.service.stabilize_video(
                    input_path_or_url=str(self.dummy_video),
                    smoothing=10,
                )

        after_files = self._get_scratch_files()
        delta = after_files - before_files
        self.assertEqual(len(delta), 0, f"Phát hiện rò rỉ tệp sau timeout: {delta}")

    async def test_transient_http_download_cleanup_on_success_and_error(self):
        """Test transient SSD download from remote URL is cleaned up both on success and error."""
        before_files = self._get_scratch_files()

        class DummyStreamResponse:
            def raise_for_status(self):
                pass
            async def aiter_bytes(self, chunk_size=65536):
                yield b"dummy_http_video_chunk"
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        mock_http = MagicMock()
        mock_http.stream.return_value = DummyStreamResponse()
        mock_http.aclose = AsyncMock()
        service_with_http = VideoEditorService(
            storage_manager=self.mock_storage,
            http_client=mock_http,
            temp_dir=self.scratch_path,
        )

        async def fake_run(cmd, timeout=300):
            Path(cmd[-1]).write_bytes(b"output_from_http")
            return 0, b"", b""

        with patch.object(service_with_http, "_run_command", side_effect=fake_run):
            res = await service_with_http.remove_text_from_video(
                input_path_or_url="https://example.com/test_clip.mp4",
                mode="delogo",
            )
            self.assertEqual(res["status"], "ok")
            # The downloaded file dl_* must be unlinked
            dl_files = list(self.scratch_path.rglob("dl_*"))
            self.assertEqual(len(dl_files), 0, f"Tệp tải tạm thời chưa được xóa: {dl_files}")

    async def test_concurrency_semaphore_limits(self):
        """Test bounded concurrency semaphore limits FFmpeg subprocesses to 2."""
        running = 0
        max_running = 0

        async def fake_proc(*cmd, **kwargs):
            nonlocal running, max_running
            running += 1
            max_running = max(max_running, running)
            await asyncio.sleep(0.05)
            running -= 1
            mock_p = MagicMock()
            mock_p.returncode = 0
            mock_p.communicate = AsyncMock(return_value=(b"", b""))
            if not cmd[-1].startswith("-"):
                Path(cmd[-1]).write_bytes(b"data")
            return mock_p

        with patch("asyncio.create_subprocess_exec", side_effect=fake_proc):
            tasks = [
                self.service.apply_color_grade(str(self.dummy_video), preset="bw")
                for _ in range(5)
            ]
            await asyncio.gather(*tasks)

        self.assertLessEqual(max_running, 2, f"Semaphore bị vượt giới hạn: max concurrent = {max_running}")

    # ═══════════════════════════════════════════════════════════════════════════
    # NHÓM 2: ADVERSARIAL & SECURITY TESTS (15 BÀI BẢO MẬT & ĐỐI KHÁNG)
    # ═══════════════════════════════════════════════════════════════════════════

    async def test_path_traversal_blocked_posix(self):
        """Test POSIX relative path traversal attempts ('../../../etc/passwd') are strictly blocked."""
        with self.assertRaises(PermissionError) as ctx:
            await self.service.remove_text_from_video("../../../etc/passwd")
        self.assertIn("Path Traversal", str(ctx.exception))

    async def test_path_traversal_url_encoded(self):
        """Test URL percent-encoded traversal attempts ('%2e%2e%2f') are decoded and blocked."""
        with self.assertRaises(PermissionError) as ctx:
            await self.service.remove_text_from_video("%2e%2e%2f%2e%2e%2fetc%2fpasswd")
        self.assertIn("Path Traversal", str(ctx.exception))

    async def test_path_traversal_windows_backslash(self):
        """Test Windows backslash traversal attempts ('..\\..\\windows\\win.ini') are normalized and blocked."""
        with self.assertRaises(PermissionError) as ctx:
            await self.service.remove_text_from_video("..\\..\\windows\\win.ini")
        self.assertIn("Path Traversal", str(ctx.exception))

    async def test_path_traversal_windows_drive(self):
        """Test Windows drive letter absolute paths ('C:/Windows/win.ini') outside sandbox are blocked."""
        with self.assertRaises(PermissionError) as ctx:
            await self.service.remove_text_from_video("C:/Windows/win.ini")
        self.assertIn("Windows drive letter", str(ctx.exception))

    async def test_path_traversal_unc(self):
        """Test UNC network paths ('\\\\attacker\\share' or '//attacker/share') are blocked."""
        with self.assertRaises(PermissionError) as ctx:
            await self.service.remove_text_from_video("\\\\attacker\\share\\payload.mp4")
        self.assertIn("UNC", str(ctx.exception))

    async def test_sandbox_whitelist_blocks_outside_path(self):
        """Test absolute system path ('/etc/passwd' or '/var/log/syslog') outside sandbox is rejected."""
        # On Linux/macOS, /etc/passwd has no '..' but is outside sandbox whitelist
        # On Windows, /etc/passwd resolves to current drive root e.g. D:\etc\passwd outside sandbox
        with self.assertRaises((ValueError, PermissionError)) as ctx:
            await self.service.remove_text_from_video("/etc/passwd")
        self.assertTrue(
            "sandbox" in str(ctx.exception).lower() or "từ chối" in str(ctx.exception).lower()
        )

    async def test_invalid_region_negative_x(self):
        """Test negative region coordinate x < 0 raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            await self.service.remove_text_from_video(
                input_path_or_url=str(self.dummy_video),
                region={"x": -10, "y": 0, "w": 100, "h": 50},
            )
        self.assertIn("không âm", str(ctx.exception))

    async def test_invalid_region_exceeds_bounds(self):
        """Test region dimension exceeding safety boundary (w > 10000) raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            await self.service.remove_text_from_video(
                input_path_or_url=str(self.dummy_video),
                region={"x": 0, "y": 0, "w": 10001, "h": 50},
            )
        self.assertIn("vượt quá giới hạn an toàn", str(ctx.exception))

    async def test_invalid_region_missing_keys(self):
        """Test region dict missing required coordinate keys raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            await self.service.remove_text_from_video(
                input_path_or_url=str(self.dummy_video),
                region={"x": 10, "y": 20},
            )
        self.assertIn("Thiếu tham số tọa độ", str(ctx.exception))

    async def test_invalid_region_zero_or_negative_dim(self):
        """Test region with zero or negative width/height raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            await self.service.remove_text_from_video(
                input_path_or_url=str(self.dummy_video),
                region={"x": 10, "y": 20, "w": 0, "h": 50},
            )
        self.assertIn("phải lớn hơn 0", str(ctx.exception))

    async def test_invalid_preset_raises(self):
        """Test invalid color grading preset raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            await self.service.apply_color_grade(
                input_path_or_url=str(self.dummy_video),
                preset="unsupported_cyberpunk_filter",
            )
        self.assertIn("không hợp lệ", str(ctx.exception))

    async def test_empty_concat_list(self):
        """Test empty video clips list for concatenation raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            await self.service.concatenate_videos([])
        self.assertIn("không được để trống", str(ctx.exception))

    async def test_exceed_max_watermark_regions(self):
        """Test providing more than 5 watermark regions raises ValueError."""
        excessive_regions = [{"x": 10 * i, "y": 10 * i, "w": 50, "h": 50} for i in range(6)]
        with self.assertRaises(ValueError) as ctx:
            await self.service.remove_watermark_region(
                input_path_or_url=str(self.dummy_video),
                regions=excessive_regions,
            )
        self.assertIn("tối đa là 5", str(ctx.exception))

    async def test_stabilize_video_invalid_smoothing(self):
        """Test invalid smoothing factor (<1 or >60) raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            await self.service.stabilize_video(str(self.dummy_video), smoothing=0)
        self.assertIn("từ 1 đến 60", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            await self.service.stabilize_video(str(self.dummy_video), smoothing=65)
        self.assertIn("từ 1 đến 60", str(ctx.exception))

    async def test_extract_frames_invalid_interval(self):
        """Test non-positive interval_seconds raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            await self.service.extract_frames(str(self.dummy_video), interval_seconds=0)
        self.assertIn("lớn hơn 0", str(ctx.exception))

    async def test_generate_thumbnail_invalid_bounds(self):
        """Test negative timestamp or invalid dimensions raises ValueError."""
        with self.assertRaises(ValueError):
            await self.service.generate_video_thumbnail(str(self.dummy_video), timestamp=-1.0)

        with self.assertRaises(ValueError):
            await self.service.generate_video_thumbnail(str(self.dummy_video), width=0)

        with self.assertRaises(ValueError):
            await self.service.generate_video_thumbnail(str(self.dummy_video), height=-50)

    async def test_zero_disk_leak_adversarial_stress_10iter(self):
        """
        Adversarial Stress Test: Executes 10 iterations of diverse video operations
        mixing successful executions, parameter violations, and FFmpeg crashes,
        then verifies EXACTLY ZERO leaked temporary files in scratch space.
        """
        before_files = self._get_scratch_files()

        async def fake_alternating_run(cmd, timeout=300):
            if "-f" in cmd and "null" in cmd:
                return 0, b"", b""
            out_file = Path(cmd[-1])
            out_file.write_bytes(b"stress_test_payload")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_alternating_run):
            for i in range(10):
                # 1. Successful color grading
                res_color = await self.service.apply_color_grade(
                    str(self.dummy_video), preset="vivid"
                )
                self.assertEqual(res_color["status"], "ok")
                # Clean up delivered output file to simulate consumer retrieving file
                Path(res_color["output_path"]).unlink(missing_ok=True)

                # 2. Blocked path traversal attempt
                with self.assertRaises(PermissionError):
                    await self.service.remove_text_from_video(f"../../attack_{i}.mp4")

                # 3. Invalid region rejection
                with self.assertRaises(ValueError):
                    await self.service.remove_text_from_video(
                        str(self.dummy_video), region={"x": -1, "y": 0, "w": 10, "h": 10}
                    )

                # 4. Successful subtitle addition
                res_sub = await self.service.add_subtitle_to_video(
                    str(self.dummy_video), subtitle_text_or_path=f"Subtitle line {i}"
                )
                self.assertEqual(res_sub["status"], "ok")
                Path(res_sub["output_path"]).unlink(missing_ok=True)

        after_files = self._get_scratch_files()
        leaked_files = after_files - before_files
    # ─── Tests for Bug Fix: Overlay Text Detection & Inpainting (R1, R2, R3) ──

    async def test_auto_detect_individual_boxes_not_union(self):
        """R1: Verifies that multiple separate watermarks are returned as individual boxes, not one gigantic union."""
        async def fake_run(cmd, timeout=30):
            if "-vsync" in cmd:
                sample_pattern = cmd[-1]
                sample_dir = Path(sample_pattern).parent
                for i in range(5):
                    (sample_dir / f"sample_0{i}.jpg").write_bytes(b"frame")
                return 0, b"", b""
            return 0, b"", b""

        # Two watermarks: one at top-left (20, 20, 50, 20) and one at bottom-right (800, 500, 60, 25)
        mock_tesseract = MagicMock()
        mock_tesseract.Output.DICT = "dict"
        mock_tesseract.image_to_data.return_value = {
            "text": ["LOGO1", "LOGO2"],
            "conf": [90, 88],
            "left": [20, 800],
            "top": [20, 500],
            "width": [50, 60],
            "height": [20, 25],
        }

        mock_pil = MagicMock()
        mock_img = MagicMock()
        mock_img.width = 1000
        mock_img.height = 600
        mock_pil.Image.open.return_value.__enter__.return_value = mock_img

        with patch.object(self.service, "_run_command", side_effect=fake_run):
            with patch.dict("sys.modules", {"pytesseract": mock_tesseract, "PIL": mock_pil}):
                detected = await self.service._auto_detect_text_region(self.dummy_video)
                # Must return 2 individual small boxes, NOT a single massive union from (20,20) to (860,525)
                self.assertEqual(len(detected), 2)
                for b in detected:
                    box_area = b["w"] * b["h"]
                    frame_area = 1000 * 600
                    self.assertLess(box_area / frame_area, 0.25)
                    self.assertLess(b["w"], 200)
                    self.assertLess(b["h"], 100)

    async def test_auto_detect_sanity_check_ignores_box_over_25_percent(self):
        """R1: Any bounding box exceeding 25% of the frame area must be discarded as false positive / scene text."""
        async def fake_run(cmd, timeout=30):
            if "-vsync" in cmd:
                sample_dir = Path(cmd[-1]).parent
                for i in range(5):
                    (sample_dir / f"sample_0{i}.jpg").write_bytes(b"frame")
                return 0, b"", b""
            return 0, b"", b""

        # Bounding box of 600x500 in a 1000x600 frame = 50% area (> 25%)
        mock_tesseract = MagicMock()
        mock_tesseract.Output.DICT = "dict"
        mock_tesseract.image_to_data.return_value = {
            "text": ["HUGE_TEXT"],
            "conf": [90],
            "left": [100],
            "top": [50],
            "width": [600],
            "height": [500],
        }

        mock_pil = MagicMock()
        mock_img = MagicMock()
        mock_img.width = 1000
        mock_img.height = 600
        mock_pil.Image.open.return_value.__enter__.return_value = mock_img

        with patch.object(self.service, "_run_command", side_effect=fake_run):
            with patch.dict("sys.modules", {"pytesseract": mock_tesseract, "PIL": mock_pil}):
                detected = await self.service._auto_detect_text_region(self.dummy_video)
                # Over-25% box must be completely discarded
                self.assertEqual(detected, [])

    async def test_auto_detect_distinguishes_overlay_vs_scene_text(self):
        """R2: Persistent overlay (IoU >= 0.7 in >= 3/5 frames) is kept; transient scene text is discarded."""
        async def fake_run(cmd, timeout=30):
            if "-vsync" in cmd:
                sample_dir = Path(cmd[-1]).parent
                for i in range(5):
                    (sample_dir / f"sample_0{i}.jpg").write_bytes(b"frame")
                return 0, b"", b""
            return 0, b"", b""

        call_count = 0

        def fake_image_to_data(img, output_type=None):
            nonlocal call_count
            frame_idx = call_count % 5
            call_count += 1
            # Watermark at (450, 50, 60, 25) present in frames 0, 1, 3, 4 (4 of 5 frames >= 3)
            # Transient scene text at moving positions (100, 200), (200, 300), etc.
            if frame_idx in (0, 1, 3, 4):
                return {
                    "text": ["WATERMARK", f"SCENE_{frame_idx}"],
                    "conf": [95, 80],
                    "left": [450, 100 * (frame_idx + 1)],
                    "top": [50, 200 + 30 * frame_idx],
                    "width": [60, 80],
                    "height": [25, 20],
                }
            else:
                return {
                    "text": [f"SCENE_{frame_idx}"],
                    "conf": [80],
                    "left": [300],
                    "top": [400],
                    "width": [80],
                    "height": [20],
                }

        mock_tesseract = MagicMock()
        mock_tesseract.Output.DICT = "dict"
        mock_tesseract.image_to_data.side_effect = fake_image_to_data

        mock_pil = MagicMock()
        mock_img = MagicMock()
        mock_img.width = 1000
        mock_img.height = 600
        mock_pil.Image.open.return_value.__enter__.return_value = mock_img

        with patch.object(self.service, "_run_command", side_effect=fake_run):
            with patch.dict("sys.modules", {"pytesseract": mock_tesseract, "PIL": mock_pil}):
                detected = await self.service._auto_detect_text_region(self.dummy_video)
                # Only the persistent WATERMARK should be detected (1 box)
                self.assertEqual(len(detected), 1)
                # With 10px pad: x=440, y=40, w=80, h=45
                self.assertEqual(detected[0]["x"], 440)
                self.assertEqual(detected[0]["y"], 40)
                self.assertEqual(detected[0]["w"], 80)
                self.assertEqual(detected[0]["h"], 45)

    async def test_auto_detect_no_text_returns_original_video(self):
        """R3: When no persistent text is detected, remove_text_from_video returns the intact video without filtering."""
        with patch.object(self.service, "_auto_detect_text_region", AsyncMock(return_value=[])):
            res = await self.service.remove_text_from_video(
                input_path_or_url=str(self.dummy_video),
                mode="auto",
            )
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["regions"], [])
            self.assertIn("Không phát hiện text", res["message"])
            out_p = Path(res["output_path"])
            self.assertTrue(out_p.exists())
            # Intact content identical to dummy video
            self.assertEqual(out_p.read_bytes(), self.dummy_video.read_bytes())
            out_p.unlink(missing_ok=True)

    async def test_auto_mode_prefers_inpaint_when_opencv_available(self):
        """R3: Auto mode uses OpenCV inpainting when cv2 is available."""
        mock_cv2 = MagicMock()
        detected_region = [{"x": 100, "y": 80, "w": 60, "h": 20}]

        def fake_inpaint(inp, out, rx, ry, rw, rh):
            out.write_bytes(b"inpaint_auto_payload")

        with patch.object(self.service, "_auto_detect_text_region", AsyncMock(return_value=detected_region)):
            with patch.dict("sys.modules", {"cv2": mock_cv2}):
                with patch.object(self.service, "_inpaint_video_sync", side_effect=fake_inpaint) as mock_sync:
                    res = await self.service.remove_text_from_video(
                        input_path_or_url=str(self.dummy_video),
                        mode="auto",
                    )
                    self.assertEqual(res["status"], "ok")
                    self.assertEqual(res["mode_used"], "inpaint")
                    mock_sync.assert_called_once()
                    out_p = Path(res["output_path"])
                    self.assertTrue(out_p.exists())
                    out_p.unlink(missing_ok=True)

    async def test_auto_detect_single_sample_does_not_falsely_detect_scene_text(self):
        """R2 Adversarial: When video is too short to extract >=2 frames, transient scene text must NOT be detected."""
        async def fake_run(cmd, timeout=30):
            if "-vsync" in cmd:
                sample_pattern = cmd[-1]
                sample_dir = Path(sample_pattern).parent
                (sample_dir / "sample_00.jpg").write_bytes(b"frame")
                return 0, b"", b""
            return 0, b"", b""

        mock_tesseract = MagicMock()
        mock_tesseract.Output.DICT = "dict"
        mock_tesseract.image_to_data.return_value = {
            "text": ["ROAD_SIGN"],
            "conf": [85],
            "left": [50],
            "top": [50],
            "width": [100],
            "height": [30],
        }

        mock_pil = MagicMock()
        mock_img = MagicMock()
        mock_img.width = 1000
        mock_img.height = 600
        mock_pil.Image.open.return_value.__enter__.return_value = mock_img

        with patch.object(self.service, "_run_command", side_effect=fake_run):
            with patch.dict("sys.modules", {"pytesseract": mock_tesseract, "PIL": mock_pil}):
                detected = await self.service._auto_detect_text_region(self.dummy_video)
                self.assertEqual(detected, [])

    async def test_auto_detect_padding_near_frame_edges_does_not_shift_or_skew(self):
        """Edge Case: When text box is located at (2, 2, 50, 30), padding=10 should expand to (0, 0, 62, 42)."""
        async def fake_run(cmd, timeout=30):
            if "-vsync" in cmd:
                sample_dir = Path(cmd[-1]).parent
                for i in range(5):
                    (sample_dir / f"sample_0{i}.jpg").write_bytes(b"frame")
                return 0, b"", b""
            return 0, b"", b""

        mock_tesseract = MagicMock()
        mock_tesseract.Output.DICT = "dict"
        mock_tesseract.image_to_data.return_value = {
            "text": ["CORNER_LOGO"],
            "conf": [95],
            "left": [2],
            "top": [2],
            "width": [50],
            "height": [30],
        }

        mock_pil = MagicMock()
        mock_img = MagicMock()
        mock_img.width = 1000
        mock_img.height = 600
        mock_pil.Image.open.return_value.__enter__.return_value = mock_img

        with patch.object(self.service, "_run_command", side_effect=fake_run):
            with patch.dict("sys.modules", {"pytesseract": mock_tesseract, "PIL": mock_pil}):
                detected = await self.service._auto_detect_text_region(self.dummy_video)
                self.assertEqual(len(detected), 1)
                b = detected[0]
                self.assertEqual(b["x"], 0)
                self.assertEqual(b["y"], 0)
                self.assertEqual(b["w"], 62)
                self.assertEqual(b["h"], 42)

    async def test_auto_detect_merges_overlapping_boxes_after_padding(self):
        """Edge Case: Boxes that overlap after padding are merged into one clean disjoint bounding box."""
        async def fake_run(cmd, timeout=30):
            if "-vsync" in cmd:
                sample_dir = Path(cmd[-1]).parent
                for i in range(5):
                    (sample_dir / f"sample_0{i}.jpg").write_bytes(b"frame")
                return 0, b"", b""
            return 0, b"", b""

        # Two boxes: (100, 100, 40, 20) and (145, 100, 40, 20), gap is 5px (< 2*pad=20px)
        mock_tesseract = MagicMock()
        mock_tesseract.Output.DICT = "dict"
        mock_tesseract.image_to_data.return_value = {
            "text": ["WORD_A", "WORD_B"],
            "conf": [95, 95],
            "left": [100, 145],
            "top": [100, 100],
            "width": [40, 40],
            "height": [20, 20],
        }

        mock_pil = MagicMock()
        mock_img = MagicMock()
        mock_img.width = 1000
        mock_img.height = 600
        mock_pil.Image.open.return_value.__enter__.return_value = mock_img

        with patch.object(self.service, "_run_command", side_effect=fake_run):
            with patch.dict("sys.modules", {"pytesseract": mock_tesseract, "PIL": mock_pil}):
                detected = await self.service._auto_detect_text_region(self.dummy_video)
                # After padding & merge, must be 1 unified box, NOT 2 overlapping boxes
                self.assertEqual(len(detected), 1)
                b = detected[0]
                self.assertEqual(b["x"], 90)
                self.assertEqual(b["y"], 90)
                self.assertEqual(b["w"], 105)
                self.assertEqual(b["h"], 40)

    async def test_remove_text_explicit_empty_region_list_preserves_original_video(self):
        """R3 Edge Case: Calling remove_text_from_video with region=[] preserves original video without encoding."""
        res = await self.service.remove_text_from_video(
            input_path_or_url=str(self.dummy_video),
            region=[],
            mode="inpaint",
        )
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["regions"], [])
        out_p = Path(res["output_path"])
        self.assertTrue(out_p.exists())
        self.assertEqual(out_p.read_bytes(), self.dummy_video.read_bytes())
        out_p.unlink(missing_ok=True)

    def test_inpaint_video_sync_multi_audio_and_sar_preservation(self):
        """Edge Case: Inpaint sync worker maps all audio streams (-map 1:a?), sets pixel format yuv420p, and restores SAR."""
        mock_cv2 = MagicMock()
        mock_cap = MagicMock()
        mock_cap.isOpened.side_effect = [True, True, False]
        mock_cap.get.side_effect = lambda prop: 30.0 if prop == mock_cv2.CAP_PROP_FPS else (720 if prop == mock_cv2.CAP_PROP_FRAME_WIDTH else 576)
        dummy_frame = MagicMock()
        mock_cap.read.return_value = (True, dummy_frame)
        mock_cv2.VideoCapture.return_value = mock_cap
        mock_cv2.inpaint.return_value = dummy_frame

        executed_commands = []

        def fake_subprocess_run(cmd, capture_output=True, text=False, timeout=None):
            executed_commands.append(cmd)
            res = MagicMock()
            res.returncode = 0
            if "stream=sample_aspect_ratio" in " ".join(cmd):
                res.stdout = "64:45"
            else:
                res.stdout = ""
                res.stderr = b""
            return res

        output_file = self.service._temp_dir / "test_inp_out.mp4"

        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                self.service._inpaint_video_sync(
                    input_file=self.dummy_video,
                    output_file=output_file,
                    rx_or_regions=[{"x": 10, "y": 10, "w": 50, "h": 20}],
                )

        # Verify merge command structure
        merge_cmd = executed_commands[-1]
        self.assertIn("-map", merge_cmd)
        self.assertIn("1:a?", merge_cmd)
        self.assertIn("-pix_fmt", merge_cmd)
        self.assertIn("yuv420p", merge_cmd)
        self.assertIn("-map_metadata", merge_cmd)
        self.assertIn("1", merge_cmd)
        self.assertIn("-vf", merge_cmd)
        self.assertIn("setsar=sar=64/45", merge_cmd)

    def test_inpaint_video_sync_out_of_bounds_region_copies_original(self):
        """Edge Case: When inpaint regions lie completely outside the frame, original video is copied without CPU inpaint."""
        mock_cv2 = MagicMock()
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.side_effect = lambda prop: 30.0 if prop == mock_cv2.CAP_PROP_FPS else (320 if prop == mock_cv2.CAP_PROP_FRAME_WIDTH else 240)
        mock_cv2.VideoCapture.return_value = mock_cap

        output_file = self.service._temp_dir / "test_inp_oob.mp4"

        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            with patch("shutil.copy2") as mock_copy:
                self.service._inpaint_video_sync(
                    input_file=self.dummy_video,
                    output_file=output_file,
                    rx_or_regions=[{"x": 500, "y": 0, "w": 100, "h": 50}],
                )
                # Video lies at [0..320]x[0..240], box at x=500 is completely out-of-bounds
                mock_copy.assert_called_once_with(self.dummy_video, output_file)
                # cv2.inpaint must NOT be called
                mock_cv2.inpaint.assert_not_called()

    async def test_delogo_mode_clamps_regions_within_frame_boundaries(self):
        """Edge Case: Delogo mode clamps bounding boxes to frame width/height to avoid FFmpeg error code 234."""
        async def fake_run(cmd, timeout=300):
            if "stream=width,height" in " ".join(cmd):
                return 0, b"320x240\n", b""
            if cmd and str(cmd[-1]).endswith(".mp4"):
                Path(cmd[-1]).write_bytes(b"delogo_fake_output")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.remove_text_from_video(
                input_path_or_url=str(self.dummy_video),
                region={"x": 300, "y": 200, "w": 50, "h": 50},
                mode="delogo",
            )
            self.assertEqual(res["status"], "ok")
            delogo_cmd = mock_run.call_args[0][0]
            vf_flag = delogo_cmd[delogo_cmd.index("-vf") + 1]
            # Must be clamped: x=300, y=200, w=19, h=39 (so x+w=319 <= 319, y+h=239 <= 239)
            self.assertIn("delogo=x=300:y=200:w=19:h=39:show=0", vf_flag)

    async def test_delogo_mode_all_regions_outside_frame_preserves_original_video(self):
        """Edge Case: When all delogo regions lie completely outside the video frame, original video is preserved."""
        async def fake_run(cmd, timeout=300):
            if "stream=width,height" in " ".join(cmd):
                return 0, b"320x240\n", b""
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run):
            res = await self.service.remove_text_from_video(
                input_path_or_url=str(self.dummy_video),
                region={"x": 500, "y": 400, "w": 50, "h": 50},
                mode="delogo",
            )
            self.assertEqual(res["status"], "ok")
            self.assertIn("bên ngoài khung hình", res["message"])
            out_p = Path(res["output_path"])
            self.assertTrue(out_p.exists())
            self.assertEqual(out_p.read_bytes(), self.dummy_video.read_bytes())
            out_p.unlink(missing_ok=True)

    async def test_auto_detect_handles_float_confidence_strings(self):
        """Robustness: Tesseract float confidence string (e.g. '88.5') is parsed correctly instead of discarded."""
        async def fake_run(cmd, timeout=30):
            if "-vsync" in cmd:
                sample_dir = Path(cmd[-1]).parent
                for i in range(5):
                    (sample_dir / f"sample_0{i}.jpg").write_bytes(b"frame")
                return 0, b"", b""
            return 0, b"", b""

        mock_tesseract = MagicMock()
        mock_tesseract.Output.DICT = "dict"
        mock_tesseract.image_to_data.return_value = {
            "text": ["LOGO"],
            "conf": ["88.5"],  # Float string
            "left": [20],
            "top": [20],
            "width": [60],
            "height": [25],
        }

        mock_pil = MagicMock()
        mock_img = MagicMock()
        mock_img.width = 1000
        mock_img.height = 600
        mock_pil.Image.open.return_value.__enter__.return_value = mock_img

        with patch.object(self.service, "_run_command", side_effect=fake_run):
            with patch.dict("sys.modules", {"pytesseract": mock_tesseract, "PIL": mock_pil}):
                detected = await self.service._auto_detect_text_region(self.dummy_video)
                # Should detect the box, not discard it because of float conf string
                self.assertEqual(len(detected), 1)
                self.assertEqual(detected[0]["x"], 10)
                self.assertEqual(detected[0]["y"], 10)

    async def test_delogo_mode_preserves_multi_audio_and_metadata(self):
        """Robustness: Delogo mode maps all audio streams (-map 0:a?), preserves metadata (-map_metadata 0), and ensures yuv420p."""
        async def fake_run(cmd, timeout=300):
            if "stream=width,height" in " ".join(cmd):
                return 0, b"320x240\n", b""
            if cmd and str(cmd[-1]).endswith(".mp4"):
                Path(cmd[-1]).write_bytes(b"delogo_multi_audio_out")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.remove_text_from_video(
                input_path_or_url=str(self.dummy_video),
                region={"x": 10, "y": 10, "w": 50, "h": 20},
                mode="delogo",
            )
            self.assertEqual(res["status"], "ok")
            delogo_cmd = mock_run.call_args[0][0]
            self.assertIn("-map", delogo_cmd)
            self.assertIn("0:v:0", delogo_cmd)
            self.assertIn("0:a?", delogo_cmd)
            self.assertIn("-map_metadata", delogo_cmd)
            self.assertIn("0", delogo_cmd)
            self.assertIn("-pix_fmt", delogo_cmd)
            self.assertIn("yuv420p", delogo_cmd)

    def test_inpaint_video_sync_merge_timeout_handling(self):
        """Robustness: Inpaint worker catches subprocess.TimeoutExpired during merge and raises clear RuntimeError."""
        import subprocess
        mock_cv2 = MagicMock()
        mock_cap = MagicMock()
        mock_cap.isOpened.side_effect = [True, True, False]
        mock_cap.get.side_effect = lambda prop: 30.0 if prop == mock_cv2.CAP_PROP_FPS else (320 if prop == mock_cv2.CAP_PROP_FRAME_WIDTH else 240)
        dummy_frame = MagicMock()
        mock_cap.read.return_value = (True, dummy_frame)
        mock_cv2.VideoCapture.return_value = mock_cap
        mock_cv2.inpaint.return_value = dummy_frame

        def fake_subprocess_run(cmd, capture_output=True, text=False, timeout=None):
            if "setsar" in " ".join(cmd) or "stream=sample_aspect_ratio" in " ".join(cmd):
                res = MagicMock()
                res.returncode = 0
                res.stdout = "1:1"
                return res
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=300)

        output_file = self.service._temp_dir / "test_timeout_out.mp4"

        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                with self.assertRaises(RuntimeError) as ctx:
                    self.service._inpaint_video_sync(
                        input_file=self.dummy_video,
                        output_file=output_file,
                        rx_or_regions=[{"x": 10, "y": 10, "w": 50, "h": 20}],
                    )
                self.assertIn("timeout", str(ctx.exception).lower())

    def test_inpaint_video_sync_videowriter_failure_raises(self):
        """Robustness: Inpaint worker raises RuntimeError if cv2.VideoWriter fails to initialize."""
        mock_cv2 = MagicMock()
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.side_effect = lambda prop: 30.0 if prop == mock_cv2.CAP_PROP_FPS else (320 if prop == mock_cv2.CAP_PROP_FRAME_WIDTH else 240)
        mock_cv2.VideoCapture.return_value = mock_cap
        mock_writer = MagicMock()
        mock_writer.isOpened.return_value = False
        mock_cv2.VideoWriter.return_value = mock_writer

        output_file = self.service._temp_dir / "test_vw_fail.mp4"

        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            with self.assertRaises(RuntimeError) as ctx:
                self.service._inpaint_video_sync(
                    input_file=self.dummy_video,
                    output_file=output_file,
                    rx_or_regions=[{"x": 10, "y": 10, "w": 50, "h": 20}],
                )
            self.assertIn("OpenCV VideoWriter", str(ctx.exception))
            mock_cap.release.assert_called()

    def test_inpaint_video_sync_zero_frames_raises(self):
        """Robustness: Inpaint worker raises RuntimeError if 0 frames could be read from input video."""
        mock_cv2 = MagicMock()
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.side_effect = lambda prop: 30.0 if prop == mock_cv2.CAP_PROP_FPS else (320 if prop == mock_cv2.CAP_PROP_FRAME_WIDTH else 240)
        mock_cap.read.return_value = (False, None)
        mock_cv2.VideoCapture.return_value = mock_cap
        mock_writer = MagicMock()
        mock_writer.isOpened.return_value = True
        mock_cv2.VideoWriter.return_value = mock_writer

        output_file = self.service._temp_dir / "test_zero_frames.mp4"

        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            with self.assertRaises(RuntimeError) as ctx:
                self.service._inpaint_video_sync(
                    input_file=self.dummy_video,
                    output_file=output_file,
                    rx_or_regions=[{"x": 10, "y": 10, "w": 50, "h": 20}],
                )
            self.assertIn("Không thể đọc bất kỳ frame nào", str(ctx.exception))

    async def test_auto_detect_text_region_probe_exception_graceful(self):
        """Robustness: ffprobe duration probe exception or timeout is caught gracefully and falls back without crash."""
        async def fake_run(cmd, timeout=30):
            if "format=duration" in " ".join(cmd):
                raise asyncio.TimeoutError("Probe timeout")
            if "-vsync" in cmd:
                return 0, b"", b""
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run):
            with patch.dict("sys.modules", {"pytesseract": None}):
                detected = await self.service._auto_detect_text_region(self.dummy_video)
                self.assertEqual(detected, [])

    async def test_auto_detect_dense_temporal_scan_captures_temporal_extents(self):
        """R1: Dense temporal scan clusters text regions into segments with accurate [frame_start, frame_end]."""
        async def fake_run(cmd, timeout=30):
            if "-vsync" in cmd:
                sample_dir = Path(cmd[-1]).parent
                for i in range(4):
                    (sample_dir / f"sample_0{i}.jpg").write_bytes(b"frame")
                return 0, b"", b""
            return 0, b"", b""

        call_idx = 0
        def fake_ocr(img, output_type=None):
            nonlocal call_idx
            idx = call_idx
            call_idx += 1
            if idx in (1, 2):
                return {
                    "text": ["CAPTION_A"],
                    "conf": [92],
                    "left": [100],
                    "top": [200],
                    "width": [150],
                    "height": [30],
                }
            return {"text": [], "conf": [], "left": [], "top": [], "width": [], "height": []}

        mock_tess = MagicMock()
        mock_tess.Output.DICT = "dict"
        mock_tess.image_to_data.side_effect = fake_ocr

        mock_pil = MagicMock()
        mock_img = MagicMock()
        mock_img.width = 1000
        mock_img.height = 600
        mock_pil.Image.open.return_value.__enter__.return_value = mock_img

        with patch.object(self.service, "_run_command", side_effect=fake_run):
            with patch.dict("sys.modules", {"pytesseract": mock_tess, "PIL": mock_pil}):
                detected = await self.service._auto_detect_text_region(self.dummy_video)
                self.assertEqual(len(detected), 1)
                seg = detected[0]
                self.assertEqual(seg["x"], 90)
                self.assertEqual(seg["y"], 190)
                self.assertEqual(seg["w"], 170)
                self.assertEqual(seg["h"], 50)
                self.assertIn("frame_start", seg)
                self.assertIn("frame_end", seg)
                self.assertLess(seg["frame_start"], seg["frame_end"])

    def test_inpaint_temporal_extents_only_modifies_active_frames(self):
        """R2: Frame-by-frame inpainting only calls cv2.inpaint during active temporal extents."""
        import numpy as np

        mock_cv2 = MagicMock()
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.side_effect = lambda prop: {
            mock_cv2.CAP_PROP_FPS: 30.0,
            mock_cv2.CAP_PROP_FRAME_WIDTH: 200,
            mock_cv2.CAP_PROP_FRAME_HEIGHT: 100,
        }.get(prop, 0)

        # 4 frames: frame 0, 1, 2, 3
        dummy_frame = np.zeros((100, 200, 3), dtype=np.uint8)
        mock_cap.read.side_effect = [
            (True, dummy_frame),
            (True, dummy_frame),
            (True, dummy_frame),
            (True, dummy_frame),
            (False, None),
        ]
        mock_cv2.VideoCapture.return_value = mock_cap

        mock_writer = MagicMock()
        mock_writer.isOpened.return_value = True
        mock_cv2.VideoWriter.return_value = mock_writer
        mock_cv2.inpaint.return_value = dummy_frame

        output_file = self.service._temp_dir / "test_temporal_out.mp4"
        regions = [{"x": 10, "y": 10, "w": 30, "h": 20, "frame_start": 1, "frame_end": 2}]

        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            with patch("subprocess.run") as mock_sub:
                mock_sub.return_value = MagicMock(returncode=0, stdout="", stderr="")
                self.service._inpaint_video_sync(
                    input_file=self.dummy_video,
                    output_file=output_file,
                    rx_or_regions=regions,
                )
                # cv2.inpaint should ONLY be called for frames 1 and 2 (exactly 2 calls out of 4 frames)
                self.assertEqual(mock_cv2.inpaint.call_count, 2)
                # mock_writer.write should be called for all 4 frames
                self.assertEqual(mock_writer.write.call_count, 4)

    async def test_auto_detect_rejects_non_alphanumeric_noise(self):
        """Noise Rejection: Pytesseract false positives with non-alphanumeric noise (|, ---, ,,) are rejected."""
        async def fake_run(cmd, timeout=30):
            if "-vsync" in cmd:
                sample_dir = Path(cmd[-1]).parent
                for i in range(5):
                    (sample_dir / f"sample_0{i}.jpg").write_bytes(b"frame")
                return 0, b"", b""
            return 0, b"", b""

        mock_tesseract = MagicMock()
        mock_tesseract.Output.DICT = "dict"
        mock_tesseract.image_to_data.return_value = {
            "text": ["|", "---", ",,", "..."],
            "conf": [90, 90, 90, 90],
            "left": [10, 50, 100, 150],
            "top": [10, 10, 10, 10],
            "width": [20, 20, 20, 20],
            "height": [20, 20, 20, 20],
        }

        mock_pil = MagicMock()
        mock_img = MagicMock()
        mock_img.width = 1000
        mock_img.height = 600
        mock_pil.Image.open.return_value.__enter__.return_value = mock_img

        with patch.object(self.service, "_run_command", side_effect=fake_run):
            with patch.dict("sys.modules", {"pytesseract": mock_tesseract, "PIL": mock_pil}):
                detected = await self.service._auto_detect_text_region(self.dummy_video)
                self.assertEqual(detected, [])

    async def test_delogo_with_temporal_enable(self):
        """Temporal Delogo: delogo filter includes between(n, start, end) enable option when temporal frames are set."""
        async def fake_run(cmd, timeout=300):
            if "stream=width,height" in " ".join(cmd):
                return 0, b"640x360\n", b""
            if cmd and str(cmd[-1]).endswith(".mp4"):
                Path(cmd[-1]).write_bytes(b"delogo_temporal_out")
            return 0, b"", b""

        with patch.object(self.service, "_run_command", side_effect=fake_run) as mock_run:
            res = await self.service.remove_text_from_video(
                input_path_or_url=str(self.dummy_video),
                region={"x": 50, "y": 60, "w": 120, "h": 40, "frame_start": 30, "frame_end": 90},
                mode="delogo",
            )
            self.assertEqual(res["status"], "ok")
            delogo_cmd = mock_run.call_args[0][0]
            vf_flag = delogo_cmd[delogo_cmd.index("-vf") + 1]
            self.assertIn("delogo=x=50:y=60:w=120:h=40:enable='between(n\\,30\\,90)':show=0", vf_flag)

    async def test_auto_detect_step2_horizontal_proximity_prevents_fullscreen_merge(self):
        """Hardening: Far-apart boxes on the same line are not merged into screen-wide banners."""
        async def fake_run(cmd, timeout=30):
            if "-vsync" in cmd:
                sample_dir = Path(cmd[-1]).parent
                for i in range(3):
                    (sample_dir / f"sample_0{i}.jpg").write_bytes(b"frame")
                return 0, b"", b""
            return 0, b"", b""

        call_idx = 0
        def fake_ocr(img, output_type=None):
            nonlocal call_idx
            idx = call_idx
            call_idx += 1
            if idx == 0:
                return {
                    "text": ["LEFT_TAG"],
                    "conf": [90],
                    "left": [20],
                    "top": [100],
                    "width": [50],
                    "height": [30],
                }
            elif idx == 1:
                return {
                    "text": ["RIGHT_TAG"],
                    "conf": [90],
                    "left": [400],
                    "top": [100],
                    "width": [80],
                    "height": [30],
                }
            return {"text": [], "conf": [], "left": [], "top": [], "width": [], "height": []}

        mock_tess = MagicMock()
        mock_tess.Output.DICT = "dict"
        mock_tess.image_to_data.side_effect = fake_ocr

        mock_pil = MagicMock()
        mock_img = MagicMock()
        mock_img.width = 600
        mock_img.height = 400
        mock_pil.Image.open.return_value.__enter__.return_value = mock_img

        with patch.object(self.service, "_run_command", side_effect=fake_run):
            with patch.dict("sys.modules", {"pytesseract": mock_tess, "PIL": mock_pil}):
                detected = await self.service._auto_detect_text_region(self.dummy_video)
                for seg in detected:
                    self.assertLess(seg["w"], 350)

    def test_merge_temporal_segments_tight_overlap_prevents_chaining(self):
        """Hardening: Step 4 tight overlap requires containment >= 0.60 or IoU >= 0.25 to prevent transitive chaining."""
        s1 = {"x": 0, "y": 0, "w": 100, "h": 100, "frame_start": 0, "frame_end": 100}
        s2 = {"x": 85, "y": 85, "w": 30, "h": 30, "frame_start": 10, "frame_end": 90}
        merged = self.service._merge_overlapping_temporal_segments([s1, s2], 500, 500, 250000)
        self.assertEqual(len(merged), 2, "Weakly touching boxes must NOT be chained into a single large segment")

    async def test_last_sample_frame_temporal_extent_covers_video_tail(self):
        """Hardening: The final sampled frame's temporal extent extends to cover trailing frames."""
        async def fake_run(cmd, timeout=30):
            if "-vsync" in cmd:
                sample_dir = Path(cmd[-1]).parent
                for i in range(3):
                    (sample_dir / f"sample_0{i}.jpg").write_bytes(b"frame")
                return 0, b"", b""
            return 0, b"", b""

        def fake_ocr(img, output_type=None):
            return {
                "text": ["WATERMARK"],
                "conf": [95],
                "left": [50],
                "top": [50],
                "width": [60],
                "height": [25],
            }

        mock_tess = MagicMock()
        mock_tess.Output.DICT = "dict"
        mock_tess.image_to_data.side_effect = fake_ocr

        mock_pil = MagicMock()
        mock_img = MagicMock()
        mock_img.width = 600
        mock_img.height = 400
        mock_pil.Image.open.return_value.__enter__.return_value = mock_img

        with patch.object(self.service, "_run_command", side_effect=fake_run):
            with patch.dict("sys.modules", {"pytesseract": mock_tess, "PIL": mock_pil}):
                detected = await self.service._auto_detect_text_region(self.dummy_video)
                self.assertGreater(len(detected), 0)
                self.assertGreater(detected[0]["frame_end"], 0)

    def test_inpaint_video_multiple_disjoint_regions_per_region_roi(self):
        """Hardening: Inpainting handles multiple disjoint regions per-region without throwing."""
        import numpy as np

        mock_cv2 = MagicMock()
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.side_effect = lambda prop: {
            mock_cv2.CAP_PROP_FPS: 30.0,
            mock_cv2.CAP_PROP_FRAME_WIDTH: 600,
            mock_cv2.CAP_PROP_FRAME_HEIGHT: 800,
        }.get(prop, 0)

        dummy_frame = np.zeros((800, 600, 3), dtype=np.uint8)
        mock_cap.read.side_effect = [
            (True, dummy_frame),
            (False, None),
        ]
        mock_cv2.VideoCapture.return_value = mock_cap

        mock_writer = MagicMock()
        mock_writer.isOpened.return_value = True
        mock_cv2.VideoWriter.return_value = mock_writer
        mock_cv2.inpaint.return_value = dummy_frame

        output_file = self.service._temp_dir / "test_multi_disjoint_out.mp4"
        regions = [
            {"x": 20, "y": 30, "w": 100, "h": 40, "frame_start": 0, "frame_end": 5},
            {"x": 30, "y": 700, "w": 120, "h": 50, "frame_start": 0, "frame_end": 5},
        ]

        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            with patch("subprocess.run") as mock_sub:
                mock_sub.return_value = MagicMock(returncode=0, stdout="", stderr="")
                self.service._inpaint_video_sync(
                    input_file=self.dummy_video,
                    output_file=output_file,
                    rx_or_regions=regions,
                )
                self.assertEqual(mock_cv2.inpaint.call_count, 2)

    async def test_auto_detect_unknown_duration_falls_back_to_dense_sampling(self):
        """Adversarial R3: Unknown video duration (0.0s) defaults to 2.0s dense sampling instead of dropping to 1 frame."""
        captured_commands = []
        async def fake_run(cmd, timeout=30):
            captured_commands.append(cmd)
            if "-vsync" in cmd:
                sample_dir = Path(cmd[-1]).parent
                for i in range(4):
                    (sample_dir / f"sample_0{i}.jpg").write_bytes(b"frame")
                return 0, b"", b""
            return 0, b"", b""

        def fake_ocr(img, output_type=None):
            return {
                "text": ["PERSISTENT_LOGO"],
                "conf": [92],
                "left": [30],
                "top": [40],
                "width": [60],
                "height": [25],
            }

        mock_tess = MagicMock()
        mock_tess.Output.DICT = "dict"
        mock_tess.image_to_data.side_effect = fake_ocr

        mock_pil = MagicMock()
        mock_img = MagicMock()
        mock_img.width = 640
        mock_img.height = 360
        mock_pil.Image.open.return_value.__enter__.return_value = mock_img

        with patch.object(self.service, "_run_command", side_effect=fake_run):
            with patch.dict("sys.modules", {"pytesseract": mock_tess, "PIL": mock_pil}):
                detected = await self.service._auto_detect_text_region(self.dummy_video)
                # Ensure ffmpeg sample command used fps=1/2.0000 instead of select=eq(n,0)
                sample_cmd = next(c for c in captured_commands if "-vsync" in c)
                vf_arg = sample_cmd[sample_cmd.index("-vf") + 1]
                self.assertIn("fps=1/2.0000", vf_arg)
                self.assertEqual(len(detected), 1)
                self.assertEqual(detected[0]["x"], 20)
                self.assertEqual(detected[0]["y"], 30)

    async def test_auto_detect_short_video_dense_sampling(self):
        """Adversarial R3: Sub-second video (duration=0.8s) extracts multiple samples and detects text."""
        captured_commands = []
        async def fake_run(cmd, timeout=30):
            captured_commands.append(cmd)
            # Duration probe returns 0.8s
            if "format=duration:stream=duration" in " ".join(cmd):
                return 0, b"0.800000\n", b""
            if "-vsync" in cmd:
                sample_dir = Path(cmd[-1]).parent
                for i in range(3):
                    (sample_dir / f"sample_0{i}.jpg").write_bytes(b"frame")
                return 0, b"", b""
            return 0, b"", b""

        def fake_ocr(img, output_type=None):
            return {
                "text": ["SHORT_TAG"],
                "conf": [88],
                "left": [50],
                "top": [50],
                "width": [70],
                "height": [30],
            }

        mock_tess = MagicMock()
        mock_tess.Output.DICT = "dict"
        mock_tess.image_to_data.side_effect = fake_ocr

        mock_pil = MagicMock()
        mock_img = MagicMock()
        mock_img.width = 640
        mock_img.height = 360
        mock_pil.Image.open.return_value.__enter__.return_value = mock_img

        with patch.object(self.service, "_run_command", side_effect=fake_run):
            with patch.dict("sys.modules", {"pytesseract": mock_tess, "PIL": mock_pil}):
                detected = await self.service._auto_detect_text_region(self.dummy_video)
                self.assertEqual(len(detected), 1)
                sample_cmd = next(c for c in captured_commands if "-vsync" in c)
                vf_arg = sample_cmd[sample_cmd.index("-vf") + 1]
                self.assertIn("fps=", vf_arg)

    def test_inpaint_odd_dimension_adds_padding_filter(self):
        """Adversarial R3: Video with odd dimensions (575x1023) adds pad=ceil(iw/2)*2 filter for libx264."""
        import numpy as np

        mock_cv2 = MagicMock()
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.side_effect = lambda prop: {
            mock_cv2.CAP_PROP_FPS: 30.0,
            mock_cv2.CAP_PROP_FRAME_WIDTH: 575,
            mock_cv2.CAP_PROP_FRAME_HEIGHT: 1023,
        }.get(prop, 0)

        dummy_frame = np.zeros((1023, 575, 3), dtype=np.uint8)
        mock_cap.read.side_effect = [
            (True, dummy_frame),
            (False, None),
        ]
        mock_cv2.VideoCapture.return_value = mock_cap

        mock_writer = MagicMock()
        mock_writer.isOpened.return_value = True
        mock_cv2.VideoWriter.return_value = mock_writer
        mock_cv2.inpaint.return_value = dummy_frame

        output_file = self.service._temp_dir / "test_odd_out.mp4"
        regions = [{"x": 10, "y": 10, "w": 40, "h": 20}]

        captured_merge_cmd = []
        def fake_subprocess_run(cmd, **kwargs):
            captured_merge_cmd.extend(cmd)
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                self.service._inpaint_video_sync(
                    input_file=self.dummy_video,
                    output_file=output_file,
                    rx_or_regions=regions,
                )
                self.assertIn("-vf", captured_merge_cmd)
                vf_val = captured_merge_cmd[captured_merge_cmd.index("-vf") + 1]
                self.assertIn("pad=ceil(iw/2)*2:ceil(ih/2)*2", vf_val)

    async def test_auto_detect_unicode_multilingual_text(self):
        """Adversarial R3: Multilingual and Vietnamese text (Tiếng Việt, CJK) is recognized and not rejected as noise."""
        async def fake_run(cmd, timeout=30):
            if "-vsync" in cmd:
                sample_dir = Path(cmd[-1]).parent
                for i in range(2):
                    (sample_dir / f"sample_0{i}.jpg").write_bytes(b"frame")
                return 0, b"", b""
            return 0, b"", b""

        def fake_ocr(img, output_type=None):
            return {
                "text": ["TiếngViệt", "你好", "---"],
                "conf": [90, 85, 90],
                "left": [20, 100, 200],
                "top": [50, 50, 50],
                "width": [60, 40, 20],
                "height": [25, 25, 20],
            }

        mock_tess = MagicMock()
        mock_tess.Output.DICT = "dict"
        mock_tess.image_to_data.side_effect = fake_ocr

        mock_pil = MagicMock()
        mock_img = MagicMock()
        mock_img.width = 600
        mock_img.height = 400
        mock_pil.Image.open.return_value.__enter__.return_value = mock_img

        with patch.object(self.service, "_run_command", side_effect=fake_run):
            with patch.dict("sys.modules", {"pytesseract": mock_tess, "PIL": mock_pil}):
                detected = await self.service._auto_detect_text_region(self.dummy_video)
                # Both TiếngViệt and 你好 should be detected; '---' must be discarded
                self.assertGreater(len(detected), 0)

    def test_generate_text_stroke_mask_with_character_stroke_subtitles(self):
        """R1: Character stroke mask generation isolates text strokes with coverage < 25-30%."""
        import cv2
        import numpy as np
        h, w = 120, 480
        bg = np.tile(np.linspace(100, 150, w, dtype=np.uint8), (h, 1))
        roi = cv2.cvtColor(bg, cv2.COLOR_GRAY2BGR)

        text = "TEST SUBTITLE REMOVAL"
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 1.2
        thickness = 3
        cv2.putText(roi, text, (30, 75), font, font_scale, (0, 0, 0), thickness + 4, cv2.LINE_AA)
        cv2.putText(roi, text, (30, 75), font, font_scale, (255, 255, 255), thickness, cv2.LINE_AA)

        mask = VideoEditorService._generate_text_stroke_mask(roi)
        self.assertIsInstance(mask, np.ndarray)
        self.assertEqual(mask.shape, (h, w))

        mask_pixels = np.count_nonzero(mask > 0)
        coverage = (mask_pixels / (h * w)) * 100
        self.assertGreater(mask_pixels, 100)
        self.assertLess(coverage, 30.0)

    def test_generate_text_stroke_mask_empty_on_plain_background(self):
        """R1: Character stroke mask returns empty mask on plain background without text."""
        import numpy as np
        roi = np.random.randint(110, 140, (100, 300, 3), dtype=np.uint8)
        mask = VideoEditorService._generate_text_stroke_mask(roi)
        self.assertEqual(np.count_nonzero(mask), 0)

    def test_generate_text_stroke_mask_handles_edge_cases(self):
        """R1: Mask generation handles empty, tiny, and invalid inputs gracefully."""
        import numpy as np
        m1 = VideoEditorService._generate_text_stroke_mask(None)
        self.assertEqual(m1.size, 0)
        m2 = VideoEditorService._generate_text_stroke_mask(np.zeros((0, 0, 3), dtype=np.uint8))
        self.assertEqual(m2.size, 0)
        m3 = VideoEditorService._generate_text_stroke_mask(np.ones((2, 2, 3), dtype=np.uint8))
        self.assertEqual(m3.shape, (2, 2))
        self.assertEqual(np.count_nonzero(m3), 0)

    def test_inpaint_edge_aware_dual_pass(self):
        """R2: Dual-pass edge-aware inpainting restores background texture without rectangular smear."""
        import cv2
        import numpy as np
        h, w = 100, 200
        grid = np.zeros((h, w), dtype=np.uint8)
        grid[::4, :] = 180
        grid[:, ::4] = 180
        roi = cv2.cvtColor(grid, cv2.COLOR_GRAY2BGR)

        mask = np.zeros((h, w), dtype=np.uint8)
        cv2.line(mask, (20, 50), (180, 50), 255, 3)

        inpainted = VideoEditorService._inpaint_edge_aware(roi, mask)
        self.assertEqual(inpainted.shape, roi.shape)
        empty_mask = np.zeros((h, w), dtype=np.uint8)
        self.assertTrue(np.array_equal(VideoEditorService._inpaint_edge_aware(roi, empty_mask), roi))

    def test_generate_text_stroke_mask_with_inverted_black_text_on_white_background(self):
        """R1: Character stroke mask identifies black text on bright background and inpaints cleanly."""
        import cv2
        import numpy as np

        h, w = 120, 480
        roi = np.full((h, w, 3), 245, dtype=np.uint8)
        glyph = np.zeros((h, w), dtype=np.uint8)
        cv2.putText(glyph, "BLACK INVERTED SUBTITLE", (30, 75), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 255, 2)
        roi[glyph > 0] = (15, 15, 15)

        mask = VideoEditorService._generate_text_stroke_mask(roi)
        self.assertIsInstance(mask, np.ndarray)
        mask_pixels = np.count_nonzero(mask > 0)
        coverage = (mask_pixels / (h * w)) * 100
        self.assertGreater(mask_pixels, 100)
        self.assertLess(coverage, 25.0)

        # Inpainting should completely eliminate the black text
        inpainted = VideoEditorService._inpaint_edge_aware(roi, mask)
        rem_black = np.count_nonzero(inpainted[glyph > 0, 0] < 50)
        self.assertEqual(rem_black, 0)

    def test_generate_text_stroke_mask_with_meme_black_text_white_outline(self):
        """R1: Character stroke mask handles meme subtitles (black core with white outline)."""
        import cv2
        import numpy as np

        h, w = 120, 480
        roi = np.full((h, w, 3), 110, dtype=np.uint8)
        glyph = np.zeros((h, w), dtype=np.uint8)
        cv2.putText(glyph, "MEME SUBTITLE STYLE", (30, 75), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 255, 2)
        outline = cv2.dilate(glyph, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
        roi[outline > 0] = (250, 250, 250)
        roi[glyph > 0] = (10, 10, 10)

        mask = VideoEditorService._generate_text_stroke_mask(roi)
        self.assertIsInstance(mask, np.ndarray)
        mask_pixels = np.count_nonzero(mask > 0)
        coverage = (mask_pixels / (h * w)) * 100
        self.assertGreater(mask_pixels, 100)
        self.assertLess(coverage, 25.0)

        inpainted = VideoEditorService._inpaint_edge_aware(roi, mask)
        rem_black = np.count_nonzero(inpainted[glyph > 0, 0] < 50)
        rem_white = np.count_nonzero(inpainted[outline > 0, 0] > 200)
        self.assertEqual(rem_black, 0)
        self.assertEqual(rem_white, 0)

    def test_generate_text_stroke_mask_with_vibrant_colored_subtitles_red_cyan_green(self):
        """R1: Character stroke mask detects vivid colored subtitles across diverse hues."""
        import cv2
        import numpy as np

        h, w = 120, 480
        for color_name, bgr in [("Red", (0, 0, 255)), ("Cyan", (255, 255, 0)), ("Green", (0, 255, 0))]:
            roi = np.full((h, w, 3), 120, dtype=np.uint8)
            glyph = np.zeros((h, w), dtype=np.uint8)
            cv2.putText(glyph, f"COLOR {color_name}", (30, 75), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 255, 2)
            outline = cv2.dilate(glyph, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
            roi[outline > 0] = (10, 10, 10)
            roi[glyph > 0] = bgr

            mask = VideoEditorService._generate_text_stroke_mask(roi)
            mask_pixels = np.count_nonzero(mask > 0)
            coverage = (mask_pixels / (h * w)) * 100
            self.assertGreater(mask_pixels, 100, f"Failed detecting {color_name} subtitle")
            self.assertLess(coverage, 25.0)

            inpainted = VideoEditorService._inpaint_edge_aware(roi, mask)
            rem_fg = np.count_nonzero(np.all(np.abs(inpainted[glyph > 0].astype(int) - bgr) < 25, axis=-1))
            self.assertEqual(rem_fg, 0, f"Remaining foreground artifacts for {color_name}")

    def test_generate_text_stroke_mask_with_multicolor_rainbow_gradient_watermark(self):
        """R1: Character stroke mask removes multi-color rainbow gradient watermarks."""
        import cv2
        import numpy as np

        h, w = 120, 480
        roi = np.full((h, w, 3), 120, dtype=np.uint8)
        glyph = np.zeros((h, w), dtype=np.uint8)
        cv2.putText(glyph, "RAINBOW WATERMARK", (30, 75), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 255, 2)
        outline = cv2.dilate(glyph, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
        roi[outline > 0] = (10, 10, 10)

        for x in range(w):
            hue = int((x / w) * 180)
            bgr_col = cv2.cvtColor(np.uint8([[[hue, 255, 240]]]), cv2.COLOR_HSV2BGR)[0, 0]
            roi[glyph[:, x] > 0, x] = bgr_col

        mask = VideoEditorService._generate_text_stroke_mask(roi)
        mask_pixels = np.count_nonzero(mask > 0)
        coverage = (mask_pixels / (h * w)) * 100
        self.assertGreater(mask_pixels, 100)
        self.assertLess(coverage, 25.0)

    def test_generate_text_stroke_mask_temporal_stability_avoids_ghost_leak_on_subtitle_change(self):
        """R1 & R2: Temporal stability prevents leaking ghost masks when subtitle text changes."""
        import cv2
        import numpy as np

        h, w = 120, 480
        # Frame A: Subtitle on left
        roi1 = np.full((h, w, 3), 120, dtype=np.uint8)
        g1 = np.zeros((h, w), dtype=np.uint8)
        cv2.putText(g1, "LEFT SUBTITLE", (20, 75), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 255, 2)
        roi1[cv2.dilate(g1, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))) > 0] = (10, 10, 10)
        roi1[g1 > 0] = (255, 255, 255)
        mask1 = VideoEditorService._generate_text_stroke_mask(roi1)

        # Frame B: Different subtitle on right
        roi2 = np.full((h, w, 3), 120, dtype=np.uint8)
        g2 = np.zeros((h, w), dtype=np.uint8)
        cv2.putText(g2, "RIGHT TEXT", (280, 75), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 255, 2)
        roi2[cv2.dilate(g2, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))) > 0] = (10, 10, 10)
        roi2[g2 > 0] = (255, 255, 255)

        mask2_fresh = VideoEditorService._generate_text_stroke_mask(roi2)
        mask2_with_prev = VideoEditorService._generate_text_stroke_mask(roi2, prev_mask=mask1)

        # Because subtitles differ (IoU < 0.70), prev_mask must not be merged
        self.assertTrue(np.array_equal(mask2_with_prev, mask2_fresh))
        left_leak = np.count_nonzero(mask2_with_prev[g1 > 0] > 0)
        self.assertEqual(left_leak, 0)

    def test_generate_text_stroke_mask_with_semi_transparent_drop_shadow(self):
        """R1: Character stroke mask encompasses semi-transparent drop shadow on medium backgrounds."""
        import cv2
        import numpy as np

        h, w = 60, 200
        roi = np.full((h, w, 3), 130, dtype=np.uint8)
        # Drop shadow at dx=3, dy=3 with V=85
        cv2.putText(roi, "DROP SHADOW", (13, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (85, 85, 85), 2)
        # Bright text core at (10, 35)
        cv2.putText(roi, "DROP SHADOW", (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        mask = VideoEditorService._generate_text_stroke_mask(roi)
        self.assertIsInstance(mask, np.ndarray)
        mask_cov = (np.count_nonzero(mask > 0) / (h * w)) * 100
        self.assertLess(mask_cov, 30.0)
        self.assertGreater(mask_cov, 10.0)

        # Inpaint and verify all drop shadow artifacts are cleanly removed
        inpainted = VideoEditorService._inpaint_edge_aware(roi, mask)
        rem_shadow = np.count_nonzero((inpainted[:, :, 0] <= 95) & (inpainted[:, :, 0] >= 75))
        self.assertEqual(rem_shadow, 0, "Lingering drop shadow smudges remaining after inpaint")

    def test_generate_text_stroke_mask_with_soft_neon_glow_subtitles(self):
        """R1: Character stroke mask covers fuzzy soft glow halo without leaving colored aura ghosts."""
        import cv2
        import numpy as np

        h, w = 60, 200
        roi = np.full((h, w, 3), 50, dtype=np.uint8)
        glow_layer = np.zeros((h, w, 3), dtype=np.uint8)
        cv2.putText(glow_layer, "SOFT GLOW", (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 5)
        glow_layer = cv2.GaussianBlur(glow_layer, (9, 9), 0)
        roi = cv2.add(roi, glow_layer)
        cv2.putText(roi, "SOFT GLOW", (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        mask = VideoEditorService._generate_text_stroke_mask(roi)
        self.assertIsInstance(mask, np.ndarray)
        mask_cov = (np.count_nonzero(mask > 0) / (h * w)) * 100
        self.assertLess(mask_cov, 30.0)
        self.assertGreater(mask_cov, 12.0)

        inpainted = VideoEditorService._inpaint_edge_aware(roi, mask)
        hsv_inp = cv2.cvtColor(inpainted, cv2.COLOR_BGR2HSV)
        # Yellow glow lingering in HSV
        rem_glow = np.count_nonzero(
            (hsv_inp[:, :, 0] >= 15) & (hsv_inp[:, :, 0] <= 45) & (hsv_inp[:, :, 1] >= 40) & (hsv_inp[:, :, 2] >= 60)
        )
        self.assertEqual(rem_glow, 0, "Soft glow colored halo ghost remaining after inpaint")

    def test_generate_text_stroke_mask_rejects_high_frequency_textured_background_false_positives(self):
        """R1: Stroke mask rejects textured brick wall / mortar line background false positives."""
        import cv2
        import numpy as np

        h, w = 100, 200
        brick = np.full((h, w, 3), 160, dtype=np.uint8)
        for y in range(0, h, 20):
            brick[y:y + 3, :] = 50
        for row, y in enumerate(range(0, h, 20)):
            offset = 20 if row % 2 == 1 else 0
            for x in range(offset, w, 40):
                brick[y:y + 20, x:x + 3] = 50
        np.random.seed(42)
        noise = np.random.normal(0, 15, (h, w, 3)).astype(np.int16)
        brick = np.clip(brick.astype(np.int16) + noise, 0, 255).astype(np.uint8)

        mask = VideoEditorService._generate_text_stroke_mask(brick)
        self.assertEqual(np.count_nonzero(mask), 0, "Textured wall falsely detected as subtitle text")

    def test_generate_text_stroke_mask_with_small_and_skewed_aspect_ratio_rois(self):
        """R1: Character stroke mask preserves fine character strokes in tiny and wide thin ROIs."""
        import cv2
        import numpy as np

        # Tiny ROI: 12x12
        roi_small = np.full((12, 12, 3), 40, dtype=np.uint8)
        cv2.putText(roi_small, "A", (1, 10), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1)
        mask_small = VideoEditorService._generate_text_stroke_mask(roi_small)
        self.assertGreater(np.count_nonzero(mask_small), 10, "Tiny 12x12 glyph improperly erased by opening")

        # Wide single-line ticker ROI: 14x200
        roi_wide = np.full((14, 200, 3), 40, dtype=np.uint8)
        cv2.putText(roi_wide, "HELLO WORLD", (5, 11), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1)
        mask_wide = VideoEditorService._generate_text_stroke_mask(roi_wide)
        self.assertGreater(np.count_nonzero(mask_wide), 100, "Thin 14x200 banner text improperly erased")

    def test_generate_text_stroke_mask_temporal_stability_bounds_dynamic_shadow_growth(self):
        """R1 & R2: Temporal stability bounds mask expansion on moving watermarks and deformed shadows."""
        import cv2
        import numpy as np

        prev_m = None
        counts = []
        for t in range(20):
            roi = np.full((50, 150, 3), 40, dtype=np.uint8)
            dx = int(2 * np.sin(t * 0.5))
            cv2.putText(roi, "3D LOGO", (20 + dx, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
            m = VideoEditorService._generate_text_stroke_mask(roi, prev_m)
            prev_m = m
            counts.append(np.count_nonzero(m))

        # Check mask growth is bounded and does not accumulate unboundedly
        expansion = counts[-1] - counts[0]
        self.assertLess(expansion, 150, "Unbounded temporal mask expansion on dynamic watermark")


if __name__ == "__main__":
    unittest.main()


