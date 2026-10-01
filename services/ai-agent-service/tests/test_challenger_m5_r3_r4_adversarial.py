"""
Test Suite: Tier 5 Adversarial Coverage Hardening for R3 (Proactive Remediation) & R4 (Conversational Goals).
Tác giả: Challenger 2 (Adversarial Empirical Challenger)
Đường dẫn: services/ai-agent-service/tests/test_challenger_m5_r3_r4_adversarial.py

Mục tiêu kiểm thử đối kháng (Empirical Stress Testing):
1. Bão cảnh báo dồn dập (Alert storm 100+ alerts) kiểm tra tính cách ly và độ chính xác của Cooldown 30 phút per-action.
2. Thử thách phân cấp Tri-Tier Risk Gating: Đảm bảo Tier 2/Tier 3 không bao giờ auto-execute dưới bất kỳ alert giả mạo nào.
3. Xung đột từ khóa Swap Thrashing vs Disk Space: Đảm bảo không nhầm lẫn giữa dọn dẹp đĩa và giải phóng ram/swap.
4. Bão intent đàm thoại (Conversational Token Budget Storm) với 10+ cụm công cụ, tiếng Việt không dấu, dấu câu phức tạp, câu lệnh > 200 ký tự.
5. Thẩm định tính trung thực của Fallback và khả năng chịu lỗi khi autonomous_goal_worker bị ngắt kết nối DB đột ngột.
"""

import asyncio
from datetime import datetime, timezone, timedelta
import unittest
from unittest.mock import AsyncMock, MagicMock

from app.services.proactive_service import (
    ProactiveIntelligenceService,
    _REMEDIATION_COOLDOWN_SECONDS,
)
from app.services.ai_agent_tools import (
    AgentToolExecutor,
    ACTION_TIER_1_SAFE,
    ACTION_TIER_2_REVERSIBLE,
    ACTION_TIER_3_LETHAL,
    classify_action_risk,
    classify_command_risk,
    evaluate_spinal_safety_veto,
)
from app.services.autonomous_goal_worker import (
    AutonomousGoalWorker,
    InMemoryTaskStore,
)


