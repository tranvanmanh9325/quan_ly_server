"""
Video Editor Service for AI Agent Tieu Bao Bao (Milestone 2).
Provides 9 studio-grade video processing tools with hardware safety (concurrency bounding),
non-blocking subprocess execution, secure path traversal validation, Dual-Delivery,
and Zero-Disk Leak guarantees.
"""

import asyncio
import logging
import os
import posixpath
import re
import secrets
import shutil
import tempfile
import urllib.parse
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx

try:
    from app.services.media_storage_manager import media_storage_manager
except ImportError:
    media_storage_manager = None

logger = logging.getLogger(__name__)

# Telegram Bot API direct send size limit (50 MB)
TELEGRAM_MAX_FILE_SIZE = 50 * 1024 * 1024

# Allowed file extensions for video operations
SUPPORTED_VIDEO_EXTENSIONS = frozenset({
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".m4v", ".ts"
})


class VideoEditorService:
    """
    Core engine for professional video editing tools.
    Adheres strictly to the concurrency limits (2 concurrent FFmpeg tasks, 1 inpaint task)
    to protect the host machine (2 CPU cores, 3.2GB RAM).
    """

    def __init__(
        self,
        storage_manager: Any = None,
        http_client: Optional[httpx.AsyncClient] = None,
        temp_dir: Optional[Union[str, Path]] = None,
    ):
        self._storage = storage_manager if storage_manager is not None else media_storage_manager
        self._http = http_client
        # Limit concurrent FFmpeg loads to 2 to prevent CPU starvation on 2 cores
        self._semaphore = asyncio.Semaphore(2)
        # Limit CPU-heavy OpenCV inpainting tasks to 1 to preserve system responsiveness
        self._inpaint_semaphore = asyncio.Semaphore(1)

        base_temp = Path(temp_dir or os.getenv("MEDIA_STUDIO_TEMP_DIR", tempfile.gettempdir()))
        self._temp_dir = base_temp / "video_editor"
        self._ensure_temp_dir()

    def _ensure_temp_dir(self) -> None:
        """Create scratch directory if missing."""
        try:
            self._temp_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            logger.warning("[VideoEditorService] Failed to create scratch directory %s: %s", self._temp_dir, exc)

    def _get_allowed_bases(self) -> List[Path]:
        """
        Returns authorized sandbox base directories.
        Permits scratch temp dirs, system temp, project repo root, and /home/kirito.
        """
        bases: List[Path] = []
        if hasattr(self, "_temp_dir") and self._temp_dir:
            bases.append(self._temp_dir.resolve())
        bases.append(Path(tempfile.gettempdir()).resolve())
        posix_tmp = Path("/tmp")
        if posix_tmp.exists():
            bases.append(posix_tmp.resolve())
        bases.append(Path.cwd().resolve())

        # Project root resolution (services/ai-agent-service/app/services -> repo root)
        try:
            repo_root = Path(__file__).resolve().parents[4]
            bases.append(repo_root.resolve())
        except (IndexError, ValueError):
            pass

        repo_explicit = Path("d:/GitHub/quan_ly_server")
        if repo_explicit.exists():
            bases.append(repo_explicit.resolve())

        home_kirito = Path("/home/kirito")
        if home_kirito.exists():
            bases.append(home_kirito.resolve())

        return bases

    def _is_safe_in_sandbox(self, p: Path) -> bool:
        """Checks if a resolved path is contained within authorized sandbox bases."""
        allowed_bases = self._get_allowed_bases()
        for base in allowed_bases:
            try:
                if p.is_relative_to(base):
                    return True
            except (ValueError, TypeError):
                continue
        return False

    def _validate_path_security(self, raw_path: str) -> None:
        """
        Validate path security to prevent path traversal, UNC attacks, drive injections,
        and access outside authorized sandbox boundaries.
        Why: Adversarial inputs may attempt to escape the filesystem boundary or probe sensitive system files.
        """
        if not raw_path or not isinstance(raw_path, str):
            raise ValueError("Đường dẫn tệp không hợp lệ.")

        # Decode percent-encoded characters twice to catch double-encoding attacks
        decoded = urllib.parse.unquote(raw_path)
        decoded = urllib.parse.unquote(decoded)

        # Normalize backslashes to forward slashes for unified cross-platform evaluation
        normalized = decoded.replace("\\", "/")

        # Reject UNC network paths (e.g. //server/share, \\server\share)
        if normalized.startswith("//") or raw_path.startswith("\\\\"):
            raise PermissionError(f"Truy cập đường dẫn mạng UNC bị từ chối: {raw_path}")

        # Reject Windows drive letters (e.g. C:/, D:\, C:cmd.exe)
        if re.search(r"^[A-Za-z]:", normalized):
            if os.name != "nt":
                raise PermissionError(f"Truy cập đường dẫn Windows drive letter bị từ chối: {raw_path}")
            else:
                # On Windows, relative drive letters or unauthorized drives outside sandbox must be blocked
                if re.match(r"^[A-Za-z]:[^/]", normalized):
                    raise PermissionError(f"Truy cập đường dẫn Windows drive letter bị từ chối: {raw_path}")
                try:
                    candidate = Path(normalized).resolve()
                    if not self._is_safe_in_sandbox(candidate):
                        raise PermissionError(f"Truy cập đường dẫn Windows drive letter bị từ chối: {raw_path}")
                except PermissionError:
                    raise
                except Exception:
                    raise PermissionError(f"Truy cập đường dẫn Windows drive letter bị từ chối: {raw_path}")

        # Check for directory traversal sequences
        parts = normalized.split("/")
        if ".." in parts:
            raise PermissionError(f"Phát hiện hành vi Path Traversal ('..'): {raw_path}")

        # Sandbox Whitelist validation for POSIX paths and all resolved targets
        try:
            candidate_path = Path(normalized).resolve()
        except Exception:
            raise ValueError("Đường dẫn nằm ngoài thư mục sandbox được phép.")

        if not self._is_safe_in_sandbox(candidate_path):
            raise ValueError("Đường dẫn nằm ngoài thư mục sandbox được phép.")

    async def _run_command(
        self,
        cmd: List[str],
        timeout: int = 300,
    ) -> Tuple[int, bytes, bytes]:
        """
        Executes a subprocess safely with concurrency bounding and strict timeout.
        Why List[str]: Prevents command injection attacks; shell=True is strictly forbidden.
        """
        async with self._semaphore:
            logger.debug("[VideoEditorService] Executing command: %s", " ".join(cmd[:8]))
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                return proc.returncode or 0, stdout, stderr
            except asyncio.TimeoutError:
                logger.error("[VideoEditorService] Subprocess timed out after %ds: %s", timeout, cmd[0])
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
                raise TimeoutError(f"Tác vụ xử lý video vượt quá thời gian tối đa ({timeout}s).")

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
            url_name = Path(urllib.parse.urlsplit(clean_input).path).name or "input_remote.mp4"
            token = secrets.token_hex(6)
            download_dest = self._temp_dir / f"dl_{token}_{url_name}"

            client = self._http
            should_close_client = False
            if client is None:
                client = httpx.AsyncClient(timeout=60.0, follow_redirects=True)
                should_close_client = True

            try:
                try:
                    async with client.stream("GET", clean_input) as resp:
                        resp.raise_for_status()
                        with open(download_dest, "wb") as f:
                            async for chunk in resp.aiter_bytes(chunk_size=65536):
                                f.write(chunk)
                    return download_dest, True
                except Exception:
                    if download_dest.exists():
                        download_dest.unlink(missing_ok=True)
                    raise
            finally:
                if should_close_client:
                    await client.aclose()

        # Handle local filesystem path with security validation
        self._validate_path_security(clean_input)
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
        formatted_size = f"{size_mb} MB" if size_mb >= 1.0 else f"{round(file_size / 1024, 1)} KB"

        if file_size <= TELEGRAM_MAX_FILE_SIZE:
            return {
                "delivery": "direct",
                "file_path": str(file_path),
                "filename": file_path.name,
                "file_size": file_size,
                "file_size_formatted": formatted_size,
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
                    ttl_seconds=4 * 3600,
                )
                return {
                    "delivery": "portal",
                    "file_path": str(record.file_path),
                    "filename": record.filename,
                    "file_size": record.file_size,
                    "file_size_formatted": formatted_size,
                    "file_size_mb": round(record.file_size / (1024 * 1024), 2),
                    "internet_url": record.internet_url,
                    "lan_url": record.lan_url,
                    "expires_at": record.expires_at,
                }
            except Exception as exc:
                logger.warning("[VideoEditorService] Failed publishing to portal storage: %s", exc)

        return {
            "delivery": "direct",
            "file_path": str(file_path),
            "filename": file_path.name,
            "file_size": file_size,
            "file_size_formatted": formatted_size,
            "file_size_mb": size_mb,
            "internet_url": None,
            "lan_url": None,
            "expires_at": None,
        }

    # ─── 1. REMOVE TEXT FROM VIDEO ──────────────────────────────────────────

    async def remove_text_from_video(
        self,
        input_path_or_url: str,
        region: Optional[Dict[str, int]] = None,
        mode: str = "delogo",
        output_format: str = "mp4",
    ) -> Dict[str, Any]:
        """
        Removes text, watermark, or static overlays from video.
        Modes supported:
          - 'delogo': Native fast FFmpeg delogo filter (default).
          - 'inpaint': High-quality OpenCV Telea inpainting.
          - 'auto': Automatic detection of text bounding box via OCR sampling, then delogo/inpaint.
        """
        valid_modes = {"delogo", "inpaint", "auto"}
        clean_mode = str(mode).strip().lower()
        if clean_mode not in valid_modes:
            raise ValueError(f"Mode '{mode}' không hợp lệ. Chỉ hỗ trợ: {', '.join(sorted(valid_modes))}.")

        input_file, is_transient = await self._resolve_input(input_path_or_url)
        token = secrets.token_hex(6)
        out_ext = output_format.lstrip(".").lower()
        output_file = self._temp_dir / f"clean_{token}.{out_ext}"
        mode_used = clean_mode
        success = False

        try:
            # Handle 'auto' mode: Detect text bounding box across sample frames
            if clean_mode == "auto":
                if region is None:
                    region = await self._auto_detect_text_region(input_file)
                mode_used = "delogo"

            # Validate target region coordinates
            target_region = region or {"x": 50, "y": 145, "w": 475, "h": 125}
            self._validate_region_dict(target_region)

            rx = int(target_region["x"])
            ry = int(target_region["y"])
            rw = int(target_region["w"])
            rh = int(target_region["h"])

            if mode_used == "delogo":
                rx = max(1, rx)
                ry = max(1, ry)
                rw = max(1, rw)
                rh = max(1, rh)
                delogo_vf = f"delogo=x={rx}:y={ry}:w={rw}:h={rh}:show=0"
                cmd = [
                    "ffmpeg", "-y",
                    "-i", str(input_file),
                    "-vf", delogo_vf,
                    "-c:a", "copy",
                    "-movflags", "+faststart",
                    str(output_file),
                ]
                code, stdout, stderr = await self._run_command(cmd, timeout=300)
                if code != 0:
                    err_msg = stderr.decode(errors="replace").strip()
                    raise RuntimeError(f"FFmpeg delogo thất bại (code {code}): {err_msg[-200:]}")

            elif mode_used == "inpaint":
                try:
                    import cv2
                except (ImportError, ModuleNotFoundError):
                    raise RuntimeError("opencv-python-headless chưa được cài đặt. Vui lòng dùng mode='delogo'.")

                async with self._inpaint_semaphore:
                    await asyncio.to_thread(
                        self._inpaint_video_sync,
                        input_file,
                        output_file,
                        rx, ry, rw, rh,
                    )

            delivery_info = self._publish_or_direct(output_file, title="Video đã xóa text")
            success = True
            return {
                "status": "ok",
                "tool": "remove_text_from_video",
                "mode_requested": clean_mode,
                "mode_used": mode_used,
                "region": {"x": rx, "y": ry, "w": rw, "h": rh},
                "output_path": str(output_file),
                **delivery_info,
                "message": f"Đã xóa text/watermark thành công bằng mode '{mode_used}' tại tọa độ ({rx},{ry},{rw}x{rh}).",
            }

        finally:
            if not success and output_file.exists():
                output_file.unlink(missing_ok=True)
            if is_transient and input_file.exists():
                input_file.unlink(missing_ok=True)

    def _validate_region_dict(self, region: Dict[str, Any]) -> None:
        """Validate bounding box region coordinates."""
        for k in ("x", "y", "w", "h"):
            if k not in region:
                raise ValueError(f"Thiếu tham số tọa độ '{k}' trong region.")
            val = region[k]
            if not isinstance(val, (int, float)) or int(val) < 0:
                raise ValueError(f"Tọa độ '{k}' phải là số nguyên không âm.")
            if int(val) > 10000:
                raise ValueError(f"Tọa độ '{k}' ({val}) vượt quá giới hạn an toàn 10000px.")
        if int(region["w"]) <= 0 or int(region["h"]) <= 0:
            raise ValueError("Kích thước chiều rộng (w) và chiều cao (h) phải lớn hơn 0.")

    async def _auto_detect_text_region(self, input_file: Path) -> Dict[str, int]:
        """
        Samples 5 keyframes and runs pytesseract to identify text bounding boxes.
        Falls back to default coordinates if pytesseract is unavailable or no text is detected.
        """
        default_fallback = {"x": 0, "y": 0, "w": 200, "h": 50}
        token = secrets.token_hex(4)
        sample_dir = self._temp_dir / f"samples_{token}"
        sample_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Extract 5 sample frames spread across the video
            cmd = [
                "ffmpeg", "-y",
                "-i", str(input_file),
                "-vf", "select=eq(n\\,0)+eq(n\\,50)+eq(n\\,100)+eq(n\\,200)+eq(n\\,400)",
                "-vsync", "0",
                str(sample_dir / "sample_%02d.jpg"),
            ]
            code, _, _ = await self._run_command(cmd, timeout=30)
            if code != 0:
                return default_fallback

            try:
                import pytesseract
                from PIL import Image
            except (ImportError, ModuleNotFoundError):
                return default_fallback

            frames = sorted(list(sample_dir.glob("sample_*.jpg")))
            if not frames:
                return default_fallback

            min_x, min_y = 99999, 99999
            max_x, max_y = 0, 0
            found_text = False

            frame_w, frame_h = 0, 0
            for frame_path in frames:
                try:
                    with Image.open(frame_path) as img:
                        if hasattr(img, "width") and isinstance(img.width, int):
                            frame_w = max(frame_w, img.width)
                            frame_h = max(frame_h, img.height)
                        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
                        n_boxes = len(data.get("text", []))
                        for i in range(n_boxes):
                            conf = int(data["conf"][i]) if str(data["conf"][i]).isdigit() else -1
                            text = str(data["text"][i]).strip()
                            if conf > 30 and len(text) > 0:
                                found_text = True
                                x = int(data["left"][i])
                                y = int(data["top"][i])
                                w = int(data["width"][i])
                                h = int(data["height"][i])
                                min_x = min(min_x, x)
                                min_y = min(min_y, y)
                                max_x = max(max_x, x + w)
                                max_y = max(max_y, y + h)
                except Exception:
                    pass

            if found_text and max_x > min_x and max_y > min_y:
                # Add a 10px margin around detected text clamped within frame borders
                pad = 10
                fx = max(1, min_x - pad) if frame_w > 2 else max(0, min_x - pad)
                fy = max(1, min_y - pad) if frame_h > 2 else max(0, min_y - pad)
                max_x_clamped = min(frame_w - 2, max_x + pad) if frame_w > 2 else max_x + pad
                max_y_clamped = min(frame_h - 2, max_y + pad) if frame_h > 2 else max_y + pad
                fw = max(1, max_x_clamped - fx)
                fh = max(1, max_y_clamped - fy)
                return {"x": fx, "y": fy, "w": fw, "h": fh}

            return default_fallback

        finally:
            shutil.rmtree(sample_dir, ignore_errors=True)

    def _inpaint_video_sync(
        self,
        input_file: Path,
        output_file: Path,
        rx: int,
        ry: int,
        rw: int,
        rh: int,
    ) -> None:
        """
        Synchronous worker for OpenCV Telea video frame inpainting.
        Re-assembles the video with original audio via FFmpeg stream copy.
        """
        import cv2
        import numpy as np

        cap = cv2.VideoCapture(str(input_file))
        if not cap.isOpened():
            raise RuntimeError(f"Không thể mở video qua OpenCV: {input_file}")

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        # Clamp bounding box to frame boundaries
        rx = max(0, min(rx, width - 1))
        ry = max(0, min(ry, height - 1))
        rw = max(1, min(rw, width - rx))
        rh = max(1, min(rh, height - ry))

        # Create binary inpainting mask
        mask = np.zeros((height, width), dtype=np.uint8)
        mask[ry : ry + rh, rx : rx + rw] = 255

        token = secrets.token_hex(4)
        raw_video_path = self._temp_dir / f"inp_raw_{token}.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out = cv2.VideoWriter(str(raw_video_path), fourcc, fps, (width, height))

        try:
            try:
                while cap.isOpened():
                    ret, frame = cap.read()
                    if not ret:
                        break
                    inpainted = cv2.inpaint(frame, mask, 7, cv2.INPAINT_TELEA)
                    out.write(inpainted)
            finally:
                cap.release()
                out.release()

            # Combine video stream with original audio stream using FFmpeg
            merge_cmd = [
                "ffmpeg", "-y",
                "-i", str(raw_video_path),
                "-i", str(input_file),
                "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                "-c:a", "copy",
                "-map", "0:v:0",
                "-map", "1:a:0?",
                "-shortest",
                "-movflags", "+faststart",
                str(output_file),
            ]
            import subprocess
            proc = subprocess.run(merge_cmd, capture_output=True)
            if proc.returncode != 0:
                err = proc.stderr.decode(errors="replace")
                raise RuntimeError(f"FFmpeg ghép âm thanh sau khi inpaint thất bại: {err[-200:]}")
        finally:
            raw_video_path.unlink(missing_ok=True)

    # ─── 2. ADD SUBTITLE TO VIDEO ────────────────────────────────────────────

    async def add_subtitle_to_video(
        self,
        input_path_or_url: str,
        subtitle_text_or_path: str,
        style: Optional[Dict[str, Any]] = None,
        position: str = "bottom",
        output_format: str = "mp4",
    ) -> Dict[str, Any]:
        """
        Burns subtitles or text captions directly into video frames.
        Supports .srt subtitle files or auto-generating timestamps from raw text.
        """
        valid_positions = {"bottom", "top", "center"}
        clean_pos = str(position).strip().lower()
        if clean_pos not in valid_positions:
            raise ValueError(f"Vị trí '{position}' không hợp lệ. Chỉ hỗ trợ: bottom, top, center.")

        input_file, is_transient = await self._resolve_input(input_path_or_url)
        token = secrets.token_hex(6)
        out_ext = output_format.lstrip(".").lower()
        output_file = self._temp_dir / f"subbed_{token}.{out_ext}"
        success = False

        temp_srt_file: Optional[Path] = None
        try:
            clean_sub = str(subtitle_text_or_path).strip()
            # Determine if input is a local .srt file or raw text
            if clean_sub.lower().endswith(".srt"):
                self._validate_path_security(clean_sub)
                local_srt = Path(clean_sub).resolve()
                if not local_srt.exists():
                    raise FileNotFoundError(f"Tệp phụ đề .srt không tồn tại: {clean_sub}")
                srt_path = local_srt
            else:
                # Create a temporary .srt file from plain text lines
                temp_srt_file = self._temp_dir / f"gen_sub_{token}.srt"
                lines = [line.strip() for line in clean_sub.splitlines() if line.strip()]
                if not lines:
                    lines = [clean_sub]

                srt_content = []
                for idx, line in enumerate(lines, start=1):
                    start_sec = (idx - 1) * 5
                    end_sec = start_sec + 5
                    sh, sm, ss = start_sec // 3600, (start_sec % 3600) // 60, start_sec % 60
                    eh, em, es = end_sec // 3600, (end_sec % 3600) // 60, end_sec % 60
                    srt_content.append(f"{idx}\n{sh:02d}:{sm:02d}:{ss:02d},000 --> {eh:02d}:{em:02d}:{es:02d},000\n{line}\n")

                with open(temp_srt_file, "w", encoding="utf-8") as f:
                    f.write("\n".join(srt_content))
                srt_path = temp_srt_file

            # Configure subtitle style options with safe sanitation against filtergraph injection
            # Alignment: 2 = bottom-center, 6 = top-center, 10 = middle-center in SubStation Alpha
            align_map = {"bottom": 2, "top": 6, "center": 10}
            font_size = int((style or {}).get("fontsize", 22))
            raw_color = str((style or {}).get("color", "&H00FFFFFF"))
            font_color = re.sub(r"[^A-Za-z0-9#&_]", "", raw_color) or "&H00FFFFFF"
            raw_outline = str((style or {}).get("outline", "&H00000000"))
            outline_color = re.sub(r"[^A-Za-z0-9#&_]", "", raw_outline) or "&H00000000"

            # Escape path for FFmpeg subtitles filter: colons and backslashes
            escaped_srt = str(srt_path).replace("\\", "/").replace(":", "\\:")
            style_str = f"Alignment={align_map[clean_pos]},FontSize={font_size},PrimaryColour={font_color},OutlineColour={outline_color}"
            vf_arg = f"subtitles='{escaped_srt}':force_style='{style_str}'"

            cmd = [
                "ffmpeg", "-y",
                "-i", str(input_file),
                "-vf", vf_arg,
                "-c:a", "copy",
                "-movflags", "+faststart",
                str(output_file),
            ]
            code, stdout, stderr = await self._run_command(cmd, timeout=300)
            if code != 0:
                err_msg = stderr.decode(errors="replace").strip()
                raise RuntimeError(f"FFmpeg thêm phụ đề thất bại (code {code}): {err_msg[-200:]}")

            delivery_info = self._publish_or_direct(output_file, title="Video gắn phụ đề")
            success = True
            return {
                "status": "ok",
                "tool": "add_subtitle_to_video",
                "position": clean_pos,
                "output_path": str(output_file),
                **delivery_info,
                "message": f"Đã gắn phụ đề vào video thành công tại vị trí '{clean_pos}'.",
            }

        finally:
            if not success and output_file.exists():
                output_file.unlink(missing_ok=True)
            if temp_srt_file and temp_srt_file.exists():
                temp_srt_file.unlink(missing_ok=True)
            if is_transient and input_file.exists():
                input_file.unlink(missing_ok=True)

    # ─── 3. APPLY COLOR GRADE ────────────────────────────────────────────────

    async def apply_color_grade(
        self,
        input_path_or_url: str,
        preset: str = "vivid",
        custom_eq: Optional[Dict[str, Any]] = None,
        output_format: str = "mp4",
    ) -> Dict[str, Any]:
        """
        Applies aesthetic color grading presets or custom equalizers to video.
        Presets: vivid, vintage, cinematic, cool, warm, bw, custom.
        """
        preset_filters = {
            "vivid": "eq=contrast=1.2:saturation=1.3:brightness=0.02",
            "vintage": "curves=vintage,hue=s=0.85",
            "cinematic": "curves=strong_contrast,eq=saturation=1.15",
            "cool": "colorbalance=bs=0.15:bm=0.1:bh=0.1:rs=-0.1:rm=-0.1:rh=-0.1",
            "warm": "colorbalance=rs=0.15:rm=0.1:rh=0.1:bs=-0.1:bm=-0.1:bh=-0.1",
            "bw": "hue=s=0",
        }

        clean_preset = str(preset).strip().lower()
        if clean_preset not in preset_filters and clean_preset != "custom":
            raise ValueError(
                f"Preset '{preset}' không hợp lệ. Chỉ hỗ trợ: {', '.join(sorted(preset_filters.keys()))}, custom."
            )

        if clean_preset == "custom":
            ceq = custom_eq or {}
            c = float(ceq.get("contrast", 1.0))
            b = float(ceq.get("brightness", 0.0))
            s = float(ceq.get("saturation", 1.0))
            g = float(ceq.get("gamma", 1.0))
            vf_filter = f"eq=contrast={c}:brightness={b}:saturation={s}:gamma={g}"
        else:
            vf_filter = preset_filters[clean_preset]

        input_file, is_transient = await self._resolve_input(input_path_or_url)
        token = secrets.token_hex(6)
        out_ext = output_format.lstrip(".").lower()
        output_file = self._temp_dir / f"color_{token}.{out_ext}"
        success = False

        try:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(input_file),
                "-vf", vf_filter,
                "-c:a", "copy",
                "-movflags", "+faststart",
                str(output_file),
            ]
            code, stdout, stderr = await self._run_command(cmd, timeout=300)
            if code != 0:
                err_msg = stderr.decode(errors="replace").strip()
                raise RuntimeError(f"FFmpeg chỉnh màu thất bại (code {code}): {err_msg[-200:]}")

            delivery_info = self._publish_or_direct(output_file, title=f"Video Color Grade ({clean_preset})")
            success = True
            return {
                "status": "ok",
                "tool": "apply_color_grade",
                "preset": clean_preset,
                "filter_applied": vf_filter,
                "output_path": str(output_file),
                **delivery_info,
                "message": f"Đã áp dụng bộ lọc màu '{clean_preset}' thành công.",
            }

        finally:
            if not success and output_file.exists():
                output_file.unlink(missing_ok=True)
            if is_transient and input_file.exists():
                input_file.unlink(missing_ok=True)

    # ─── 4. STABILIZE VIDEO ──────────────────────────────────────────────────

    async def stabilize_video(
        self,
        input_path_or_url: str,
        smoothing: int = 10,
        output_format: str = "mp4",
    ) -> Dict[str, Any]:
        """
        Stabilizes shaky camera footage using FFmpeg vidstab 2-pass analysis and transformation.
        """
        if not isinstance(smoothing, (int, float)) or int(smoothing) < 1 or int(smoothing) > 60:
            raise ValueError(f"Độ mượt smoothing ({smoothing}) phải nằm trong khoảng từ 1 đến 60.")

        input_file, is_transient = await self._resolve_input(input_path_or_url)
        token = secrets.token_hex(6)
        transforms_file = self._temp_dir / f"transforms_{token}.trf"
        out_ext = output_format.lstrip(".").lower()
        output_file = self._temp_dir / f"stab_{token}.{out_ext}"
        success = False

        try:
            # Pass 1: Detect camera motion vectors
            # Escape path for transforms file
            escaped_trf = str(transforms_file).replace("\\", "/").replace(":", "\\:")
            pass1_vf = f"vidstabdetect=shakiness=5:accuracy=15:result='{escaped_trf}'"
            pass1_cmd = [
                "ffmpeg", "-y",
                "-i", str(input_file),
                "-vf", pass1_vf,
                "-an",
                "-f", "null",
                "-",
            ]
            code1, _, stderr1 = await self._run_command(pass1_cmd, timeout=300)
            if code1 != 0:
                err_msg = stderr1.decode(errors="replace").strip()
                raise RuntimeError(f"FFmpeg vidstabdetect Pass 1 thất bại: {err_msg[-200:]}")

            # Pass 2: Transform frames and compensate motion
            pass2_vf = f"vidstabtransform=smoothing={int(smoothing)}:input='{escaped_trf}',unsharp=5:5:0.8"
            pass2_cmd = [
                "ffmpeg", "-y",
                "-i", str(input_file),
                "-vf", pass2_vf,
                "-c:a", "copy",
                "-movflags", "+faststart",
                str(output_file),
            ]
            code2, _, stderr2 = await self._run_command(pass2_cmd, timeout=300)
            if code2 != 0:
                err_msg = stderr2.decode(errors="replace").strip()
                raise RuntimeError(f"FFmpeg vidstabtransform Pass 2 thất bại: {err_msg[-200:]}")

            delivery_info = self._publish_or_direct(output_file, title="Video chống rung")
            success = True
            return {
                "status": "ok",
                "tool": "stabilize_video",
                "smoothing": int(smoothing),
                "output_path": str(output_file),
                **delivery_info,
                "message": f"Đã ổn định khung hình video 2-pass thành công (smoothing: {smoothing}).",
            }

        finally:
            if not success and output_file.exists():
                output_file.unlink(missing_ok=True)
            if transforms_file.exists():
                transforms_file.unlink(missing_ok=True)
            if is_transient and input_file.exists():
                input_file.unlink(missing_ok=True)

    # ─── 5. CONCATENATE VIDEOS ───────────────────────────────────────────────

    async def concatenate_videos(
        self,
        input_paths: List[str],
        output_format: str = "mp4",
        reencode: bool = False,
    ) -> Dict[str, Any]:
        """
        Concatenates multiple video clips in sequential order (1 to 10 clips).
        Checks total input file size to not exceed 500MB.
        """
        if not input_paths or not isinstance(input_paths, list):
            raise ValueError("Danh sách video đầu vào không được để trống.")

        if not (1 <= len(input_paths) <= 10):
            raise ValueError(f"Số lượng video ghép nối phải từ 1 đến 10 clip. Hiện tại: {len(input_paths)}.")

        resolved_files: List[Tuple[Path, bool]] = []
        token = secrets.token_hex(6)
        concat_list_file = self._temp_dir / f"concat_{token}.txt"
        out_ext = output_format.lstrip(".").lower()
        output_file = self._temp_dir / f"merged_{token}.{out_ext}"
        success = False

        try:
            total_size = 0
            for item in input_paths:
                fpath, is_trans = await self._resolve_input(str(item).strip())
                resolved_files.append((fpath, is_trans))
                total_size += fpath.stat().st_size

            # Enforce 500MB safety ceiling for video concatenation
            max_concat_size = 500 * 1024 * 1024
            if total_size > max_concat_size:
                size_mb = round(total_size / (1024 * 1024), 2)
                raise ValueError(f"Tổng dung lượng ({size_mb}MB) vượt quá giới hạn an toàn 500MB.")

            # Create FFmpeg concat demuxer file
            with open(concat_list_file, "w", encoding="utf-8") as f:
                for fpath, _ in resolved_files:
                    escaped_line = str(fpath).replace("'", "'\\''")
                    f.write(f"file '{escaped_line}'\n")

            if reencode:
                cmd = [
                    "ffmpeg", "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", str(concat_list_file),
                    "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                    "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart",
                    str(output_file),
                ]
            else:
                cmd = [
                    "ffmpeg", "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", str(concat_list_file),
                    "-c", "copy",
                    "-movflags", "+faststart",
                    str(output_file),
                ]

            code, stdout, stderr = await self._run_command(cmd, timeout=300)
            if code != 0:
                err_msg = stderr.decode(errors="replace").strip()
                raise RuntimeError(f"FFmpeg ghép video thất bại (code {code}): {err_msg[-200:]}")

            delivery_info = self._publish_or_direct(output_file, title="Video đã ghép")
            success = True
            return {
                "status": "ok",
                "tool": "concatenate_videos",
                "clips_count": len(resolved_files),
                "reencode": reencode,
                "output_path": str(output_file),
                **delivery_info,
                "message": f"Đã ghép nối thành công {len(resolved_files)} video clips.",
            }

        finally:
            if not success and output_file.exists():
                output_file.unlink(missing_ok=True)
            if concat_list_file.exists():
                concat_list_file.unlink(missing_ok=True)
            for fpath, is_trans in resolved_files:
                if is_trans and fpath.exists():
                    fpath.unlink(missing_ok=True)

    # ─── 6. EXTRACT FRAMES ───────────────────────────────────────────────────

    async def extract_frames(
        self,
        input_path_or_url: str,
        interval_seconds: float = 1.0,
        output_format: str = "jpg",
        quality: int = 2,
    ) -> Dict[str, Any]:
        """
        Extracts still image frames from video at a periodic interval.
        Packages frames into a ZIP archive for convenient download.
        """
        if not isinstance(interval_seconds, (int, float)) or float(interval_seconds) <= 0:
            raise ValueError("Khoảng thời gian trích xuất frame (interval_seconds) phải lớn hơn 0.")

        clean_fmt = str(output_format).strip().lower().lstrip(".")
        if clean_fmt not in {"jpg", "jpeg", "png"}:
            clean_fmt = "jpg"

        input_file, is_transient = await self._resolve_input(input_path_or_url)
        token = secrets.token_hex(6)
        frames_dir = self._temp_dir / f"frames_{token}"
        frames_dir.mkdir(parents=True, exist_ok=True)
        zip_output = self._temp_dir / f"extracted_frames_{token}.zip"
        success = False

        try:
            fps_val = f"1/{interval_seconds}"
            cmd = [
                "ffmpeg", "-y",
                "-i", str(input_file),
                "-vf", f"fps={fps_val}",
                "-qscale:v", str(int(quality)),
                str(frames_dir / f"frame_%04d.{clean_fmt}"),
            ]
            code, stdout, stderr = await self._run_command(cmd, timeout=300)
            if code != 0:
                err_msg = stderr.decode(errors="replace").strip()
                raise RuntimeError(f"FFmpeg trích xuất frames thất bại: {err_msg[-200:]}")

            frame_files = sorted(list(frames_dir.glob(f"*.{clean_fmt}")))
            if not frame_files:
                raise RuntimeError("Không tìm thấy frame nào được trích xuất từ video.")

            # Create ZIP archive of extracted frames
            with zipfile.ZipFile(zip_output, "w", zipfile.ZIP_DEFLATED) as zf:
                for ff in frame_files:
                    zf.write(ff, arcname=ff.name)

            sample_paths = [str(ff) for ff in frame_files[:5]]
            delivery_info = self._publish_or_direct(zip_output, title="Gói Frames Video")
            success = True
            return {
                "status": "ok",
                "tool": "extract_frames",
                "frames_count": len(frame_files),
                "interval_seconds": float(interval_seconds),
                "zip_path": str(zip_output),
                "sample_frames": sample_paths,
                **delivery_info,
                "message": f"Đã trích xuất thành công {len(frame_files)} frames (mỗi {interval_seconds}s).",
            }

        finally:
            if not success and zip_output.exists():
                zip_output.unlink(missing_ok=True)
            shutil.rmtree(frames_dir, ignore_errors=True)
            if is_transient and input_file.exists():
                input_file.unlink(missing_ok=True)

    # ─── 7. REMOVE WATERMARK REGION ──────────────────────────────────────────

    async def remove_watermark_region(
        self,
        input_path_or_url: str,
        regions: List[Dict[str, int]],
        output_format: str = "mp4",
    ) -> Dict[str, Any]:
        """
        Removes up to 5 watermark / logo bounding boxes simultaneously via chained FFmpeg delogo.
        """
        if not regions or not isinstance(regions, list):
            raise ValueError("Danh sách regions không được để trống.")

        if not (1 <= len(regions) <= 5):
            raise ValueError(f"Số lượng vùng xóa watermark (regions) tối đa là 5. Hiện tại: {len(regions)}.")

        for r in regions:
            self._validate_region_dict(r)

        input_file, is_transient = await self._resolve_input(input_path_or_url)
        token = secrets.token_hex(6)
        out_ext = output_format.lstrip(".").lower()
        output_file = self._temp_dir / f"delogo_multi_{token}.{out_ext}"
        success = False

        try:
            filter_chain = ",".join([
                f"delogo=x={int(r['x'])}:y={int(r['y'])}:w={int(r['w'])}:h={int(r['h'])}:show=0"
                for r in regions
            ])
            cmd = [
                "ffmpeg", "-y",
                "-i", str(input_file),
                "-vf", filter_chain,
                "-c:a", "copy",
                "-movflags", "+faststart",
                str(output_file),
            ]
            code, stdout, stderr = await self._run_command(cmd, timeout=300)
            if code != 0:
                err_msg = stderr.decode(errors="replace").strip()
                raise RuntimeError(f"FFmpeg chained delogo thất bại (code {code}): {err_msg[-200:]}")

            delivery_info = self._publish_or_direct(output_file, title="Video đã xóa watermark")
            success = True
            return {
                "status": "ok",
                "tool": "remove_watermark_region",
                "regions_count": len(regions),
                "regions": regions,
                "output_path": str(output_file),
                **delivery_info,
                "message": f"Đã xóa thành công {len(regions)} vùng watermark trên video.",
            }

        finally:
            if not success and output_file.exists():
                output_file.unlink(missing_ok=True)
            if is_transient and input_file.exists():
                input_file.unlink(missing_ok=True)

    # ─── 8. ENHANCE VIDEO QUALITY ────────────────────────────────────────────

    async def enhance_video_quality(
        self,
        input_path_or_url: str,
        preset: str = "sharpen",
        output_format: str = "mp4",
    ) -> Dict[str, Any]:
        """
        Enhances video visual fidelity using post-processing filters:
        - sharpen: unsharp masking
        - denoise: high-quality 3D spatio-temporal denoising (hqdn3d)
        - deinterlace: YADIF deinterlacing
        - upscale_2x: Lanczos 2x super-resolution scaling
        - hdr_tonemap: contrast/vividness enhancement
        """
        preset_filters = {
            "sharpen": "unsharp=5:5:1.0:5:5:0.0",
            "denoise": "hqdn3d=4.0:3.0:6.0:4.5",
            "deinterlace": "yadif=0:-1:0",
            "upscale_2x": "scale=iw*2:ih*2:flags=lanczos",
            "hdr_tonemap": "eq=contrast=1.15:brightness=0.03:saturation=1.2,unsharp=3:3:0.5",
        }

        clean_preset = str(preset).strip().lower()
        if clean_preset not in preset_filters:
            raise ValueError(
                f"Preset tăng cường '{preset}' không hợp lệ. Chỉ hỗ trợ: {', '.join(sorted(preset_filters.keys()))}."
            )

        input_file, is_transient = await self._resolve_input(input_path_or_url)
        token = secrets.token_hex(6)
        out_ext = output_format.lstrip(".").lower()
        output_file = self._temp_dir / f"enhanced_{token}.{out_ext}"
        success = False

        try:
            vf_filter = preset_filters[clean_preset]
            cmd = [
                "ffmpeg", "-y",
                "-i", str(input_file),
                "-vf", vf_filter,
                "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                "-c:a", "copy",
                "-movflags", "+faststart",
                str(output_file),
            ]
            code, stdout, stderr = await self._run_command(cmd, timeout=300)
            if code != 0:
                err_msg = stderr.decode(errors="replace").strip()
                raise RuntimeError(f"FFmpeg nâng cấp chất lượng thất bại (code {code}): {err_msg[-200:]}")

            delivery_info = self._publish_or_direct(output_file, title=f"Video Enhanced ({clean_preset})")
            success = True
            return {
                "status": "ok",
                "tool": "enhance_video_quality",
                "preset": clean_preset,
                "filter_applied": vf_filter,
                "output_path": str(output_file),
                **delivery_info,
                "message": f"Đã nâng cao chất lượng video thành công theo bộ lọc '{clean_preset}'.",
            }

        finally:
            if not success and output_file.exists():
                output_file.unlink(missing_ok=True)
            if is_transient and input_file.exists():
                input_file.unlink(missing_ok=True)

    # ─── 9. GENERATE VIDEO THUMBNAIL ─────────────────────────────────────────

    async def generate_video_thumbnail(
        self,
        input_path_or_url: str,
        timestamp: float = 0.0,
        width: int = 320,
        height: int = 240,
        output_format: str = "jpg",
    ) -> Dict[str, Any]:
        """
        Generates a crisp thumbnail image at the specified timestamp.
        """
        if not isinstance(timestamp, (int, float)) or float(timestamp) < 0:
            raise ValueError(f"Mốc thời gian timestamp ({timestamp}) không được âm.")

        if not isinstance(width, int) or width <= 0 or width > 7680:
            raise ValueError("Chiều rộng width phải là số nguyên dương (1 - 7680).")

        if not isinstance(height, int) or height <= 0 or height > 4320:
            raise ValueError("Chiều cao height phải là số nguyên dương (1 - 4320).")

        clean_fmt = str(output_format).strip().lower().lstrip(".")
        if clean_fmt not in {"jpg", "jpeg", "png"}:
            clean_fmt = "jpg"

        input_file, is_transient = await self._resolve_input(input_path_or_url)
        token = secrets.token_hex(6)
        output_file = self._temp_dir / f"thumb_{token}.{clean_fmt}"
        success = False

        try:
            vf_scale = f"scale={width}:{height}:force_original_aspect_ratio=decrease"
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(float(timestamp)),
                "-i", str(input_file),
                "-vframes", "1",
                "-vf", vf_scale,
                str(output_file),
            ]
            code, stdout, stderr = await self._run_command(cmd, timeout=60)
            if code != 0:
                err_msg = stderr.decode(errors="replace").strip()
                raise RuntimeError(f"FFmpeg tạo thumbnail thất bại (code {code}): {err_msg[-200:]}")

            delivery_info = self._publish_or_direct(output_file, title="Video Thumbnail")
            success = True
            return {
                "status": "ok",
                "tool": "generate_video_thumbnail",
                "timestamp": float(timestamp),
                "width": width,
                "height": height,
                "output_path": str(output_file),
                **delivery_info,
                "message": f"Đã trích xuất thumbnail thành công tại mốc {timestamp}s ({width}x{height} px).",
            }

        finally:
            if not success and output_file.exists():
                output_file.unlink(missing_ok=True)
            if is_transient and input_file.exists():
                input_file.unlink(missing_ok=True)
