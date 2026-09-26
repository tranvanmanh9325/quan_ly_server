"""
test_challenger_m5_1_adversarial.py — Empirical Adversarial Stress-Testing Suite for Milestone M5.

Author: Challenger 1 (Adversarial Empirical Challenger)
Scope:
1. Dynamic Tool Scoping Stress-Testing:
   - 48 hostile/adversarial queries (Compound intents, homonyms, empty, 500+ chars, unaccented, special chars, injections).
   - Invariant: 100% len(scoped_tools) <= 8 (and <= 6 when heavy cluster is activated). NEVER > 8.
   - Semantic verification: Disambiguation between "đổi tên file" vs "đổi 100 USD sang VND", etc.
2. Tri-Tier Action Risk Gating & Spinal Safety Veto:
   - 35+ lethal commands (rm -rf /, mkfs, DROP DATABASE, fork bomb, disk zeroing, docker prune).
   - 100% blocked without token; unblocked ONLY with CONFIRM_DANGEROUS_ACTION.
   - Tier 2 Operational Confirmation Token Verification:
     - restart_service requires confirm='RESTART_CONFIRMED' for production services.
     - restart_ngrok_tunnel requires confirm='RESTART_CONFIRMED'.
     - delete_cron_job requires confirm='DELETE_CONFIRMED'.
   - Tier classification consistency for all 27 new tools + bash commands.
"""

import asyncio
import json
import re
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.ai_agent_tools import (
    AgentToolExecutor,
    ACTION_TIER_1_SAFE,
    ACTION_TIER_2_REVERSIBLE,
    ACTION_TIER_3_LETHAL,
    classify_action_risk,
    classify_command_risk,
    evaluate_spinal_safety_veto,
)


def _create_mock_executor() -> AgentToolExecutor:
    mock_ssh = MagicMock()
    mock_ssh.execute_command = AsyncMock(return_value="mock ssh output")
    mock_cache = MagicMock()
    mock_telegram = MagicMock()
    mock_telegram.send_message = AsyncMock(return_value=True)
    return AgentToolExecutor(ssh_client=mock_ssh, message_cache=mock_cache, telegram_bot=mock_telegram)


