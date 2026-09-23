"""
test_file_transfer_portal.py — Comprehensive Test Suite for Milestone 2 Web Drop Portal UI.

Verifies:
  1. Template size constraints (< 50KB, < 30KB uncompressed, < 10KB gzipped).
  2. 100% Zero-CDN & offline LAN compatibility (no external script/style/font tags).
  3. Mobile/Safari touch optimization (touch targets >= 44px, playsinline, viewport-fit=cover).
  4. Automatic Dark & Light theme support with CSS variables.
  5. Upload Dropzone rendering & XHR progress, speed, ETA, and cancellation.
  6. Download Portal rendering, real-time TTL countdown, and LAN/WAN dual links.
  7. Multi-Format In-Browser Previews: Video, Audio, Image (with Lightbox), PDF, Archive.
  8. One-time self-destruction badge indicator.
  9. Standalone 404 / Expired session portal rendering.
  10. FastAPI endpoint GET /api/ai/transfer/portal/{token} (200 OK HTML, 404 HTML).
  11. End-to-End upload-then-portal-preview lifecycle.
"""

from __future__ import annotations

import gzip
from io import BytesIO
import json
from pathlib import Path
import re
import shutil
import tempfile
import time
import unittest

from starlette.testclient import TestClient

from app.main import app
from app.routers.file_transfer import router
from app.services.transfer_portal_template import (
    format_file_size,
    get_media_category,
    render_not_found_html,
    render_transfer_portal_html,
)
from app.services.transfer_storage_manager import (
    TransferRecord,
    TransferStorageManager,
    transfer_storage_manager,
)


