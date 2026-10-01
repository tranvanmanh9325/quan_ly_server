"""
Test Suite: Proactive Action Execution & Auto-Remediation (R3).
Dự án: True Autonomous AI Agent Architecture (Tiểu Bảo Bảo) - services/ai-agent-service
Mã nguồn kiểm thử: services/ai-agent-service/tests/test_proactive_remediation.py

Verifies:
1. Tri-Tier Risk Classification in _decide_remediation (Tier 1 Safe auto_execute=True vs Tier 2+ auto_execute=False).
2. Per-action Cooldown mechanism (30 minutes / 1800 seconds).
3. Before/After system metrics snapshot collection and efficiency calculation.
4. Telegram proactive HTML reporting and AgentMemoryService episode recording.
5. Fault tolerance: try/except safety wrapping in _run_scan_cycle against SSH and Telegram failures.
"""

import asyncio
from datetime import datetime, timezone, timedelta
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.proactive_service import (
    ProactiveIntelligenceService,
    _REMEDIATION_COOLDOWN_SECONDS,
)


class TestProactiveRemediation(unittest.IsolatedAsyncioTestCase):
    """Unit and Integration Test Suite for Proactive Self-Healing & Auto-Remediation (R3)."""

    async def asyncSetUp(self) -> None:
        self.mock_ssh = MagicMock()
        self.mock_ssh.run_command = AsyncMock(return_value="Command executed successfully")

        self.mock_memory = MagicMock()
        self.mock_memory.record_episode = AsyncMock()
        self.mock_memory.should_send_proactive_alert = AsyncMock(return_value=True)
        self.mock_memory.upsert_proactive_check = AsyncMock()

        self.mock_telegram = MagicMock()
        self.mock_telegram.chat_id = "test_chat_m3_123"
        self.mock_telegram.send_message = AsyncMock(return_value=True)

        self.service = ProactiveIntelligenceService(
            ssh_client=self.mock_ssh,
            memory_service=self.mock_memory,
            telegram_bot=self.mock_telegram,
            scan_interval=3600,
        )

    # ── 1. Tri-Tier Decision Logic Tests ─────────────────────────────────────

    def test_decide_remediation_disk_alert(self) -> None:
        """Kiểm tra disk alert trả về Tier 1 Safe auto-execute docker_prune."""
        alert = "💽 <b>Ổ đĩa sắp đầy:</b>\n  <code>/dev/sda1</code>: 89%"
        decision = self.service._decide_remediation(alert)

        self.assertIsNotNone(decision)
        self.assertEqual(decision["action_key"], "docker_prune")
        self.assertEqual(decision["tier"], 1)
        self.assertEqual(decision["command"], "docker system prune -f")
        self.assertEqual(decision["metric_type"], "disk")
        self.assertTrue(decision["auto_execute"])
        self.assertIn("Docker", decision["description"])

    def test_decide_remediation_root_disk_alert(self) -> None:
        """Kiểm tra phân vùng root sắp đầy trả về Tier 1 docker_prune."""
        alert = "💽 <b>Phân vùng root (/) sắp đầy:</b> 92% (ngưỡng an toàn < 90%)"
        decision = self.service._decide_remediation(alert)

        self.assertIsNotNone(decision)
        self.assertEqual(decision["action_key"], "docker_prune")
        self.assertEqual(decision["tier"], 1)
        self.assertTrue(decision["auto_execute"])

    def test_decide_remediation_log_cleanup_alert(self) -> None:
        """Kiểm tra log tích tụ trả về Tier 1 cleanup_logs."""
        alert = "⚠️ Cảnh báo: log tích tụ quá lớn trên phân vùng hệ thống"
        decision = self.service._decide_remediation(alert)

        self.assertIsNotNone(decision)
        self.assertEqual(decision["action_key"], "cleanup_logs")
        self.assertEqual(decision["tier"], 1)
        self.assertEqual(decision["command"], "journalctl --vacuum-time=3d")
        self.assertEqual(decision["metric_type"], "disk")
        self.assertTrue(decision["auto_execute"])

    def test_decide_remediation_ram_alert(self) -> None:
        """Kiểm tra RAM alert trả về Tier 1 drop_caches."""
        alert = "🧠 <b>RAM đang cao:</b> 91% đã sử dụng (ngưỡng cảnh báo: 85%)"
        decision = self.service._decide_remediation(alert)

        self.assertIsNotNone(decision)
        self.assertEqual(decision["action_key"], "drop_caches")
        self.assertEqual(decision["tier"], 1)
        self.assertEqual(decision["command"], "sync && echo 3 > /proc/sys/vm/drop_caches")
        self.assertEqual(decision["metric_type"], "ram")
        self.assertTrue(decision["auto_execute"])

    def test_decide_remediation_swap_alert(self) -> None:
        """Kiểm tra Swap alert trả về Tier 1 drop_caches."""
        alert = "⚠️ <b>Dung lượng Swap cao:</b> 750MB > 500MB (cảnh báo Disk Thrashing)"
        decision = self.service._decide_remediation(alert)

        self.assertIsNotNone(decision)
        self.assertEqual(decision["action_key"], "drop_caches")
        self.assertEqual(decision["tier"], 1)
        self.assertTrue(decision["auto_execute"])

    def test_decide_remediation_tier2_alert(self) -> None:
        """Kiểm tra container crash và SSL cert trả về Tier 2 với auto_execute=False."""
        # Container flapping / crash
        alert_container = "🚨 <b>Core Container gặp sự cố:</b>\n  <code>dashboard_db</code>: Exited (State: exited)"
        decision_container = self.service._decide_remediation(alert_container)

        self.assertIsNotNone(decision_container)
        self.assertEqual(decision_container["action_key"], "restart_container")
        self.assertEqual(decision_container["tier"], 2)
        self.assertFalse(decision_container["auto_execute"])

        # SSL cert expiry
        alert_ssl = "🔒 <b>SSL cert sắp hết hạn:</b>\n  <code>kirito.vn</code>: còn <b>5 ngày</b>"
        decision_ssl = self.service._decide_remediation(alert_ssl)

        self.assertIsNotNone(decision_ssl)
        self.assertEqual(decision_ssl["action_key"], "renew_ssl")
        self.assertEqual(decision_ssl["tier"], 2)
        self.assertFalse(decision_ssl["auto_execute"])

    def test_decide_remediation_unknown_or_benign_alert(self) -> None:
        """Kiểm tra alert không xác định hoặc rỗng trả về None."""
        self.assertIsNone(self.service._decide_remediation(""))
        self.assertIsNone(self.service._decide_remediation("   "))
        self.assertIsNone(self.service._decide_remediation("Hệ thống hoạt động bình thường"))

    def test_decide_remediation_dict_input(self) -> None:
        """Kiểm tra _decide_remediation hỗ trợ cấu trúc alert dạng dictionary."""
        dict_alert = {"message": "Ổ đĩa sắp đầy: 95% trên /"}
        decision = self.service._decide_remediation(dict_alert)
        self.assertIsNotNone(decision)
        self.assertEqual(decision["action_key"], "docker_prune")
        self.assertTrue(decision["auto_execute"])

    # ── 2. Cooldown Mechanism Tests ──────────────────────────────────────────

    async def test_remediation_cooldown_blocks_frequent_execution(self) -> None:
        """Kiểm tra cơ chế cooldown 30 phút (_REMEDIATION_COOLDOWN_SECONDS = 1800) chặn thực thi lặp lại."""
        remediation = {
            "action_key": "docker_prune",
            "tier": 1,
            "command": "docker system prune -f",
            "metric_type": "disk",
            "auto_execute": True,
            "description": "Tự động dọn rác Docker",
        }

        # Mock SSH responses for df before and after
        self.mock_ssh.run_command.side_effect = [
            "89% 4.1G 35G",          # before snapshot
            "Deleted Containers: ...", # prune command
            "73% 9.8G 35G",          # after snapshot
        ]

        # First execution should succeed
        res1 = await self.service._execute_remediation(remediation, "Disk alert 1")
        self.assertTrue(res1)
        self.assertIn("docker_prune", self.service._remediation_cooldowns)

        # Attempt immediate second execution (within 30 mins) -> must be blocked
        res2 = await self.service._execute_remediation(remediation, "Disk alert 2")
        self.assertFalse(res2)

        # Attempt execution at t = 15 minutes (900s < 1800s) -> must be blocked
        t_past = datetime.now(timezone.utc) - timedelta(seconds=900)
        self.service._remediation_cooldowns["docker_prune"] = t_past
        res3 = await self.service._execute_remediation(remediation, "Disk alert 3")
        self.assertFalse(res3)

    async def test_remediation_allowed_after_cooldown_expires(self) -> None:
        """Kiểm tra sau khi hết cooldown 30 phút (1801s), hành động được phép chạy lại."""
        remediation = {
            "action_key": "docker_prune",
            "tier": 1,
            "command": "docker system prune -f",
            "metric_type": "disk",
            "auto_execute": True,
            "description": "Tự động dọn rác Docker",
        }

        # Set last run time to 31 minutes ago (> 1800s)
        t_expired = datetime.now(timezone.utc) - timedelta(seconds=1801)
        self.service._remediation_cooldowns["docker_prune"] = t_expired

        self.mock_ssh.run_command.side_effect = [
            "90% 3.0G 35G",
            "Total reclaimed space: 5.2GB",
            "75% 8.2G 35G",
        ]

        res = await self.service._execute_remediation(remediation, "Disk alert after cooldown")
        self.assertTrue(res)

    async def test_remediation_cooldown_isolated_per_action(self) -> None:
        """Kiểm tra cooldown của action này không ảnh hưởng đến action khác."""
        # docker_prune is in cooldown
        self.service._remediation_cooldowns["docker_prune"] = datetime.now(timezone.utc)

        # drop_caches is a different action, should execute freely
        ram_remediation = {
            "action_key": "drop_caches",
            "tier": 1,
            "command": "sync && echo 3 > /proc/sys/vm/drop_caches",
            "metric_type": "ram",
            "auto_execute": True,
            "description": "Giải phóng bộ nhớ đệm RAM",
        }

        self.mock_ssh.run_command.side_effect = [
            "2900 300 3200",  # free -m before
            "",               # drop_caches command
            "1600 1600 3200", # free -m after
        ]

        res = await self.service._execute_remediation(ram_remediation, "RAM alert")
        self.assertTrue(res)
        self.assertIn("drop_caches", self.service._remediation_cooldowns)

    # ── 3. Full Flow: Before/After Metrics & Telegram Reporting ──────────────

    async def test_execute_remediation_full_flow_with_metrics_and_telegram(self) -> None:
        """Kiểm tra toàn bộ luồng: đo Before/After, chạy lệnh SSH, gửi Telegram và ghi nhận memory."""
        remediation = {
            "action_key": "docker_prune",
            "tier": 1,
            "command": "docker system prune -f",
            "metric_type": "disk",
            "auto_execute": True,
            "description": "Tự động dọn rác Docker (dangling images/containers)",
        }

        # Mock SSH calls in order: before metric, command, after metric
        self.mock_ssh.run_command.side_effect = [
            "88% 4.1G 35G",                 # df -h / before
            "Deleted Containers: ... 5.7G",  # docker system prune -f
            "73% 9.8G 35G",                 # df -h / after
        ]

        success = await self.service._execute_remediation(remediation, "Ổ đĩa sắp đầy 88%")
        self.assertTrue(success)

        # Verify SSH run_command called 3 times (before, prune, after)
        self.assertEqual(self.mock_ssh.run_command.call_count, 3)
        self.assertEqual(self.mock_ssh.run_command.call_args_list[1][0][0], "docker system prune -f")

        # Verify Telegram message dispatched
        self.mock_telegram.send_message.assert_called_once()
        target_chat_id, sent_msg = self.mock_telegram.send_message.call_args[0]
        self.assertEqual(target_chat_id, "test_chat_m3_123")
        self.assertIn("Tiểu Bảo Bảo — Tự động khắc phục sự cố", sent_msg)
        self.assertIn("docker system prune -f", sent_msg)
        self.assertIn("Trước khi xử lý", sent_msg)
        self.assertIn("Sau khi xử lý", sent_msg)
        self.assertIn("5.7GB", sent_msg)
        self.assertIn("Tier 1 Safe Action", sent_msg)

        # Allow background asyncio tasks to run and verify memory recording
        await asyncio.sleep(0.01)
        self.mock_memory.record_episode.assert_called_once()
        mem_kwargs = self.mock_memory.record_episode.call_args[1]
        self.assertIn("proactive_remediation", mem_kwargs["tags"])
        self.assertIn("docker_prune", mem_kwargs["tags"])

    async def test_execute_remediation_refuses_tier2_or_auto_execute_false(self) -> None:
        """Kiểm tra _execute_remediation từ chối thực thi khi tier >= 2 hoặc auto_execute=False."""
        tier2_remediation = {
            "action_key": "restart_container",
            "tier": 2,
            "command": "docker restart container_id",
            "metric_type": "container",
            "auto_execute": False,
            "description": "Khởi động lại container",
        }

        success = await self.service._execute_remediation(tier2_remediation, "Container flapping")
        self.assertFalse(success)
        # SSH command should not be executed
        self.mock_ssh.run_command.assert_not_called()
        self.mock_telegram.send_message.assert_not_called()

    # ── 4. Fault Tolerance & Graceful Handling ───────────────────────────────

    async def test_remediation_graceful_error_handling(self) -> None:
        """Kiểm tra khi SSH hoặc Telegram ném ngoại lệ, không làm sập tiến trình."""
        remediation = {
            "action_key": "docker_prune",
            "tier": 1,
            "command": "docker system prune -f",
            "metric_type": "disk",
            "auto_execute": True,
            "description": "Tự động dọn rác Docker",
        }

        # Scenario A: SSH command raises exception
        self.mock_ssh.run_command.side_effect = RuntimeError("SSH pipe disconnected")
        success_ssh_err = await self.service._execute_remediation(remediation, "Disk alert")
        self.assertFalse(success_ssh_err)

        # Scenario B: Telegram send_message raises exception
        self.mock_ssh.run_command.side_effect = [
            "85% 5G 35G",
            "Deleted ...",
            "80% 7G 35G",
        ]
        self.mock_telegram.send_message.side_effect = RuntimeError("Telegram API timeout 504")

        # Must not raise exception to the caller
        success_tg_err = await self.service._execute_remediation(remediation, "Disk alert")
        # Function catches exception and returns False cleanly
        self.assertFalse(success_tg_err)

    async def test_run_scan_cycle_triggers_remediation_for_tier1_only(self) -> None:
        """Kiểm tra _run_scan_cycle tự động thực thi Tier 1 và bỏ qua Tier 2 mà không crash."""
        # Mock checks to return 1 Tier 1 alert (disk) and 1 Tier 2 alert (container)
        disk_alert = "💽 <b>Ổ đĩa sắp đầy:</b>\n  <code>/</code>: 91%"
        container_alert = "🚨 <b>Core Container gặp sự cố:</b>\n  <code>dashboard_ai_agent</code>: exited"

        with patch.object(self.service, "_check_disk", AsyncMock(return_value=disk_alert)), \
             patch.object(self.service, "_check_memory", AsyncMock(return_value="")), \
             patch.object(self.service, "_check_ssl_certs", AsyncMock(return_value="")), \
             patch.object(self.service, "_check_oom_kills", AsyncMock(return_value="")), \
             patch.object(self.service, "_check_container_restarts", AsyncMock(return_value="")), \
             patch.object(self.service, "_check_cpu_load", AsyncMock(return_value="")), \
             patch.object(self.service, "_check_swap", AsyncMock(return_value="")), \
             patch.object(self.service, "_check_root_disk", AsyncMock(return_value="")), \
             patch.object(self.service, "_check_core_containers", AsyncMock(return_value=container_alert)), \
             patch.object(self.service, "_execute_remediation", AsyncMock(return_value=True)) as mock_exec:

            await self.service._run_scan_cycle()

            # Verify _execute_remediation was called ONLY ONCE for the disk alert (Tier 1)
            # and NOT for the container alert (Tier 2)
            self.assertEqual(mock_exec.call_count, 1)
            called_remediation = mock_exec.call_args[0][0]
            self.assertEqual(called_remediation["action_key"], "docker_prune")
            self.assertEqual(called_remediation["tier"], 1)

            # Telegram scan report message was still sent
            self.mock_telegram.send_message.assert_called()


if __name__ == "__main__":
    unittest.main()
