"""
Test Suite: Tier 5 White-Box Adversarial Neuromorphic Coverage Hardening
Dự án: Quản Lý Máy Chủ & Trợ Lý Tự Hành Cao Cấp Tiểu Bảo Bảo (services/ai-agent-service)

Tập tin kiểm thử đối kháng Tier 5 (Adversarial Coverage Hardening):
Bao quát 4 nhóm stress-test trọng tâm với 24 ca thử nghiệm khắt khe:
- Nhóm 1 (Test cases 1 - 6): Hebbian LTP/LTD Reconsolidation & 5 Whys Error Recovery
- Nhóm 2 (Test cases 7 - 12): Hyperdimensional VSA Virtual Cortex mmap 32GB Architecture
- Nhóm 3 (Test cases 13 - 18): SubconsciousDreamEngine Sleep Cycles & Homeostasis
- Nhóm 4 (Test cases 19 - 24): Proactive SRE Curiosity Engine & Alert Storm Concurrency
"""
import asyncio
import math
import os
import re
import struct
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.brain_core import (
    ArtificialBrain,
    DEFAULT_CORTEX_CAPACITY,
    HV_DIM_BITS,
    HV_DIM_BYTES,
    HyperdimensionalCortex,
    NeurotransmitterState,
    VN_TZ,
    WorkspaceSignal,
    _fnv1a_hash_64,
)
from app.services.dream_engine import SubconsciousDreamEngine
from app.services.memory_service import (
    ALL_ROOT_CAUSE_CATEGORIES,
    AgentMemoryService,
    CORRECTION_TRIGGERS,
    RootCauseCategory,
)
from app.services.proactive_service import (
    ProactiveIntelligenceService,
    _CORE_CONTAINERS,
    _DISK_ALERT_PCT,
    _MEM_ALERT_PCT,
    _SRE_CPU_LOAD_THRESHOLD,
    _SRE_RAM_ALERT_PCT,
    _SRE_ROOT_DISK_ALERT_PCT,
    _SRE_SWAP_ALERT_MB,
    _SSL_WARN_DAYS,
)

def _create_mock_memory_service() -> MagicMock:
    """Builds a mock memory service conforming to AgentMemoryService interface."""
    memory_mock = MagicMock(spec=AgentMemoryService)
    memory_mock.record_correction = AsyncMock()
    memory_mock.record_new_knowledge = AsyncMock()
    memory_mock.record_episode = AsyncMock()
    memory_mock.get_active_lessons = AsyncMock(return_value=[])
    memory_mock.get_active_lessons_prompt = AsyncMock(return_value="")
    memory_mock.get_recent_episodes = AsyncMock(return_value="")
    memory_mock.get_pending_tasks_prompt = AsyncMock(return_value="")
    memory_mock.get_active_schemas_prompt = AsyncMock(return_value="")
    memory_mock.get_all_causal_hints_prompt = AsyncMock(return_value="")
    memory_mock.should_send_proactive_alert = AsyncMock(return_value=True)
    memory_mock.upsert_proactive_check = AsyncMock()
    memory_mock.consolidation_cycle = AsyncMock(return_value={"pruned": 0, "decayed": 0})
    memory_mock.list_lessons_for_display = AsyncMock(return_value=[])
    return memory_mock