class TestTransferPortalTemplateUnit(unittest.TestCase):
    """Unit tests for transfer_portal_template HTML generation and compliance."""

    def test_portal_template_size_under_limits(self):
        """Validates that uncompressed HTML is < 50KB (and < 30KB), gzipped is < 10KB."""
        record = TransferRecord(
            token="abcdef1234567890abcdef12",
            filename="sample_video.mp4",
            file_path=Path("/tmp/sample_video.mp4"),
            file_size=104857600,  # 100 MB
            content_type="video/mp4",
            state="ready",
            created_at=time.time(),
            expires_at=time.time() + 86400,
            mode="download",
            lan_url="http://192.168.0.100:8084/api/ai/transfer/download/abcdef1234567890abcdef12",
            internet_url="https://deformational-semiopenly-ewa.ngrok-free.dev/api/ai/transfer/download/abcdef1234567890abcdef12",
        )

        html_content = render_transfer_portal_html(record)
        raw_bytes = html_content.encode("utf-8")
        gz_bytes = gzip.compress(raw_bytes)

        # Requirement: < 50KB, target < 30KB
        self.assertLess(len(raw_bytes), 50 * 1024, f"HTML size {len(raw_bytes)} exceeds 50KB")
        self.assertLess(len(raw_bytes), 30 * 1024, f"HTML size {len(raw_bytes)} exceeds 30KB target")
        self.assertLess(len(gz_bytes), 10 * 1024, f"Gzip size {len(gz_bytes)} exceeds 10KB")

        # 404 template size check
        not_found_html = render_not_found_html("sample_token_1234")
        self.assertLess(len(not_found_html.encode("utf-8")), 10 * 1024)

    def test_zero_cdn_and_offline_independence(self):
        """Ensures template has ZERO external dependencies (no external http/https scripts or styles)."""
        record = TransferRecord(
            token="abcdef1234567890abcdef12",
            filename="offline_document.pdf",
            file_path=Path("/tmp/offline.pdf"),
            file_size=204800,
            content_type="application/pdf",
            state="ready",
            created_at=time.time(),
            expires_at=time.time() + 86400,
            mode="download",
        )
        html_content = render_transfer_portal_html(record)

        # Assert no external script tags: <script src="http..."
        self.assertIsNone(re.search(r'<script\s+[^>]*src=["\']https?://', html_content, re.IGNORECASE))
        # Assert no external stylesheet links: <link rel="stylesheet" href="http..."
        self.assertIsNone(re.search(r'<link\s+[^>]*href=["\']https?://', html_content, re.IGNORECASE))
        # Assert no external @import url(...)
        self.assertIsNone(re.search(r'@import\s+url\(["\']?https?://', html_content, re.IGNORECASE))
        # Assert no external google fonts or cdnjs
        self.assertNotIn("fonts.googleapis.com", html_content)
        self.assertNotIn("cdnjs.cloudflare.com", html_content)

    def test_mobile_safari_touch_targets_and_meta(self):
        """Verifies Safari/iOS touch requirements (viewport-fit, touch target >= 44px, playsinline)."""
        record = TransferRecord(
            token="abcdef1234567890abcdef12",
            filename="mobile_clip.mp4",
            file_path=Path("/tmp/clip.mp4"),
            file_size=15000000,
            content_type="video/mp4",
            state="ready",
            created_at=time.time(),
            expires_at=time.time() + 86400,
            mode="download",
        )
        html_content = render_transfer_portal_html(record)

        # Viewport meta tags for iOS Safari
        self.assertIn("viewport-fit=cover", html_content)
        self.assertIn("user-scalable=no", html_content)
        self.assertIn("apple-mobile-web-app-capable", html_content)

        # Touch target minimum rule >= 44px
        self.assertIn("--touch-min: 44px", html_content)
        self.assertIn("min-height: var(--touch-min)", html_content)

        # Video tag must contain playsinline for iOS Safari
        self.assertIn("playsinline", html_content)
        self.assertIn('preload="metadata"', html_content)
        self.assertIn("controls", html_content)

    def test_dark_light_theme_support(self):
        """Verifies presence of auto system theme and manual theme toggle."""
        record = TransferRecord(
            token="theme_token_1234567890",
            filename="file.txt",
            file_path=None,
            file_size=0,
            content_type="text/plain",
            state="pending_upload",
            created_at=time.time(),
            expires_at=time.time() + 86400,
            mode="upload",
        )
        html_content = render_transfer_portal_html(record)

        self.assertIn(":root {", html_content)
        self.assertIn('[data-theme="light"]', html_content)
        self.assertIn("@media (prefers-color-scheme: light)", html_content)
        self.assertIn("toggleTheme", html_content)
        self.assertIn("themeBtn", html_content)

    def test_render_upload_dropzone_mode(self):
        """Verifies Upload Dropzone mode rendering with XHR progress, speed, ETA, and cancellation."""
        record = TransferRecord(
            token="upload_token_1234567890",
            filename="target.bin",
            file_path=None,
            file_size=0,
            content_type="application/octet-stream",
            state="pending_upload",
            created_at=time.time(),
            expires_at=time.time() + 86400,
            mode="upload",
        )
        html_content = render_transfer_portal_html(record)

        # Dropzone section is displayed
        self.assertIn('id="uploadSection"', html_content)
        self.assertIn('id="dropArea"', html_content)
        self.assertIn("Kéo thả tệp vào đây hoặc chạm để chọn tệp", html_content)
        self.assertIn('id="fileSelector"', html_content)

        # Progress elements
        self.assertIn('id="progressBox"', html_content)
        self.assertIn('id="progressPercent"', html_content)
        self.assertIn('id="progressFill"', html_content)
        self.assertIn('id="uploadSpeed"', html_content)
        self.assertIn('id="uploadEta"', html_content)
        self.assertIn('id="btnCancelUpload"', html_content)
        self.assertIn("cancelUpload()", html_content)

        # XHR upload logic
        self.assertIn("xhr.upload.onprogress", html_content)
        self.assertIn("currentXhr.abort()", html_content)
        self.assertIn("Tải Lên Thành Công!", html_content)

    def test_render_download_portal_mode(self):
        """Verifies Download Portal mode rendering with file metadata and TTL countdown."""
        record = TransferRecord(
            token="download_token_12345678",
            filename="document_archive.zip",
            file_path=Path("/tmp/archive.zip"),
            file_size=52428800,  # 50 MB
            content_type="application/zip",
            state="ready",
            created_at=time.time(),
            expires_at=time.time() + 86400,
            mode="download",
            lan_url="http://192.168.0.100:8084/api/ai/transfer/download/download_token_12345678",
            internet_url="https://deformational-semiopenly-ewa.ngrok-free.dev/api/ai/transfer/download/download_token_12345678",
        )
        html_content = render_transfer_portal_html(record)

        # Download section displayed
        self.assertIn('id="downloadSection"', html_content)
        self.assertIn("document_archive.zip", html_content)
        self.assertIn("50.0 MB", html_content)
        self.assertIn("Tải Về Ngay", html_content)
        self.assertIn('href="/api/ai/transfer/download/download_token_12345678"', html_content)

        # TTL countdown
        self.assertIn('id="ttlCountdown"', html_content)
        self.assertIn("startCountdown()", html_content)

        # Dual links
        self.assertIn("LAN Gigabit", html_content)
        self.assertIn("WAN Internet", html_content)
        self.assertIn("copyLinkText", html_content)

    def test_media_preview_variants(self):
        """Tests preview markup for Video, Audio, Image, PDF, and Archive."""
        base_kwargs = {
            "token": "tok_preview_12345678",
            "file_path": Path("/tmp/file"),
            "file_size": 10240,
            "state": "ready",
            "created_at": time.time(),
            "expires_at": time.time() + 86400,
            "mode": "download",
        }

        # 1. Video MP4
        rec_video = TransferRecord(filename="clip.mp4", content_type="video/mp4", **base_kwargs)
        html_video = render_transfer_portal_html(rec_video)
        self.assertIn("<video", html_video)
        self.assertIn("playsinline", html_video)
        self.assertIn("preview-video", html_video)

        # 2. Audio MP3
        rec_audio = TransferRecord(filename="song.mp3", content_type="audio/mpeg", **base_kwargs)
        html_audio = render_transfer_portal_html(rec_audio)
        self.assertIn("<audio", html_audio)
        self.assertIn("preview-audio", html_audio)
        self.assertIn("Phát Trực Tiếp Âm Thanh", html_audio)

        # 3. Image PNG
        rec_img = TransferRecord(filename="photo.png", content_type="image/png", **base_kwargs)
        html_img = render_transfer_portal_html(rec_img)
        self.assertIn("<img", html_img)
        self.assertIn("preview-image", html_img)
        self.assertIn("openLightbox", html_img)
        self.assertIn("lightboxModal", html_img)

        # 4. PDF Document
        rec_pdf = TransferRecord(filename="manual.pdf", content_type="application/pdf", **base_kwargs)
        html_pdf = render_transfer_portal_html(rec_pdf)
        self.assertIn("<iframe", html_pdf)
        self.assertIn("preview-pdf", html_pdf)
        self.assertIn("Mở Toàn Màn Hình Trong Tab Mới", html_pdf)

        # 5. Archive ZIP
        rec_zip = TransferRecord(filename="backup.zip", content_type="application/zip", **base_kwargs)
        html_zip = render_transfer_portal_html(rec_zip)
        self.assertIn("archive-wrapper", html_zip)
        self.assertIn("Tệp nén lưu trữ", html_zip)

    def test_one_time_badge_presence(self):
        """Verifies that one_time badge is displayed when one_time=True and omitted when False."""
        rec_ot = TransferRecord(
            token="tok_onetime_12345678",
            filename="secret.doc",
            file_path=Path("/tmp/secret.doc"),
            file_size=1024,
            content_type="application/msword",
            state="ready",
            created_at=time.time(),
            expires_at=time.time() + 86400,
            mode="download",
            one_time=True,
        )
        html_ot = render_transfer_portal_html(rec_ot)
        self.assertIn('class="badge-one-time"', html_ot)
        self.assertIn("Tải 1 Lần", html_ot)

        rec_normal = TransferRecord(
            token="tok_normal_12345678",
            filename="normal.doc",
            file_path=Path("/tmp/normal.doc"),
            file_size=1024,
            content_type="application/msword",
            state="ready",
            created_at=time.time(),
            expires_at=time.time() + 86400,
            mode="download",
            one_time=False,
        )
        html_normal = render_transfer_portal_html(rec_normal)
        self.assertNotIn('class="badge-one-time"', html_normal)
        self.assertNotIn("Tải 1 Lần", html_normal)

    def test_render_404_expired_session(self):
        """Verifies render_transfer_portal_html(None) returns clean 404 page."""
        html_404 = render_transfer_portal_html(None, token="expired_tok_1234")
        self.assertIn("404", html_404)
        self.assertIn("Phiên Truyền Tệp Đã Hết Hạn", html_404)
        self.assertIn("expired_tok_1234", html_404)
        self.assertIn("Zero-Disk Leak", html_404)

    def test_format_file_size_and_category_helpers(self):
        """Verifies format_file_size and get_media_category utility functions."""
        self.assertEqual(format_file_size(0), "0 B")
        self.assertEqual(format_file_size(512), "512 B")
        self.assertEqual(format_file_size(1024), "1.0 KB")
        self.assertEqual(format_file_size(1048576), "1.0 MB")
        self.assertEqual(format_file_size(1073741824), "1.0 GB")

        self.assertEqual(get_media_category("film.mp4"), "video")
        self.assertEqual(get_media_category("audio.mp3"), "audio")
        self.assertEqual(get_media_category("pic.webp"), "image")
        self.assertEqual(get_media_category("doc.pdf"), "pdf")
        self.assertEqual(get_media_category("data.tar.gz"), "archive")
        self.assertEqual(get_media_category("binary.bin"), "file")


