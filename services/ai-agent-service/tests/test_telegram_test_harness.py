"""
Test Suite for Synthetic Telegram Test Harness & Production Integration (Milestone 4)

Kiểm thử toàn diện 3 tầng:
1. Security Gating:
   - Layer 1: Environment Flag Gate (ENABLE_TELEGRAM_TEST_HARNESS == False -> 403)
   - Layer 2: Authentication Token (Missing / Invalid -> 401)
   - Layer 3: Client IP Whitelisting (Untrusted IP -> 403)
2. Synthetic Injection & Transcript Capture:
   - E2E flow qua bot._on_video_process_pipeline xác minh transcript 4 bước
     (send initial -> edit progress -> delete progress -> send video).
   - Test router endpoint POST /api/internal/test-harness/telegram/inject qua TestClient.
3. Error Handling & Defensive Guards:
   - Pipeline trả về status='error' -> tự động xóa progress message và báo lỗi tiếng Việt.
   - Pipeline ném Exception -> tự động xóa progress message và báo lỗi.
   - Defensive guard tại _format_video_quality_caption không bao giờ crash với None values.
"""

import asyncio
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Dict, List
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

# Đảm bảo đường dẫn import tới app của ai-agent-service
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.routers import telegram_test_harness
from app.services.telegram_bot import TelegramBot
from app.services.video_pipeline import PendingVideoSession, VideoMetadata


