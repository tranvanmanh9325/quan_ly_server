"""
test_challenger_m5_empirical.py — Milestone 5 Empirical Verification Suite.

Target:
  - Subconscious Dream Engine (2-Phase SWS & REM)
  - Hyperdimensional VSA Virtual Cortex 32GB mmap Sync & Zero-Copy Retrieval
  - Proactive SRE Curiosity Engine (9 Vitals Patrol & Anti-Spam Cooldown)

Code Under Test:
  - services/ai-agent-service/app/services/dream_engine.py
  - services/ai-agent-service/app/services/proactive_service.py
  - services/ai-agent-service/app/core/brain_core.py
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


class TestChallengerM5EmpiricalSuite(unittest.IsolatedAsyncioTestCase):
    """
    Challenger Suite for Milestone 5:
    Continual Learning, Subconscious Dream Engine SWS/REM, VSA Cortex Sync & Proactive SRE Curiosity.
    """

    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_m5_cortex_"))
        self.brain = ArtificialBrain(storage_dir=self.temp_dir)

    def tearDown(self) -> None:
        if self.brain and hasattr(self.brain, "cortex"):
            self.brain.cortex.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ─────────────────────────────────────────────────────────────────────────
    # 1. SUBCONSCIOUS DREAM ENGINE: PHASE 1 SLOW-WAVE SLEEP (SWS)
    # ─────────────────────────────────────────────────────────────────────────

    async def test_01_sws_cycle_episodic_replay(self) -> None:
        """SWS Phase 1 replays recent episodic memories into brain working memory."""
        mock_mem = MagicMock()
        mock_mem.get_recent_episodes = AsyncMock(
            return_value="🗓️ SỰ KIỆN GẦN ĐÂY:\n- Fix bug OOM killer trên container metrics\n- Tối ưu TCP BBR congestion control"
        )
        mock_mem.consolidation_cycle = AsyncMock(return_value={"decayed": 2, "pruned": 1, "episodes_expired": 0})
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
        self.assertGreaterEqual(res["replayed_memories"], 2)
        self.assertEqual(res["pruned_lessons"], 1)
        self.assertEqual(res["decayed_lessons"], 2)

    async def test_02_sws_cycle_synaptic_pruning_and_vsa_sync(self) -> None:
        """SWS Phase 1 prunes weak lessons (<0.25 & disused > 7d) and synchronizes active lessons to VSA Cortex."""
        now = time.time()
        old_time = (datetime.now(VN_TZ) - timedelta(days=10)).isoformat()
        recent_time = (datetime.now(VN_TZ) - timedelta(days=1)).isoformat()

        lessons = [
            # Lesson 1: Valid high-confidence lesson -> should be synced
            {
                "id": 101,
                "trigger_pattern": "swap 100gb",
                "lesson_text": "Không được tạo swap 100GB trên máy RAM 3.2GB tránh Disk Thrashing",
                "event_type": "hardware_rule",
                "confidence": 0.95,
                "is_active": True,
                "last_used_at": recent_time,
            },
            # Lesson 2: Weak and disused > 7 days -> should be pruned
            {
                "id": 102,
                "trigger_pattern": "test_weak",
                "lesson_text": "Quy tắc thử nghiệm tạm thời",
                "event_type": "ephemeral",
                "confidence": 0.15,
                "is_active": True,
                "last_used_at": old_time,
            },
            # Lesson 3: Inactive lesson -> should be pruned / ignored
            {
                "id": 103,
                "trigger_pattern": "deactivated_rule",
                "lesson_text": "Quy tắc đã bị hủy bỏ",
                "event_type": "deprecated",
                "confidence": 0.80,
                "is_active": False,
                "last_used_at": recent_time,
            },
        ]

        mock_mem = MagicMock()
        mock_mem.get_recent_episodes = AsyncMock(return_value="")
        mock_mem.consolidation_cycle = AsyncMock(return_value={"decayed": 1, "pruned": 1, "episodes_expired": 0})
        mock_mem.list_lessons_for_display = AsyncMock(return_value=lessons)

        dream = SubconsciousDreamEngine(
            brain=self.brain,
            llm_router=MagicMock(),
            ssh_client=MagicMock(),
            memory_service=mock_mem,
            storage_dir=self.temp_dir,
        )

        res = await dream.run_sws_cycle()
        self.assertEqual(res["synced_cortex_vectors"], 1)

        # Verify lesson 101 exists in VSA cortex
        self.assertIn("lesson_101", self.brain.cortex.entry_index)
        self.assertNotIn("lesson_102", self.brain.cortex.entry_index)
        self.assertNotIn("lesson_103", self.brain.cortex.entry_index)

    async def test_03_sws_cycle_adenosine_flush_and_neuro_balance(self) -> None:
        """SWS flushes Adenosine sleep pressure by 85% and rebalances neurochemicals."""
        self.brain.neuro.accumulate_adenosine(0.70)
        self.brain.neuro.stimulate("cortisol", 0.30)
        initial_adenosine = self.brain.neuro.adenosine
        initial_cortisol = self.brain.neuro.cortisol

        dream = SubconsciousDreamEngine(
            brain=self.brain,
            llm_router=MagicMock(),
            ssh_client=MagicMock(),
            storage_dir=self.temp_dir,
        )

        res = await dream.run_sws_cycle()
        self.assertLess(res["adenosine"], initial_adenosine * 0.25)
        self.assertLess(res["cortisol"], initial_cortisol)
        self.assertIn("serotonin", res)

    # ─────────────────────────────────────────────────────────────────────────
    # 2. SUBCONSCIOUS DREAM ENGINE: PHASE 2 REM SLEEP & MORNING EPIPHANY
    # ─────────────────────────────────────────────────────────────────────────

    async def test_04_rem_dream_cycle_counterfactual_synthesis(self) -> None:
        """REM Dream cycle generates creative counterfactual insight with temperature=0.85."""
        mock_router = MagicMock()
        mock_router.complete = AsyncMock(return_value={
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": json.dumps({
                        "topic": "Giải pháp Zero-Copy Cache Haswell i5-4310U",
                        "insight": "Kết hợp VSA mmap với CPU Haswell L3 cache partitioning triệt tiêu I/O wait trên RAM 3.2GB.",
                        "sisterly_note": "Anh Mạnh cứ ngủ ngon nhé, sáng mai server sẽ vận hành êm ru ạ!"
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

        with patch.object(dream, "check_hardware_idle", AsyncMock(return_value=(True, "load1=0.20"))):
            epiphany = await dream.run_rem_dream_cycle(force=True)

        self.assertIsNotNone(epiphany)
        self.assertEqual(epiphany["topic"], "Giải pháp Zero-Copy Cache Haswell i5-4310U")
        self.assertIn("Haswell", epiphany["insight"])
        self.assertIn("Anh Mạnh", epiphany["sisterly_note"])
        # Check call arguments for temperature 0.85
        mock_router.complete.assert_called_once()
        _, kwargs = mock_router.complete.call_args
        self.assertEqual(kwargs.get("temperature"), 0.85)

        # Verify stored into VSA Cortex
        self.assertIn(epiphany["id"], self.brain.cortex.entry_index)

    def test_05_morning_epiphany_format_and_single_delivery(self) -> None:
        """Morning epiphany formats warm sisterly greeting and marks delivered to prevent duplicate."""
        dream = SubconsciousDreamEngine(
            brain=self.brain,
            llm_router=MagicMock(),
            ssh_client=MagicMock(),
            storage_dir=self.temp_dir,
        )
        dream.pending_morning_epiphany = {
            "id": "epiphany_test_1",
            "topic": "Cơ chế chịu lỗi Card mạng kép",
            "insight": "Tự động failover Realtek USB sang Intel onboard khi mạng giật lag.",
            "sisterly_note": "Em luôn túc trực giữ kết nối vững chắc cho anh!",
            "delivered": False,
        }

        with patch.object(SubconsciousDreamEngine, "is_morning_window", return_value=True):
            delivered_text = dream.pop_morning_epiphany()

        self.assertIsNotNone(delivered_text)
        self.assertIn("Chào buổi sáng anh Mạnh!", delivered_text)
        self.assertIn("Cơ chế chịu lỗi Card mạng kép", delivered_text)
        self.assertIn("Em luôn túc trực", delivered_text)
        self.assertIsNone(dream.pending_morning_epiphany)
        self.assertTrue(dream.delivered_epiphanies[-1]["delivered"])

        # Subsequent call in same morning must return None
        with patch.object(SubconsciousDreamEngine, "is_morning_window", return_value=True):
            second_delivery = dream.pop_morning_epiphany()
        self.assertIsNone(second_delivery)

    # ─────────────────────────────────────────────────────────────────────────
    # 3. HYPERDIMENSIONAL VSA VIRTUAL CORTEX & ZERO-COPY MMAP
    # ─────────────────────────────────────────────────────────────────────────

    def test_06_vsa_dense_bipolar_algebra_and_popcnt_similarity(self) -> None:
        """Verifies 10,000-bit VSA algebra: Bind (XOR), Bundle, Permute, and Hamming similarity."""
        cortex = self.brain.cortex
        self.assertEqual(HV_DIM_BITS, 10000)
        self.assertEqual(HV_DIM_BYTES, 1250)

        v1 = cortex.encode_concept("nguy cơ tràn ram vật lý oom killer")
        v2 = cortex.encode_concept("nguy cơ tràn ram vật lý oom killer")
        v3 = cortex.encode_concept("tối ưu hóa ngrok tunnel websocket")

        # Identity similarity must be 1.0
        self.assertAlmostEqual(cortex.hamming_similarity(v1, v2), 1.0, places=4)

        # Orthogonal concepts should have similarity near ~0.50 (+/- 0.08)
        sim_ortho = cortex.hamming_similarity(v1, v3)
        self.assertGreaterEqual(sim_ortho, 0.42)
        self.assertLessEqual(sim_ortho, 0.58)

        # VSA Invertible Binding property: (A ^ B) ^ B == A
        bound = cortex.bind(v1, v3)
        unbound = cortex.bind(bound, v3)
        self.assertAlmostEqual(cortex.hamming_similarity(unbound, v1), 1.0, places=4)

        # Permute (Cyclic shift): permuted vector is quasi-orthogonal to original
        permuted = cortex.permute(v1, shift=17)
        self.assertEqual(len(permuted), HV_DIM_BYTES)
        self.assertLess(cortex.hamming_similarity(permuted, v1), 0.65)

    def test_07_vsa_cortex_mmap_sync_and_prune(self) -> None:
        """Verifies sync_lessons writes into mmap and removes pruned concepts."""
        cortex = self.brain.cortex

        test_lessons = [
            {
                "id": 201,
                "trigger_pattern": "docker prune -a",
                "lesson_text": "Phải kiểm tra kỹ volume trước khi prune",
                "event_type": "safety",
                "confidence": 0.90,
                "is_active": True,
            },
            {
                "id": 202,
                "trigger_pattern": "test_obsolete",
                "lesson_text": "Kiểm tra phiên bản cũ",
                "event_type": "obsolete",
                "confidence": 0.10,
                "is_active": False,
            }
        ]

        stats = cortex.sync_lessons(test_lessons)
        self.assertEqual(stats["synced"], 1)
        self.assertIn("lesson_201", cortex.entry_index)

        # Now deactivate lesson 201 and re-sync -> should prune
        test_lessons[0]["is_active"] = False
        stats2 = cortex.sync_lessons(test_lessons)
        self.assertEqual(stats2["pruned"], 1)
        self.assertNotIn("lesson_201", cortex.entry_index)

    def test_08_vsa_cortex_zero_copy_demand_paging_stats(self) -> None:
        """Verifies cortex diagnostics statistics and zero-copy demand-paging footprint."""
        stats = self.brain.cortex.get_cortex_stats()
        self.assertTrue(stats["mmap_active"])
        self.assertEqual(stats["dim_bits"], 10000)
        self.assertGreaterEqual(stats["max_capacity"], 1000)
        self.assertIn("pruned_synapses", stats)

    # ─────────────────────────────────────────────────────────────────────────
    # 4. PROACTIVE SRE CURIOSITY ENGINE (9 VITALS & ANTI-SPAM)
    # ─────────────────────────────────────────────────────────────────────────

    async def test_09_proactive_sre_ram_threshold_85_pct(self) -> None:
        """Proactive SRE detects RAM >= 85% on 3.2GB host."""
        mem_mock = MagicMock()
        mem_mock.should_send_proactive_alert = AsyncMock(return_value=True)
        mem_mock.upsert_proactive_check = AsyncMock()

        proactive = ProactiveIntelligenceService(
            ssh_client=MagicMock(),
            memory_service=mem_mock,
            telegram_bot=MagicMock(),
        )

        # 84% -> No alert when threshold is 85%
        proactive._ssh.run_command = AsyncMock(return_value="84")
        res_84 = await proactive._check_memory(threshold_pct=_SRE_RAM_ALERT_PCT)
        self.assertEqual(res_84, "")

        # 87% -> Alert triggered
        proactive._ssh.run_command = AsyncMock(return_value="87")
        res_87 = await proactive._check_memory(threshold_pct=_SRE_RAM_ALERT_PCT)
        self.assertIn("RAM đang cao", res_87)
        self.assertIn("87%", res_87)

    async def test_10_proactive_sre_cpu_load_threshold_3_5(self) -> None:
        """Proactive SRE detects CPU load average > 3.5 (exceeding 2 Cores 4 Threads i5-4310U)."""
        mem_mock = MagicMock()
        mem_mock.should_send_proactive_alert = AsyncMock(return_value=True)
        mem_mock.upsert_proactive_check = AsyncMock()

        proactive = ProactiveIntelligenceService(
            ssh_client=MagicMock(),
            memory_service=mem_mock,
            telegram_bot=MagicMock(),
        )

        # Safe load1 = 2.10 -> No alert
        proactive._ssh.run_command = AsyncMock(return_value="2.10 1.85 1.50 2/120 4567")
        res_safe = await proactive._check_cpu_load()
        self.assertEqual(res_safe, "")

        # Critical load1 = 4.25 -> Alert triggered
        proactive._ssh.run_command = AsyncMock(return_value="4.25 3.80 2.90 3/130 5678")
        res_alert = await proactive._check_cpu_load()
        self.assertIn("CPU Load Average cao", res_alert)
        self.assertIn("4.25", res_alert)
        self.assertIn("Intel Core i5-4310U", res_alert)

    async def test_11_proactive_sre_swap_threshold_500mb(self) -> None:
        """Proactive SRE detects Swap > 500MB (warning against SSD Disk Thrashing)."""
        mem_mock = MagicMock()
        mem_mock.should_send_proactive_alert = AsyncMock(return_value=True)
        mem_mock.upsert_proactive_check = AsyncMock()

        proactive = ProactiveIntelligenceService(
            ssh_client=MagicMock(),
            memory_service=mem_mock,
            telegram_bot=MagicMock(),
        )

        # Swap 350MB <= 500MB -> No alert
        proactive._ssh.run_command = AsyncMock(return_value="350")
        res_safe = await proactive._check_swap()
        self.assertEqual(res_safe, "")

        # Swap 680MB > 500MB -> Alert triggered
        proactive._ssh.run_command = AsyncMock(return_value="680")
        res_alert = await proactive._check_swap()
        self.assertIn("Dung lượng Swap cao", res_alert)
        self.assertIn("680MB", res_alert)
        self.assertIn("Disk Thrashing", res_alert)

    async def test_12_proactive_sre_root_disk_threshold_90_pct(self) -> None:
        """Proactive SRE detects Root partition (/) >= 90%."""
        mem_mock = MagicMock()
        mem_mock.should_send_proactive_alert = AsyncMock(return_value=True)
        mem_mock.upsert_proactive_check = AsyncMock()

        proactive = ProactiveIntelligenceService(
            ssh_client=MagicMock(),
            memory_service=mem_mock,
            telegram_bot=MagicMock(),
        )

        # 88% -> No alert
        proactive._ssh.run_command = AsyncMock(return_value="88")
        res_safe = await proactive._check_root_disk()
        self.assertEqual(res_safe, "")

        # 92% -> Alert triggered
        proactive._ssh.run_command = AsyncMock(return_value="92")
        res_alert = await proactive._check_root_disk()
        self.assertIn("Phân vùng root (/) sắp đầy", res_alert)
        self.assertIn("92%", res_alert)

    async def test_13_proactive_sre_core_containers_health(self) -> None:
        """Proactive SRE verifies all 6 core containers and detects unhealthy/exited ones."""
        mem_mock = MagicMock()
        mem_mock.should_send_proactive_alert = AsyncMock(return_value=True)
        mem_mock.upsert_proactive_check = AsyncMock()

        proactive = ProactiveIntelligenceService(
            ssh_client=MagicMock(),
            memory_service=mem_mock,
            telegram_bot=MagicMock(),
        )

        # Case A: All 6 core containers are healthy and running
        all_up_output = (
            "dashboard_ai_agent\tUp 3 hours\trunning\n"
            "dashboard_frontend\tUp 3 hours\trunning\n"
            "dashboard_metrics_service\tUp 3 hours\trunning\n"
            "dashboard_auth_service\tUp 3 hours\trunning\n"
            "dashboard_file_service\tUp 3 hours\trunning\n"
            "dashboard_db\tUp 3 hours\trunning"
        )
        proactive._ssh.run_command = AsyncMock(return_value=all_up_output)
        res_healthy = await proactive._check_core_containers()
        self.assertEqual(res_healthy, "")

        # Case B: dashboard_db is Exited (code 1)
        unhealthy_output = (
            "dashboard_ai_agent\tUp 3 hours\trunning\n"
            "dashboard_frontend\tUp 3 hours\trunning\n"
            "dashboard_metrics_service\tUp 3 hours\trunning\n"
            "dashboard_auth_service\tUp 3 hours\trunning\n"
            "dashboard_file_service\tUp 3 hours\trunning\n"
            "dashboard_db\tExited (1) 5 minutes ago\texited"
        )
        proactive._ssh.run_command = AsyncMock(return_value=unhealthy_output)
        res_failed = await proactive._check_core_containers()
        self.assertIn("Core Container gặp sự cố", res_failed)
        self.assertIn("dashboard_db", res_failed)

    async def test_14_proactive_sre_anti_spam_cooldown(self) -> None:
        """Cooldown guard suppresses repeated alerts within cooldown window."""
        mem_mock = MagicMock()
        # First call: allowed
        mem_mock.should_send_proactive_alert = AsyncMock(return_value=True)
        mem_mock.upsert_proactive_check = AsyncMock()

        proactive = ProactiveIntelligenceService(
            ssh_client=MagicMock(),
            memory_service=mem_mock,
            telegram_bot=MagicMock(),
        )

        proactive._ssh.run_command = AsyncMock(return_value="95")
        first_alert = await proactive._check_root_disk()
        self.assertIn("Phân vùng root", first_alert)

        # Second call within cooldown: suppressed
        mem_mock.should_send_proactive_alert = AsyncMock(return_value=False)
        second_alert = await proactive._check_root_disk()
        self.assertEqual(second_alert, "")

    async def test_15_proactive_sre_on_demand_patrol_scan(self) -> None:
        """run_patrol_scan executes all 9 checks on demand and returns structured diagnostics."""
        mem_mock = MagicMock()
        mem_mock.should_send_proactive_alert = AsyncMock(return_value=True)
        mem_mock.upsert_proactive_check = AsyncMock()

        proactive = ProactiveIntelligenceService(
            ssh_client=MagicMock(),
            memory_service=mem_mock,
            telegram_bot=MagicMock(),
        )

        # Mock SSH outputs returning normal healthy metrics
        async def mock_exec(cmd: str) -> str:
            if "df -h --output" in cmd:
                return " 45% /\n 30% /data"
            if "free |" in cmd:
                return "65"
            if "sites-enabled" in cmd:
                return ""
            if "journalctl" in cmd:
                return "0"
            if "docker ps --format" in cmd:
                return ""
            if "loadavg" in cmd:
                return "1.20 1.10 0.95 1/120 7890"
            if "Swap:" in cmd:
                return "120"
            if "df -h /" in cmd:
                return "50"
            if "docker ps -a" in cmd:
                return (
                    "dashboard_ai_agent\tUp 5 hours\trunning\n"
                    "dashboard_frontend\tUp 5 hours\trunning\n"
                    "dashboard_metrics_service\tUp 5 hours\trunning\n"
                    "dashboard_auth_service\tUp 5 hours\trunning\n"
                    "dashboard_file_service\tUp 5 hours\trunning\n"
                    "dashboard_db\tUp 5 hours\trunning"
                )
            return ""

        proactive._ssh.run_command = AsyncMock(side_effect=mock_exec)

        report = await proactive.run_patrol_scan()
        self.assertEqual(report["status"], "healthy")
        self.assertEqual(len(report["alerts"]), 0)
        self.assertEqual(report["total_checks"], 9)

    async def test_16_proactive_sre_background_scan_cycle(self) -> None:
        """_run_scan_cycle executes full background scan without exceptions and triggers brain.step_pulse with parsed ram_usage."""
        mem_mock = MagicMock()
        mem_mock.should_send_proactive_alert = AsyncMock(return_value=True)
        mem_mock.upsert_proactive_check = AsyncMock()
        mem_mock.record_episode = AsyncMock()

        tg_mock = MagicMock()
        tg_mock.send_message = AsyncMock()
        tg_mock.chat_id = "test_chat_m5"

        proactive = ProactiveIntelligenceService(
            ssh_client=MagicMock(),
            memory_service=mem_mock,
            telegram_bot=tg_mock,
        )

        # Case 1: RAM exceeds 85% threshold (e.g. 89%) -> triggers alert, passes 89.0 to step_pulse
        async def mock_exec_high_ram(cmd: str) -> str:
            if "df -h --output" in cmd:
                return " 40% /\n 30% /data"
            if "free |" in cmd:
                return "89"  # High RAM -> triggers alert with '89%'
            if "sites-enabled" in cmd:
                return ""
            if "journalctl" in cmd:
                return "0"
            if "docker ps --format" in cmd:
                return ""
            if "loadavg" in cmd:
                return "1.05 1.10 0.95 1/120 7890"
            if "Swap:" in cmd:
                return "100"
            if "df -h /" in cmd:
                return "45"
            if "docker ps -a" in cmd:
                return "\n".join([f"{c}\tUp 6 hours\trunning" for c in _CORE_CONTAINERS])
            return ""

        proactive._ssh.run_command = AsyncMock(side_effect=mock_exec_high_ram)

        with patch.object(self.brain, "step_pulse", wraps=self.brain.step_pulse) as spy_step_pulse, \
             patch.object(ArtificialBrain, "get_instance", return_value=self.brain):
            await proactive._run_scan_cycle()

            # Assert brain.step_pulse received ram_usage = 89.0
            spy_step_pulse.assert_called_once()
            called_metrics = spy_step_pulse.call_args[0][0]
            self.assertEqual(called_metrics.get("ram_usage"), 89.0)
            self.assertEqual(called_metrics.get("cpu_usage"), 0.0)

            # Assert Telegram message sent with RAM alert
            tg_mock.send_message.assert_awaited_once()
            sent_msg = tg_mock.send_message.call_args[0][1]
            self.assertIn("RAM đang cao", sent_msg)
            self.assertIn("89%", sent_msg)

        # Case 2: Healthy RAM (e.g. 60%) -> ram_pct is 0.0, no exceptions, no alerts sent
        tg_mock.send_message.reset_mock()
        async def mock_exec_healthy(cmd: str) -> str:
            if "free |" in cmd:
                return "60"  # Below 85%
            if "df -h --output" in cmd:
                return " 40% /\n 30% /data"
            if "df -h /" in cmd:
                return "45"
            if "Swap:" in cmd:
                return "100"
            if "loadavg" in cmd:
                return "1.00 1.00 1.00"
            if "docker ps -a" in cmd:
                return "\n".join([f"{c}\tUp 6 hours\trunning" for c in _CORE_CONTAINERS])
            return ""

        proactive._ssh.run_command = AsyncMock(side_effect=mock_exec_healthy)

        with patch.object(self.brain, "step_pulse", wraps=self.brain.step_pulse) as spy_step_pulse, \
             patch.object(ArtificialBrain, "get_instance", return_value=self.brain):
            await proactive._run_scan_cycle()

            # Assert step_pulse called with ram_usage = 0.0
            spy_step_pulse.assert_called_once()
            called_metrics = spy_step_pulse.call_args[0][0]
            self.assertEqual(called_metrics.get("ram_usage"), 0.0)
            tg_mock.send_message.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
