"""
test_file_transfer_qr_telegram.py — Comprehensive Test Suite for Milestone 3.

Covers:
  1. In-Memory QR Code Generator (PNG bytes & SVG string):
     - Valid PNG RFC 2083 magic signature (b"\\x89PNG\\r\\n\\x1a\\n").
     - Standalone SVG XML generation.
     - 100% Zero-Disk Leak verification (temp disk delta = 0 across heavy generation loops).
     - Custom sizing, borders, and unicode/long URL handling.
  2. File Transfer QR Endpoint (GET /api/ai/transfer/qr/{token}):
     - Successful PNG return with HTTP 200 and image/png media type.
     - Cache-Control: public, max-age=86400 verification.
     - Route alias support (/{token}/qr).
     - HTTP 404 for non-existent or expired tokens.
  3. Telegram Bot Transfer Portal Card Integration:
     - send_transfer_portal_card method calling send_photo_bytes with valid PNG.
     - Caption presentation verification: dual LAN Gigabit + WAN Internet links, 24h TTL format.
     - One-time auto-purge security notice inclusion.
     - HTML escaping of unsafe filename characters.
     - Simulated Telegram API /sendPhoto multipart transmission.
"""

from __future__ import annotations

import html
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.services.telegram_bot import TelegramBot
from app.services.transfer_qr_generator import (
    PNG_MAGIC_HEADER,
    generate_qr_png_bytes,
    generate_qr_svg,
)
from app.services.transfer_storage_manager import (
    TransferStorageManager,
    transfer_storage_manager,
)


class TestTransferQRGeneratorUnit(unittest.TestCase):
    """Unit tests for transfer_qr_generator.py in-memory operations."""

    def test_generate_qr_png_bytes_valid_magic_header_and_image(self):
        """Xác nhận ảnh PNG sinh trực tiếp trên RAM có header chuẩn và mở được bằng PIL."""
        url = "http://192.168.0.100:8084/api/ai/transfer/portal/sample-token-12345"
        png_bytes = generate_qr_png_bytes(url)

        self.assertIsInstance(png_bytes, bytes)
        self.assertGreater(len(png_bytes), 500)
        self.assertTrue(png_bytes.startswith(PNG_MAGIC_HEADER))

        # Xác thực bằng PIL giải mã ảnh thành công
        with Image.open(io.BytesIO(png_bytes)) as img:
            self.assertEqual(img.format, "PNG")
            self.assertGreater(img.size[0], 100)
            self.assertGreater(img.size[1], 100)

    def test_generate_qr_svg_valid_xml_string(self):
        """Xác nhận chuỗi SVG độc lập chứa thẻ mở, thẻ đóng và namespace SVG."""
        url = "http://192.168.0.100:8084/api/ai/transfer/portal/sample-token-12345"
        svg_str = generate_qr_svg(url)

        self.assertIsInstance(svg_str, str)
        self.assertIn("<svg", svg_str)
        self.assertIn("</svg>", svg_str)
        self.assertIn("http://www.w3.org/2000/svg", svg_str)

    def test_generate_qr_custom_box_size_and_border(self):
        """Xác nhận box_size lớn hơn sinh ra ảnh kích thước lớn hơn tương ứng."""
        url = "http://192.168.0.100:8084/api/ai/transfer/portal/sample-token-12345"
        small_png = generate_qr_png_bytes(url, box_size=5, border=2)
        large_png = generate_qr_png_bytes(url, box_size=10, border=4)

        with Image.open(io.BytesIO(small_png)) as img_small:
            small_w, small_h = img_small.size
        with Image.open(io.BytesIO(large_png)) as img_large:
            large_w, large_h = img_large.size

        self.assertGreater(large_w, small_w)
        self.assertGreater(large_h, small_h)

    def test_generate_qr_custom_colors(self):
        """Xác nhận tuỳ chỉnh màu fill và background thành công."""
        url = "http://192.168.0.100:8084/api/ai/transfer/portal/sample-token-12345"
        png_bytes = generate_qr_png_bytes(url, fill_color="darkblue", back_color="lightyellow")
        self.assertTrue(png_bytes.startswith(PNG_MAGIC_HEADER))

        with Image.open(io.BytesIO(png_bytes)) as img:
            self.assertEqual(img.format, "PNG")

    def test_zero_disk_leak_during_qr_generation(self):
        """Zero-Disk Leak: Xác nhận sinh 100 mã QR liên tục không tạo ra bất kỳ file rác nào trên đĩa."""
        temp_dir = Path(tempfile.gettempdir())
        initial_files = set(temp_dir.iterdir())

        # Sinh 100 mã QR
        for i in range(100):
            url = f"http://192.168.0.100:8084/api/ai/transfer/portal/token-stress-test-{i}"
            _ = generate_qr_png_bytes(url)
            _ = generate_qr_svg(url)

        final_files = set(temp_dir.iterdir())
        new_files = final_files - initial_files

        # Filter out unrelated OS temporary files if any
        qr_leak_files = [f for f in new_files if "qr" in f.name.lower() or f.suffix in (".png", ".svg")]
        self.assertEqual(len(qr_leak_files), 0, f"Detected disk leak: {qr_leak_files}")

    def test_qr_generation_with_long_url_and_unicode(self):
        """Xác nhận xử lý trơn tru URL dài và có ký tự tiếng Việt URL-encoded."""
        long_url = (
            "https://deformational-semiopenly-ewa.ngrok-free.dev/api/ai/transfer/portal/"
            "chuy%E1%BB%83n_t%E1%BB%87p_si%C3%AAu_t%E1%BB%91c_ti%E1%BB%83u_b%E1%BA%A3o_b%E1%BA%A3o_"
            + "a" * 300
        )
        png_bytes = generate_qr_png_bytes(long_url)
        self.assertTrue(png_bytes.startswith(PNG_MAGIC_HEADER))

        svg_content = generate_qr_svg(long_url)
        self.assertIn("<svg", svg_content)


