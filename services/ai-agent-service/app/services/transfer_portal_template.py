"""
transfer_portal_template.py — High-Speed Web Drop Portal HTML Template Generator.

Provides ultra-lightweight (< 30KB, uncompressed; ~5KB gzipped), 100% self-contained,
zero-CDN, responsive HTML5/CSS3/Vanilla JS templates for:
  1. Upload Dropzone: Drag-and-drop, large files, XHR dynamic % progress, instantaneous speed, ETA, cancel.
  2. Download Portal: File metadata, visual TTL 24h countdown, high-speed download, dual LAN/WAN links, copy.
  3. Multi-Format In-Browser Preview:
     - Video (MP4/WebM/MOV) with playsinline, preload="metadata" & HTTP 206 seek.
     - Audio (MP3/WAV/AAC) with native player.
     - Image (JPG/PNG/WebP/GIF) with click-to-zoom Lightbox.
     - PDF Document with embedded viewer & fullscreen fallback for iOS Safari.
     - Generic Archive/File cards with clean iconography.
  4. 404 / Expired Session page with Zero-Disk-Leak explanation.
  5. Automatic Dark/Light mode + manual theme toggle, touch targets >= 44px for iPhone/iPad.
"""

from __future__ import annotations

import html
import json
import mimetypes
from pathlib import Path
import time
from typing import Any, Dict, Optional

# Minimalist, crisp inline SVGs for zero-CDN offline operations
ICONS = {
    "bolt": '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>',
    "upload_cloud": '<svg class="icon icon-lg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/><path d="M12 13v6"/><path d="m15 16-3-3-3 3"/></svg>',
    "download": '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>',
    "copy": '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>',
    "check": '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
    "clock": '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
    "wifi": '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 13a10 10 0 0 1 14 0"/><path d="M8.5 16.5a5 5 0 0 1 7 0"/><path d="M2 8.82a15 15 0 0 1 20 0"/><line x1="12" y1="20" x2="12.01" y2="20"/></svg>',
    "globe": '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>',
    "sun": '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/></svg>',
    "moon": '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/></svg>',
    "video": '<svg class="icon icon-file" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m22 8-6 4 6 4V8Z"/><rect width="14" height="12" x="2" y="6" rx="2" ry="2"/></svg>',
    "audio": '<svg class="icon icon-file" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>',
    "image": '<svg class="icon icon-file" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/></svg>',
    "pdf": '<svg class="icon icon-file" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 12h4"/><path d="M10 16h4"/></svg>',
    "archive": '<svg class="icon icon-file" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="5" x="2" y="3" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/></svg>',
    "file": '<svg class="icon icon-file" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><polyline points="14 2 14 8 20 8"/></svg>',
    "alert": '<svg class="icon icon-lg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
    "x": '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>',
}


def format_file_size(size_bytes: int) -> str:
    """Formats file size into human-readable Bytes, KB, MB, GB, TB string."""
    if size_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    b = float(size_bytes)
    for unit in units:
        if b < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(b)} B"
            return f"{b:.1f} {unit}"
        b /= 1024.0
    return f"{b:.1f} TB"


def get_media_category(filename: str, content_type: str = "") -> str:
    """Categorizes file into 'video', 'audio', 'image', 'pdf', 'archive', or 'file'."""
    ext = Path(filename).suffix.lower().lstrip(".")
    ct = (content_type or "").lower()

    if ext in ("mp4", "webm", "mov", "m4v", "mkv", "avi") or ct.startswith("video/"):
        return "video"
    if ext in ("mp3", "wav", "aac", "m4a", "ogg", "flac", "opus") or ct.startswith("audio/"):
        return "audio"
    if ext in ("jpg", "jpeg", "png", "gif", "webp", "svg", "bmp", "ico") or ct.startswith("image/"):
        return "image"
    if ext == "pdf" or "application/pdf" in ct:
        return "pdf"
    if ext in ("zip", "rar", "7z", "tar", "gz", "bz2", "xz", "iso", "dmg"):
        return "archive"
    return "file"