class TestDynamicToolScopingAdversarial(unittest.TestCase):
    """
    Adversarial stress-testing suite for Dynamic Tool Scoping.
    Tests 48 complex, edge-case, and hostile queries against hard invariants.
    """

    ADVERSARIAL_QUERIES = [
        # --- Group 1: Multi-intent compound queries (>= 2 intents) ---
        {
            "id": "Q01_multi_health_email",
            "query": "kiểm tra sức khỏe server rồi gửi email báo cáo cho admin",
            "must_contain": {"get_system_health_report", "send_email"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q02_multi_calc_note_remind",
            "query": "tính 15% của 2 tỷ rồi ghi chú lại vào sổ tay và hẹn giờ nhắc lúc 18h",
            "must_contain": {"calculate", "create_note", "schedule_reminder"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q03_multi_tiktok_transfer",
            "query": "tải video tiktok https://vt.tiktok.com/abc123xyz rồi chuyển sang điện thoại",
            "must_contain": {"download_media_video", "create_file_transfer_portal"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q04_multi_log_restart",
            "query": "xem log docker rồi khởi động lại service dashboard_ai_agent nếu có lỗi",
            "must_contain": {"tail_service_logs", "restart_service"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q05_multi_read_file_disk",
            "query": "đọc file /home/kirito/app.py và kiểm tra dung lượng ổ đĩa xem cái nào nặng nhất",
            "must_contain": {"read_file_content", "get_disk_usage"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q06_multi_cron_email",
            "query": "tạo cron job backup db rồi gửi email thông báo cho sếp",
            "must_contain": {"create_cron_job", "send_email"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q07_multi_ngrok_netinfo",
            "query": "lấy link ngrok hiện tại và kiểm tra thông tin mạng IP công khai",
            "must_contain": {"get_ngrok_status", "get_network_info"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q08_multi_notes_archive_heavy",
            "query": "tìm ghi chú và giải nén backup.tar.gz",
            "must_contain": {"search_notes", "read_archive_file"},
            "must_not_exceed": 6,  # Heavy cluster: archive activated -> strict bound 6
        },
        {
            "id": "Q09_multi_fb_weather_heavy",
            "query": "facebook tin nhắn mới và thời tiết hôm nay thế nào",
            "must_contain": {"facebook_get_messages", "get_weather"},
            "must_not_exceed": 6,  # Heavy cluster: facebook activated -> strict bound 6
        },
        {
            "id": "Q10_multi_server_notes_cron",
            "query": "tình trạng máy chủ thế nào, ghi chú lại rồi lên lịch cron chạy tự động hàng ngày",
            "must_contain": {"get_system_health_report", "create_cron_job"},
            "must_not_exceed": 8,
        },

        # --- Group 2: Homonym collisions & semantic disambiguation ---
        {
            "id": "Q11_homonym_rename_file",
            "query": "đổi tên file config.json thành settings.json",
            "must_contain": {"move_or_rename_file"},
            "must_not_contain": {"convert_units"},  # File rename MUST NOT trigger calculator convert_units
            "must_not_exceed": 8,
        },
        {
            "id": "Q12_homonym_currency_convert",
            "query": "đổi 100 USD sang VND",
            "must_contain": {"convert_units"},
            "must_not_contain": {"move_or_rename_file"},  # Currency conversion MUST NOT trigger file manager
            "must_not_exceed": 8,
        },
        {
            "id": "Q13_homonym_weight_convert",
            "query": "đổi 50kg sang lbs",
            "must_contain": {"convert_units"},
            "must_not_contain": {"move_or_rename_file"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q14_homonym_temp_convert",
            "query": "đổi 100 độ F sang độ C",
            "must_contain": {"convert_units"},
            "must_not_contain": {"move_or_rename_file"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q15_homonym_move_file",
            "query": "move file /home/kirito/data.csv to /tmp/backup/",
            "must_contain": {"move_or_rename_file"},
            "must_not_contain": {"convert_units"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q16_homonym_calc_math",
            "query": "tính lãi suất 500 triệu gửi 12 tháng với lãi 7% một năm",
            "must_contain": {"calculate"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q17_homonym_tinh_colloquial",
            "query": "tính ngày mai đi chơi mà chưa biết thời tiết thế nào hè",
            "must_contain": {"get_weather"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q18_homonym_note_colloquial",
            "query": "note này hay đấy, lưu lại vào sổ tay giùm anh",
            "must_contain": {"create_note"},
            "must_not_exceed": 8,
        },

        # --- Group 3: Empty, Whitespace & Extreme lengths ---
        {
            "id": "Q19_empty_string",
            "query": "",
            "must_contain": {"run_command", "get_system_health_report"},  # Fallback to core
            "must_not_exceed": 8,
        },
        {
            "id": "Q20_whitespace_only",
            "query": "    \t\n   \r\n   ",
            "must_contain": {"run_command"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q21_long_500_chars",
            "query": "kiểm tra sức khỏe server " + ("chi tiết " * 50) + "xem có vấn đề gì về CPU và RAM không em ơi",
            "must_contain": {"get_system_health_report"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q22_long_repeated_keywords",
            "query": "ghi chú ghi chú note note nhắc nhở đặt lịch email báo cáo cron tự động tính toán chuyển đổi " * 5,
            "must_contain": set(),
            "must_not_exceed": 8,
        },

        # --- Group 4: Unaccented Vietnamese (Tiếng Việt không dấu) ---
        {
            "id": "Q23_unaccented_health_email",
            "query": "kiem tra suc khoe server roi gui email bao cao",
            "must_contain": {"get_system_health_report", "send_email"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q24_unaccented_rename_file",
            "query": "doi ten file config.json thanh settings.json",
            "must_contain": {"move_or_rename_file"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q25_unaccented_convert_currency",
            "query": "doi 100 usd sang vnd",
            "must_contain": {"convert_units"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q26_unaccented_reminder",
            "query": "dat lich nhac anh uong nuoc luc 10h",
            "must_contain": {"schedule_reminder"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q27_unaccented_notes",
            "query": "ghi chu lai mat khau wifi nha la 12345678",
            "must_contain": {"create_note"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q28_unaccented_cron",
            "query": "tao cron job backup luc 2h sang",
            "must_contain": {"create_cron_job"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q29_unaccented_ngrok",
            "query": "xem link ngrok hien tai",
            "must_contain": {"get_ngrok_status"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q30_unaccented_file_read",
            "query": "doc file /home/kirito/test.txt",
            "must_contain": {"read_file_content"},
            "must_not_exceed": 8,
        },

        # --- Group 5: Special characters & Injection strings ---
        {
            "id": "Q31_injection_semicolon_rm",
            "query": "; rm -rf /; echo hack",
            "must_contain": {"run_command"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q32_injection_pipes_and_top",
            "query": "kiểm tra server & top | grep python; ls -la /home/kirito",
            "must_contain": {"run_command"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q33_xss_with_math",
            "query": "<script>alert('xss')</script> tính 15 * 30 + 100",
            "must_contain": {"calculate"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q34_command_substitution_sql",
            "query": "calc: $(whoami) `id` || drop table users; query database SELECT 1",
            "must_contain": {"query_database"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q35_raw_json_input",
            "query": "ghi chú nội dung JSON: {\"key\": \"value\", \"nested\": [1,2,3]}",
            "must_contain": {"create_note"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q36_special_punctuation_blast",
            "query": "!@#$%^&*()_+{}[]:\"<>?~`-=\\|/ kiểm tra sức khỏe server",
            "must_contain": {"get_system_health_report"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q37_emoji_bomb",
            "query": "🚀🔥💻📊⚡🛠️🧠 kiểm tra server giúp anh với nha",
            "must_contain": {"run_command"},
            "must_not_exceed": 8,
        },

        # --- Group 6: Dialect, Slang & Regional queries ---
        {
            "id": "Q38_dialect_nghe_an_health",
            "query": "bựa ni máy chủ răng e, có đầy đĩa k",
            "must_contain": {"get_system_health_report"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q39_dialect_vinh_weather",
            "query": "thời tiết vinh bựa ni răng hè",
            "must_contain": {"get_weather"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q40_slang_ban_file",
            "query": "bắn file sang điện thoại hộ tao cái",
            "must_contain": {"create_file_transfer_portal"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q41_slang_keo_video",
            "query": "kéo video youtube này về https://youtu.be/test1234",
            "must_contain": {"download_media_video"},
            "must_not_exceed": 8,
        },

        # --- Group 7: Heavy Clusters & Strict <= 6 Bounds ---
        {
            "id": "Q42_heavy_archive_pure",
            "query": "giải nén backup.tar.gz",
            "must_contain": {"extract_archive_file"},
            "must_not_exceed": 6,  # Heavy cluster triggered: strict limit 6
        },
        {
            "id": "Q43_heavy_facebook_pure",
            "query": "xem tin nhắn facebook và gửi trả lời tin nhắn cho khách",
            "must_contain": {"facebook_get_messages", "facebook_send_reply"},
            "must_not_exceed": 6,  # Heavy cluster triggered: strict limit 6
        },
        {
            "id": "Q44_heavy_archive_password",
            "query": "bẻ khóa khôi phục mật khẩu zip secret.zip",
            "must_contain": {"recover_archive_password"},
            "must_not_exceed": 6,  # Heavy cluster triggered: strict limit 6
        },

        # --- Group 8: SQL queries & Math complex expressions ---
        {
            "id": "Q45_sql_explain",
            "query": "truy vấn sql EXPLAIN ANALYZE SELECT * FROM users WHERE active = true",
            "must_contain": {"query_database"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q46_math_expression_scientific",
            "query": "tính sqrt(256) + sin(0.5) * exp(2)",
            "must_contain": {"calculate"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q47_disk_usage_specific_path",
            "query": "kiểm tra dung lượng thư mục /home/kirito/quan_ly_server xem file nào nặng nhất",
            "must_contain": {"get_disk_usage"},
            "must_not_exceed": 8,
        },
        {
            "id": "Q48_write_file_safe_dir",
            "query": "ghi file /tmp/hello.txt nội dung Hello World",
            "must_contain": {"write_file_content"},
            "must_not_exceed": 8,
        },
    ]

    def setUp(self):
        self.executor = _create_mock_executor()

    def test_dynamic_scoping_hard_ceiling_and_semantic_preservation(self):
        """
        Tests that 100% of 48 adversarial queries:
        1. Produce len(scoped_tools) <= 8 (and <= 6 when heavy cluster is active).
        2. Produce len(scoped_tools) >= 1.
        3. Strictly contain the expected semantic tools.
        4. Do NOT contain prohibited homonym false-positive tools.
        """
        for item in self.ADVERSARIAL_QUERIES:
            q_id = item["id"]
            query = item["query"]
            must_contain = item.get("must_contain", set())
            must_not_contain = item.get("must_not_contain", set())
            must_not_exceed = item.get("must_not_exceed", 8)

            with self.subTest(query_id=q_id, query=query[:40]):
                scoped_tools = self.executor._resolve_scoped_tool_names(query=query)

                # Hard ceiling invariant
                self.assertLessEqual(
                    len(scoped_tools),
                    must_not_exceed,
                    f"[{q_id}] Query produced {len(scoped_tools)} tools, exceeding limit of {must_not_exceed}! Tools: {scoped_tools}",
                )
                self.assertGreaterEqual(
                    len(scoped_tools),
                    1,
                    f"[{q_id}] Query yielded 0 tools!",
                )

                # Must contain required semantic tools
                for expected_tool in must_contain:
                    self.assertIn(
                        expected_tool,
                        scoped_tools,
                        f"[{q_id}] Expected '{expected_tool}' in scoped tools, but got: {scoped_tools}",
                    )

                # Must not contain prohibited homonym tools
                for prohibited_tool in must_not_contain:
                    self.assertNotIn(
                        prohibited_tool,
                        scoped_tools,
                        f"[{q_id}] Homonym collision! Prohibited tool '{prohibited_tool}' found in: {scoped_tools}",
                    )

    def test_archive_keyword_shadowing_empirical_observation(self):
        """
        EMPIRICAL OBSERVATION & EVIDENCE HARNESS:
        When a query contains both an archive keyword ('giải nén') AND a file-manager keyword ('file', 'thư mục'),
        the 6 available heavy-cluster slots are consumed by file manager tools, leaving extract_archive_file
        pruned out. Demonstrates the exact priority-order shadowing behavior.
        """
        shadowed_query = "giải nén file backup.zip"
        scoped = self.executor._resolve_scoped_tool_names(query=shadowed_query)
        self.assertLessEqual(len(scoped), 6, "Must strictly respect heavy cluster limit <= 6")
        # In this shadowed query, file manager tools take precedence over archive tools
        self.assertIn("list_files", scoped)
        self.assertIn("run_command", scoped)  # Agent can still fall back to run_command for unzip/tar


class TestTriTierRiskGatingAndSpinalVetoAdversarial(unittest.TestCase):
    """
    Adversarial stress-testing suite for Tri-Tier Risk Gating and Spinal Safety Veto.
    Verifies that destructive actions are blocked and operational changes require confirmation.
    """

    LETHAL_ATTACK_VECTORS = [
        # 1. Lethal Deletions & Bulk Wiping
        "rm -rf /",
        "rm -rf /*",
        "rm -rf .",
        "rm -rf ~",
        "rm -r -f /",
        "rm -f -r /",
        "rm --recursive --force /",
        "rm -rf /home/kirito/*",
        "rm --no-preserve-root -rf /",
        "find / -delete",
        "find /home -exec rm -rf {} +",
        "truncate -s 0 /var/log/syslog",

        # 2. Disk & Filesystem Raw Destruction
        "mkfs.ext4 /dev/sda1",
        "mkfs.xfs /dev/nvme0n1p1",
        "mkfs /dev/vda",
        "dd if=/dev/zero of=/dev/sda bs=1M",
        "dd if=/dev/urandom of=/dev/nvme0n1",
        "> /dev/sda",
        "> /dev/nvme0n1",

        # 3. Database Destruction (DROP & TRUNCATE)
        "DROP DATABASE production;",
        "DROP DATABASE IF EXISTS quan_ly_server;",
        "DROP SCHEMA public CASCADE;",
        "DROP TABLE users;",
        "TRUNCATE TABLE accounts;",
        "truncate table only orders cascade;",

        # 4. Container Mass Purge & Destruction
        "docker system prune -a",
        "docker system prune --all",
        "docker rm -f $(docker ps -aq)",
        "docker kill `docker ps -q`",

        # 5. Network & Firewall Blackout
        "iptables -F",
        "iptables --flush",
        "ufw reset",
        "ufw disable",
        "ip link set eth0 down",

        # 6. SSH Keys & Auth Disruption
        "rm -rf /root/.ssh/authorized_keys",
        "rm -rf ~/.ssh/id_rsa",
        "> ~/.ssh/authorized_keys",
        "systemctl stop sshd",
        "systemctl disable ssh",

        # 7. Dangerous Permissions
        "chmod -R 777 /",
        "chmod -R 0777 /etc",
        "chmod 777 -R /var",
        "chown -R nobody:nogroup /",

        # 8. Fork Bombs & Stress Exhaustion
        ":(){ :|:& };:",
        "stress --cpu 16 --timeout 300s",
        "stress-ng --vm 4 --vm-bytes 4G",
    ]

    def test_spinal_safety_veto_blocks_all_lethal_attacks(self):
        """100% of lethal destructive commands must be blocked by Spinal Safety Veto."""
        for cmd in self.LETHAL_ATTACK_VECTORS:
            with self.subTest(command=cmd):
                veto_msg = evaluate_spinal_safety_veto(cmd)
                self.assertIsNotNone(
                    veto_msg,
                    f"Spinal Safety Veto failed to block lethal command: '{cmd}'!",
                )
                self.assertIn("SPINAL SAFETY VETO", veto_msg)
                self.assertIn("CONFIRM_DANGEROUS_ACTION", veto_msg)

    def test_spinal_safety_veto_unlocked_with_token(self):
        """Lethal commands pass through veto ONLY when explicit token CONFIRM_DANGEROUS_ACTION is supplied."""
        for cmd in self.LETHAL_ATTACK_VECTORS:
            with self.subTest(command=cmd):
                veto_msg = evaluate_spinal_safety_veto(cmd, confirm_token="CONFIRM_DANGEROUS_ACTION")
                self.assertIsNone(
                    veto_msg,
                    f"Spinal Safety Veto did not yield even with valid confirmation token for: '{cmd}'!",
                )

    def test_command_risk_classification(self):
        """Commands must be accurately classified into Tier 1, Tier 2, or Tier 3."""
        # Tier 3 Lethal
        for cmd in self.LETHAL_ATTACK_VECTORS:
            self.assertEqual(
                classify_command_risk(cmd),
                ACTION_TIER_3_LETHAL,
                f"Command '{cmd}' should be classified as Tier 3 Lethal",
            )

        # Tier 1 Safe Read-only
        safe_cmds = [
            "free -h",
            "df -h",
            "uptime",
            "docker ps",
            "top -b -n 1",
            "netstat -tuln",
            "ss -tuln",
            "cat /proc/cpuinfo",
            "ls -la /home/kirito",
            "journalctl -n 50 --no-pager",
            "systemctl status nginx",
            "crontab -l",
            "cat /etc/os-release | grep VERSION",
        ]
        for cmd in safe_cmds:
            self.assertEqual(
                classify_command_risk(cmd),
                ACTION_TIER_1_SAFE,
                f"Command '{cmd}' should be classified as Tier 1 Safe",
            )

        # Tier 2 Reversible / Non-read-only
        tier2_cmds = [
            "docker restart nginx",
            "systemctl restart postgresql",
            "touch /tmp/marker.txt",
            "echo 'hello' > /tmp/out.txt",
            "cat file.txt | tee /tmp/copy.txt",
            "cp /home/kirito/app.py /tmp/app_bak.py",
        ]
        for cmd in tier2_cmds:
            self.assertEqual(
                classify_command_risk(cmd),
                ACTION_TIER_2_REVERSIBLE,
                f"Command '{cmd}' should be classified as Tier 2 Reversible",
            )


class TestTier2OperationalConfirmationTokens(unittest.IsolatedAsyncioTestCase):
    """
    Verifies that Tier 2 actions (restart_service, restart_ngrok_tunnel, delete_cron_job)
    strictly require confirmation tokens when targeted at production or sensitive targets.
    """

    def setUp(self):
        self.executor = _create_mock_executor()

    async def test_restart_service_production_requires_confirm_token(self):
        """restart_service on production containers must require confirm='RESTART_CONFIRMED'."""
        prod_services = ["dashboard_ai_agent", "dashboard_db", "postgres", "redis", "nginx", "traefik"]
        for svc in prod_services:
            with self.subTest(service=svc):
                # Call without token
                res_no_token = await self.executor._execute_tool(
                    "restart_service",
                    {"service_name": svc},
                )
                self.assertIn("RESTART_CONFIRMED", str(res_no_token))
                self.assertIn("CẢNH BÁO BẢO MẬT", str(res_no_token))

                # Call with invalid token
                res_bad_token = await self.executor._execute_tool(
                    "restart_service",
                    {"service_name": svc, "confirm": "INVALID_TOKEN"},
                )
                self.assertIn("RESTART_CONFIRMED", str(res_bad_token))

                # Call with valid token: must proceed to execution
                with patch.object(self.executor.server_monitor_service, "restart_service", new_callable=AsyncMock) as mock_restart:
                    mock_restart.return_value = {"status": "success", "message": f"Dịch vụ {svc} đã khởi động lại"}
                    res_valid = await self.executor._execute_tool(
                        "restart_service",
                        {"service_name": svc, "confirm": "RESTART_CONFIRMED"},
                    )
                    mock_restart.assert_awaited_once_with(service_name=svc, confirm="RESTART_CONFIRMED")
                    self.assertIn("đã khởi động lại", str(res_valid))

    async def test_restart_ngrok_tunnel_requires_confirm_token(self):
        """restart_ngrok_tunnel must require confirm='RESTART_CONFIRMED'."""
        # Call without token
        res_no_token = await self.executor._execute_tool(
            "restart_ngrok_tunnel",
            {},
        )
        self.assertIn("RESTART_CONFIRMED", str(res_no_token))
        self.assertIn("CẢNH BÁO BẢO MẬT", str(res_no_token))

        # Call with invalid token
        res_bad_token = await self.executor._execute_tool(
            "restart_ngrok_tunnel",
            {"confirm": "WRONG_TOKEN"},
        )
        self.assertIn("RESTART_CONFIRMED", str(res_bad_token))

        # Call with valid token: must proceed
        with patch.object(self.executor.network_service, "restart_ngrok_tunnel", new_callable=AsyncMock) as mock_ngrok:
            mock_ngrok.return_value = {"status": "success", "message": "Ngrok tunnel đã khởi động lại"}
            res_valid = await self.executor._execute_tool(
                "restart_ngrok_tunnel",
                {"confirm": "RESTART_CONFIRMED"},
            )
            mock_ngrok.assert_awaited_once_with(tunnel_name=None, confirm="RESTART_CONFIRMED")
            self.assertIn("Ngrok tunnel đã khởi động lại", str(res_valid))

    async def test_delete_cron_job_requires_confirm_token(self):
        """delete_cron_job must require confirm='DELETE_CONFIRMED'."""
        # Call without token
        res_no_token = await self.executor._execute_tool(
            "delete_cron_job",
            {"name": "backup_db"},
        )
        self.assertIn("DELETE_CONFIRMED", str(res_no_token))

        # Call with invalid token
        res_bad_token = await self.executor._execute_tool(
            "delete_cron_job",
            {"name": "backup_db", "confirm": "NO"},
        )
        self.assertIn("DELETE_CONFIRMED", str(res_bad_token))

        # Call with valid token: must proceed
        with patch.object(self.executor.cron_service, "delete_cron_job", new_callable=AsyncMock) as mock_cron:
            mock_cron.return_value = {"status": "success", "message": "Đã xóa cron job backup_db"}
            res_valid = await self.executor._execute_tool(
                "delete_cron_job",
                {"name": "backup_db", "confirm": "DELETE_CONFIRMED"},
            )
            mock_cron.assert_awaited_once_with(name="backup_db", confirm="DELETE_CONFIRMED")
            self.assertIn("Đã xóa cron job backup_db", str(res_valid))


if __name__ == "__main__":
    unittest.main()
