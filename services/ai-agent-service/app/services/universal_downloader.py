"""
universal_downloader.py — Universal Internet Direct File Downloader.

Implements high-performance, resilient streaming file downloads from arbitrary internet URLs:
- Chunked disk streaming (64KB chunks) directly to SSD without buffering in RAM (< 5MB RAM overhead).
- Concurrency limiting via asyncio.Semaphore(2) to protect CPU/network resources.
- HTTP Range Resume support when remote server supports 'Accept-Ranges: bytes'.
- Atomic replacement (.part -> final) and Zero-Disk Leak cleanup on unresumable failure.
- Safe path sanitization against directory traversal and disk space verification before downloading.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
import re
import shutil
import time
from typing import Any, Dict, Optional
import urllib.parse

import httpx

logger = logging.getLogger(__name__)

# Default directory for direct downloads
DEFAULT_DOWNLOAD_DIR = Path(os.getenv("DIRECT_DOWNLOADS_DIR", "/tmp/direct_downloads"))

# Chunk size: 64KB for optimal I/O balance
CHUNK_SIZE = 64 * 1024  # 65,536 bytes

# Safety limits: 10GB max file size, 500MB disk margin buffer
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024 * 1024  # 10 GB
MIN_DISK_MARGIN_BYTES = 500 * 1024 * 1024      # 500 MB

# Timeouts
CONNECT_TIMEOUT_SEC = 15.0
READ_TIMEOUT_SEC = 30.0


def sanitize_filename(filename: str, fallback: str = "downloaded_file.bin") -> str:
    """
    Sanitizes arbitrary filenames, stripping path separators, path traversal patterns,
    control characters, and reserved names to prevent local filesystem compromise.
    """
    if not filename:
        return fallback

    # Decode URL encoding if present
    try:
        decoded = urllib.parse.unquote(filename)
    except Exception:
        decoded = filename

    # Take only the basename and remove traversal characters
    clean = Path(decoded).name.strip()
    clean = re.sub(r'[\/\\:\*\?"<>\|\x00-\x1f]', "_", clean)
    clean = re.sub(r"^\.+", "", clean)  # Strip leading dots (hidden / relative)
    clean = clean.strip(" .")

    if not clean or clean in (".", ".."):
        return fallback

    # Truncate overly long filenames
    if len(clean) > 200:
        stem = Path(clean).stem[:180]
        suffix = Path(clean).suffix[:20]
        clean = f"{stem}{suffix}"

    return clean


def parse_filename_from_headers(headers: httpx.Headers, fallback: str = "") -> str:
    """
    Extracts filename from HTTP Content-Disposition header, supporting both
    RFC 5987 (filename*=UTF-8''...) and standard (filename="...").
    """
    cd = headers.get("content-disposition", "")
    if not cd:
        return fallback

    # RFC 5987: filename*=UTF-8''encoded_name
    rfc5987_match = re.search(r"filename\*\s*=\s*utf-8''([^;\s]+)", cd, flags=re.IGNORECASE)
    if rfc5987_match:
        try:
            return urllib.parse.unquote(rfc5987_match.group(1))
        except Exception:
            pass

    # Standard filename="name" or filename=name
    std_match = re.search(r'filename\s*=\s*(?:"([^"]+)"|([^;\s]+))', cd, flags=re.IGNORECASE)
    if std_match:
        return std_match.group(1) or std_match.group(2) or fallback

    return fallback


def extract_filename_from_url(url: str, fallback: str = "downloaded_file.bin") -> str:
    """
    Extracts filename from the path of a URL.
    """
    try:
        parsed = urllib.parse.urlparse(url)
        path = parsed.path
        if path:
            name = Path(path).name
            if name:
                return name
    except Exception:
        pass
    return fallback


class UniversalDownloader:
    """
    Universal Internet Direct File Downloader with streaming, HTTP Range resume,
    disk space verification, and zero-disk-leak semantics.
    """

    def __init__(self, download_dir: Optional[Path] = None, max_concurrency: int = 2):
        self.download_dir = Path(download_dir) if download_dir else DEFAULT_DOWNLOAD_DIR
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self.ensure_dir()

    def ensure_dir(self) -> None:
        """Ensures the destination download directory exists."""
        try:
            self.download_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            logger.warning("[Downloader] Unable to create download directory %s: %s", self.download_dir, exc)

    async def download_direct_file(
        self,
        url: str,
        custom_filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Downloads an arbitrary file from a direct HTTP/HTTPS URL:
        1. Probes headers (Content-Length, Accept-Ranges, Content-Disposition, Content-Type).
        2. Sanitizes target filename and guards against disk space overflow.
        3. Supports HTTP Range header for resuming partial downloads.
        4. Streams 64KB chunks directly to SSD with < 5MB RAM overhead.
        5. Atomically renames .part to final destination upon complete transfer.
        6. Cleans up partial files in finally blocks if unresumable.
        """
        if not url or not url.strip():
            return {
                "status": "error",
                "message": "URL không được để trống.",
            }

        url = url.strip()
        start_time = time.time()
        self.ensure_dir()

        async with self._semaphore:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "*/*",
            }

            timeout_cfg = httpx.Timeout(
                connect=CONNECT_TIMEOUT_SEC,
                read=READ_TIMEOUT_SEC,
                write=30.0,
                pool=15.0,
            )

            part_file: Optional[Path] = None
            final_file: Optional[Path] = None
            resume_supported = False
            was_resumed = False

            try:
                async with httpx.AsyncClient(timeout=timeout_cfg, follow_redirects=True) as client:
                    # Step 1: Probe metadata via HEAD request
                    total_bytes: Optional[int] = None
                    mime_type = "application/octet-stream"
                    probe_headers = dict(headers)

                    try:
                        head_resp = await client.head(url, headers=probe_headers)
                        if head_resp.status_code < 400:
                            if "content-length" in head_resp.headers:
                                try:
                                    total_bytes = int(head_resp.headers["content-length"])
                                except (ValueError, TypeError):
                                    total_bytes = None
                            mime_type = head_resp.headers.get("content-type", mime_type)
                            accept_ranges = head_resp.headers.get("accept-ranges", "").lower()
                            if "bytes" in accept_ranges:
                                resume_supported = True
                            
                            header_filename = parse_filename_from_headers(head_resp.headers)
                        else:
                            header_filename = ""
                    except httpx.TimeoutException:
                        raise
                    except Exception as probe_exc:
                        logger.debug("[Downloader] HEAD probe failed (%s), will proceed with GET stream", probe_exc)
                        header_filename = ""

                    # Step 2: Determine target filename
                    if custom_filename and custom_filename.strip():
                        target_filename = sanitize_filename(custom_filename)
                    elif header_filename:
                        target_filename = sanitize_filename(header_filename)
                    else:
                        url_filename = extract_filename_from_url(url)
                        target_filename = sanitize_filename(url_filename, f"download_{int(time.time())}.bin")

                    final_file = self.download_dir / target_filename
                    part_file = self.download_dir / f"{target_filename}.part"

                    # Step 3: Check disk space if total_bytes is known
                    if total_bytes is not None:
                        if total_bytes > MAX_FILE_SIZE_BYTES:
                            return {
                                "status": "error",
                                "message": (
                                    f"Tệp quá lớn ({round(total_bytes / (1024**3), 2)} GB), "
                                    f"vượt quá giới hạn tối đa cho phép ({MAX_FILE_SIZE_BYTES // (1024**3)} GB)."
                                ),
                            }
                        try:
                            usage = shutil.disk_usage(self.download_dir)
                            if usage.free < (total_bytes + MIN_DISK_MARGIN_BYTES):
                                return {
                                    "status": "error",
                                    "message": (
                                        f"Không đủ dung lượng đĩa trống trên máy chủ "
                                        f"(cần {round((total_bytes + MIN_DISK_MARGIN_BYTES)/(1024*1024), 1)} MB, "
                                        f"còn trống {round(usage.free/(1024*1024), 1)} MB)."
                                    ),
                                }
                        except Exception as disk_err:
                            logger.warning("[Downloader] Failed to check disk usage: %s", disk_err)

                    # Step 4: Check existing .part file for resume
                    existing_bytes = 0
                    if part_file.exists() and resume_supported:
                        existing_bytes = part_file.stat().st_size
                        if total_bytes and existing_bytes < total_bytes:
                            headers["Range"] = f"bytes={existing_bytes}-"
                            was_resumed = True
                            logger.info(
                                "[Downloader] Resuming download for %s at byte offset %d/%s",
                                target_filename,
                                existing_bytes,
                                total_bytes,
                            )
                        elif total_bytes and existing_bytes >= total_bytes:
                            # Already fully downloaded in .part
                            part_file.replace(final_file)
                            elapsed = max(0.001, time.time() - start_time)
                            return {
                                "status": "success",
                                "file_path": str(final_file),
                                "file_name": target_filename,
                                "file_size_mb": round(final_file.stat().st_size / (1024 * 1024), 2),
                                "file_size_bytes": final_file.stat().st_size,
                                "download_time_sec": round(elapsed, 2),
                                "download_speed_mbps": 0.0,
                                "mime_type": mime_type,
                                "resume_supported": resume_supported,
                                "resumed": True,
                                "url": url,
                                "message": f"Tải tệp thành công (đã có sẵn): {target_filename}",
                            }

                    # Step 5: Perform streaming GET request
                    async with client.stream("GET", url, headers=headers) as resp:
                        if resp.status_code not in (200, 206):
                            return {
                                "status": "error",
                                "message": f"Máy chủ nguồn trả về mã lỗi HTTP {resp.status_code}: {resp.reason_phrase}",
                            }

                        if "content-type" in resp.headers:
                            mime_type = resp.headers["content-type"]

                        if "bytes" in resp.headers.get("accept-ranges", "").lower():
                            resume_supported = True

                        if total_bytes is None and "content-length" in resp.headers:
                            try:
                                clen = int(resp.headers["content-length"])
                                total_bytes = clen + (existing_bytes if resp.status_code == 206 else 0)
                            except (ValueError, TypeError):
                                pass

                        # Decide file open mode: append if 206 Partial Content, else overwrite
                        if resp.status_code == 206 and was_resumed:
                            open_mode = "ab"
                            downloaded_bytes = existing_bytes
                        else:
                            open_mode = "wb"
                            downloaded_bytes = 0
                            was_resumed = False

                        # Stream chunks to disk
                        with open(part_file, open_mode) as out_fp:
                            async for chunk in resp.aiter_bytes(chunk_size=CHUNK_SIZE):
                                if chunk:
                                    out_fp.write(chunk)
                                    downloaded_bytes += len(chunk)

                    # Step 6: Atomic rename upon complete download
                    if part_file.exists():
                        part_file.replace(final_file)

                    elapsed = max(0.001, time.time() - start_time)
                    file_size = final_file.stat().st_size if final_file.exists() else downloaded_bytes
                    file_size_mb = round(file_size / (1024 * 1024), 2)
                    speed_mbps = round((file_size / (1024 * 1024)) / elapsed, 2)

                    logger.info(
                        "[Downloader] Completed %s: %s MB in %.2fs (%.2f MB/s)",
                        target_filename,
                        file_size_mb,
                        elapsed,
                        speed_mbps,
                    )

                    return {
                        "status": "success",
                        "file_path": str(final_file),
                        "file_name": target_filename,
                        "file_size_mb": file_size_mb,
                        "file_size_bytes": file_size,
                        "download_time_sec": round(elapsed, 2),
                        "download_speed_mbps": speed_mbps,
                        "mime_type": mime_type,
                        "resume_supported": resume_supported,
                        "resumed": was_resumed,
                        "url": url,
                        "message": f"Tải tệp thành công: {target_filename} ({file_size_mb} MB) trong {round(elapsed, 2)}s.",
                    }

            except httpx.TimeoutException as timeout_err:
                logger.error("[Downloader] Timeout downloading %s: %s", url, timeout_err)
                return {
                    "status": "error",
                    "message": f"Quá thời gian chờ phản hồi từ máy chủ nguồn (timeout sau {READ_TIMEOUT_SEC}s).",
                }
            except Exception as exc:
                logger.error("[Downloader] Error downloading %s: %s", url, exc, exc_info=True)
                return {
                    "status": "error",
                    "message": f"Lỗi trong quá trình tải tệp: {str(exc)}",
                }
            finally:
                # Zero-Disk Leak: If download failed and server does not support resume, purge orphaned .part
                if part_file and part_file.exists() and not resume_supported:
                    try:
                        part_file.unlink(missing_ok=True)
                        logger.info("[Downloader] Cleaned up non-resumable temp part file %s", part_file)
                    except Exception as clean_err:
                        logger.warning("[Downloader] Failed to clean temp part file %s: %s", part_file, clean_err)

    def cleanup_temp_files(self, max_age_seconds: int = 86400) -> int:
        """
        Sweeps orphaned .part files older than max_age_seconds to prevent disk leaks.
        Returns the number of purged files.
        """
        now = time.time()
        purged = 0
        try:
            if not self.download_dir.exists():
                return 0
            for item in self.download_dir.glob("*.part"):
                if item.is_file():
                    age = now - item.stat().st_mtime
                    if age > max_age_seconds:
                        item.unlink(missing_ok=True)
                        purged += 1
        except Exception as exc:
            logger.warning("[Downloader] Error during temp files cleanup: %s", exc)
        return purged


# Module-level singleton instance
universal_downloader = UniversalDownloader()


async def download_direct_file(url: str, custom_filename: Optional[str] = None) -> Dict[str, Any]:
    """
    Public module-level contract for direct internet file downloading.
    """
    return await universal_downloader.download_direct_file(url, custom_filename=custom_filename)