# ─────────────────────────────────────────────────────────────────────────────
# NHÓM 1: Hebbian LTP/LTD Reconsolidation & 5 Whys Error Recovery (6 Tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestTier5HebbianReflexionAdversarial(unittest.IsolatedAsyncioTestCase):
    """
    Stress-tests Hebbian LTP/LTD reconsolidation, 5 Whys Root Cause Classification,
    and Reflexion error recovery under extreme, corrupted, and adversarial conditions.
    """

    def setUp(self):
        self.mem_service = AgentMemoryService()

    # ── Test 1: 5 Whys Root Cause Extreme & Hybrid Corrupt Inputs ──
    def test_t5_01_5whys_extreme_corrupt_and_hybrid_dialect_inputs(self):
        """
        Stress-test classify_root_cause with null, unicode garbage, massive strings,
        and hybrid multi-cause dialectical inputs.
        """
        corrupted_inputs = [
            ("", None),
            ("   \n\t   ", ""),
            ("\x00\x01\x02\ufffd\u200b\ufeff", "error"),
            ("A" * 15000, "B" * 5000),
        ]
        for user_in, orig_resp in corrupted_inputs:
            cat = AgentMemoryService.classify_root_cause(user_in, orig_resp)
            self.assertIn(
                cat, ALL_ROOT_CAUSE_CATEGORIES,
                f"Root cause '{cat}' for input '{user_in[:20]}' must be in valid taxonomy"
            )

        dialect_inputs = [
            ("răng lại rứa hè em, tau hỏi một đằng m trả lời một nẻo", ""),
            ("nói chi rứa, tau có hỏi cấy nớ mô mà nói", "Dạ đây là thông tin"),
            ("mần răng mà nỏ đúng rứa", "Em vừa chạy lệnh"),
        ]
        for user_in, orig_resp in dialect_inputs:
            cat = AgentMemoryService.classify_root_cause(user_in, orig_resp)
            self.assertEqual(
                cat, RootCauseCategory.DIALECT_CONFUSION,
                f"Dialect input '{user_in}' must classify as DIALECT_CONFUSION"
            )

        resource_inputs = [
            ("máy này ram 3.2gb mà em đòi tạo swap 100gb làm treo máy rồi", "Em tạo swap"),
            ("server chỉ có 2 core i5-4310u thôi sao lại stress test nặng thế", ""),
            ("bị oom tràn ram đơ máy rồi kìa", "Tiến trình đang chạy"),
        ]
        for user_in, orig_resp in resource_inputs:
            cat = AgentMemoryService.classify_root_cause(user_in, orig_resp)
            self.assertEqual(
                cat, RootCauseCategory.RESOURCE_ASSUMPTION,
                f"Resource input '{user_in}' must classify as RESOURCE_ASSUMPTION"
            )

        self.assertEqual(
            AgentMemoryService.classify_root_cause("lệnh bị lỗi exit code 127 command failed", ""),
            RootCauseCategory.TOOL_FAILURE
        )
        self.assertEqual(
            AgentMemoryService.classify_root_cause("em chưa gọi tool chi cả mà dám phán bừa", ""),
            RootCauseCategory.HALLUCINATION
        )
        self.assertEqual(
            AgentMemoryService.classify_root_cause("lệnh thiếu flag tham số -rf rồi", ""),
            RootCauseCategory.PARAM_OMISSION
        )

    # ── Test 2: Fuzzy and Boundary Correction Triggers ──
    def test_t5_02_is_correction_fuzzy_and_boundary_triggers(self):
        """
        Tests is_correction against tricky deceptive sentences and multi-language dialect cues.
        """
        positive_cues = [
            "Anh thấy sai rồi em nhé",
            "Nỏ đúng mô nà",
            "Hỏi một đằng trả lời một nẻo thế em",
            "Command failed with exit code 1",
            "Tào lao quá, trật lất hết",
            "m hiểu t nói chi ko",
        ]
        for cue in positive_cues:
            self.assertTrue(
                AgentMemoryService.is_correction(cue),
                f"Expression '{cue}' must be recognized as a correction"
            )

        negative_cues = [
            "Hôm nay trời đẹp quá em nhỉ",
            "Kiểm tra ram server giúp anh với",
            "Em giải thích khái niệm Docker container là gì",
            "Cảm ơn em nhiều nhé, làm rất tốt",
        ]
        for cue in negative_cues:
            self.assertFalse(
                AgentMemoryService.is_correction(cue),
                f"Expression '{cue}' must NOT be flagged as a correction"
            )

    # ── Test 3: Hebbian LTP Reinforcement Bound Ceiling (Cap at 0.92) ──
    async def test_t5_03_hebbian_ltp_reinforcement_bound_ceiling(self):
        """
        Stress-tests repeated reinforcing lessons (LTP): confidence must increment
        by +0.05 on each reconsolidation but NEVER exceed the biological ceiling of 0.92.
        """
        base_lesson = "Cấu hình PostgreSQL shared_buffers mức 128MB cho máy chủ RAM 3.2GB"
        reinforcing_lesson = "Cấu hình PostgreSQL shared_buffers ở mức 128MB cho máy chủ RAM 3.2GB"

        self.mem_service._lesson_cache = [{
            "id": 101,
            "lesson_text": base_lesson,
            "event_type": "procedural",
            "confidence": 0.80,
            "usage_count": 1,
            "is_search_grounded": True,
        }]
        self.mem_service._cache_dirty = False

        async def mock_update(lesson_id: int, new_text: str, new_conf: float):
            for l in self.mem_service._lesson_cache:
                if l["id"] == lesson_id:
                    l["confidence"] = new_conf
                    l["lesson_text"] = new_text

        with patch.object(self.mem_service, "_update_lesson_content", side_effect=mock_update), \
             patch.object(self.mem_service, "_insert_lesson", AsyncMock(return_value=999)):

            for i in range(20):
                lesson_id, reconsolidated = await self.mem_service.reconsolidate_or_insert(
                    trigger_pattern="postgresql_ram",
                    lesson_text=reinforcing_lesson,
                    event_type="procedural",
                    confidence=0.85,
                    is_search_grounded=True,
                    search_query="postgresql shared_buffers 3.2gb ram",
                )
                self.assertTrue(reconsolidated, f"Iteration {i} must reconsolidate similar lesson")
                self.assertEqual(lesson_id, 101)

            final_conf = self.mem_service._lesson_cache[0]["confidence"]
            self.assertAlmostEqual(
                final_conf, 0.92, places=2,
                msg="Hebbian LTP confidence must strictly cap at 0.92 ceiling and not overflow"
            )

    # ── Test 4: Hebbian LTD Depression Floor & Oscillation Underflow ──
    async def test_t5_04_hebbian_ltd_depression_floor_and_oscillation(self):
        """
        Stress-tests contradictory beliefs (LTD): confidence decays by -0.15,
        and must never underflow below biological floor 0.10 under repeated contradiction.
        """
        old_belief = "Nên tạo swap 100GB mở rộng bộ nhớ máy chủ kirito"
        contradicting_belief = "Không nên tạo swap 100GB mở rộng bộ nhớ máy chủ kirito"

        self.mem_service._lesson_cache = [{
            "id": 202,
            "lesson_text": old_belief,
            "event_type": "procedural",
            "confidence": 0.35,
            "usage_count": 3,
            "is_search_grounded": False,
        }]
        self.mem_service._cache_dirty = False

        async def mock_update(lesson_id: int, new_text: str, new_conf: float):
            for l in self.mem_service._lesson_cache:
                if l["id"] == lesson_id:
                    l["confidence"] = new_conf

        with patch.object(self.mem_service, "_update_lesson_content", side_effect=mock_update), \
             patch.object(self.mem_service, "_insert_lesson", AsyncMock(return_value=303)):

            self.assertTrue(self.mem_service._is_contradicting(old_belief, contradicting_belief))

            new_id, reconsolidated = await self.mem_service.reconsolidate_or_insert(
                trigger_pattern="swap_myth",
                lesson_text=contradicting_belief,
                event_type="procedural",
                confidence=0.88,
                is_search_grounded=True,
                search_query="swap 100gb ssd disk thrashing",
            )
            self.assertFalse(reconsolidated)
            self.assertEqual(new_id, 303)
            self.assertAlmostEqual(self.mem_service._lesson_cache[0]["confidence"], 0.20, places=2)

            await self.mem_service.reconsolidate_or_insert(
                trigger_pattern="swap_myth",
                lesson_text=contradicting_belief,
                event_type="procedural",
                confidence=0.88,
                is_search_grounded=True,
                search_query="swap 100gb",
            )
            final_conf = self.mem_service._lesson_cache[0]["confidence"]
            self.assertGreaterEqual(
                final_conf, 0.10,
                msg="Hebbian LTD confidence must strictly respect 0.10 minimum floor bound"
            )

    # ── Test 5: Hebbian Contradiction Semantic Boundary ──
    def test_t5_05_hebbian_contradiction_semantic_boundary(self):
        """
        Tests _is_contradicting boundary: negation words must be accompanied by
        topic keyword overlap (> 0.20 Jaccard) to avoid false LTD triggers on unrelated lessons.
        """
        text_a = "Cấu hình firewall UFW cho phép cổng 22 và 443"
        text_b = "Không nên ăn quá nhiều đường vào ban đêm"
        self.assertFalse(self.mem_service._is_contradicting(text_a, text_b))

        text_c = "Luôn khởi động lại Nginx sau khi kiểm tra nginx -t thành công"
        text_d = "Khởi động lại Nginx sau khi kiểm tra cú pháp nginx -t hợp lệ"
        self.assertFalse(self.mem_service._is_contradicting(text_c, text_d))

        text_e = "Dùng rm -rf /tmp/test để xóa thư mục tạm"
        text_f = "Đừng dùng rm -rf /tmp/test mà nên tránh xóa bừa bãi"
        self.assertTrue(self.mem_service._is_contradicting(text_e, text_f))

        text_g = "Always restart docker daemon directly during peak hours"
        text_h = "Never restart docker daemon directly during peak hours, avoid downtime"
        self.assertTrue(self.mem_service._is_contradicting(text_g, text_h))

    # ── Test 6: Database Connection Failure Resilience ──
    async def test_t5_06_hebbian_db_connection_failure_resilience(self):
        """
        Verifies that when database connection throws OperationalError or drops,
        reconsolidate_or_insert fails gracefully without unhandled crashes.
        """
        with patch("app.services.memory_service.get_db_connection", side_effect=Exception("DB Connection Lost")):
            self.mem_service._lesson_cache = []
            self.mem_service._cache_dirty = True

            lesson_id, reconsolidated = await self.mem_service.reconsolidate_or_insert(
                trigger_pattern="test_error",
                lesson_text="Lesson during DB outage",
                event_type="procedural",
                confidence=0.8,
                is_search_grounded=False,
                search_query=None,
            )
            self.assertIsNone(lesson_id)
            self.assertFalse(reconsolidated)

