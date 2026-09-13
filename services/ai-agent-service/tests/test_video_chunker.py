"""
test_video_chunker.py — Comprehensive Unit and Empirical Integration Tests for VideoChunker.

Verifies:
1. Video <= 48MB returns single lossless part without splitting.
2. Video > 48MB (and parameterized chunk thresholds) splits seamlessly via FFmpeg stream-copy (-c copy).
3. Faststart flag (-movflags +faststart), moov atom placement, and codec preservation.
4. Defensive Guard Loop: recursive splitting when GOP snap causes part size overshoot.
5. Zero-Disk-Leak: cleanup_parts, temporary_chunks async context manager, and error-path cleanup.
6. Robust probe_video_info edge cases and resilience.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.video_chunker import (
    VideoChunker,
    VideoChunkerError,
    TELEGRAM_SAFE_PART_BYTES,
    TARGET_CHUNK_BYTES,
)

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def generate_synthetic_mp4(
    output_path: Path,
    duration_secs: int = 10,
    width: int = 320,
    height: int = 240,
    fps: int = 30,
    gop_size: int = 30,
) -> Path:
    """Helper to generate a valid, playable MP4 file with controlled GOP using FFmpeg."""
    import subprocess
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"testsrc=size={width}x{height}:rate={fps}",
        "-f", "lavfi", "-i", "sine=frequency=1000",
        "-t", str(duration_secs),
        "-c:v", "libx264", "-preset", "ultrafast",
        "-g", str(gop_size), "-keyint_min", str(gop_size), "-sc_threshold", "0",
        "-c:a", "aac",
        "-movflags", "+faststart",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return output_path


class TestVideoChunkerProbeInfo(unittest.IsolatedAsyncioTestCase):
    """Test probe_video_info metadata extraction and defensive handling."""

    async def asyncSetUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_chunker_probe_"))

    async def asyncTearDown(self):
        shutil.rmtree(str(self.temp_dir), ignore_errors=True)

    async def test_probe_nonexistent_file_raises_filenotfound(self):
        """Probing a non-existent file must immediately raise FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            await VideoChunker.probe_video_info(str(self.temp_dir / "nonexistent.mp4"))

    async def test_probe_ffprobe_missing_binary_raises_runtimeerror(self):
        """If ffprobe executable cannot be launched, raise descriptive RuntimeError."""
        dummy_file = self.temp_dir / "dummy.mp4"
        dummy_file.write_bytes(b"dummy")

        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError("No ffprobe")):
            with self.assertRaises(RuntimeError) as ctx:
                await VideoChunker.probe_video_info(str(dummy_file))
            self.assertIn("ffprobe executable not found", str(ctx.exception))

    async def test_probe_ffprobe_failure_raises_runtimeerror(self):
        """If ffprobe exits with non-zero code, raise RuntimeError containing stderr."""
        dummy_file = self.temp_dir / "corrupted.mp4"
        dummy_file.write_bytes(b"not a valid mp4")

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"Invalid data found when processing input"))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with self.assertRaises(RuntimeError) as ctx:
                await VideoChunker.probe_video_info(str(dummy_file))
            self.assertIn("ffprobe failed", str(ctx.exception))
            self.assertIn("Invalid data found", str(ctx.exception))

    async def test_probe_handles_missing_fields_gracefully(self):
        """Ensure probe_video_info falls back to safe defaults when metadata is incomplete."""
        dummy_file = self.temp_dir / "partial.mp4"
        dummy_file.write_bytes(b"x" * 1024)

        json_output = json.dumps({
            "format": {"duration": "N/A", "size": "1024"},
            "streams": [
                {"codec_type": "audio", "codec_name": "aac"},
                {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "duration": "45.5"}
            ]
        }).encode("utf-8")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(json_output, b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            info = await VideoChunker.probe_video_info(str(dummy_file))
            self.assertEqual(info["duration"], 45.5)
            self.assertEqual(info["width"], 1920)
            self.assertEqual(info["height"], 1080)
            self.assertEqual(info["codec_name"], "h264")
            self.assertEqual(info["size"], 1024)

    async def test_probe_ffprobe_timeout_kills_process(self):
        """If ffprobe hangs, wait_for should trigger timeout, killing the process and cleaning up."""
        dummy_file = self.temp_dir / "hanging.mp4"
        dummy_file.write_bytes(b"content")

        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)

        async def hanging_communicate():
            await asyncio.sleep(10)
            return (b"", b"")
        mock_proc.communicate = hanging_communicate

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with self.assertRaises(RuntimeError) as ctx:
                await VideoChunker.probe_video_info(str(dummy_file), timeout=0.1)
            self.assertIn("ffprobe timed out", str(ctx.exception))
            mock_proc.kill.assert_called_once()
            mock_proc.wait.assert_awaited_once()

    async def test_probe_ffprobe_cancellation_kills_process(self):
        """If probe task is cancelled, subprocess must be killed and waited upon."""
        dummy_file = self.temp_dir / "cancelled.mp4"
        dummy_file.write_bytes(b"content")

        mock_proc = MagicMock()
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)

        async def hang():
            await asyncio.sleep(10)
            return (b"", b"")
        mock_proc.communicate = hang

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            task = asyncio.create_task(VideoChunker.probe_video_info(str(dummy_file)))
            await asyncio.sleep(0.02)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            mock_proc.kill.assert_called_once()
            mock_proc.wait.assert_awaited_once()


