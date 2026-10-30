"""
test_phase5_remediation.py — Adversarial Verification Suite for Phase 5 Remediation.

Features Verified (Anti-Gaming & Fail-Closed):
1. TestIterativeSelfCritiqueLoop:
   - Exact convergence penalty formula: Phi = 100*words + 50*max(0, 0.70-tex) + 30*max(0, seam-1.25) + 20*(5-vision).
   - 3-tier refinement strategy ladder recommendations (dilation +12px, flow 60 frames, guided filter/LaMa).
   - Real _execute_iterative_self_critique_loop early exit on clean pass (words=0, tex>=0.70, seam<=1.25, vision>=4).
   - Monotonic penalty evaluation: progress acceptance when Phi improves, rollback when regression occurs.
   - Invariant fail-closed: is_pass=False, status="unverified", verdict="FAIL_CLOSED_DEFECTS_REMAINING", uncleaned_regions populated.
2. TestMonotonicTelegramProgressUX:
   - Monotonic progress guarantee: p = max(p_prev, min(100, max(0, p_new))).
   - Send New, Delete Old pattern: sends new message, deletes previous message, cleans up on finish.
   - edit_message_text is eliminated in favour of transaction-safe message management.
   - Throttling & debouncing: suppresses updates within min_interval unless 100%.
3. TestDedicatedHarnessSecret:
   - Fail-closed 403 Forbidden when TELEGRAM_TEST_HARNESS_SECRET is empty/unconfigured.
   - Rejection of production JWT_SECRET (no fallback).
   - Rejection of invalid secret (401 Unauthorized).
   - Acceptance of dedicated secret via Bearer token and X-Telegram-Test-Harness-Secret header (200 OK).
4. TestSandboxedAssetStorage:
   - Resolution of valid files inside sandbox root.
   - Rejection of paths outside sandbox (403 Forbidden).
   - Rejection of '../' Path Traversal attacks (403 Forbidden).
   - Rejection of symlink escapes pointing outside sandbox (403 Forbidden).
   - Rejection of non-existent files inside sandbox (404 Not Found).
"""

import asyncio
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.routers import telegram_test_harness
from app.routers.telegram_test_harness import (
    get_dedicated_harness_secret,
    probe_real_video_metadata,
    resolve_and_verify_sandbox_path,
)
from app.services.telegram_bot import MonotonicProgressTracker, TelegramBot
from app.services.video_critique_engine import VideoCritiqueEngine
from app.services.video_editor_service import VideoEditorService, VideoJobContext