class TestFileTransferPortalAPI(unittest.TestCase):
    """Integration tests for FastAPI GET /api/ai/transfer/portal/{token} endpoint."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_portal_api_")
        self.base_dir = Path(self.test_dir)
        self.orig_base = transfer_storage_manager.base_dir
        transfer_storage_manager.base_dir = self.base_dir
        transfer_storage_manager.ensure_dirs()

    def tearDown(self):
        transfer_storage_manager.base_dir = self.orig_base
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_get_portal_upload_mode(self):
        """GET /portal/{token} on pending_upload session returns 200 OK HTML with Dropzone."""
        rec = transfer_storage_manager.create_session(
            filename="incoming.zip",
            mode="upload",
        )
        resp = self.client.get(f"/api/ai/transfer/portal/{rec.token}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.headers["content-type"])
        self.assertIn("Kéo thả tệp vào đây hoặc chạm để chọn tệp", resp.text)
        self.assertIn("progressPercent", resp.text)
        self.assertIn(rec.token, resp.text)

    def test_get_portal_download_mode_with_preview(self):
        """GET /portal/{token} on ready session returns 200 OK HTML with preview and download button."""
        rec = transfer_storage_manager.create_session(
            filename="presentation.mp4",
            mode="download",
        )
        token_dir = self.base_dir / rec.token
        data_file = token_dir / "presentation.mp4"
        data_file.write_bytes(b"FAKE_MP4_VIDEO_HEADER_DATA" * 50)

        # Update metadata state to ready
        meta_file = token_dir / "metadata.json"
        with open(meta_file, "r", encoding="utf-8") as f:
            meta = json.load(f)
        meta["state"] = "ready"
        meta["file_size"] = data_file.stat().st_size
        meta["content_type"] = "video/mp4"
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f)

        resp = self.client.get(f"/api/ai/transfer/portal/{rec.token}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.headers["content-type"])
        self.assertIn("presentation.mp4", resp.text)
        self.assertIn("Tải Về Ngay", resp.text)
        self.assertIn("<video", resp.text)
        self.assertIn("playsinline", resp.text)

    def test_get_portal_invalid_or_expired_token_returns_404_html(self):
        """GET /portal/{token} on non-existent or expired token returns 404 status with clean HTML."""
        resp = self.client.get("/api/ai/transfer/portal/non_existent_token_12345678")
        self.assertEqual(resp.status_code, 404)
        self.assertIn("text/html", resp.headers["content-type"])
        self.assertIn("Phiên Truyền Tệp Đã Hết Hạn", resp.text)
        self.assertIn("non_existent_token_12345678", resp.text)

    def test_get_portal_alias_route(self):
        """Verifies /{token}/portal alias returns the same 200 HTML content."""
        rec = transfer_storage_manager.create_session(filename="alias_test.txt")
        resp = self.client.get(f"/api/ai/transfer/{rec.token}/portal")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.headers["content-type"])

    def test_create_session_returns_portal_url(self):
        """POST /create response includes portal_url."""
        resp = self.client.post("/api/ai/transfer/create", json={"file_name": "test_portal.bin"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("portal_url", data)
        self.assertIn(f"/api/ai/transfer/portal/{data['token']}", data["portal_url"])

    def test_end_to_end_upload_and_portal_lifecycle(self):
        """E2E: Create session -> check upload portal -> upload file -> check ready download portal."""
        # Step 1: Create session
        resp_create = self.client.post("/api/ai/transfer/create", json={"file_name": "cool_art.png", "mode": "upload"})
        self.assertEqual(resp_create.status_code, 200)
        token = resp_create.json()["token"]

        # Step 2: Portal is initially in upload mode
        resp_portal_1 = self.client.get(f"/api/ai/transfer/portal/{token}")
        self.assertEqual(resp_portal_1.status_code, 200)
        self.assertIn('id="uploadSection"', resp_portal_1.text)

        # Step 3: Upload the image file
        file_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 2048
        resp_upload = self.client.post(
            f"/api/ai/transfer/upload/{token}",
            files={"file": ("cool_art.png", BytesIO(file_bytes), "image/png")},
        )
        self.assertEqual(resp_upload.status_code, 200)
        self.assertEqual(resp_upload.json()["status"], "success")

        # Step 4: Portal is now in download mode with image preview
        resp_portal_2 = self.client.get(f"/api/ai/transfer/portal/{token}")
        self.assertEqual(resp_portal_2.status_code, 200)
        self.assertIn("cool_art.png", resp_portal_2.text)
        self.assertIn("preview-image", resp_portal_2.text)
        self.assertIn("openLightbox", resp_portal_2.text)
        self.assertIn("Tải Về Ngay", resp_portal_2.text)


if __name__ == "__main__":
    unittest.main()
