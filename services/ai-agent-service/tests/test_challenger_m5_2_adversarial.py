"""
test_challenger_m5_2_adversarial.py — Milestone 5 Challenger 2 Adversarial Stress Suite.

Empirical Adversarial Stress Testing:
1. Resident Set Size (RSS RAM) benchmark: zero-copy demand paging across 500+ vectors (delta <= 10MB).
2. POPCNT similarity search O(1) hardware instruction latency & semantic accuracy.
3. Concept removal (remove_concept) and mmap slot reuse/restoration.
4. Synaptic pruning under capacity pressure protecting pinned concepts.
5. Batch sync_lessons with stale/low-confidence pruning.
6. Proactive SRE Curiosity scenarios:
   - RAM 86% trigger vs RAM 75% non-trigger.
   - CPU Load 3.8 trigger vs normal non-trigger.
   - Swap 600MB trigger vs normal non-trigger.
   - Core container crash trigger vs all-running healthy.
   - Missing container detection.
   - Root disk (/) 92% trigger.
   - Anti-spam Cooldown Guard across 5 consecutive incidents.
   - Aggregated on-demand patrol scan.

Target Modules:
- services/ai-agent-service/app/core/brain_core.py
- services/ai-agent-service/app/services/proactive_service.py
"""
import asyncio
import gc
import json
import os
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

import psutil

# Ensure app is in Python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.brain_core import (
    ArtificialBrain,
    HyperdimensionalCortex,
    NeurotransmitterState,
    HV_DIM_BITS,
    HV_DIM_BYTES,
    DEFAULT_CORTEX_CAPACITY,
    VN_TZ,
)
from app.services.proactive_service import (
    ProactiveIntelligenceService,
    _DISK_ALERT_PCT,
    _MEM_ALERT_PCT,
    _SRE_RAM_ALERT_PCT,
    _SRE_CPU_LOAD_THRESHOLD,
    _SRE_SWAP_ALERT_MB,
    _SRE_ROOT_DISK_ALERT_PCT,
    _CORE_CONTAINERS,
)


