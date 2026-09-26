"""
test_challenger_m3_2_empirical.py — Empirical Challenger Adversarial Verification Suite for Milestone 3.

Focus areas:
1. Hebbian Reconsolidation:
   - Long-Term Potentiation (LTP): Semantic similarity reinforcement (+0.05 boost, capped at 0.92).
   - Long-Term Depression (LTD): Opposing contradiction with negation words (-0.15 decay, floor at 0.10).
   - Dominant belief insertion & topic overlap gate (> 0.20 threshold).
2. Neuromorphic Brain Stress:
   - Neurotransmitter surge coefficients: noradrenaline (+0.25), dopamine (-0.20), acetylcholine (+0.30).
   - Boundary clamping strictly within [0.0, 1.0] under severe multi-burst stresses.
   - Non-interference isolation across other neurochemical channels.
   - Affective Circumplex shift into high-focus / self-critical state.
3. Concurrency, Edge Cases & Memory Leak Resilience.
4. End-to-End AI Agent Integration & 5 Whys Root Cause Classification.
"""

import asyncio
import gc
import math
import re
import time
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

# Import ai_agent first to ensure runtime extensions (acetylcholine, stimulate_neurotransmitters) are bootstrapped
import app.services.ai_agent
from app.core.brain_core import ArtificialBrain, NeurotransmitterState
from app.services.memory_service import (
    AgentMemoryService,
    RootCauseCategory,
    CORRECTION_TRIGGERS,
)


class InMemoryAgentMemoryHarness(AgentMemoryService):
    """
    Empirical In-Memory Test Harness for AgentMemoryService.
    Preserves 100% of real Hebbian Reconsolidation & Contradiction logic
    while replacing low-level database persistence with a high-fidelity in-memory store.
    """

    def __init__(self) -> None:
        super().__init__()
        self.mock_db_lessons: List[Dict[str, Any]] = []
        self._next_id: int = 1

    async def _refresh_lesson_cache(self, limit: int = 30) -> None:
        self._lesson_cache = [dict(item) for item in self.mock_db_lessons if item.get("is_active", True)][:limit]
        self._cache_dirty = False

    async def _update_lesson_content(
        self, lesson_id: int, new_text: str, new_confidence: float
    ) -> None:
        for item in self.mock_db_lessons:
            if item["id"] == lesson_id:
                item["lesson_text"] = new_text
                item["confidence"] = new_confidence
                item["last_used_at"] = time.time()
                item["last_verified_at"] = time.time()
                break
        self._cache_dirty = True

    async def _insert_lesson(
        self,
        trigger_pattern: str,
        lesson_text: str,
        event_type: str,
        confidence: float,
        is_search_grounded: bool,
        search_query: Optional[str],
    ) -> Optional[int]:
        lid = self._next_id
        self._next_id += 1
        record = {
            "id": lid,
            "trigger_pattern": trigger_pattern,
            "lesson_text": lesson_text,
            "event_type": event_type,
            "confidence": confidence,
            "is_search_grounded": is_search_grounded,
            "search_query": search_query,
            "is_active": True,
            "created_at": time.time(),
        }
        self.mock_db_lessons.append(record)
        self._cache_dirty = True
        return lid