class TestAdversarialAlertStormAndCooldown(unittest.IsolatedAsyncioTestCase):
    """
    Kịch bản 1: Bão cảnh báo dồn dập (Alert Storm 100+ alerts)
    Kiểm tra tính cách ly và độ chính xác của Cooldown 30 phút per-action.
    """

    async def asyncSetUp(self) -> None:
        self.mock_ssh = MagicMock()
        self.mock_ssh.run_command = AsyncMock(return_value="80% 5.0G 30G")
        self.mock_memory = MagicMock()
        self.mock_memory.record_episode = AsyncMock()
        self.mock_memory.should_send_proactive_alert = AsyncMock(return_value=True)
        self.mock_memory.upsert_proactive_check = AsyncMock()
        self.mock_telegram = MagicMock()
        self.mock_telegram.chat_id = "test_chat_storm_999"
        self.mock_telegram.send_message = AsyncMock(return_value=True)

        self.service = ProactiveIntelligenceService(
            ssh_client=self.mock_ssh,
            memory_service=self.mock_memory,
            telegram_bot=self.mock_telegram,
            scan_interval=3600,
        )

    async def test_01_alert_storm_120_sequential_alerts_exact_single_execution(self) -> None:
        """
        Bão 120 cảnh báo liên tiếp về ổ đĩa trong 1 giây:
        Chỉ duy nhất lần đầu tiên được thực thi, 119 lần còn lại BẮT BUỘC bị chặn bởi Cooldown 30 phút.
        """
        remediation = {
            "action_key": "docker_prune",
            "tier": 1,
            "command": "docker system prune -f",
            "metric_type": "disk",
            "auto_execute": True,
            "description": "Tự động dọn rác Docker",
        }

        # Mock SSH responses cho before snapshot, command, after snapshot
        self.mock_ssh.run_command.side_effect = [
            "92% 2.0G 35G",       # Before metric
            "Total reclaimed: 4G", # Prune command
            "75% 8.0G 35G",       # After metric
        ] + ["80% 5.0G 30G"] * 500

        results = []
        for i in range(120):
            res = await self.service._execute_remediation(remediation, f"Disk alert storm index {i}")
            results.append(res)

        success_count = sum(1 for r in results if r is True)
        blocked_count = sum(1 for r in results if r is False)

        self.assertEqual(success_count, 1, "Chỉ duy nhất 1 lần thực thi thành công trong bão 120 alerts.")
        self.assertEqual(blocked_count, 119, "119 alerts còn lại phải bị chặn hoàn toàn bởi Cooldown.")
        self.assertIn("docker_prune", self.service._remediation_cooldowns)

    async def test_02_alert_storm_multi_action_strict_isolation(self) -> None:
        """
        Bão 150 alerts hỗn hợp giữa 3 loại Tier 1 (docker_prune, drop_caches, cleanup_logs):
        Đảm bảo tính cách ly per-action: Cooldown của docker_prune KHÔNG ĐƯỢC chặn drop_caches hay cleanup_logs.
        Mỗi loại action hợp lệ chỉ được thực thi đúng 1 lần.
        """
        actions = [
            {
                "action_key": "docker_prune",
                "tier": 1,
                "command": "docker system prune -f",
                "metric_type": "disk",
                "auto_execute": True,
                "description": "Dọn rác Docker",
            },
            {
                "action_key": "drop_caches",
                "tier": 1,
                "command": "sync && echo 3 > /proc/sys/vm/drop_caches",
                "metric_type": "ram",
                "auto_execute": True,
                "description": "Giải phóng RAM cache",
            },
            {
                "action_key": "cleanup_logs",
                "tier": 1,
                "command": "journalctl --vacuum-time=3d",
                "metric_type": "disk",
                "auto_execute": True,
                "description": "Dọn dẹp log hệ thống",
            },
        ]

        self.mock_ssh.run_command.return_value = "85% 4.0G 32G"
        results_by_action = {"docker_prune": 0, "drop_caches": 0, "cleanup_logs": 0}

        for i in range(150):
            act = actions[i % 3]
            res = await self.service._execute_remediation(act, f"Multi-storm alert #{i}")
            if res:
                results_by_action[act["action_key"]] += 1

        self.assertEqual(results_by_action["docker_prune"], 1, "docker_prune phải được thực thi chính xác 1 lần.")
        self.assertEqual(results_by_action["drop_caches"], 1, "drop_caches phải được thực thi chính xác 1 lần.")
        self.assertEqual(results_by_action["cleanup_logs"], 1, "cleanup_logs phải được thực thi chính xác 1 lần.")
        self.assertEqual(len(self.service._remediation_cooldowns), 3)

    async def test_03_cooldown_millisecond_boundary_precision(self) -> None:
        """
        Kiểm tra độ chính xác tuyệt đối ở ranh giới thời gian Cooldown 30 phút (1800 giây):
        - Tại t = 1799.5 giây (< 1800s): BẮT BUỘC bị chặn.
        - Tại t = 1800.5 giây (> 1800s): BẮT BUỘC được cho phép thực thi.
        """
        remediation = {
            "action_key": "docker_prune",
            "tier": 1,
            "command": "docker system prune -f",
            "metric_type": "disk",
            "auto_execute": True,
            "description": "Dọn rác Docker",
        }

        now = datetime.now(timezone.utc)
        self.service._remediation_cooldowns["docker_prune"] = now - timedelta(seconds=1799.5)

        res_blocked = await self.service._execute_remediation(remediation, "Test boundary blocked")
        self.assertFalse(res_blocked, "Tại t = 1799.5s, cooldown 1800s vẫn phải còn hiệu lực.")

        self.service._remediation_cooldowns["docker_prune"] = now - timedelta(seconds=1800.5)

        self.mock_ssh.run_command.side_effect = [
            "90% 2.5G 35G",
            "reclaimed 3G",
            "70% 8.5G 35G",
        ]
        res_allowed = await self.service._execute_remediation(remediation, "Test boundary allowed")
        self.assertTrue(res_allowed, "Tại t = 1800.5s, cooldown đã hết, hành động phải được thực thi.")

    async def test_04_alert_storm_with_ssh_or_telegram_failures_does_not_crash(self) -> None:
        """
        Kiểm tra độ bền bỉ khi xảy ra bão cảnh báo đồng thời SSH hoặc Telegram Bot ném lỗi mạng:
        _execute_remediation phải bắt trọn ngoại lệ (graceful error handling) và trả về False mà không làm sập tiến trình.
        """
        mock_broken_ssh = MagicMock()
        mock_broken_ssh.run_command.side_effect = ConnectionResetError("SSH socket closed unexpectedly")
        mock_broken_tg = MagicMock()
        mock_broken_tg.chat_id = "test_chat"
        mock_broken_tg.send_message.side_effect = TimeoutError("Telegram gateway timeout 504")

        service = ProactiveIntelligenceService(
            ssh_client=mock_broken_ssh,
            memory_service=MagicMock(),
            telegram_bot=mock_broken_tg,
        )

        remediation = {
            "action_key": "docker_prune",
            "tier": 1,
            "command": "docker system prune -f",
            "metric_type": "disk",
            "auto_execute": True,
        }

        for i in range(10):
            res = await service._execute_remediation(remediation, f"Broken network alert #{i}")
            self.assertFalse(res)