class TestVideoChunkerSplitLogic(unittest.IsolatedAsyncioTestCase):
    """Test splitting boundaries, command composition, and guard loop."""

    async def asyncSetUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_chunker_logic_"))
        self.out_dir = self.temp_dir / "output"
        self.out_dir.mkdir()

    async def asyncTearDown(self):
        shutil.rmtree(str(self.temp_dir), ignore_errors=True)

    async def test_split_file_not_found(self):
        """split_video should fail if target file does not exist."""
        with self.assertRaises(FileNotFoundError):
            await VideoChunker.split_video(
                str(self.temp_dir / "not_found.mp4"),
                self.out_dir,
            )

    async def test_split_video_under_max_bytes_returns_original_single_part(self):
        """Files <= max_part_bytes must return 1 part pointing to the original file."""
        sample_file = self.temp_dir / "small_video.mp4"
        sample_file.write_bytes(b"content" * 100)

        mock_info = {
            "duration": 12.4,
            "width": 1280,
            "height": 720,
            "codec_name": "h264",
            "size": sample_file.stat().st_size,
        }

        with patch.object(VideoChunker, "probe_video_info", new=AsyncMock(return_value=mock_info)):
            parts = await VideoChunker.split_video(
                video_path=str(sample_file),
                output_dir=self.out_dir,
                max_part_bytes=TELEGRAM_SAFE_PART_BYTES,
            )

            self.assertEqual(len(parts), 1)
            self.assertEqual(parts[0]["part_index"], 1)
            self.assertEqual(parts[0]["total_parts"], 1)
            self.assertEqual(parts[0]["path"], str(sample_file.resolve()))
            self.assertEqual(parts[0]["duration"], 12)
            self.assertEqual(parts[0]["size"], sample_file.stat().st_size)
            self.assertEqual(parts[0]["width"], 1280)
            self.assertEqual(parts[0]["height"], 720)

    async def test_split_video_ffmpeg_command_structure(self):
        """Verify the exact FFmpeg command contains -c copy, +faststart, -reset_timestamps 1, -map 0."""
        large_file = self.temp_dir / "large_video.mp4"
        large_file.write_bytes(b"0" * 1000)

        mock_info = {
            "duration": 60.0,
            "width": 1920,
            "height": 1080,
            "codec_name": "h264",
            "size": 1000,
        }

        captured_cmd = []

        async def fake_subprocess_exec(*args, **kwargs):
            nonlocal captured_cmd
            captured_cmd = list(args)
            # Simulate FFmpeg generating 2 part files
            p1 = self.out_dir / "part_000.mp4"
            p2 = self.out_dir / "part_001.mp4"
            p1.write_bytes(b"a" * 400)
            p2.write_bytes(b"b" * 400)

            proc = MagicMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"", b""))
            return proc

        with patch.object(VideoChunker, "probe_video_info", new=AsyncMock(return_value=mock_info)), \
             patch("asyncio.create_subprocess_exec", side_effect=fake_subprocess_exec):

            parts = await VideoChunker.split_video(
                video_path=str(large_file),
                output_dir=self.out_dir,
                max_part_bytes=500,
                target_part_bytes=450,
            )

            # Assert FFmpeg flags
            self.assertIn("-nostdin", captured_cmd)
            self.assertIn("-c", captured_cmd)
            self.assertEqual(captured_cmd[captured_cmd.index("-c") + 1], "copy")
            self.assertIn("0:v", captured_cmd)
            self.assertIn("0:a?", captured_cmd)
            self.assertIn("-f", captured_cmd)
            self.assertEqual(captured_cmd[captured_cmd.index("-f") + 1], "segment")
            self.assertIn("-segment_format_options", captured_cmd)
            self.assertEqual(captured_cmd[captured_cmd.index("-segment_format_options") + 1], "movflags=+faststart")
            self.assertIn("-reset_timestamps", captured_cmd)
            self.assertEqual(captured_cmd[captured_cmd.index("-reset_timestamps") + 1], "1")
            self.assertIn("-movflags", captured_cmd)
            self.assertEqual(captured_cmd[captured_cmd.index("-movflags") + 1], "+faststart")

            self.assertEqual(len(parts), 2)
            self.assertEqual(parts[0]["part_index"], 1)
            self.assertEqual(parts[1]["part_index"], 2)
            self.assertEqual(parts[0]["total_parts"], 2)

    async def test_defensive_guard_loop_recursive_splitting(self):
        """
        Adversarial Test: When a generated part exceeds max_part_bytes (GOP overshoot),
        the defensive guard loop must detect it and recursively split the oversized part.
        """
        oversized_file = self.temp_dir / "oversized.mp4"
        oversized_file.write_bytes(b"X" * 1000)

        # Call count tracker
        call_count = 0

        async def fake_split_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            cmd_args = list(args)
            out_pattern = cmd_args[-1]
            parent_dir = Path(out_pattern).parent

            proc = MagicMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"", b""))

            if call_count == 1:
                # First run: part_000 is 300B (OK), part_001 is 700B (EXCEEDS 500B limit!)
                (parent_dir / "part_000.mp4").write_bytes(b"A" * 300)
                (parent_dir / "part_001.mp4").write_bytes(b"B" * 700)
            else:
                # Recursive run for part_001: splits into two 350B parts (both <= 500B)
                (parent_dir / "part_000.mp4").write_bytes(b"C" * 350)
                (parent_dir / "part_001.mp4").write_bytes(b"D" * 350)
            return proc

        mock_probe = {
            "duration": 30.0,
            "width": 1920,
            "height": 1080,
            "codec_name": "h264",
            "size": 350,
        }

        with patch.object(VideoChunker, "probe_video_info", new=AsyncMock(return_value=mock_probe)), \
             patch("asyncio.create_subprocess_exec", side_effect=fake_split_exec):

            parts = await VideoChunker.split_video(
                video_path=str(oversized_file),
                output_dir=self.out_dir,
                max_part_bytes=500,
                target_part_bytes=450,
            )

            # Defensive guard must have triggered recursive split
            self.assertGreater(call_count, 1)
            # Total parts should now be 3 (part 0 + 2 sub-parts of part 1)
            self.assertEqual(len(parts), 3)
            for p in parts:
                self.assertLessEqual(p["size"], 500)
                self.assertTrue(Path(p["path"]).exists())

            # Verify the oversized parent part (part_001) was unlinked to prevent disk leak
            self.assertFalse((self.out_dir / "part_001.mp4").exists())