def render_not_found_html(token: str = "") -> str:
    """Renders a standalone 404 / Expired Session portal page."""
    safe_token = html.escape(token or "unknown")
    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
  <title>Phiên Không Tồn Tại — Tiểu Bảo Bảo</title>
  <style>
    :root {{
      --bg: #090d16;
      --card-bg: rgba(22, 30, 46, 0.92);
      --border: rgba(255, 255, 255, 0.12);
      --text: #f8fafc;
      --text-dim: #94a3b8;
      --accent: #00e5ff;
      --danger: #ef4444;
      --radius: 18px;
      --touch-min: 44px;
    }}
    @media (prefers-color-scheme: light) {{
      :root {{
        --bg: #f1f5f9;
        --card-bg: rgba(255, 255, 255, 0.95);
        --border: rgba(0, 0, 0, 0.1);
        --text: #0f172a;
        --text-dim: #64748b;
        --accent: #0284c7;
      }}
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      min-height: -webkit-fill-available;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 16px;
    }}
    .card {{
      width: 100%;
      max-width: 500px;
      background: var(--card-bg);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: 0 20px 45px rgba(0,0,0,0.35);
      padding: 32px 24px;
      text-align: center;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 16px;
    }}
    .icon-lg {{ width: 56px; height: 56px; stroke: var(--danger); }}
    h1 {{ font-size: 1.35rem; font-weight: 700; }}
    p {{ font-size: 0.9rem; color: var(--text-dim); line-height: 1.5; }}
    code {{ background: rgba(255,255,255,0.06); padding: 4px 8px; border-radius: 6px; font-size: 0.82rem; }}
    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: rgba(239, 68, 68, 0.12);
      color: var(--danger);
      padding: 6px 14px;
      border-radius: 999px;
      font-size: 0.8rem;
      font-weight: 600;
    }}
    .btn {{
      min-height: var(--touch-min);
      min-width: var(--touch-min);
      padding: 12px 24px;
      border-radius: 12px;
      font-size: 0.95rem;
      font-weight: 600;
      text-decoration: none;
      background: var(--accent);
      color: #000;
      border: none;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      margin-top: 8px;
    }}
  </style>
</head>
<body>
  <div class="card">
    {ICONS["alert"]}
    <span class="badge">404 — Không Tìm Thấy Phiên</span>
    <h1>Phiên Truyền Tệp Đã Hết Hạn</h1>
    <p>Phiên truyền với mã <code>{safe_token}</code> không tồn tại hoặc đã được tự động dọn sạch theo cơ chế <b>Zero-Disk Leak (TTL 24h)</b> của Tiểu Bảo Bảo để bảo vệ máy chủ.</p>
    <a href="javascript:history.back()" class="btn">Quay Lại</a>
  </div>
