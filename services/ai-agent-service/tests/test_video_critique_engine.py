"""
Comprehensive test suite for Milestone 3:
- Feature F9: 5 Streaming CPU Quality Metrics (VideoCritiqueEngine)
- Feature F10: Vision-LLM Critic & Strategy Ladder Refinement
- Feature F11: Telegram UX Progress Emitter & Quality Summary Formatting
"""

import asyncio
import base64
import os
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import cv2
import numpy as np

from app.services.progress_emitter import PipelineProgressEmitter
from app.services.video_critique_engine import (
    CritiqueJudgeResult,
    FrameQualityRecord,
    OpenRouterKeyPool,
    VideoCritiqueEngine,
    WorstCandidateRecord,
)
from app.services.telegram_bot import TelegramBot


class TestVideoCritiqueEngine(unittest.TestCase):
    """Unit tests covering F9, F10, F11 functionality on synthetic frames."""

    def setUp(self):
        self.engine = VideoCritiqueEngine(max_refinement_rounds=2)

    # ─── 1. FEATURE F9: RESIDUAL OCR ─────────────────────────────────────────

    def test_residual_ocr_clean_crop(self):
        """Clean crop with uniform or noisy background without text returns 0 words."""
        # Create 120x60 random noise background
        np.random.seed(42)
        clean_crop = np.random.randint(100, 160, (60, 120, 3), dtype=np.uint8)
        words, max_conf, text = self.engine.compute_residual_ocr(clean_crop)
        self.assertEqual(words, 0)
        self.assertLess(max_conf, 35.0)

    def test_residual_ocr_empty_or_small(self):
        """Tiny or empty ROI handled safely without crashing."""
        words, conf, text = self.engine.compute_residual_ocr(np.zeros((2, 2, 3), dtype=np.uint8))
        self.assertEqual(words, 0)
        self.assertEqual(conf, 0.0)

    # ─── 2. FEATURE F9: TEXTURE RATIO ────────────────────────────────────────

    def test_texture_ratio_natural_vs_smeared(self):
        """
        Smeared inpaint patch has Laplacian variance drop (ratio < 0.70).
        Preserved texture patch retains high Laplacian variance (ratio >= 0.70).
        """
        np.random.seed(123)
        h, w = 120, 120
        # Highly textured Gaussian frame
        frame = np.random.normal(128, 30, (h, w)).clip(0, 255).astype(np.uint8)
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)

        # Center inpaint mask 30x30
        mask = np.zeros((h, w), dtype=np.uint8)
        mask[45:75, 45:75] = 255

        # Case A: Preserved texture
        ratio_natural, var_inp, var_ctx = self.engine.compute_texture_ratio(frame_bgr, mask)
        self.assertGreaterEqual(ratio_natural, 0.70)

        # Case B: Heavily smeared (blurred to flat gray patch)
        smeared_frame = frame_bgr.copy()
        smeared_frame[45:75, 45:75] = cv2.GaussianBlur(smeared_frame[45:75, 45:75], (25, 25), 10)
        ratio_smeared, s_inp, s_ctx = self.engine.compute_texture_ratio(smeared_frame, mask)
        self.assertLess(ratio_smeared, 0.70)

    def test_texture_ratio_smooth_background_tolerance(self):
        """Flat smooth backgrounds (e.g. sky, solid paper) do not get falsely penalized."""
        h, w = 100, 100
        flat_frame = np.full((h, w, 3), 240, dtype=np.uint8)
        mask = np.zeros((h, w), dtype=np.uint8)
        mask[30:60, 30:60] = 255

        ratio, _, var_ctx = self.engine.compute_texture_ratio(flat_frame, mask)
        self.assertLess(var_ctx, 15.0)
        self.assertEqual(ratio, 1.0)

    # ─── 3. FEATURE F9: TEMPORAL FLICKER ─────────────────────────────────────

    def test_temporal_flicker_motion_compensation(self):
        """
        Consecutive frames with smooth motion yield flicker_mse <= 45.0.
        Abrupt patch flickers produce flicker_mse > 45.0.
        """
        np.random.seed(456)
        h, w = 100, 100
        f1 = np.random.randint(50, 200, (h, w, 3), dtype=np.uint8)
        f1_smooth = cv2.GaussianBlur(f1, (5, 5), 1.0)

        # f2 slightly shifted (simulating subtle motion)
        M = np.float32([[1, 0, 1], [0, 1, 0]])
        f2_smooth = cv2.warpAffine(f1_smooth, M, (w, h))

        mask = np.zeros((h, w), dtype=np.uint8)
        mask[30:70, 30:70] = 255

        # Smooth motion case
        mse_smooth, is_cut = self.engine.compute_temporal_flicker(f2_smooth, f1_smooth, mask)
        self.assertFalse(is_cut)
        self.assertLessEqual(mse_smooth, 45.0)

        # Flickering artifact case (inverted patch)
        f2_flicker = f2_smooth.copy()
        f2_flicker[30:70, 30:70] = 255 - f2_flicker[30:70, 30:70]
        mse_flicker, _ = self.engine.compute_temporal_flicker(f2_flicker, f1_smooth, mask)
        self.assertGreater(mse_flicker, 45.0)

    def test_temporal_flicker_shot_cut_gating(self):
        """Dramatic whole-frame scene cuts are gated out from flicker penalties."""
        h, w = 80, 80
        f1 = np.full((h, w, 3), 20, dtype=np.uint8)
        f2 = np.full((h, w, 3), 220, dtype=np.uint8)
        mask = np.zeros((h, w), dtype=np.uint8)
        mask[20:40, 20:40] = 255

        mse, is_cut = self.engine.compute_temporal_flicker(f2, f1, mask)
        self.assertTrue(is_cut)
        self.assertEqual(mse, 0.0)

    # ─── 4. FEATURE F9: EDGE SEAM DISCONTINUITY ──────────────────────────────

    def test_edge_seam_discontinuity_detection(self):
        """
        Sharp unfeathered inpaint boundary step causes seam_ratio > 1.25.
        Seamless/smooth boundary step keeps seam_ratio <= 1.25.
        """
        h, w = 100, 100
        base = np.full((h, w, 3), 100, dtype=np.uint8)
        mask = np.zeros((h, w), dtype=np.uint8)
        mask[30:70, 30:70] = 255

        # Sharp boundary step: inpaint patch is 220 vs background 100
        sharp_frame = base.copy()
        sharp_frame[30:70, 30:70] = 220
        ratio_sharp, seam_g, ref_g = self.engine.compute_edge_seam_ratio(sharp_frame, mask)
        self.assertGreater(ratio_sharp, 1.25)

        # Smooth boundary step: gentle blend
        smooth_frame = base.copy()
        smooth_frame[30:70, 30:70] = 102
        ratio_smooth, _, _ = self.engine.compute_edge_seam_ratio(smooth_frame, mask)
        self.assertLessEqual(ratio_smooth, 1.25)

    # ─── 5. FEATURE F9: DHASH DRIFT ──────────────────────────────────────────

    def test_dhash_drift_calculation(self):
        """Identical or nearly identical frames have dHash drift <= 6; drastic changes > 6."""
        h, w = 100, 100
        f1 = np.zeros((h, w, 3), dtype=np.uint8)
        for j in range(w):
            f1[:, j] = int(255 * j / w)

        # Subtle noise added
        noise = np.random.randint(0, 3, (h, w, 3), dtype=np.uint8)
        f1_subtle = cv2.add(f1, noise)
        drift_small, is_cut = self.engine.compute_dhash_drift(f1_subtle, f1)
        self.assertLessEqual(drift_small, 6)
        self.assertFalse(is_cut)

        # Completely inverted image with opposite horizontal gradient
        f2_inverted = 255 - f1
        drift_large, _ = self.engine.compute_dhash_drift(f2_inverted, f1)
        self.assertGreater(drift_large, 6)

    # ─── 6. FEATURE F10: WORST-K HARVESTER & TEMPORAL NMS ────────────────────

    def test_worst_k_selection_with_temporal_nms(self):
        """Temporal NMS enforces minimum gap between worst candidate selections."""
        records = []
        # Create 10 frames spanning 0.0s to 4.5s
        for i in range(10):
            t = i * 0.5
            # Clustered defects around t=1.0s, 1.5s (same subtitle)
            words = 2 if 1.0 <= t <= 1.5 else 0
            tex = 0.50 if 1.0 <= t <= 1.5 else 0.95
            rec = FrameQualityRecord(
                frame_idx=i * 15,
                timestamp_sec=t,
                residual_words=words,
                residual_max_conf=80.0 if words > 0 else 0.0,
                residual_text="defect" if words > 0 else "",
                texture_ratio=tex,
                temporal_flicker_mse=20.0,
                edge_seam_ratio=1.0,
                dhash_drift=2,
                is_shot_cut=False,
                penalty_score=0.0,
                roi_rect=(10, 10, 50, 50),
                orig_crop=np.zeros((50, 50, 3), dtype=np.uint8),
                clean_crop=np.zeros((50, 50, 3), dtype=np.uint8),
                mask_crop=np.zeros((50, 50), dtype=np.uint8),
            )
            records.append(rec)

        # Select top 3 candidates with min_gap_sec = 1.0
        worst = self.engine.select_worst_k_candidates(records, k=3, min_gap_sec=1.0)
        self.assertLessEqual(len(worst), 3)
        self.assertGreaterEqual(len(worst), 1)

        # Verify pairwise temporal distance >= 1.0s
        for idx1 in range(len(worst)):
            for idx2 in range(idx1 + 1, len(worst)):
                diff = abs(worst[idx1].timestamp_sec - worst[idx2].timestamp_sec)
                self.assertGreaterEqual(diff, 1.0)

    # ─── 7. FEATURE F10: DUAL-COLUMN CONTACT SHEET ───────────────────────────

    def test_contact_sheet_generation_and_dimensions(self):
        """Contact sheet produces valid dual-column JPEG base64 within <= 1024x1024."""
        candidates = []
        for i in range(3):
            c = WorstCandidateRecord(
                frame_idx=i * 30,
                timestamp_sec=float(i),
                penalty_score=15.0 * (3 - i),
                roi_rect=(10, 10, 80, 40),
                orig_crop=np.full((40, 80, 3), 150, dtype=np.uint8),
                clean_crop=np.full((40, 80, 3), 160, dtype=np.uint8),
                mask_crop=np.zeros((40, 80), dtype=np.uint8),
                violated_metrics=["blur_smear"],
            )
            candidates.append(c)

        sheet, b64_str = self.engine.build_contact_sheet(candidates, target_dim=1024)
        h, w = sheet.shape[:2]
        self.assertLessEqual(h, 1024)
        self.assertLessEqual(w, 1024)
        self.assertTrue(b64_str.startswith("data:image/jpeg;base64,"))

        # Test decode
        payload = b64_str.split(",", 1)[1]
        decoded_bytes = base64.b64decode(payload)
        self.assertGreater(len(decoded_bytes), 100)

    # ─── 8. FEATURE F10: JSON EXTRACTION & THINK TAGS ────────────────────────

    def test_extract_critique_json_with_think_tags(self):
        """Parser cleans reasoning model <think> tags and parses markdown JSON."""
        raw_llm = (
            "<think>\n"
            "The crop shows slight blurring on the Porsche speaker mesh.\n"
            "I should flag blur_smear.\n"
            "</think>\n"
            "```json\n"
            "{\n"
            '  "score": 3,\n'
            '  "artifacts": ["blur_smear"],\n'
            '  "pass": false,\n'
            '  "suggested_action": "borrow_flow_keyframe",\n'
            '  "reason": "Porsche speaker mesh has slight smear"\n'
            "}\n"
            "```"
        )
        parsed = self.engine._extract_critique_json(raw_llm)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.get("score"), 3)
        self.assertFalse(parsed.get("pass"))
        self.assertEqual(parsed.get("suggested_action"), "borrow_flow_keyframe")

    # ─── 9. FEATURE F10: PURE CPU FALLBACK JUDGE ─────────────────────────────

    def test_pure_cpu_fallback_judge_pass_and_fail(self):
        """Pure CPU decision logic returns valid CritiqueJudgeResult without external calls."""
        # Case A: Passing metrics
        clean_metrics = {
            "residual_ocr_words": 0,
            "laplacian_texture_ratio": 0.85,
            "temporal_flicker_mse": 20.0,
            "seam_discontinuity": 1.10,
        }
        res_pass = self.engine.pure_cpu_fallback_judge([], clean_metrics)
        self.assertTrue(res_pass.is_pass)
        self.assertEqual(res_pass.score, 4)
        self.assertEqual(res_pass.source_judge, "pure_cpu_fallback")

        # Case B: Failing metrics (residual text)
        dirty_metrics = {
            "residual_ocr_words": 2,
            "laplacian_texture_ratio": 0.50,
            "temporal_flicker_mse": 30.0,
            "seam_discontinuity": 1.40,
        }
        res_fail = self.engine.pure_cpu_fallback_judge([], dirty_metrics)
        self.assertFalse(res_fail.is_pass)
        self.assertLessEqual(res_fail.score, 3)
        self.assertEqual(res_fail.suggested_action, "expand_mask_dilation")

    # ─── 10. FEATURE F10: STRATEGY LADDER DISPATCHER ─────────────────────────

    def test_strategy_ladder_decision_flow(self):
        """
        Strategy ladder dispatches correct targeted action and stops after 2 rounds.
        """
        # Round 1: expand_mask_dilation
        judge_res1 = CritiqueJudgeResult(
            score=2,
            artifacts=["text_residue"],
            is_pass=False,
            suggested_action="expand_mask_dilation",
            reason="residual text found",
            source_judge="pure_cpu_fallback",
        )
        strat1 = self.engine.recommend_refinement_strategy(judge_res1, round_num=1)
        self.assertIsNotNone(strat1)
        self.assertEqual(strat1.get("action"), "expand_mask_dilation")
        self.assertEqual(strat1.get("dilation_extra_px"), 4)
        self.assertEqual(strat1.get("top_margin_px"), 8)

        # Round 2: combined_deep_refine
        strat2 = self.engine.recommend_refinement_strategy(judge_res1, round_num=2)
        self.assertIsNotNone(strat2)
        self.assertEqual(strat2.get("action"), "combined_deep_refine")
        self.assertEqual(strat2.get("dilation_extra_px"), 8)

        # Round 3: max rounds reached -> None (bounded iteration)
        strat3 = self.engine.recommend_refinement_strategy(judge_res1, round_num=3)
        self.assertIsNone(strat3)

        # Passing judge -> None
        judge_pass = CritiqueJudgeResult(
            score=5,
            artifacts=[],
            is_pass=True,
            suggested_action="pass_no_action",
            reason="all clean",
            source_judge="groq_vision",
        )
        self.assertIsNone(self.engine.recommend_refinement_strategy(judge_pass, round_num=1))

    # ─── 11. FEATURE F11: PIPELINE PROGRESS EMITTER THREAD SAFETY ───────────

    def test_pipeline_progress_emitter_thread_safety(self):
        """Progress emitter dispatches safely across worker thread boundary without error."""
        loop = asyncio.new_event_loop()
        called_reports = []

        async def dummy_callback(pct: int, desc: str, extra=None):
            called_reports.append((pct, desc))

        emitter = PipelineProgressEmitter(loop=loop, callback=dummy_callback)

        def worker():
            for p in [10, 50, 100]:
                emitter.emit(p, f"Stage {p}")

        # Start loop in background thread
        t_loop = threading.Thread(target=loop.run_forever, daemon=True)
        t_loop.start()

        # Run worker in separate thread
        t_worker = threading.Thread(target=worker)
        t_worker.start()
        t_worker.join()

        # Give loop time to process callbacks
        time.sleep(0.1)
        loop.call_soon_threadsafe(loop.stop)
        t_loop.join(timeout=1.0)
        loop.close()

        self.assertEqual(len(called_reports), 3)
        self.assertEqual(called_reports[0], (10, "Stage 10"))
        self.assertEqual(called_reports[2], (100, "Stage 100"))

    # ─── 12. FEATURE F11: QUALITY SUMMARY CAPTION FORMATTING ────────────────

    def test_format_video_quality_caption(self):
        """_format_video_quality_caption creates complete HTML caption within Telegram limits (< 1024 chars)."""
        bot = TelegramBot.__new__(TelegramBot)
        dummy_res = {
            "status": "ok",
            "processing_time_sec": 42.5,
            "critique": {
                "metrics": {
                    "residual_ocr_words": 0,
                    "laplacian_texture_ratio": 0.98,
                    "temporal_flicker_ratio": 1.03,
                    "seam_discontinuity": 0.015,
                    "phash_drift": 2,
                },
                "vision_llm_score": 4.8,
                "refinement_rounds": 0,
            },
        }

        caption = bot._format_video_quality_caption(dummy_res)
        self.assertIn("BẢNG TỔNG KẾT CHẤT LƯỢNG", caption)
        self.assertIn("Residual OCR:", caption)
        self.assertIn("0 từ tồn dư", caption)
        self.assertIn("Laplacian Texture:", caption)
        self.assertIn("0.98", caption)
        self.assertIn("Temporal Flicker:", caption)
        self.assertIn("1.03x", caption)
        self.assertIn("Seam Discontinuity:", caption)
        self.assertIn("pHash Visual Drift:", caption)
        self.assertIn("Vision-LLM Score:", caption)
        self.assertIn("Vòng tinh chỉnh:", caption)
        self.assertIn("42.5s", caption)

        # Telegram caption max length is 1024 characters
        self.assertLess(len(caption), 1024)


if __name__ == "__main__":
    unittest.main()