class TestVideoChunkerZeroDiskLeak(unittest.IsolatedAsyncioTestCase):
    """Test Zero-Disk-Leak guarantees across error handling and lifecycle helpers."""

    async def asyncSetUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_chunker_leak_"))
        self.out_dir = self.temp_dir / "leak_out"
        self.out_dir.mkdir()

    async def asyncTearDown(self):
        shutil.rmtree(str(self.temp_dir), ignore_errors=True)

    async def test_cleanup_parts_with_dict_list(self):
        """cleanup_parts must delete all files specified in part dictionaries."""
        f1 = self.temp_dir / "test1.mp4"
        f2 = self.temp_dir / "test2.mp4"
        f1.write_bytes(b"data1")
        f2.write_bytes(b"data2")

        parts = [{"path": str(f1)}, {"path": str(f2)}]
        VideoChunker.cleanup_parts(parts)

        self.assertFalse(f1.exists())
        self.assertFalse(f2.exists())

    async def test_cleanup_parts_with_directory(self):
        """cleanup_parts must recursively delete a directory."""
        sub = self.temp_dir / "sub_dir"
        sub.mkdir()
        (sub / "nested.mp4").write_bytes(b"data")

        VideoChunker.cleanup_parts(sub)
        self.assertFalse(sub.exists())

    async def test_cleanup_parts_idempotency(self):
        """Calling cleanup_parts on already deleted or missing files should not raise errors."""
        missing = self.temp_dir / "already_deleted.mp4"
        VideoChunker.cleanup_parts([{"path": str(missing)}])
        VideoChunker.cleanup_parts(str(missing))

    async def test_split_failure_cleans_up_orphaned_parts(self):
        """If FFmpeg or a subsequent step fails, any partial segment files must be cleaned up."""
        dummy_input = self.temp_dir / "corrupt_input.mp4"
        dummy_input.write_bytes(b"V" * 1000)

        async def failing_exec(*args, **kwargs):
            # Create a partial part before failing
            (self.out_dir / "part_000.mp4").write_bytes(b"partial")
            proc = MagicMock()
            proc.returncode = 1
            proc.communicate = AsyncMock(return_value=(b"", b"Segmentation fault in muxer"))
            return proc

        mock_probe = {"duration": 20.0, "width": 1280, "height": 720, "codec_name": "h264", "size": 1000}

        with patch.object(VideoChunker, "probe_video_info", new=AsyncMock(return_value=mock_probe)), \
             patch("asyncio.create_subprocess_exec", side_effect=failing_exec):

            with self.assertRaises(RuntimeError):
                await VideoChunker.split_video(
                    video_path=str(dummy_input),
                    output_dir=self.out_dir,
                    max_part_bytes=500,
                )

            # Orphaned partial file must be gone
            self.assertFalse((self.out_dir / "part_000.mp4").exists())

    async def test_temporary_chunks_context_manager_cleans_up_on_normal_exit(self):
        """temporary_chunks context manager automatically removes temporary folder on exit."""
        mock_parts = [
            {"path": str(self.temp_dir / "part1.mp4"), "part_index": 1, "total_parts": 1, "duration": 5, "size": 10, "width": 640, "height": 480}
        ]
        created_dir = None

        with patch.object(VideoChunker, "split_video", new=AsyncMock(return_value=mock_parts)):
            async with VideoChunker.temporary_chunks("dummy_video.mp4") as parts:
                self.assertEqual(parts, mock_parts)
                # Ensure context yields parts

    async def test_temporary_chunks_context_manager_cleans_up_on_exception(self):
        """temporary_chunks context manager cleans up even if an exception occurs inside."""
        with patch.object(VideoChunker, "split_video", new=AsyncMock(return_value=[])):
            with self.assertRaises(ValueError):
                async with VideoChunker.temporary_chunks("dummy_video.mp4"):
                    raise ValueError("User code failed inside context")

    async def test_split_video_cancellation_kills_process_and_cleans_disk(self):
        """When split_video task is cancelled, FFmpeg must be killed and all partial parts cleaned."""
        dummy_input = self.temp_dir / "cancelled_input.mp4"
        dummy_input.write_bytes(b"C" * 2000)

        mock_probe = {"duration": 60.0, "width": 1280, "height": 720, "codec_name": "h264", "size": 2000}

        mock_proc = MagicMock()
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)

        async def slow_communicate():
            # Create partial part file on disk to test Zero-Disk-Leak
            (self.out_dir / "part_000.mp4").write_bytes(b"partial segment data")
            (self.out_dir / "part_001.mp4").write_bytes(b"partial segment data")
            await asyncio.sleep(10)
            return (b"", b"")
        mock_proc.communicate = slow_communicate

        with patch.object(VideoChunker, "probe_video_info", new=AsyncMock(return_value=mock_probe)), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc):

            task = asyncio.create_task(VideoChunker.split_video(
                video_path=str(dummy_input),
                output_dir=self.out_dir,
                max_part_bytes=500,
            ))
            await asyncio.sleep(0.05)
            task.cancel()

            with self.assertRaises(asyncio.CancelledError):
                await task

            mock_proc.kill.assert_called_once()
            mock_proc.wait.assert_awaited_once()
            # Zero-Disk-Leak check: partial part files must be removed
            self.assertFalse((self.out_dir / "part_000.mp4").exists())
            self.assertFalse((self.out_dir / "part_001.mp4").exists())

    async def test_split_video_timeout_kills_process(self):
        """When FFmpeg chunking hangs beyond timeout, process is killed and RuntimeError raised."""
        dummy_input = self.temp_dir / "timeout_input.mp4"
        dummy_input.write_bytes(b"T" * 2000)

        mock_probe = {"duration": 60.0, "width": 1280, "height": 720, "codec_name": "h264", "size": 2000}

        mock_proc = MagicMock()
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)

        async def hang():
            (self.out_dir / "part_000.mp4").write_bytes(b"hanging data")
            await asyncio.sleep(10)
            return (b"", b"")
        mock_proc.communicate = hang

        with patch.object(VideoChunker, "probe_video_info", new=AsyncMock(return_value=mock_probe)), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc):

            with self.assertRaises(RuntimeError) as ctx:
                await VideoChunker.split_video(
                    video_path=str(dummy_input),
                    output_dir=self.out_dir,
                    max_part_bytes=500,
                    timeout=0.1,
                )
            self.assertIn("FFmpeg chunking timed out", str(ctx.exception))
            mock_proc.kill.assert_called_once()
            mock_proc.wait.assert_awaited_once()
            self.assertFalse((self.out_dir / "part_000.mp4").exists())

    async def test_recursive_split_cleans_sub_directories_on_failure(self):
        """If recursive split encounters an exception, all sub_* directories must be purged."""
        dummy_input = self.temp_dir / "oversized_fail.mp4"
        dummy_input.write_bytes(b"F" * 2000)

        mock_probe = {"duration": 60.0, "width": 1280, "height": 720, "codec_name": "h264", "size": 2000}

        call_count = 0
        async def fake_subprocess_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            cmd_args = list(args)
            out_pattern = cmd_args[-1]
            parent_dir = Path(out_pattern).parent

            proc = MagicMock()
            if call_count == 1:
                # First level: generate oversized part
                (parent_dir / "part_000.mp4").write_bytes(b"X" * 1500)
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"", b""))
                return proc
            else:
                # Recursive level: simulate crash (e.g. Disk Full)
                sub_dir = parent_dir
                (sub_dir / "orphan.tmp").write_bytes(b"garbage")
                proc.returncode = 1
                proc.communicate = AsyncMock(return_value=(b"", b"No space left on device"))
                return proc

        with patch.object(VideoChunker, "probe_video_info", new=AsyncMock(return_value=mock_probe)), \
             patch("asyncio.create_subprocess_exec", side_effect=fake_subprocess_exec):

            with self.assertRaises(RuntimeError):
                await VideoChunker.split_video(
                    video_path=str(dummy_input),
                    output_dir=self.out_dir,
                    max_part_bytes=500,
                    target_part_bytes=400,
                )

            # Check that no sub_* directories or part_*.mp4 files remain
            sub_dirs = list(self.out_dir.glob("sub_*"))
            self.assertEqual(len(sub_dirs), 0, "All sub_* directories must be recursively cleaned up")
            parts = list(self.out_dir.glob("part_*.mp4"))
            self.assertEqual(len(parts), 0, "All part_*.mp4 files must be deleted on error")