class TestAdversarialTriTierRiskGating(unittest.IsolatedAsyncioTestCase):
    """
    Kịch bản 2: Thử thách phân cấp Tri-Tier Risk Gating
    Đảm bảo các hành vi Tier 2 và Tier 3 không bao giờ bị auto-execute dưới bất kỳ dạng alert giả mạo nào.
    """

    async def asyncSetUp(self) -> None:
        self.mock_ssh = MagicMock()
        self.mock_ssh.run_command = AsyncMock(return_value="output")
        self.service = ProactiveIntelligenceService(
            ssh_client=self.mock_ssh,
            memory_service=MagicMock(),
            telegram_bot=MagicMock(),
        )

    async def test_05_tier2_and_tier3_remediation_never_auto_executed(self) -> None:
        """
        Đảm bảo nếu một cấu trúc remediation khai báo Tier 2, Tier 3 hoặc auto_execute=False,
        hàm _execute_remediation BẮT BUỘC từ chối thực thi và KHÔNG BAO GIỜ gọi lệnh SSH.
        """
        adversarial_payloads = [
            {
                "action_key": "restart_container",
                "tier": 2,
                "command": "docker restart dashboard_db",
                "auto_execute": False,
                "metric_type": "container",
            },
            {
                "action_key": "lethal_rm_rf",
                "tier": 3,
                "command": "rm -rf / --no-preserve-root",
                "auto_execute": True,
                "metric_type": "disk",
            },
            {
                "action_key": "fake_tier2_auto",
                "tier": 2,
                "command": "systemctl restart nginx",
                "auto_execute": True,
                "metric_type": "service",
            },
            {
                "action_key": "empty_command",
                "tier": 1,
                "command": "",
                "auto_execute": True,
                "metric_type": "disk",
            },
        ]

        for payload in adversarial_payloads:
            res = await self.service._execute_remediation(payload, "Adversarial Tri-Tier Spoof")
            self.assertFalse(
                res,
                f"Payload {payload.get('action_key')} thuộc Tier {payload.get('tier')} không được phép auto-execute!",
            )

        self.mock_ssh.run_command.assert_not_called()

    def test_06_decide_remediation_strict_tri_tier_classification(self) -> None:
        """
        Kiểm tra _decide_remediation phân loại nghiêm ngặt:
        - Alert liên quan container crash, restart flapping, ssl expiry -> BẮT BUỘC Tier 2, auto_execute=False.
        - Alert trống, rỗng hoặc benign -> None.
        """
        tier2_alerts = [
            "🚨 Core Container gặp sự cố: dashboard_db Exited (State: exited)",
            "Container dashboard_ai_agent đang restart bất thường 5 lần trong 1 giờ",
            "Cảnh báo crash dịch vụ container core",
            "🔒 SSL cert sắp hết hạn: kirito.vn còn 3 ngày",
            "chứng chỉ SSL certbot hết hạn cần renew",
        ]
        for alert in tier2_alerts:
            decision = self.service._decide_remediation(alert)
            self.assertIsNotNone(decision, f"Alert '{alert}' phải được nhận diện.")
            self.assertEqual(decision["tier"], 2, f"Alert '{alert}' phải được gắn nhãn Tier 2.")
            self.assertFalse(decision["auto_execute"], f"Tier 2 alert '{alert}' KHÔNG ĐƯỢC có auto_execute=True.")

        self.assertIsNone(self.service._decide_remediation(None))
        self.assertIsNone(self.service._decide_remediation(""))
        self.assertIsNone(self.service._decide_remediation("Mọi dịch vụ đều đang hoạt động tốt!"))

    def test_07_classify_action_risk_and_command_risk_lethal_gating(self) -> None:
        """
        Thẩm định Spinal Safety Veto và classify_command_risk trên các lệnh nguy hiểm:
        Tất cả các lệnh phá hoại, ghi đè phân vùng, xóa dữ liệu hàng loạt đều phải là ACTION_TIER_3_LETHAL.
        """
        lethal_commands = [
            "rm -rf /",
            "rm -rf /var/log/*",
            "mkfs.ext4 /dev/sda1",
            "dd if=/dev/zero of=/dev/sda",
            "DROP DATABASE production;",
            "TRUNCATE TABLE agent_tasks CASCADE;",
            "docker system prune -a --volumes -f",
            "chmod -R 777 /",
            ":(){ :|:& };:",
            "find / -delete",
        ]

        for cmd in lethal_commands:
            tier = classify_command_risk(cmd)
            self.assertEqual(
                tier,
                ACTION_TIER_3_LETHAL,
                f"Lệnh nguy hiểm '{cmd}' phải được phân loại ACTION_TIER_3_LETHAL.",
            )
            veto = evaluate_spinal_safety_veto(cmd)
            self.assertIsNotNone(veto, f"Lệnh '{cmd}' phải bị Spinal Safety Veto chặn đứng.")

    async def test_08_tier3_lethal_action_in_worker_transitions_to_waiting_approval(self) -> None:
        """
        Nếu một bước trong task là lệnh Tier 3 Lethal (ví dụ: rm -rf / hoặc DROP TABLE):
        Worker BẮT BUỘC chặn thực thi, KHÔNG gọi execute_tool, và chuyển task sang waiting_approval.
        """
        mock_executor = MagicMock()
        mock_executor.execute_tool = AsyncMock()
        mock_tg = MagicMock()
        mock_tg.send_message = AsyncMock(return_value=True)
        worker = AutonomousGoalWorker(
            tool_executor=mock_executor,
            telegram_bot=mock_tg,
            use_db=False,
        )

        task_record = {
            "id": "task_lethal_step_001",
            "goal": "Dọn dẹp hệ thống nhưng chứa mã độc",
            "steps": [
                {"step_id": 1, "tool": "run_command", "args": {"command": "rm -rf / --no-preserve-root"}, "status": "pending"},
            ],
            "current_step": 0,
            "status": "pending",
        }
        await worker._in_memory_store.insert(task_record)

        res = await worker.execute_pending_step(task_record)
        self.assertEqual(res["status"], "waiting_approval")
        self.assertEqual(res["steps"][0]["status"], "waiting_approval")
        self.assertIn("Tier 3 Lethal", res["error_message"])
        mock_executor.execute_tool.assert_not_called()


