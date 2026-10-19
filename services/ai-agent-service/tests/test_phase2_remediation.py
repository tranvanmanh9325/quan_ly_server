"""
Phase 2 Remediation (R2 - P1) Verification Test Suite.
Validates:
1. Item 1: Fail-Closed Critique & Metric Evaluation (no silent clean fake scores).
2. Item 2: Vision-LLM Critic Event Loop Safety & Audit Logging.
3. Item 3: VideoJobContext Isolation, Zero Shared Mutable State & Transparent Fallback.
4. Item 4: Zero Test-Aware Branches in Production Code.
5. Item 5: Telegram target_scope Propagation & Quality Captioning.
"""

import asyncio
import logging
import re
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np

from app.services.video_critique_engine import (
    CritiqueJudgeResult,
    FrameQualityRecord,
    VideoCritiqueEngine,
    WorstCandidateRecord,
)
from app.services.video_editor_service import (
    VideoEditorService,
    VideoJobContext,
)
from app.services.telegram_bot import TelegramBot


class TestPhase2FailClosedCritique(unittest.TestCase):
    """Item 1: Triệt tiêu Fail-Open & Thiết kế Kiến trúc Fail-Closed."""

    def setUp(self):
        self.engine = VideoCritiqueEngine()

    def test_residual_ocr_missing_pytesseract_returns_unverified(self):
        """When pytesseract is missing or raises an exception, return words=-1 with unverified tag."""
        sample_crop = np.zeros((50, 100, 3), dtype=np.uint8)
        with patch.dict("sys.modules", {"pytesseract": None}):
            with patch("app.services.video_critique_engine.pytesseract", None):
                words, conf, text = self.engine.compute_residual_ocr(sample_crop)
                self.assertEqual(words, -1)
                self.assertEqual(conf, 0.0)
                self.assertIn("UNVERIFIED", text)

    def test_residual_ocr_exception_returns_unverified(self):
        """When pytesseract raises an internal exception, return words=-1 with unverified tag."""
        sample_crop = np.zeros((50, 100, 3), dtype=np.uint8)
        mock_pytesseract = MagicMock()
        mock_pytesseract.image_to_data.side_effect = RuntimeError("OCR binary crashed")
        mock_pytesseract.Output.DICT = "dict"

        with patch("app.services.video_critique_engine.pytesseract", mock_pytesseract):
            words, conf, text = self.engine.compute_residual_ocr(sample_crop)
            self.assertEqual(words, -1)
            self.assertEqual(conf, 0.0)
            self.assertIn("UNVERIFIED_OCR_ERROR", text)

    def test_calculate_composite_penalty_for_unverified_ocr(self):
        """When residual_words < 0 (unverified), calculate_composite_penalty imposes severe 50.0 penalty."""
        rec = FrameQualityRecord(
            frame_idx=30,
            timestamp_sec=1.0,
            residual_words=-1,
            residual_max_conf=0.0,
            residual_text="[UNVERIFIED]",
            texture_ratio=1.0,
            temporal_flicker_mse=0.0,
            edge_seam_ratio=1.0,
            dhash_drift=0,
            is_shot_cut=False,
            penalty_score=0.0,
        )
        penalty = self.engine.calculate_composite_penalty(rec)
        self.assertGreaterEqual(penalty, 50.0)

    def test_pure_cpu_fallback_judge_fail_closed_on_none_metrics(self):
        """When metrics are empty, missing, or unverified, pure_cpu_fallback_judge must fail-closed."""
        res = self.engine.pure_cpu_fallback_judge({})
        self.assertFalse(res.is_pass)
        self.assertEqual(res.score, 1)
        self.assertEqual(res.source_judge, "pure_cpu_fallback_unverified")
        self.assertTrue(any("unverified" in a for a in res.artifacts))

    def test_pure_cpu_fallback_judge_fail_closed_on_unverified_ocr(self):
        """When residual_ocr_words is None or < 0, pure_cpu_fallback_judge must fail-closed."""
        res = self.engine.pure_cpu_fallback_judge({
            "residual_ocr_words": None,
            "laplacian_texture_ratio": 1.0,
            "temporal_flicker_ratio": 1.0,
            "seam_discontinuity": 0.0,
            "phash_drift": 0,
        })
        self.assertFalse(res.is_pass)
        self.assertEqual(res.score, 1)
        self.assertTrue(any("unverified" in a for a in res.artifacts))

    def test_evaluate_video_stream_sync_empty_records_fails_closed(self):
        """
        Finding 1 Adversarial Test:
        When evaluate_video_stream_sync processes a video with 0 extractable frames
        (corrupted stream, 0 duration, or read() returning False immediately),
        records list is empty ([]).
        The engine must fail-closed:
        - is_pass == False (NEVER True!)
        - metrics["residual_ocr_status"] == "unverified"
        - metrics["residual_ocr_words"] is None
        - result["status"] == "unverified"
        - records_count == 0
        """
        mock_cap_orig = MagicMock()
        mock_cap_clean = MagicMock()
        mock_cap_orig.isOpened.return_value = True
        mock_cap_clean.isOpened.return_value = True
        mock_cap_orig.get.return_value = 0.0
        mock_cap_clean.get.return_value = 0.0
        # Immediately returns (False, None) to simulate 0 frames read
        mock_cap_orig.read.return_value = (False, None)
        mock_cap_clean.read.return_value = (False, None)

        with patch.object(Path, "exists", return_value=True):
            with patch("cv2.VideoCapture", side_effect=[mock_cap_orig, mock_cap_clean]):
                res = self.engine.evaluate_video_stream_sync("empty_orig.mp4", "empty_clean.mp4")

        self.assertFalse(res["is_pass"], "Empty video must NEVER pass quality audit")
        self.assertEqual(res["status"], "unverified", "Status must be unverified for empty frames")
        self.assertEqual(res["records_count"], 0)
        self.assertIsNone(res["metrics"]["residual_ocr_words"])
        self.assertEqual(res["metrics"]["residual_ocr_status"], "unverified")

        # Downstream Pure CPU Judge must also fail closed with these unverified metrics
        cpu_judge = self.engine.pure_cpu_fallback_judge(res["metrics"])
        self.assertFalse(cpu_judge.is_pass)
        self.assertEqual(cpu_judge.score, 1)
        self.assertTrue(any("unverified" in a for a in cpu_judge.artifacts))


