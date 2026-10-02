"""
Video Editor Service for AI Agent Tieu Bao Bao (Milestone 2).
Provides 9 studio-grade video processing tools with hardware safety (concurrency bounding),
non-blocking subprocess execution, secure path traversal validation, Dual-Delivery,
and Zero-Disk Leak guarantees.
"""

import asyncio
import difflib
import logging
import os
import posixpath
import re
import secrets
import shutil
import subprocess
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
        region: Optional[Union[Dict[str, int], List[Dict[str, int]]]] = None,
        mode: str = "delogo",
        output_format: str = "mp4",
    ) -> Dict[str, Any]:
        """
        Removes text, watermark, or static overlays from video.
        Modes supported:
          - 'delogo': Native fast FFmpeg delogo filter.
          - 'inpaint': High-quality OpenCV Telea inpainting.
          - 'auto': Automatic detection of persistent overlay text via OCR sampling across keyframes,
                    distinguishing fixed overlays from scene text, then applying OpenCV inpainting (or delogo fallback).
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
                try:
                    import cv2  # noqa: F401
                    candidate_mode = "inpaint"
                except (ImportError, ModuleNotFoundError):
                    candidate_mode = "delogo"

                if region is None:
                    detected_regions = await self._auto_detect_text_region(input_file)
                elif isinstance(region, list):
                    detected_regions = region
                else:
                    detected_regions = [region]

                mode_used = candidate_mode
                target_regions = detected_regions
            else:
                if region is None:
                    target_regions = [{"x": 50, "y": 145, "w": 475, "h": 125}]
                elif isinstance(region, list):
                    target_regions = region
                else:
                    target_regions = [region]

            # R3: If no text/watermark regions need to be removed, preserve original video intact
            if not target_regions:
                shutil.copy2(input_file, output_file)
                delivery_info = self._publish_or_direct(output_file, title="Video gốc (không có vùng text overlay)")
                success = True
                return {
                    "status": "ok",
                    "tool": "remove_text_from_video",
                    "mode_requested": clean_mode,
                    "mode_used": mode_used,
                    "region": {},
                    "regions": [],
                    "output_path": str(output_file),
                    **delivery_info,
                    "message": "Không phát hiện text hoặc watermark cố định (overlay) nào cần xóa trong video. Đã giữ nguyên video gốc.",
                }

            # Validate all target region coordinates
            for reg in target_regions:
                self._validate_region_dict(reg)

            primary_region = target_regions[0] if target_regions else {"x": 0, "y": 0, "w": 0, "h": 0}
            rx = int(primary_region["x"])
            ry = int(primary_region["y"])
            rw = int(primary_region["w"])
            rh = int(primary_region["h"])

            if mode_used == "delogo":
                probe_cmd = [
                    "ffprobe", "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=width,height",
                    "-of", "csv=s=x:p=0",
                    str(input_file),
                ]
                p_code, p_out, _ = await self._run_command(probe_cmd, timeout=10)
                vid_w, vid_h = 0, 0
                if p_code == 0:
                    try:
                        wh_parts = p_out.decode(errors="ignore").strip().split("x")
                        if len(wh_parts) == 2:
                            vid_w, vid_h = int(wh_parts[0]), int(wh_parts[1])
                    except Exception:
                        vid_w, vid_h = 0, 0

                delogo_filters = []
                for reg in target_regions:
                    if vid_w > 0 and vid_h > 0:
                        x1 = max(1, int(reg["x"]))
                        y1 = max(1, int(reg["y"]))
                        x2 = min(vid_w - 1, int(reg["x"]) + int(reg["w"]))
                        y2 = min(vid_h - 1, int(reg["y"]) + int(reg["h"]))
                        if x2 > x1 and y2 > y1:
                            delogo_filters.append(f"delogo=x={x1}:y={y1}:w={x2 - x1}:h={y2 - y1}:show=0")
                    else:
                        drx = max(1, int(reg["x"]))
                        dry = max(1, int(reg["y"]))
                        drw = max(1, int(reg["w"]))
                        drh = max(1, int(reg["h"]))
                        delogo_filters.append(f"delogo=x={drx}:y={dry}:w={drw}:h={drh}:show=0")

                if not delogo_filters:
                    shutil.copy2(input_file, output_file)
                    delivery_info = self._publish_or_direct(output_file, title="Video gốc (vùng chỉ định nằm ngoài khung hình)")
                    success = True
                    return {
                        "status": "ok",
                        "tool": "remove_text_from_video",
                        "mode_requested": clean_mode,
                        "mode_used": mode_used,
                        "region": {},
                        "regions": [],
                        "output_path": str(output_file),
                        **delivery_info,
                        "message": "Các vùng chỉ định nằm hoàn toàn bên ngoài khung hình video. Đã giữ nguyên video gốc.",
                    }

                delogo_vf = ",".join(delogo_filters)

                cmd = [
                    "ffmpeg", "-y",
                    "-i", str(input_file),
                    "-vf", delogo_vf,
                    "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "copy",
                    "-map", "0:v:0",
                    "-map", "0:a?",
                    "-map_metadata", "0",
                    "-movflags", "+faststart",
                    str(output_file),
                ]
                code, stdout, stderr = await self._run_command(cmd, timeout=300)
                if code != 0:
                    err_msg = stderr.decode(errors="replace").strip()
                    raise RuntimeError(f"FFmpeg delogo thất bại (code {code}): {err_msg[-200:]}")

            elif mode_used == "inpaint":
                try:
                    import cv2  # noqa: F401
                except (ImportError, ModuleNotFoundError):
                    raise RuntimeError("opencv-python-headless chưa được cài đặt. Vui lòng dùng mode='delogo'.")

                async with self._inpaint_semaphore:
                    if len(target_regions) == 1 and "frame_start" not in target_regions[0]:
                        await asyncio.to_thread(
                            self._inpaint_video_sync,
                            input_file,
                            output_file,
                            rx, ry, rw, rh,
                        )
                    else:
                        await asyncio.to_thread(
                            self._inpaint_video_sync,
                            input_file,
                            output_file,
                            target_regions,
                        )

            delivery_info = self._publish_or_direct(output_file, title="Video đã xóa text")
            region_summaries = ", ".join(f"({r['x']},{r['y']},{r['w']}x{r['h']})" for r in target_regions[:3])
            success = True
            return {
                "status": "ok",
                "tool": "remove_text_from_video",
                "mode_requested": clean_mode,
                "mode_used": mode_used,
                "region": primary_region,
                "regions": target_regions,
                "output_path": str(output_file),
                **delivery_info,
                "message": f"Đã xóa text/watermark thành công bằng mode '{mode_used}' tại {len(target_regions)} vùng ({region_summaries}).",
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

    @staticmethod
    def _compute_iou(b1: Tuple[int, int, int, int], b2: Tuple[int, int, int, int]) -> float:
        """Computes Intersection-over-Union (IoU) between two bounding boxes (x, y, w, h)."""
        x1 = max(b1[0], b2[0])
        y1 = max(b1[1], b2[1])
        x2 = min(b1[0] + b1[2], b2[0] + b2[2])
        y2 = min(b1[1] + b1[3], b2[1] + b2[3])
        inter_w = max(0, x2 - x1)
        inter_h = max(0, y2 - y1)
        inter_area = inter_w * inter_h
        if inter_area <= 0:
            return 0.0
        union_area = (b1[2] * b1[3]) + (b2[2] * b2[3]) - inter_area
        if union_area <= 0:
            return 0.0
        return float(inter_area) / float(union_area)

    @staticmethod
    def _merge_adjacent_words(boxes: List[Tuple[int, int, int, int]], frame_w: int, frame_h: int) -> List[Tuple[int, int, int, int]]:
        """Merges horizontally adjacent word boxes on the same line into coherent text clusters."""
        if not boxes:
            return []
        merged = list(boxes)
        changed = True
        while changed:
            changed = False
            new_merged = []
            skip_indices = set()
            for i in range(len(merged)):
                if i in skip_indices:
                    continue
                combined = merged[i]
                for j in range(i + 1, len(merged)):
                    if j in skip_indices:
                        continue
                    b2 = merged[j]
                    overlap_y = max(0, min(combined[1] + combined[3], b2[1] + b2[3]) - max(combined[1], b2[1]))
                    min_h = min(combined[3], b2[3])
                    if min_h > 0 and (overlap_y / min_h) >= 0.5:
                        gap_x = max(0, max(combined[0], b2[0]) - min(combined[0] + combined[2], b2[0] + b2[2]))
                        max_allowed_gap = max(25, int(min_h * 1.5))
                        if gap_x <= max_allowed_gap:
                            nx = min(combined[0], b2[0])
                            ny = min(combined[1], b2[1])
                            nw = max(combined[0] + combined[2], b2[0] + b2[2]) - nx
                            nh = max(combined[1] + combined[3], b2[1] + b2[3]) - ny
                            combined = (nx, ny, nw, nh)
                            skip_indices.add(j)
                            changed = True
                new_merged.append(combined)
            merged = new_merged
        return merged

    @staticmethod
    def _merge_overlapping_boxes(boxes: List[Tuple[int, int, int, int]]) -> List[Tuple[int, int, int, int]]:
        """Merges any overlapping bounding boxes into a single enclosing box."""
        if not boxes:
            return []
        merged = list(boxes)
        changed = True
        while changed:
            changed = False
            new_merged = []
            skip_indices = set()
            for i in range(len(merged)):
                if i in skip_indices:
                    continue
                combined = merged[i]
                for j in range(i + 1, len(merged)):
                    if j in skip_indices:
                        continue
                    b2 = merged[j]
                    x1 = max(combined[0], b2[0])
                    y1 = max(combined[1], b2[1])
                    x2 = min(combined[0] + combined[2], b2[0] + b2[2])
                    y2 = min(combined[1] + combined[3], b2[1] + b2[3])
                    if x2 > x1 and y2 > y1:
                        nx = min(combined[0], b2[0])
                        ny = min(combined[1], b2[1])
                        nw = max(combined[0] + combined[2], b2[0] + b2[2]) - nx
                        nh = max(combined[1] + combined[3], b2[1] + b2[3]) - ny
                        combined = (nx, ny, nw, nh)
                        skip_indices.add(j)
                        changed = True
                new_merged.append(combined)
            merged = new_merged
        return merged

    @staticmethod
    def _compute_text_similarity(s1: str, s2: str) -> float:
        """Computes string similarity between two OCR texts to cluster changing captions."""
        if not s1 or not s2:
            return 0.0
        return float(difflib.SequenceMatcher(None, s1.lower().strip(), s2.lower().strip()).ratio())

    @staticmethod
    def _merge_overlapping_temporal_segments(
        segments: List[Dict[str, Any]],
        frame_w: int,
        frame_h: int,
        frame_area: int,
    ) -> List[Dict[str, Any]]:
        """
        Merges text segments that overlap in BOTH spatial bounding box and temporal duration.
        Ensures disjoint inpainting masks per frame.
        """
        if not segments:
            return []
        merged = [dict(s) for s in segments]
        changed = True
        while changed:
            changed = False
            new_merged = []
            skip_indices = set()
            for i in range(len(merged)):
                if i in skip_indices:
                    continue
                combined = dict(merged[i])
                for j in range(i + 1, len(merged)):
                    if j in skip_indices:
                        continue
                    s2 = merged[j]
                    # Check temporal overlap
                    has_time_overlap = max(combined.get("frame_start", 0), s2.get("frame_start", 0)) <= min(combined.get("frame_end", 999999999), s2.get("frame_end", 999999999))
                    if has_time_overlap:
                        # Check spatial overlap
                        x1 = max(combined["x"], s2["x"])
                        y1 = max(combined["y"], s2["y"])
                        x2 = min(combined["x"] + combined["w"], s2["x"] + s2["w"])
                        y2 = min(combined["y"] + combined["h"], s2["y"] + s2["h"])
                        if x2 > x1 and y2 > y1:
                            nx = min(combined["x"], s2["x"])
                            ny = min(combined["y"], s2["y"])
                            nw = max(combined["x"] + combined["w"], s2["x"] + s2["w"]) - nx
                            nh = max(combined["y"] + combined["h"], s2["y"] + s2["h"]) - ny
                            if frame_area <= 0 or (nw * nh) <= 0.30 * frame_area:
                                combined["x"] = nx
                                combined["y"] = ny
                                combined["w"] = nw
                                combined["h"] = nh
                                combined["frame_start"] = min(combined.get("frame_start", 0), s2.get("frame_start", 0))
                                combined["frame_end"] = max(combined.get("frame_end", 999999999), s2.get("frame_end", 999999999))
                                skip_indices.add(j)
                                changed = True
                new_merged.append(combined)
            merged = new_merged
        return merged

    async def _auto_detect_text_region(self, input_file: Path) -> List[Dict[str, Any]]:
        """
        R1. Dense Temporal Scan text detection:
          - Samples 1 frame every 2 seconds across video (max 60 frames for >=120s video).
          - Detects text in each sampled frame using pytesseract OCR.
          - Clusters text regions into temporal text segments (similar text at proximate coordinates = same caption),
            each with a temporal extent [frame_start, frame_end].
          - Sanity check: bounding boxes exceeding 30% of frame area are discarded as false positives.
        Returns a list of text segments with coordinates and temporal extents, or empty list if no text is detected.
        """
        token = secrets.token_hex(4)
        sample_dir = self._temp_dir / f"samples_{token}"
        sample_dir.mkdir(parents=True, exist_ok=True)

        try:
            duration = 0.0
            fps = 30.0

            # Probe duration
            probe_cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(input_file),
            ]
            try:
                p_code, p_stdout, _ = await self._run_command(probe_cmd, timeout=10)
                if p_code == 0:
                    try:
                        duration = float(p_stdout.decode(errors="ignore").strip())
                    except Exception:
                        duration = 0.0
            except Exception as p_exc:
                logger.debug("[VideoEditorService] Probe duration failed: %s", p_exc)
                duration = 0.0

            # Probe FPS
            probe_fps_cmd = [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=r_frame_rate",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(input_file),
            ]
            try:
                p_code, p_stdout, _ = await self._run_command(probe_fps_cmd, timeout=10)
                if p_code == 0:
                    try:
                        fps_str = p_stdout.decode(errors="ignore").strip()
                        if "/" in fps_str:
                            num, den = fps_str.split("/", 1)
                            fps = float(num) / max(1.0, float(den))
                        elif fps_str:
                            fps = float(fps_str)
                    except Exception:
                        fps = 30.0
            except Exception:
                fps = 30.0

            if not fps or fps <= 0:
                fps = 30.0

            # Dense Temporal Scan: 1 frame every 2s, capped at 60 frames max
            if duration > 60.0:
                step_sec = duration / 60.0
            elif duration >= 2.0:
                step_sec = 2.0
            else:
                step_sec = 1.0

            if duration >= 1.0:
                vf_expr = f"fps=1/{step_sec:.4f}"
            else:
                vf_expr = "select=eq(n\\,0)"

            # Extract sample frames across the video
            cmd = [
                "ffmpeg", "-y",
                "-i", str(input_file),
                "-vf", vf_expr,
                "-vframes", "60",
                "-vsync", "0",
                str(sample_dir / "sample_%04d.jpg"),
            ]
            try:
                code, _, _ = await self._run_command(cmd, timeout=30)
                if code != 0:
                    return []
            except Exception as exc:
                logger.warning("[VideoEditorService] Lấy sample frames thất bại hoặc timeout: %s", exc)
                return []

            try:
                import pytesseract
                from PIL import Image
            except (ImportError, ModuleNotFoundError):
                return []

            frames = sorted(list(sample_dir.glob("sample_*.jpg")))
            if not frames or len(frames) < 2:
                return []

            frame_w, frame_h = 0, 0
            raw_frame_detections: List[Tuple[int, float, int, int, List[Tuple[int, int, int, int, str]]]] = []

            for idx, frame_path in enumerate(frames):
                t_sec = idx * step_sec
                f_start = max(0, int(round((t_sec - step_sec / 2.0) * fps)))
                f_end = int(round((t_sec + step_sec / 2.0) * fps))
                if duration > 0 and f_end > int(round(duration * fps)):
                    f_end = int(round(duration * fps))

                boxes_in_frame: List[Tuple[int, int, int, int, str]] = []
                try:
                    with Image.open(frame_path) as img:
                        if hasattr(img, "width") and isinstance(img.width, int):
                            frame_w = max(frame_w, img.width)
                            frame_h = max(frame_h, img.height)
                        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
                        n_boxes = len(data.get("text", []))
                        for i in range(n_boxes):
                            try:
                                conf = float(data["conf"][i])
                            except (ValueError, TypeError):
                                conf = -1.0
                            text = str(data["text"][i]).strip()
                            if conf > 30.0 and len(text) > 0:
                                x = int(data["left"][i])
                                y = int(data["top"][i])
                                w = int(data["width"][i])
                                h = int(data["height"][i])
                                if w > 0 and h > 0:
                                    boxes_in_frame.append((x, y, w, h, text))
                except Exception:
                    pass
                raw_frame_detections.append((idx, t_sec, f_start, f_end, boxes_in_frame))

            frame_area = frame_w * frame_h

            # 1. Per-frame merge and sanity check (box <= 30% frame area)
            processed_frame_detections = []
            for idx, t_sec, f_start, f_end, raw_boxes in raw_frame_detections:
                valid_raw = [b for b in raw_boxes if not (frame_area > 0 and (b[2] * b[3]) > 0.30 * frame_area)]
                coord_boxes = [(b[0], b[1], b[2], b[3]) for b in valid_raw]
                merged_coords = self._merge_adjacent_words(coord_boxes, frame_w, frame_h)
                valid_merged_coords = [b for b in merged_coords if not (frame_area > 0 and (b[2] * b[3]) > 0.30 * frame_area)]

                merged_with_text: List[Tuple[int, int, int, int, str]] = []
                for mb in valid_merged_coords:
                    mb_x, mb_y, mb_w, mb_h = mb
                    words = [
                        b[4] for b in valid_raw
                        if self._compute_iou((mb_x, mb_y, mb_w, mb_h), (b[0], b[1], b[2], b[3])) > 0 or (
                            b[0] >= mb_x - 5 and b[0] + b[2] <= mb_x + mb_w + 5 and b[1] >= mb_y - 5 and b[1] + b[3] <= mb_y + mb_h + 5
                        )
                    ]
                    merged_with_text.append((mb_x, mb_y, mb_w, mb_h, " ".join(words).strip()))
                processed_frame_detections.append((idx, t_sec, f_start, f_end, merged_with_text))

            # 2. Temporal clustering into segments (similar text at proximate coordinates = same caption)
            segments: List[Dict[str, Any]] = []
            for sample_idx, t_sec, f_start, f_end, boxes in processed_frame_detections:
                for bx, by, bw, bh, btext in boxes:
                    matched_segment = None
                    best_score = 0.0

                    for seg in segments:
                        if sample_idx - seg["last_sample_idx"] <= 2:
                            iou = self._compute_iou((bx, by, bw, bh), (seg["x"], seg["y"], seg["w"], seg["h"]))
                            overlap_y = max(0, min(by + bh, seg["y"] + seg["h"]) - max(by, seg["y"]))
                            min_h = min(bh, seg["h"])
                            vert_overlap = (overlap_y / min_h) if min_h > 0 else 0.0
                            text_sim = self._compute_text_similarity(btext, seg.get("text", ""))

                            # Segment match condition: spatial proximity or significant vertical line overlap
                            if iou >= 0.2 or vert_overlap >= 0.6:
                                score = iou + vert_overlap + text_sim
                                if score > best_score:
                                    best_score = score
                                    matched_segment = seg

                    if matched_segment is not None:
                        nx1 = min(matched_segment["x"], bx)
                        ny1 = min(matched_segment["y"], by)
                        nx2 = max(matched_segment["x"] + matched_segment["w"], bx + bw)
                        ny2 = max(matched_segment["y"] + matched_segment["h"], by + bh)
                        matched_segment["x"] = nx1
                        matched_segment["y"] = ny1
                        matched_segment["w"] = nx2 - nx1
                        matched_segment["h"] = ny2 - ny1
                        matched_segment["frame_end"] = max(matched_segment["frame_end"], f_end)
                        matched_segment["last_sample_idx"] = sample_idx
                        matched_segment["hits"] = matched_segment.get("hits", 1) + 1
                        if btext:
                            matched_segment["text"] = f"{matched_segment['text']} {btext}".strip()
                    else:
                        segments.append({
                            "x": bx,
                            "y": by,
                            "w": bw,
                            "h": bh,
                            "frame_start": f_start,
                            "frame_end": f_end,
                            "last_sample_idx": sample_idx,
                            "text": btext,
                            "hits": 1,
                        })

            # Filter persistent overlay text / captions (hits >= 2 across sampled frames)
            persistent_segments = [s for s in segments if s.get("hits", 1) >= 2]

            # 3. Add padding & clamp within frame boundaries, checking area ceiling
            pad = 10
            padded_segments: List[Dict[str, Any]] = []
            for seg in persistent_segments:
                x1 = max(0, seg["x"] - pad)
                y1 = max(0, seg["y"] - pad)
                x2 = min(frame_w, seg["x"] + seg["w"] + pad) if frame_w > 0 else (seg["x"] + seg["w"] + pad)
                y2 = min(frame_h, seg["y"] + seg["h"] + pad) if frame_h > 0 else (seg["y"] + seg["h"] + pad)
                fw = max(1, x2 - x1)
                fh = max(1, y2 - y1)

                if frame_area > 0 and (fw * fh) > 0.30 * frame_area:
                    continue
                padded_segments.append({
                    "x": x1,
                    "y": y1,
                    "w": fw,
                    "h": fh,
                    "frame_start": seg["frame_start"],
                    "frame_end": seg["frame_end"],
                })

            # 4. Merge overlapping segments in space and time
            final_segments = self._merge_overlapping_temporal_segments(
                padded_segments, frame_w, frame_h, frame_area
            )

            results: List[Dict[str, Any]] = []
            for s in final_segments:
                if frame_area > 0 and (s["w"] * s["h"]) > 0.30 * frame_area:
                    continue
                results.append({
                    "x": s["x"],
                    "y": s["y"],
                    "w": s["w"],
                    "h": s["h"],
                    "frame_start": s.get("frame_start", 0),
                    "frame_end": s.get("frame_end", 0),
                })

            return results

        finally:
            shutil.rmtree(sample_dir, ignore_errors=True)

    def _inpaint_video_sync(
        self,
        input_file: Path,
        output_file: Path,
        rx_or_regions: Union[int, List[Dict[str, Any]]],
        ry: Optional[int] = None,
        rw: Optional[int] = None,
        rh: Optional[int] = None,
    ) -> None:
        """
        Synchronous worker for OpenCV Telea video frame inpainting with temporal extent support (R2).
        Only inpaints frames during the active temporal extent of each detected segment.
        Re-assembles the video with original audio via FFmpeg stream copy.
        """
        import math
        import cv2
        import numpy as np

        cap = cv2.VideoCapture(str(input_file))
        if not cap.isOpened():
            raise RuntimeError(f"Không thể mở video qua OpenCV: {input_file}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        if not fps or fps <= 0 or math.isnan(fps):
            fps = 30.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if width <= 0 or height <= 0:
            cap.release()
            raise RuntimeError(f"Kích thước video không hợp lệ ({width}x{height}) khi mở bằng OpenCV: {input_file}")

        # Parse regions list
        regions_list: List[Dict[str, Any]] = []
        if isinstance(rx_or_regions, list):
            regions_list = rx_or_regions
        elif isinstance(rx_or_regions, (int, float)) and ry is not None and rw is not None and rh is not None:
            regions_list = [{"x": int(rx_or_regions), "y": int(ry), "w": int(rw), "h": int(rh)}]
        else:
            cap.release()
            raise ValueError("Tham số tọa độ không hợp lệ cho inpaint.")

        # Check if all regions lie completely outside the frame
        all_outside = True
        for reg in regions_list:
            x1 = max(0, int(reg["x"]))
            y1 = max(0, int(reg["y"]))
            x2 = min(width, int(reg["x"]) + int(reg["w"]))
            y2 = min(height, int(reg["y"]) + int(reg["h"]))
            if x2 > x1 and y2 > y1:
                all_outside = False
                break

        if all_outside or not regions_list:
            cap.release()
            shutil.copy2(input_file, output_file)
            return

        token = secrets.token_hex(4)
        raw_video_path = self._temp_dir / f"inp_raw_{token}.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out = cv2.VideoWriter(str(raw_video_path), fourcc, fps, (width, height))
        if not out.isOpened():
            cap.release()
            raw_video_path.unlink(missing_ok=True)
            raise RuntimeError(f"Không thể khởi tạo OpenCV VideoWriter để ghi video tại {raw_video_path.name}")

        try:
            frames_written = 0
            frame_idx = 0
            try:
                while cap.isOpened():
                    ret, frame = cap.read()
                    if not ret:
                        break

                    # R2: Frame-by-frame inpainting within segment temporal extents
                    active_regions = [
                        r for r in regions_list
                        if r.get("frame_start", 0) <= frame_idx <= r.get("frame_end", 999999999)
                    ]

                    if active_regions:
                        mask = np.zeros((height, width), dtype=np.uint8)
                        for reg in active_regions:
                            x1 = max(0, int(reg["x"]))
                            y1 = max(0, int(reg["y"]))
                            x2 = min(width, int(reg["x"]) + int(reg["w"]))
                            y2 = min(height, int(reg["y"]) + int(reg["h"]))
                            if x2 > x1 and y2 > y1:
                                mask[y1:y2, x1:x2] = 255
                        if np.count_nonzero(mask) > 0:
                            inpainted = cv2.inpaint(frame, mask, 3, cv2.INPAINT_TELEA)
                            out.write(inpainted)
                        else:
                            out.write(frame)
                    else:
                        out.write(frame)

                    frames_written += 1
                    frame_idx += 1
            finally:
                cap.release()
                out.release()

            if frames_written == 0:
                raise RuntimeError(f"Không thể đọc bất kỳ frame nào từ video đầu vào: {input_file}")

            # Probe SAR to prevent aspect ratio distortion on anamorphic video
            sar_filter: Optional[str] = None
            try:
                probe_sar_cmd = [
                    "ffprobe", "-v", "error", "-select_streams", "v:0",
                    "-show_entries", "stream=sample_aspect_ratio",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(input_file),
                ]
                p_sar = subprocess.run(probe_sar_cmd, capture_output=True, text=True, timeout=10)
                sar_val = p_sar.stdout.strip().splitlines()[0].strip() if p_sar.stdout.strip() else ""
                if sar_val and sar_val not in ("1:1", "0:1", "N/A"):
                    clean_sar = sar_val.replace(":", "/")
                    if re.match(r"^\d+/\d+$", clean_sar):
                        sar_filter = f"setsar=sar={clean_sar}"
            except Exception as sar_exc:
                logger.debug("[VideoEditorService] Could not probe SAR: %s", sar_exc)

            # Combine video stream with all original audio streams using FFmpeg
            merge_cmd = [
                "ffmpeg", "-y",
                "-i", str(raw_video_path),
                "-i", str(input_file),
            ]
            if sar_filter:
                merge_cmd.extend(["-vf", sar_filter])
            merge_cmd.extend([
                "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                "-pix_fmt", "yuv420p",
                "-c:a", "copy",
                "-map", "0:v:0",
                "-map", "1:a?",
                "-map_metadata", "1",
                "-shortest",
                "-movflags", "+faststart",
                str(output_file),
            ])
            try:
                proc = subprocess.run(merge_cmd, capture_output=True, timeout=300)
                if proc.returncode != 0:
                    err = proc.stderr.decode(errors="replace")
                    raise RuntimeError(f"FFmpeg ghép âm thanh sau khi inpaint thất bại: {err[-200:]}")
            except subprocess.TimeoutExpired:
                raise RuntimeError("FFmpeg ghép âm thanh sau khi inpaint bị timeout quá 300 giây.")
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