class TestChallengerM52AdversarialSuite(unittest.IsolatedAsyncioTestCase):
    """
    Adversarial Empirical Stress Test Suite for Gate Milestone 5.
    17 exhaustive test cases validating memory efficiency, hardware POPCNT,
    mmap zero-copy lifecycle, and proactive SRE curiosity alerting.
    """

    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_challenger_m5_2_"))
        self.cortex_bin_path = self.temp_dir / "hyper_cortex_test.bin"
        self.cortex = HyperdimensionalCortex(storage_path=self.cortex_bin_path, max_capacity=2000)

    def tearDown(self) -> None:
        if self.cortex:
            self.cortex.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ─────────────────────────────────────────────────────────────────────────
    # PHẦN 1: VSA CORTEX MMAP, RSS RAM ZERO-COPY & HARDWARE POPCNT
    # ─────────────────────────────────────────────────────────────────────────

    def test_01_mmap_sparse_binary_structure_and_header_integrity(self) -> None:
        """Kiểm tra cấu trúc file nhị phân mmap sparse file và tính toàn vẹn của header."""
        self.assertTrue(self.cortex_bin_path.exists())
        file_size = self.cortex_bin_path.stat().st_size
        expected_size = HyperdimensionalCortex.HEADER_SIZE + (2000 * HV_DIM_BYTES)
        self.assertEqual(file_size, expected_size)

        # Đọc trực tiếp từ file nhị phân đĩa để đối chiếu với mmap
        with open(self.cortex_bin_path, "rb") as f:
            header_bytes = f.read(HyperdimensionalCortex.HEADER_SIZE)
            magic = header_bytes[:15]
            self.assertEqual(magic, HyperdimensionalCortex.HEADER_MAGIC)
            cap, count = struct.unpack_from("<II", header_bytes, 16)
            self.assertEqual(cap, 2000)
            self.assertEqual(count, 0)

    def test_02_rss_ram_zero_copy_demand_paging_500_plus_vectors(self) -> None:
        """
        [TRỌNG TÂM] Đo mức tăng Resident Set Size (RSS RAM) khi nạp và query 500+ vector trong
        HyperdimensionalCortex mmap: bảo đảm delta RAM <= 10MB (zero-copy demand paging).
        """
        gc.collect()
        process = psutil.Process(os.getpid())
        initial_rss = process.memory_info().rss

        # Nạp 550 vector nhị phân 10.000-bit độc lập vào mmap
        total_vectors = 550
        for i in range(total_vectors):
            concept_text = f"Hạ tầng máy chủ server node {i} phân vùng NVMe swap 32GB cluster worker {i * 13}"
            vec = HyperdimensionalCortex.encode_concept(concept_text)
            self.cortex.store_vector(
                f"concept_stress_{i}",
                vec,
                {"index": i, "text": concept_text, "category": "adversarial_stress"}
            )

        self.assertEqual(self.cortex.vector_count, total_vectors)

        # Thực thi 60 lượt truy vấn associative recall trên toàn bộ 550 vector mmap
        for q_idx in range(60):
            query = f"máy chủ server node {q_idx * 7} swap 32GB"
            results = self.cortex.recall_nearest(query, top_k=5, threshold=0.50)
            self.assertIsInstance(results, list)

        gc.collect()
        final_rss = process.memory_info().rss
        delta_bytes = max(0, final_rss - initial_rss)
        delta_mb = delta_bytes / (1024 * 1024)

        # Bảo đảm delta RAM <= 10.0 MB theo đúng chuẩn demand paging của OS
        self.assertLessEqual(
            delta_mb,
            10.0,
            f"Mức tăng RSS RAM ({delta_mb:.2f} MB) vượt quá trần cho phép 10MB!"
        )

    def test_03_popcnt_similarity_search_o1_hardware_instruction_latency(self) -> None:
        """
        [TRỌNG TÂM] Thử nghiệm O(1) similarity search bằng POPCNT với vector ngẫu nhiên,
        kiểm tra tính đúng đắn toán học và độ trễ dưới 0.05ms/phép tính.
        """
        v1 = HyperdimensionalCortex.encode_concept("Hệ điều hành Ubuntu LTS Linux Kernel 6.8")
        v2 = HyperdimensionalCortex.encode_concept("Hệ điều hành Ubuntu LTS Linux Kernel 6.8")
        v_diff = HyperdimensionalCortex.encode_concept("Công thức nấu phở bò gia truyền Nam Định")

        # Hai vector đồng nhất -> similarity = 1.0
        self.assertAlmostEqual(HyperdimensionalCortex.hamming_similarity(v1, v2), 1.0, places=4)

        # Hai vector bitwise đối nghịch hoàn toàn -> similarity = 0.0
        v_inv = bytes(b ^ 0xFF for b in v1)
        self.assertAlmostEqual(HyperdimensionalCortex.hamming_similarity(v1, v_inv), 0.0, places=4)

        # Hai vector không liên quan -> similarity chuẩn trực giao ~0.50 (+/- 0.08)
        sim_diff = HyperdimensionalCortex.hamming_similarity(v1, v_diff)
        self.assertGreater(sim_diff, 0.42)
        self.assertLess(sim_diff, 0.58)

        # Stress test 5,000 phép tính POPCNT đo độ trễ O(1)
        start_time = time.perf_counter()
        for _ in range(5000):
            _ = HyperdimensionalCortex.hamming_similarity(v1, v_diff)
        elapsed_sec = time.perf_counter() - start_time

        avg_latency_ms = (elapsed_sec / 5000) * 1000
        # POPCNT int.bit_count() chạy cấp độ CPU cycle, độ trễ trung bình phải < 0.05ms
        self.assertLess(
            avg_latency_ms,
            0.05,
            f"Độ trễ POPCNT ({avg_latency_ms:.4f} ms) quá chậm so với chuẩn O(1) hardware!"
        )

    def test_04_remove_concept_and_mmap_slot_restoration(self) -> None:
        """
        [TRỌNG TÂM] Thử nghiệm gỡ bỏ vector (remove_concept), xóa sạch slot mmap
        và khôi phục tái sử dụng slot trống cho concept mới.
        """
        vec_a = HyperdimensionalCortex.encode_concept("Khái niệm A")
        vec_b = HyperdimensionalCortex.encode_concept("Khái niệm B")
        vec_c = HyperdimensionalCortex.encode_concept("Khái niệm C")

        slot_0 = self.cortex.store_vector("concept_A", vec_a)
        slot_1 = self.cortex.store_vector("concept_B", vec_b)
        slot_2 = self.cortex.store_vector("concept_C", vec_c)

        self.assertEqual(slot_0, 0)
        self.assertEqual(slot_1, 1)
        self.assertEqual(slot_2, 2)
        self.assertEqual(self.cortex.vector_count, 3)

        # Gỡ bỏ concept_B (nằm ở slot 1)
        remove_res = self.cortex.remove_concept("concept_B")
        self.assertTrue(remove_res)
        self.assertEqual(self.cortex.vector_count, 2)
        self.assertNotIn("concept_B", self.cortex.entry_index)
        self.assertNotIn("concept_B", self.cortex.metadata_index)

        # Kiểm tra mmap byte offset của slot 1 đã được zeroed out sạch sẽ
        offset_1 = HyperdimensionalCortex.HEADER_SIZE + (1 * HV_DIM_BYTES)
        raw_slot_bytes = self.cortex._mmap_obj[offset_1:offset_1 + HV_DIM_BYTES]
        self.assertEqual(raw_slot_bytes, b"\x00" * HV_DIM_BYTES)

        # Thêm một concept mới D -> Hệ thống phải tái sử dụng (reuse) slot 1 đã giải phóng
        vec_d = HyperdimensionalCortex.encode_concept("Khái niệm D thay thế")
        slot_d = self.cortex.store_vector("concept_D", vec_d)
        self.assertEqual(slot_d, 1, f"Kỳ vọng tái sử dụng slot 1 đã gỡ bỏ, nhưng lại dùng slot {slot_d}!")
        self.assertEqual(self.cortex.vector_count, 3)

    def test_05_remove_nonexistent_concept_idempotency(self) -> None:
        """Kiểm tra tính an toàn khi gọi remove_concept với ID không tồn tại hoặc đã xóa."""
        self.assertFalse(self.cortex.remove_concept("non_existent_key"))

        vec = HyperdimensionalCortex.encode_concept("Dữ liệu tạm")
        self.cortex.store_vector("temp_key", vec)
        self.assertTrue(self.cortex.remove_concept("temp_key"))
        # Gọi lại lần 2 phải trả về False an toàn, không ném ngoại lệ
        self.assertFalse(self.cortex.remove_concept("temp_key"))

    def test_06_cortex_synaptic_pruning_under_capacity_preserves_pinned(self) -> None:
        """Kiểm tra cơ chế Synaptic Pruning khi đầy bộ nhớ: gỡ bỏ synapse yếu, bảo vệ pinned."""
        tiny_cortex_path = self.temp_dir / "tiny_cortex.bin"
        tiny_cortex = HyperdimensionalCortex(storage_path=tiny_cortex_path, max_capacity=3)

        try:
            v1 = HyperdimensionalCortex.encode_concept("Ký ức cốt lõi - Innate Core")
            v2 = HyperdimensionalCortex.encode_concept("Tri thức bình thường")
            v3 = HyperdimensionalCortex.encode_concept("Ký ức phù du yếu ớt")

            # c1 là pinned (không bao giờ được prune)
            tiny_cortex.store_vector("c1_core", v1, {"pinned": True, "salience": 0.95})
            # c2 là unpinned salience 0.8
            tiny_cortex.store_vector("c2_normal", v2, {"pinned": False, "salience": 0.80})
            # c3 là unpinned salience thấp 0.15
            tiny_cortex.store_vector("c3_weak", v3, {"pinned": False, "salience": 0.15})

            self.assertEqual(tiny_cortex.vector_count, 3)

            # Nạp concept thứ 4 khi đã đầy 3 slots -> buộc phải kích hoạt prune_weakest_synapses
            v4 = HyperdimensionalCortex.encode_concept("Khái niệm mới cần nạp")
            slot_4 = tiny_cortex.store_vector("c4_new", v4, {"pinned": False, "salience": 0.70})

            self.assertIn(slot_4, [0, 1, 2])
            # c1_core (pinned) và c2_normal (salience 0.8) phải còn
            self.assertIn("c1_core", tiny_cortex.entry_index)
            # c3_weak phải bị trục xuất
            self.assertNotIn("c3_weak", tiny_cortex.entry_index)
            self.assertIn("c4_new", tiny_cortex.entry_index)

            stats = tiny_cortex.get_cortex_stats()
            self.assertGreaterEqual(stats["pruned_synapses"], 1)
        finally:
            tiny_cortex.close()

    def test_07_sync_lessons_batch_with_stale_and_inactive_pruning(self) -> None:
        """Kiểm tra sync_lessons: nạp bài học hợp lệ, cắt tỉa bài học inactive và stale."""
        now = time.time()
        old_iso = (datetime.now(VN_TZ) - timedelta(days=12)).isoformat()
        recent_iso = (datetime.now(VN_TZ) - timedelta(hours=2)).isoformat()

        lessons_batch = [
            # 1. Hợp lệ, tự tin cao -> sync
            {
                "id": 201,
                "trigger_pattern": "oom_killer",
                "lesson_text": "Cấu hình swap 4GB để bảo vệ container metrics khi RAM vượt 90%",
                "event_type": "sre_rule",
                "confidence": 0.92,
                "is_active": True,
                "last_used_at": recent_iso,
            },
            # 2. Bị disable (is_active = False) -> không sync / bị prune
            {
                "id": 202,
                "trigger_pattern": "old_deprecated_rule",
                "lesson_text": "Quy tắc cũ không còn áp dụng",
                "event_type": "deprecated",
                "confidence": 0.85,
                "is_active": False,
                "last_used_at": recent_iso,
            },
            # 3. Tự tin rất thấp (<0.25) và cũ > 7 ngày -> bị prune
            {
                "id": 203,
                "trigger_pattern": "weak_hypothesis",
                "lesson_text": "Giả thuyết không chắc chắn",
                "event_type": "experiment",
                "confidence": 0.18,
                "is_active": True,
                "last_used_at": old_iso,
            },
            # 4. Tự tin thấp (<0.25) nhưng mới dùng hôm nay -> vẫn giữ
            {
                "id": 204,
                "trigger_pattern": "recent_hypothesis",
                "lesson_text": "Giả thuyết vừa kiểm tra sáng nay",
                "event_type": "experiment",
                "confidence": 0.20,
                "is_active": True,
                "last_used_at": recent_iso,
            },
        ]

        # Nạp trước lesson 203 vào cortex để kiểm tra xem sync_lessons có prune nó không
        pre_vec = HyperdimensionalCortex.encode_concept("Giả thuyết không chắc chắn")
        self.cortex.store_vector("lesson_203", pre_vec)
        self.assertIn("lesson_203", self.cortex.entry_index)

        res = self.cortex.sync_lessons(lessons_batch)
        self.assertEqual(res["synced"], 2)  # lesson 201 và 204
        self.assertEqual(res["pruned"], 1)  # lesson 203 bị xóa khỏi cortex
        self.assertNotIn("lesson_203", self.cortex.entry_index)
        self.assertIn("lesson_201", self.cortex.entry_index)
        self.assertIn("lesson_204", self.cortex.entry_index)

    # ─────────────────────────────────────────────────────────────────────────
    # PHẦN 2: PROACTIVE SRE CURIOSITY SCENARIOS & COOLDOWN GUARD
    # ─────────────────────────────────────────────────────────────────────────

    async def test_08_proactive_sre_ram_86_pct_trigger(self) -> None:
        """[TRỌNG TÂM] Mô phỏng RAM 86% -> BẮT BUỘC KÍCH HOẠT CẢNH BÁO SRE."""
        mem_mock = MagicMock()
        mem_mock.should_send_proactive_alert = AsyncMock(return_value=True)
        mem_mock.upsert_proactive_check = AsyncMock()

        proactive = ProactiveIntelligenceService(
            ssh_client=MagicMock(),
            memory_service=mem_mock,
            telegram_bot=MagicMock(),
        )

        # SSH trả về 86%
        proactive._ssh.run_command = AsyncMock(return_value="86")
        alert = await proactive._check_memory(threshold_pct=_SRE_RAM_ALERT_PCT)

        self.assertTrue(bool(alert), "RAM 86% phải kích hoạt cảnh báo nhưng lại trả về rỗng!")
        self.assertIn("RAM đang cao", alert)
        self.assertIn("86%", alert)
        self.assertIn("85%", alert)  # Ngưỡng cảnh báo 85%
        mem_mock.upsert_proactive_check.assert_awaited_once()

    async def test_09_proactive_sre_ram_75_pct_non_trigger(self) -> None:
        """[TRỌNG TÂM] Mô phỏng RAM 75% -> TUYỆT ĐỐI KHÔNG KÍCH HOẠT CẢNH BÁO (IM LẶNG)."""
        mem_mock = MagicMock()
        mem_mock.should_send_proactive_alert = AsyncMock(return_value=True)
        mem_mock.upsert_proactive_check = AsyncMock()

        proactive = ProactiveIntelligenceService(
            ssh_client=MagicMock(),
            memory_service=mem_mock,
            telegram_bot=MagicMock(),
        )

        # SSH trả về 75% (dưới ngưỡng 85%)
        proactive._ssh.run_command = AsyncMock(return_value="75")
        alert = await proactive._check_memory(threshold_pct=_SRE_RAM_ALERT_PCT)

        self.assertEqual(alert, "", "RAM 75% trong ngưỡng an toàn, không được phép phát cảnh báo!")
        mem_mock.upsert_proactive_check.assert_not_awaited()

    async def test_10_proactive_sre_cpu_load_3_8_trigger(self) -> None:
        """[TRỌNG TÂM] Mô phỏng CPU Load 3.8 -> BẮT BUỘC KÍCH HOẠT CẢNH BÁO."""
        mem_mock = MagicMock()
        mem_mock.should_send_proactive_alert = AsyncMock(return_value=True)
        mem_mock.upsert_proactive_check = AsyncMock()

        proactive = ProactiveIntelligenceService(
            ssh_client=MagicMock(),
            memory_service=mem_mock,
            telegram_bot=MagicMock(),
        )

        # CPU Load = 3.80 (vượt trần 3.5 của 2 nhân 4 luồng i5-4310U)
        proactive._ssh.run_command = AsyncMock(return_value="3.80 2.95 2.10 3/140 12345")
        alert = await proactive._check_cpu_load(threshold=_SRE_CPU_LOAD_THRESHOLD)

        self.assertTrue(bool(alert), "CPU Load 3.8 phải kích hoạt cảnh báo!")
        self.assertIn("CPU Load Average cao", alert)
        self.assertIn("3.80", alert)
        self.assertIn("Intel Core i5-4310U", alert)

        # Kiểm tra tải bình thường 2.40 -> Không cảnh báo
        proactive._ssh.run_command = AsyncMock(return_value="2.40 2.10 1.80 2/120 12346")
        normal_res = await proactive._check_cpu_load(threshold=_SRE_CPU_LOAD_THRESHOLD)
        self.assertEqual(normal_res, "")

    async def test_11_proactive_sre_swap_600mb_trigger(self) -> None:
        """[TRỌNG TÂM] Mô phỏng Swap 600MB -> BẮT BUỘC KÍCH HOẠT CẢNH BÁO (Disk Thrashing)."""
        mem_mock = MagicMock()
        mem_mock.should_send_proactive_alert = AsyncMock(return_value=True)
        mem_mock.upsert_proactive_check = AsyncMock()

        proactive = ProactiveIntelligenceService(
            ssh_client=MagicMock(),
            memory_service=mem_mock,
            telegram_bot=MagicMock(),
        )

        # Swap 600MB (vượt ngưỡng 500MB)
        proactive._ssh.run_command = AsyncMock(return_value="600")
        alert = await proactive._check_swap(threshold_mb=_SRE_SWAP_ALERT_MB)

        self.assertTrue(bool(alert), "Swap 600MB phải kích hoạt cảnh báo Disk Thrashing!")
        self.assertIn("Dung lượng Swap cao", alert)
        self.assertIn("600MB", alert)
        self.assertIn("Disk Thrashing", alert)

        # Kiểm tra Swap an toàn 250MB -> Không cảnh báo
        proactive._ssh.run_command = AsyncMock(return_value="250")
        safe_res = await proactive._check_swap(threshold_mb=_SRE_SWAP_ALERT_MB)
        self.assertEqual(safe_res, "")

    async def test_12_proactive_sre_container_core_crash_trigger(self) -> None:
        """[TRỌNG TÂM] Mô phỏng container core bị crash (Exited/Restarting) -> KÍCH HOẠT CẢNH BÁO."""
        mem_mock = MagicMock()
        mem_mock.should_send_proactive_alert = AsyncMock(return_value=True)
        mem_mock.upsert_proactive_check = AsyncMock()

        proactive = ProactiveIntelligenceService(
            ssh_client=MagicMock(),
            memory_service=mem_mock,
            telegram_bot=MagicMock(),
        )

        # dashboard_metrics_service bị crash với mã 137 (OOMKilled)
        crash_output = (
            "dashboard_ai_agent\tUp 5 hours\trunning\n"
            "dashboard_frontend\tUp 5 hours\trunning\n"
            "dashboard_metrics_service\tExited (137) 2 minutes ago\texited\n"
            "dashboard_auth_service\tUp 5 hours\trunning\n"
            "dashboard_file_service\tUp 5 hours\trunning\n"
            "dashboard_db\tUp 5 hours\trunning"
        )
        proactive._ssh.run_command = AsyncMock(return_value=crash_output)
        alert = await proactive._check_core_containers()

        self.assertTrue(bool(alert), "Container core crash phải kích hoạt cảnh báo!")
        self.assertIn("Core Container gặp sự cố", alert)
        self.assertIn("dashboard_metrics_service", alert)
        self.assertIn("Exited (137)", alert)

    async def test_13_proactive_sre_core_containers_all_healthy(self) -> None:
        """Kiểm tra khi cả 6 core containers đều Up và running thì trả về rỗng."""
        mem_mock = MagicMock()
        mem_mock.should_send_proactive_alert = AsyncMock(return_value=True)

        proactive = ProactiveIntelligenceService(
            ssh_client=MagicMock(),
            memory_service=mem_mock,
            telegram_bot=MagicMock(),
        )

        healthy_output = "\n".join([f"{c}\tUp 12 hours\trunning" for c in _CORE_CONTAINERS])
        proactive._ssh.run_command = AsyncMock(return_value=healthy_output)
        alert = await proactive._check_core_containers()
        self.assertEqual(alert, "")

    async def test_14_proactive_sre_missing_container_detection(self) -> None:
        """Kiểm tra phát hiện thiếu sót container core (không tìm thấy trong output docker ps)."""
        mem_mock = MagicMock()
        mem_mock.should_send_proactive_alert = AsyncMock(return_value=True)
        mem_mock.upsert_proactive_check = AsyncMock()

        proactive = ProactiveIntelligenceService(
            ssh_client=MagicMock(),
            memory_service=mem_mock,
            telegram_bot=MagicMock(),
        )

        # Thiếu dashboard_auth_service và dashboard_db
        partial_output = (
            "dashboard_ai_agent\tUp 2 hours\trunning\n"
            "dashboard_frontend\tUp 2 hours\trunning\n"
            "dashboard_metrics_service\tUp 2 hours\trunning\n"
            "dashboard_file_service\tUp 2 hours\trunning"
        )
        proactive._ssh.run_command = AsyncMock(return_value=partial_output)
        alert = await proactive._check_core_containers()

        self.assertIn("Core Container gặp sự cố", alert)
        self.assertIn("dashboard_auth_service", alert)
        self.assertIn("dashboard_db", alert)
        self.assertIn("Không tìm thấy", alert)

    async def test_15_cooldown_guard_anti_spam_5_consecutive_incidents(self) -> None:
        """
        [TRỌNG TÂM] Thử nghiệm cơ chế Cooldown Guard ngăn chặn spam khi có 5 sự cố liên tiếp.
        Chỉ cho phép phát cảnh báo ở lần 1, chặn hoàn toàn ở các lần 2, 3, 4, 5.
        """
        sent_alerts: List[str] = []
        alert_call_count = 0

        # Giả lập memory service với Cooldown state thực tế
        last_alert_time: Dict[str, float] = {}

        async def mock_should_send_alert(check_key: str, cooldown_hours: float) -> bool:
            nonlocal alert_call_count
            alert_call_count += 1
            now = time.time()
            if check_key in last_alert_time:
                elapsed_hours = (now - last_alert_time[check_key]) / 3600.0
                if elapsed_hours < cooldown_hours:
                    return False  # Đang trong cooldown -> CHẶN
            return True

        async def mock_upsert_check(check_key: str, val: str, send_alert: bool = True) -> None:
            if send_alert:
                last_alert_time[check_key] = time.time()

        mem_mock = MagicMock()
        mem_mock.should_send_proactive_alert = AsyncMock(side_effect=mock_should_send_alert)
        mem_mock.upsert_proactive_check = AsyncMock(side_effect=mock_upsert_check)

        proactive = ProactiveIntelligenceService(
            ssh_client=MagicMock(),
            memory_service=mem_mock,
            telegram_bot=MagicMock(),
        )

        # Giả lập 5 lần quét liên tiếp khi RAM liên tục ở mức nguy cấp 95%
        proactive._ssh.run_command = AsyncMock(return_value="95")

        for scan_index in range(1, 6):
            alert = await proactive._check_memory(threshold_pct=85)
            if alert:
                sent_alerts.append(f"Scan {scan_index}: {alert}")

        # Khẳng định: Trong 5 lần gặp sự cố liên tiếp, Cooldown Guard CHỈ cho phép gửi ĐÚNG 1 alert!
        self.assertEqual(
            len(sent_alerts),
            1,
            f"Cooldown Guard thất bại! Đã gửi {len(sent_alerts)} cảnh báo thay vì đúng 1 cảnh báo: {sent_alerts}"
        )
        self.assertIn("Scan 1:", sent_alerts[0])
        self.assertEqual(alert_call_count, 5)

    async def test_16_proactive_sre_root_disk_92_pct_trigger(self) -> None:
        """Kiểm tra phân vùng Root (/) >= 90% kích hoạt cảnh báo, <90% thì im lặng."""
        mem_mock = MagicMock()
        mem_mock.should_send_proactive_alert = AsyncMock(return_value=True)
        mem_mock.upsert_proactive_check = AsyncMock()

        proactive = ProactiveIntelligenceService(
            ssh_client=MagicMock(),
            memory_service=mem_mock,
            telegram_bot=MagicMock(),
        )

        # 92% -> Cảnh báo
        proactive._ssh.run_command = AsyncMock(return_value="92")
        alert = await proactive._check_root_disk(threshold_pct=_SRE_ROOT_DISK_ALERT_PCT)
        self.assertIn("Phân vùng root (/) sắp đầy", alert)
        self.assertIn("92%", alert)

        # 84% -> Im lặng
        proactive._ssh.run_command = AsyncMock(return_value="84")
        safe_res = await proactive._check_root_disk(threshold_pct=_SRE_ROOT_DISK_ALERT_PCT)
        self.assertEqual(safe_res, "")

    async def test_17_proactive_on_demand_patrol_scan_aggregated_matrix(self) -> None:
        """Kiểm tra run_patrol_scan tổng hợp đa sự cố (RAM, CPU, Swap, Core Container) thành báo cáo JSON chuẩn."""
        mem_mock = MagicMock()
        mem_mock.should_send_proactive_alert = AsyncMock(return_value=True)
        mem_mock.upsert_proactive_check = AsyncMock()

        proactive = ProactiveIntelligenceService(
            ssh_client=MagicMock(),
            memory_service=mem_mock,
            telegram_bot=MagicMock(),
        )

        async def mock_patrol_ssh(cmd: str) -> str:
            if "df -h --output" in cmd:
                return " 40% /\n 30% /data"
            if "free |" in cmd:
                return "88"  # RAM 88% -> Trigger
            if "sites-enabled" in cmd:
                return ""
            if "journalctl" in cmd:
                return "0"
            if "docker ps --format" in cmd:
                return ""
            if "loadavg" in cmd:
                return "3.90 3.20 2.50 4/120 4455"  # CPU 3.9 -> Trigger
            if "Swap:" in cmd:
                return "650"  # Swap 650MB -> Trigger
            if "df -h /" in cmd:
                return "65"  # Root 65% -> Safe
            if "docker ps -a" in cmd:
                # dashboard_db bị Exited -> Trigger
                return (
                    "dashboard_ai_agent\tUp 6 hours\trunning\n"
                    "dashboard_frontend\tUp 6 hours\trunning\n"
                    "dashboard_metrics_service\tUp 6 hours\trunning\n"
                    "dashboard_auth_service\tUp 6 hours\trunning\n"
                    "dashboard_file_service\tUp 6 hours\trunning\n"
                    "dashboard_db\tExited (1) 10 minutes ago\texited"
                )
            return ""

        proactive._ssh.run_command = AsyncMock(side_effect=mock_patrol_ssh)

        patrol_report = await proactive.run_patrol_scan()

        self.assertEqual(patrol_report["status"], "warning")
        self.assertEqual(patrol_report["total_checks"], 9)
        self.assertGreaterEqual(len(patrol_report["alerts"]), 4)

        alert_text = " ".join(patrol_report["alerts"])
        self.assertIn("RAM đang cao", alert_text)
        self.assertIn("CPU Load Average cao", alert_text)
        self.assertIn("Dung lượng Swap cao", alert_text)
        self.assertIn("dashboard_db", alert_text)


if __name__ == "__main__":
    unittest.main()