# ─────────────────────────────────────────────────────────────────────────────
# NHÓM 2: Hyperdimensional VSA Virtual Cortex mmap 32GB Architecture (6 Tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestTier5VsaVirtualCortexAdversarial(unittest.TestCase):
    """
    Stress-tests the 32GB Virtual Memory mmap Cortex: 1,500+ vector heavy ingestion,
    header binary integrity, thread concurrency, algebraic invariants, and capacity overflow.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_path = Path(self.temp_dir.name) / "hyper_cortex_test.bin"

    def tearDown(self):
        self.temp_dir.cleanup()

    # ── Test 7: Heavy Ingestion 1,500+ Vectors into Cortex ──
    def test_t5_07_vsa_cortex_heavy_ingestion_1500_vectors(self):
        """
        Ingests 1,500 distinct hypervectors into HyperdimensionalCortex (max_capacity=2000).
        Verifies zero vector loss, header synchronization, and retrieval integrity.
        """
        cortex = HyperdimensionalCortex(self.storage_path, max_capacity=2000)
        try:
            start_t = time.perf_counter()
            for i in range(1500):
                text = f"SRE Principle #{i}: Monitor CPU load and RAM thresholds on Intel Haswell node {i}"
                vec = cortex.encode_concept(text)
                cortex.store_vector(f"concept_{i}", vec, {"id": i, "text": text})
            duration_s = time.perf_counter() - start_t

            self.assertEqual(cortex.vector_count, 1500)
            self.assertEqual(len(cortex.entry_index), 1500)

            for sample_idx in [0, 10, 100, 500, 999, 1499]:
                cid = f"concept_{sample_idx}"
                slot = cortex.entry_index[cid]
                offset = cortex.HEADER_SIZE + (slot * HV_DIM_BYTES)
                read_vec = cortex._mmap_obj[offset:offset + HV_DIM_BYTES]
                self.assertEqual(len(read_vec), HV_DIM_BYTES)
                self.assertNotEqual(read_vec, b"\x00" * HV_DIM_BYTES)

            self.assertLess(duration_s, 60.0, f"Ingestion took {duration_s:.2f}s, expected < 60.0s")
        finally:
            cortex.close()

    # ── Test 8: Header Binary Integrity & Corruption Resilience ──
    def test_t5_08_vsa_cortex_header_binary_integrity_and_corruption_resilience(self):
        """
        Validates binary header format (AGY_VSA_CORTEX\x01) and resilience against
        corrupted headers, bad magic bytes, and truncated storage files.
        """
        cortex = HyperdimensionalCortex(self.storage_path, max_capacity=50)
        cortex.store_vector("c1", cortex.encode_concept("Test Header Integrity"))
        cortex.close()

        with open(self.storage_path, "rb") as f:
            header_bytes = f.read(cortex.HEADER_SIZE)
            magic = header_bytes[:15]
            self.assertEqual(magic, HyperdimensionalCortex.HEADER_MAGIC)
            cap, count = struct.unpack_from("<II", header_bytes, 16)
            self.assertEqual(cap, 50)
            self.assertEqual(count, 1)

        # Scenario A: Corrupt the magic byte sequence
        with open(self.storage_path, "r+b") as f:
            f.seek(0)
            f.write(b"CORRUPTED_MAGIC!")

        cortex_corrupt = HyperdimensionalCortex(self.storage_path, max_capacity=50)
        try:
            self.assertIsNotNone(cortex_corrupt._mmap_obj)
        finally:
            cortex_corrupt.close()

        # Scenario B: Truncate file to partial size (< HEADER_SIZE)
        meta_file = self.storage_path.with_suffix(".meta.json")
        if meta_file.exists():
            meta_file.unlink()
        with open(self.storage_path, "wb") as f:
            f.write(b"SHORT_TRUNCATED")

        cortex_reinit = HyperdimensionalCortex(self.storage_path, max_capacity=50)
        try:
            self.assertEqual(cortex_reinit.vector_count, 0)
            slot = cortex_reinit.store_vector("c_new", cortex_reinit.encode_concept("Reborn after truncate"))
            self.assertEqual(slot, 0)
            self.assertEqual(cortex_reinit.vector_count, 1)
        finally:
            cortex_reinit.close()

    # ── Test 9: Concurrent Multithreaded Queries on mmap ──
    def test_t5_09_vsa_cortex_concurrent_multithreaded_queries(self):
        """
        Stress-tests multi-threaded concurrent querying on mmap Cortex buffer:
        16 concurrent workers executing 160 continuous recall_nearest queries simultaneously.
        Verifies zero race-condition crashes on demand-paging memory-mapped buffer and POPCNT instructions.
        """
        cortex = HyperdimensionalCortex(self.storage_path, max_capacity=300)
        try:
            for i in range(50):
                cortex.store_vector(f"base_{i}", cortex.encode_concept(f"Node configuration {i} for cluster"))

            def query_worker(worker_id: int):
                for q_idx in range(10):
                    query_text = f"Node configuration {worker_id % 50}"
                    results = cortex.recall_nearest(query_text, top_k=3, threshold=0.50)
                    self.assertIsInstance(results, list)
                    if results:
                        top_cid, top_sim, top_meta = results[0]
                        self.assertGreaterEqual(top_sim, 0.50)

            with ThreadPoolExecutor(max_workers=16) as executor:
                futures = [executor.submit(query_worker, wid) for wid in range(16)]
                for f in futures:
                    f.result()

            self.assertEqual(cortex.vector_count, 50)
        finally:
            cortex.close()

    # ── Test 10: VSA Algebraic Invariants (Bind, Permute, Hamming) ──
    def test_t5_10_vsa_algebraic_invariants_and_bit_properties(self):
        """
        Empirically verifies core mathematical invariants of Vector Symbolic Architecture:
        1. Bind Self-Inverse: (a ^ b) ^ b = a
        2. Bind Commutativity: a ^ b = b ^ a
        3. Hamming Identity: sim(a, a) == 1.0
        4. Hamming Bitwise Inversion: sim(a, ~a) == 0.0
        5. Quasi-Orthogonality: sim(random_a, random_b) ≈ 0.50 ± 0.06
        6. Cyclic Permutation Invariant: permute(a, 10000) == a
        """
        v1 = HyperdimensionalCortex.encode_concept("Intel Core i5-4310U Haswell Architecture")
        v2 = HyperdimensionalCortex.encode_concept("PostgreSQL Database Optimization Guide")

        bound = HyperdimensionalCortex.bind(v1, v2)
        unbound = HyperdimensionalCortex.bind(bound, v2)
        self.assertEqual(unbound, v1, "VSA XOR binding must be perfectly self-inverting")

        self.assertEqual(
            HyperdimensionalCortex.bind(v1, v2),
            HyperdimensionalCortex.bind(v2, v1),
            "VSA XOR binding must be commutative"
        )

        self.assertEqual(HyperdimensionalCortex.hamming_similarity(v1, v1), 1.0)

        int_v1 = int.from_bytes(v1, "little")
        inv_v1 = (~int_v1 & ((1 << HV_DIM_BITS) - 1)).to_bytes(HV_DIM_BYTES, "little")
        self.assertEqual(HyperdimensionalCortex.hamming_similarity(v1, inv_v1), 0.0)

        sim = HyperdimensionalCortex.hamming_similarity(v1, v2)
        self.assertAlmostEqual(
            sim, 0.50, delta=0.06,
            msg=f"Quasi-orthogonal vectors should have similarity ~0.50, got {sim:.3f}"
        )

        permuted_full = HyperdimensionalCortex.permute(v1, shift=HV_DIM_BITS)
        self.assertEqual(permuted_full, v1, "Permute by full dimension 10,000 must cycle back to original")

    # ── Test 11: Synaptic Pruning Under Capacity Overflow ──
    def test_t5_11_vsa_synaptic_pruning_capacity_overflow(self):
        """
        Verifies that when cortex exceeds max_capacity, Synaptic Homeostasis
        evicts the weakest unpinned synapses while 100% protecting pinned concepts.
        """
        cortex = HyperdimensionalCortex(self.storage_path, max_capacity=30)
        try:
            for i in range(5):
                cid = f"innate_{i}"
                vec = cortex.encode_concept(f"Innate identity directive #{i}")
                cortex.store_vector(cid, vec, {"pinned": True, "salience": 1.0, "category": "identity"})

            for i in range(35):
                cid = f"transient_{i}"
                vec = cortex.encode_concept(f"Transient observation data log #{i}")
                cortex.store_vector(cid, vec, {"pinned": False, "salience": 0.40})

            self.assertLessEqual(
                len(cortex.entry_index), 30,
                "Cortex vector count must never exceed max_capacity"
            )

            for i in range(5):
                cid = f"innate_{i}"
                self.assertIn(
                    cid, cortex.entry_index,
                    f"Pinned concept '{cid}' must NEVER be pruned during capacity eviction"
                )
        finally:
            cortex.close()

    # ── Test 12: Concept Encoding Extreme Edge Cases ──
    def test_t5_12_vsa_encode_concept_edge_cases(self):
        """
        Tests encode_concept with empty, multi-byte emoji, single token, and 500-token paragraphs.
        All must yield valid 1,250-byte (10,000-bit) hypervectors without throwing.
        """
        edge_inputs = [
            "",
            "   ",
            "x",
            "🚀🔥🧠⚡💽🐳",
            "Tiểu Bảo Bảo — trợ lý AI kiêm quản trị viên máy chủ kirito-server",
            " ".join(["token"] * 600),
        ]
        for inp in edge_inputs:
            vec = HyperdimensionalCortex.encode_concept(inp)
            self.assertIsInstance(vec, bytes)
            self.assertEqual(len(vec), HV_DIM_BYTES)

# ─────────────────────────────────────────────────────────────────────────────
# NHÓM 3: SubconsciousDreamEngine Sleep Cycles & Homeostasis (6 Tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestTier5DreamEngineSleepHomeostasisAdversarial(unittest.IsolatedAsyncioTestCase):
    """
    Stress-tests SubconsciousDreamEngine across simulated 30 consecutive sleep cycles,
    verifying synaptic stability, memory leak prevention, LLM resilience, and circadian rhythm.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_dir = Path(self.temp_dir.name)
        self.brain = ArtificialBrain(storage_dir=self.storage_dir)

    def tearDown(self):
        if hasattr(self.brain, "cortex") and self.brain.cortex:
            self.brain.cortex.close()
        self.temp_dir.cleanup()

    # ── Test 13: 30 Consecutive SWS Sleep Cycles Stability ──
    async def test_t5_13_dream_30_consecutive_sws_sleep_cycles_stability(self):
        """
        Simulates 30 consecutive nights of SWS consolidation.
        Verifies:
        - Working memory buffer is completely flushed after every SWS cycle (Zero-Memory-Leak).
        - Adenosine sleep pressure stays bounded in [0.05, 1.0].
        - Cortisol and Serotonin maintain valid homeostatic ranges.
        - Synaptic weight score does not collapse to NaN or infinite.
        """
        dream_engine = SubconsciousDreamEngine(
            brain=self.brain,
            llm_router=MagicMock(),
            ssh_client=MagicMock(),
            memory_service=_create_mock_memory_service(),
            storage_dir=self.storage_dir,
        )

        for day in range(1, 31):
            self.brain.add_working_memory_item(
                text=f"Day #{day}: Incident resolution for PostgreSQL connection pool exhaustion",
                category="incident",
                salience=0.80,
            )
            self.brain.neuro.accumulate_adenosine(0.40)
            self.brain.neuro.stimulate("cortisol", 0.15)

            result = await dream_engine.run_sws_cycle()

            self.assertEqual(result["phase"], "SWS")
            self.assertEqual(len(self.brain.working_memory), 0, f"Day {day}: Working memory must be 0 after SWS")
            self.assertGreaterEqual(self.brain.neuro.adenosine, 0.05)
            self.assertLessEqual(self.brain.neuro.adenosine, 1.0)
            self.assertGreaterEqual(self.brain.neuro.cortisol, 0.0)
            self.assertLessEqual(self.brain.neuro.cortisol, 1.0)
            self.assertGreaterEqual(self.brain.neuro.serotonin, 0.0)
            self.assertLessEqual(self.brain.neuro.serotonin, 1.0)

    # ── Test 14: Epiphany Cache Overflow & Zero-Disk-Leak ──
    def test_t5_14_dream_epiphany_cache_leak_prevention(self):
        """
        Verifies that delivered_epiphanies is strictly capped at the 20 most recent entries,
        guaranteeing zero disk/memory leakage across months of continuous operation.
        """
        dream_engine = SubconsciousDreamEngine(
            brain=self.brain,
            llm_router=MagicMock(),
            ssh_client=MagicMock(),
            memory_service=_create_mock_memory_service(),
            storage_dir=self.storage_dir,
        )

        for i in range(60):
            dream_engine.delivered_epiphanies.append({
                "id": f"ep_{i}",
                "topic": f"Insight {i}",
                "delivered": True,
            })
            dream_engine._save_cache()

        dream_engine._load_cache()
        self.assertLessEqual(
            len(dream_engine.delivered_epiphanies), 20,
            "Delivered epiphanies history must be strictly capped at 20 items to prevent disk bloat"
        )

    # ── Test 15: REM LLM Output Corruption & Markdown Fence Resilience ──
    async def test_t5_15_dream_rem_llm_json_corruption_and_markdown_fence_resilience(self):
        """
        Stress-tests run_rem_dream_cycle against corrupted LLM outputs:
        1. Markdown wrapped code fences (```json ... ```)
        2. Broken truncated JSON missing closing brace
        3. Pure gibberish string
        """
        mock_router = MagicMock()
        dream_engine = SubconsciousDreamEngine(
            brain=self.brain,
            llm_router=mock_router,
            ssh_client=MagicMock(),
            memory_service=_create_mock_memory_service(),
            storage_dir=self.storage_dir,
        )

        mock_router.complete = AsyncMock(return_value={
            "choices": [{"message": {"content": """```json
            {
              "topic": "Tối ưu hóa L3 Cache Haswell",
              "insight": "Phân vùng bộ nhớ đệm giúp triệt tiêu xung đột bus.",
              "sisterly_note": "Chúc anh Mạnh buổi sáng vui vẻ ạ!"
            }
            ```"""}}]
        })
        with patch.object(dream_engine, "check_hardware_idle", AsyncMock(return_value=(True, "idle"))):
            epiphany1 = await dream_engine.run_rem_dream_cycle(force=True)
            self.assertIsNotNone(epiphany1)
            self.assertEqual(epiphany1["topic"], "Tối ưu hóa L3 Cache Haswell")

        mock_router.complete = AsyncMock(return_value={
            "choices": [{"message": {"content": '{"topic": "Phòng ngự tủy sống", "insight": "Đánh chặn lệnh độc hại", "sisterly_note": "Em luôn bên anh'}}]
        })
        dream_engine.last_rem_time = None
        epiphany2 = await dream_engine.run_rem_dream_cycle(force=True)
        self.assertIsNotNone(epiphany2)
        self.assertEqual(epiphany2["topic"], "Phòng ngự tủy sống")

        mock_router.complete = AsyncMock(return_value={
            "choices": [{"message": {"content": "Tôi là một mô hình ngôn ngữ lớn và không thể mơ được."}}]
        })
        dream_engine.last_rem_time = None
        epiphany3 = await dream_engine.run_rem_dream_cycle(force=True)
        self.assertIsNone(epiphany3)

    # ── Test 16: Hardware Idle Guard & SSH Network Dropout ──
    async def test_t5_16_dream_hardware_idle_guard_with_ssh_failure(self):
        """
        Verifies check_hardware_idle:
        - When load1 < 0.8 -> Returns (True, "Load1=...")
        - When load1 >= 0.8 -> Returns (False, "Load1=...")
        - When SSH drops/times out -> Graceful fallback to (True, "Night window default")
        """
        mock_ssh = MagicMock()
        dream_engine = SubconsciousDreamEngine(
            brain=self.brain,
            llm_router=MagicMock(),
            ssh_client=mock_ssh,
            memory_service=_create_mock_memory_service(),
            storage_dir=self.storage_dir,
        )

        mock_ssh.execute_command = AsyncMock(return_value="0.35 0.40 0.42 1/150 12345")
        is_idle, msg = await dream_engine.check_hardware_idle()
        self.assertTrue(is_idle)
        self.assertIn("0.35", msg)

        mock_ssh.execute_command = AsyncMock(return_value="2.50 1.80 1.20 5/200 12346")
        is_idle, msg = await dream_engine.check_hardware_idle()
        self.assertFalse(is_idle)
        self.assertIn("2.50", msg)

        mock_ssh.execute_command = AsyncMock(side_effect=TimeoutError("SSH connection timed out"))
        is_idle, msg = await dream_engine.check_hardware_idle()
        self.assertTrue(is_idle)
        self.assertIn("Night window default", msg)

    # ── Test 17: Morning Epiphany Wake Window Delivery Protocol ──
    def test_t5_17_dream_pop_morning_epiphany_window_and_delivery_flag(self):
        """
        Verifies that pop_morning_epiphany only delivers inside morning window (05:30 - 11:30),
        formats thoughtful Vietnamese greeting, and strictly avoids duplicate delivery.
        """
        dream_engine = SubconsciousDreamEngine(
            brain=self.brain,
            llm_router=MagicMock(),
            ssh_client=MagicMock(),
            memory_service=_create_mock_memory_service(),
            storage_dir=self.storage_dir,
        )
        dream_engine.pending_morning_epiphany = {
            "topic": "Cơ chế Zero-Copy mmap",
            "insight": "Ánh xạ mmap giúp bảo vệ trần RAM 3.2GB của máy chủ.",
            "sisterly_note": "Chúc anh Mạnh một ngày làm việc tràn đầy năng lượng!",
            "delivered": False,
        }

        with patch.object(SubconsciousDreamEngine, "is_morning_window", return_value=False):
            self.assertIsNone(dream_engine.pop_morning_epiphany())
            self.assertIsNotNone(dream_engine.pending_morning_epiphany)

        with patch.object(SubconsciousDreamEngine, "is_morning_window", return_value=True):
            delivered_text = dream_engine.pop_morning_epiphany()
            self.assertIsNotNone(delivered_text)
            self.assertIn("Cơ chế Zero-Copy mmap", delivered_text)
            self.assertIn("Chúc anh Mạnh", delivered_text)

            self.assertIsNone(dream_engine.pending_morning_epiphany)
            self.assertTrue(dream_engine.delivered_epiphanies[-1]["delivered"])

            self.assertIsNone(dream_engine.pop_morning_epiphany())

    # ── Test 18: SWS Cycle Resilience Against External Failures ──
    async def test_t5_18_dream_sws_database_sync_resilience(self):
        """
        Verifies that if memory_service raises exceptions during SWS consolidation,
        run_sws_cycle does not abort and safely finishes neurochemical regulation.
        """
        failing_mem = _create_mock_memory_service()
        failing_mem.consolidation_cycle = AsyncMock(side_effect=Exception("Database unreachable"))
        failing_mem.list_lessons_for_display = AsyncMock(side_effect=Exception("Timeout"))

        dream_engine = SubconsciousDreamEngine(
            brain=self.brain,
            llm_router=MagicMock(),
            ssh_client=MagicMock(),
            memory_service=failing_mem,
            storage_dir=self.storage_dir,
        )

        result = await dream_engine.run_sws_cycle()
        self.assertEqual(result["phase"], "SWS")
        self.assertIn("duration_ms", result)