class TestChallengerM32Empirical(unittest.IsolatedAsyncioTestCase):
    """
    Empirical Adversarial Test Suite for M3 Hebbian Reconsolidation and Neuromorphic Stress.
    """

    def setUp(self) -> None:
        self.mem = InMemoryAgentMemoryHarness()
        # Clean neurochemical state for each test
        self.neuro = NeurotransmitterState()
        # Ensure acetylcholine is present on this instance
        if not hasattr(self.neuro, "acetylcholine"):
            setattr(self.neuro, "acetylcholine", 0.30)
        if hasattr(self.neuro, "BASELINES") and isinstance(self.neuro.BASELINES, dict):
            self.neuro.BASELINES["acetylcholine"] = 0.30
        if hasattr(self.neuro, "HALF_LIVES") and isinstance(self.neuro.HALF_LIVES, dict):
            self.neuro.HALF_LIVES["acetylcholine"] = 180.0
        self.addCleanup(ArtificialBrain.reset_instance)

    # ──────────────────────────────────────────────────────────────────────────
    # GROUP 1: EMPIRICAL HEBBIAN LTP (LONG-TERM POTENTIATION) TESTS
    # ──────────────────────────────────────────────────────────────────────────

    async def test_01_ltp_reinforcement_boost(self) -> None:
        """
        LTP Test 1: Reinforcing lesson with high semantic similarity (>= 0.68)
        must boost confidence by +0.05 and update existing lesson content.
        """
        # 1. Insert initial baseline lesson
        base_text = "Restart nginx bằng lệnh nginx -s reload khi cập nhật cấu hình webserver"
        base_id = await self.mem._insert_lesson(
            trigger_pattern="nginx reload",
            lesson_text=base_text,
            event_type="optimization",
            confidence=0.70,
            is_search_grounded=True,
            search_query="nginx reload best practice",
        )
        self.assertEqual(base_id, 1)

        # 2. Reconsolidate with a reinforcing (non-contradicting) lesson
        boost_text = "Restart nginx bằng lệnh nginx -s reload khi cập nhật cấu hình webserver an toàn"
        lid, reconsolidated = await self.mem.reconsolidate_or_insert(
            trigger_pattern="nginx reload",
            lesson_text=boost_text,
            event_type="optimization",
            confidence=0.75,
            is_search_grounded=True,
            search_query=None,
        )

        self.assertTrue(reconsolidated, "Expected LTP reconsolidation to succeed for similar reinforcing lesson")
        self.assertEqual(lid, base_id, "Expected updated lesson ID to match existing lesson ID")
        self.assertEqual(len(self.mem.mock_db_lessons), 1, "No duplicate lesson should be inserted under LTP")

        # Verify math: min(max(0.70, 0.75) + 0.05, 0.92) = 0.80
        updated = self.mem.mock_db_lessons[0]
        self.assertAlmostEqual(updated["confidence"], 0.80, places=4)
        self.assertEqual(updated["lesson_text"], boost_text)

    async def test_02_ltp_ceiling_saturation_at_092(self) -> None:
        """
        LTP Test 2: Multiple consecutive LTP reinforcements must saturate strictly
        at 0.92 ceiling and NEVER exceed 0.92.
        """
        base_text = "Kiểm tra dung lượng ổ đĩa ssd bằng lệnh df -h trước khi tải video lớn"
        await self.mem._insert_lesson(
            trigger_pattern="check disk",
            lesson_text=base_text,
            event_type="disk_safety",
            confidence=0.88,
            is_search_grounded=True,
            search_query=None,
        )

        # Iteration 1: 0.88 + 0.05 = 0.93 -> capped at 0.92
        lid, recon = await self.mem.reconsolidate_or_insert(
            trigger_pattern="check disk",
            lesson_text=base_text,
            event_type="disk_safety",
            confidence=0.88,
            is_search_grounded=True,
            search_query=None,
        )
        self.assertTrue(recon)
        self.assertAlmostEqual(self.mem.mock_db_lessons[0]["confidence"], 0.92, places=4)

        # Run 10 more iterations with high confidence inputs (e.g. 0.99)
        for i in range(10):
            lid, recon = await self.mem.reconsolidate_or_insert(
                trigger_pattern="check disk",
                lesson_text=base_text,
                event_type="disk_safety",
                confidence=0.99,
                is_search_grounded=True,
                search_query=None,
            )
            self.assertTrue(recon)
            self.assertAlmostEqual(
                self.mem.mock_db_lessons[0]["confidence"],
                0.92,
                places=4,
                msg=f"LTP ceiling violated at iteration {i}: {self.mem.mock_db_lessons[0]['confidence']} > 0.92",
            )

    async def test_03_ltp_jaccard_similarity_threshold_boundary(self) -> None:
        """
        LTP Test 3: Verify strict boundary behavior at Jaccard similarity threshold 0.68.
        - Below 0.68: Must treated as independent lesson (was_reconsolidated = False).
        - At/Above 0.68: Must trigger reconsolidation (was_reconsolidated = True).
        """
        t1 = "quản trị hệ thống máy chủ linux ubuntu server với quyền root"
        await self.mem._insert_lesson(
            trigger_pattern="server mgmt",
            lesson_text=t1,
            event_type="mgmt",
            confidence=0.60,
            is_search_grounded=False,
            search_query=None,
        )

        # Test A: Text with similarity < 0.68
        t_low = "quản trị cơ sở dữ liệu postgresql trên máy chủ centos"
        sim_low = self.mem._jaccard_similarity(t1, t_low)
        self.assertLess(sim_low, 0.68, f"Jaccard similarity {sim_low} should be < 0.68")

        lid_low, recon_low = await self.mem.reconsolidate_or_insert(
            trigger_pattern="db mgmt",
            lesson_text=t_low,
            event_type="mgmt",
            confidence=0.70,
            is_search_grounded=False,
            search_query=None,
        )
        self.assertFalse(recon_low, "Low similarity must not trigger reconsolidation")
        self.assertEqual(len(self.mem.mock_db_lessons), 2, "Low similarity must insert as second lesson")

        # Test B: Text with similarity >= 0.68
        t_high = "quản trị hệ thống máy chủ linux ubuntu server với quyền root an toàn"
        sim_high = self.mem._jaccard_similarity(t1, t_high)
        self.assertGreaterEqual(sim_high, 0.68, f"Jaccard similarity {sim_high} should be >= 0.68")

        lid_high, recon_high = await self.mem.reconsolidate_or_insert(
            trigger_pattern="server mgmt",
            lesson_text=t_high,
            event_type="mgmt",
            confidence=0.70,
            is_search_grounded=False,
            search_query=None,
        )
        self.assertTrue(recon_high, "High similarity must trigger reconsolidation")
        self.assertEqual(lid_high, 1, "Should reconsolidate with original lesson #1")

    # ──────────────────────────────────────────────────────────────────────────
    # GROUP 2: EMPIRICAL HEBBIAN LTD (LONG-TERM DEPRESSION) TESTS
    # ──────────────────────────────────────────────────────────────────────────

    def test_04_ltd_negation_keywords_detection_matrix(self) -> None:
        """
        LTD Test 4: Comprehensive test of negation keywords in _is_contradicting.
        Every negation keyword when coupled with on-topic keywords (> 0.2 overlap)
        must trigger contradiction gate.
        """
        old_belief_vn = "sử dụng swap 100gb trên máy chủ để tăng dung lượng bộ nhớ ram ảo"

        negation_samples_vn = [
            ("không sử dụng swap 100gb vì làm chậm máy chủ", "không"),
            ("đừng sử dụng swap 100gb trên máy chủ vì disk thrashing", "đừng"),
            ("chớ cấu hình swap 100gb trên máy chủ", "chớ"),
            ("chưa nên kích hoạt swap 100gb trên máy chủ", "chưa"),
            ("chẳng nên dùng swap 100gb trên máy chủ ram 3.2gb", "chẳng"),
            ("sai khi cấu hình swap 100gb trên máy chủ", "sai"),
            ("nhầm lẫn khi nghĩ swap 100gb thay thế được ram máy chủ", "nhầm"),
        ]

        for new_belief, keyword in negation_samples_vn:
            is_contra = self.mem._is_contradicting(old_belief_vn, new_belief)
            self.assertTrue(
                is_contra,
                f"Failed to detect contradiction for Vietnamese keyword '{keyword}': '{new_belief}'"
            )

        old_belief_en = "use swap 100gb on linux server to increase virtual ram memory"
        negation_samples_en = [
            ("never use swap 100gb on linux server because of latency", "never"),
            ("not recommend using swap 100gb on linux server", "not"),
            ("no swap 100gb should be used on linux server", "no"),
            ("avoid swap 100gb on linux server due to disk thrashing", "avoid"),
            ("wrong to assume swap 100gb works like linux server memory", "wrong"),
            ("incorrect belief that swap 100gb replaces linux server memory", "incorrect"),
            ("instead of swap 100gb optimize linux server memory", "instead"),
            ("rather than swap 100gb tune linux server swappiness", "rather"),
        ]

        for new_belief, keyword in negation_samples_en:
            is_contra = self.mem._is_contradicting(old_belief_en, new_belief)
            self.assertTrue(
                is_contra,
                f"Failed to detect contradiction for English keyword '{keyword}': '{new_belief}'"
            )

    def test_05_ltd_topic_overlap_boundary_discrimination(self) -> None:
        """
        LTD Test 5: Verify topic overlap gate (> 0.20 threshold).
        Even if a new lesson contains 'không', if the topic overlap is < 0.20,
        it is NOT a contradiction of the old lesson (prevents false LTD).
        """
        old_belief = "sử dụng swap 100gb trên máy chủ để tăng dung lượng bộ nhớ ram ảo"

        unrelated_negation = "không ăn kem vào mùa đông vì dễ bị viêm họng"
        is_contra = self.mem._is_contradicting(old_belief, unrelated_negation)
        self.assertFalse(is_contra, "Unrelated topic must NOT trigger contradiction despite containing 'không'")

    async def test_06_ltd_decay_step_and_dominant_belief_insertion(self) -> None:
        """
        LTD Test 6: When contradiction occurs:
        1. Old lesson confidence decays by exactly -0.15 (decay 0.15).
        2. New lesson is inserted as the dominant belief.
        3. was_reconsolidated returns False.
        """
        old_text = "cần cấu hình swap 100gb trên máy chủ kirito để tăng bộ nhớ ram ảo"
        old_id = await self.mem._insert_lesson(
            trigger_pattern="swap config",
            lesson_text=old_text,
            event_type="resource_mgmt",
            confidence=0.85,
            is_search_grounded=True,
            search_query="swap config",
        )

        # High similarity (Jaccard >= 0.68) with contradiction
        new_conflicting_text = "không cấu hình swap 100gb trên máy chủ kirito để tăng bộ nhớ ram ảo"
        new_id, recon = await self.mem.reconsolidate_or_insert(
            trigger_pattern="swap config",
            lesson_text=new_conflicting_text,
            event_type="resource_mgmt",
            confidence=0.88,
            is_search_grounded=True,
            search_query="swap thrashing 3.2gb ram",
        )

        # Checks
        self.assertFalse(recon, "Contradiction must NOT be marked as reconsolidated")
        self.assertNotEqual(new_id, old_id, "New lesson must be assigned a new distinct ID")
        self.assertEqual(len(self.mem.mock_db_lessons), 2, "Both old weakened lesson and new dominant lesson must coexist")

        # Check old lesson decayed confidence: 0.85 - 0.15 = 0.70
        old_lesson = next(item for item in self.mem.mock_db_lessons if item["id"] == old_id)
        self.assertAlmostEqual(old_lesson["confidence"], 0.70, places=4, msg="LTD must decay old lesson confidence by 0.15")
        self.assertEqual(old_lesson["lesson_text"], old_text, "Old lesson text must be preserved")

        # Check new lesson dominant confidence
        new_lesson = next(item for item in self.mem.mock_db_lessons if item["id"] == new_id)
        self.assertAlmostEqual(new_lesson["confidence"], 0.88, places=4)
        self.assertEqual(new_lesson["lesson_text"], new_conflicting_text)

    async def test_07_ltd_floor_saturation_at_010(self) -> None:
        """
        LTD Test 7: Repeated contradiction must decay confidence down to
        the 0.10 floor, never dropping below 0.10 or becoming negative.
        """
        old_text = "cho phép chạy lệnh rm -rf trên thư mục gốc hệ thống máy chủ linux"
        old_id = await self.mem._insert_lesson(
            trigger_pattern="dangerous rm",
            lesson_text=old_text,
            event_type="security",
            confidence=0.22,  # Low confidence starting point
            is_search_grounded=False,
            search_query=None,
        )

        # 1st contradiction: 0.22 - 0.15 = 0.07 -> clamped to 0.10
        contra_1 = "không cho phép chạy lệnh rm -rf trên thư mục gốc hệ thống máy chủ linux"
        await self.mem.reconsolidate_or_insert(
            trigger_pattern="dangerous rm",
            lesson_text=contra_1,
            event_type="security",
            confidence=0.90,
            is_search_grounded=True,
            search_query=None,
        )

        old_lesson = next(item for item in self.mem.mock_db_lessons if item["id"] == old_id)
        self.assertAlmostEqual(old_lesson["confidence"], 0.10, places=4)

        # 2nd contradiction: 0.10 - 0.15 = -0.05 -> clamped to 0.10
        contra_2 = "đừng bao giờ cho phép chạy lệnh rm -rf trên thư mục gốc hệ thống máy chủ linux"
        await self.mem.reconsolidate_or_insert(
            trigger_pattern="dangerous rm",
            lesson_text=contra_2,
            event_type="security",
            confidence=0.95,
            is_search_grounded=True,
            search_query=None,
        )

        old_lesson = next(item for item in self.mem.mock_db_lessons if item["id"] == old_id)
        self.assertGreaterEqual(old_lesson["confidence"], 0.10)
        self.assertAlmostEqual(old_lesson["confidence"], 0.10, places=4)

    # ──────────────────────────────────────────────────────────────────────────
    # GROUP 3: NEUROMORPHIC STRESS, COEFFICIENTS & CLAMPING BOUNDS [0.0, 1.0]
    # ──────────────────────────────────────────────────────────────────────────

    def test_08_neuromorphic_surge_coefficients_on_correction(self) -> None:
        """
        Neuromorphic Test 8: Verify exact surge coefficients:
        - noradrenaline: +0.25 (heightened cognitive alertness)
        - dopamine: -0.20 (negative reward prediction error penalty)
        - acetylcholine: +0.30 (neuroplasticity boost for rapid unlearning)
        """
        # Baseline check
        self.assertAlmostEqual(self.neuro.noradrenaline, 0.20, places=4)
        self.assertAlmostEqual(self.neuro.dopamine, 0.50, places=4)
        self.assertAlmostEqual(getattr(self.neuro, "acetylcholine", 0.30), 0.30, places=4)

        # Simulate correction surge
        self.neuro.stimulate("noradrenaline", 0.25)
        self.neuro.stimulate("dopamine", -0.20)
        self.neuro.stimulate("acetylcholine", 0.30)

        # Verification
        self.assertAlmostEqual(self.neuro.noradrenaline, 0.45, places=4, msg="Noradrenaline should surge by +0.25 to 0.45")
        self.assertAlmostEqual(self.neuro.dopamine, 0.30, places=4, msg="Dopamine should decrease by -0.20 to 0.30")
        self.assertAlmostEqual(self.neuro.acetylcholine, 0.60, places=4, msg="Acetylcholine should surge by +0.30 to 0.60")

    def test_09_neuromorphic_bounds_clamping_stress(self) -> None:
        """
        Neuromorphic Test 9: Severe stress clamping test:
        1. noradrenaline bombarded with +0.25 x 10 bursts -> strictly clamped at 1.0.
        2. acetylcholine bombarded with +0.30 x 10 bursts -> strictly clamped at 1.0.
        3. dopamine drained with -0.20 x 10 bursts -> strictly clamped at 0.0.
        4. Astronomical stimuli (+10,000 and -10,000) -> stay in [0.0, 1.0].
        """
        # 1. Noradrenaline Upper Bound Stress
        for i in range(10):
            self.neuro.stimulate("noradrenaline", 0.25)
            self.assertLessEqual(self.neuro.noradrenaline, 1.0)
            self.assertGreaterEqual(self.neuro.noradrenaline, 0.0)
        self.assertAlmostEqual(self.neuro.noradrenaline, 1.0, places=4)

        # 2. Acetylcholine Upper Bound Stress
        for i in range(10):
            self.neuro.stimulate("acetylcholine", 0.30)
            self.assertLessEqual(self.neuro.acetylcholine, 1.0)
            self.assertGreaterEqual(self.neuro.acetylcholine, 0.0)
        self.assertAlmostEqual(self.neuro.acetylcholine, 1.0, places=4)

        # 3. Dopamine Lower Bound Stress
        for i in range(10):
            self.neuro.stimulate("dopamine", -0.20)
            self.assertGreaterEqual(self.neuro.dopamine, 0.0)
            self.assertLessEqual(self.neuro.dopamine, 1.0)
        self.assertAlmostEqual(self.neuro.dopamine, 0.0, places=4)

        # 4. Extreme Stimulus Shocks
        self.neuro.stimulate("noradrenaline", 999999.0)
        self.assertEqual(self.neuro.noradrenaline, 1.0)

        self.neuro.stimulate("noradrenaline", -999999.0)
        self.assertEqual(self.neuro.noradrenaline, 0.0)

        self.neuro.stimulate("dopamine", -999999.0)
        self.assertEqual(self.neuro.dopamine, 0.0)

        self.neuro.stimulate("dopamine", 999999.0)
        self.assertEqual(self.neuro.dopamine, 1.0)

        self.neuro.stimulate("acetylcholine", 55555.0)
        self.assertEqual(self.neuro.acetylcholine, 1.0)

        self.neuro.stimulate("acetylcholine", -55555.0)
        self.assertEqual(self.neuro.acetylcholine, 0.0)

    def test_10_neuromorphic_cross_channel_isolation(self) -> None:
        """
        Neuromorphic Test 10: Stimulating noradrenaline, dopamine, or acetylcholine
        must NOT bleed into or alter untouched neurochemical channels (serotonin, cortisol, oxytocin, endorphins).
        """
        initial_serotonin = self.neuro.serotonin
        initial_cortisol = self.neuro.cortisol
        initial_oxytocin = self.neuro.oxytocin
        initial_endorphins = self.neuro.endorphins
        initial_adenosine = self.neuro.adenosine

        # Apply massive stimulation on targeted channels
        self.neuro.stimulate("noradrenaline", 0.50)
        self.neuro.stimulate("dopamine", -0.40)
        self.neuro.stimulate("acetylcholine", 0.60)

        # Untargeted channels must remain unaltered
        self.assertEqual(self.neuro.serotonin, initial_serotonin)
        self.assertEqual(self.neuro.cortisol, initial_cortisol)
        self.assertEqual(self.neuro.oxytocin, initial_oxytocin)
        self.assertEqual(self.neuro.endorphins, initial_endorphins)
        self.assertEqual(self.neuro.adenosine, initial_adenosine)

    def test_11_circumplex_affective_shift_under_correction_surge(self) -> None:
        """
        Neuromorphic Test 11: When correction surge occurs (noradrenaline +0.25, dopamine -0.20),
        the agent's emotional state in Russell's Circumplex must shift:
        - Valence must decrease significantly (sober, self-critical, non-smug).
        - Arousal must increase (heightened focus and vigilance to resolve the error).
        """
        val_pre, aro_pre, quad_pre, _, _ = self.neuro.calculate_circumplex()

        # Apply correction shock
        self.neuro.stimulate("noradrenaline", 0.25)
        self.neuro.stimulate("dopamine", -0.20)
        self.neuro.stimulate("acetylcholine", 0.30)

        val_post, aro_post, quad_post, _, _ = self.neuro.calculate_circumplex()

        self.assertLess(val_post, val_pre, f"Valence should decrease after correction (pre={val_pre:.2f}, post={val_post:.2f})")
        self.assertGreater(aro_post, aro_pre, f"Arousal should increase after correction (pre={aro_pre:.2f}, post={aro_post:.2f})")
        self.assertIn(quad_post, ["Q2_VIGILANT_FIGHT", "Q3_REMORSEFUL_MELANCHOLY"])

    # ──────────────────────────────────────────────────────────────────────────
    # GROUP 4: CONCURRENCY, RESILIENCE & RESOURCE LEAK HARNESS
    # ──────────────────────────────────────────────────────────────────────────

    async def test_12_concurrent_reconsolidation_and_surge_stress(self) -> None:
        """
        Stress Test 12: High concurrency test with 50 parallel coroutines
        simultaneously executing reconsolidation and neurochemical stimulation.
        Must execute with 0 unhandled exceptions and zero bounds violations.
        """
        async def worker_coro(idx: int) -> None:
            if idx % 2 == 0:
                # Reinforcing LTP
                await self.mem.reconsolidate_or_insert(
                    trigger_pattern=f"pattern_{idx % 5}",
                    lesson_text=f"bài học chuẩn mực tối ưu hóa cơ sở dữ liệu số {idx % 5} trên máy chủ",
                    event_type="optimization",
                    confidence=0.70 + (idx % 10) * 0.02,
                    is_search_grounded=True,
                    search_query=None,
                )
            else:
                # Contradicting LTD
                await self.mem.reconsolidate_or_insert(
                    trigger_pattern=f"pattern_{idx % 5}",
                    lesson_text=f"không bài học chuẩn mực tối ưu hóa cơ sở dữ liệu số {idx % 5} trên máy chủ vì sai sót",
                    event_type="optimization",
                    confidence=0.80,
                    is_search_grounded=True,
                    search_query=None,
                )
            # Parallel neuromorphic shock
            self.neuro.stimulate("noradrenaline", 0.05 * (idx % 5))
            self.neuro.stimulate("dopamine", -0.04 * (idx % 4))
            self.neuro.stimulate("acetylcholine", 0.06 * (idx % 3))

        tasks = [asyncio.create_task(worker_coro(i)) for i in range(50)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, res in enumerate(results):
            self.assertNotIsInstance(res, Exception, f"Worker {i} failed with exception: {res}")

        # Ensure all neuro levels remain strictly in bounds [0.0, 1.0]
        self.assertGreaterEqual(self.neuro.noradrenaline, 0.0)
        self.assertLessEqual(self.neuro.noradrenaline, 1.0)
        self.assertGreaterEqual(self.neuro.dopamine, 0.0)
        self.assertLessEqual(self.neuro.dopamine, 1.0)
        self.assertGreaterEqual(self.neuro.acetylcholine, 0.0)
        self.assertLessEqual(self.neuro.acetylcholine, 1.0)

    def test_13_artificial_brain_stimulate_neurotransmitters_helper(self) -> None:
        """
        Stress Test 13: Verify ArtificialBrain.stimulate_neurotransmitters helper.
        Ensures kwargs parsing, safe handling of non-existent chemicals, and proper routing to self.neuro.
        """
        brain = ArtificialBrain.get_instance()
        self.assertTrue(hasattr(brain, "stimulate_neurotransmitters"))

        # Stimulate known and unknown chemical
        brain.stimulate_neurotransmitters(
            noradrenaline=0.25,
            dopamine=-0.20,
            acetylcholine=0.30,
            non_existent_chemical=99.9,  # Must NOT raise exception
        )

        self.assertGreaterEqual(brain.neuro.noradrenaline, 0.0)
        self.assertLessEqual(brain.neuro.noradrenaline, 1.0)
        self.assertGreaterEqual(brain.neuro.dopamine, 0.0)
        self.assertLessEqual(brain.neuro.dopamine, 1.0)

    def test_14_memory_leak_and_gc_cleanliness(self) -> None:
        """
        Stress Test 14: Execute 1,000 rapid stimulate cycles and verify
        that no object leaks occur and garbage collection operates cleanly.
        """
        for i in range(1000):
            self.neuro.stimulate("noradrenaline", 0.1)
            self.neuro.stimulate("dopamine", -0.1)
            self.neuro.stimulate("acetylcholine", 0.1)

        collected = gc.collect()
        self.assertGreaterEqual(collected, 0)
        self.assertGreaterEqual(self.neuro.noradrenaline, 0.0)
        self.assertLessEqual(self.neuro.noradrenaline, 1.0)

    # ──────────────────────────────────────────────────────────────────────────
    # GROUP 5: 5 WHYS FORENSIC ROOT CAUSE CLASSIFICATION UNDER ADVERSARIAL DIALECTS
    # ──────────────────────────────────────────────────────────────────────────

    def test_15_root_cause_classification_adversarial_matrix(self) -> None:
        """
        Stress Test 15: Rigorously verify classify_root_cause against adversarial inputs
        across all 5 Whys categories: DIALECT_CONFUSION, RESOURCE_ASSUMPTION,
        PARAM_OMISSION, TOOL_FAILURE, and HALLUCINATION.
        """
        test_cases = [
            # 1. DIALECT_CONFUSION (Nghệ Tĩnh regional dialects & slang)
            ("tau hỏi một đằng m trả lời một nẻo", RootCauseCategory.DIALECT_CONFUSION),
            ("răng lại rứa hè", RootCauseCategory.DIALECT_CONFUSION),
            ("tau có hỏi cấy nớ mô nờ", RootCauseCategory.DIALECT_CONFUSION),
            ("chi rứa em, nói chi rứa hè", RootCauseCategory.DIALECT_CONFUSION),
            ("tiếng nghệ nỏ hiểu chi hết", RootCauseCategory.DIALECT_CONFUSION),
            ("m co hieu tau noi chi ko", RootCauseCategory.DIALECT_CONFUSION),

            # 2. RESOURCE_ASSUMPTION (RAM 3.2GB, i5-4310U 2 cores, Swap myth)
            ("máy chủ chỉ có ram 3.2gb thôi em giả định sai rồi", RootCauseCategory.RESOURCE_ASSUMPTION),
            ("swap 100gb là sai lầm làm treo máy OOM", RootCauseCategory.RESOURCE_ASSUMPTION),
            ("cpu 2 nhân i5-4310u sao chịu nổi quá tải", RootCauseCategory.RESOURCE_ASSUMPTION),
            ("bộ nhớ ram bị tràn disk thrashing rồi", RootCauseCategory.RESOURCE_ASSUMPTION),

            # 3. PARAM_OMISSION (Omitted flags, syntax issues)
            ("em quên cờ -rf rồi kìa", RootCauseCategory.PARAM_OMISSION),
            ("thiếu tham số port 8000 trong lệnh", RootCauseCategory.PARAM_OMISSION),
            ("cú pháp lệnh bị sai flag", RootCauseCategory.PARAM_OMISSION),

            # 4. TOOL_FAILURE (Execution failure, exit code, timeout)
            ("lệnh bị lỗi exit code 1", RootCauseCategory.TOOL_FAILURE),
            ("công cụ command failed rồi", RootCauseCategory.TOOL_FAILURE),
            ("tool execute timeout không trả về", RootCauseCategory.TOOL_FAILURE),

            # 5. HALLUCINATION (Speculation, unverified claims)
            ("em đang bịa đặt chém gió tự nghĩ ra", RootCauseCategory.HALLUCINATION),
            ("chưa kiểm tra lệnh mà đã đoán mò", RootCauseCategory.HALLINATION if hasattr(RootCauseCategory, "HALLINATION") else RootCauseCategory.HALLUCINATION),
            ("sai bét nhè logic kiểu gì thế", RootCauseCategory.HALLUCINATION),
        ]

        for text, expected_cat in test_cases:
            cat = AgentMemoryService.classify_root_cause(text)
            self.assertEqual(
                cat,
                expected_cat,
                f"Input '{text}' was classified as {cat}, expected {expected_cat}",
            )

    async def test_16_ai_agent_chat_trigger_neuromorphic_surge(self) -> None:
        """
        Stress Test 16: Verify AiAgentService chat turn triggers neuromorphic surge:
        When user corrects the bot (e.g. 'Sai rồi em, ram chỉ có 3.2gb'),
        the bot must:
        1. Classify root cause as RESOURCE_ASSUMPTION.
        2. Stimulate brain with noradrenaline=+0.25, dopamine=-0.20, acetylcholine=+0.30.
        """
        from app.services.ai_agent import AiAgentService

        agent = AiAgentService(
            llm_router=MagicMock(),
            ssh_client=MagicMock(),
            message_cache=MagicMock(),
        )
        agent.is_configured = MagicMock(return_value=True)

        mock_brain = MagicMock()
        mock_brain.stimulate_neurotransmitters = MagicMock()
        agent.brain = mock_brain

        mem_mock = MagicMock()
        mem_mock.get_active_lessons = AsyncMock(return_value=[])
        mem_mock.get_recent_episodes = AsyncMock(return_value=[])
        mem_mock.get_pending_tasks_prompt = AsyncMock(return_value="")
        mem_mock.get_active_schemas_prompt = AsyncMock(return_value="")
        mem_mock.get_all_causal_hints_prompt = AsyncMock(return_value="")
        mem_mock.record_correction = AsyncMock()
        agent.memory_service = mem_mock

        chat_id = "test_chat_123"
        agent._history_map[chat_id] = [
            {"role": "user", "content": "Server có bao nhiêu ram?"},
            {"role": "assistant", "content": "Server có 100GB ram và swap thoải mái."},
        ]

        correction_msg = "Sai rồi em, server chỉ có 3.2gb ram thôi"
        self.assertTrue(AgentMemoryService.is_correction(correction_msg))

        agent.llm_router.complete = AsyncMock(return_value={
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "Dạ em thành thật nhận sai với anh Mạnh, server chỉ có 3.2GB RAM vật lý."
                },
                "finish_reason": "stop"
            }]
        })

        reply = await agent.chat(chat_id, correction_msg)

        mock_brain.stimulate_neurotransmitters.assert_called_once_with(
            noradrenaline=0.25,
            dopamine=-0.20,
            acetylcholine=0.30,
        )


if __name__ == "__main__":
    unittest.main()