class TestIterativeSelfCritiqueLoop(unittest.TestCase):
    """Kiểm thử đối kháng Vòng lặp Tự Phản biện & Bậc thang Sửa đổi 3 Nấc (Finding B, D)."""

    def setUp(self):
        self.editor = VideoEditorService.__new__(VideoEditorService)
        self.critique_engine = VideoCritiqueEngine()
        self.temp_dir = tempfile.mkdtemp(prefix="test_critique_loop_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_convergence_penalty_calculation(self):
        """Kiểm tra công thức tính điểm phạt hội tụ Phi = 100*words + 50*max(0, 0.70-tex) + 30*max(0, seam-1.25) + 20*(5-vision)."""
        # Case 1: Video hoàn hảo sạch chữ, texture chuẩn, seam thấp, vision 5
        critique_clean = {
            "metrics": {
                "residual_ocr_words": 0,
                "laplacian_texture_ratio": 0.85,
                "seam_discontinuity": 1.05,
            }
        }
        vision_eval_5 = {"score": 5}
        phi, words, tex, seam, v = self.editor._calculate_convergence_penalty(critique_clean, vision_eval_5)
        self.assertEqual(words, 0)
        self.assertAlmostEqual(tex, 0.85)
        self.assertAlmostEqual(seam, 1.05)
        self.assertEqual(v, 5)
        self.assertAlmostEqual(phi, 0.0, places=3, msg="Clean video must have Phi = 0.0")

        # Case 2: Video có 2 chữ tồn dư, texture bị nhòe (0.50), seam lộ rõ (1.45), vision 3/5
        critique_defect = {
            "metrics": {
                "residual_ocr_words": 2,
                "laplacian_texture_ratio": 0.50,
                "seam_discontinuity": 1.45,
            }
        }
        vision_eval_3 = {"score": 3}
        # Expected Phi: 100*2 + 50*(0.70 - 0.50) + 30*(1.45 - 1.25) + 20*(5 - 3)
        # = 200 + 10 + 6 + 40 = 256.0
        phi_d, words_d, tex_d, seam_d, v_d = self.editor._calculate_convergence_penalty(critique_defect, vision_eval_3)
        self.assertEqual(words_d, 2)
        self.assertAlmostEqual(phi_d, 256.0, places=3)

        # Case 3: Metric bị thiếu (unverified) -> tính ít nhất 1 chữ tồn dư (fail-closed)
        critique_missing = {"metrics": {}}
        phi_m, words_m, _, _, _ = self.editor._calculate_convergence_penalty(critique_missing, None)
        self.assertGreaterEqual(words_m, 1, "Missing residual_ocr_words must be treated as defect")
        self.assertGreaterEqual(phi_m, 100.0)

    def test_recommend_refinement_strategy_3_tiers(self):
        """Kiểm tra Bậc thang Chiến lược Sửa đổi 3 Nấc trong VideoCritiqueEngine."""
        critique_stub = {
            "metrics": {
                "residual_ocr_words": 3,
                "laplacian_texture_ratio": 0.55,
                "seam_discontinuity": 1.35,
            },
            "worst_candidates": [{"frame_idx": 10, "roi_rect": (10, 20, 50, 60)}],
        }

        # Nấc 1 (Round 1): Mở rộng mask thích ứng (+12px top cho dấu tiếng Việt, +6px viền)
        strat_1 = self.critique_engine.recommend_refinement_strategy(critique_stub, round_num=1)
        self.assertIsNotNone(strat_1)
        self.assertEqual(strat_1.get("tier"), 1)
        self.assertEqual(strat_1.get("top_margin_px"), 12)
        self.assertEqual(strat_1.get("dilation_extra_px"), 6)

        # Nấc 2 (Round 2): Mở rộng tìm kiếm keyframe flow 60 frames, nới lỏng sai số 2.5px
        strat_2 = self.critique_engine.recommend_refinement_strategy(critique_stub, round_num=2)
        self.assertIsNotNone(strat_2)
        self.assertEqual(strat_2.get("tier"), 2)
        self.assertEqual(strat_2.get("max_temporal_window_frames"), 60)
        self.assertAlmostEqual(float(strat_2.get("max_fb_error", 0)), 2.5)

        # Nấc 3 (Round 3): Guided Filter / Micro-lattice synthesis hoặc Remote GPU LaMa
        strat_3 = self.critique_engine.recommend_refinement_strategy(critique_stub, round_num=3)
        self.assertIsNotNone(strat_3)
        self.assertEqual(strat_3.get("tier"), 3)
        self.assertTrue(strat_3.get("use_guided_filter", False) or strat_3.get("use_remote_lama", False))

    def test_iterative_loop_early_exit_on_clean_candidate(self):
        """Vòng lặp tự phản biện phải thoát sớm (early stop) khi candidate vòng 0 đạt chuẩn sạch."""
        input_vid = Path(self.temp_dir) / "input.mp4"
        candidate_vid = Path(self.temp_dir) / "candidate_0.mp4"
        output_vid = Path(self.temp_dir) / "output.mp4"
        input_vid.write_bytes(b"dummy_input_stream")
        candidate_vid.write_bytes(b"dummy_candidate_clean")

        reports = []
        def mock_report(p, text):
            reports.append((p, text))

        context = VideoJobContext(job_id="test_early_clean")

        mock_clean_eval = {
            "metrics": {
                "residual_ocr_words": 0,
                "laplacian_texture_ratio": 0.88,
                "seam_discontinuity": 1.10,
                "total_sampled_frames": 10,
            },
            "worst_candidates": [],
        }
        mock_vision = {"score": 5, "analysis": "flawless"}

        with patch("app.services.video_critique_engine.VideoCritiqueEngine.evaluate_video_stream_sync", return_value=mock_clean_eval), \
             patch("app.services.video_critique_engine.VideoCritiqueEngine.critique_worst_crops_sync", return_value=mock_vision):

            res = self.editor._execute_iterative_self_critique_loop(
                input_file=input_vid,
                initial_candidate_video=candidate_vid,
                final_output_file=output_vid,
                report=mock_report,
                context=context,
                max_refinement_rounds=2,
            )

            self.assertTrue(res.get("is_pass"), "Clean candidate must result in is_pass=True")
            self.assertEqual(res.get("status"), "ok")
            self.assertEqual(res.get("refinement_rounds"), 0, "No extra repair rounds should execute when candidate is clean")
            self.assertTrue(output_vid.exists())

    def test_iterative_loop_escalation_and_monotonic_rollback(self):
        """
        Vòng lặp tự phản biện:
        - Vòng 1 phát hiện chữ tồn dư -> kích hoạt Nấc 1 và cải thiện chất lượng (Phi giảm).
        - Vòng 2 bị thoái hóa chất lượng (Phi tăng hoặc words tăng) -> Lập tức rollback về vòng 1.
        """
        input_vid = Path(self.temp_dir) / "input.mp4"
        candidate_vid = Path(self.temp_dir) / "candidate_0.mp4"
        output_vid = Path(self.temp_dir) / "output.mp4"
        input_vid.write_bytes(b"dummy_input_stream")
        candidate_vid.write_bytes(b"round_0_bytes")

        context = VideoJobContext(job_id="test_escalation_rollback")

        # Mô phỏng: Round 0: 3 words -> Round 1: 1 word (improves) -> Round 2: 4 words (regression!)
        eval_round_0 = {
            "metrics": {"residual_ocr_words": 3, "laplacian_texture_ratio": 0.60, "seam_discontinuity": 1.30},
            "worst_candidates": [{"frame_idx": 1, "roi_rect": (0, 0, 10, 10), "residual_text": "DEF1"}],
        }
        eval_round_1 = {
            "metrics": {"residual_ocr_words": 1, "laplacian_texture_ratio": 0.75, "seam_discontinuity": 1.15},
            "worst_candidates": [{"frame_idx": 1, "roi_rect": (0, 0, 10, 10), "residual_text": "DEF2"}],
        }
        eval_round_2 = {
            "metrics": {"residual_ocr_words": 4, "laplacian_texture_ratio": 0.40, "seam_discontinuity": 1.60},
            "worst_candidates": [{"frame_idx": 1, "roi_rect": (0, 0, 10, 10), "residual_text": "DEF3"}],
        }

        call_idx = 0
        def side_effect_eval(*args, **kwargs):
            nonlocal call_idx
            idx = call_idx
            call_idx += 1
            if idx == 0:
                return dict(eval_round_0)
            elif idx == 1:
                return dict(eval_round_1)
            else:
                return dict(eval_round_2)

        def mock_apply_refinement(input_video, source_cleaned_video, target_output_video, strategy, worst_candidates, **kwargs):
            target_output_video.write_bytes(f"refined_bytes_tier_{strategy.get('tier', 1)}".encode())

        with patch("app.services.video_critique_engine.VideoCritiqueEngine.evaluate_video_stream_sync", side_effect=side_effect_eval), \
             patch("app.services.video_critique_engine.VideoCritiqueEngine.critique_worst_crops_sync", return_value={"score": 3}), \
             patch.object(self.editor, "_apply_targeted_refinement", side_effect=mock_apply_refinement):

            res = self.editor._execute_iterative_self_critique_loop(
                input_file=input_vid,
                initial_candidate_video=candidate_vid,
                final_output_file=output_vid,
                report=lambda p, t: None,
                context=context,
                max_refinement_rounds=2,
            )

            # Rollback: Best candidate được giữ là Round 1 (residual words = 1) chứ không phải Round 2 (residual words = 4)
            self.assertEqual(res.get("metrics", {}).get("residual_ocr_words"), 1, "Must rollback to Round 1 metrics")
            # Fail-closed: Vì vẫn còn 1 chữ tồn dư, is_pass phải là False
            self.assertFalse(res.get("is_pass"), "Must fail-closed when words still remain")
            self.assertEqual(res.get("status"), "unverified")
            self.assertEqual(res.get("verdict"), "FAIL_CLOSED_DEFECTS_REMAINING")
            self.assertTrue(len(res.get("uncleaned_regions", [])) > 0)


class TestMonotonicTelegramProgressUX(unittest.IsolatedAsyncioTestCase):
    """Kiểm thử đối kháng Bộ Theo Dõi Tiến Độ Đơn Điệu Ngặt & Send New, Delete Old (Finding G)."""

    async def asyncSetUp(self):
        self.bot = TelegramBot.__new__(TelegramBot)
        self.bot.token = "fake_token"
        self.bot.chat_id = "123456789"
        self.transcript = []

        async def fake_send_message(chat_id, text, **kwargs):
            msg_id = 1000 + len(self.transcript) + 1
            self.transcript.append({"action": "send_message", "chat_id": chat_id, "text": text, "message_id": msg_id})
            return {"message_id": msg_id}

        async def fake_delete_message(chat_id, message_id):
            self.transcript.append({"action": "delete_message", "chat_id": chat_id, "message_id": message_id})
            return True

        self.bot.send_message = AsyncMock(side_effect=fake_send_message)
        self.bot.delete_message = AsyncMock(side_effect=fake_delete_message)
        self.bot.edit_message_text = AsyncMock(side_effect=AssertionError("edit_message_text must NOT be used in P6 Monotonic UX"))

    async def test_telegram_progress_monotonicity_and_send_new_delete_old(self):
        """
        Kiểm thử đối kháng UX Tiến độ:
        - Tiến độ p không bao giờ lùi bước: chuỗi [20, 40, 30, 70, 60, 100] -> [20, 40, 40, 70, 70, 100].
        - edit_message_text hoàn toàn bị loại bỏ.
        - Send New, Delete Old: Mỗi bản tin mới gửi đi thì bản tin cũ bị xóa.
        """
        tracker = MonotonicProgressTracker(bot=self.bot, chat_id="123456789", min_interval_sec=0.0)

        reported_steps = [
            (20, "Phân tích khung hình"),
            (40, "Khử chữ dải 1"),
            (30, "Lỗi lùi tiến độ giả lập"),
            (70, "Flow propagation"),
            (60, "Lỗi lùi tiến độ giả lập 2"),
            (100, "Hoàn tất biên tập"),
        ]

        for p, text in reported_steps:
            await tracker.report(p, text)

        # 1. Tuyệt đối không gọi edit_message_text
        self.bot.edit_message_text.assert_not_called()

        # 2. Kiểm tra chuỗi phần trăm tăng đơn điệu ngặt
        send_events = [ev for ev in self.transcript if ev["action"] == "send_message"]
        extracted_percentages = []
        for ev in send_events:
            match = re.search(r"\((\d+)%\)", ev["text"])
            if match:
                extracted_percentages.append(int(match.group(1)))

        self.assertEqual(len(extracted_percentages), len(reported_steps))
        for i in range(len(extracted_percentages) - 1):
            self.assertLessEqual(
                extracted_percentages[i],
                extracted_percentages[i + 1],
                f"Tiến độ bị lùi: {extracted_percentages[i]}% > {extracted_percentages[i+1]}%",
            )

        # 3. Kiểm tra cơ chế Send New, Delete Old
        delete_events = [ev for ev in self.transcript if ev["action"] == "delete_message"]
        self.assertEqual(len(delete_events), len(send_events) - 1)

        # 4. Khi cleanup/finish: tin nhắn cuối cùng phải được xóa sạch
        await tracker.cleanup()
        delete_events_after = [ev for ev in self.transcript if ev["action"] == "delete_message"]
        self.assertEqual(len(delete_events_after), len(send_events), "Cleanup must delete final progress message")

    async def test_throttling_suppresses_rapid_updates(self):
        """Kiểm tra throttling: các cập nhật trung gian diễn ra nhanh hơn min_interval_sec bị bỏ qua."""
        tracker = MonotonicProgressTracker(bot=self.bot, chat_id="123456789", min_interval_sec=2.0)

        # Lần 1: Được gửi
        await tracker.report(10, "Bước 1")
        # Lần 2 (ngay lập tức): Bị throttle bỏ qua
        await tracker.report(20, "Bước 2")
        # Lần 3 (100% hoàn tất): Bỏ qua rate limit và gửi ngay
        await tracker.report(100, "Hoàn tất")

        send_events = [ev for ev in self.transcript if ev["action"] == "send_message"]
        self.assertEqual(len(send_events), 2, "Bước 2 phải bị throttle, chỉ có 10% và 100% được gửi")


class TestDedicatedHarnessSecret(unittest.TestCase):
    """Kiểm thử đối kháng Cơ chế Bảo mật Khóa Bí Mật Riêng Biệt (Dedicated Secret Guard)."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_harness_secret_")
        self.sandbox_dir = os.path.join(self.temp_dir, "sandboxed_harness")
        os.makedirs(self.sandbox_dir, exist_ok=True)
        self.valid_video = os.path.join(self.sandbox_dir, "test.mp4")
        Path(self.valid_video).write_bytes(b"\x00" * 1024)

        self.app = FastAPI()
        self.app.include_router(telegram_test_harness.router)
        self.client = TestClient(self.app, client=("127.0.0.1", 54321))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_fail_closed_when_secret_empty(self):
        """Fail-Closed: Khi TELEGRAM_TEST_HARNESS_SECRET chưa cấu hình -> 403 Forbidden."""
        with patch.object(settings, "ENABLE_TELEGRAM_TEST_HARNESS", True), \
             patch.object(settings, "TELEGRAM_TEST_HARNESS_SECRET", ""), \
             patch.object(settings, "TEST_HARNESS_SECRET_KEY", ""):

            resp = self.client.post(
                "/api/internal/test-harness/telegram/inject",
                json={"video_path": self.valid_video},
                headers={"Authorization": "Bearer dummy_token"},
            )
            self.assertEqual(resp.status_code, 403)
            self.assertIn("not configured", resp.json().get("detail", "").lower())

    def test_reject_production_jwt_secret(self):
        """Từ chối dùng JWT_SECRET của production (cấm fallback)."""
        with patch.object(settings, "ENABLE_TELEGRAM_TEST_HARNESS", True), \
             patch.object(settings, "TELEGRAM_TEST_HARNESS_SECRET", "dedicated_secret_999"), \
             patch.object(settings, "TEST_HARNESS_SECRET_KEY", ""), \
             patch.object(settings, "JWT_SECRET", "prod_jwt_secret_888"):

            resp = self.client.post(
                "/api/internal/test-harness/telegram/inject",
                json={"video_path": self.valid_video},
                headers={"Authorization": "Bearer prod_jwt_secret_888"},
            )
            self.assertEqual(resp.status_code, 401)
            self.assertIn("invalid", resp.json().get("detail", "").lower())

    def test_reject_invalid_secret(self):
        """Từ chối khi secret không đúng."""
        with patch.object(settings, "ENABLE_TELEGRAM_TEST_HARNESS", True), \
             patch.object(settings, "TELEGRAM_TEST_HARNESS_SECRET", "dedicated_secret_999"), \
             patch.object(settings, "TEST_HARNESS_SECRET_KEY", ""):

            resp = self.client.post(
                "/api/internal/test-harness/telegram/inject",
                json={"video_path": self.valid_video},
                headers={"Authorization": "Bearer wrong_secret_123"},
            )
            self.assertEqual(resp.status_code, 401)

    def test_accept_valid_dedicated_secret(self):
        """Chấp nhận xác thực khi secret riêng biệt chính xác."""
        bot_mock = MagicMock()
        bot_mock.chat_id = "123456789"
        bot_mock._process_update = AsyncMock()
        self.app.state.telegram_bot = bot_mock

        with patch.object(settings, "ENABLE_TELEGRAM_TEST_HARNESS", True), \
             patch.object(settings, "TELEGRAM_TEST_HARNESS_SECRET", "dedicated_secret_999"), \
             patch.object(settings, "TEST_HARNESS_SECRET_KEY", ""), \
             patch("app.routers.telegram_test_harness.resolve_and_verify_sandbox_path", return_value=self.valid_video), \
             patch("app.routers.telegram_test_harness.probe_real_video_metadata", return_value={"width": 720, "height": 1280, "duration": 5, "file_size": 1024}):

            # Thử nghiệm qua Header Bearer
            resp = self.client.post(
                "/api/internal/test-harness/telegram/inject",
                json={"video_path": self.valid_video},
                headers={"Authorization": "Bearer dedicated_secret_999"},
            )
            self.assertEqual(resp.status_code, 200)

            # Thử nghiệm qua Header X-Telegram-Test-Harness-Secret
            resp2 = self.client.post(
                "/api/internal/test-harness/telegram/inject",
                json={"video_path": self.valid_video},
                headers={"X-Telegram-Test-Harness-Secret": "dedicated_secret_999"},
            )
            self.assertEqual(resp2.status_code, 200)


class TestSandboxedAssetStorage(unittest.TestCase):
    """Kiểm thử đối kháng Quản lý Tệp Sandbox & Chống Path Traversal (Finding G)."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_sandbox_storage_")
        self.sandbox_dir = os.path.join(self.temp_dir, "sandboxed_harness")
        os.makedirs(self.sandbox_dir, exist_ok=True)
        self.valid_video = os.path.join(self.sandbox_dir, "sample.mp4")
        Path(self.valid_video).write_bytes(b"\x00" * 512)

        self.outside_secret = os.path.join(self.temp_dir, "outside_etc_shadow")
        Path(self.outside_secret).write_text("root:leaked_hash")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_valid_file_in_sandbox_resolves(self):
        """Tệp hợp lệ nằm bên trong sandbox phải được phân giải thành công."""
        res = resolve_and_verify_sandbox_path("sample.mp4", custom_sandbox_dir=self.sandbox_dir)
        self.assertEqual(res, os.path.realpath(self.valid_video))

    def test_reject_file_outside_sandbox(self):
        """Từ chối 403 Forbidden đối với tệp tuyệt đối nằm ngoài sandbox."""
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            resolve_and_verify_sandbox_path(self.outside_secret, custom_sandbox_dir=self.sandbox_dir)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("path traversal", ctx.exception.detail.lower())

    def test_reject_dotdot_path_traversal(self):
        """Từ chối 403 Forbidden đối với đường dẫn chứa '../' nhằm thoát khỏi sandbox."""
        from fastapi import HTTPException
        traversal = os.path.join(self.sandbox_dir, "..", "outside_etc_shadow")
        with self.assertRaises(HTTPException) as ctx:
            resolve_and_verify_sandbox_path(traversal, custom_sandbox_dir=self.sandbox_dir)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_reject_symlink_pointing_outside(self):
        """Từ chối 403 Forbidden đối với symbolic link bên trong sandbox trỏ ra ngoài."""
        from fastapi import HTTPException
        symlink_target = os.path.join(self.sandbox_dir, "symlink_escape.mp4")
        try:
            os.symlink(self.outside_secret, symlink_target)
        except OSError:
            # Bỏ qua nếu môi trường Windows không có quyền Developer Mode tạo symlink
            return

        with self.assertRaises(HTTPException) as ctx:
            resolve_and_verify_sandbox_path(symlink_target, custom_sandbox_dir=self.sandbox_dir)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_reject_nonexistent_file_404(self):
        """Trả về 404 Not Found nếu tệp nằm trong sandbox nhưng không tồn tại."""
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            resolve_and_verify_sandbox_path("non_existent.mp4", custom_sandbox_dir=self.sandbox_dir)
        self.assertEqual(ctx.exception.status_code, 404)