class TestTelegramTestHarness(unittest.IsolatedAsyncioTestCase):
    """Bộ kiểm thử đơn vị & tích hợp cho Synthetic Telegram Test Harness."""

    async def asyncSetUp(self):
        """Khởi tạo môi trường kiểm thử và các mock objects cần thiết."""
        self.temp_dir = tempfile.mkdtemp(prefix="test_harness_suite_")
        self.test_video_path = os.path.join(self.temp_dir, "sample_test_video.mp4")
        with open(self.test_video_path, "wb") as f:
            f.write(b"\x00" * 4096)

        # Khởi tạo instance TelegramBot độc lập (không gọi __init__ gốc để tránh spawn thread/polling)
        self.bot = TelegramBot.__new__(TelegramBot)
        self.bot.token = "mock_telegram_token"
        self.bot._running = False
        self.bot.chat_id = "123456789"

        # Mock media processor và video editor
        self.mock_editor = AsyncMock()
        self.bot._video_editor_svc = self.mock_editor

        self.mock_media = MagicMock()
        self.mock_media.download_telegram_file_to_path = AsyncMock()
        self.bot._media = self.mock_media

        # Bắt giữ outbound calls thành transcript mô phỏng
        self.transcript: List[Dict[str, Any]] = []

        async def fake_send_message(chat_id, text, **kwargs):
            self.transcript.append({
                "action": "send_message",
                "chat_id": chat_id,
                "text": text,
                "message_id": 1001,
            })
            return {"message_id": 1001}

        async def fake_edit_message_text(chat_id, message_id, text, **kwargs):
            self.transcript.append({
                "action": "edit_message_text",
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
            })
            return True

        async def fake_delete_message(chat_id, message_id):
            self.transcript.append({
                "action": "delete_message",
                "chat_id": chat_id,
                "message_id": message_id,
            })
            return True

        async def fake_send_video(chat_id, video_path, caption=None, **kwargs):
            self.transcript.append({
                "action": "send_video",
                "chat_id": chat_id,
                "video_path": video_path,
                "caption": caption,
            })
            return True

        async def fake_send_video_file(chat_id, video_path, caption=None, **kwargs):
            self.transcript.append({
                "action": "send_video_file",
                "chat_id": chat_id,
                "video_path": video_path,
                "caption": caption,
            })
            return await fake_send_video(chat_id, video_path, caption=caption, **kwargs)

        self.bot.send_message = AsyncMock(side_effect=fake_send_message)
        self.bot.send_message_with_result = AsyncMock(side_effect=fake_send_message)
        self.bot.edit_message_text = AsyncMock(side_effect=fake_edit_message_text)
        self.bot.delete_message = AsyncMock(side_effect=fake_delete_message)
        self.bot.send_video = AsyncMock(side_effect=fake_send_video)
        self.bot.send_video_file = AsyncMock(side_effect=fake_send_video_file)

    async def asyncTearDown(self):
        """Dọn dẹp tệp tin tạm sau khi test kết thúc."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    # =========================================================================
    # NHÓM 1: SECURITY GATING TESTS
    # =========================================================================

    def test_security_gating_disabled_flag_rejects_with_403(self):
        """Test Case 1.1: Khi cờ ENABLE_TELEGRAM_TEST_HARNESS tắt (False), từ chối truy cập 403."""
        app = FastAPI()
        app.include_router(telegram_test_harness.router)
        client = TestClient(app)

        with patch.object(settings, "ENABLE_TELEGRAM_TEST_HARNESS", False):
            resp = client.post(
                "/api/internal/test-harness/telegram/inject",
                json={"video_path": self.test_video_path},
            )
            self.assertEqual(resp.status_code, 403)
            self.assertIn("disabled", resp.json().get("detail", "").lower())

    def test_security_gating_missing_or_invalid_auth_token_rejects_with_401(self):
        """Test Case 1.2: Khi thiếu hoặc sai token xác thực, từ chối với HTTP 401 Unauthorized."""
        app = FastAPI()
        app.include_router(telegram_test_harness.router)
        client = TestClient(app)

        with patch.object(settings, "ENABLE_TELEGRAM_TEST_HARNESS", True), \
             patch.object(settings, "TEST_HARNESS_SECRET_KEY", "correct_secret_key_123"):

            # 1. Không gửi token
            resp_no_token = client.post(
                "/api/internal/test-harness/telegram/inject",
                json={"video_path": self.test_video_path},
            )
            self.assertEqual(resp_no_token.status_code, 401)

            # 2. Gửi token sai
            resp_wrong_token = client.post(
                "/api/internal/test-harness/telegram/inject",
                json={"video_path": self.test_video_path},
                headers={"Authorization": "Bearer wrong_secret"},
            )
            self.assertEqual(resp_wrong_token.status_code, 401)

            # 3. Gửi token sai qua header X-Test-Harness-Key
            resp_wrong_key = client.post(
                "/api/internal/test-harness/telegram/inject",
                json={"video_path": self.test_video_path},
                headers={"X-Test-Harness-Key": "wrong_key"},
            )
            self.assertEqual(resp_wrong_key.status_code, 401)

    def test_security_gating_unauthorized_ip_rejects_with_403(self):
        """Test Case 1.3: Khi IP client không thuộc whitelist (IP public ngoài), từ chối 403."""
        app = FastAPI()
        app.include_router(telegram_test_harness.router)

        with patch.object(settings, "ENABLE_TELEGRAM_TEST_HARNESS", True), \
             patch.object(settings, "TEST_HARNESS_SECRET_KEY", "secret123"), \
             patch.object(settings, "TEST_HARNESS_ALLOWED_IPS", ["127.0.0.1", "::1", "172.16.0.0/12"]):

            # Mô phỏng TestClient với IP public 203.0.113.1
            client_external = TestClient(app, client=("203.0.113.1", 54321))
            resp_blocked = client_external.post(
                "/api/internal/test-harness/telegram/inject",
                json={"video_path": self.test_video_path},
                headers={"Authorization": "Bearer secret123"},
            )
            self.assertEqual(resp_blocked.status_code, 403)
            self.assertIn("whitelist", resp_blocked.json().get("detail", "").lower())

            # Mô phỏng giả mạo IP qua header X-Forwarded-For
            client_loopback = TestClient(app, client=("127.0.0.1", 54321))
            resp_spoofed = client_loopback.post(
                "/api/internal/test-harness/telegram/inject",
                json={"video_path": self.test_video_path},
                headers={
                    "Authorization": "Bearer secret123",
                    "X-Forwarded-For": "203.0.113.1, 127.0.0.1",
                },
            )
            self.assertEqual(resp_spoofed.status_code, 403)

    # =========================================================================
    # NHÓM 2: SYNTHETIC INJECTION SUCCESS & TRANSCRIPT CAPTURE
    # =========================================================================

    async def test_synthetic_injection_success_and_transcript_event_stream(self):
        """
        Test Case 2.1: Bơm video giả lập thành công qua bot handler.
        Xác minh chuỗi transcript đầy đủ:
        1. send_message (initial progress)
        2. edit_message_text (progress callback)
        3. delete_message (auto-cleanup progress bar)
        4. send_video (gửi kết quả kèm AI Quality Audit caption)
        """
        clean_output_file = os.path.join(self.temp_dir, "clean_output_success.mp4")
        with open(clean_output_file, "wb") as f:
            f.write(b"\x00" * 2048)

        # Mock hành vi remove_text_from_video: phát callback tiến độ rồi trả về dict kết quả
        async def mock_remove_text(input_path_or_url, mode="auto", progress_callback=None, **kwargs):
            if progress_callback:
                if asyncio.iscoroutinefunction(progress_callback):
                    await progress_callback(50, "Đang khử chữ qua LaMa")
                    await progress_callback(100, "Mã hóa hoàn tất")
                else:
                    progress_callback(50, "Đang khử chữ qua LaMa")
                    progress_callback(100, "Mã hóa hoàn tất")

            return {
                "status": "ok",
                "output_path": clean_output_file,
                "delivery": "direct",
                "message": "Xóa text thành công",
                "processing_time_sec": 12.8,
                "critique": {
                    "metrics": {
                        "residual_ocr_words": 0,
                        "laplacian_texture_ratio": 0.99,
                        "temporal_flicker_ratio": 1.02,
                        "seam_discontinuity": 0.008,
                        "phash_drift": 1,
                    },
                    "vision_llm_score": 9.5,
                    "refinement_rounds": 1,
                },
            }

        self.mock_editor.remove_text_from_video = AsyncMock(side_effect=mock_remove_text)

        # Tạo Synthetic Video Session
        session = PendingVideoSession(
            chat_id="123456789",
            file_id="synthetic_file_id",
            temp_dir=self.temp_dir,
            video_path=self.test_video_path,
            metadata=VideoMetadata(
                filename="sample_test_video.mp4",
                duration=30,
                width=1280,
                height=720,
                file_size=4096,
            ),
            instruction="xóa chữ video",
        )

        # Gọi trực tiếp handler sản xuất của bot
        await self.bot._on_video_process_pipeline(
            chat_id="123456789",
            session=session,
            instruction="xóa chữ video",
        )

        # Xác minh transcript ghi nhận đúng thứ tự 4 sự kiện
        self.assertGreaterEqual(len(self.transcript), 4)

        actions = [ev["action"] for ev in self.transcript]
        self.assertEqual(actions[0], "send_message", "Sự kiện 1 phải là gửi tin nhắn tiến độ khởi đầu")
        self.assertIn("edit_message_text", actions, "Phải có sự kiện cập nhật tiến độ qua callback")
        self.assertIn("delete_message", actions, "Phải có sự kiện tự động xóa tin nhắn tiến độ khi xong")
        self.assertEqual(actions[-1], "send_video", "Sự kiện cuối phải là gửi video kết quả")

        # Xác minh caption thành phẩm có đầy đủ các chỉ số AI Quality Audit
        final_video_event = [ev for ev in self.transcript if ev["action"] == "send_video"][-1]
        caption = final_video_event.get("caption", "")
        self.assertIn("BẢNG TỔNG KẾT CHẤT LƯỢNG (AI QUALITY AUDIT)", caption)
        self.assertIn("Residual OCR:", caption)
        self.assertIn("0 từ tồn dư", caption)
        self.assertIn("Laplacian Texture:", caption)
        self.assertIn("Temporal Flicker:", caption)
        self.assertIn("12.8s", caption)

    def test_synthetic_injection_endpoint_e2e(self):
        """
        Test Case 2.2: Gọi endpoint POST /api/internal/test-harness/telegram/inject
        xác nhận response JSON trả về success=True, duration_sec > 0, và transcript hợp lệ.
        """
        clean_output_file = os.path.join(self.temp_dir, "clean_endpoint_output.mp4")
        with open(clean_output_file, "wb") as f:
            f.write(b"\x00" * 1024)

        app = FastAPI()
        app.state.telegram_bot = self.bot
        app.include_router(telegram_test_harness.router)

        async def mock_remove_text(input_path_or_url, **kwargs):
            return {
                "status": "ok",
                "output_path": clean_output_file,
                "delivery": "direct",
                "message": "Thành công",
                "processing_time_sec": 5.0,
            }

        self.mock_editor.remove_text_from_video = AsyncMock(side_effect=mock_remove_text)

        client = TestClient(app, client=("127.0.0.1", 54321))
        secret_key = "test_e2e_secret_key"

        with patch.object(settings, "ENABLE_TELEGRAM_TEST_HARNESS", True), \
             patch.object(settings, "TEST_HARNESS_SECRET_KEY", secret_key):

            resp = client.post(
                "/api/internal/test-harness/telegram/inject",
                json={
                    "chat_id": 123456789,
                    "caption": "xóa sạch text trong video giúp tôi",
                    "video_path": self.test_video_path,
                },
                headers={"Authorization": f"Bearer {secret_key}"},
            )

            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertTrue(data.get("success"), f"Injection thất bại: {data.get('error')}")
            self.assertGreater(data.get("duration_sec", 0.0), 0.0)
            self.assertIsInstance(data.get("transcript"), list)
            self.assertGreaterEqual(len(data["transcript"]), 1)

    # =========================================================================
    # NHÓM 3: ERROR HANDLING & DEFENSIVE GUARDS TESTS
    # =========================================================================

    async def test_error_handling_when_pipeline_returns_status_error(self):
        """
        Test Case 3.1: Khi pipeline trả về status='error',
        tiến trình phải tự động xóa progress message và gửi thông báo lỗi thân thiện.
        """
        self.mock_editor.remove_text_from_video = AsyncMock(return_value={
            "status": "error",
            "message": "Không tìm thấy vùng phụ đề hợp lệ để xử lý",
        })

        session = PendingVideoSession(
            chat_id="123456789",
            file_id="synthetic_file_id",
            temp_dir=self.temp_dir,
            video_path=self.test_video_path,
            metadata=VideoMetadata(
                filename="sample_test_video.mp4",
                duration=30,
                width=1280,
                height=720,
                file_size=4096,
            ),
            instruction="xóa chữ video",
        )

        await self.bot._on_video_process_pipeline(
            chat_id="123456789",
            session=session,
            instruction="xóa chữ video",
        )

        actions = [ev["action"] for ev in self.transcript]
        self.assertIn("send_message", actions)
        self.assertIn("delete_message", actions, "Phải xóa progress message trước khi báo lỗi")

        # Kiểm tra nội dung tin nhắn lỗi cuối
        last_msg = [ev for ev in self.transcript if ev["action"] == "send_message"][-1]
        self.assertIn("Không thể hoàn thành biên tập video", last_msg["text"])
        self.assertIn("Không tìm thấy vùng phụ đề hợp lệ", last_msg["text"])

    async def test_error_handling_when_pipeline_raises_exception(self):
        """
        Test Case 3.2: Khi pipeline ném ngoại lệ (Exception), bot không được crash,
        phải xóa progress message và thông báo lỗi tiếng Việt.
        """
        self.mock_editor.remove_text_from_video = AsyncMock(
            side_effect=RuntimeError("FFmpeg re-encoding error: disk full")
        )

        session = PendingVideoSession(
            chat_id="123456789",
            file_id="synthetic_file_id",
            temp_dir=self.temp_dir,
            video_path=self.test_video_path,
            metadata=VideoMetadata(
                filename="sample_test_video.mp4",
                duration=30,
                width=1280,
                height=720,
                file_size=4096,
            ),
            instruction="xóa chữ video",
        )

        await self.bot._on_video_process_pipeline(
            chat_id="123456789",
            session=session,
            instruction="xóa chữ video",
        )

        actions = [ev["action"] for ev in self.transcript]
        self.assertIn("delete_message", actions, "Phải dọn dẹp progress message khi gặp exception")
        last_msg = [ev for ev in self.transcript if ev["action"] == "send_message"][-1]
        self.assertIn("Có lỗi trong quá trình biên tập video", last_msg["text"])

    def test_defensive_guard_format_video_quality_caption_none_values(self):
        """
        Test Case 3.3: Thẩm tra chuyên sâu Defensive Guard tại _format_video_quality_caption.
        Đảm bảo không bao giờ ném AttributeError hoặc TypeError với mọi biến thể NoneType.
        """
        test_payloads = [
            # 1. critique và processing_time_sec đều bằng None
            {"critique": None, "processing_time_sec": None},
            # 2. metrics bằng None
            {"critique": {"metrics": None, "vision_llm_score": None}},
            # 3. Từng metric cụ thể nhận giá trị None
            {
                "critique": {
                    "metrics": {
                        "residual_ocr_words": None,
                        "laplacian_texture_ratio": None,
                        "temporal_flicker_ratio": None,
                        "seam_discontinuity": None,
                        "phash_drift": None,
                    },
                    "vision_llm_score": None,
                    "refinement_rounds": None,
                },
                "processing_time_sec": None,
            },
            # 4. Dict rỗng hoàn toàn
            {},
            # 5. Truyền None trực tiếp
            None,
        ]

        for idx, payload in enumerate(test_payloads, start=1):
            with self.subTest(payload_idx=idx):
                caption = self.bot._format_video_quality_caption(payload)
                self.assertIsInstance(caption, str)
                self.assertIn("BẢNG TỔNG KẾT CHẤT LƯỢNG (AI QUALITY AUDIT)", caption)
                self.assertIn("Residual OCR:", caption)
                self.assertIn("Laplacian Texture:", caption)
                self.assertIn("Temporal Flicker:", caption)
                self.assertIn("Seam Discontinuity:", caption)

    def test_format_video_quality_caption_residual_ocr_warning(self):
        """Kiểm chứng caption hiển thị trung thực khi residual_ocr > 0 và sạch hoàn toàn khi = 0."""
        # Nhánh 1: res_ocr == 0 -> Phải hiển thị (Sạch hoàn toàn)
        res_clean = {
            "critique": {
                "metrics": {"residual_ocr_words": 0},
                "vision_llm_score": 5.0,
            }
        }
        caption_clean = self.bot._format_video_quality_caption(res_clean)
        self.assertIn("<code>0 từ tồn dư</code> (Sạch hoàn toàn)", caption_clean)
        self.assertNotIn("Cảnh báo: Còn dư ảnh chữ", caption_clean)

        # Nhánh 2: res_ocr > 0 -> Phải hiển thị cảnh báo trung thực
        res_dirty = {
            "critique": {
                "metrics": {"residual_ocr_words": 436},
                "vision_llm_score": 2.0,
            }
        }
        caption_dirty = self.bot._format_video_quality_caption(res_dirty)
        self.assertIn("<code>436 từ tồn dư</code> (Cảnh báo: Còn dư ảnh chữ)", caption_dirty)
        self.assertNotIn("(Sạch hoàn toàn)", caption_dirty)


if __name__ == "__main__":
    unittest.main()