class TestSwapThrashingVsDiskSpaceDisambiguation(unittest.TestCase):
    """
    Kịch bản 3: Xung đột từ khóa Swap Thrashing vs Disk Space
    Xác thực không xảy ra nhầm lẫn giữa dọn dẹp đĩa (docker_prune) và giải phóng bộ nhớ swap (drop_caches)
    khi cảnh báo chứa từ khóa hỗn hợp.
    """

    def setUp(self) -> None:
        self.service = ProactiveIntelligenceService(
            ssh_client=MagicMock(),
            memory_service=MagicMock(),
            telegram_bot=MagicMock(),
        )

    def test_09_swap_thrashing_activates_drop_caches_not_docker_prune(self) -> None:
        """
        Alert chứa cả cụm từ 'Disk Thrashing' và 'Swap':
        BẮT BUỘC kích hoạt 'drop_caches' (giải phóng RAM/Swap, metric_type='ram'),
        TUYỆT ĐỐI KHÔNG ĐƯỢC nhầm sang 'docker_prune' (dọn dẹp đĩa).
        """
        swap_thrashing_alerts = [
            "⚠️ <b>Dung lượng Swap cao:</b> 750MB > 500MB (cảnh báo nguy cơ Disk Thrashing trên SSD)",
            "Cảnh báo: Swap quá tải 850MB dẫn đến Disk Thrashing làm chậm ổ đĩa",
            "Disk Thrashing phát hiện trên hệ thống do thiếu hụt bộ nhớ Swap và RAM",
            "canh bao swap cao gay nguy co disk thrashing tren o dia ssd",
            "Bộ nhớ Swap đạt đỉnh 900MB gây nghẽn đĩa Disk Thrashing",
        ]

        for alert in swap_thrashing_alerts:
            decision = self.service._decide_remediation(alert)
            self.assertIsNotNone(decision, f"Cảnh báo '{alert}' phải được phân tích.")
            self.assertEqual(
                decision["action_key"],
                "drop_caches",
                f"Alert '{alert}' chứa Swap/RAM phải giải phóng bộ nhớ (drop_caches), không phải dọn đĩa!",
            )
            self.assertEqual(
                decision["metric_type"],
                "ram",
                f"Metric type phải là 'ram', nhận được: {decision.get('metric_type')}",
            )
            self.assertEqual(
                decision["command"],
                "sync && echo 3 > /proc/sys/vm/drop_caches",
            )
            self.assertTrue(decision["auto_execute"])

    def test_10_pure_disk_and_root_partition_triggers_docker_prune(self) -> None:
        """
        Cảnh báo thuần về ổ đĩa hoặc phân vùng root chứa từ khóa chuẩn ('đĩa', 'disk', 'root (/)', 'phân vùng root'):
        BẮT BUỘC chọn 'docker_prune' (metric_type='disk').
        Cảnh báo dùng phương ngữ khác ('ổ cứng') không khớp từ khóa vi mạch -> An toàn trả về None.
        """
        pure_disk_alerts = [
            "💽 Ổ đĩa sắp đầy: <code>/dev/sda1</code>: 91%",
            "💽 Phân vùng root (/) sắp đầy: 94% (ngưỡng an toàn < 90%, nguy cơ crash dịch vụ)",
            "Dung lượng đĩa phân vùng root đang ở mức báo động 95%",
            "Ổ đĩa ssd /dev/nvme0n1 hết dung lượng trống",
            "Disk usage on /data exceeds 90%",
        ]

        for alert in pure_disk_alerts:
            decision = self.service._decide_remediation(alert)
            self.assertIsNotNone(decision, f"Cảnh báo '{alert}' phải được nhận diện.")
            self.assertEqual(
                decision["action_key"],
                "docker_prune",
                f"Alert '{alert}' phải kích hoạt docker_prune.",
            )
            self.assertEqual(decision["metric_type"], "disk")
            self.assertEqual(decision["command"], "docker system prune -f")
            self.assertTrue(decision["auto_execute"])

        unmatched_alert = "Ổ cứng ssd /dev/nvme0n1 hết dung lượng trống"
        self.assertIsNone(
            self.service._decide_remediation(unmatched_alert),
            "Alert không chứa 'đĩa'/'disk'/'root' an toàn trả về None, không kích hoạt bừa bãi.",
        )

    def test_11_log_buildup_prioritizes_cleanup_logs_over_disk_prune(self) -> None:
        """
        Cảnh báo log tích tụ quá lớn trên ổ đĩa:
        BẮT BUỘC ưu tiên chọn 'cleanup_logs' (journalctl --vacuum-time=3d) thay vì docker_prune.
        """
        log_alerts = [
            "⚠️ Cảnh báo: log tích tụ quá lớn làm đầy dung lượng ổ đĩa",
            "Nhật ký hệ thống journalctl phình to, cần dọn log ngay",
            "cleanup_logs: phân vùng /var/log vượt ngưỡng dung lượng",
            "log tích tụ chiếm dụng 15GB trên phân vùng root",
        ]

        for alert in log_alerts:
            decision = self.service._decide_remediation(alert)
            self.assertIsNotNone(decision)
            self.assertEqual(
                decision["action_key"],
                "cleanup_logs",
                f"Alert '{alert}' phải ưu tiên cleanup_logs.",
            )
            self.assertEqual(decision["command"], "journalctl --vacuum-time=3d")
            self.assertTrue(decision["auto_execute"])

    def test_12_swap_and_disk_simultaneous_in_alert_prioritizes_swap_memory(self) -> None:
        """
        Kịch bản đối kháng gay gắt: Alert cố tình chứa cả hai từ khóa Swap và Đĩa:
        'Cảnh báo: bộ nhớ swap cao 850MB và phân vùng đĩa / sắp đầy 92%'
        Do ram/swap được kiểm tra trước đĩa, hệ thống ưu tiên drop_caches để cứu nguy khẩn cấp cho memory.
        """
        dual_alert = "Cảnh báo khẩn: dung lượng bộ nhớ swap cao 850MB và phân vùng đĩa / sắp đầy 92%"
        decision = self.service._decide_remediation(dual_alert)

        self.assertIsNotNone(decision)
        self.assertEqual(
            decision["action_key"],
            "drop_caches",
            "Khi cả swap và đĩa cùng xuất hiện, vi mạch ưu tiên drop_caches để ngăn chặn crash memory.",
        )
        self.assertEqual(decision["metric_type"], "ram")
        self.assertTrue(decision["auto_execute"])


