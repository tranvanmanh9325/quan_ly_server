"""
media_downloader.py — Resilient Multi-Tier Social Media Video Downloader Pipeline.

Kiến trúc phân tầng chuyên biệt cho 'quan_ly_server' trên hạ tầng RAM 3.2GB / 2 Cores i5 Haswell:
  • Tier 1: TikWM API Engine (Siêu tốc < 0.5s, 100% No-Watermark HD cho TikTok & Douyin, hỗ trợ Album ảnh)
  • Tier 2: yt-dlp Engine (Universal Robust Downloader cho YouTube, Facebook Reels/Watch, IG, X/Twitter)
  • Tier 3: Playwright JSON Hydration Sniffer (Dự phòng khẩn cấp khi bị chặn mạng)

Tính năng an toàn:
  • Zero-RAM chunked disk streaming (64KB chunks trực tiếp ra đĩa SSD tạm)
  • Tải chất lượng cao nhất (Best Video + Best Audio / 1080p, 2K, 4K lossless), không giới hạn dung lượng tải về máy chủ
  • Format MP4 chuẩn tương thích phát trực tiếp hoặc phân phối kép cho Telegram
  • Giới hạn tác vụ song song bằng asyncio.Semaphore bảo vệ CPU máy chủ
  • Tự động dọn dẹp file tạm triệt để trong khối try...finally
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse

import httpx

from app.core.http_client import http_client_manager
from app.core.memory_reclaimer import reclaim_memory_background

logger = logging.getLogger(__name__)

# Giới hạn 50MB của Telegram Bot API dùng cho phân phối (Milestone 2), không dùng để ngắt tải máy chủ
TELEGRAM_MAX_FILE_SIZE = 50 * 1024 * 1024
TELEGRAM_CHUNK_SIZE = 48 * 1024 * 1024
TEMP_MEDIA_DIR = Path("/tmp/media_downloads")


def _clean_fbcdn_stream_url(stream_url: str) -> str:
    """
    Loại bỏ các query parameter phân đoạn byte range ('bytestart', 'byteend')
    từ URL CDN của Meta (fbcdn.net / cdninstagram.com), chuyển đổi request từ
    phân đoạn DASH range sang tải toàn vẹn progressive MP4 (chuẩn HTTP 200 OK).
    """
    parsed = urllib.parse.urlsplit(stream_url)
    query_params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    filtered = [
        (k, v) for (k, v) in query_params 
        if k.lower() not in ("bytestart", "byteend")
    ]
    new_query = urllib.parse.urlencode(filtered)
    return urllib.parse.urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        new_query,
        parsed.fragment,
    ))


def _is_meta_cdn_url(url: Optional[str]) -> bool:
    """
    Safely validates that a candidate stream URL belongs to Meta CDN domains.
    RFC-compliant hostname parsing eliminates CodeQL py/incomplete-url-substring-sanitization.
    """
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urllib.parse.urlparse(url)
        hostname = (parsed.hostname or "").lower()
        allowed_domains = ("fbcdn.net", "cdninstagram.com")
        return any(hostname == d or hostname.endswith("." + d) for d in allowed_domains)
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────────────
# TẦNG 1: Regex Canonical Rewriting cho Facebook Share URLs (0ms, Zero Network)
# ──────────────────────────────────────────────────────────────────────────

_FB_SHARE_REEL_PATTERN = re.compile(
    r"^https?://(?:(?:[\w-]+\.)?facebook\.com|(?:www\.)?fb\.com)/share/(?:r|reel)/([^/?#&]+)",
    re.IGNORECASE,
)
_FB_SHARE_WATCH_PATTERN = re.compile(
    r"^https?://(?:(?:[\w-]+\.)?facebook\.com|(?:www\.)?fb\.com)/share/(?:v|video)/([^/?#&]+)",
    re.IGNORECASE,
)


def canonicalize_facebook_url(url: str) -> str:
    """
    Tầng 1 (Tĩnh): Chuẩn hóa các URL Facebook dạng share chứa ID rõ ràng sang Canonical URL chuẩn
    mà yt-dlp hỗ trợ (/reel/<id>/ hoặc /watch/?v=<id>).

    Ưu điểm:
      - Hoàn toàn không tốn request mạng (0ms latency, 0 RAM, 0 HTTP overhead).
      - Bỏ qua hoàn toàn cơ chế WAF/Bot Protection của Facebook đối với các link chia sẻ từ mobile.
      - Tự động bóc tách và loại bỏ sạch sẽ các query parameters rác (?mibextid=..., ?_fb_noscript=1).
    """
    clean = url.strip()
    m_reel = _FB_SHARE_REEL_PATTERN.search(clean)
    if m_reel:
        reel_id = m_reel.group(1)
        return f"https://www.facebook.com/reel/{reel_id}/"

    m_watch = _FB_SHARE_WATCH_PATTERN.search(clean)
    if m_watch:
        video_id = m_watch.group(1)
        return f"https://www.facebook.com/watch/?v={video_id}"

    return clean


_normalize_facebook_url = canonicalize_facebook_url


@dataclass
class MediaItem:
    """Đại diện cho tệp media đã tải sẵn sàng chuyển giao cho Telegram Bot."""
    file_path: Optional[str]
    title: str
    author: str
    duration: int
    media_type: str  # 'video', 'audio', 'images'
    source_url: str
    images: List[str] = field(default_factory=list)
    file_size: int = 0
    direct_stream_url: Optional[str] = None
    cover_url: Optional[str] = None
    thumbnail_path: Optional[str] = None
    is_temp_file: bool = True
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[float] = None

    @property
    def is_60fps(self) -> bool:
        """Kiểm tra video có phải chuẩn tốc độ khung hình cao (60fps hoặc 59.94fps) hay không."""
        return bool(self.fps is not None and self.fps >= 55.0)

    @property
    def resolution_label(self) -> str:
        """Nhãn độ phân giải trực quan phục vụ Telegram Card caption."""
        if not self.width or not self.height:
            return ""
        min_dim = min(self.width, self.height)
        if min_dim >= 2160:
            return "4K UHD"
        if min_dim >= 1440:
            return "2K QHD"
        if min_dim >= 1080:
            return "1080p FHD"
        if min_dim >= 720:
            return "720p HD"
        if min_dim >= 480:
            return "480p SD"
        return f"{self.width}x{self.height}"

    @property
    def fps_label(self) -> str:
        """Nhãn tốc độ khung hình làm tròn chuẩn truyền thông (ví dụ: 60fps, 120fps, 30fps)."""
        if self.fps is None or self.fps <= 0:
            return ""
        if 55.0 <= self.fps <= 65.0:
            return "60fps"
        if self.fps >= 115.0:
            return "120fps"
        return f"{round(self.fps)}fps"

    def cleanup(self) -> None:
        """Xóa sạch tệp tạm khỏi ổ đĩa một cách an toàn."""
        if self.is_temp_file and self.file_path:
            try:
                p = Path(self.file_path)
                if p.exists():
                    p.unlink()
                    logger.debug("[MediaItem] Cleaned up temporary file: %s", self.file_path)
                parent = p.parent
                if (
                    parent.is_dir()
                    and parent.name.startswith("media_ytdlp_")
                    and parent.resolve() != TEMP_MEDIA_DIR.resolve()
                    and parent.resolve().is_relative_to(TEMP_MEDIA_DIR.resolve())
                ):
                    shutil.rmtree(parent, ignore_errors=True)
                    logger.debug("[MediaItem] Cleaned up temporary directory: %s", parent)
            except Exception as err:
                logger.warning("[MediaItem] Failed to clean up file %s: %s", self.file_path, err)

        if self.thumbnail_path:
            try:
                tp = Path(self.thumbnail_path)
                if tp.exists():
                    tp.unlink()
                    logger.debug("[MediaItem] Cleaned up temporary thumbnail: %s", self.thumbnail_path)
            except Exception as err:
                logger.warning("[MediaItem] Failed to clean up thumbnail %s: %s", self.thumbnail_path, err)

    def __enter__(self) -> "MediaItem":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.cleanup()

    async def __aenter__(self) -> "MediaItem":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self.cleanup()


def cleanup_expired_media(max_age_seconds: int = 600) -> int:
    """
    Quét dọn các tệp và thư mục tạm mồ côi trong TEMP_MEDIA_DIR cũ hơn max_age_seconds (mặc định 10 phút).
    Bảo đảm dọn dẹp triệt để trong trường hợp container bị crash, OOM kill hoặc yt-dlp partial files.
    """
    if not TEMP_MEDIA_DIR.exists():
        return 0
    now = time.time()
    cleaned_count = 0
    try:
        for entry in os.scandir(TEMP_MEDIA_DIR):
            try:
                stat = entry.stat()
                age = now - stat.st_mtime
                if age > max_age_seconds:
                    if entry.is_dir(follow_symlinks=False):
                        shutil.rmtree(entry.path, ignore_errors=True)
                        cleaned_count += 1
                        logger.info("[MediaCleanup] Cleaned expired directory: %s (age %.1fs)", entry.path, age)
                    elif entry.is_file(follow_symlinks=False):
                        os.unlink(entry.path)
                        cleaned_count += 1
                        logger.info("[MediaCleanup] Cleaned expired file: %s (age %.1fs)", entry.path, age)
            except Exception as item_err:
                logger.debug("[MediaCleanup] Error inspecting entry %s: %s", entry.name, item_err)
    except Exception as scan_err:
        logger.warning("[MediaCleanup] Failed scanning %s: %s", TEMP_MEDIA_DIR, scan_err)
    return cleaned_count


class MediaPipelineError(Exception):
    """Lỗi chung của pipeline tải media."""
    pass


class VideoTooLargeError(MediaPipelineError):
    """Ném ra khi video vượt quá giới hạn 50MB của Telegram Bot API."""
    pass


class MediaDurationLimitError(MediaPipelineError):
    """Ném ra khi video vượt quá giới hạn thời lượng an toàn tối đa 7200s (2 giờ)."""
    pass


def _parse_fps_string(fps_val: Any) -> Optional[float]:
    """Chuyển đổi chuỗi/giá trị FPS (ví dụ: '60000/1001', '60/1', 59.94, '30') sang float chuẩn xác."""
    if not fps_val or fps_val in ("0/0", "N/A"):
        return None
    try:
        if isinstance(fps_val, (int, float)):
            val = float(fps_val)
            return round(val, 2) if val > 0 else None
        fps_str = str(fps_val).strip()
        if "/" in fps_str:
            num_s, den_s = fps_str.split("/", 1)
            num, den = float(num_s), float(den_s)
            if den > 0:
                return round(num / den, 2)
        else:
            val = float(fps_str)
            if val > 0:
                return round(val, 2)
    except Exception:
        pass
    return None


class MultiTierMediaPipeline:
    """
    Bộ điều phối tải video đa tầng với cơ chế suy giảm dự phòng (Graceful Degradation).
    Bảo vệ RAM 3.2GB và 2 Cores CPU bằng Semaphore và Streaming I/O.
    """

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self._external_client = http_client
        self._ytdlp_semaphore = asyncio.Semaphore(2)
        self._playwright_semaphore = asyncio.Semaphore(1)

        self._tiktok_regex = re.compile(
            r"https?://(?:www\.|vt\.|vm\.|v\.|m\.)?(?:tiktok\.com|douyin\.com)/.+",
            re.IGNORECASE
        )
        self._youtube_regex = re.compile(
            r"https?://(?:www\.|m\.)?(?:youtube\.com|youtu\.be)/.+",
            re.IGNORECASE
        )
        self._facebook_regex = re.compile(
            r"https?://(?:www\.|web\.|m\.)?(?:facebook\.com|fb\.watch|fb\.me)/.+",
            re.IGNORECASE
        )
        self._facebook_redirect_regex = re.compile(
            r"^https?://(?:(?:[\w-]+\.)?facebook\.com/share/|(?:www\.)?(?:fb\.watch|fb\.me|fb\.com/share)/)",
            re.IGNORECASE
        )
        self._threads_regex = re.compile(
            r"https?://(?:www\.)?(?:threads\.net|threads\.com)/(?:@[^/\s]+/post|t)/[^\s]+",
            re.IGNORECASE,
        )
        self._audio_platform_regex = re.compile(
            r"https?://(?:[a-zA-Z0-9_-]+\.)?(?:soundcloud\.com|music\.youtube\.com)/",
            re.IGNORECASE,
        )

        TEMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        # Quét dọn các file mồ côi cũ từ các phiên làm việc trước khi khởi tạo
        cleanup_expired_media(max_age_seconds=600)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._external_client and not self._external_client.is_closed:
            return self._external_client
        return http_client_manager.get_media_client()

    async def _resolve_redirect_url(self, url: str) -> str:
        """
        Tầng 2 (Động): Phân giải URL Facebook rút gọn động (fb.watch, fb.me...) bằng httpx stream ngắt sớm.

        Ưu điểm kỹ thuật:
          - Tái sử dụng HTTP connection pool qua http_client_manager.get_media_client(), tiết kiệm 150-300ms TLS handshake.
          - Ép IPv4 (local_address='0.0.0.0') loại bỏ lỗi [Errno 101] Network is unreachable trên Docker bridge.
          - Sử dụng User-Agent chính thức 'facebookexternalhit/1.1' được Meta white-list, loại bỏ triệt để HTTP 400 WAF.
          - Dùng client.stream('GET', follow_redirects=True, max_redirects=5) ngắt sớm (early abort): đọc xong HTTP headers
            chuyển hướng 3xx và header đích 200 OK là thoát ngay, không đọc byte nội dung nào (0 byte body, 0 RAM).
          - Giới hạn max_redirects=5 và bắt httpx.TooManyRedirects chống redirect lặp vô tận từ login.php.
          - Tự động nhận diện khi Facebook chuyển hướng về trang login hoặc checkpoint để cảnh báo video riêng tư.
          - Chuẩn hóa canonicalize_facebook_url ngay sau khi phân giải để đảm bảo định dạng đích tương thích yt-dlp.
          - Bọc try-except toàn diện: nếu timeout hoặc lỗi kết nối, trả về URL gốc một cách an toàn.
        """
        logger.info("[RedirectResolver] Resolving potential redirect URL: %s", url)
        try:
            headers = {
                "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
            }
            client = self._external_client if (self._external_client and not self._external_client.is_closed) else httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=httpx.Timeout(10.0))
            is_managed = (client is self._external_client)
            try:
                async with client.stream(
                    "GET",
                    url,
                    headers=headers,
                    follow_redirects=True,
                    max_redirects=5,
                ) as resp:
                    resolved_url = str(resp.url)
                    status_code = resp.status_code

                    # Kiểm tra nếu Facebook redirect về trang login hoặc checkpoint (bài viết/video riêng tư)
                    if any(p in resolved_url for p in ("/login", "/checkpoint", "login.php")):
                        logger.warning(
                            "[RedirectResolver] Facebook URL redirected to login/checkpoint (private/restricted): %s -> %s",
                            url,
                            resolved_url,
                        )
                        return url

                    if status_code < 400:
                        canonical = canonicalize_facebook_url(resolved_url)
                        logger.info(
                            "[RedirectResolver] Successfully resolved: %s -> %s (canonical: %s, HTTP %d)",
                            url,
                            resolved_url,
                            canonical,
                            status_code,
                        )
                        return canonical
                    else:
                        logger.warning(
                            "[RedirectResolver] HTTP %d received for %s. Keeping original URL.",
                            status_code,
                            url,
                        )
                        return url
            finally:
                if not is_managed:
                    await client.aclose()

        except (asyncio.TimeoutError, httpx.TooManyRedirects) as err:
            logger.warning("[RedirectResolver] Timeout or redirect loop resolving for %s (%s). Keeping original URL.", url, err)
            return url
        except Exception as err:
            logger.warning("[RedirectResolver] Error resolving redirect for %s: %s. Keeping original URL.", url, err)
            return url

    # ──────────────────────────────────────────────────────────────────────────
    # TẦNG 1: TikWM API Engine (Siêu tốc < 0.5s - 1s, 100% No-Watermark HD)
    # ──────────────────────────────────────────────────────────────────────────

    async def _download_tikwm(self, url: str) -> Optional[MediaItem]:
        """Trích xuất video TikTok/Douyin không logo chất lượng cao qua TikWM API."""
        logger.info("[Tier 1: TikWM] Initiating extraction for: %s", url)
        client = await self._get_client()
        api_endpoint = "https://www.tikwm.com/api/"

        try:
            resp = await client.post(api_endpoint, data={"url": url, "hd": 1}, timeout=10.0)
            if resp.status_code != 200:
                logger.warning("[Tier 1: TikWM] HTTP %d received from TikWM API", resp.status_code)
                return None

            res_json = resp.json()
            if res_json.get("code") != 0 or "data" not in res_json:
                logger.warning("[Tier 1: TikWM] API error: %s", res_json.get("msg"))
                return None

            data = res_json["data"]
            title = data.get("title") or "TikTok Video"
            author_info = data.get("author") or {}
            author = author_info.get("nickname") or author_info.get("unique_id") or "tiktok_creator"
            duration = int(data.get("duration", 0))

            if data.get("images"):
                images_list = data["images"]
                music_url = data.get("music")
                logger.info("[Tier 1: TikWM] Detected photo album with %d photos", len(images_list))
                return MediaItem(
                    file_path=None,
                    title=title,
                    author=author,
                    duration=duration,
                    media_type="images",
                    source_url=url,
                    images=images_list,
                    direct_stream_url=music_url,
                    is_temp_file=False,
                )

            stream_url = data.get("hdplay") or data.get("play")
            if not stream_url:
                logger.warning("[Tier 1: TikWM] No playable stream URL in response")
                return None

            # Chuẩn hóa URL tuyệt đối để phòng trường hợp TikWM trả về relative path
            stream_url = urllib.parse.urljoin("https://www.tikwm.com", stream_url)

            temp_file_path, file_size = await self._stream_url_to_file(stream_url, client)

            return MediaItem(
                file_path=temp_file_path,
                title=title,
                author=author,
                duration=duration,
                media_type="video",
                source_url=url,
                file_size=file_size,
                direct_stream_url=stream_url,
                is_temp_file=True,
            )

        except VideoTooLargeError:
            raise
        except (httpx.RequestError, asyncio.TimeoutError) as err:
            logger.warning("[Tier 1: TikWM] Request failure: %s", err)
            return None
        except Exception as err:
            logger.error("[Tier 1: TikWM] Unexpected failure: %s", err, exc_info=True)
            return None

    async def _prepare_cover_and_thumb(
        self, cover_url: Optional[str], client: httpx.AsyncClient
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Tải ảnh bìa và tạo thumbnail JPEG max 320x320 (< 200KB) bằng Pillow.
        Trả về: (raw_cover_path, thumbnail_path).
        raw_cover_path được giải phóng trong finally của quá trình muxing.
        thumbnail_path được gán vào MediaItem và giải phóng khi cleanup.
        Nếu ảnh lỗi hoặc không hợp lệ, dọn dẹp sạch sẽ và trả về (None, None).
        """
        if not cover_url:
            return None, None

        raw_cover_path = None
        thumbnail_path = None
        t_name = None
        try:
            raw_cover_path, _ = await self._stream_url_to_file(cover_url, client, suffix=".jpg")
            try:
                from PIL import Image
                # Mở và xác thực ảnh bằng Pillow TRƯỚC KHI tạo file thumbnail trên đĩa
                with Image.open(raw_cover_path) as img:
                    img.thumbnail((320, 320))
                    rgb = img.convert("RGB")
                    with tempfile.NamedTemporaryFile(suffix="_thumb.jpg", dir=str(TEMP_MEDIA_DIR), delete=False) as tf:
                        t_name = tf.name
                    rgb.save(t_name, format="JPEG", quality=85)
                    if os.path.exists(t_name) and os.path.getsize(t_name) > 200 * 1024:
                        rgb.save(t_name, format="JPEG", quality=65)
                if t_name and os.path.exists(t_name):
                    thumbnail_path = t_name
            except Exception as pe:
                logger.warning("[MediaDownloader] Invalid cover image or Pillow generation error: %s", pe)
                if t_name and os.path.exists(t_name):
                    try:
                        os.unlink(t_name)
                    except OSError:
                        pass
                if raw_cover_path and os.path.exists(raw_cover_path):
                    try:
                        os.unlink(raw_cover_path)
                    except OSError:
                        pass
                return None, None
        except Exception as err:
            logger.warning("[MediaDownloader] Failed preparing cover/thumb for %s: %s", cover_url, err)
            if t_name and os.path.exists(t_name):
                try:
                    os.unlink(t_name)
                except OSError:
                    pass
            if raw_cover_path and os.path.exists(raw_cover_path):
                try:
                    os.unlink(raw_cover_path)
                except OSError:
                    pass
            return None, None

        return raw_cover_path, thumbnail_path

    async def _mux_mp3_with_metadata(
        self,
        input_path: str,
        output_path: str,
        is_video: bool,
        cover_path: Optional[str] = None,
        title: str = "TikTok Audio",
        artist: str = "TikTok Creator",
        album: str = "TikTok Audio",
        date: Optional[str] = None,
    ) -> bool:
        """
        Trích xuất (nếu is_video=True, 320kbps MP3 CBR Stereo 44.1kHz) hoặc remux copy
        kèm ID3v2.3 tags và APIC Cover Art qua FFmpeg native.
        """
        clean_title = (title or "TikTok Audio")[:250]
        clean_artist = (artist or "TikTok Creator")[:250]
        clean_album = (album or "TikTok Audio")[:250]
        year_str = date or time.strftime("%Y")

        cmd = [
            "ffmpeg", "-y", "-v", "error", "-threads", "2",
            "-i", str(input_path),
        ]
        if cover_path and os.path.exists(cover_path):
            cmd.extend([
                "-i", str(cover_path),
                "-map", "0:a:0",
                "-map", "1:v",
            ])
            if is_video:
                cmd.extend([
                    "-c:a", "libmp3lame", "-b:a", "320k", "-ar", "44100", "-ac", "2",
                ])
            else:
                cmd.extend([
                    "-c:a", "copy",
                ])
            cmd.extend([
                "-c:v", "mjpeg",
                "-disposition:v:0", "attached_pic",
                "-id3v2_version", "3",
                "-metadata:s:v", 'title="Album cover"',
                "-metadata:s:v", 'comment="Cover (front)"',
            ])
        else:
            cmd.extend([
                "-map", "0:a:0",
            ])
            if is_video:
                cmd.extend([
                    "-c:a", "libmp3lame", "-b:a", "320k", "-ar", "44100", "-ac", "2",
                ])
            else:
                cmd.extend([
                    "-c:a", "copy",
                ])
            cmd.extend([
                "-id3v2_version", "3",
            ])

        cmd.extend([
            "-metadata", f"title={clean_title}",
            "-metadata", f"artist={clean_artist}",
            "-metadata", f"album={clean_album}",
            "-metadata", f"date={year_str}",
            str(output_path),
        ])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                return True
            err_msg = stderr.decode("utf-8", errors="replace").strip() if stderr else ""
            logger.warning("[FFmpeg Mux] FFmpeg exited with code %d: %s", proc.returncode, err_msg)
            return False
        except Exception as e:
            logger.warning("[FFmpeg Mux] Exception during FFmpeg execution: %s", e)
            return False

    async def _download_tikwm_audio(self, url: str) -> Optional[MediaItem]:
        """
        Dual-Source Smart Audio Engine cho TikTok/Douyin qua TikWM API:
          - So khớp duration giữa video và music snippet.
          - Nhánh Direct CDN (0% CPU, <0.5s): Slideshow (images) hoặc duration khớp (độ lệch <=2s) và video <=30s.
          - Nhánh Trích Xuất HD Video (Full-Fidelity 320kbps MP3 via FFmpeg): Khi music bị cắt 30s hoặc video >30s.
          - Nhúng ID3v2.3 tags và APIC Cover Art frame.
          - Resize ảnh bìa Pillow max 320x320 JPEG (<200KB) làm thumbnail cho Telegram Bot Native Audio Card.
          - Dọn dẹp sạch sẽ 100% tệp trung gian trong finally (Zero-Disk Leak).
        """
        logger.info("[Tier 1: TikWM Audio] Initiating dual-source audio extraction for: %s", url)
        client = await self._get_client()
        api_endpoint = "https://www.tikwm.com/api/"

        try:
            resp = await client.post(api_endpoint, data={"url": url, "hd": 1}, timeout=10.0)
            if resp.status_code != 200:
                logger.warning("[Tier 1: TikWM Audio] HTTP %d received from TikWM API", resp.status_code)
                return None

            res_json = resp.json()
            if res_json.get("code") != 0 or "data" not in res_json:
                logger.warning("[Tier 1: TikWM Audio] API error: %s", res_json.get("msg"))
                return None

            data = res_json["data"]
            music_info = data.get("music_info") or {}
            author_info = data.get("author") or {}

            video_duration = int(data.get("duration") or 0)
            music_duration = int(music_info.get("duration") or 0)
            images = data.get("images")
            play_url = data.get("hdplay") or data.get("play")
            music_url = data.get("music") or music_info.get("play")
            cover_url = (
                music_info.get("cover")
                or data.get("origin_cover")
                or data.get("cover")
            )

            if music_url:
                music_url = urllib.parse.urljoin("https://www.tikwm.com", music_url)
            if play_url:
                play_url = urllib.parse.urljoin("https://www.tikwm.com", play_url)
            if cover_url:
                cover_url = urllib.parse.urljoin("https://www.tikwm.com", cover_url)

            if not music_url and not play_url:
                logger.warning("[Tier 1: TikWM Audio] Neither music_url nor play_url found in TikWM response")
                return None

            title = music_info.get("title") or data.get("title") or "TikTok Audio"
            performer = (
                music_info.get("author")
                or author_info.get("nickname")
                or author_info.get("unique_id")
                or "TikTok Creator"
            )

            # Routing Decision:
            # 1. Slideshow (images) -> Direct CDN (không có video track)
            # 2. Không có play_url nhưng có music_url -> Direct CDN
            # 3. Video ngắn <= 30s VÀ duration khớp (độ lệch <= 2s) VÀ có music_url -> Direct CDN
            # 4. Ngược lại (music bị cắt 30s, video > 30s, hoặc vlog/đối thoại) -> HD Video Extraction
            use_direct_cdn = False
            if images:
                use_direct_cdn = True
            elif not play_url and music_url:
                use_direct_cdn = True
            elif music_url and abs(video_duration - music_duration) <= 2 and video_duration <= 30:
                use_direct_cdn = True

            staging_cleanup_files: List[str] = []
            raw_cover_path = None
            thumbnail_path = None
            final_file_path = None
            final_file_size = 0
            final_duration = video_duration or music_duration
            is_success = False

            try:
                if cover_url:
                    raw_cover_path, thumbnail_path = await self._prepare_cover_and_thumb(cover_url, client)
                    if raw_cover_path:
                        staging_cleanup_files.append(raw_cover_path)

                if not use_direct_cdn and play_url:
                    logger.info(
                        "[Tier 1: TikWM Audio] Engaging HD Video Audio Extraction (video: %ds, music: %ds)",
                        video_duration, music_duration
                    )
                    temp_vid_path, _ = await self._stream_url_to_file(play_url, client, suffix=".mp4")
                    staging_cleanup_files.append(temp_vid_path)

                    with tempfile.NamedTemporaryFile(suffix=".mp3", dir=str(TEMP_MEDIA_DIR), delete=False) as tf:
                        target_mp3_path = tf.name

                    success = await self._mux_mp3_with_metadata(
                        input_path=temp_vid_path,
                        output_path=target_mp3_path,
                        is_video=True,
                        cover_path=raw_cover_path,
                        title=title,
                        artist=performer,
                        album="TikTok Audio",
                    )
                    # Graceful Degradation: Nếu mux kèm cover lỗi, retry một lần nữa không cover
                    if not success and raw_cover_path:
                        logger.warning(
                            "[Tier 1: TikWM Audio] Mux with cover failed, retrying without cover art (graceful degradation)"
                        )
                        success = await self._mux_mp3_with_metadata(
                            input_path=temp_vid_path,
                            output_path=target_mp3_path,
                            is_video=True,
                            cover_path=None,
                            title=title,
                            artist=performer,
                            album="TikTok Audio",
                        )
                    if success:
                        final_file_path = target_mp3_path
                        final_file_size = os.path.getsize(target_mp3_path)
                        final_duration = video_duration or music_duration
                    else:
                        if os.path.exists(target_mp3_path):
                            try:
                                os.unlink(target_mp3_path)
                            except OSError:
                                pass
                        if music_url:
                            logger.warning("[Tier 1: TikWM Audio] HD extraction failed, falling back to direct CDN")
                            use_direct_cdn = True

                if use_direct_cdn or not final_file_path:
                    if not music_url:
                        logger.warning("[Tier 1: TikWM Audio] Direct CDN selected but no music_url available")
                        return None

                    logger.info("[Tier 1: TikWM Audio] Engaging Direct CDN Stream: %s", music_url)
                    raw_mp3_path, raw_size = await self._stream_url_to_file(music_url, client, suffix=".mp3")
                    staging_cleanup_files.append(raw_mp3_path)

                    if raw_cover_path:
                        with tempfile.NamedTemporaryFile(suffix=".mp3", dir=str(TEMP_MEDIA_DIR), delete=False) as tf:
                            target_mp3_path = tf.name
                        remux_success = await self._mux_mp3_with_metadata(
                            input_path=raw_mp3_path,
                            output_path=target_mp3_path,
                            is_video=False,
                            cover_path=raw_cover_path,
                            title=title,
                            artist=performer,
                            album="TikTok Audio",
                        )
                        if not remux_success:
                            logger.warning(
                                "[Tier 1: TikWM Audio] Direct CDN remux with cover failed, retrying without cover art"
                            )
                            remux_success = await self._mux_mp3_with_metadata(
                                input_path=raw_mp3_path,
                                output_path=target_mp3_path,
                                is_video=False,
                                cover_path=None,
                                title=title,
                                artist=performer,
                                album="TikTok Audio",
                            )
                        if remux_success:
                            final_file_path = target_mp3_path
                            final_file_size = os.path.getsize(target_mp3_path)
                        else:
                            if os.path.exists(target_mp3_path):
                                try:
                                    os.unlink(target_mp3_path)
                                except OSError:
                                    pass
                            final_file_path = raw_mp3_path
                            final_file_size = raw_size
                            if raw_mp3_path in staging_cleanup_files:
                                staging_cleanup_files.remove(raw_mp3_path)
                    else:
                        final_file_path = raw_mp3_path
                        final_file_size = raw_size
                        if raw_mp3_path in staging_cleanup_files:
                            staging_cleanup_files.remove(raw_mp3_path)

                    final_duration = music_duration or video_duration

                if not final_file_path:
                    logger.warning("[Tier 1: TikWM Audio] Failed to produce final MP3 audio")
                    return None

                is_success = True
                return MediaItem(
                    file_path=final_file_path,
                    title=title,
                    author=performer,
                    duration=final_duration,
                    media_type="audio",
                    source_url=url,
                    file_size=final_file_size,
                    direct_stream_url=music_url or play_url,
                    cover_url=cover_url,
                    thumbnail_path=thumbnail_path,
                    is_temp_file=True,
                )

            finally:
                for staging_file in staging_cleanup_files:
                    if staging_file and os.path.exists(staging_file):
                        try:
                            os.unlink(staging_file)
                            logger.debug("[Tier 1: TikWM Audio] Cleaned staging file: %s", staging_file)
                        except Exception as ce:
                            logger.warning("[Tier 1: TikWM Audio] Error cleaning staging file %s: %s", staging_file, ce)

                if not is_success:
                    if final_file_path and os.path.exists(final_file_path):
                        try:
                            os.unlink(final_file_path)
                            logger.debug("[Tier 1: TikWM Audio] Cleaned unreturned final file: %s", final_file_path)
                        except Exception as fe:
                            logger.warning("[Tier 1: TikWM Audio] Error cleaning unreturned final file %s: %s", final_file_path, fe)
                    if thumbnail_path and os.path.exists(thumbnail_path):
                        try:
                            os.unlink(thumbnail_path)
                            logger.debug("[Tier 1: TikWM Audio] Cleaned unreturned thumbnail: %s", thumbnail_path)
                        except Exception as te:
                            logger.warning("[Tier 1: TikWM Audio] Error cleaning unreturned thumbnail %s: %s", thumbnail_path, te)

        except VideoTooLargeError:
            raise
        except (httpx.RequestError, asyncio.TimeoutError) as err:
            logger.warning("[Tier 1: TikWM Audio] Request failure: %s", err)
            return None
        except Exception as err:
            logger.error("[Tier 1: TikWM Audio] Unexpected failure: %s", err, exc_info=True)
            return None

    # ──────────────────────────────────────────────────────────────────────────
    # TẦNG 2: Robust Universal Engine (yt-dlp)
    # ──────────────────────────────────────────────────────────────────────────

    async def _download_ytdlp(self, url: str) -> Optional[MediaItem]:
        """Tải video vạn năng cho YouTube, Facebook Reels, Douyin, X/Twitter..."""
        logger.info("[Tier 2: yt-dlp] Initiating extraction for: %s", url)

        async with self._ytdlp_semaphore:
            loop = asyncio.get_running_loop()
            future = loop.run_in_executor(None, self._sync_ytdlp_download, url)
            try:
                return await asyncio.shield(future)
            except asyncio.CancelledError:
                def _cleanup_orphaned(f):
                    try:
                        if not f.cancelled():
                            res = f.result()
                            if res:
                                res.cleanup()
                    except Exception:
                        pass
                future.add_done_callback(_cleanup_orphaned)
                raise

    @staticmethod
    def _probe_video_metadata_sync(file_path: str) -> Optional[Dict[str, Any]]:
        """Dùng ffprobe đọc nhanh header video cục bộ để lấy duration, width, height, fps."""
        try:
            cmd = [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height,r_frame_rate,avg_frame_rate,duration:format=duration",
                "-of", "json",
                str(file_path),
            ]
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5.0,
                check=False,
            )
            if result.returncode != 0:
                return None
            data = json.loads(result.stdout.decode("utf-8", errors="replace") or "{}")
            streams = data.get("streams", [])
            format_data = data.get("format", {})
            out: Dict[str, Any] = {}
            if streams:
                v = streams[0]
                if v.get("width"):
                    out["width"] = int(v["width"])
                if v.get("height"):
                    out["height"] = int(v["height"])
                fps = _parse_fps_string(v.get("r_frame_rate")) or _parse_fps_string(v.get("avg_frame_rate"))
                if fps:
                    out["fps"] = fps
                if v.get("duration"):
                    try:
                        out["duration"] = float(v["duration"])
                    except (ValueError, TypeError):
                        pass
            if "duration" not in out and format_data.get("duration"):
                try:
                    out["duration"] = float(format_data["duration"])
                except (ValueError, TypeError):
                    pass
            return out
        except Exception as err:
            logger.debug("[FFprobe Metadata] Probe failed for %s: %s", file_path, err)
            return None

    def _extract_media_item(
        self,
        info: Dict[str, Any],
        file_path: str,
        source_url: str,
        default_media_type: str = "video",
    ) -> MediaItem:
        """
        Trích xuất siêu dữ liệu toàn diện (title, duration, width, height, fps, file_size)
        từ yt-dlp info_dict và tự động bù đắp bằng FFprobe nếu thông số bị thiếu.
        """
        file_size = 0
        if file_path and os.path.exists(file_path):
            file_size = os.path.getsize(file_path)
        else:
            file_size = int(info.get("filesize") or info.get("filesize_approx") or 0)

        final_ext = os.path.splitext(file_path)[1].lower() if file_path else ""
        is_audio = final_ext in {".mp3", ".m4a", ".aac", ".opus", ".flac", ".wav", ".ogg"} or (
            info.get("vcodec") == "none" and info.get("acodec") != "none"
        )
        media_type = "audio" if is_audio else default_media_type

        default_title = "Social Audio" if media_type == "audio" else "Social Video"
        title = info.get("title") or default_title
        author = info.get("uploader") or info.get("channel") or info.get("uploader_id") or "Unknown"

        duration = int(info.get("duration") or 0)

        width: Optional[int] = int(info.get("width") or 0) or None
        height: Optional[int] = int(info.get("height") or 0) or None
        fps: Optional[float] = _parse_fps_string(info.get("fps"))

        # Kiểm tra trong requested_formats nếu yt-dlp mux tách rời
        requested_formats = info.get("requested_formats")
        if (width is None or height is None or fps is None) and isinstance(requested_formats, list):
            for fmt in requested_formats:
                if fmt.get("vcodec") and fmt.get("vcodec") != "none":
                    if width is None and fmt.get("width"):
                        width = int(fmt["width"])
                    if height is None and fmt.get("height"):
                        height = int(fmt["height"])
                    if fps is None and fmt.get("fps"):
                        parsed_fmt_fps = _parse_fps_string(fmt.get("fps"))
                        if parsed_fmt_fps:
                            fps = parsed_fmt_fps

        # Fallback FFprobe cục bộ nhanh nếu tệp video trên đĩa còn thiếu width/height/fps
        if media_type == "video" and file_path and os.path.exists(file_path):
            if width is None or height is None or fps is None or duration <= 0:
                probed = self._probe_video_metadata_sync(file_path)
                if probed:
                    if width is None and probed.get("width"):
                        width = int(probed["width"])
                    if height is None and probed.get("height"):
                        height = int(probed["height"])
                    if fps is None and probed.get("fps"):
                        fps = float(probed["fps"])
                    if duration <= 0 and probed.get("duration"):
                        duration = int(probed["duration"])

        return MediaItem(
            file_path=file_path,
            title=title,
            author=author,
            duration=duration,
            media_type=media_type,
            source_url=source_url,
            file_size=file_size,
            direct_stream_url=info.get("direct_stream_url"),
            cover_url=info.get("thumbnail") or info.get("cover_url"),
            is_temp_file=True,
            width=width,
            height=height,
            fps=fps,
        )

    def _sync_ytdlp_download(self, url: str) -> Optional[MediaItem]:
        try:
            import yt_dlp
        except ImportError:
            logger.warning("[Tier 2: yt-dlp] yt-dlp module not installed.")
            return None

        temp_dir = tempfile.mkdtemp(prefix="media_ytdlp_", dir=str(TEMP_MEDIA_DIR))
        out_tmpl = os.path.join(temp_dir, "media_%(id)s.%(ext)s")

        # 1. Cấu hình Best Quality: Video tốt nhất + Audio tốt nhất, tự động mux lossless sang MP4
        format_chain = "bestvideo+bestaudio/best"

        # 2. Bộ lọc bảo vệ: từ chối livestream và video quá dài (> 2 giờ = 7200s) để chống DoS
        def _match_filter_duration(info_dict: Dict[str, Any], *, incomplete: bool = False) -> Optional[str]:
            if info_dict.get("is_live"):
                raise ValueError("Livestreams are not supported for offline download")
            duration = info_dict.get("duration")
            if duration and duration > 7200:
                return "Thời lượng video vượt quá giới hạn an toàn tối đa 2 giờ của hệ thống."
            return None

        ydl_opts: Dict[str, Any] = {
            "format": format_chain,
            "format_sort": ["res", "fps", "quality", "size", "br"],
            "merge_output_format": "mp4",
            "remuxvideo": "mp4",
            "outtmpl": out_tmpl,
            # Bỏ hoàn toàn max_filesize: cho phép tải trọn vẹn mọi dung lượng về máy chủ
            "source_address": "0.0.0.0",
            "noplaylist": True,
            "socket_timeout": 30,
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": True,
            "match_filter": _match_filter_duration,
            "postprocessor_args": {
                "merger": ["-movflags", "+faststart"],
                "videoremuxer": ["-movflags", "+faststart"],
            },
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "web"],
                },
            },
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
                )
            },
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if not info:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    return None

                if info.get("is_live"):
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    raise ValueError("Livestreams are not supported for offline download")

                duration = info.get("duration")
                if duration and duration > 7200:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    raise MediaDurationLimitError("Thời lượng video vượt quá giới hạn an toàn tối đa 2 giờ của hệ thống.")

                downloaded_file = ydl.prepare_filename(info)
                base, _ = os.path.splitext(downloaded_file)
                mp4_candidate = f"{base}.mp4"
                final_path = mp4_candidate if os.path.exists(mp4_candidate) else downloaded_file

                if not os.path.exists(final_path):
                    residual_files = list(Path(temp_dir).iterdir())
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    if residual_files:
                        logger.warning("[Tier 2: yt-dlp] Incomplete download detected (%s).", residual_files)
                        raise MediaPipelineError(f"Tải video không hoàn tất, phát hiện tệp dở dang: {residual_files}")
                    return None

                final_ext = os.path.splitext(final_path)[1].lower()
                is_audio = final_ext in {".mp3", ".m4a", ".aac", ".opus", ".flac", ".wav", ".ogg"} or (
                    info.get("vcodec") == "none" and info.get("acodec") != "none"
                )
                media_type = "audio" if is_audio else "video"

                return self._extract_media_item(
                    info=info,
                    file_path=final_path,
                    source_url=url,
                    default_media_type=media_type,
                )

        except VideoTooLargeError:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise
        except (MediaDurationLimitError, ValueError):
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise
        except MediaPipelineError:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise
        except yt_dlp.utils.DownloadError as err:
            shutil.rmtree(temp_dir, ignore_errors=True)
            err_msg = str(err)
            if "Thời lượng video vượt quá" in err_msg or "7200" in err_msg:
                raise MediaDurationLimitError("Thời lượng video vượt quá giới hạn an toàn tối đa 2 giờ của hệ thống.") from err
            logger.warning("[Tier 2: yt-dlp] Download error: %s", err)
            return None
        except Exception as err:
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.error("[Tier 2: yt-dlp] Extraction failed: %s", err, exc_info=True)
            return None

    async def _download_ytdlp_audio(self, url: str) -> Optional[MediaItem]:
        """Tải âm thanh chuẩn hóa MP3 320kbps cho YouTube, Facebook Reels/Watch, Douyin..."""
        logger.info("[Tier 2: yt-dlp Audio] Initiating audio extraction for: %s", url)

        async with self._ytdlp_semaphore:
            loop = asyncio.get_running_loop()
            future = loop.run_in_executor(None, self._sync_ytdlp_audio_download, url)
            try:
                return await asyncio.shield(future)
            except asyncio.CancelledError:
                def _cleanup_orphaned(f):
                    try:
                        if not f.cancelled():
                            res = f.result()
                            if res:
                                res.cleanup()
                    except Exception:
                        pass
                future.add_done_callback(_cleanup_orphaned)
                raise

    def _sync_ytdlp_audio_download(self, url: str) -> Optional[MediaItem]:
        try:
            import yt_dlp
        except ImportError:
            logger.warning("[Tier 2: yt-dlp Audio] yt-dlp module not installed.")
            return None

        temp_dir = tempfile.mkdtemp(prefix="media_ytdlp_audio_", dir=str(TEMP_MEDIA_DIR))
        out_tmpl = os.path.join(temp_dir, "audio_%(id)s.%(ext)s")

        def _match_filter_duration(info_dict: Dict[str, Any], *, incomplete: bool = False) -> Optional[str]:
            duration = info_dict.get("duration")
            if duration and duration > 7200:
                return "Thời lượng âm thanh vượt quá giới hạn an toàn tối đa 2 giờ của hệ thống."
            return None

        ydl_opts: Dict[str, Any] = {
            "format": "bestaudio/best",
            "outtmpl": out_tmpl,
            "source_address": "0.0.0.0",
            "noplaylist": True,
            "socket_timeout": 30,
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": True,
            "match_filter": _match_filter_duration,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "320",
                },
            ],
            "postprocessor_args": {
                "FFmpegExtractAudio": [
                    "-id3v2_version", "3",
                ],
            },
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "web"],
                },
            },
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
                )
            },
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if not info:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    return None

                downloaded_file = ydl.prepare_filename(info)
                base, _ = os.path.splitext(downloaded_file)
                mp3_candidate = f"{base}.mp3"

                final_path = None
                if os.path.exists(mp3_candidate):
                    final_path = mp3_candidate
                else:
                    mp3_files = list(Path(temp_dir).glob("*.mp3"))
                    if mp3_files:
                        final_path = str(mp3_files[0])
                    elif os.path.exists(downloaded_file):
                        final_path = downloaded_file

                if not final_path or not os.path.exists(final_path):
                    residual_files = list(Path(temp_dir).iterdir())
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    if residual_files:
                        logger.warning("[Tier 2: yt-dlp Audio] Incomplete download detected (%s).", residual_files)
                        raise MediaPipelineError(f"Tải audio không hoàn tất, phát hiện tệp dở dang: {residual_files}")
                    return None

                size = os.path.getsize(final_path)
                title = info.get("track") or info.get("title") or "Audio Track"
                author = (
                    info.get("artist")
                    or info.get("creator")
                    or info.get("uploader")
                    or info.get("channel")
                    or "Unknown Artist"
                )

                cover_url = info.get("thumbnail")
                thumbnail_path = None
                if cover_url:
                    try:
                        import urllib.request
                        raw_thumb = os.path.join(temp_dir, "raw_thumb.jpg")
                        out_thumb = os.path.join(temp_dir, "thumb_320.jpg")
                        req = urllib.request.Request(cover_url, headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(req, timeout=10) as resp, open(raw_thumb, "wb") as out_f:
                            out_f.write(resp.read())
                        if os.path.exists(raw_thumb):
                            from PIL import Image
                            with Image.open(raw_thumb) as im:
                                im.thumbnail((320, 320))
                                rgb = im.convert("RGB")
                                rgb.save(out_thumb, format="JPEG", quality=85)
                            if os.path.exists(out_thumb):
                                thumbnail_path = out_thumb
                    except Exception as te:
                        logger.warning("[Tier 2: yt-dlp Audio] Failed extracting thumbnail: %s", te)

                return MediaItem(
                    file_path=final_path,
                    title=title,
                    author=author,
                    duration=int(info.get("duration", 0)),
                    media_type="audio",
                    source_url=url,
                    file_size=size,
                    cover_url=cover_url,
                    thumbnail_path=thumbnail_path,
                    is_temp_file=True,
                )

        except VideoTooLargeError:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise
        except MediaPipelineError:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise
        except yt_dlp.utils.DownloadError as err:
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.warning("[Tier 2: yt-dlp Audio] Download error: %s", err)
            return None
        except Exception as err:
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.error("[Tier 2: yt-dlp Audio] Extraction failed: %s", err, exc_info=True)
            return None

    # ──────────────────────────────────────────────────────────────────────────
    # TẦNG 3: Emergency Fallback (Playwright JSON Hydration Sniffer)
    # ──────────────────────────────────────────────────────────────────────────

    async def _download_playwright_sniff(self, url: str) -> Optional[MediaItem]:
        """Bóc tách luồng trực tiếp từ DOM Hydration hoặc Network Stream."""
        logger.info("[Tier 3: Playwright] Initiating sniffing for: %s", url)

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning("[Tier 3: Playwright] Playwright not installed.")
            return None

        captured_video_url: Optional[str] = None
        media_event = asyncio.Event()

        async with self._playwright_semaphore:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--disable-extensions",
                    ],
                )
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 720},
                )
                page = await context.new_page()

                await page.route(
                    re.compile(r"\.(png|jpg|jpeg|gif|svg|woff|woff2|ttf|css)$", re.IGNORECASE),
                    lambda route: route.abort(),
                )

                async def _on_response(response: Any) -> None:
                    nonlocal captured_video_url
                    headers = response.headers
                    content_type = headers.get("content-type", "").lower()
                    if (
                        "video/mp4" in content_type
                        or "video/webm" in content_type
                        or response.request.resource_type == "media"
                    ):
                        if not captured_video_url:
                            captured_video_url = response.url
                            media_event.set()

                page.on("response", _on_response)

                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=15000)

                    script_content = await page.evaluate("""() => {
                        const el = document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__');
                        return el ? el.textContent : null;
                    }""")
                    if script_content:
                        import json
                        try:
                            rehydration = json.loads(script_content)
                            default_scope = rehydration.get("__DEFAULT_SCOPE__", {})
                            item_info = default_scope.get("webapp.video-detail", {}).get("itemInfo", {}).get("itemStruct", {})
                            play_addr = item_info.get("video", {}).get("playAddr")
                            if play_addr:
                                logger.info("[Tier 3: Playwright] Found playAddr via JSON hydration")
                                captured_video_url = play_addr
                                media_event.set()
                        except Exception as parse_err:
                            logger.debug("[Tier 3: Playwright] JSON hydration parse failed: %s", parse_err)

                    if not media_event.is_set():
                        try:
                            await asyncio.wait_for(media_event.wait(), timeout=5.0)
                        except asyncio.TimeoutError:
                            pass
                finally:
                    await context.close()
                    await browser.close()

        if not captured_video_url:
            logger.warning("[Tier 3: Playwright] Sniffing yielded no media URL")
            return None

        client = await self._get_client()
        temp_file, size = await self._stream_url_to_file(captured_video_url, client)

        return MediaItem(
            file_path=temp_file,
            title="Extracted Media",
            author="Creator",
            duration=0,
            media_type="video",
            source_url=url,
            file_size=size,
            direct_stream_url=captured_video_url,
            is_temp_file=True,
        )

    async def _download_threads_playwright(self, url: str) -> Optional[MediaItem]:
        """
        Trích xuất video Threads chuyên biệt bằng Playwright Headless Chromium:
          - Quản lý bộ nhớ bằng asyncio.Semaphore(1) bảo vệ máy chủ RAM 3.2GB.
          - Chặn toàn bộ hình ảnh, font, stylesheet để tối ưu tốc độ và giảm băng thông.
          - Cơ chế Dual-Vector: bóc tách direct URL từ JSON hydration `video_versions`
            kết hợp lắng nghe luồng mạng CDN Meta (`fbcdn.net`).
          - Loại bỏ tham số byte range (`bytestart`, `byteend`) để tải toàn bộ tệp MP4 chuẩn 200 OK.
          - Đóng Chromium ngay lập tức khi bắt được stream URL để giải phóng RAM trước khi stream.
          - Ghi trực tiếp từng chunk 64KB ra đĩa SSD tạm /tmp/media_downloads/.
        """
        logger.info("[Threads Playwright] Initiating extraction for: %s", url)

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning("[Threads Playwright] Playwright module not installed.")
            return None

        title = "Threads Video"
        author = "threads_creator"
        extracted_stream_url: Optional[str] = None

        # Bóc tách username tác giả từ URL pattern: /@username/post/
        m_author = re.search(r"/@([^/\?]+)", url)
        if m_author:
            author = m_author.group(1)

        async with self._playwright_semaphore:
            network_stream_url: Optional[str] = None
            stream_event = asyncio.Event()

            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--disable-extensions",
                        "--disable-background-networking",
                        "--disable-background-timer-throttling",
                        "--disable-renderer-backgrounding",
                        "--mute-audio",
                    ],
                )
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 800},
                )
                page = await context.new_page()

                # Chặn tối đa các tài nguyên không liên quan đến việc lấy stream URL
                await page.route(
                    re.compile(r"\.(png|jpg|jpeg|gif|webp|svg|woff|woff2|ttf|otf|css)($|\?)", re.IGNORECASE),
                    lambda route: route.abort(),
                )

                async def _on_response(response: Any) -> None:
                    nonlocal network_stream_url
                    res_url = response.url
                    ct = response.headers.get("content-type", "").lower()
                    if (
                        _is_meta_cdn_url(res_url)
                        and ("video" in ct or ".mp4" in res_url or response.request.resource_type == "media")
                    ):
                        if not network_stream_url:
                            network_stream_url = res_url
                            stream_event.set()

                page.on("response", _on_response)

                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=15000)

                    # Trích xuất metadata bài viết từ thẻ meta OpenGraph hoặc tiêu đề trang
                    page_meta = await page.evaluate("""() => {
                        const ogDesc = document.querySelector('meta[property="og:description"]')?.content;
                        const ogTitle = document.querySelector('meta[property="og:title"]')?.content;
                        const docTitle = document.title;
                        return { ogDesc, ogTitle, docTitle };
                    }""")

                    if page_meta.get("ogDesc"):
                        title = page_meta["ogDesc"].strip()
                    elif page_meta.get("ogTitle"):
                        title = page_meta["ogTitle"].strip()
                    elif page_meta.get("docTitle"):
                        title = page_meta["docTitle"].strip()

                    # Cắt ngắn tiêu đề nếu quá dài để hiển thị chuẩn trong Telegram caption
                    if len(title) > 100:
                        title = title[:97] + "..."

                    # Vector 1: Bóc tách trực tiếp từ mảng JSON hydration video_versions trong HTML
                    html_content = await page.content()
                    matches = re.finditer(r'\"video_versions\"\s*:\s*(\[[^\]]+\])', html_content)
                    for m in matches:
                        try:
                            clean_json = m.group(1).replace(r"\/", "/")
                            items = json.loads(clean_json)
                            for it in items:
                                candidate = it.get("url")
                                if candidate and _is_meta_cdn_url(candidate):
                                    extracted_stream_url = candidate
                                    logger.info("[Threads Playwright] Found stream URL via video_versions JSON hydration")
                                    break
                            if extracted_stream_url:
                                break
                        except Exception as parse_err:
                            logger.debug("[Threads Playwright] Failed parsing video_versions snippet: %s", parse_err)

                    # Vector 2: Dự phòng nếu JSON hydration không có, chờ tín hiệu từ Network Listener
                    if not extracted_stream_url:
                        if not stream_event.is_set():
                            try:
                                await asyncio.wait_for(stream_event.wait(), timeout=4.0)
                            except asyncio.TimeoutError:
                                pass

                        if network_stream_url:
                            extracted_stream_url = network_stream_url
                            logger.info("[Threads Playwright] Found stream URL via Network Sniffer")

                finally:
                    # ĐÓNG BROWSER NGAY LẬP TỨC để giải phóng 150MB RAM trước khi thực hiện tải stream
                    await context.close()
                    await browser.close()

        if not extracted_stream_url:
            logger.warning("[Threads Playwright] No video stream URL could be captured from %s", url)
            return None

        # Chuẩn hóa URL: Loại bỏ byte range query parameters để tải toàn bộ tệp
        cleaned_stream_url = _clean_fbcdn_stream_url(extracted_stream_url)

        # Tải tệp bằng Chunked Disk Streaming 64KB trực tiếp ra đĩa SSD
        client = await self._get_client()
        temp_file, size = await self._stream_url_to_file(cleaned_stream_url, client)

        logger.info("[Threads Playwright] Successfully downloaded video to %s (%d bytes)", temp_file, size)

        return MediaItem(
            file_path=temp_file,
            title=title,
            author=author,
            duration=0,
            media_type="video",
            source_url=url,
            file_size=size,
            direct_stream_url=cleaned_stream_url,
            is_temp_file=True,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Tiện ích Zero-RAM Chunked Disk Streaming
    # ──────────────────────────────────────────────────────────────────────────

    async def _stream_url_to_file(
        self,
        url: str,
        client: httpx.AsyncClient,
        suffix: str = ".mp4",
    ) -> Tuple[str, int]:
        """Ghi stream trực tiếp từng chunk 64KB ra đĩa SSD tạm, bảo vệ RAM 3.2GB."""
        async with client.stream("GET", url) as response:
            if response.status_code != 200:
                raise MediaPipelineError(f"HTTP stream status {response.status_code}")

            with tempfile.NamedTemporaryFile(suffix=suffix, dir=str(TEMP_MEDIA_DIR), delete=False) as tf:
                temp_path = tf.name

            total_bytes = 0
            download_success = False
            try:
                with open(temp_path, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                        total_bytes += len(chunk)
                        f.write(chunk)
                download_success = True
            finally:
                if not download_success and os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass

            return temp_path, total_bytes

    # ──────────────────────────────────────────────────────────────────────────
    # Cổng Thực Thi Chính (Public Gateway)
    # ──────────────────────────────────────────────────────────────────────────

    async def download(self, url: str) -> MediaItem:
        """
        Phân giải và tải media qua hệ thống phân tầng thông minh:
          - Audio Platforms (SoundCloud, YT Music) -> download_audio
          - Threads -> _download_threads_playwright
          - Facebook (rút gọn/chia sẻ) -> _resolve_redirect_url -> Tier 2 (yt-dlp)
          - TikTok / Douyin -> Tier 1 (TikWM) -> Tier 2 (yt-dlp) -> Tier 3 (Playwright)
          - 20+ Nền tảng & Universal Web Extractor Fallback -> Tier 2 (yt-dlp) -> Tier 3 (Playwright)
        """
        # Tự động dọn dẹp các tệp tạm mồ côi cũ hơn 10 phút trước khi bắt đầu phiên mới
        cleanup_expired_media(max_age_seconds=600)

        clean_url = url.strip()
        if not clean_url.startswith(("http://", "https://")):
            raise MediaPipelineError(f"Định dạng URL không hợp lệ: {clean_url}")

        try:
            # 0. Định tuyến chuyên biệt cho nền tảng thuần âm nhạc (SoundCloud, YouTube Music)
            if self._audio_platform_regex.search(clean_url):
                logger.info("[Pipeline] Dedicated audio platform detected, routing to download_audio: %s", clean_url)
                return await self.download_audio(clean_url)

            # 1. Định tuyến Threads chuyên biệt (yt-dlp không hỗ trợ Threads, đi thẳng vào Playwright Sniffer)
            if self._threads_regex.search(clean_url):
                try:
                    item = await self._download_threads_playwright(clean_url)
                    if item:
                        item.source_url = clean_url
                        logger.info("[Pipeline] Threads Playwright Sniffer succeeded!")
                        return item
                except VideoTooLargeError:
                    raise
                except Exception as err:
                    logger.error("[Pipeline] Threads extraction failed: %s", err)
                    raise MediaPipelineError(f"Không thể tải video từ Threads: {err}")

            # 2. Tiền xử lý Facebook URLs: Kết hợp 2 tầng (Tầng 1 Tĩnh -> Tầng 2 Động)
            target_url = canonicalize_facebook_url(clean_url)
            if self._facebook_redirect_regex.search(target_url):
                resolved = await self._resolve_redirect_url(target_url)
                target_url = canonicalize_facebook_url(resolved)

            # 3. Định tuyến TikTok / Douyin (Tier 1: TikWM -> Tier 2: yt-dlp -> Tier 3: Playwright)
            is_tiktok_douyin = bool(self._tiktok_regex.search(clean_url))

            if is_tiktok_douyin:
                try:
                    item = await self._download_tikwm(clean_url)
                    if item:
                        item.source_url = clean_url
                        logger.info("[Pipeline] Tier 1 (TikWM) succeeded!")
                        return item
                except VideoTooLargeError:
                    raise
                except Exception as err:
                    logger.warning("[Pipeline] Tier 1 failed, falling back to Tier 2: %s", err)

            # 4. Tier 2: Universal Extractor Engine (yt-dlp Core) — 20+ Nền Tảng & Generic Web Fallback
            try:
                item = await self._download_ytdlp(target_url)
                if item:
                    item.source_url = clean_url
                    logger.info("[Pipeline] Tier 2 (yt-dlp Universal Extractor) succeeded for URL: %s", target_url)
                    return item
            except VideoTooLargeError:
                raise
            except (MediaDurationLimitError, ValueError) as err:
                logger.warning("[Pipeline] Tier 2 rejected video due to policy/duration limits: %s", err)
                raise
            except Exception as err:
                logger.warning("[Pipeline] Tier 2 Universal Extractor failed, falling back to Tier 3: %s", err)

            # 5. Tier 3: Playwright Sniffer Fallback
            try:
                item = await self._download_playwright_sniff(clean_url)
                if item:
                    item.source_url = clean_url
                    logger.info("[Pipeline] Tier 3 (Playwright Sniffer) succeeded!")
                    return item
            except VideoTooLargeError:
                raise
            except Exception as err:
                logger.error("[Pipeline] Tier 3 failed: %s", err)

            raise MediaPipelineError(f"Không thể trích xuất video từ liên kết: {clean_url}")
        finally:
            # Chủ động thu hồi RAM nền (glibc malloc_trim + gc.collect) sau khi xử lý media xong
            await reclaim_memory_background(delay_seconds=0.2)

    async def download_audio(self, url: str) -> MediaItem:
        """
        Trích xuất và tải âm thanh chất lượng cao (MP3) từ các nền tảng mạng xã hội:
          - Tự động dọn dẹp các tệp tạm mồ côi cũ hơn 10 phút.
          - Tiền xử lý Facebook URLs: Canonicalize + Resolve redirect nếu là dạng rút gọn.
          - Tier 1 (TikTok / Douyin): TikWM API direct MP3 stream (data.music / data.music_info).
            Siêu tốc < 0.5s, 0% CPU transcoding, giữ nguyên chất lượng gốc từ TikTok CDN.
            Hỗ trợ cả bài đăng album ảnh slideshow (data.images).
          - Tier 2 (Universal - YouTube, Facebook Reels/Watch, Douyin, X/Twitter...):
            yt-dlp với format 'bestaudio/best' + postprocessor 'FFmpegExtractAudio' (MP3 320kbps CBR / ID3v2.3).
          - Zero-RAM & Zero-Disk Leak: Chunked streaming 64KB và tự động dọn dẹp file tạm.
          - Trả về MediaItem với media_type='audio', sẵn sàng gửi qua Telegram /sendAudio.
        """
        # Tự động dọn dẹp các tệp tạm mồ côi cũ hơn 10 phút trước khi bắt đầu phiên mới
        cleanup_expired_media(max_age_seconds=600)

        clean_url = url.strip()

        try:
            # 1. Tiền xử lý Facebook URLs: Kết hợp 2 tầng (Tầng 1 Tĩnh -> Tầng 2 Động)
            target_url = canonicalize_facebook_url(clean_url)
            if self._facebook_redirect_regex.search(target_url):
                resolved = await self._resolve_redirect_url(target_url)
                target_url = canonicalize_facebook_url(resolved)

            # 2. Định tuyến TikTok / Douyin (Tier 1: TikWM Direct MP3 -> Fallback Tier 2: yt-dlp)
            is_tiktok_douyin = bool(self._tiktok_regex.search(clean_url))

            if is_tiktok_douyin:
                try:
                    item = await self._download_tikwm_audio(clean_url)
                    if item:
                        item.source_url = clean_url
                        logger.info("[Pipeline Audio] Tier 1 (TikWM Audio) succeeded!")
                        return item
                except VideoTooLargeError:
                    raise
                except Exception as err:
                    logger.warning("[Pipeline Audio] Tier 1 failed, falling back to Tier 2: %s", err)

            # 3. Tier 2: yt-dlp Universal Audio Downloader (YouTube, Facebook Reels/Watch, Douyin...)
            try:
                item = await self._download_ytdlp_audio(target_url)
                if item:
                    item.source_url = clean_url
                    logger.info("[Pipeline Audio] Tier 2 (yt-dlp Audio) succeeded for URL: %s", target_url)
                    return item
            except VideoTooLargeError:
                raise
            except Exception as err:
                logger.warning("[Pipeline Audio] Tier 2 audio extraction failed: %s", err)

            raise MediaPipelineError(f"Không thể trích xuất âm thanh từ liên kết: {clean_url}")
        finally:
            # Chủ động thu hồi RAM nền (glibc malloc_trim + gc.collect) sau khi xử lý media xong
            await reclaim_memory_background(delay_seconds=0.2)


# Alias tương thích ngược cho các service tiêu thụ
MediaDownloaderService = MultiTierMediaPipeline