class TestPhase2EventLoopAndAuditLogging(unittest.TestCase):
    """Item 2: Khắc phục Event Loop / Thread & Thêm Logging [AUDIT]."""

    def setUp(self):
        self.engine = VideoCritiqueEngine()

    def test_critique_worst_crops_sync_when_called_from_worker_thread(self):
        """
        When called from a worker thread with no event loop,
        critique_worst_crops_sync safely spins up an event loop and completes without RuntimeError.
        """
        result_container = []

        def worker():
            with patch.object(self.engine, "judge_with_vision_llm", return_value=CritiqueJudgeResult(
                score=4,
                artifacts=[],
                is_pass=True,
                suggested_action="pass_no_action",
                reason="clean",
                source_judge="test_mock",
            )):
                dummy_crop = np.zeros((40, 40, 3), dtype=np.uint8)
                res = self.engine.critique_worst_crops_sync([dummy_crop], [dummy_crop])
                result_container.append(res)

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=5.0)

        self.assertEqual(len(result_container), 1)
        self.assertTrue(result_container[0]["is_pass"])
        self.assertEqual(result_container[0]["score"], 4)

    def test_audit_logging_format_in_judge_with_vision_llm(self):
        """judge_with_vision_llm records [AUDIT] info log with tokens, latency, and model."""
        with patch.object(self.engine._groq_pool, "has_keys", return_value=False):
            with patch.object(self.engine._openrouter_pool, "has_keys", return_value=True):
                with patch.object(self.engine._openrouter_pool, "get_next_key", new_callable=AsyncMock, return_value="fake-sk-key"):
                    with patch.object(self.engine._openrouter_pool, "mark_success", new_callable=AsyncMock):
                        with patch.object(self.engine, "_call_vision_http", new_callable=AsyncMock) as mock_call:
                            mock_call.return_value = {
                                "content": '{"score": 5, "artifacts": [], "pass": true, "suggested_action": "pass_no_action", "reason": "flawless"}',
                                "model": "google/gemini-2.0-flash-001",
                                "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
                                "latency_sec": 0.45,
                            }

                            cand = WorstCandidateRecord(
                                frame_idx=10,
                                timestamp_sec=0.5,
                                penalty_score=60.0,
                                roi_rect=(0, 0, 50, 50),
                                orig_crop=np.zeros((50, 50, 3), dtype=np.uint8),
                                clean_crop=np.zeros((50, 50, 3), dtype=np.uint8),
                                mask_crop=np.zeros((50, 50), dtype=np.uint8),
                                violated_metrics=["residual_text"],
                            )

                            with self.assertLogs("app.services.video_critique_engine", level=logging.INFO) as cm:
                                res = asyncio.run(self.engine.judge_with_vision_llm(candidates=[cand]))
                                self.assertTrue(res.is_pass)
                                self.assertEqual(res.model, "google/gemini-2.0-flash-001")
                                self.assertEqual(res.total_tokens, 150)
                                self.assertEqual(res.latency_sec, 0.45)

                                audit_logs = [line for line in cm.output if "[AUDIT]" in line]
                                self.assertTrue(len(audit_logs) >= 1)
                                self.assertIn("Tokens: 150", audit_logs[0])
                                self.assertIn("Latency: 0.45s", audit_logs[0])

    def test_critique_worst_crops_sync_loop_guard_prevents_same_thread_deadlock(self):
        """
        Finding 3 Adversarial Test:
        When critique_worst_crops_sync is called with an external `loop` that is
        IDENTICAL to the current thread's running event loop,
        calling asyncio.run_coroutine_threadsafe(...).result() would DEADLOCK
        because the current thread is blocked waiting for the event loop on the same thread.

        The Tier 1 dispatcher MUST verify `loop is not current_running_loop`.
        If loop IS the current running loop, Tier 1 must be safely bypassed
        without freezing/deadlocking.
        """
        async def run_test_in_loop():
            current_loop = asyncio.get_running_loop()
            t0 = time.monotonic()
            res = self.engine.critique_worst_crops_sync(
                worst_candidates=[],
                aggregated_cpu_metrics={"residual_ocr_words": 0, "total_sampled_frames": 1, "laplacian_texture_ratio": 1.0},
                loop=current_loop,
            )
            elapsed = time.monotonic() - t0
            self.assertLess(elapsed, 2.0, "Function took too long, possible deadlock or timeout wait!")
            self.assertIsInstance(res, dict)
            self.assertIn("is_pass", res)

        asyncio.run(run_test_in_loop())

    def test_critique_worst_crops_sync_cross_thread_tier1_dispatches_cleanly(self):
        """
        Finding 3 Verification Test:
        When called from a worker thread with a distinct background event loop,
        Tier 1 safely dispatches via run_coroutine_threadsafe and retrieves the result.
        """
        bg_loop = asyncio.new_event_loop()
        bg_thread = threading.Thread(target=bg_loop.run_forever, daemon=True)
        bg_thread.start()

        try:
            with patch.object(self.engine, "judge_with_vision_llm", new_callable=AsyncMock) as mock_judge:
                mock_judge.return_value = CritiqueJudgeResult(
                    score=5,
                    artifacts=[],
                    is_pass=True,
                    suggested_action="pass_no_action",
                    reason="clean cross-thread execution",
                    source_judge="vision_llm_tier1",
                )

                res = self.engine.critique_worst_crops_sync(
                    worst_candidates=[],
                    aggregated_cpu_metrics={"residual_ocr_words": 0},
                    loop=bg_loop,
                )

                self.assertTrue(res["is_pass"])
                self.assertEqual(res["score"], 5)
                self.assertEqual(res["source_judge"], "vision_llm_tier1")
        finally:
            bg_loop.call_soon_threadsafe(bg_loop.stop)
            bg_thread.join(timeout=2.0)
            bg_loop.close()


