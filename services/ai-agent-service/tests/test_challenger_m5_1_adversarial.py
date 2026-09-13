"""
test_challenger_m5_1_adversarial.py — Milestone 5 Challenger 1 Adversarial Verification Suite.

Adversarial Stress Testing of:
  - Synaptic Pruning Logic (Confidence boundaries, time decay thresholds, mmap zeroing)
  - Slow-Wave Sleep (SWS) & REM Sleep Cycles (Adenosine flush, neuro-chemical balance, memory replay)
  - Morning Epiphany Lifecycle (Idempotent single delivery, time-window gating, sisterly formatting)
  - Extreme Boundary & Exception Resilience (Empty DB, None memory_service, LLM failures, corrupted cache)

Author: Challenger 1 (Empirical Adversarial Gatekeeper)
Date: 2026-09-13
"""
import asyncio
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure app is in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.brain_core import (
    ArtificialBrain,
    HyperdimensionalCortex,
    NeurotransmitterState,
    HV_DIM_BITS,
    HV_DIM_BYTES,
    VN_TZ,
)
from app.services.dream_engine import SubconsciousDreamEngine


class TestChallengerM5AdversarialSuite(unittest.IsolatedAsyncioTestCase):
    """
    Empirical Adversarial Test Suite for Milestone 5 Subconscious Dream & Synaptic Pruning Engine.
    """

    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_challenger_m5_cortex_"))
        self.brain = ArtificialBrain(storage_dir=self.temp_dir)

    def tearDown(self) -> None:
        if self.brain and hasattr(self.brain, "cortex") and self.brain.cortex:
            self.brain.cortex.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # =========================================================================
    # NHOM 1: SYNAPTIC PRUNING STRESS & BOUNDARY TESTING
    # =========================================================================

    def test_01_synaptic_pruning_mandatory_for_low_confidence_and_old_disuse(self) -> None:
        """
        Ca 1: Bai hoc confidence < 0.25 (0.20) va khong truy cap > 7 ngay (8 ngay truoc)
        BAT BUOC bi prune (khong duoc dong bo vao Cortex).
        """
        cortex = self.brain.cortex
        old_time = (datetime.now(VN_TZ) - timedelta(days=8)).isoformat()

        lessons = [
            {
                "id": 101,
                "lesson_text": "Quy tac yeu cu can cat tia",
                "trigger_pattern": "test_weak_old",
                "event_type": "ephemeral",
                "confidence": 0.20,
                "is_active": True,
                "last_used_at": old_time,
            }
        ]

        stats = cortex.sync_lessons(lessons)
        self.assertEqual(stats["synced"], 0, "Bai hoc yeu cu khong duoc phep sync vao cortex")
        self.assertNotIn("lesson_101", cortex.entry_index, "lesson_101 khong duoc phep ton tai trong cortex")

    def test_02_synaptic_pruning_retains_low_confidence_if_recently_accessed(self) -> None:
        """
        Ca 2: Bai hoc confidence < 0.25 (0.15) nhung moi truy cap 2 ngay truoc
        KHONG DUOC prune, phai duoc giu lai va dong bo vao Cortex.
        """
        cortex = self.brain.cortex
        recent_time = (datetime.now(VN_TZ) - timedelta(days=2)).isoformat()

        lessons = [
            {
                "id": 102,
                "lesson_text": "Quy tac moi hoc du confidence thap van dang thu nghiem",
                "trigger_pattern": "test_weak_recent",
                "event_type": "experimental",
                "confidence": 0.15,
                "is_active": True,
                "last_used_at": recent_time,
            }
        ]

        stats = cortex.sync_lessons(lessons)
        self.assertEqual(stats["synced"], 1, "Bai hoc moi dung phai duoc sync")
        self.assertIn("lesson_102", cortex.entry_index, "lesson_102 phai ton tai trong cortex")
        self.assertAlmostEqual(cortex.metadata_index["lesson_102"]["confidence"], 0.15)

    def test_03_synaptic_pruning_retains_high_confidence_even_if_ancient(self) -> None:
        """
        Ca 3: Bai hoc confidence >= 0.25 (0.85) du khong truy cap 30 ngay
        KHONG DUOC prune, phai duoc bao toan nguyen ven trong Cortex.
        """
        cortex = self.brain.cortex
        ancient_time = (datetime.now(VN_TZ) - timedelta(days=30)).isoformat()

        lessons = [
            {
                "id": 103,
                "lesson_text": "Quy tac cot loi ve bao ve kernel",
                "trigger_pattern": "core_kernel_safety",
                "event_type": "fundamental_rule",
                "confidence": 0.85,
                "is_active": True,
                "last_used_at": ancient_time,
            }
        ]

        stats = cortex.sync_lessons(lessons)
        self.assertEqual(stats["synced"], 1, "Bai hoc confidence cao phai duoc sync")
        self.assertIn("lesson_103", cortex.entry_index, "lesson_103 phai duoc giu lai trong cortex")

    def test_04_synaptic_pruning_confidence_boundary_point(self) -> None:
        """
        Ca 4: Thu nghiem ranh gioi toan hoc cua Confidence:
        - Lesson A: confidence = 0.249 ( < 0.25 ), disused 10d -> BAT BUOC prune
        - Lesson B: confidence = 0.250 ( >= 0.25 ), disused 10d -> KHONG prune, giu nguyen
        """
        cortex = self.brain.cortex
        old_time = (datetime.now(VN_TZ) - timedelta(days=10)).isoformat()

        lessons = [
            {
                "id": 1041,
                "lesson_text": "Bai hoc ngay duoi nguong",
                "trigger_pattern": "sub_threshold",
                "confidence": 0.249,
                "is_active": True,
                "last_used_at": old_time,
            },
            {
                "id": 1042,
                "lesson_text": "Bai hoc ngay tai nguong chinh xac",
                "trigger_pattern": "exact_threshold",
                "confidence": 0.250,
                "is_active": True,
                "last_used_at": old_time,
            }
        ]

        cortex.sync_lessons(lessons)
        self.assertNotIn("lesson_1041", cortex.entry_index, "0.249 < 0.25 phai bi prune")
        self.assertIn("lesson_1042", cortex.entry_index, "0.250 >= 0.25 phai duoc giu nguyen")

    def test_05_synaptic_pruning_time_boundary_seven_days(self) -> None:
        """
        Ca 5: Thu nghiem ranh gioi thoi gian 7 ngay voi confidence < 0.25 (0.18):
        - Lesson A: disused 6 ngay 23 gio (6.96 ngay < 7 ngay) -> KHONG prune
        - Lesson B: disused 7 ngay 1 gio (7.04 ngay > 7 ngay) -> BAT BUOC prune
        """
        cortex = self.brain.cortex
        now_dt = datetime.now(VN_TZ)
        time_under_7d = (now_dt - timedelta(days=6, hours=23)).isoformat()
        time_over_7d = (now_dt - timedelta(days=7, hours=1)).isoformat()

        lessons = [
            {
                "id": 1051,
                "lesson_text": "Bai hoc chua du 7 ngay",
                "trigger_pattern": "under_7d",
                "confidence": 0.18,
                "is_active": True,
                "last_used_at": time_under_7d,
            },
            {
                "id": 1052,
                "lesson_text": "Bai hoc da qua 7 ngay",
                "trigger_pattern": "over_7d",
                "confidence": 0.18,
                "is_active": True,
                "last_used_at": time_over_7d,
            }
        ]

        cortex.sync_lessons(lessons)
        self.assertIn("lesson_1051", cortex.entry_index, "6 ngay 23 gio chua du 7 ngay, khong duoc prune")
        self.assertNotIn("lesson_1052", cortex.entry_index, "7 ngay 1 gio da vuot qua 7 ngay, phai bi prune")

    def test_06_synaptic_pruning_existing_cortex_concept_removal_and_mmap_zeroing(self) -> None:
        """
        Ca 6: Kiem tra cat tia bai hoc DA TON TAI trong Cortex:
        - Ban dau bai hoc dang active trong Cortex.
        - O chu ky sau, bai hoc bi suy yeu (confidence=0.10, >7 ngay).
        - Khi sync lai: remove_concept duoc kich hoat, mmap slot bi zeroed out, entry_index xoa key.
        """
        cortex = self.brain.cortex
        recent_time = (datetime.now(VN_TZ) - timedelta(days=1)).isoformat()

        # Phase 1: Them bai hoc ban dau
        initial_lessons = [{
            "id": 106,
            "lesson_text": "Bai hoc ban dau co hieu luc",
            "trigger_pattern": "initial_pattern",
            "confidence": 0.80,
            "is_active": True,
            "last_used_at": recent_time,
        }]
        cortex.sync_lessons(initial_lessons)
        self.assertIn("lesson_106", cortex.entry_index)
        slot = cortex.entry_index["lesson_106"]

        if cortex._mmap_obj:
            offset = cortex.HEADER_SIZE + (slot * HV_DIM_BYTES)
            vector_bytes = cortex._mmap_obj[offset:offset + HV_DIM_BYTES]
            self.assertNotEqual(vector_bytes, b"\x00" * HV_DIM_BYTES, "Slot ban dau phai chua vector")

        # Phase 2: Sync dot tiep theo, bai hoc bi giam confidence va disused 10 ngay
        old_time = (datetime.now(VN_TZ) - timedelta(days=10)).isoformat()
        decayed_lessons = [{
            "id": 106,
            "lesson_text": "Bai hoc ban dau da bi suy yeu",
            "trigger_pattern": "initial_pattern",
            "confidence": 0.10,
            "is_active": True,
            "last_used_at": old_time,
        }]
        stats = cortex.sync_lessons(decayed_lessons)
        self.assertEqual(stats["pruned"], 1, "Phai ghi nhan 1 bai hoc bi pruned")
        self.assertNotIn("lesson_106", cortex.entry_index, "Phai xoa khoi entry_index")

        if cortex._mmap_obj:
            offset = cortex.HEADER_SIZE + (slot * HV_DIM_BYTES)
            zeroed_bytes = cortex._mmap_obj[offset:offset + HV_DIM_BYTES]
            self.assertEqual(zeroed_bytes, b"\x00" * HV_DIM_BYTES, "Slot mmap phai duoc ghi zeroed out sach se")

    def test_07_synaptic_pruning_inactive_lessons_always_pruned(self) -> None:
        """
        Ca 7: Bai hoc co is_active = False BAT BUOC bi loai bo bat ke confidence=1.0 va moi dung 1 giay truoc.
        """
        cortex = self.brain.cortex
        fresh_time = datetime.now(VN_TZ).isoformat()

        lessons = [{
            "id": 107,
            "lesson_text": "Bai hoc da bi admin deactive thu cong",
            "trigger_pattern": "manual_disable",
            "confidence": 1.0,
            "is_active": False,
            "last_used_at": fresh_time,
        }]

        stats = cortex.sync_lessons(lessons)
        self.assertEqual(stats["synced"], 0)
        self.assertNotIn("lesson_107", cortex.entry_index)

    def test_08_synaptic_pruning_heterogeneous_timestamp_formats(self) -> None:
        """
        Ca 8: Kha nang chong chiu voi cac dinh dang timestamp da dang:
        - ISO string co timezone (+07:00)
        - Timestamp int / float (Unix epoch)
        - Datetime object truc tiep
        - None (fallback sang created_at)
        - Chuoi khong hop le
        """
        cortex = self.brain.cortex
        now_ts = time.time()
        now_dt = datetime.now(VN_TZ)

        lessons = [
            {
                "id": 1081,
                "lesson_text": "ISO tz format",
                "trigger_pattern": "p1",
                "confidence": 0.20,
                "is_active": True,
                "last_used_at": (now_dt - timedelta(days=2)).isoformat(),
            },
            {
                "id": 1082,
                "lesson_text": "Float epoch format",
                "trigger_pattern": "p2",
                "confidence": 0.20,
                "is_active": True,
                "last_used_at": now_ts - (2 * 86400.0),
            },
            {
                "id": 1083,
                "lesson_text": "Datetime object format",
                "trigger_pattern": "p3",
                "confidence": 0.20,
                "is_active": True,
                "last_used_at": now_dt - timedelta(days=9),
            },
            {
                "id": 1084,
                "lesson_text": "Fallback created_at",
                "trigger_pattern": "p4",
                "confidence": 0.20,
                "is_active": True,
                "last_used_at": None,
                "created_at": (now_dt - timedelta(days=1)).isoformat(),
            },
            {
                "id": 1085,
                "lesson_text": "Invalid string format",
                "trigger_pattern": "p5",
                "confidence": 0.20,
                "is_active": True,
                "last_used_at": "invalid-non-iso-date-string",
            }
        ]

        cortex.sync_lessons(lessons)
        self.assertIn("lesson_1081", cortex.entry_index, "ISO tz gan phai duoc giu lai")
        self.assertIn("lesson_1082", cortex.entry_index, "Epoch float gan phai duoc giu lai")
        self.assertNotIn("lesson_1083", cortex.entry_index, "Datetime object cu phai bi prune")
        self.assertIn("lesson_1084", cortex.entry_index, "Fallback created_at gan phai duoc giu lai")
        self.assertNotIn("lesson_1085", cortex.entry_index, "Invalid timestamp format voi conf<0.25 phai prune an toan")

    # =========================================================================
    # NHOM 2: CHU TRINH SWS & KHOI PHUC HOA CHAT THAN KINH
    # =========================================================================

    async def test_09_sws_cycle_adenosine_flush_efficiency(self) -> None:
        """
        Ca 9: Thu nghiem Adenosine Flush trong Slow-Wave Sleep (SWS):
        - Ap luc met moi Adenosine tich luy cao (0.90).
        - Sau chu ky SWS, Adenosine phai duoc xa sach con <= 15% (nhan he so 0.15).
        """
        self.brain.neuro.adenosine = 0.90
        initial_adenosine = self.brain.neuro.adenosine
        self.assertAlmostEqual(initial_adenosine, 0.90, places=2)

        dream = SubconsciousDreamEngine(
            brain=self.brain,
            llm_router=MagicMock(),
            ssh_client=MagicMock(),
            storage_dir=self.temp_dir,
        )

        res = await dream.run_sws_cycle()
        expected_max_adenosine = initial_adenosine * 0.15 + 0.01
        self.assertLessEqual(res["adenosine"], expected_max_adenosine,
                             f"Adenosine sau SWS ({res['adenosine']}) phai <= 15% muc ban dau ({expected_max_adenosine})")
        self.assertAlmostEqual(self.brain.neuro.adenosine, res["adenosine"])

    async def test_10_sws_cycle_neurochemical_homeostasis(self) -> None:
        """
        Ca 10: Khoi phuc can bang hoa chat than kinh trong SWS:
        - Cortisol (cang thang) phai giam dang ke.
        - Serotonin (thanh than) phai tang (+0.10).
        - Cac hoa chat phai duy tri trong bien do sinh hoc hop le [0.0, 1.0].
        """
        self.brain.neuro.stimulate("cortisol", 0.60)
        self.brain.neuro.serotonin = 0.40
        pre_cortisol = self.brain.neuro.cortisol
        pre_serotonin = self.brain.neuro.serotonin

        dream = SubconsciousDreamEngine(
            brain=self.brain,
            llm_router=MagicMock(),
            ssh_client=MagicMock(),
            storage_dir=self.temp_dir,
        )

        res = await dream.run_sws_cycle()
        self.assertLess(res["cortisol"], pre_cortisol, "Cortisol phai giam sau giac ngu sau SWS")
        self.assertGreater(res["serotonin"], pre_serotonin, "Serotonin phai tang sau SWS")
        self.assertTrue(0.0 <= res["cortisol"] <= 1.0)
        self.assertTrue(0.0 <= res["serotonin"] <= 1.0)

    async def test_11_sws_cycle_working_memory_replay_and_consolidation(self) -> None:
        """
        Ca 11: Mo phong chuoi su kien Hippocampal Episodic Replay va co ket vao Cortex:
        - 3 su kien tu memory_service duoc replay vao working memory cua brain.
        - Qua trinh consolidation bien doi working memory thanh long-term vectors trong Cortex.
        - Working memory tam thoi duoc giai phong sach se.
        """
        mock_mem = MagicMock()
        mock_mem.get_recent_episodes = AsyncMock(
            return_value="🗓️ SỰ KIỆN GẦN ĐÂY:\n- Sự kiện 1: Tối ưu CPU Haswell\n- Sự kiện 2: Kiểm soát ngrok pool\n- Sự kiện 3: Vá lỗi RAM leak"
        )
        mock_mem.consolidation_cycle = AsyncMock(return_value={"decayed": 0, "pruned": 0, "episodes_expired": 0})
        mock_mem.list_lessons_for_display = AsyncMock(return_value=[])

        dream = SubconsciousDreamEngine(
            brain=self.brain,
            llm_router=MagicMock(),
            ssh_client=MagicMock(),
            memory_service=mock_mem,
            storage_dir=self.temp_dir,
        )

        res = await dream.run_sws_cycle()
        self.assertEqual(res["replayed_memories"], 3, "Phai replay dung 3 su kien")
        self.assertGreaterEqual(res["consolidated_vectors"], 3, "Phai chuyen hoa it nhat 3 vectors vao cortex")
        self.assertEqual(len(self.brain.working_memory), 0, "Working memory phai duoc flush ve rong")

    # =========================================================================
    # NHOM 3: CHU TRINH REM & VONG DOI MORNING EPIPHANY
    # =========================================================================

    async def test_12_rem_cycle_valid_epiphany_generation_and_dopamine_surge(self) -> None:
        """
        Ca 12: Giac mo REM sinh Morning Epiphany hop le:
        - LLM sinh insight voi temperature=0.85.
        - Dat chuan JSON: topic, insight, sisterly_note.
        - Thuc day Dopamine (+0.15) va Endorphins (+0.12).
        - Tu dong ma hoa va ket tinh vector vao Virtual Cortex.
        """
        mock_router = MagicMock()
        mock_router.complete = AsyncMock(return_value={
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": json.dumps({
                        "topic": "Hai hoa xung nhip i5-4310U",
                        "insight": "Phan bo luong nhe vao nhan 0 va streaming nang vao nhan 1 giam jitter 35%.",
                        "sisterly_note": "Anh Manh an tam, em luon toi uu hoa tung chu ky may cho anh!"
                    })
                }
            }]
        })

        mock_mem = MagicMock()
        mock_mem.record_episode = AsyncMock()

        dream = SubconsciousDreamEngine(
            brain=self.brain,
            llm_router=mock_router,
            ssh_client=MagicMock(),
            memory_service=mock_mem,
            storage_dir=self.temp_dir,
        )

        pre_dopamine = self.brain.neuro.dopamine
        pre_endorphins = self.brain.neuro.endorphins

        epiphany = await dream.run_rem_dream_cycle(force=True)
        self.assertIsNotNone(epiphany)
        self.assertEqual(epiphany["topic"], "Hai hoa xung nhip i5-4310U")
        self.assertIn("jitter", epiphany["insight"])
        self.assertIn("Anh Manh", epiphany["sisterly_note"])
        self.assertFalse(epiphany["delivered"])

        self.assertGreater(self.brain.neuro.dopamine, pre_dopamine)
        self.assertGreater(self.brain.neuro.endorphins, pre_endorphins)
        self.assertIn(epiphany["id"], self.brain.cortex.entry_index)

    async def test_13_rem_cycle_skip_within_six_hours_unless_forced(self) -> None:
        """
        Ca 13: REM Cycle Cooldown Guard:
        - Neu vua hoan thanh REM cycle trong vong < 6 gio, lan goi tiep theo khong force=True phai BO QUA (None).
        - Neu truyen orce=True, chu trinh van duoc phep chay.
        """
        mock_router = MagicMock()
        mock_router.complete = AsyncMock(return_value={
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": json.dumps({
                        "topic": "Test REM Cooldown",
                        "insight": "Insight test cooldown.",
                        "sisterly_note": "Loi nhan em gai."
                    })
                }
            }]
        })

        dream = SubconsciousDreamEngine(
            brain=self.brain,
            llm_router=mock_router,
            ssh_client=MagicMock(),
            storage_dir=self.temp_dir,
        )

        res1 = await dream.run_rem_dream_cycle(force=True)
        self.assertIsNotNone(res1)
        self.assertEqual(mock_router.complete.call_count, 1)

        res2 = await dream.run_rem_dream_cycle(force=False)
        self.assertIsNone(res2, "Phai bo qua REM cycle neu chua du 6 gio")
        self.assertEqual(mock_router.complete.call_count, 1)

        res3 = await dream.run_rem_dream_cycle(force=True)
        self.assertIsNotNone(res3)
        self.assertEqual(mock_router.complete.call_count, 2)

    def test_14_morning_epiphany_idempotent_single_delivery(self) -> None:
        """
        Ca 14: Dam bao tinh Idempotent / Single-Delivery cua pop_morning_epiphany:
        - Lan goi dau tien trong khung gio sang: Tra ve buc thong diep chao buoi sang am ap.
        - Lan goi thu hai ngay sau do: BAT BUOC tra ve None (da tieu thu xong).
        - pending_morning_epiphany phai chuyen thanh None.
        - Ban ghi duoc luu vao delivered_epiphanies voi co delivered: True.
        """
        dream = SubconsciousDreamEngine(
            brain=self.brain,
            llm_router=MagicMock(),
            ssh_client=MagicMock(),
            storage_dir=self.temp_dir,
        )

        dream.pending_morning_epiphany = {
            "id": "epiphany_single_delivery_test",
            "topic": "Giai phap Cache Zero-Copy",
            "insight": "Toi uu duong dan RAM cho SSD.",
            "sisterly_note": "Chuc anh Manh mot ngay moi lam viec that hieu qua a!",
            "delivered": False,
        }

        with patch.object(SubconsciousDreamEngine, "is_morning_window", return_value=True):
            first_pop = dream.pop_morning_epiphany()
            second_pop = dream.pop_morning_epiphany()

        self.assertIsNotNone(first_pop)
        self.assertIn("Chào buổi sáng anh Mạnh!", first_pop)
        self.assertIn("Giai phap Cache Zero-Copy", first_pop)
        self.assertIn("Chuc anh Manh mot ngay moi", first_pop)

        self.assertIsNone(second_pop, "Lan pop thu 2 bat buoc phai la None de tranh gui trung lap")
        self.assertIsNone(dream.pending_morning_epiphany, "Pending epiphany phai duoc don ve None")
        self.assertEqual(len(dream.delivered_epiphanies), 1)
        self.assertTrue(dream.delivered_epiphanies[0]["delivered"])

    def test_15_morning_epiphany_outside_window_retention(self) -> None:
        """
        Ca 15: Gating khung gio nhan thuc:
        - Neu chua toi khung gio sang (vi du 03:00 dem hoac 14:00 chieu),
          pop_morning_epiphany() phai tra ve None va KHONG DUOC xoa pending_morning_epiphany.
        """
        dream = SubconsciousDreamEngine(
            brain=self.brain,
            llm_router=MagicMock(),
            ssh_client=MagicMock(),
            storage_dir=self.temp_dir,
        )

        dream.pending_morning_epiphany = {
            "id": "epiphany_time_gate_test",
            "topic": "Chiem nghiem dem sau",
            "insight": "Insight chua the tiet lo luc nua dem.",
            "sisterly_note": "Doi sang mai em se gui anh.",
            "delivered": False,
        }

        with patch.object(SubconsciousDreamEngine, "is_morning_window", return_value=False):
            pop_res = dream.pop_morning_epiphany()

        self.assertIsNone(pop_res, "Ngoai khung gio sang, pop_morning_epiphany phai tra ve None")
        self.assertIsNotNone(dream.pending_morning_epiphany, "Pending epiphany phai duoc bao luu nguyen ven")
        self.assertFalse(dream.pending_morning_epiphany["delivered"])

    # =========================================================================
    # NHOM 4: XU LY NGOAI LE & ADVERSARIAL STRESS RESILIENCE
    # =========================================================================

    async def test_16_sws_resilience_empty_db_and_none_episodes(self) -> None:
        """
        Ca 16: Kha nang chong chiu khi Database hoan toan rong:
        - get_recent_episodes tra ve chuoi rong "".
        - list_lessons_for_display tra ve danh sach rong [].
        - SWS cycle phai hoan tat tron tru, khong nem exception, tra ve cac counts = 0.
        """
        mock_mem = MagicMock()
        mock_mem.get_recent_episodes = AsyncMock(return_value="")
        mock_mem.consolidation_cycle = AsyncMock(return_value={"decayed": 0, "pruned": 0, "episodes_expired": 0})
        mock_mem.list_lessons_for_display = AsyncMock(return_value=[])

        dream = SubconsciousDreamEngine(
            brain=self.brain,
            llm_router=MagicMock(),
            ssh_client=MagicMock(),
            memory_service=mock_mem,
            storage_dir=self.temp_dir,
        )

        res = await dream.run_sws_cycle()
        self.assertEqual(res["phase"], "SWS")
        self.assertEqual(res["replayed_memories"], 0)
        self.assertEqual(res["pruned_lessons"], 0)
        self.assertEqual(res["synced_cortex_vectors"], 0)

    async def test_17_sws_resilience_none_memory_service(self) -> None:
        """
        Ca 17: Kha nang chay doc lap khi memory_service = None:
        - Khong phu thuoc vao database PostgreSQL.
        - Van thuc hien cung co working memory cua nao bo va flush Adenosine.
        """
        dream = SubconsciousDreamEngine(
            brain=self.brain,
            llm_router=MagicMock(),
            ssh_client=MagicMock(),
            memory_service=None,
            storage_dir=self.temp_dir,
        )

        self.brain.neuro.accumulate_adenosine(0.50)
        res = await dream.run_sws_cycle()
        self.assertEqual(res["phase"], "SWS")
        self.assertLess(res["adenosine"], 0.10)

    async def test_18_sws_resilience_memory_service_exceptions(self) -> None:
        """
        Ca 18: Ngoai le nghiem trong tu Database Memory Service:
        - get_recent_episodes nem ConnectionRefusedError.
        - consolidation_cycle nem TimeoutError.
        - list_lessons_for_display nem RuntimeError.
        - SWS cycle bat loi gracefully, khong crash tien trinh, tiep tuc hoan tat cac buoc tiep theo.
        """
        mock_mem = MagicMock()
        mock_mem.get_recent_episodes = AsyncMock(side_effect=ConnectionRefusedError("Postgres down"))
        mock_mem.consolidation_cycle = AsyncMock(side_effect=TimeoutError("Lock timeout"))
        mock_mem.list_lessons_for_display = AsyncMock(side_effect=RuntimeError("Corrupt table"))

        dream = SubconsciousDreamEngine(
            brain=self.brain,
            llm_router=MagicMock(),
            ssh_client=MagicMock(),
            memory_service=mock_mem,
            storage_dir=self.temp_dir,
        )

        res = await dream.run_sws_cycle()
        self.assertEqual(res["phase"], "SWS")
        self.assertEqual(res["replayed_memories"], 0)
        self.assertEqual(res["pruned_lessons"], 0)
        self.assertEqual(res["synced_cortex_vectors"], 0)

    async def test_19_rem_resilience_llm_router_exceptions_and_empty_response(self) -> None:
        """
        Ca 19: Xu ly su co mang LLM Router trong giac mo REM:
        - Router nem ngoai le HTTP 429 RateLimitError, 500 InternalServerError hoac tra None.
        - un_rem_dream_cycle() bat loi an toan, ghi log, tra ve None ma khong crash.
        """
        mock_router = MagicMock()
        mock_router.complete = AsyncMock(side_effect=Exception("Groq HTTP 429: TPM Rate limit exceeded"))

        dream = SubconsciousDreamEngine(
            brain=self.brain,
            llm_router=mock_router,
            ssh_client=MagicMock(),
            storage_dir=self.temp_dir,
        )

        res = await dream.run_rem_dream_cycle(force=True)
        self.assertIsNone(res, "Khi LLM Router nem Exception, REM cycle phai tra ve None an toan")

        mock_router.complete = AsyncMock(return_value=None)
        res_none = await dream.run_rem_dream_cycle(force=True)
        self.assertIsNone(res_none, "Khi LLM Router tra None, REM cycle phai tra ve None an toan")

    async def test_20_rem_resilience_malformed_json_fallback_extraction(self) -> None:
        """
        Ca 20: Chong chiu phan hoi JSON di dang / boc markdown tu LLM:
        - TH 1: Markdown codeblock `json ... ` -> boc tach dung.
        - TH 2: Truncated JSON thieu dau dong '}' -> regex fallback thanh cong.
        - TH 3: Rac khong co truong insight -> None an toan.
        """
        mock_router = MagicMock()
        dream = SubconsciousDreamEngine(
            brain=self.brain,
            llm_router=mock_router,
            ssh_client=MagicMock(),
            storage_dir=self.temp_dir,
        )

        # TH 1
        wrapped_json = "`json\n{\n  \"topic\": \"Boc Markdown\",\n  \"insight\": \"Van trich xuat duoc.\",\n  \"sisterly_note\": \"Yeu quy anh.\"\n}\n`"
        mock_router.complete = AsyncMock(return_value={"choices": [{"message": {"content": wrapped_json}}]})
        res1 = await dream.run_rem_dream_cycle(force=True)
        self.assertIsNotNone(res1)
        self.assertEqual(res1["topic"], "Boc Markdown")

        # TH 2
        truncated_json = '{\n  "topic": "Truncated Topic",\n  "insight": "Insight bi ngat quang giua chung",\n  "sisterly_note": "Loi nhan'
        mock_router.complete = AsyncMock(return_value={"choices": [{"message": {"content": truncated_json}}]})
        res2 = await dream.run_rem_dream_cycle(force=True)
        self.assertIsNotNone(res2)
        self.assertEqual(res2["topic"], "Truncated Topic")
        self.assertIn("Insight bi ngat", res2["insight"])

        # TH 3
        garbage_reply = "Xin loi, toi khong the mo duoc."
        mock_router.complete = AsyncMock(return_value={"choices": [{"message": {"content": garbage_reply}}]})
        res3 = await dream.run_rem_dream_cycle(force=True)
        self.assertIsNone(res3, "Khong co insight field phai tra ve None an toan")

    async def test_21_hardware_idle_check_ssh_resilience(self) -> None:
        """
        Ca 21: Kiem tra chong chiu loi cua check_hardware_idle:
        - Khi SSH client nem ngoai le, ham fallback ve (True, 'Night window default').
        """
        mock_ssh = MagicMock()
        mock_ssh.execute_command = AsyncMock(side_effect=Exception("SSH Connection reset"))

        dream = SubconsciousDreamEngine(
            brain=self.brain,
            llm_router=MagicMock(),
            ssh_client=mock_ssh,
            storage_dir=self.temp_dir,
        )

        is_idle, reason = await dream.check_hardware_idle()
        self.assertTrue(is_idle)
        self.assertEqual(reason, "Night window default")

    def test_22_cache_persistence_corrupt_file_recovery(self) -> None:
        """
        Ca 22: Chong chiu su co tap tin bo nho dem (epiphany_cache.json) bi hong / corrupt:
        - Ghi chuoi json rac vao cache_file.
        - Khoi tao engine moi: _load_cache() bat ngoai le va khong crash.
        """
        cache_file = self.temp_dir / "epiphany_cache.json"
        with open(cache_file, "w", encoding="utf-8") as f:
            f.write("{ corrupt json truncated content ... [[")

        dream = SubconsciousDreamEngine(
            brain=self.brain,
            llm_router=MagicMock(),
            ssh_client=MagicMock(),
            storage_dir=self.temp_dir,
        )

        self.assertIsNone(dream.pending_morning_epiphany)
        self.assertEqual(dream.delivered_epiphanies, [])


if __name__ == "__main__":
    unittest.main()