class TestFileTransferQREndpoint(unittest.TestCase):
    """Integration tests for GET /api/ai/transfer/qr/{token} endpoint."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="qr_transfers_test_"))
        self.original_base_dir = transfer_storage_manager.base_dir
        transfer_storage_manager.base_dir = self.tmp_dir
        transfer_storage_manager.ensure_dirs()
        self.client = TestClient(app)

    def tearDown(self):
        transfer_storage_manager.base_dir = self.original_base_dir
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_get_qr_endpoint_success(self):
        """Xác nhận endpoint GET /qr/{token} trả về HTTP 200, Content-Type image/png, Cache-Control 86400s."""
        record = transfer_storage_manager.create_session(
            filename="presentation.pdf",
            mode="download",
            ttl_hours=24,
        )

        response = self.client.get(f"/api/ai/transfer/qr/{record.token}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertIn("Cache-Control", response.headers)
        self.assertIn("public", response.headers["Cache-Control"])
        self.assertIn("max-age=86400", response.headers["Cache-Control"])

        content = response.content
        self.assertTrue(content.startswith(PNG_MAGIC_HEADER))
        with Image.open(io.BytesIO(content)) as img:
            self.assertEqual(img.format, "PNG")

    def test_get_qr_endpoint_alias_route(self):
        """Xác nhận route alias /{token}/qr hoạt động đồng nhất."""
        record = transfer_storage_manager.create_session(
            filename="archive.zip",
            mode="upload",
        )

        response = self.client.get(f"/api/ai/transfer/{record.token}/qr")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertTrue(response.content.startswith(PNG_MAGIC_HEADER))

    def test_get_qr_endpoint_non_existent_token_returns_404(self):
        """Xác nhận trả về HTTP 404 khi token không tồn tại."""
        response = self.client.get("/api/ai/transfer/qr/non_existent_token_123456789012")
        self.assertEqual(response.status_code, 404)
        self.assertIn("not found", response.json()["detail"].lower())

    def test_get_qr_endpoint_expired_session_returns_404(self):
        """Xác nhận trả về HTTP 404 khi session đã hết hạn TTL."""
        record = transfer_storage_manager.create_session(
            filename="expired_doc.docx",
            ttl_hours=1,
        )
        # Manually alter expires_at to simulate expired session
        meta_file = self.tmp_dir / record.token / "metadata.json"
        with open(meta_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["expires_at"] = time.time() - 3600
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(data, f)

        response = self.client.get(f"/api/ai/transfer/qr/{record.token}")
        self.assertEqual(response.status_code, 404)


class TestTelegramBotTransferPortalCard(unittest.IsolatedAsyncioTestCase):
    """Unit and mock delivery tests for send_transfer_portal_card."""

    def setUp(self):
        self.bot = TelegramBot(ai_agent=MagicMock(), ssh_client=MagicMock())
        self.bot.token = "123456:fake_bot_token"
        self.bot.chat_id = "987654321"

    async def test_send_transfer_portal_card_full_success(self):
        """Xác nhận gửi thẻ card hoàn chỉnh với đầy đủ thông tin LAN, WAN, TTL và ảnh QR PNG."""
        self.bot.send_photo_bytes = AsyncMock(return_value=True)

        res = await self.bot.send_transfer_portal_card(
            chat_id="987654321",
            file_name="video_bao_cao.mp4",
            file_size_bytes=52428800,  # 50.0 MB
            token="secure_token_abc123456789",
            lan_url="http://192.168.0.100:8084/api/ai/transfer/portal/secure_token_abc123456789",
            wan_url="https://deformational-semiopenly-ewa.ngrok-free.dev/api/ai/transfer/portal/secure_token_abc123456789",
            ttl_hours=24,
            mode="download",
            one_time=False,
        )

        self.assertTrue(res)
        self.bot.send_photo_bytes.assert_called_once()
        call_kwargs = self.bot.send_photo_bytes.call_args.kwargs

        self.assertEqual(call_kwargs["chat_id"], "987654321")
        self.assertEqual(call_kwargs["filename"], "portal_qr.png")
        self.assertEqual(call_kwargs["parse_mode"], "HTML")

        photo_bytes = call_kwargs["photo_bytes"]
        self.assertIsInstance(photo_bytes, bytes)
        self.assertTrue(photo_bytes.startswith(PNG_MAGIC_HEADER))

        caption = call_kwargs["caption"]
        self.assertIn("NHẬN TỆP CHUYỂN GIAO", caption)
        self.assertIn("video_bao_cao.mp4", caption)
        self.assertIn("50.0 MB", caption)
        self.assertIn("http://192.168.0.100:8084", caption)
        self.assertIn("https://deformational-semiopenly-ewa.ngrok-free.dev", caption)
        self.assertIn("24 giờ", caption)
        self.assertIn("Quét mã QR đính kèm", caption)
        self.assertNotIn("Liên kết tự hủy", caption)

    async def test_send_transfer_portal_card_one_time_warning(self):
        """Xác nhận kèm cảnh báo tự hủy sau 1 lần tải khi one_time=True."""
        self.bot.send_photo_bytes = AsyncMock(return_value=True)

        await self.bot.send_transfer_portal_card(
            chat_id="987654321",
            file_name="secret_key.pem",
            file_size_bytes=2048,
            token="token_one_time_99999",
            lan_url="http://192.168.0.100:8084/portal/secret",
            wan_url="https://ngrok/portal/secret",
            one_time=True,
        )

        caption = self.bot.send_photo_bytes.call_args.kwargs["caption"]
        self.assertIn("Liên kết tự hủy sau 1 lần tải thành công", caption)

    async def test_send_transfer_portal_card_upload_mode(self):
        """Xác nhận tiêu đề phù hợp khi mode='upload'."""
        self.bot.send_photo_bytes = AsyncMock(return_value=True)

        await self.bot.send_transfer_portal_card(
            chat_id="987654321",
            file_name="",
            file_size_bytes=0,
            token="token_upload_mode",
            lan_url="http://192.168.0.100:8084/upload",
            wan_url="https://ngrok/upload",
            mode="upload",
        )

        caption = self.bot.send_photo_bytes.call_args.kwargs["caption"]
        self.assertIn("CỔNG CHUYỂN TỆP SIÊU TỐC TIỂU BẢO BẢO", caption)

    async def test_send_transfer_portal_card_html_escaping(self):
        """Xác nhận tên tệp có ký tự đặc biệt được html.escape an toàn."""
        self.bot.send_photo_bytes = AsyncMock(return_value=True)

        special_filename = "<b>hacked</b> & 'quotes' <script>.zip"
        await self.bot.send_transfer_portal_card(
            chat_id="987654321",
            file_name=special_filename,
            file_size_bytes=1024,
            token="token_special_chars",
            lan_url="http://lan",
            wan_url="http://wan",
        )

        caption = self.bot.send_photo_bytes.call_args.kwargs["caption"]
        self.assertIn("&lt;b&gt;hacked&lt;/b&gt;", caption)
        self.assertIn("&amp;", caption)
        self.assertNotIn("<script>", caption)

    async def test_send_transfer_portal_card_custom_qr_target(self):
        """Xác nhận hỗ trợ chỉ định qr_target_url tùy chọn."""
        with patch("app.services.transfer_qr_generator.generate_qr_png_bytes", wraps=generate_qr_png_bytes) as mock_qr:
            self.bot.send_photo_bytes = AsyncMock(return_value=True)

            custom_target = "https://custom-portal.ngrok-free.dev/open/my_session"
            await self.bot.send_transfer_portal_card(
                chat_id="987654321",
                file_name="file.dat",
                file_size_bytes=100,
                token="token_custom_qr",
                lan_url="http://lan_url",
                wan_url="http://wan_url",
                qr_target_url=custom_target,
            )

            mock_qr.assert_called_once_with(custom_target)

    async def test_send_transfer_portal_card_network_delivery_mock(self):
        """Xác nhận toàn bộ chuỗi gửi qua HTTP mock tới Telegram API /sendPhoto."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"ok": true}'

        self.bot._http_client.post = AsyncMock(return_value=mock_response)

        res = await self.bot.send_transfer_portal_card(
            chat_id="123456",
            file_name="test_doc.pdf",
            file_size_bytes=10240,
            token="net_token_77777",
            lan_url="http://192.168.0.100:8084/lan",
            wan_url="https://wan.ngrok-free.dev/wan",
        )

        self.assertTrue(res)
        self.bot._http_client.post.assert_called_once()
        url = self.bot._http_client.post.call_args.args[0]
        self.assertTrue(url.endswith("/sendPhoto"))
        files = self.bot._http_client.post.call_args.kwargs["files"]
        self.assertIn("photo", files)
        self.assertTrue(files["photo"][1].startswith(PNG_MAGIC_HEADER))


if __name__ == "__main__":
    unittest.main()