class TestFeature23StateSanitization(unittest.IsolatedAsyncioTestCase):
    """Kiểm tra Feature 23: Triệt tiêu shared mutable state & Scoped ContextVar."""

    async def test_scoped_allowed_chat_override_restores_state(self):
        """ScopedAllowedChatOverride phải khôi phục chat permissions ngay cả khi có exception."""
        from app.services.telegram_bot import ScopedAllowedChatOverride, TelegramBot

        bot = TelegramBot.__new__(TelegramBot)
        bot.allowed_chat_ids = {"100", "200"}

        self.assertFalse(bot.is_chat_authorized("999"))

        try:
            async with ScopedAllowedChatOverride("999"):
                self.assertTrue(bot.is_chat_authorized("999"))
                raise ValueError("Simulated failure in test harness")
        except ValueError:
            pass

        self.assertFalse(bot.is_chat_authorized("999"), "Chat permission must be restored after exception")

    def test_job_context_isolation_roi_cache(self):
        """VideoJobContext phải cô lập roi_inpaint_cache per-job mà không đè lên singleton."""
        ctx1 = VideoJobContext(job_id="job_1")
        ctx2 = VideoJobContext(job_id="job_2")

        ctx1.roi_inpaint_cache["key1"] = "val1"
        self.assertNotIn("key1", ctx2.roi_inpaint_cache)

        editor = VideoEditorService.__new__(VideoEditorService)
        # Property _roi_inpaint_cache trả về dict nhưng không chia sẻ state
        self.assertIsInstance(editor._roi_inpaint_cache, dict)


class TestFeature24BitExactAudioAndProcessSafety(unittest.TestCase):
    """Kiểm tra Feature 24: Bit-exact audio copy 100% & an toàn tiến trình subprocess."""

    def test_tesseract_timeout_in_codebase(self):
        """Đảm bảo mọi lời gọi pytesseract.image_to_data đều cấu hình timeout=15."""
        import inspect
        src = inspect.getsource(VideoEditorService._detect_text_boxes_image_sync)
        self.assertIn("timeout=15", src)

        src2 = inspect.getsource(VideoEditorService._count_ocr_words)
        self.assertIn("timeout=15", src2)


if __name__ == "__main__":
    unittest.main()
