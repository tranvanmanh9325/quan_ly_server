"""
multimedia_service.py — High-Performance Multimedia Studio Engine for Kirito-Server.

Provides 8 specialized multimedia tools:
  1. edit_video_clip: Fast stream-copy (-c copy) or high-quality re-encode video trimming.
  2. compress_video: Automated 2-pass bitrate allocation targeting < 50MB for Telegram.
  3. convert_video_format: Transcoding across MP4, MKV, AVI, MOV, WEBM, and GIF (palettegen).
  4. convert_audio_format: Studio audio transcoding (FLAC/WAV/M4A/OGG/AAC -> MP3 320kbps).
  5. trim_audio_clip: Precise second-level audio trimming with optional fade-in/fade-out.
  6. normalize_audio_volume: EBU R128 loudnorm volume balancing with video passthrough.
  7. convert_and_resize_image: Multi-format image conversion (WEBP/PNG/JPG/HEIC) and resizing.
  8. generate_custom_qr: High-resolution in-memory QR code generation with label banner.

Hardware Protection for kirito-server (Haswell 2-core CPU, 3.2GB RAM):
  - Concurrency limited via asyncio.Semaphore(2).
  - Subprocess execution via asyncio.create_subprocess_exec (List[str], no shell=True).
  - Strict subprocess timeouts (60s - 300s) with SIGKILL on expiration.
  - Zero-Disk Leak guarantee: temporary files purged in try...finally blocks.
  - Dual-Delivery: files <= 50MB returned for Telegram bot; > 50MB published via media_storage_manager.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
from pathlib import Path
import re
import secrets
import shutil
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple, Union
import urllib.parse

import httpx
from PIL import Image, ImageDraw, ImageFont
import qrcode
import qrcode.constants

try:
    from app.services.media_storage_manager import media_storage_manager
except ImportError:
    media_storage_manager = None

logger = logging.getLogger(__name__)

# Maximum file size for direct Telegram Bot transmission (50MB)
TELEGRAM_MAX_FILE_SIZE: int = 50 * 1024 * 1024

# Common video file extensions for type identification
VIDEO_EXTENSIONS = frozenset({
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v", ".3gp", ".ts"
})

# Common audio file extensions
AUDIO_EXTENSIONS = frozenset({
    ".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".wma", ".opus", ".aiff"
})

# Common image file extensions
IMAGE_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp", ".tiff", ".gif"
})


class MultimediaService:
    """
    Core execution engine for R1 Multimedia Studio Suite.
    Enforces hardware safety, non-blocking subprocesses, and Dual-Delivery.
    """

    def __init__(
        self,
        storage_manager: Any = None,
        http_client: Optional[httpx.AsyncClient] = None,
        temp_dir: Optional[Union[str, Path]] = None,
    ):
        self._storage = storage_manager if storage_manager is not None else media_storage_manager
        self._http = http_client
        self._semaphore = asyncio.Semaphore(2)  # Limit concurrent FFmpeg loads on 2 cores
        
        # Configure working scratch directory
        base_temp = Path(temp_dir or os.getenv("MEDIA_STUDIO_TEMP_DIR", tempfile.gettempdir()))
        self._temp_dir = base_temp / "media_studio"
        self._ensure_temp_dir()

    def _ensure_temp_dir(self) -> None:
        """Create scratch directory if missing."""
        try:
            self._temp_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            logger.warning("[MultimediaService] Failed to create scratch directory %s: %s", self._temp_dir, exc)

    async def _run_command(
        self,
        cmd: List[str],
        timeout: int = 180,
    ) -> Tuple[int, bytes, bytes]:
        """
        Executes a subprocess safely with concurrency bounding and strict timeout.
        Why List[str]: Prevents command injection attacks; shell=True is forbidden.
        """
        async with self._semaphore:
            logger.debug("[MultimediaService] Executing command: %s", " ".join(cmd[:8]))
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                return proc.returncode or 0, stdout, stderr
            except asyncio.TimeoutError:
                logger.error("[MultimediaService] Subprocess timed out after %ds: %s", timeout, cmd[0])
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
                raise TimeoutError(f"Tác vụ xử lý media vượt quá thời gian tối đa ({timeout}s).")

    async def _resolve_input(self, input_path_or_url: str) -> Tuple[Path, bool]:
        """
        Resolves input target: streams remote URL to SSD scratch file or validates local file.
        Returns: (local_file_path, is_transient_downloaded)
        """
        clean_input = str(input_path_or_url).strip()
        if not clean_input:
            raise ValueError("Đường dẫn hoặc URL đầu vào không được để trống.")

        # Handle remote HTTP/HTTPS streaming download
        if clean_input.lower().startswith(("http://", "https://")):
            url_name = Path(urllib.parse.urlsplit(clean_input).path).name or "input_remote.bin"
            token = secrets.token_hex(6)
            download_dest = self._temp_dir / f"dl_{token}_{url_name}"
            
            client = self._http
            should_close_client = False
            if client is None:
                client = httpx.AsyncClient(timeout=60.0, follow_redirects=True)
                should_close_client = True

            try:
                async with client.stream("GET", clean_input) as resp:
                    resp.raise_for_status()
                    with open(download_dest, "wb") as f:
                        async for chunk in resp.aiter_bytes(chunk_size=65536):
                            f.write(chunk)
                return download_dest, True
            finally:
                if should_close_client:
                    await client.aclose()

        # Handle local filesystem path
        local_path = Path(clean_input).resolve()
        if not local_path.exists():
            raise FileNotFoundError(f"Tệp không tồn tại: {clean_input}")
        return local_path, False

    def _publish_or_direct(
        self,
        file_path: Path,
        title: str = "",
        duration: int = 0,
    ) -> Dict[str, Any]:
        """
        Dual-Delivery router:
          - Size <= 50MB: 'direct' delivery for instant Telegram upload.
          - Size > 50MB: 'portal' delivery via MediaStorageManager (LAN & Ngrok links, 4h TTL).
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Tệp kết quả không tồn tại: {file_path}")

        file_size = file_path.stat().st_size
        size_mb = round(file_size / (1024 * 1024), 2)

        if file_size <= TELEGRAM_MAX_FILE_SIZE:
            return {
                "delivery": "direct",
                "file_path": str(file_path),
                "filename": file_path.name,
                "file_size": file_size,
                "file_size_mb": size_mb,
                "internet_url": None,
                "lan_url": None,
                "expires_at": None,
            }

        # Size exceeds Telegram 50MB limit -> Publish via storage manager if available
        if self._storage is not None:
            try:
                record = self._storage.publish_download_item(
                    file_path=file_path,
                    filename=file_path.name,
                    title=title or file_path.name,
                    duration=duration,
                    ttl=4 * 3600,
                )
                return {
                    "delivery": "portal",
                    "file_path": str(record.file_path),
                    "filename": record.filename,
                    "file_size": record.file_size,
                    "file_size_mb": round(record.file_size / (1024 * 1024), 2),
                    "internet_url": record.internet_url,
                    "lan_url": record.lan_url,
                    "expires_at": record.expires_at,
                }
            except Exception as exc:
                logger.warning("[MultimediaService] Failed publishing to portal storage: %s", exc)

        return {
            "delivery": "direct",
            "file_path": str(file_path),
            "filename": file_path.name,
            "file_size": file_size,
            "file_size_mb": size_mb,
            "internet_url": None,
            "lan_url": None,
            "expires_at": None,
        }

    # ─── 1. EDIT VIDEO CLIP ───────────────────────────────────────────────────

    async def edit_video_clip(
        self,
        input_path_or_url: str,
        start_time: Union[str, float, int],
        duration: Optional[Union[str, float, int]] = None,
        end_time: Optional[Union[str, float, int]] = None,
        reencode: bool = False,
        output_format: Optional[str] = "mp4",
    ) -> Dict[str, Any]:
        """
        Cắt clip video theo mốc thời gian không encode lại (-c copy) hoặc re-encode chất lượng cao qua FFmpeg.
        """
        input_file, is_transient = await self._resolve_input(input_path_or_url)
        fmt = (output_format or "mp4").lstrip(".").lower()
        token = secrets.token_hex(6)
        out_file = self._temp_dir / f"clip_{token}.{fmt}"

        try:
            cmd = ["ffmpeg", "-y", "-nostdin", "-ss", str(start_time), "-i", str(input_file)]

            if duration is not None:
                cmd.extend(["-t", str(duration)])
            elif end_time is not None:
                cmd.extend(["-to", str(end_time)])

            if not reencode:
                # Fast copy mode: 0% CPU load, completes in <1s
                cmd.extend([
                    "-c", "copy",
                    "-avoid_negative_ts", "make_zero",
                    "-movflags", "+faststart",
                    str(out_file),
                ])
            else:
                # Frame-accurate re-encode mode with x264 veryfast preset
                cmd.extend([
                    "-c:v", "libx264",
                    "-preset", "veryfast",
                    "-crf", "22",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-threads", "2",
                    "-movflags", "+faststart",
                    str(out_file),
                ])

            code, _, stderr = await self._run_command(cmd, timeout=300)
            if code != 0:
                err_msg = stderr.decode("utf-8", errors="replace").strip()
                logger.error("[MultimediaService] edit_video_clip failed (code %d): %s", code, err_msg[-300:])
                return {
                    "status": "error",
                    "tool": "edit_video_clip",
                    "message": f"FFmpeg cắt video thất bại: {err_msg[-150:]}",
                }

            delivery_info = self._publish_or_direct(out_file, title=f"Video Clip {start_time}")
            return {
                "status": "ok",
                "tool": "edit_video_clip",
                "reencode": reencode,
                "start_time": str(start_time),
                "duration": duration,
                **delivery_info,
                "message": (
                    f"Đã cắt clip video thành công ({delivery_info['file_size_mb']} MB, "
                    f"chế độ {'Re-encode' if reencode else 'Fast-Copy'})."
                ),
            }
        finally:
            if is_transient and input_file.exists():
                input_file.unlink(missing_ok=True)

    # ─── 2. COMPRESS VIDEO (2-PASS BITRATE ALLOCATION) ──────────────────────────

    async def compress_video(
        self,
        input_path_or_url: str,
        target_size_mb: float = 48.0,
        max_dimension: Optional[int] = 1080,
    ) -> Dict[str, Any]:
        """
        Tự động tính toán 2-pass bitrate nén video dung lượng lớn xuống < 50MB để gửi qua Telegram.
        Sử dụng log prefix trong /tmp và dọn dẹp sạch sẽ Zero-Disk Leak.
        """
        input_file, is_transient = await self._resolve_input(input_path_or_url)
        token = secrets.token_hex(6)
        log_prefix = str(self._temp_dir / f"ffpass_{token}")
        out_file = self._temp_dir / f"compressed_{token}.mp4"

        try:
            # 1. Probe input duration
            probe_cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(input_file),
            ]
            code, stdout, _ = await self._run_command(probe_cmd, timeout=30)
            duration = 60.0
            if code == 0:
                try:
                    parsed_dur = float(stdout.decode().strip())
                    if parsed_dur > 0:
                        duration = parsed_dur
                except (ValueError, TypeError):
                    pass

            # 2. Compute 2-pass bitrate allocation (5% safety container muxing overhead)
            usable_bits = target_size_mb * 1024 * 1024 * 8 * 0.95
            total_bitrate = usable_bits / duration

            # Audio bitrate allocation based on total length
            audio_bps = 96000 if duration > 600 else 128000
            if total_bitrate <= (audio_bps + 100000):
                audio_bps = 64000
            video_bps = max(150000, int(total_bitrate - audio_bps))

            # 3. Optional video scaling filter
            vf_args: List[str] = []
            if max_dimension:
                vf_args = ["-vf", f"scale='min({max_dimension},iw)':-2"]

            # Null output sink cross-platform
            null_sink = "NUL" if os.name == "nt" else "/dev/null"

            # Pass 1: Analysis pass
            pass1_cmd = [
                "ffmpeg", "-y", "-nostdin",
                "-i", str(input_file),
            ] + vf_args + [
                "-c:v", "libx264",
                "-b:v", str(video_bps),
                "-pass", "1",
                "-passlogfile", log_prefix,
                "-an",
                "-f", "null",
                null_sink,
            ]
            p1_code, _, p1_err = await self._run_command(pass1_cmd, timeout=300)
            if p1_code != 0:
                return {
                    "status": "error",
                    "tool": "compress_video",
                    "message": f"FFmpeg Pass 1 thất bại: {p1_err.decode(errors='replace')[-150:]}",
                }

            # Pass 2: High quality encoding pass
            pass2_cmd = [
                "ffmpeg", "-y", "-nostdin",
                "-i", str(input_file),
            ] + vf_args + [
                "-c:v", "libx264",
                "-b:v", str(video_bps),
                "-pass", "2",
                "-passlogfile", log_prefix,
                "-c:a", "aac",
                "-b:a", f"{audio_bps // 1000}k",
                "-preset", "faster",
                "-threads", "2",
                "-movflags", "+faststart",
                str(out_file),
            ]
            p2_code, _, p2_err = await self._run_command(pass2_cmd, timeout=300)
            if p2_code != 0:
                return {
                    "status": "error",
                    "tool": "compress_video",
                    "message": f"FFmpeg Pass 2 thất bại: {p2_err.decode(errors='replace')[-150:]}",
                }

            delivery_info = self._publish_or_direct(out_file, title=f"Compressed Video ({target_size_mb}MB)", duration=int(duration))
            return {
                "status": "ok",
                "tool": "compress_video",
                "target_size_mb": target_size_mb,
                "video_bitrate_kbps": int(video_bps / 1000),
                "audio_bitrate_kbps": int(audio_bps / 1000),
                **delivery_info,
                "message": (
                    f"Đã nén video thành công về dung lượng {delivery_info['file_size_mb']} MB "
                    f"(mục tiêu {target_size_mb} MB, bitrate {int(video_bps/1000)}k)."
                ),
            }
        finally:
            # Purge passlogfile artifacts (Zero-Disk Leak)
            for ext in ["-0.log", "-0.log.mbtree"]:
                p = Path(f"{log_prefix}{ext}")
                p.unlink(missing_ok=True)
            if is_transient and input_file.exists():
                input_file.unlink(missing_ok=True)

    # ─── 3. CONVERT VIDEO FORMAT ──────────────────────────────────────────────

    async def convert_video_format(
        self,
        input_path_or_url: str,
        target_format: str,
    ) -> Dict[str, Any]:
        """
        Chuyển đổi qua lại giữa MP4, MKV, AVI, MOV, WEBM, GIF.
        """
        target_fmt = target_format.lstrip(".").lower()
        supported = {"mp4", "mkv", "avi", "mov", "webm", "gif"}
        if target_fmt not in supported:
            return {
                "status": "error",
                "tool": "convert_video_format",
                "message": f"Định dạng đích '{target_format}' không được hỗ trợ. Các định dạng hợp lệ: {', '.join(sorted(supported))}",
            }

        input_file, is_transient = await self._resolve_input(input_path_or_url)
        token = secrets.token_hex(6)
        out_file = self._temp_dir / f"conv_{token}.{target_fmt}"

        try:
            if target_fmt == "gif":
                # High-fidelity 2-phase palette generation to eliminate banding
                filter_str = (
                    "fps=15,scale=480:-1:flags=lanczos,split[s0][s1];"
                    "[s0]palettegen=stats_mode=diff[p];"
                    "[s1][p]paletteuse=dither=bayer:bayer_scale=3"
                )
                cmd = [
                    "ffmpeg", "-y", "-nostdin",
                    "-i", str(input_file),
                    "-vf", filter_str,
                    str(out_file),
                ]
            elif target_fmt == "webm":
                cmd = [
                    "ffmpeg", "-y", "-nostdin",
                    "-i", str(input_file),
                    "-c:v", "libvpx-vp9",
                    "-b:v", "0",
                    "-crf", "32",
                    "-c:a", "libopus",
                    "-b:a", "128k",
                    "-threads", "2",
                    str(out_file),
                ]
            elif target_fmt == "avi":
                cmd = [
                    "ffmpeg", "-y", "-nostdin",
                    "-i", str(input_file),
                    "-c:v", "mpeg4",
                    "-q:v", "4",
                    "-c:a", "mp3",
                    "-b:a", "192k",
                    "-threads", "2",
                    str(out_file),
                ]
            else:
                # mp4, mkv, mov
                cmd = [
                    "ffmpeg", "-y", "-nostdin",
                    "-i", str(input_file),
                    "-c:v", "libx264",
                    "-preset", "veryfast",
                    "-crf", "23",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-threads", "2",
                    "-movflags", "+faststart",
                    str(out_file),
                ]

            code, _, stderr = await self._run_command(cmd, timeout=300)
            if code != 0:
                err_msg = stderr.decode("utf-8", errors="replace").strip()
                return {
                    "status": "error",
                    "tool": "convert_video_format",
                    "message": f"FFmpeg chuyển đổi video sang {target_fmt.upper()} thất bại: {err_msg[-150:]}",
                }

            delivery_info = self._publish_or_direct(out_file, title=f"Converted {target_fmt.upper()}")
            return {
                "status": "ok",
                "tool": "convert_video_format",
                "target_format": target_fmt,
                **delivery_info,
                "message": f"Đã chuyển đổi định dạng sang {target_fmt.upper()} thành công ({delivery_info['file_size_mb']} MB).",
            }
        finally:
            if is_transient and input_file.exists():
                input_file.unlink(missing_ok=True)

    # ─── 4. CONVERT AUDIO FORMAT ──────────────────────────────────────────────

    async def convert_audio_format(
        self,
        input_path_or_url: str,
        target_format: str = "mp3",
        bitrate: str = "320k",
    ) -> Dict[str, Any]:
        """
        Chuyển đổi âm thanh chuyên nghiệp (FLAC/WAV/M4A/OGG/AAC -> MP3 320kbps).
        """
        target_fmt = target_format.lstrip(".").lower()
        supported = {"mp3", "wav", "flac", "m4a", "ogg", "aac"}
        if target_fmt not in supported:
            return {
                "status": "error",
                "tool": "convert_audio_format",
                "message": f"Định dạng âm thanh '{target_format}' không được hỗ trợ. Các định dạng: {', '.join(sorted(supported))}",
            }

        input_file, is_transient = await self._resolve_input(input_path_or_url)
        token = secrets.token_hex(6)
        out_file = self._temp_dir / f"audio_{token}.{target_fmt}"

        try:
            cmd = ["ffmpeg", "-y", "-nostdin", "-i", str(input_file), "-vn"]

            if target_fmt == "mp3":
                cmd.extend(["-c:a", "libmp3lame", "-b:a", bitrate, "-id3v2_version", "3"])
            elif target_fmt in ("m4a", "aac"):
                cmd.extend(["-c:a", "aac", "-b:a", bitrate])
            elif target_fmt == "ogg":
                cmd.extend(["-c:a", "libvorbis", "-b:a", bitrate])
            elif target_fmt == "flac":
                cmd.extend(["-c:a", "flac"])
            elif target_fmt == "wav":
                cmd.extend(["-c:a", "pcm_s16le"])

            cmd.append(str(out_file))

            code, _, stderr = await self._run_command(cmd, timeout=180)
            if code != 0:
                err_msg = stderr.decode("utf-8", errors="replace").strip()
                return {
                    "status": "error",
                    "tool": "convert_audio_format",
                    "message": f"FFmpeg chuyển đổi audio thất bại: {err_msg[-150:]}",
                }

            delivery_info = self._publish_or_direct(out_file, title=f"Audio {target_fmt.upper()} {bitrate}")
            return {
                "status": "ok",
                "tool": "convert_audio_format",
                "target_format": target_fmt,
                "bitrate": bitrate,
                **delivery_info,
                "message": f"Đã chuyển đổi âm thanh sang {target_fmt.upper()} ({bitrate}) thành công ({delivery_info['file_size_mb']} MB).",
            }
        finally:
            if is_transient and input_file.exists():
                input_file.unlink(missing_ok=True)

    # ─── 5. TRIM AUDIO CLIP ───────────────────────────────────────────────────

    async def trim_audio_clip(
        self,
        input_path_or_url: str,
        start_time: Union[str, float, int],
        duration: Optional[Union[str, float, int]] = None,
        end_time: Optional[Union[str, float, int]] = None,
        fade_in: float = 0.0,
        fade_out: float = 0.0,
        output_format: str = "mp3",
    ) -> Dict[str, Any]:
        """
        Cắt đoạn nhạc chuông / audio clip chính xác từng giây kèm hiệu ứng fade.
        """
        fmt = output_format.lstrip(".").lower()
        input_file, is_transient = await self._resolve_input(input_path_or_url)
        token = secrets.token_hex(6)
        out_file = self._temp_dir / f"ringtone_{token}.{fmt}"

        try:
            cmd = ["ffmpeg", "-y", "-nostdin", "-ss", str(start_time), "-i", str(input_file), "-vn"]

            if duration is not None:
                cmd.extend(["-t", str(duration)])
            elif end_time is not None:
                cmd.extend(["-to", str(end_time)])

            # Audio filter for fade-in / fade-out
            af_filters: List[str] = []
            if fade_in > 0:
                af_filters.append(f"afade=t=in:ss=0:d={fade_in}")
            if fade_out > 0 and duration is not None:
                try:
                    dur_val = float(duration)
                    start_fade = max(0.0, dur_val - fade_out)
                    af_filters.append(f"afade=t=out:st={start_fade}:d={fade_out}")
                except ValueError:
                    pass

            if af_filters:
                cmd.extend(["-af", ",".join(af_filters)])

            cmd.extend(["-c:a", "libmp3lame" if fmt == "mp3" else "aac", "-b:a", "320k", str(out_file)])

            code, _, stderr = await self._run_command(cmd, timeout=120)
            if code != 0:
                err_msg = stderr.decode("utf-8", errors="replace").strip()
                return {
                    "status": "error",
                    "tool": "trim_audio_clip",
                    "message": f"FFmpeg cắt audio clip thất bại: {err_msg[-150:]}",
                }

            delivery_info = self._publish_or_direct(out_file, title=f"Audio Ringtone {start_time}")
            return {
                "status": "ok",
                "tool": "trim_audio_clip",
                "start_time": str(start_time),
                "duration": duration,
                "fade_in": fade_in,
                "fade_out": fade_out,
                **delivery_info,
                "message": f"Đã cắt audio clip thành công ({delivery_info['file_size_mb']} MB).",
            }
        finally:
            if is_transient and input_file.exists():
                input_file.unlink(missing_ok=True)

    # ─── 6. NORMALIZE AUDIO VOLUME (EBU R128 LOUDNORM) ─────────────────────────

    async def normalize_audio_volume(
        self,
        input_path_or_url: str,
        target_i: float = -16.0,
        target_lra: float = 11.0,
        target_tp: float = -1.5,
    ) -> Dict[str, Any]:
        """
        Cân bằng âm lượng tự động (loudnorm filter chuẩn EBU R128).
        Nếu là video, giữ nguyên luồng hình ảnh (-c:v copy) để tiết kiệm CPU!
        """
        input_file, is_transient = await self._resolve_input(input_path_or_url)
        token = secrets.token_hex(6)
        suffix = input_file.suffix.lower()
        is_video = suffix in VIDEO_EXTENSIONS
        out_ext = suffix if suffix else (".mp4" if is_video else ".mp3")
        out_file = self._temp_dir / f"norm_{token}{out_ext}"

        try:
            loudnorm_filter = f"loudnorm=I={target_i}:LRA={target_lra}:TP={target_tp}"
            cmd = ["ffmpeg", "-y", "-nostdin", "-i", str(input_file)]

            if is_video:
                # Video passthrough: zero CPU load on video stream
                cmd.extend([
                    "-c:v", "copy",
                    "-af", loudnorm_filter,
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-movflags", "+faststart",
                    str(out_file),
                ])
            else:
                cmd.extend([
                    "-vn",
                    "-af", loudnorm_filter,
                    "-c:a", "libmp3lame",
                    "-b:a", "320k",
                    str(out_file),
                ])

            code, _, stderr = await self._run_command(cmd, timeout=300)
            if code != 0:
                err_msg = stderr.decode("utf-8", errors="replace").strip()
                return {
                    "status": "error",
                    "tool": "normalize_audio_volume",
                    "message": f"FFmpeg cân bằng âm lượng thất bại: {err_msg[-150:]}",
                }

            delivery_info = self._publish_or_direct(out_file, title="Normalized Media")
            return {
                "status": "ok",
                "tool": "normalize_audio_volume",
                "target_i": target_i,
                "is_video": is_video,
                **delivery_info,
                "message": (
                    f"Đã cân bằng âm lượng tự động theo chuẩn EBU R128 (I={target_i} LUFS) thành công "
                    f"({delivery_info['file_size_mb']} MB)."
                ),
            }
        finally:
            if is_transient and input_file.exists():
                input_file.unlink(missing_ok=True)

    # ─── 7. CONVERT AND RESIZE IMAGE ──────────────────────────────────────────

    async def convert_and_resize_image(
        self,
        input_path_or_url: str,
        format: Optional[str] = "webp",
        max_width: Optional[int] = None,
        max_height: Optional[int] = None,
        quality: int = 85,
    ) -> Dict[str, Any]:
        """
        Xử lý định dạng ảnh (WEBP, HEIC, PNG, JPG), nén và resize ảnh (Pillow, fallback FFmpeg cho HEIC).
        """
        target_fmt = (format or "webp").lstrip(".").lower()
        supported = {"webp", "png", "jpg", "jpeg", "heic"}
        if target_fmt not in supported:
            return {
                "status": "error",
                "tool": "convert_and_resize_image",
                "message": f"Định dạng ảnh '{format}' không được hỗ trợ. Các định dạng: {', '.join(sorted(supported))}",
            }

        input_file, is_transient = await self._resolve_input(input_path_or_url)
        token = secrets.token_hex(6)
        out_ext = ".jpg" if target_fmt in ("jpg", "jpeg") else f".{target_fmt}"
        out_file = self._temp_dir / f"img_{token}{out_ext}"
        temp_png: Optional[Path] = None

        try:
            # Handle HEIC decoding via FFmpeg if input is HEIC
            src_file_to_open = input_file
            if input_file.suffix.lower() == ".heic":
                temp_png = self._temp_dir / f"heic_decode_{token}.png"
                code, _, stderr = await self._run_command(
                    ["ffmpeg", "-y", "-nostdin", "-i", str(input_file), str(temp_png)],
                    timeout=60,
                )
                if code == 0 and temp_png.exists():
                    src_file_to_open = temp_png
                else:
                    return {
                        "status": "error",
                        "tool": "convert_and_resize_image",
                        "message": f"Không thể giải mã ảnh HEIC qua FFmpeg: {stderr.decode(errors='replace')[-150:]}",
                    }

            # Open with Pillow
            with Image.open(src_file_to_open) as img:
                orig_w, orig_h = img.size

                # Resize if maximum bounding box specified
                if max_width or max_height:
                    w = max_width or orig_w
                    h = max_height or orig_h
                    img.thumbnail((w, h), Image.Resampling.LANCZOS)

                # Format-specific channel handling
                if target_fmt in ("jpg", "jpeg"):
                    if img.mode in ("RGBA", "LA", "P"):
                        # Flatten alpha onto pure white background to avoid JPEG save crash
                        background = Image.new("RGB", img.size, (255, 255, 255))
                        if img.mode == "P":
                            img = img.convert("RGBA")
                        background.paste(img, mask=img.split()[-1] if "A" in img.mode else None)
                        img = background
                    else:
                        img = img.convert("RGB")
                    img.save(out_file, format="JPEG", quality=quality, optimize=True)

                elif target_fmt == "heic":
                    # Encode HEIC via FFmpeg x265
                    intermediate_png = self._temp_dir / f"heic_in_{token}.png"
                    img.save(intermediate_png, format="PNG")
                    try:
                        code, _, stderr = await self._run_command(
                            ["ffmpeg", "-y", "-nostdin", "-i", str(intermediate_png), "-c:v", "libx265", "-crf", "28", str(out_file)],
                            timeout=60,
                        )
                        if code != 0:
                            return {
                                "status": "error",
                                "tool": "convert_and_resize_image",
                                "message": f"FFmpeg mã hóa HEIC thất bại: {stderr.decode(errors='replace')[-150:]}",
                            }
                    finally:
                        intermediate_png.unlink(missing_ok=True)

                else:
                    # WEBP, PNG
                    save_fmt = "WEBP" if target_fmt == "webp" else "PNG"
                    save_kwargs: Dict[str, Any] = {"format": save_fmt}
                    if target_fmt == "webp":
                        save_kwargs["quality"] = quality
                    img.save(out_file, **save_kwargs)

            delivery_info = self._publish_or_direct(out_file, title=f"Image {target_fmt.upper()}")
            return {
                "status": "ok",
                "tool": "convert_and_resize_image",
                "format": target_fmt,
                "original_dimensions": f"{orig_w}x{orig_h}",
                **delivery_info,
                "message": f"Đã xử lý ảnh sang định dạng {target_fmt.upper()} thành công ({delivery_info['file_size_mb']} MB).",
            }
        finally:
            if temp_png and temp_png.exists():
                temp_png.unlink(missing_ok=True)
            if is_transient and input_file.exists():
                input_file.unlink(missing_ok=True)

    # ─── 8. GENERATE CUSTOM QR CODE ───────────────────────────────────────────

    async def generate_custom_qr(
        self,
        content: str,
        label: Optional[str] = None,
        fill_color: str = "#0f172a",
        back_color: str = "#ffffff",
        box_size: int = 10,
    ) -> Dict[str, Any]:
        """
        Sinh mã QR Code độ phân giải cao in-memory từ nội dung bất kỳ qua qrcode[pil].
        Hỗ trợ nhãn ghi chú căn giữa dưới chân mã QR.
        """
        clean_content = str(content).strip()
        if not clean_content:
            return {
                "status": "error",
                "tool": "generate_custom_qr",
                "message": "Nội dung tạo mã QR không được để trống.",
            }

        # ERROR_CORRECT_H allows up to 30% data recovery
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=max(2, min(50, box_size)),
            border=2,
        )
        qr.add_data(clean_content)
        qr.make(fit=True)

        qr_img = qr.make_image(fill_color=fill_color, back_color=back_color).convert("RGBA")

        # Extend canvas if text label is specified
        if label and label.strip():
            label_text = label.strip()
            font = ImageFont.load_default()

            # Estimate text bounding box
            dummy_img = Image.new("RGBA", (1, 1))
            draw_dummy = ImageDraw.Draw(dummy_img)
            bbox = draw_dummy.textbbox((0, 0), label_text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]

            banner_h = text_h + 24
            canvas_w = max(qr_img.width, text_w + 32)
            canvas_h = qr_img.height + banner_h

            composite = Image.new("RGBA", (canvas_w, canvas_h), back_color)
            qr_x = (canvas_w - qr_img.width) // 2
            composite.paste(qr_img, (qr_x, 0))

            draw = ImageDraw.Draw(composite)
            text_x = (canvas_w - text_w) // 2
            text_y = qr_img.height + (banner_h - text_h) // 2
            draw.text((text_x, text_y), label_text, fill=fill_color, font=font)
            final_img = composite
        else:
            final_img = qr_img

        # Save to in-memory bytes buffer (Zero-Disk Leak)
        buffer = io.BytesIO()
        final_img.save(buffer, format="PNG")
        png_bytes = buffer.getvalue()
        buffer.close()

        # Also save to scratch file for delivery
        token = secrets.token_hex(6)
        out_file = self._temp_dir / f"qr_{token}.png"
        with open(out_file, "wb") as f:
            f.write(png_bytes)

        delivery_info = self._publish_or_direct(out_file, title="Custom QR Code")
        return {
            "status": "ok",
            "tool": "generate_custom_qr",
            "content": clean_content,
            "label": label,
            "width": final_img.width,
            "height": final_img.height,
            "base64_png": base64.b64encode(png_bytes).decode("ascii"),
            **delivery_info,
            "message": f"Đã sinh mã QR Code độ phân giải cao thành công ({final_img.width}x{final_img.height} px).",
        }