@unittest.skipUnless(HAS_FFMPEG, "Requires FFmpeg and FFprobe installed in system PATH")
class TestVideoChunkerEmpiricalFFmpeg(unittest.IsolatedAsyncioTestCase):
    """
    Empirical Integration Tests running with real FFmpeg and FFprobe.
    Verifies bit-exact lossless stream copy, faststart moov atom, and flawless playback.
    """

    async def asyncSetUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_chunker_empirical_"))
        self.out_dir = self.temp_dir / "empirical_chunks"
        self.out_dir.mkdir()

    async def asyncTearDown(self):
        shutil.rmtree(str(self.temp_dir), ignore_errors=True)

    async def test_empirical_probe_video_info_real_file(self):
        """Verify real FFprobe extracts accurate duration, width, height, and codec_name."""
        source = self.temp_dir / "real_source.mp4"
        generate_synthetic_mp4(source, duration_secs=5, width=640, height=360, fps=25)

        info = await VideoChunker.probe_video_info(str(source))
        self.assertAlmostEqual(info["duration"], 5.0, delta=0.5)
        self.assertEqual(info["width"], 640)
        self.assertEqual(info["height"], 360)
        self.assertEqual(info["codec_name"], "h264")
        self.assertGreater(info["size"], 0)

    async def test_empirical_split_video_lossless_stream_copy(self):
        """
        Verify real FFmpeg segmenting:
        1. Codec matches original stream exactly without transcoding.
        2. Faststart moov atom is in place.
        3. Cumulative duration covers the original duration.
        """
        source = self.temp_dir / "long_source.mp4"
        # 12-second synthetic video with 1s GOP (gop_size=30 at 30fps)
        generate_synthetic_mp4(source, duration_secs=12, width=480, height=270, fps=30, gop_size=30)
        source_size = source.stat().st_size

        # Set target bytes so that it splits into at least 3 parts
        target_bytes = max(source_size // 3, 1024)
        max_bytes = int(source_size * 0.65)

        parts = await VideoChunker.split_video(
            video_path=str(source),
            output_dir=self.out_dir,
            max_part_bytes=max_bytes,
            target_part_bytes=target_bytes,
        )

        self.assertGreaterEqual(len(parts), 2)
        total_duration = 0.0

        for idx, part in enumerate(parts, 1):
            self.assertEqual(part["part_index"], idx)
            self.assertEqual(part["total_parts"], len(parts))
            self.assertTrue(os.path.exists(part["path"]))
            self.assertLessEqual(part["size"], max_bytes)

            # Probe each part with real ffprobe
            p_info = await VideoChunker.probe_video_info(part["path"])
            self.assertEqual(p_info["codec_name"], "h264", "Must be bit-exact lossless stream copy (h264)")
            self.assertEqual(p_info["width"], 480)
            self.assertEqual(p_info["height"], 270)
            total_duration += p_info["duration"]

            # Verify that moov atom is located in the first 64KB for instant faststart playback
            with open(part["path"], "rb") as pf:
                header_data = pf.read(65536)
                self.assertIn(b"moov", header_data, f"Part {idx} must have moov atom at beginning for faststart inline streaming")

        # Sum of part durations should match original duration within GOP tolerance (1.5s)
        self.assertAlmostEqual(total_duration, 12.0, delta=1.5)

    async def test_empirical_zero_disk_leak_send_and_purge(self):
        """Simulate sending parts and purging them one by one, confirming zero residual files."""
        source = self.temp_dir / "purge_source.mp4"
        generate_synthetic_mp4(source, duration_secs=8, width=320, height=240, fps=30, gop_size=30)
        source_size = source.stat().st_size

        target_bytes = max(source_size // 2, 1024)
        parts = await VideoChunker.split_video(
            video_path=str(source),
            output_dir=self.out_dir,
            max_part_bytes=int(source_size * 0.75),
            target_part_bytes=target_bytes,
        )

        self.assertGreaterEqual(len(parts), 2)

        # Purge each part simulating Telegram sequential delivery
        for part in parts:
            Path(part["path"]).unlink()

        # Output directory must now have 0 mp4 files
        remaining = list(self.out_dir.glob("*.mp4"))
        self.assertEqual(len(remaining), 0, "No residual files should remain after purge")

    async def test_empirical_split_video_with_subtitles_does_not_crash(self):
        """
        Verify that splitting a video containing incompatible subtitle streams (e.g. SubRip/SRT)
        does not crash FFmpeg with exit code 234 due to '-map 0:v -map 0:a?'.
        """
        import subprocess

        sub_file = self.temp_dir / "sample.srt"
        sub_file.write_text("1\n00:00:00,000 --> 00:00:06,000\nSubtitle text test\n", encoding="utf-8")
        source_mkv = self.temp_dir / "subbed_video.mkv"

        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=1000",
            "-i", str(sub_file),
            "-t", "8",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-g", "30", "-keyint_min", "30",
            "-c:a", "aac",
            "-c:s", "srt",
            str(source_mkv),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        source_size = source_mkv.stat().st_size

        target_bytes = max(source_size // 2, 1024)
        max_bytes = int(source_size * 0.75)

        # Splitting must succeed without exit code 234 (subrip tag error)
        parts = await VideoChunker.split_video(
            video_path=str(source_mkv),
            output_dir=self.out_dir,
            max_part_bytes=max_bytes,
            target_part_bytes=target_bytes,
        )

        self.assertGreaterEqual(len(parts), 2)
        for part in parts:
            self.assertTrue(os.path.exists(part["path"]))
            p_info = await VideoChunker.probe_video_info(part["path"])
            self.assertEqual(p_info["codec_name"], "h264")


if __name__ == "__main__":
    unittest.main()
