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
    is_temp_file: bool = True

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
            client = await self._get_client()
            headers = {
                "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
            }
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

        # 2. Bộ lọc bảo vệ: chỉ từ chối video quá dài (> 2 giờ = 7200s) để chống DoS
        def _match_filter_duration(info_dict: Dict[str, Any], *, incomplete: bool = False) -> Optional[str]:
            duration = info_dict.get("duration")
            if duration and duration > 7200:
                return "Thời lượng video vượt quá giới hạn an toàn tối đa 2 giờ của hệ thống."
            return None

        ydl_opts: Dict[str, Any] = {
            "format": format_chain,
            "merge_output_format": "mp4",
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
                mp4_candidate = f"{base}.mp4"
                final_path = mp4_candidate if os.path.exists(mp4_candidate) else downloaded_file

                if not os.path.exists(final_path):
                    residual_files = list(Path(temp_dir).iterdir())
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    if residual_files:
                        logger.warning("[Tier 2: yt-dlp] Incomplete download detected (%s).", residual_files)
                        raise MediaPipelineError(f"Tải video không hoàn tất, phát hiện tệp dở dang: {residual_files}")
                    return None

                size = os.path.getsize(final_path)
                return MediaItem(
                    file_path=final_path,
                    title=info.get("title") or "Social Video",
                    author=info.get("uploader") or info.get("channel") or "Unknown",
                    duration=int(info.get("duration", 0)),
                    media_type="video",
                    source_url=url,
                    file_size=size,
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
            logger.warning("[Tier 2: yt-dlp] Download error: %s", err)
            return None
        except Exception as err:
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.error("[Tier 2: yt-dlp] Extraction failed: %s", err, exc_info=True)
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
                        ("fbcdn.net" in res_url or "cdninstagram.com" in res_url)
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
                                if candidate and ("fbcdn.net" in candidate or "cdninstagram.com" in candidate):
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

    async def _stream_url_to_file(self, url: str, client: httpx.AsyncClient) -> Tuple[str, int]:
        """Ghi stream trực tiếp từng chunk 64KB ra đĩa SSD tạm, bảo vệ RAM 3.2GB."""
        async with client.stream("GET", url) as response:
            if response.status_code != 200:
                raise MediaPipelineError(f"HTTP stream status {response.status_code}")

            with tempfile.NamedTemporaryFile(suffix=".mp4", dir=str(TEMP_MEDIA_DIR), delete=False) as tf:
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
          - Threads -> _download_threads_playwright
          - Facebook (rút gọn/chia sẻ) -> _resolve_redirect_url -> Tier 2 (yt-dlp)
          - TikTok / Douyin -> Tier 1 (TikWM) -> Tier 2 (yt-dlp) -> Tier 3 (Playwright)
          - YouTube, Facebook và các nền tảng khác -> Tier 2 (yt-dlp) -> Tier 3 (Playwright)
        """
        # Tự động dọn dẹp các tệp tạm mồ côi cũ hơn 10 phút trước khi bắt đầu phiên mới
        cleanup_expired_media(max_age_seconds=600)

        clean_url = url.strip()

        try:
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

            # 4. Tier 2: yt-dlp Universal Downloader (YouTube, Facebook Reels/Watch, Douyin...)
            try:
                item = await self._download_ytdlp(target_url)
                if item:
                    item.source_url = clean_url
                    logger.info("[Pipeline] Tier 2 (yt-dlp) succeeded for URL: %s", target_url)
                    return item
            except VideoTooLargeError:
                raise
            except Exception as err:
                logger.warning("[Pipeline] Tier 2 failed, falling back to Tier 3: %s", err)

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