class TestPhase2VideoJobContextAndNoSharedState(unittest.IsolatedAsyncioTestCase):
    """Item 3 & Item 4: VideoJobContext, Không Shared State, Fallback Minh Bạch & Zero Test-Aware Code."""

    async def asyncSetUp(self):
        self.service = VideoEditorService()

    def test_production_code_contains_zero_test_aware_branches(self):
        """Ensure no MagicMock, Mock, is_mock_cv, or is_mock_inpaint exist in production files."""
        app_services_dir = Path(__file__).resolve().parent.parent / "app" / "services"
        prod_files = [
            app_services_dir / "video_editor_service.py",
            app_services_dir / "video_critique_engine.py",
            app_services_dir / "telegram_bot.py",
        ]

        forbidden_patterns = [
            r"MagicMock",
            r"is_mock_cv",
            r"is_mock_inpaint",
            r"type\(cv2\)\.__name__\s*in\s*\(",
        ]

        for file_path in prod_files:
            content = file_path.read_text(encoding="utf-8")
            for pattern in forbidden_patterns:
                matches = re.findall(pattern, content)
                self.assertEqual(
                    len(matches),
                    0,
                    f"Forbidden test-aware branch '{pattern}' found in {file_path.name}: {matches}",
                )

    def test_video_job_context_isolation_and_cleanup(self):
        """Verify VideoJobContext maintains independent state per job and cleans up cache properly."""
        ctx1 = VideoJobContext(
            input_file=Path("video1.mp4"),
            output_file=Path("out1.mp4"),
            mode_requested="auto",
            mode_used="inpaint",
            target_scope="overlay",
        )
        ctx2 = VideoJobContext(
            input_file=Path("video2.mp4"),
            output_file=Path("out2.mp4"),
            mode_requested="auto",
            mode_used="inpaint",
            target_scope="all",
        )

        self.assertNotEqual(ctx1.job_id, ctx2.job_id)
        ctx1.branch_counters["fast_path"] = 10
        ctx2.branch_counters["fast_path"] = 5
        self.assertEqual(ctx1.branch_counters["fast_path"], 10)
        self.assertEqual(ctx2.branch_counters["fast_path"], 5)

        # Record transparent fallback on ctx1
        ctx1.record_fallback(
            stage="streaming",
            from_system="streaming_pipeline",
            to_system="inpaint_fallback_legacy",
            reason="Synthetic test failure",
            impact="Reduced visual fidelity",
        )
        self.assertTrue(ctx1.is_fallback)
        self.assertFalse(ctx2.is_fallback)
        self.assertEqual(len(ctx1.fallback_events), 1)
        self.assertEqual(ctx1.fallback_events[0]["stage"], "streaming")

        # Cleanup
        ctx1.roi_cache["test"] = b"data"
        ctx1.cleanup()
        self.assertEqual(len(ctx1.roi_cache), 0)