</body>
</html>"""


def render_transfer_portal_html(
    record: Optional[Any] = None,
    lan_url: str = "",
    wan_url: str = "",
    token: Optional[str] = None,
) -> str:
    """
    Renders the responsive, lightweight (< 30KB, Zero-CDN) Web Drop Portal HTML.
    Supports:
      - Upload Dropzone with XHR progress, speed, ETA, and cancellation.
      - Download Portal with real-time TTL countdown and in-browser preview (video/audio/image/pdf).
      - Dark/Light mode, touch target >= 44px, offline LAN ready.
    """
    if record is None:
        return render_not_found_html(token=token or "")

    # Extract record metadata safely
    effective_token = getattr(record, "token", "") or token or ""
    filename = getattr(record, "filename", "unnamed_file") or "unnamed_file"
    file_size = getattr(record, "file_size", 0) or 0
    content_type = getattr(record, "content_type", "") or ""
    state = getattr(record, "state", "pending_upload")
    mode = getattr(record, "mode", "upload")
    expires_at = getattr(record, "expires_at", time.time() + 86400)
    ttl_seconds = getattr(record, "ttl_seconds", 86400)
    one_time = bool(getattr(record, "one_time", False))

    effective_lan_url = lan_url or getattr(record, "lan_url", "")
    effective_wan_url = wan_url or getattr(record, "internet_url", "")

    # Fallback endpoint paths
    download_path = f"/api/ai/transfer/download/{effective_token}"
    upload_path = f"/api/ai/transfer/upload/{effective_token}"
    info_path = f"/api/ai/transfer/info/{effective_token}"

    category = get_media_category(filename, content_type)
    size_str = format_file_size(file_size)
    safe_filename = html.escape(filename)
    safe_token = html.escape(effective_token)

    # Initial display state: download mode if ready or has file size
    is_ready = (state == "ready") or (file_size > 0 and mode != "upload")
    initial_mode = "download" if is_ready else "upload"

    file_icon_svg = ICONS.get(category, ICONS["file"])

    # JSON configuration injected for client-side vanilla JS
    client_config = {
        "token": effective_token,
        "filename": filename,
        "fileSize": file_size,
        "contentType": content_type,
        "category": category,
        "state": state,
        "mode": initial_mode,
        "expiresAt": expires_at,
        "ttlSeconds": ttl_seconds,
        "oneTime": one_time,
        "downloadUrl": download_path,
        "uploadUrl": upload_path,
        "infoUrl": info_path,
        "lanUrl": effective_lan_url,
        "wanUrl": effective_wan_url,
    }
    client_json = json.dumps(client_config)

    # Multi-format preview initial markup for download mode
    preview_markup = ""
    if category == "video":
        preview_markup = f"""<div class="media-wrapper">
          <video controls playsinline preload="metadata" src="{download_path}" class="preview-media preview-video">
            Trình duyệt của bạn không hỗ trợ phát video trực tiếp.
          </video>
        </div>"""
    elif category == "audio":
        preview_markup = f"""<div class="media-wrapper audio-wrapper">
          <div class="audio-banner">{ICONS['audio']}<span>Phát Trực Tiếp Âm Thanh</span></div>
          <audio controls preload="metadata" src="{download_path}" class="preview-media preview-audio">
            Trình duyệt của bạn không hỗ trợ phát âm thanh trực tiếp.
          </audio>
        </div>"""
    elif category == "image":
        preview_markup = f"""<div class="media-wrapper image-wrapper" onclick="openLightbox(this)">
          <img src="{download_path}" alt="{safe_filename}" loading="lazy" class="preview-media preview-image">
          <div class="image-hint">Chạm để phóng to toàn màn hình</div>
        </div>"""
    elif category == "pdf":
        preview_markup = f"""<div class="media-wrapper pdf-wrapper">
          <iframe src="{download_path}#toolbar=0" class="preview-media preview-pdf" title="Xem trước PDF"></iframe>
          <a href="{download_path}" target="_blank" rel="noopener" class="btn btn-secondary pdf-btn">
            {ICONS['pdf']}<span>Mở Toàn Màn Hình Trong Tab Mới</span>
          </a>
        </div>"""
    elif category == "archive":
        preview_markup = f"""<div class="media-wrapper archive-wrapper">
          {ICONS['archive']}
          <div class="archive-info">Tệp nén lưu trữ — Sẵn sàng tải về giải nén</div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <title>Cổng Chuyển Tệp Siêu Tốc — {safe_filename}</title>
  <style>
    :root {{
      --bg: #090d16;
      --card-bg: rgba(22, 30, 46, 0.88);
      --card-border: rgba(255, 255, 255, 0.12);
      --card-shadow: 0 20px 45px rgba(0, 0, 0, 0.45);
      --text: #f8fafc;
      --text-dim: #94a3b8;
      --text-sub: #64748b;
      --accent: #00e5ff;
      --accent-glow: rgba(0, 229, 255, 0.22);
      --accent-grad: linear-gradient(135deg, #00e5ff 0%, #3b82f6 100%);
      --surface: rgba(255, 255, 255, 0.05);
      --surface-hover: rgba(255, 255, 255, 0.09);
      --success: #10b981;
      --success-glow: rgba(16, 185, 129, 0.2);
      --danger: #ef4444;
      --radius: 18px;
      --radius-sm: 12px;
      --touch-min: 44px;
    }}
    [data-theme="light"] {{
      --bg: #f1f5f9;
      --card-bg: rgba(255, 255, 255, 0.94);
      --card-border: rgba(0, 0, 0, 0.08);
      --card-shadow: 0 16px 36px rgba(0, 0, 0, 0.09);
      --text: #0f172a;
      --text-dim: #475569;
      --text-sub: #94a3b8;
      --accent: #0284c7;
      --accent-glow: rgba(2, 132, 199, 0.18);
      --accent-grad: linear-gradient(135deg, #0284c7 0%, #2563eb 100%);
      --surface: rgba(0, 0, 0, 0.035);
      --surface-hover: rgba(0, 0, 0, 0.07);
    }}
    @media (prefers-color-scheme: light) {{
      :root:not([data-theme="dark"]) {{
        --bg: #f1f5f9;
        --card-bg: rgba(255, 255, 255, 0.94);
        --card-border: rgba(0, 0, 0, 0.08);
        --card-shadow: 0 16px 36px rgba(0, 0, 0, 0.09);
        --text: #0f172a;
        --text-dim: #475569;
        --text-sub: #94a3b8;
        --accent: #0284c7;
        --accent-glow: rgba(2, 132, 199, 0.18);
        --accent-grad: linear-gradient(135deg, #0284c7 0%, #2563eb 100%);
        --surface: rgba(0, 0, 0, 0.035);
        --surface-hover: rgba(0, 0, 0, 0.07);
      }}
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      min-height: -webkit-fill-available;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: max(16px, env(safe-area-inset-top)) max(16px, env(safe-area-inset-right)) max(16px, env(safe-area-inset-bottom)) max(16px, env(safe-area-inset-left));
    }}
    .container {{
      width: 100%;
      max-width: 580px;
      background: var(--card-bg);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border: 1px solid var(--card-border);
      border-radius: var(--radius);
      box-shadow: var(--card-shadow);
      padding: 26px 22px;
      display: flex;
      flex-direction: column;
      gap: 18px;
    }}
    .header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 1px solid var(--card-border);
      padding-bottom: 14px;
    }}
    .brand {{
      display: flex;
      align-items: center;
      gap: 12px;
    }}
    .brand-icon {{
      width: 40px;
      height: 40px;
      border-radius: 10px;
      background: var(--accent-glow);
      display: flex;
      align-items: center;
      justify-content: center;
      color: var(--accent);
      flex-shrink: 0;
    }}
    .brand-title h1 {{ font-size: 1.15rem; font-weight: 700; line-height: 1.2; }}
    .brand-title p {{ font-size: 0.8rem; color: var(--text-dim); margin-top: 2px; }}
    .theme-toggle {{
      min-height: var(--touch-min);
      min-width: var(--touch-min);
      background: var(--surface);
      border: 1px solid var(--card-border);
      border-radius: 10px;
      color: var(--text-dim);
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      transition: background 0.2s;
    }}
    .theme-toggle:hover {{ background: var(--surface-hover); color: var(--text); }}
    .icon {{ width: 20px; height: 20px; stroke-width: 2; flex-shrink: 0; }}
    .icon-lg {{ width: 44px; height: 44px; }}
    .icon-file {{ width: 36px; height: 36px; }}

    /* Dropzone Upload */
    .dropzone {{
      border: 2px dashed var(--accent);
      background: var(--accent-glow);
      border-radius: var(--radius-sm);
      padding: 34px 20px;
      text-align: center;
      cursor: pointer;
      transition: transform 0.15s, background 0.2s;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 10px;
      min-height: 160px;
      justify-content: center;
    }}
    .dropzone:hover, .dropzone.dragover {{ background: rgba(0, 229, 255, 0.3); transform: scale(1.01); }}
    .dropzone p {{ font-size: 0.95rem; font-weight: 600; }}
    .dropzone span {{ font-size: 0.8rem; color: var(--text-dim); }}

    /* Progress & Speed */
    .progress-box {{
      display: none;
      flex-direction: column;
      gap: 10px;
      background: var(--surface);
      border: 1px solid var(--card-border);
      border-radius: var(--radius-sm);
      padding: 16px;
    }}
    .progress-stats {{
      display: flex;
      justify-content: space-between;
      font-size: 0.85rem;
      font-weight: 600;
      color: var(--text);
    }}
    .progress-meta {{
      display: flex;
      justify-content: space-between;
      font-size: 0.78rem;
      color: var(--text-dim);
    }}
    .progress-bar-bg {{
      width: 100%;
      height: 10px;
      background: rgba(255, 255, 255, 0.12);
      border-radius: 999px;
      overflow: hidden;
    }}
    .progress-bar-fill {{
      width: 0%;
      height: 100%;
      background: var(--accent-grad);
      transition: width 0.15s ease-out;
      border-radius: 999px;
    }}

    /* File Metadata Card */
    .file-card {{
      display: flex;
      align-items: center;
      gap: 14px;
      background: var(--surface);
      padding: 14px 16px;
      border-radius: var(--radius-sm);
      border: 1px solid var(--card-border);
    }}
    .file-icon-box {{
      width: 48px;
      height: 48px;
      border-radius: 12px;
      background: var(--accent-glow);
      display: flex;
      align-items: center;
      justify-content: center;
      color: var(--accent);
      flex-shrink: 0;
    }}
    .file-details {{ flex: 1; min-width: 0; }}
    .file-name {{ font-weight: 600; font-size: 0.95rem; word-break: break-all; line-height: 1.3; }}
    .file-meta {{
      font-size: 0.8rem;
      color: var(--text-dim);
      margin-top: 4px;
      display: flex;
      gap: 12px;
      align-items: center;
    }}
    .badge-one-time {{
      font-size: 0.72rem;
      background: rgba(245, 158, 11, 0.15);
      color: #f59e0b;
      padding: 2px 8px;
      border-radius: 999px;
      font-weight: 600;
    }}

    /* Preview Container */
    .preview-box {{
      width: 100%;
      border-radius: var(--radius-sm);
      overflow: hidden;
      background: #000;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      border: 1px solid var(--card-border);
      min-height: 120px;
    }}
    .media-wrapper {{ width: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; }}
    .preview-media {{ width: 100%; max-height: 380px; object-fit: contain; }}
    .preview-video {{ background: #000; outline: none; }}
    .audio-wrapper {{ background: var(--surface); padding: 16px; gap: 10px; }}
    .audio-banner {{ display: flex; align-items: center; gap: 8px; font-size: 0.85rem; font-weight: 600; color: var(--accent); }}
    .preview-audio {{ width: 100%; min-height: 44px; }}
    .image-wrapper {{ cursor: zoom-in; position: relative; }}
    .image-hint {{
      position: absolute;
      bottom: 8px;
      background: rgba(0,0,0,0.65);
      color: #fff;
      font-size: 0.72rem;
      padding: 4px 10px;
      border-radius: 999px;
      pointer-events: none;
    }}
    .preview-pdf {{ width: 100%; height: 360px; border: none; background: #fff; }}
    .pdf-btn {{ width: 100%; border-radius: 0; border-top: 1px solid var(--card-border); }}
    .archive-wrapper {{ padding: 28px 16px; gap: 10px; color: var(--accent); }}
    .archive-info {{ font-size: 0.85rem; color: var(--text-dim); }}

    /* Buttons */
    .btn-group {{ display: flex; gap: 10px; }}
    .btn {{
      min-height: var(--touch-min);
      min-width: var(--touch-min);
      flex: 1;
      padding: 12px 18px;
      border-radius: var(--radius-sm);
      font-size: 0.95rem;
      font-weight: 600;
      border: none;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      text-decoration: none;
      transition: transform 0.1s, opacity 0.2s;
    }}
    .btn:active {{ transform: scale(0.98); opacity: 0.9; }}
    .btn-primary {{ background: var(--accent-grad); color: #000; font-weight: 700; }}
    .btn-secondary {{ background: var(--surface); color: var(--text); border: 1px solid var(--card-border); }}
    .btn-secondary:hover {{ background: var(--surface-hover); }}
    .btn-cancel {{ background: rgba(239, 68, 68, 0.12); color: var(--danger); border: 1px solid rgba(239, 68, 68, 0.25); }}

    /* Links & TTL */
    .links-box {{
      display: flex;
      flex-direction: column;
      gap: 8px;
      background: var(--surface);
      padding: 12px 14px;
      border-radius: var(--radius-sm);
      border: 1px solid var(--card-border);
      font-size: 0.8rem;
    }}
    .link-row {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }}
    .link-info {{ display: flex; align-items: center; gap: 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .link-btn {{
      min-height: var(--touch-min);
      padding: 0 12px;
      background: transparent;
      border: 1px solid var(--card-border);
      border-radius: 8px;
      color: var(--accent);
      cursor: pointer;
      font-size: 0.75rem;
      font-weight: 600;
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }}
    .ttl-bar {{
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      font-size: 0.8rem;
      color: var(--text-dim);
    }}
    .ttl-time {{ font-weight: 700; color: var(--accent); }}

    /* Toast Notification */
    .toast {{
      position: fixed;
      bottom: 24px;
      background: #0f172a;
      color: #fff;
      border: 1px solid var(--accent);
      padding: 10px 18px;
      border-radius: 999px;
      font-size: 0.85rem;
      font-weight: 600;
      box-shadow: 0 8px 24px rgba(0,0,0,0.4);
      display: none;
      align-items: center;
      gap: 8px;
      z-index: 1000;
    }}

    /* Lightbox Modal */
    .lightbox {{
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.92);
      display: none;
      align-items: center;
      justify-content: center;
      z-index: 2000;
      padding: 16px;
      cursor: zoom-out;
    }}
    .lightbox img {{ max-width: 95vw; max-height: 95vh; object-fit: contain; border-radius: 8px; }}
    .lightbox-close {{
      position: absolute;
      top: 16px;
      right: 16px;
      width: 44px;
      height: 44px;
      background: rgba(255,255,255,0.15);
      border: none;
      border-radius: 50%;
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="brand">
        <div class="brand-icon">{ICONS["bolt"]}</div>
        <div class="brand-title">
          <h1>Cổng Chuyển Tệp Siêu Tốc</h1>
          <p>LAN Gigabit & Internet WAN — Tiểu Bảo Bảo</p>
        </div>
      </div>
      <button class="theme-toggle" id="themeBtn" aria-label="Đổi giao diện" onclick="toggleTheme()">
        {ICONS["sun"]}
      </button>
    </div>

    <!-- KHU VỰC TẢI LÊN (UPLOAD DROPZONE) -->
    <div id="uploadSection" style="display: {'flex' if initial_mode == 'upload' else 'none'}; flex-direction: column; gap: 14px;">
      <div class="dropzone" id="dropArea">
        {ICONS["upload_cloud"]}
        <p>Kéo thả tệp vào đây hoặc chạm để chọn tệp</p>
        <span>Hỗ trợ mọi định dạng, tốc độ tối đa không giới hạn</span>
        <input type="file" id="fileSelector" style="display: none;">
      </div>

      <div class="progress-box" id="progressBox">
        <div class="progress-stats">
          <span id="progressPercent">0%</span>
          <span id="uploadSpeed">0 MB/s</span>
        </div>
        <div class="progress-bar-bg">
          <div class="progress-bar-fill" id="progressFill"></div>
        </div>
        <div class="progress-meta">
          <span id="progressTransferred">0 MB / 0 MB</span>
          <span id="uploadEta">ETA: --:--</span>
        </div>
        <button class="btn btn-cancel" id="btnCancelUpload" onclick="cancelUpload()">Hủy Bỏ Tải Lên</button>
      </div>
    </div>

    <!-- KHU VỰC TẢI XUỐNG & XEM TRƯỚC (DOWNLOAD / PREVIEW PORTAL) -->
    <div id="downloadSection" style="display: {'flex' if initial_mode == 'download' else 'none'}; flex-direction: column; gap: 16px;">
      <div class="file-card">
        <div class="file-icon-box" id="fileIconBox">{file_icon_svg}</div>
        <div class="file-details">
          <div class="file-name" id="fileNameDisplay">{safe_filename}</div>
          <div class="file-meta">
            <span id="fileSizeDisplay">{size_str}</span>
            <span id="fileCategoryDisplay">{category.upper()}</span>
            {'<span class="badge-one-time">Tải 1 Lần</span>' if one_time else ''}
          </div>
        </div>
      </div>

      <!-- Preview Trực Tiếp Trên Web -->
      <div class="preview-box" id="previewContainer">
        {preview_markup}
      </div>

      <div class="btn-group">
        <a id="btnDownload" href="{download_path}" class="btn btn-primary" download="{safe_filename}">
          {ICONS["download"]}
          <span>Tải Về Ngay</span>
        </a>
        <button id="btnCopyPageLink" class="btn btn-secondary" onclick="copyCurrentLink()">
          {ICONS["copy"]}
          <span>Sao Chép Link</span>
        </button>
      </div>

      <!-- Khối liên kết mạng kép (LAN & WAN) -->
      <div class="links-box">
        <div class="link-row">
          <div class="link-info">{ICONS["wifi"]} <span>LAN Gigabit (Tối đa Wi-Fi)</span></div>
          <button class="link-btn" onclick="copyLinkText('{effective_lan_url}')">Sao chép</button>
        </div>
        <div class="link-row">
          <div class="link-info">{ICONS["globe"]} <span>WAN Internet (Ngrok toàn cầu)</span></div>
          <button class="link-btn" onclick="copyLinkText('{effective_wan_url}')">Sao chép</button>
        </div>
      </div>
    </div>

    <!-- TTL Countdown Indicator -->
    <div class="ttl-bar" id="ttlBar">
      {ICONS["clock"]}
      <span>Thời hạn hiệu lực:</span>
      <span class="ttl-time" id="ttlCountdown">--:--:--</span>
    </div>
  </div>

  <!-- Toast Notification -->
  <div class="toast" id="toastBox">
    {ICONS["check"]}
    <span id="toastMsg">Đã sao chép liên kết vào bộ nhớ tạm!</span>
  </div>

  <!-- Lightbox Popup for Fullscreen Image View -->
  <div class="lightbox" id="lightboxModal" onclick="closeLightbox()">
    <button class="lightbox-close" aria-label="Đóng">{ICONS["x"]}</button>
    <img id="lightboxImg" src="" alt="Fullscreen Preview">
  </div>

  <script>
    const CONFIG = {client_json};
    let currentXhr = null;
    let countdownTimer = null;

    // Theme Switcher with localStorage persistence
    function initTheme() {{
      const saved = localStorage.getItem("portal_theme");
      if (saved) {{
        document.documentElement.setAttribute("data-theme", saved);
      }}
      updateThemeIcon();
    }}

    function toggleTheme() {{
      const current = document.documentElement.getAttribute("data-theme") || "dark";
      const next = current === "light" ? "dark" : "light";
      document.documentElement.setAttribute("data-theme", next);
      localStorage.setItem("portal_theme", next);
      updateThemeIcon();
    }}

    function updateThemeIcon() {{
      const current = document.documentElement.getAttribute("data-theme") || "dark";
      const btn = document.getElementById("themeBtn");
      if (btn) {{
        btn.innerHTML = current === "light" ? `{ICONS['moon']}` : `{ICONS['sun']}`;
      }}
    }}

    // Real-Time TTL Countdown
    function startCountdown() {{
      const el = document.getElementById("ttlCountdown");
      if (!el) return;

      function update() {{
        const now = Date.now() / 1000;
        const diff = Math.max(0, Math.floor(CONFIG.expiresAt - now));
        if (diff <= 0) {{
          el.innerText = "Phiên đã hết hạn (24h)";
          el.style.color = "var(--danger)";
          clearInterval(countdownTimer);
          return;
        }}
        const h = Math.floor(diff / 3600);
        const m = Math.floor((diff % 3600) / 60);
        const s = diff % 60;
        el.innerText = `${{h}}h ${{String(m).padStart(2, '0')}}m ${{String(s).padStart(2, '0')}}s`;
      }}
      update();
      countdownTimer = setInterval(update, 1000);
    }}

    // Formatting helpers
    function formatBytes(bytes) {{
      if (bytes <= 0) return "0 B";
      const k = 1024;
      const sizes = ["B", "KB", "MB", "GB", "TB"];
      const i = Math.floor(Math.log(bytes) / Math.log(k));
      return (bytes / Math.pow(k, i)).toFixed(1) + " " + sizes[i];
    }}

    function formatSpeed(bps) {{
      if (bps <= 0) return "0 MB/s";
      const mbps = bps / (1024 * 1024);
      if (mbps >= 1.0) return mbps.toFixed(1) + " MB/s";
      const kbps = bps / 1024;
      return kbps.toFixed(0) + " KB/s";
    }}

    function formatEta(seconds) {{
      if (seconds <= 0 || !isFinite(seconds)) return "--:--";
      if (seconds < 60) return `${{Math.round(seconds)}}s`;
      const m = Math.floor(seconds / 60);
      const s = Math.round(seconds % 60);
      return `${{m}}m ${{String(s).padStart(2, '0')}}s`;
    }}

    // Toast helper
    function showToast(msg) {{
      const toast = document.getElementById("toastBox");
      const msgEl = document.getElementById("toastMsg");
      if (!toast || !msgEl) return;
      msgEl.innerText = msg;
      toast.style.display = "flex";
      setTimeout(() => {{ toast.style.display = "none"; }}, 2500);
    }}

    // Clipboard helpers
    function copyLinkText(text) {{
      const link = text || window.location.href;
      if (navigator.clipboard && window.isSecureContext) {{
        navigator.clipboard.writeText(link).then(() => showToast("Đã sao chép liên kết!")).catch(() => fallbackCopy(link));
      }} else {{
        fallbackCopy(link);
      }}
    }}

    function copyCurrentLink() {{
      copyLinkText(window.location.href);
    }}

    function fallbackCopy(text) {{
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      try {{
        document.execCommand("copy");
        showToast("Đã sao chép liên kết!");
      }} catch (e) {{
        showToast("Vui lòng sao chép liên kết thủ công.");
      }}
      document.body.removeChild(ta);
    }}

    // Lightbox modal for images
    function openLightbox(el) {{
      const img = el.querySelector("img");
      if (!img) return;
      const modal = document.getElementById("lightboxModal");
      const modalImg = document.getElementById("lightboxImg");
      modalImg.src = img.src;
      modal.style.display = "flex";
    }}

    function closeLightbox() {{
      document.getElementById("lightboxModal").style.display = "none";
    }}

    // Upload Dropzone Handlers
    function initDropzone() {{
      const dropArea = document.getElementById("dropArea");
      const fileInput = document.getElementById("fileSelector");
      if (!dropArea || !fileInput) return;

      dropArea.addEventListener("click", () => fileInput.click());
      dropArea.addEventListener("dragover", (e) => {{ e.preventDefault(); dropArea.classList.add("dragover"); }});
      dropArea.addEventListener("dragleave", () => dropArea.classList.remove("dragover"));
      dropArea.addEventListener("drop", (e) => {{
        e.preventDefault();
        dropArea.classList.remove("dragover");
        if (e.dataTransfer && e.dataTransfer.files.length > 0) {{
          handleFileUpload(e.dataTransfer.files[0]);
        }}
      }});
      fileInput.addEventListener("change", () => {{
        if (fileInput.files.length > 0) {{
          handleFileUpload(fileInput.files[0]);
        }}
      }});
    }}

    function handleFileUpload(file) {{
      document.getElementById("dropArea").style.display = "none";
      const pBox = document.getElementById("progressBox");
      pBox.style.display = "flex";

      const xhr = new XMLHttpRequest();
      currentXhr = xhr;

      let lastLoaded = 0;
      let lastTime = performance.now();
      let speedSamples = [];

      xhr.upload.onprogress = (e) => {{
        if (e.lengthComputable && e.total > 0) {{
          const now = performance.now();
          const dt = (now - lastTime) / 1000;
          const percent = Math.min(100, Math.round((e.loaded / e.total) * 100));

          document.getElementById("progressPercent").innerText = percent + "%";
          document.getElementById("progressFill").style.width = percent + "%";
          document.getElementById("progressTransferred").innerText = `${{formatBytes(e.loaded)}} / ${{formatBytes(e.total)}}`;

          if (dt >= 0.3 || e.loaded === e.total) {{
            const instantSpeed = (e.loaded - lastLoaded) / (dt || 0.001);
            speedSamples.push(instantSpeed);
            if (speedSamples.length > 6) speedSamples.shift();
            const avgSpeed = speedSamples.reduce((a, b) => a + b, 0) / speedSamples.length;

            document.getElementById("uploadSpeed").innerText = formatSpeed(avgSpeed);

            if (avgSpeed > 0) {{
              const rem = (e.total - e.loaded) / avgSpeed;
              document.getElementById("uploadEta").innerText = "ETA: " + formatEta(rem);
            }}
            lastLoaded = e.loaded;
            lastTime = now;
          }}
        }}
      }};

      xhr.onload = () => {{
        if (xhr.status >= 200 && xhr.status < 300) {{
          showToast("Tải Lên Thành Công!");
          setTimeout(() => {{
            window.location.reload();
          }}, 700);
        }} else {{
          alert("Lỗi khi tải lên (Mã " + xhr.status + "): " + (xhr.statusText || "Máy chủ phản hồi thất bại."));
          resetUploadUI();
        }}
      }};

      xhr.onerror = () => {{
        alert("Lỗi kết nối mạng trong quá trình upload!");
        resetUploadUI();
      }};

      const formData = new FormData();
      formData.append("file", file, file.name);
      const targetUrl = `${{CONFIG.uploadUrl}}?filename=${{encodeURIComponent(file.name)}}`;
      xhr.open("POST", targetUrl, true);
      xhr.setRequestHeader("X-Filename", encodeURIComponent(file.name));
      xhr.send(formData);
    }}

    function cancelUpload() {{
      if (currentXhr) {{
        currentXhr.abort();
        currentXhr = null;
        showToast("Đã hủy bỏ tải lên.");
        resetUploadUI();
      }}
    }}

    function resetUploadUI() {{
      document.getElementById("progressBox").style.display = "none";
      document.getElementById("dropArea").style.display = "flex";
      document.getElementById("progressPercent").innerText = "0%";
      document.getElementById("progressFill").style.width = "0%";
    }}

    // Initialization
    initTheme();
    startCountdown();
    initDropzone();
  </script>
</body>
</html>"""