class TestConversationalTokenBudgetStorm(unittest.TestCase):
    """
    Kịch bản 4: Bão intent đàm thoại (Conversational Token Budget Storm)
    Kiểm tra dynamic scoping với 10+ cụm công cụ kết hợp từ khóa tiếng Việt không dấu,
    dấu câu phức tạp, câu lệnh dài > 200 ký tự, đảm bảo token budget luôn <= 8 tools.
    """

    def setUp(self) -> None:
        mock_ssh = MagicMock()
        mock_cache = MagicMock()
        self.executor = AgentToolExecutor(ssh_client=mock_ssh, message_cache=mock_cache)

    def test_13_mega_storm_prompt_10_clusters_capped_at_budget(self) -> None:
        """
        Prompt dồn dập > 250 ký tự kích hoạt đồng thời 10+ intent:
        Server, RAM, Docker, Video Download, Audio MP3, Archive Zip, File Manager, Email, Weather, Autonomous Goals.
        BẢO ĐẢM TUYỆT ĐỐI:
        1. Token Budget Invariant: len(scoped_tools) <= 6 (vì chứa Archive là heavy cluster).
        2. Specialized Intent Priority: Các công cụ mục tiêu tự hành và tác vụ chuyên biệt được ưu tiên giữ lại.
        """
        mega_query = (
            "Tiểu Bảo Bảo ơi! Em hãy kiểm tra cpu, ram, swap, ổ đĩa /dev/sda1, rồi mở docker xem container "
            "dashboard_db có đang chạy không??? Sau đó tải video https://youtube.com/watch?v=adversarial_123 "
            "và tách nhạc mp3 lưu vào thư mục /data/music! Đồng thời nén file zip gửi email báo cáo sang "
            "admin@server.com, rồi lập kế hoạch đặt mục tiêu tự hành theo dõi thời tiết Đà Nẵng hôm nay thế nào?!"
        )
        self.assertGreater(len(mega_query), 250)

        scoped = self.executor._resolve_scoped_tool_names(query=mega_query)

        self.assertLessEqual(
            len(scoped),
            6,
            f"Bão 10+ cụm công cụ có heavy cluster phải siết trần <= 6: len={len(scoped)}, tools={scoped}",
        )
        self.assertGreaterEqual(len(scoped), 2, f"Số lượng tools quá ít: len={len(scoped)}")
        self.assertTrue(
            any(t in scoped for t in ("create_autonomous_goal", "list_autonomous_goals", "cancel_autonomous_goal")),
            "Autonomous goal tools phải được ưu tiên khi người dùng yêu cầu lập kế hoạch mục tiêu.",
        )

    def test_14_unaccented_vietnamese_extreme_query_preserves_budget(self) -> None:
        """
        Prompt tiếng Việt không dấu, viết tắt, ký tự đặc biệt lộn xộn (> 200 ký tự):
        Kiểm tra hệ thống nhận diện từ khóa và duy trì Token Budget nghiêm ngặt (<= 8 tools, hoặc <= 6 tools).
        """
        unaccented_query = (
            "kiem tra suc khoe may chu, xem ram o dia, chay script python, doc file log, "
            "dat muc tieu tu dong theo doi tien trinh server; neu ram > 90% thi tu dong giai phong; "
            "dong thoi xem lich nhac va gui email bao cao tong hop cho anh nhanh len nhe... &*#$@!?"
        )
        self.assertGreater(len(unaccented_query), 200)

        scoped = self.executor._resolve_scoped_tool_names(query=unaccented_query)

        self.assertLessEqual(
            len(scoped),
            8,
            f"Token budget bị phá vỡ trên query không dấu: len={len(scoped)}",
        )
        self.assertIn("create_autonomous_goal", scoped)
        self.assertIn("execute_system_script", scoped)

    def test_15_heavy_cluster_enforces_max_6_tools_limit(self) -> None:
        """
        Khi kích hoạt heavy cluster (Facebook, Archive giải nén mật khẩu, Media Studio):
        Priority Pruning BẮT BUỘC siết chặt trần token xuống max_tools = 6 (chống HTTP 413 TPM).
        """
        heavy_query = (
            "Giải nén file bí mật encrypted_archive.zip bằng mật khẩu kirito2026, "
            "sau đó kiểm tra tin nhắn inbox Facebook và cắt video clip này giúp anh!"
        )
        scoped = self.executor._resolve_scoped_tool_names(query=heavy_query)

        self.assertLessEqual(
            len(scoped),
            6,
            f"Heavy cluster phải bị giới hạn nghiêm ngặt <= 6 tools, nhận được: {len(scoped)} ({scoped})",
        )

    def test_16_autonomous_goal_intents_correctly_prioritized(self) -> None:
        """
        Các câu lệnh đàm thoại quản trị mục tiêu tự hành (R4):
        - Tạo goal: BẮT BUỘC có create_autonomous_goal
        - Danh sách goal: BẮT BUỘC có list_autonomous_goals
        - Hủy goal: BẮT BUỘC có cancel_autonomous_goal
        Tất cả đều tuân thủ len(scoped) <= 8.
        """
        test_cases = [
            ("Lập kế hoạch tự động theo dõi ram và cpu máy chủ", "create_autonomous_goal"),
            ("Xem danh sách các mục tiêu tự động đang chạy", "list_autonomous_goals"),
            ("Hủy mục tiêu task_12345 không cần chạy nữa", "cancel_autonomous_goal"),
            ("dang theo doi nhung gi tren may chu the em", "list_autonomous_goals"),
            ("xoa task tu dong task_abcdef", "cancel_autonomous_goal"),
        ]

        for query, expected_tool in test_cases:
            scoped = self.executor._resolve_scoped_tool_names(query=query)
            self.assertIn(
                expected_tool,
                scoped,
                f"Query '{query}' phải chọn công cụ '{expected_tool}'. Scoped: {scoped}",
            )
            self.assertLessEqual(
                len(scoped),
                8,
                f"Query '{query}' vượt quá Token Budget <= 8: len={len(scoped)}",
            )

    def test_17_massive_prompt_1000_chars_token_budget_strictly_bounded(self) -> None:
        """
        Kiểm tra độ co giãn và khả năng chống tràn bộ nhớ với prompt siêu dài 1000+ ký tự:
        Token budget vẫn giữ nghiêm ngặt <= 8 tools, không ném exception.
        """
        massive_prompt = (
            "Tiểu Bảo Bảo hãy hỗ trợ anh kiểm tra toàn diện hệ thống: " +
            "kiểm tra ram cpu swap đĩa docker service nginx " * 25 +
            "và đồng thời lập kế hoạch đặt mục tiêu tự động theo dõi máy chủ " +
            "sau đó tải video https://youtube.com/watch?v=massive_123 và gửi email báo cáo!"
        )
        self.assertGreater(len(massive_prompt), 1000)

        scoped = self.executor._resolve_scoped_tool_names(query=massive_prompt)
        self.assertLessEqual(len(scoped), 8, f"Prompt 1000+ ký tự vượt quá Token Budget: len={len(scoped)}")
        self.assertGreaterEqual(len(scoped), 2)