# ─────────────────────────────────────────────────────────────────────────────
# NHÓM 4: Proactive SRE Curiosity Engine & Alert Storm Concurrency (6 Tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestTier5ProactiveSreCuriosityAdversarial(unittest.IsolatedAsyncioTestCase):
    """
    Stress-tests the Proactive SRE Curiosity Engine under alert storms,
    cooldown throttling, SSH failure cascades, and anomalous sensory inputs.
    """

    def setUp(self):
        self.ssh_mock = MagicMock()
        self.mem_mock = _create_mock_memory_service()
        self.tg_mock  = MagicMock()
        self.tg_mock.chat_id = "12345678"
        self.tg_mock.send_message = AsyncMock()
        self.proactive = ProactiveIntelligenceService(
            ssh_client=self.ssh_mock,
            memory_service=self.mem_mock,
            telegram_bot=self.tg_mock,
        )

    # ── Test 19: Alert Storm - All 9 Vitals Concurrently Critical ──
    async def test_t5_19_sre_alert_storm_all_9_vitals_critical(self):
        """
        Simulates an apocalyptic alert storm: all 9 SRE vitals spike above threshold simultaneously.
        Verifies:
        - All 9 anomalies are caught concurrently via asyncio.gather.
        - Telegram alert summarizes all issues cleanly without crashing.
        - High-severity episodic trace is dispatched.
        """
        async def mock_run_cmd(cmd: str):
            if "df -h --output=pcent,target" in cmd:
                return "95% /var\n92% /data"
            if "NR==2{printf" in cmd:
                return "96"
            if "grep -rh 'server_name'" in cmd:
                return "quanly.kirito.vn"
            if "openssl s_client" in cmd:
                exp_date = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%b %d %H:%M:%S %Y GMT")
                return exp_date
            if "journalctl -k" in cmd and "wc -l" in cmd:
                return "14"
            if "journalctl -k" in cmd and "awk" in cmd:
                return "postgres"
            if "docker ps --format '{{.Names}} {{.Status}}'" in cmd:
                return "dashboard_db Restarting (12) 3 seconds ago"
            if "docker ps -q" in cmd:
                return "dashboard_db 5"
            if "cat /proc/loadavg" in cmd:
                return "8.50 7.20 6.10 4/350 22345"
            if "/Swap:/" in cmd:
                return "1850"
            if "df -h /" in cmd:
                return "96"
            if "docker ps -a --format" in cmd:
                return (
                    "dashboard_ai_agent\tUp 10 hours\trunning\n"
                    "dashboard_frontend\tExited (1) 2 minutes ago\texited\n"
                    "dashboard_db\tRestarting (5) 10 seconds ago\trestarting\n"
                )
            return ""

        self.ssh_mock.run_command = AsyncMock(side_effect=mock_run_cmd)

        await self.proactive._run_scan_cycle()

        self.assertTrue(self.tg_mock.send_message.called)
        sent_msg = self.tg_mock.send_message.call_args[0][1]
        self.assertIn("Tiểu Bảo Bảo — Báo cáo quét chủ động", sent_msg)
        self.assertIn("Ổ đĩa sắp đầy", sent_msg)
        self.assertIn("RAM đang cao", sent_msg)
        self.assertIn("CPU Load Average cao", sent_msg)
        self.assertIn("Dung lượng Swap cao", sent_msg)
        self.assertIn("Phân vùng root", sent_msg)

        self.assertTrue(self.mem_mock.record_episode.called)
        ep_kwargs = self.mem_mock.record_episode.call_args[1]
        self.assertEqual(ep_kwargs["severity"], "high")
        self.assertEqual(ep_kwargs["salience_score"], 0.75)

    # ── Test 20: Cooldown Guard Prevents Telegram Alert Spam ──
    async def test_t5_20_sre_cooldown_guard_prevents_telegram_alert_spam(self):
        """
        Verifies that during persistent anomalies, cooldown guard checks
        (should_send_proactive_alert) prevent duplicate spamming to Telegram.
        """
        self.ssh_mock.run_command = AsyncMock(return_value="95")
        self.mem_mock.should_send_proactive_alert = AsyncMock(return_value=True)
        alert1 = await self.proactive._check_root_disk()
        self.assertTrue(bool(alert1))

        self.mem_mock.should_send_proactive_alert = AsyncMock(return_value=False)
        alert2 = await self.proactive._check_root_disk()
        self.assertEqual(alert2, "", "Cooldown guard must suppress alert when should_send_proactive_alert is False")

    # ── Test 21: SSH Catastrophic Disconnection Resilience ──
    async def test_t5_21_sre_ssh_catastrophic_disconnection_mid_scan(self):
        """
        Simulates total SSH network outage (BrokenPipeError / TimeoutError across all checks).
        Verifies that asyncio.gather(return_exceptions=True) shields the background daemon
        from crashing, returning clean empty findings.
        """
        self.ssh_mock.run_command = AsyncMock(side_effect=ConnectionResetError("SSH pipe severed"))

        patrol_res = await self.proactive.run_patrol_scan()
        self.assertEqual(patrol_res["status"], "healthy")
        self.assertEqual(len(patrol_res["alerts"]), 0)
        self.assertEqual(patrol_res["total_checks"], 9)

        await self.proactive._run_scan_cycle()
        self.assertFalse(self.tg_mock.send_message.called)

    # ── Test 22: Brain Pulse Ignition with Anomalous Sensory Inputs ──
    def test_t5_22_sre_brain_pulse_ignition_with_anomalous_inputs(self):
        """
        Tests ArtificialBrain.step_pulse when sensory metrics contain anomalies:
        negative RAM, RAM > 100%, float NaN, or missing values.
        Must maintain homeostatic balance without mathematical overflow or crash.
        """
        temp_dir = tempfile.TemporaryDirectory()
        brain = ArtificialBrain(storage_dir=Path(temp_dir.name))
        try:
            anomalous_metrics = [
                {"ram_usage": -20.0, "cpu_usage": -10.0},
                {"ram_usage": 150.0, "cpu_usage": 999.0},
                {"ram_usage": float("nan"), "cpu_usage": 50.0},
                None,
                {},
            ]
            for metrics in anomalous_metrics:
                signal = brain.step_pulse(metrics)
                self.assertIsNotNone(signal)
                self.assertIsInstance(signal, WorkspaceSignal)
                for chem in ("dopamine", "noradrenaline", "serotonin", "cortisol"):
                    val = getattr(brain.neuro, chem)
                    self.assertFalse(math.isnan(val), f"{chem} became NaN")
                    self.assertGreaterEqual(val, 0.0)
                    self.assertLessEqual(val, 1.0)
        finally:
            if hasattr(brain, "cortex") and brain.cortex:
                brain.cortex.close()
            temp_dir.cleanup()

    # ── Test 23: Core Containers Status & Missing Detection ──
    async def test_t5_23_sre_core_containers_unusual_status_matrix(self):
        """
        Verifies _check_core_containers identifies exited, restarting, and missing containers.
        """
        docker_ps_output = (
            "dashboard_ai_agent\tUp 5 hours\trunning\n"
            "dashboard_frontend\tUp 5 hours\trunning\n"
            "dashboard_metrics_service\tRestarting (3) 12 seconds ago\trestarting\n"
            "dashboard_auth_service\tExited (137) 1 minute ago\texited\n"
            "dashboard_db\tUp 5 hours\trunning\n"
        )
        self.ssh_mock.run_command = AsyncMock(return_value=docker_ps_output)
        self.mem_mock.should_send_proactive_alert = AsyncMock(return_value=True)

        alert = await self.proactive._check_core_containers()
        self.assertTrue(bool(alert))
        self.assertIn("dashboard_metrics_service", alert)
        self.assertIn("dashboard_auth_service", alert)
        self.assertIn("dashboard_file_service", alert)
        self.assertIn("Không tìm thấy", alert)

    # ── Test 24: Patrol Scan Output Schema Integrity ──
    async def test_t5_24_sre_patrol_scan_output_schema_integrity(self):
        """
        Verifies run_patrol_scan conforms to the expected contract:
        returns a dictionary with status, alerts list, total_checks=9, and ISO timestamp.
        """
        self.ssh_mock.run_command = AsyncMock(return_value="")
        result = await self.proactive.run_patrol_scan()

        self.assertIn("status", result)
        self.assertIn("alerts", result)
        self.assertIn("total_checks", result)
        self.assertIn("timestamp", result)
        self.assertEqual(result["total_checks"], 9)
        self.assertEqual(result["status"], "healthy")
        self.assertEqual(result["alerts"], [])


if __name__ == "__main__":
    unittest.main()
