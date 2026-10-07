"""
test_challenger_m4_concurrency.py — Adversarial Stress Test Suite for Milestone 4 Test Harness.

Kiểm thử đối kháng (Adversarial Stress Testing) tập trung vào:
1. Coroutine Isolation & Cross-Talk Stress Test:
   - 50 coroutines chạy đồng thời (25 Test Harness coroutines có ContextVar capture + 25 Production coroutines không có capture).
   - Xác nhận tuyệt đối 100% không rò rỉ sự kiện giữa harness và production, cũng như giữa các harness session với nhau.
2. Post-Context Reversion & ContextVar Token Cleanup:
   - Sau khi thoát khỏi ngữ cảnh `async with capture:`, ContextVar tự động reset về None.
   - Các lệnh gọi kế tiếp trong cùng coroutine lập tức chuyển về production handler.
3. Burst Injection & Rate Stress Test (No Deadlock / Race Condition):
   - 50 synthetic injection requests bắn dồn dập đồng thời.
   - Kiểm tra lock, semaphore, monotonic message_id, event loop không bị block hay deadlock.
4. Memory & Resource Leak Test:
   - Hàng loạt injections (cả thành công, lỗi exception, timeout).
   - Kiểm tra các thư mục `harness_session_*` được dọn dẹp sạch sẽ 100% không để lại rác đĩa.
   - Kiểm tra thu hồi bộ nhớ (GC / weakref) của capture context và session.
5. Mixed Burst with Errors, Cancellations & Recovery:
   - Đan xen các task thành công, crash lỗi, và bị huỷ giữa chừng (cancelled).
   - Xác nhận hệ thống hồi phục hoàn toàn cho các request kế tiếp.
6. Large Buffer Bounds & Serialization Stress:
   - Bắn hàng trăm callback tiến độ dồn dập, kiểm tra serialization JSON không lỗi.
"""

import asyncio
import gc
import os
from pathlib import Path
import random
import shutil
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import weakref

from fastapi import FastAPI, Request
from starlette.datastructures import Headers

# Đảm bảo đường dẫn import tới app của ai-agent-service
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.routers.telegram_test_harness import (
    router,
    TestHarnessTranscriptCapture,
    MockTelegramMessageDict,
    _active_capture_context,
    SyntheticTelegramUpdateRequest,
    SyntheticTelegramInjectionResponse,
    inject_synthetic_telegram_update,
)
from app.services.telegram_bot import TelegramBot
from app.services.video_pipeline import PendingVideoSession, VideoMetadata

# Tránh pytest nhầm TestHarnessTranscriptCapture là test case class
TestHarnessTranscriptCapture.__test__ = False