class TestAutonomousGoalWorkerDbDisconnectionFallback(unittest.IsolatedAsyncioTestCase):
    """
    Kịch bản 5: Thẩm định tính trung thực của Fallback và khả năng chịu lỗi
    khi autonomous_goal_worker bị ngắt kết nối DB đột ngột.
    """

    async def asyncSetUp(self) -> None:
        self.mock_tool_executor = MagicMock()
        self.mock_tool_executor.execute_tool = AsyncMock(return_value="Command succeeded")
        self.mock_telegram = MagicMock()
        self.mock_telegram.send_message = AsyncMock(return_value=True)

    async def test_18_create_goal_graceful_fallback_when_db_fails_on_write(self) -> None:
        """
        Worker được khởi tạo với use_db=True nhưng PostgreSQL bị mất kết nối đột ngột (ConnectionRefusedError):
        Worker BẮT BUỘC tự động chuyển đổi sang InMemoryTaskStore mà KHÔNG crash,
        trả về task_id hợp lệ và dữ liệu task được lưu trữ toàn vẹn trong bộ nhớ.
        """
        failing_pool = MagicMock()
        failing_pool.connection.side_effect = ConnectionRefusedError("Could not connect to PostgreSQL server: Port 5432 down")

        worker = AutonomousGoalWorker(
            tool_executor=self.mock_tool_executor,
            telegram_bot=self.mock_telegram,
            pool=failing_pool,
            use_db=True,
        )

        task_id = await worker.create_goal(
            goal="Theo dõi dung lượng ổ đĩa khi DB sập",
            steps=[{"step_id": 1, "tool": "run_command", "args": {"command": "df -h"}}],
            chat_id="test_chat_fallback",
        )

        self.assertIsNotNone(task_id)
        self.assertTrue(task_id.startswith("task_"))
        self.assertFalse(worker.use_db, "Worker phải tự chuyển use_db sang False khi DB ném Exception.")

        task = await worker.get_goal_status(task_id)
        self.assertIsNotNone(task)
        self.assertEqual(task["id"], task_id)
        self.assertEqual(task["goal"], "Theo dõi dung lượng ổ đĩa khi DB sập")
        self.assertEqual(task["status"], "pending")
        self.assertEqual(len(task["steps"]), 1)

    async def test_19_step_execution_survives_midflight_db_crash(self) -> None:
        """
        Đang thực thi các bước của task thì DB bị ngắt kết nối (OperationalError):
        Worker không bị gián đoạn, ghi nhận kết quả vào InMemoryTaskStore và hoàn tất task bình thường.
        """
        failing_pool = MagicMock()
        failing_pool.connection.side_effect = RuntimeError("SSL SYSCALL error: EOF detected - DB pool lost connection")

        worker = AutonomousGoalWorker(
            tool_executor=self.mock_tool_executor,
            telegram_bot=self.mock_telegram,
            pool=failing_pool,
            use_db=True,
        )

        task_record = {
            "id": "task_midflight_crash_001",
            "goal": "Kiểm tra bộ nhớ RAM và swap",
            "steps": [
                {"step_id": 1, "tool": "run_command", "args": {"command": "free -m"}, "status": "pending"},
                {"step_id": 2, "tool": "run_command", "args": {"command": "uptime"}, "status": "pending"},
            ],
            "current_step": 0,
            "status": "pending",
            "retry_count": 0,
            "max_retries": 3,
        }
        await worker._in_memory_store.insert(task_record)

        res_step1 = await worker.execute_pending_step(task_record)
        self.assertEqual(res_step1["current_step"], 1)
        self.assertEqual(res_step1["status"], "running")
        self.assertEqual(res_step1["steps"][0]["status"], "completed")

        res_step2 = await worker.execute_pending_step(res_step1)
        self.assertEqual(res_step2["current_step"], 2)
        self.assertEqual(res_step2["status"], "completed")
        self.assertEqual(res_step2["steps"][1]["status"], "completed")
        self.assertIsNotNone(res_step2["completed_at"])

    async def test_20_status_protection_preserved_in_memory_store_under_failure(self) -> None:
        """
        Xác thực tính bất biến của trạng thái cuối (Status Protection Invariant):
        Khi task đã chuyển sang trạng thái kết thúc (completed, cancelled, failed, waiting_approval),
        mọi thao tác ghi đè vô ý không được phép hạ cấp status trở lại 'pending' hay 'running'.
        """
        store = InMemoryTaskStore()

        task = {
            "id": "task_protect_01",
            "goal": "Goal hoàn tất",
            "status": "completed",
            "completed_at": "2026-10-01T16:00:00Z",
            "error_message": None,
        }
        await store.insert(task)

        await store.update({
            "id": "task_protect_01",
            "goal": "Goal hoàn tất",
            "status": "running",
        })
        persisted = await store.get("task_protect_01")
        self.assertEqual(persisted["status"], "completed", "Trạng thái 'completed' không được phép bị đổi thành 'running'.")

        task_cancel = {
            "id": "task_protect_02",
            "goal": "Goal bị hủy",
            "status": "cancelled",
            "error_message": "User cancelled",
        }
        await store.insert(task_cancel)

        await store.update({
            "id": "task_protect_02",
            "goal": "Goal bị hủy",
            "status": "running",
        })
        persisted_cancel = await store.get("task_protect_02")
        self.assertEqual(persisted_cancel["status"], "cancelled", "Trạng thái 'cancelled' không được phép bị đổi thành 'running'.")

    async def test_21_concurrent_goal_operations_under_db_catastrophe(self) -> None:
        """
        25 tác vụ tạo và truy vấn mục tiêu đồng thời trong khi kết nối DB bị đứt gãy liên tục:
        Toàn bộ 25 mục tiêu phải được tạo thành công trên fallback store mà không có unhandled exception nào.
        """
        broken_pool = MagicMock()
        broken_pool.connection.side_effect = TimeoutError("PostgreSQL connection pool timed out after 30000ms")

        worker = AutonomousGoalWorker(
            tool_executor=self.mock_tool_executor,
            telegram_bot=self.mock_telegram,
            pool=broken_pool,
            use_db=True,
        )

        async def _create_single_goal(idx: int) -> str:
            return await worker.create_goal(
                goal=f"Mục tiêu đồng thời số #{idx} trong thảm họa DB",
                steps=[{"step_id": 1, "tool": "get_system_health_report", "args": {}}],
            )

        task_ids = await asyncio.gather(*[_create_single_goal(i) for i in range(25)])

        self.assertEqual(len(task_ids), 25)
        self.assertEqual(len(set(task_ids)), 25, "Tất cả 25 task_ids phải là duy nhất.")

        goals_list = await worker.list_goals(limit=50)
        self.assertGreaterEqual(len(goals_list), 25)

    async def test_22_cancel_goal_fallback_under_db_failure(self) -> None:
        """
        Thao tác cancel_goal hoạt động chính xác và bảo toàn trạng thái khi DB gặp sự cố.
        """
        broken_pool = MagicMock()
        broken_pool.connection.side_effect = ConnectionResetError("Connection lost")

        worker = AutonomousGoalWorker(
            tool_executor=self.mock_tool_executor,
            telegram_bot=self.mock_telegram,
            pool=broken_pool,
            use_db=True,
        )

        task_id = await worker.create_goal("Goal to cancel", steps=[{"step_id": 1, "tool": "get_system_health_report"}])
        self.assertIsNotNone(task_id)

        cancelled = await worker.cancel_goal(task_id, reason="Challenger test cancellation")
        self.assertTrue(cancelled)

        status = await worker.get_goal_status(task_id)
        self.assertEqual(status["status"], "cancelled")
        self.assertEqual(status["error_message"], "Challenger test cancellation")

        cancelled_again = await worker.cancel_goal(task_id)
        self.assertFalse(cancelled_again)


if __name__ == "__main__":
    unittest.main()