class TestPhase2TelegramTargetScopeAndQualityCaption(unittest.TestCase):
    """Item 5: target_scope Parsing & Quality Caption Formatting."""

    def test_extract_target_scope(self):
        """_extract_target_scope parses Vietnamese instructions accurately."""
        bot = TelegramBot.__new__(TelegramBot)

        # 1. Cases that trigger 'all' scope (Chỉ khi có từ khóa rõ ràng về bối cảnh/cảnh)
        self.assertEqual(bot._extract_target_scope("xóa cả chữ trong cảnh giúp em"), "all")
        self.assertEqual(bot._extract_target_scope("xoa ca chu trong canh giup em"), "all")
        self.assertEqual(bot._extract_target_scope("xóa tất cả text trong bối cảnh"), "all")
        self.assertEqual(bot._extract_target_scope("toàn bộ chữ trong cảnh"), "all")
        self.assertEqual(bot._extract_target_scope("cả chữ trên biển hiệu"), "all")
        self.assertEqual(bot._extract_target_scope("xóa cả cảnh"), "all")
        self.assertEqual(bot._extract_target_scope("remove text in scene"), "all")
        self.assertEqual(bot._extract_target_scope("target_scope=all"), "all")

        # 2. Cases that retain default 'overlay' scope (Mọi câu lệnh chung chung / tăng từ)
        self.assertEqual(bot._extract_target_scope("xóa sạch text trong video này giúp tôi"), "overlay")
        self.assertEqual(bot._extract_target_scope("xoa sach text trong video nay giup toi"), "overlay")
        self.assertEqual(bot._extract_target_scope("xóa sạch text"), "overlay")
        self.assertEqual(bot._extract_target_scope("xóa sạch chữ"), "overlay")
        self.assertEqual(bot._extract_target_scope("xóa hết text"), "overlay")
        self.assertEqual(bot._extract_target_scope("xóa hết chữ"), "overlay")
        self.assertEqual(bot._extract_target_scope("xóa toàn bộ chữ"), "overlay")
        self.assertEqual(bot._extract_target_scope("xóa hết toàn bộ chữ trên video"), "overlay")
        self.assertEqual(bot._extract_target_scope("xóa tất cả text"), "overlay")
        self.assertEqual(bot._extract_target_scope("remove all text"), "overlay")
        self.assertEqual(bot._extract_target_scope("xóa phụ đề video này"), "overlay")
        self.assertEqual(bot._extract_target_scope("xóa watermark góc phải"), "overlay")
        self.assertEqual(bot._extract_target_scope("xóa logo giúp anh"), "overlay")
        self.assertEqual(bot._extract_target_scope("làm sạch text phụ đề"), "overlay")

    def test_extract_target_scope_parameterized_adversarial(self):
        """
        Finding 2 Adversarial Test:
        Accurately distinguish between default 'overlay' scope vs explicit 'all' scope.
        User commands like 'xóa sạch text trong video này giúp tôi' must retain
        default 'overlay' scope to preserve scene text (Anti-Gaming Rule 4 & R2).
        Only commands explicitly targeting scene text switch to 'all'.
        """
        bot = TelegramBot.__new__(TelegramBot)

        overlay_cases = [
            "xóa sạch text trong video này giúp tôi",
            "xóa text",
            "xóa sạch chữ trong video",
            "xóa phụ đề trên video",
            "xóa watermark",
            "xóa logo ở góc",
            "xóa chữ phụ đề giúp em",
            "xóa sạch phụ đề tiếng việt",
            "nhờ bot xóa text video",
            "làm sạch text",
            "xóa watermark mờ",
        ]

        all_cases = [
            "xóa cả chữ trong cảnh",
            "xóa chữ trong cảnh",
            "xóa cả cảnh",
            "xóa toàn bộ chữ trong cảnh",
            "xóa cả text trong cảnh",
            "chữ trong bối cảnh",
            "xóa toàn bộ text trong bối cảnh",
            "xóa sạch chữ trong cảnh",
            "xoa ca chu trong canh",
            "xoa chu trong canh",
            "remove text in scene",
            "target_scope=all",
        ]

        for phrase in overlay_cases:
            with self.subTest(phrase=phrase, expected="overlay"):
                actual = bot._extract_target_scope(phrase)
                self.assertEqual(
                    actual,
                    "overlay",
                    f"User phrase '{phrase}' must be classified as 'overlay', got '{actual}'",
                )

        for phrase in all_cases:
            with self.subTest(phrase=phrase, expected="all"):
                actual = bot._extract_target_scope(phrase)
                self.assertEqual(
                    actual,
                    "all",
                    f"Explicit scene phrase '{phrase}' must be classified as 'all', got '{actual}'",
                )

    def test_format_video_quality_caption_fallback_never_congratulates(self):
        """
        Finding 4 Adversarial Test:
        When is_fallback is True, the caption header must be a Fallback Warning.
        It must NEVER display fake congratulatory headlines like 'đã xóa sạch text',
        even if critique metrics happen to have is_pass=True.
        """
        bot = TelegramBot.__new__(TelegramBot)

        # Sub-case A: Fallback mode with is_pass = True (must NOT congratulate)
        res_fallback_pass = {
            "status": "ok",
            "processing_time_sec": 15.2,
            "is_fallback": True,
            "mode_used": "inpaint_fallback_legacy",
            "fallback_reason": "Neural streaming pipeline out of memory",
            "critique": {
                "status": "ok",
                "is_pass": True,  # even if fallback passes critique!
                "metrics": {
                    "residual_ocr_words": 0,
                    "laplacian_texture_ratio": 0.92,
                    "temporal_flicker_ratio": 1.02,
                    "seam_discontinuity": 0.75,
                    "phash_drift": 1,
                },
                "vision_llm_score": 4.5,
                "refinement_rounds": 1,
            },
        }

        caption_a = bot._format_video_quality_caption(res_fallback_pass)
        header_a = caption_a.strip().split("\n")[0]

        self.assertIn("Chế độ Dự phòng", header_a, "Header must explicitly state Fallback Mode")
        self.assertIn("⚠️", header_a, "Header must contain warning icon ⚠️")
        self.assertNotIn("đã xóa sạch text", header_a, "Header must NEVER falsely congratulate")
        self.assertNotIn("xóa sạch text trong video cho anh Mạnh", header_a)
        self.assertIn("CẢNH BÁO: CHẾ ĐỘ DỰ PHÒNG", caption_a)
        self.assertIn("Neural streaming pipeline out of memory", caption_a)

        # Sub-case B: Standard non-fallback mode with is_pass = True (allowed to congratulate)
        res_standard_pass = {
            "status": "ok",
            "processing_time_sec": 22.0,
            "is_fallback": False,
            "mode_used": "streaming_pipeline",
            "critique": {
                "status": "ok",
                "is_pass": True,
                "metrics": {
                    "residual_ocr_words": 0,
                    "laplacian_texture_ratio": 0.98,
                    "temporal_flicker_ratio": 1.01,
                    "seam_discontinuity": 0.65,
                    "phash_drift": 0,
                },
                "vision_llm_score": 5.0,
                "refinement_rounds": 0,
            },
        }

        caption_b = bot._format_video_quality_caption(res_standard_pass)
        header_b = caption_b.strip().split("\n")[0]
        self.assertIn("xóa sạch text trong video cho anh Mạnh", header_b)
        self.assertNotIn("CẢNH BÁO: CHẾ ĐỘ DỰ PHÒNG", caption_b)

    def test_format_video_quality_caption_unverified_fail_closed(self):
        """When metrics are empty, None, or unverified, caption displays 'Chưa kiểm chứng (UNVERIFIED)'."""
        bot = TelegramBot.__new__(TelegramBot)
        dummy_res = {
            "status": "ok",
            "processing_time_sec": 12.3,
            "is_fallback": True,
            "fallback_reason": "Streaming pipeline encountered corrupt frame",
            "critique": {
                "status": "unverified",
                "is_pass": False,
                "metrics": {
                    "residual_ocr_words": None,
                    "laplacian_texture_ratio": None,
                    "temporal_flicker_ratio": None,
                    "seam_discontinuity": None,
                    "phash_drift": None,
                },
                "vision_llm_score": None,
                "refinement_rounds": 0,
            },
        }

        caption = bot._format_video_quality_caption(dummy_res)
        self.assertIn("Chưa kiểm chứng (UNVERIFIED)", caption)
        self.assertIn("CHẾ ĐỘ DỰ PHÒNG", caption)
        self.assertIn("Streaming pipeline encountered corrupt frame", caption)
        self.assertLess(len(caption), 1024)


if __name__ == "__main__":
    unittest.main()