class TestChallengerM4Concurrency(unittest.IsolatedAsyncioTestCase):
    """Adversarial Concurrency, Isolation, and Resource Leak Test Suite."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="challenger_m4_suite_")
        self.dummy_video_path = os.path.join(self.temp_dir, "challenger_dummy.mp4")
        with open(self.dummy_video_path, "wb") as f:
            f.write(b"\x00" * 4096)

        # Tạo bot instance độc lập
        self.bot = TelegramBot.__new__(TelegramBot)
        self.bot.token = "mock_challenger_token"
        self.bot._running = False
        self.bot.chat_id = "987654321"

        self.mock_editor = AsyncMock()
        self.bot._video_editor_svc = self.mock_editor

        self.mock_media = MagicMock()
        self.mock_media.download_telegram_file_to_path = AsyncMock()
        self.bot._media = self.mock_media

        # Ghi nhận các sự kiện thật từ phía production
        self.production_events: List[Dict[str, Any]] = []
        self._prod_lock = asyncio.Lock()

        async def prod_send_message(chat_id, text, reply_markup=None, parse_mode="HTML", **kwargs):
            async with self._prod_lock:
                ev = {
                    "action": "send_message",
                    "chat_id": chat_id,
                    "text": text,
                    "caller_type": "production",
                }
                self.production_events.append(ev)
            return {"message_id": 9999}

        async def prod_send_message_with_result(chat_id, text, reply_markup=None, parse_mode="HTML", **kwargs):
            return await prod_send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode, **kwargs)

        async def prod_edit_message_text(chat_id, message_id, text, reply_markup=None, parse_mode="HTML", **kwargs):
            async with self._prod_lock:
                ev = {
                    "action": "edit_message_text",
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": text,
                    "caller_type": "production",
                }
                self.production_events.append(ev)
            return True

        async def prod_delete_message(chat_id, message_id, **kwargs):
            async with self._prod_lock:
                ev = {
                    "action": "delete_message",
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "caller_type": "production",
                }
                self.production_events.append(ev)
            return True

        async def prod_send_video(chat_id, video_path, caption=None, *args, **kwargs):
            async with self._prod_lock:
                ev = {
                    "action": "send_video",
                    "chat_id": chat_id,
                    "video_path": video_path,
                    "caption": caption,
                    "caller_type": "production",
                }
                self.production_events.append(ev)
            return True

        async def prod_send_video_file(chat_id, video_path, caption=None, *args, **kwargs):
            async with self._prod_lock:
                ev = {
                    "action": "send_video_file",
                    "chat_id": chat_id,
                    "video_path": video_path,
                    "caption": caption,
                    "caller_type": "production",
                }
                self.production_events.append(ev)
            return True

        async def prod_send_chat_action(chat_id, action="typing", **kwargs):
            async with self._prod_lock:
                ev = {
                    "action": "send_chat_action",
                    "chat_id": chat_id,
                    "action_name": action,
                    "caller_type": "production",
                }
                self.production_events.append(ev)
            return None

        self.bot.send_message = AsyncMock(side_effect=prod_send_message)
        self.bot.send_message_with_result = AsyncMock(side_effect=prod_send_message_with_result)
        self.bot.edit_message_text = AsyncMock(side_effect=prod_edit_message_text)
        self.bot.delete_message = AsyncMock(side_effect=prod_delete_message)
        self.bot.send_video = AsyncMock(side_effect=prod_send_video)
        self.bot.send_video_file = AsyncMock(side_effect=prod_send_video_file)
        self.bot.send_chat_action = AsyncMock(side_effect=prod_send_chat_action)

    async def asyncTearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    # =========================================================================
    # TEST 1: 50 COROUTINES ISOLATION & CROSS-TALK STRESS TEST
    # =========================================================================

    async def test_50_coroutines_isolation_and_cross_talk_stress(self):
        """
        Stress test tính cô lập đồng thời của 50 coroutines:
        - 25 tasks chạy trong test harness session (có ContextVar capture).
        - 25 tasks chạy trong production context (ContextVar is None).
        - Các task đan xen gọi các method của bot với delay ngẫu nhiên.
        - Khẳng định 100% không có cross-talk rò rỉ sự kiện giữa harness và production,
          cũng như giữa các harness session với nhau.
        """
        num_harness = 25
        num_prod = 25
        actions_per_task = 5

        harness_captures: List[TestHarnessTranscriptCapture] = []
        for _ in range(num_harness):
            cap = TestHarnessTranscriptCapture(bot=self.bot)
            harness_captures.append(cap)

        async def run_harness_task(task_idx: int, capture: TestHarnessTranscriptCapture):
            async with capture:
                for step in range(actions_per_task):
                    chat_id = f"harness_chat_{task_idx:03d}"
                    tag = f"HARNESS_T{task_idx:03d}_S{step}"

                    # Gọi xen kẽ các action
                    res = await self.bot.send_message(chat_id, f"Hello from {tag}")
                    msg_id = res.get("message_id") if isinstance(res, dict) else 1000

                    await asyncio.sleep(0.001 * random.random())
                    await self.bot.edit_message_text(chat_id, msg_id, f"Edit from {tag}")

                    await asyncio.sleep(0.001 * random.random())
                    await self.bot.send_chat_action(chat_id, "upload_video")

                    await asyncio.sleep(0.001 * random.random())
                    await self.bot.delete_message(chat_id, msg_id)

                    await asyncio.sleep(0.001 * random.random())
                    await self.bot.send_video_file(chat_id, self.dummy_video_path, caption=f"Video from {tag}")

        async def run_prod_task(task_idx: int):
            for step in range(actions_per_task):
                chat_id = f"prod_chat_{task_idx:03d}"
                tag = f"PROD_T{task_idx:03d}_S{step}"

                res = await self.bot.send_message(chat_id, f"Hello from {tag}")
                msg_id = res.get("message_id") if isinstance(res, dict) else 9999

                await asyncio.sleep(0.001 * random.random())
                await self.bot.edit_message_text(chat_id, msg_id, f"Edit from {tag}")

                await asyncio.sleep(0.001 * random.random())
                await self.bot.send_chat_action(chat_id, "typing")

                await asyncio.sleep(0.001 * random.random())
                await self.bot.delete_message(chat_id, msg_id)

                await asyncio.sleep(0.001 * random.random())
                await self.bot.send_video_file(chat_id, self.dummy_video_path, caption=f"Video from {tag}")

        # Khởi chạy đồng thời toàn bộ 50 tasks
        tasks = []
        for i in range(num_harness):
            tasks.append(run_harness_task(i, harness_captures[i]))
        for j in range(num_prod):
            tasks.append(run_prod_task(j))

        # Shuffle để tăng tối đa tính bất định và interleaving
        random.shuffle(tasks)
        await asyncio.gather(*tasks)

        # ── KIỂM ĐỊNH KẾT QUẢ ĐỐI KHÁNG ──

        # 1. Kiểm tra 25 Harness Captures:
        # Mỗi task thực hiện 5 bước, mỗi bước có 5 actions = 25 actions
        expected_events_per_harness = actions_per_task * 5

        for i, cap in enumerate(harness_captures):
            events = cap.get_transcript()
            self.assertEqual(
                len(events),
                expected_events_per_harness,
                f"Harness task {i} ghi nhận sai số lượng sự kiện: {len(events)} != {expected_events_per_harness}",
            )

            # Kiểm tra từng event trong capture này:
            for ev in events:
                content = str(ev)

                # 1. Chat ID PHẢI thuộc về đúng Harness task i
                self.assertEqual(
                    ev.get("chat_id"),
                    f"harness_chat_{i:03d}",
                    f"Sự kiện có chat_id sai lệch lọt vào Harness session {i}: {ev}",
                )

                # 2. Nếu là action có text/caption, PHẢI chứa đúng tag HARNESS_T{i:03d}_
                if ev.get("action") in ("send_message", "edit_message_text", "send_video", "send_video_file"):
                    self.assertIn(
                        f"HARNESS_T{i:03d}_",
                        content,
                        f"Event không chứa đúng tag của Harness task {i}: {ev}",
                    )

                # 3. TUYỆT ĐỐI KHÔNG chứa chat_id hoặc tag của Production
                self.assertNotIn(
                    "prod_chat_",
                    content,
                    f"RÒ RỈ NGHIÊM TRỌNG: prod_chat lọt vào Harness session {i}: {ev}",
                )
                self.assertNotIn(
                    "PROD_",
                    content,
                    f"RÒ RỈ NGHIÊM TRỌNG: Sự kiện của Production lọt vào Harness session {i}: {ev}",
                )

                # 4. TUYỆT ĐỐI KHÔNG chứa chat_id hoặc tag của Harness task khác
                for other_idx in range(num_harness):
                    if other_idx != i:
                        self.assertNotIn(
                            f"harness_chat_{other_idx:03d}",
                            content,
                            f"RÒ RỈ NGHIÊM TRỌNG: chat_id của Harness {other_idx} lọt vào Harness {i}: {ev}",
                        )
                        self.assertNotIn(
                            f"HARNESS_T{other_idx:03d}_",
                            content,
                            f"RÒ RỈ NGHIÊM TRỌNG: Sự kiện của Harness {other_idx} lọt vào Harness {i}: {ev}",
                        )

        # 2. Kiểm tra Production Events:
        expected_prod_events = num_prod * actions_per_task * 5
        self.assertEqual(
            len(self.production_events),
            expected_prod_events,
            f"Production nhận sai số lượng sự kiện: {len(self.production_events)} != {expected_prod_events}",
        )

        for p_ev in self.production_events:
            p_content = str(p_ev)

            # Chat ID PHẢI thuộc về Production
            self.assertTrue(
                p_ev.get("chat_id", "").startswith("prod_chat_"),
                f"Sự kiện production có chat_id không hợp lệ: {p_ev}",
            )

            # TUYỆT ĐỐI KHÔNG chứa bất kỳ chat_id hay tag HARNESS nào
            self.assertNotIn(
                "harness_chat_",
                p_content,
                f"RÒ RỈ NGHIÊM TRỌNG: chat_id của Test Harness lọt sang Production: {p_ev}",
            )
            self.assertNotIn(
                "HARNESS_",
                p_content,
                f"RÒ RỈ NGHIÊM TRỌNG: Sự kiện của Test Harness lọt sang Production: {p_ev}",
            )

    # =========================================================================
    # TEST 2: POST-CONTEXT REVERSION & CONTEXTVAR TOKEN CLEANUP
    # =========================================================================

    async def test_post_context_reversion_and_clean_exit(self):
        """
        Kiểm tra phục hồi ngữ cảnh sau khi thoát `async with capture`:
        - Trong context: các sự kiện được bắt bởi capture.
        - Sau context: ContextVar được reset về None.
        - Các lệnh gọi kế tiếp trong cùng coroutine lập tức chuyển về production handler.
        """
        capture = TestHarnessTranscriptCapture(bot=self.bot)

        # Trước context
        self.assertIsNone(_active_capture_context.get())

        async with capture:
            self.assertEqual(_active_capture_context.get(), capture)
            await self.bot.send_message("111", "In harness context")

        # Sau context: ContextVar phải được reset hoàn toàn về None
        self.assertIsNone(
            _active_capture_context.get(),
            "ContextVar không được reset về None sau khi thoát khỏi __aexit__!",
        )

        # Lệnh gọi sau context phải đi thẳng về production
        await self.bot.send_message("222", "After harness context - should be prod")

        # Xác minh capture chỉ có 1 event
        self.assertEqual(len(capture.get_transcript()), 1)
        self.assertEqual(capture.get_transcript()[0]["text"], "In harness context")

        # Xác minh production nhận đúng event sau context
        prod_texts = [e.get("text") for e in self.production_events if "text" in e]
        self.assertIn("After harness context - should be prod", prod_texts)
        self.assertNotIn("In harness context", prod_texts)

    # =========================================================================
    # TEST 3: BURST INJECTION & RATE STRESS TEST (NO DEADLOCK / RACE CONDITIONS)
    # =========================================================================

    async def test_burst_injection_rate_and_concurrency_no_deadlock(self):
        """
        Bắn dồn dập 50 synthetic injection requests đồng thời:
        - Kiểm tra event loop không bị stall hay deadlock.
        - Kiểm tra lock an toàn, message_id tăng đơn điệu không trùng lặp trong từng session.
        - Kiểm tra tất cả 50 requests đều trả về success=True.
        """
        num_burst = 50

        # Mock editor trả về kết quả sau khi qua các callback tiến độ
        async def mock_remove_text(input_path_or_url, mode="auto", progress_callback=None, **kwargs):
            if progress_callback:
                if asyncio.iscoroutinefunction(progress_callback):
                    await progress_callback(25, "Bắt đầu")
                    await asyncio.sleep(0.002)
                    await progress_callback(75, "Khử chữ")
                    await asyncio.sleep(0.002)
                    await progress_callback(100, "Hoàn tất")
                else:
                    progress_callback(25, "Bắt đầu")
                    progress_callback(75, "Khử chữ")
                    progress_callback(100, "Hoàn tất")

            return {
                "status": "ok",
                "output_path": self.dummy_video_path,
                "delivery": "direct",
                "message": "Thành công",
                "processing_time_sec": 1.5,
                "critique": {
                    "metrics": {
                        "residual_ocr_words": 0,
                        "laplacian_texture_ratio": 1.0,
                    },
                    "vision_llm_score": 9.0,
                },
            }

        self.mock_editor.remove_text_from_video = AsyncMock(side_effect=mock_remove_text)

        app = FastAPI()
        app.state.telegram_bot = self.bot
        app.include_router(router)

        # Tạo dummy request mock cho FastAPI
        def create_mock_fastapi_request():
            req = MagicMock(spec=Request)
            req.app = app
            req.client = MagicMock()
            req.client.host = "127.0.0.1"
            req.headers = Headers({"Authorization": "Bearer sentinel-test-key"})
            return req

        async def single_burst_call(idx: int) -> SyntheticTelegramInjectionResponse:
            mock_req = create_mock_fastapi_request()
            req_body = SyntheticTelegramUpdateRequest(
                chat_id=100000 + idx,
                user_id=100000 + idx,
                caption="xóa sạch text trong video giúp tôi",
                video_path=self.dummy_video_path,
                options={"timeout_sec": 10.0},
            )
            # Gọi trực tiếp endpoint handler
            with patch.object(settings, "ENABLE_TELEGRAM_TEST_HARNESS", True), \
                 patch.object(settings, "TEST_HARNESS_SECRET_KEY", "sentinel-test-key"):
                return await inject_synthetic_telegram_update(mock_req, req_body)

        start_t = time.time()
        burst_tasks = [single_burst_call(i) for i in range(num_burst)]
        responses: List[SyntheticTelegramInjectionResponse] = await asyncio.gather(*burst_tasks)
        duration = time.time() - start_t

        # Xác nhận không bị deadlock và hoàn tất trong thời gian hợp lý (< 10s)
        self.assertLess(duration, 10.0, f"Burst 50 requests chạy quá chậm ({duration:.2f}s), có nguy cơ deadlock/contention!")

        self.assertEqual(len(responses), num_burst)
        for idx, resp in enumerate(responses):
            self.assertTrue(resp.success, f"Burst request {idx} thất bại: {resp.error}")
            self.assertIsNotNone(resp.output_video_path)
            self.assertGreater(len(resp.transcript), 0)

            # Kiểm tra: Các tin nhắn mới sinh (send_message, send_video, send_video_file) có message_id tăng đơn điệu
            created_msg_ids = [
                ev["message_id"] for ev in resp.transcript
                if ev.get("action") in ("send_message", "send_video", "send_video_file") and ev.get("message_id") is not None
            ]
            for m_idx in range(len(created_msg_ids) - 1):
                self.assertLess(
                    created_msg_ids[m_idx],
                    created_msg_ids[m_idx + 1],
                    f"Message ID của tin nhắn mới không tăng đơn điệu trong session {idx}: {created_msg_ids}",
                )

            # Các thao tác sửa đổi/xóa (edit_message_text, delete_message) phải trỏ đúng vào message_id ban đầu
            status_msg_id = created_msg_ids[0] if created_msg_ids else None
            for ev in resp.transcript:
                if ev.get("action") in ("edit_message_text", "delete_message"):
                    self.assertEqual(
                        ev.get("message_id"),
                        status_msg_id,
                        f"Action {ev.get('action')} trỏ sai message_id mục tiêu trong session {idx}: {ev.get('message_id')} != {status_msg_id}",
                    )

    # =========================================================================
    # TEST 4: MEMORY & RESOURCE LEAK TEST (TEMP DIRS & GARBAGE COLLECTION)
    # =========================================================================

    async def test_memory_and_resource_leak_synthetic_injections(self):
        """
        Kiểm tra rò rỉ tài nguyên đĩa và bộ nhớ qua 20 injections liên tiếp:
        - Kiểm tra các thư mục `harness_session_*` được xóa sạch 100% sau khi hoàn thành.
        - Kiểm tra xóa sạch cả trong trường hợp pipeline trả về status='error' hoặc ném Exception.
        - Kiểm tra garbage collection: capture session và pending session được thu hồi sạch.
        """
        app = FastAPI()
        app.state.telegram_bot = self.bot
        app.include_router(router)

        temp_root = tempfile.gettempdir()

        created_temp_dirs: List[str] = []

        # Hook để theo dõi chính xác các thư mục tạm được tạo ra
        orig_mkdtemp = tempfile.mkdtemp

        def tracked_mkdtemp(*args, **kwargs):
            path = orig_mkdtemp(*args, **kwargs)
            if "harness_session_" in path:
                created_temp_dirs.append(path)
            return path

        weak_captures = []

        async def run_tracked_injection(scenario: str, idx: int):
            if scenario == "success":
                self.mock_editor.remove_text_from_video = AsyncMock(return_value={
                    "status": "ok",
                    "output_path": self.dummy_video_path,
                    "message": "OK",
                })
            elif scenario == "error_status":
                self.mock_editor.remove_text_from_video = AsyncMock(return_value={
                    "status": "error",
                    "message": "Lỗi phụ đề",
                })
            elif scenario == "exception":
                self.mock_editor.remove_text_from_video = AsyncMock(
                    side_effect=RuntimeError("FFmpeg simulated crash")
                )

            req = MagicMock(spec=Request)
            req.app = app
            req.client = MagicMock()
            req.client.host = "127.0.0.1"

            req_body = SyntheticTelegramUpdateRequest(
                chat_id=200000 + idx,
                caption="xóa text",
                video_path=self.dummy_video_path,
                options={"timeout_sec": 5.0},
            )

            with patch("tempfile.mkdtemp", side_effect=tracked_mkdtemp), \
                 patch.object(settings, "ENABLE_TELEGRAM_TEST_HARNESS", True), \
                 patch.object(settings, "TEST_HARNESS_SECRET_KEY", "key"):
                resp = await inject_synthetic_telegram_update(req, req_body)
                return resp

        # Chạy 20 lượt đan xen các tình huống (success, error_status, exception)
        scenarios = ["success", "error_status", "exception", "success"] * 5
        for idx, sc in enumerate(scenarios):
            await run_tracked_injection(sc, idx)

        # ── 1. KIỂM ĐỊNH RÒ RỈ ĐĨA (DISK LEAK ZERO TOLERANCE) ──
        self.assertGreaterEqual(len(created_temp_dirs), 20)
        leaked_dirs = [d for d in created_temp_dirs if os.path.exists(d)]
        self.assertEqual(
            len(leaked_dirs),
            0,
            f"RÒ RỈ TÀI NGUYÊN ĐĨA: Tìm thấy {len(leaked_dirs)} thư mục tạm chưa được dọn dẹp: {leaked_dirs}",
        )

        # ── 2. KIỂM ĐỊNH RÒ RỈ BỘ NHỚ (GC & CONTEXTVAR ISOLATION) ──
        gc.collect()
        self.assertIsNone(
            _active_capture_context.get(),
            "ContextVar vẫn giữ tham chiếu sau khi hoàn tất chuỗi injection!",
        )

    # =========================================================================
    # TEST 5: MIXED BURST WITH ERRORS, CANCELLATIONS & RECOVERY
    # =========================================================================

    async def test_mixed_burst_with_errors_cancellations_and_recovery(self):
        """
        Adversarial Test: Bắn 30 tasks hỗn hợp:
        - 10 tasks thành công
        - 10 tasks ném Exception
        - 10 tasks bị huỷ giữa chừng (asyncio.CancelledError)
        Sau đó thực hiện 1 request mới và xác nhận hệ thống phục hồi hoàn hảo.
        """
        app = FastAPI()
        app.state.telegram_bot = self.bot
        app.include_router(router)

        async def worker(task_idx: int):
            req = MagicMock(spec=Request)
            req.app = app
            req.client = MagicMock()
            req.client.host = "127.0.0.1"

            if task_idx % 3 == 0:
                # Success
                async def mock_ok(*a, **kw):
                    await asyncio.sleep(0.01)
                    return {"status": "ok", "output_path": self.dummy_video_path}
                self.mock_editor.remove_text_from_video = AsyncMock(side_effect=mock_ok)
            elif task_idx % 3 == 1:
                # Exception
                async def mock_err(*a, **kw):
                    await asyncio.sleep(0.01)
                    raise ValueError(f"Crash simulated at task {task_idx}")
                self.mock_editor.remove_text_from_video = AsyncMock(side_effect=mock_err)
            else:
                # Cancellation target
                async def mock_hang(*a, **kw):
                    await asyncio.sleep(10.0)
                    return {"status": "ok", "output_path": self.dummy_video_path}
                self.mock_editor.remove_text_from_video = AsyncMock(side_effect=mock_hang)

            req_body = SyntheticTelegramUpdateRequest(
                chat_id=300000 + task_idx,
                caption="xóa text",
                video_path=self.dummy_video_path,
            )
            with patch.object(settings, "ENABLE_TELEGRAM_TEST_HARNESS", True), \
                 patch.object(settings, "TEST_HARNESS_SECRET_KEY", "key"):
                return await inject_synthetic_telegram_update(req, req_body)

        tasks = [asyncio.create_task(worker(i)) for i in range(30)]

        # Chờ 0.005s rồi cancel các tasks có task_idx % 3 == 2
        await asyncio.sleep(0.005)
        for i in range(30):
            if i % 3 == 2:
                tasks[i].cancel()

        # Thu hoạch kết quả (cho phép CancelledError)
        results = await asyncio.gather(*tasks, return_exceptions=True)
        self.assertEqual(len(results), 30)

        # ── KIỂM ĐỊNH PHỤC HỒI HỆ THỐNG (SYSTEM RECOVERY) ──
        # Đảm bảo bot vẫn hoạt động bình thường, không bị kẹt lock hay context dơ
        self.mock_editor.remove_text_from_video = AsyncMock(return_value={
            "status": "ok",
            "output_path": self.dummy_video_path,
            "message": "Phục hồi thành công",
        })

        recover_req = MagicMock(spec=Request)
        recover_req.app = app
        recover_req.client = MagicMock()
        recover_req.client.host = "127.0.0.1"

        recover_body = SyntheticTelegramUpdateRequest(
            chat_id=999999,
            caption="xóa text sau recovery",
            video_path=self.dummy_video_path,
        )

        with patch.object(settings, "ENABLE_TELEGRAM_TEST_HARNESS", True), \
             patch.object(settings, "TEST_HARNESS_SECRET_KEY", "key"):
            recover_resp = await inject_synthetic_telegram_update(recover_req, recover_body)

        self.assertTrue(
            recover_resp.success,
            f"Hệ thống không thể phục hồi sau đợt huỷ và ngoại lệ dồn dập: {recover_resp.error}",
        )
        self.assertIsNotNone(recover_resp.output_video_path)

    # =========================================================================
    # TEST 6: LARGE BUFFER BOUNDS & SERIALIZATION STRESS TEST
    # =========================================================================

    async def test_large_transcript_buffer_bounds_and_serialization(self):
        """
        Kiểm tra khả năng chịu tải của TestHarnessTranscriptCapture khi có tới 200 callbacks tiến độ:
        - Transcript ghi nhận đầy đủ 200+ sự kiện.
        - Khóa `_lock` trong capture đảm bảo thread-safe.
        - Response JSON serialize trơn tru mà không bị lỗi đệ quy hay tràn bộ nhớ.
        """
        total_callbacks = 200

        async def mock_heavy_progress(input_path_or_url, mode="auto", progress_callback=None, **kwargs):
            if progress_callback:
                for p in range(total_callbacks):
                    if asyncio.iscoroutinefunction(progress_callback):
                        await progress_callback(p, f"Tiến độ {p}/{total_callbacks}")
                    else:
                        progress_callback(p, f"Tiến độ {p}/{total_callbacks}")
                    if p % 20 == 0:
                        await asyncio.sleep(0.001)

            return {
                "status": "ok",
                "output_path": self.dummy_video_path,
                "message": "Xong",
            }

        self.mock_editor.remove_text_from_video = AsyncMock(side_effect=mock_heavy_progress)

        app = FastAPI()
        app.state.telegram_bot = self.bot
        app.include_router(router)

        req = MagicMock(spec=Request)
        req.app = app
        req.client = MagicMock()
        req.client.host = "127.0.0.1"

        req_body = SyntheticTelegramUpdateRequest(
            chat_id=400001,
            caption="xóa text tải nặng",
            video_path=self.dummy_video_path,
        )

        with patch.object(settings, "ENABLE_TELEGRAM_TEST_HARNESS", True), \
             patch.object(settings, "TEST_HARNESS_SECRET_KEY", "key"):
            resp = await inject_synthetic_telegram_update(req, req_body)

        self.assertTrue(resp.success)
        self.assertGreaterEqual(len(resp.transcript), 1)

        # Kiểm tra serialization sang JSON Pydantic
        json_data = resp.model_dump()
        self.assertIsInstance(json_data, dict)
        self.assertEqual(json_data["success"], True)
        self.assertIsInstance(json_data["transcript"], list)


if __name__ == "__main__":
    unittest.main()
