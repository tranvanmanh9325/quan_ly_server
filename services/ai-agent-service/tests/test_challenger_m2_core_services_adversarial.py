"""
test_challenger_m2_core_services_adversarial.py — Milestone M2 Empirical Adversarial Stress Test Suite.

Author: Challenger 1 (Adversarial Empirical Verifier)
Target Services:
1. app.services.scheduler_service (R1)
2. app.services.server_monitor_service (R2)
3. app.services.notes_service (R3)

MANDATORY EMPIRICAL VERIFICATION CRITERIA:
- Test scheduler_service: schedule_reminder với delay âm, delay lớn, repeat daily/weekly, cancel reminder không tồn tại, list rỗng.
- Test server_monitor_service: restart_service không có confirm token đối với production container (phải từ chối), test parse logs rỗng hoặc chứa lỗi.
- Test notes_service: kiểm tra tạo ghi chú chứa ký tự đặc biệt, tag rỗng, tìm kiếm từ khóa không có, xóa ghi chú.
- 100% test thực nghiệm pass.
"""

import asyncio
from datetime import datetime, timezone
import json
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.security import find_security_violation
from app.services.notes_service import (
    NotesService,
    create_note,
    delete_note,
    list_notes,
    search_notes,
)
from app.services.scheduler_service import (
    InMemoryReminderStore,
    SchedulerService,
    cancel_reminder,
    list_scheduled_reminders,
    schedule_reminder,
)
from app.services.server_monitor_service import (
    PROTECTED_PRODUCTION_SERVICES,
    ServerMonitorService,
    check_service_status,
    get_system_health_report,
    restart_service,
    tail_service_logs,
)


class MockSshClient:
    """Deterministic Mock SSH Client for Adversarial Probing."""

    def __init__(self, responses=None, default_response=""):
        self.responses = responses or {}
        self.default_response = default_response
        self.executed_commands = []

    async def execute_command(self, command: str) -> str:
        self.executed_commands.append(command)
        for pattern, resp in self.responses.items():
            if pattern in command:
                return resp
        return self.default_response


# ──────────────────────────────────────────────────────────────────────────────
# SECTION 1: SCHEDULER SERVICE ADVERSARIAL STRESS HARNESS
# ──────────────────────────────────────────────────────────────────────────────

class TestSchedulerServiceAdversarial(unittest.IsolatedAsyncioTestCase):
    """Adversarial stress-test harness for SchedulerService (R1)."""

    async def asyncSetUp(self):
        self.service = SchedulerService(use_db=False)

    async def test_01_negative_delay_strictly_rejected(self):
        """Negative delay values must be rejected with informative error."""
        negative_delays = [-1, -5, -60, -999999]
        for d in negative_delays:
            res = await self.service.schedule_reminder("Nhắc nhở delay âm", d)
            self.assertEqual(res["status"], "error", f"Negative delay {d} was unexpectedly accepted!")
            self.assertIn("phải lớn hơn 0", res["message"])

    async def test_02_zero_delay_strictly_rejected(self):
        """Zero delay must be rejected."""
        res = await self.service.schedule_reminder("Nhắc nhở delay 0", 0)
        self.assertEqual(res["status"], "error")
        self.assertIn("phải lớn hơn 0", res["message"])

    async def test_03_massive_delay_computes_safely_without_overflow(self):
        """Massive delays (1 year, 10 years, 100 years) must compute ISO timestamp safely."""
        massive_delays = [525600, 5256000, 52560000]
        for d in massive_delays:
            res = await self.service.schedule_reminder("Nhắc tương lai xa", d)
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["delay_minutes"], d)
            remind_at = datetime.fromisoformat(res["remind_at"])
            self.assertGreater(remind_at, datetime.now(timezone.utc))

    async def test_04_repeat_daily_and_weekly_and_case_normalization(self):
        """Repeat frequency must support 'daily' and 'weekly' with case-insensitivity."""
        cases = [
            ("Uống nước", 30, "daily", "daily"),
            ("Họp sprint", 120, "weekly", "weekly"),
            ("Chạy bộ", 45, "DAILY", "daily"),
            ("Backup tuần", 60, "Weekly", "weekly"),
            ("Một lần duy nhất", 15, "none", "none"),
            ("Mặc định không lặp", 10, None, "none"),
        ]
        for msg, delay, repeat_input, expected_repeat in cases:
            res = await self.service.schedule_reminder(msg, delay, repeat=repeat_input)
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["repeat"], expected_repeat)

    async def test_05_invalid_repeat_strictly_rejected(self):
        """Invalid repeat options must be blocked with allowed options in message."""
        invalid_options = ["monthly", "hourly", "yearly", "biweekly", "random", "*/5 * * * *"]
        for opt in invalid_options:
            res = await self.service.schedule_reminder("Nhắc lặp lỗi", 10, repeat=opt)
            self.assertEqual(res["status"], "error")
            self.assertIn("Tần suất lặp", res["message"])
            self.assertIn("daily", res["message"])
            self.assertIn("weekly", res["message"])

    async def test_06_cancel_nonexistent_reminder(self):
        """Cancelling non-existent ID must return status='not_found'."""
        ghost_ids = [999999, 1234567, 0, -1]
        for gid in ghost_ids:
            res = await self.service.cancel_reminder(gid)
            self.assertEqual(res["status"], "not_found")
            self.assertEqual(res["reminder_id"], gid)

    async def test_07_list_empty_reminders(self):
        """Listing on empty store must return success with total=0 and empty list."""
        res = await self.service.list_scheduled_reminders()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["total"], 0)
        self.assertEqual(res["reminders"], [])

    async def test_08_empty_or_whitespace_message_rejected(self):
        """Blank or whitespace-only messages must be rejected."""
        blank_cases = ["", "   ", "\t\n", None]
        for b in blank_cases:
            res = await self.service.schedule_reminder(b, 10)
            self.assertEqual(res["status"], "error")
            self.assertIn("không được để trống", res["message"])

    async def test_09_concurrency_stress_test(self):
        """50 concurrent schedule requests must generate 50 unique incremental IDs."""
        tasks = [
            self.service.schedule_reminder(f"Parallel Task #{i}", 10 + i)
            for i in range(50)
        ]
        results = await asyncio.gather(*tasks)
        self.assertEqual(len(results), 50)
        self.assertTrue(all(r["status"] == "success" for r in results))

        ids = [r["reminder_id"] for r in results]
        self.assertEqual(len(set(ids)), 50, "ID collision detected under concurrency!")

        listing = await self.service.list_scheduled_reminders()
        self.assertEqual(listing["total"], 50)

    async def test_10_database_error_graceful_fallback(self):
        """When database connection raises an exception, service must fall back to memory store."""
        db_service = SchedulerService(use_db=True)
        with patch("app.services.scheduler_service.get_db_connection") as mock_conn:
            mock_conn.side_effect = Exception("PostgreSQL down: Connection refused")
            res = await db_service.schedule_reminder("DB fallback test", 15)
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["storage"], "memory")


# ──────────────────────────────────────────────────────────────────────────────
# SECTION 2: SERVER MONITOR SERVICE ADVERSARIAL STRESS HARNESS
# ──────────────────────────────────────────────────────────────────────────────

class TestServerMonitorServiceAdversarial(unittest.IsolatedAsyncioTestCase):
    """Adversarial stress-test harness for ServerMonitorService (R2)."""

    def setUp(self):
        self.mock_ssh = MockSshClient()
        self.service = ServerMonitorService(ssh_client=self.mock_ssh)

    async def test_11_production_container_restart_without_confirm_vetoed(self):
        """Production containers MUST be vetoed without confirm='RESTART_CONFIRMED'."""
        prod_services = [
            "dashboard_ai_agent",
            "dashboard_server_api",
            "dashboard_client",
            "postgres",
            "postgresql",
            "redis",
            "traefik",
            "nginx",
            "dashboard_db",
        ]
        unconfirmed_tokens = [None, "", "yes", "true", "RESTART", "CONFIRM", "123456"]

        for sname in prod_services:
            for token in unconfirmed_tokens:
                res = await self.service.restart_service(sname, confirm=token)
                self.assertEqual(
                    res["status"],
                    "confirmation_required",
                    f"Production service '{sname}' was not vetoed with token='{token}'!",
                )
                self.assertTrue(res["requires_confirm"])
                self.assertEqual(res["confirm_token"], "RESTART_CONFIRMED")
                self.assertIn("CẢNH BÁO BẢO MẬT", res["message"])

        # Crucial security guarantee: NO command was executed on the server
        self.assertEqual(len(self.mock_ssh.executed_commands), 0)

    async def test_12_production_container_restart_with_valid_token_executes(self):
        """With exact confirm='RESTART_CONFIRMED', production container restarts cleanly."""
        self.mock_ssh.responses = {
            "docker inspect": json.dumps({"Running": True, "Status": "running"}),
            "docker restart": "dashboard_ai_agent",
        }
        res = await self.service.restart_service("dashboard_ai_agent", confirm="RESTART_CONFIRMED")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["service_name"], "dashboard_ai_agent")
        self.assertTrue(any("docker restart dashboard_ai_agent" in cmd for cmd in self.mock_ssh.executed_commands))

    async def test_13_restart_service_command_injection_prevented(self):
        """Shell injection payloads in service name must be rejected prior to execution."""
        injection_payloads = [
            "dashboard_ai_agent; rm -rf /",
            "redis && cat /etc/passwd",
            "postgres | reboot",
            "nginx$(whoami)",
            "traefik`id`",
            "svc\nwhoami",
            "; shutdown -h now",
        ]
        for payload in injection_payloads:
            res = await self.service.restart_service(payload, confirm="RESTART_CONFIRMED")
            self.assertEqual(res["status"], "error")
            self.assertIn("Tên dịch vụ không hợp lệ", res["message"])

        self.assertEqual(len(self.mock_ssh.executed_commands), 0)

    async def test_14_tail_logs_empty_output(self):
        """Empty log output must be handled gracefully without exceptions."""
        self.mock_ssh.responses = {"docker logs": ""}
        res = await self.service.tail_service_logs("dashboard_ai_agent", lines=50)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["total_lines"], 0)
        self.assertEqual(res["error_count"], 0)
        self.assertEqual(res["warning_count"], 0)
        self.assertEqual(res["error_samples"], [])
        self.assertIn("Hoàn toàn bình thường", res["error_summary"])

    async def test_15_tail_logs_error_and_warning_parsing_and_deduplication(self):
        """Logs with errors, warnings, exceptions, and panic must be accurately counted and deduplicated."""
        log_sample = (
            "2026-09-26 10:00:00 [INFO] Worker pool initialized\n"
            "2026-09-26 10:00:01 [ERROR] Connection lost to Postgres\n"
            "2026-09-26 10:00:02 [CRITICAL] Exception in thread asyncio_1: ZeroDivisionError\n"
            "2026-09-26 10:00:03 [WARN] High memory usage: 89%\n"
            "2026-09-26 10:00:04 [FATAL] Panic: out of memory (oom-killer triggered)\n"
            "2026-09-26 10:00:05 [WARNING] Request timeout on port 8084\n"
            "2026-09-26 10:00:01 [ERROR] Connection lost to Postgres\n"  # Exact duplicate line
        )
        self.mock_ssh.responses = {"docker logs": log_sample}
        res = await self.service.tail_service_logs("dashboard_ai_agent", lines=50)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["total_lines"], 7)
        self.assertEqual(res["error_count"], 4)    # ERROR, CRITICAL/Exception, FATAL/Panic, ERROR
        self.assertEqual(res["warning_count"], 2)  # WARN, WARNING
        self.assertIn("Phát hiện 4 dòng log chứa lỗi", res["error_summary"])
        # Deduplication check: 4 errors, 1 exact duplicate -> 3 unique samples
        self.assertEqual(len(res["error_samples"]), 3)

    async def test_16_tail_logs_clamping_boundary_conditions(self):
        """Requested lines must be clamped safely between 1 and 500."""
        self.mock_ssh.responses = {"docker logs": "logline\n"}

        res_neg = await self.service.tail_service_logs("dashboard_ai_agent", lines=-100)
        self.assertEqual(res_neg["lines_requested"], 1)

        res_zero = await self.service.tail_service_logs("dashboard_ai_agent", lines=0)
        self.assertEqual(res_zero["lines_requested"], 1)

        res_huge = await self.service.tail_service_logs("dashboard_ai_agent", lines=99999)
        self.assertEqual(res_huge["lines_requested"], 500)

        res_bad = await self.service.tail_service_logs("dashboard_ai_agent", lines="invalid_number")
        self.assertEqual(res_bad["lines_requested"], 50)


# ──────────────────────────────────────────────────────────────────────────────
# SECTION 3: NOTES SERVICE ADVERSARIAL STRESS HARNESS
# ──────────────────────────────────────────────────────────────────────────────

class TestNotesServiceAdversarial(unittest.IsolatedAsyncioTestCase):
    """Adversarial stress-test harness for NotesService (R3)."""

    def setUp(self):
        self.mock_ssh = MockSshClient()
        self.service = NotesService(
            ssh_client=self.mock_ssh,
            base_path="/home/kirito/quan_ly_server/data/notes",
        )

    async def test_17_create_note_special_characters_and_emojis(self):
        """Notes with Vietnamese accents, emojis, and symbols must be preserved via Base64."""
        title = "Ghi chú Bí mật SRE & Hệ thống AI 2026 🛡️ [Ưu Tiên #1]"
        content = (
            "Tiêu chuẩn: UTF-8.\n"
            "Ký tự đặc biệt: !@#$%^&*()_+=-~`{}[]|:;'<>,.?/\n"
            "Toán học: ∑ ∏ √ ∫ ≈ ≠ ≤ ≥\n"
            "Tiếng Việt: ắ ằ ẳ ẵ ặ ấ ầ ổ ỗ ớ ờ ợ ứ ừ ự"
        )
        tags = ["sre", "bảo_mật", "tiểu_bảo_bảo"]

        res = await self.service.create_note(title=title, content=content, tags=tags)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["title"], title)
        self.assertEqual(res["tags"], tags)

        # Inspect executed command
        executed_cmd = self.mock_ssh.executed_commands[0]
        self.assertNotIn(" > /", executed_cmd)
        self.assertNotIn(" >> /", executed_cmd)
        self.assertIn("base64 -d | tee", executed_cmd)
        self.assertIsNone(find_security_violation(executed_cmd))

    async def test_18_create_note_shell_metacharacters_neutralized(self):
        """Shell metacharacters in title and body must be neutralized via Base64 encoding."""
        evil_title = "Safe Note with `id` and $(echo 123) and ; ls"
        evil_content = "Body containing | bash and ; rm -rf / and > /etc/passwd and reboot"

        res = await self.service.create_note(title=evil_title, content=evil_content)
        self.assertEqual(res["status"], "success")

        executed_cmd = self.mock_ssh.executed_commands[0]
        # Command MUST pass security filter
        self.assertIsNone(find_security_violation(executed_cmd))

    async def test_19_create_note_empty_and_whitespace_tags_filtered(self):
        """Empty and whitespace strings in tags must be filtered out cleanly."""
        res = await self.service.create_note(
            title="Clean Tags Note",
            content="Valid content",
            tags=["", "   ", "tag1", "  tag2  ", "\t", ""],
        )
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["tags"], ["tag1", "tag2"])

    async def test_20_search_notes_nonexistent_keyword(self):
        """Searching for non-existent keyword must return total=0 and polite message."""
        self.mock_ssh.responses = {"grep -rn": ""}
        res = await self.service.search_notes("NONEXISTENT_KEYWORD_XYZ_987654321")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["total"], 0)
        self.assertEqual(res["notes"], [])
        self.assertIn("Không tìm thấy", res["message"])

    async def test_21_delete_note_tier2_reversible_trash_bin(self):
        """Deleting a note must move to .trash/ and NEVER use rm command."""
        res = await self.service.delete_note("note_sre_report_2026")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["action"], "moved_to_trash")
        self.assertTrue(res["reversible"])

        executed_cmd = self.mock_ssh.executed_commands[0]
        self.assertIn("mkdir -p", executed_cmd)
        self.assertIn("mv ", executed_cmd)
        self.assertIn(".trash/", executed_cmd)
        self.assertNotIn("rm ", executed_cmd)
        self.assertIsNone(find_security_violation(executed_cmd))

    async def test_22_delete_note_path_traversal_and_injection_blocked(self):
        """Path traversal and command injection in note_id must be neutralized or rejected."""
        malicious_ids = [
            "note; rm -rf /",
            "note$(whoami)",
            "note`id`",
            "note | bash",
            "",
            "   ",
        ]
        for mid in malicious_ids:
            res = await self.service.delete_note(mid)
            self.assertEqual(res["status"], "error")
            self.assertIn("Mã ghi chú không hợp lệ", res["message"])

        self.mock_ssh.responses = {"mv ": "mv: cannot stat: No such file or directory"}
        traversal_ids = ["../../etc/passwd", "../secret.txt", "notes/child"]
        for tid in traversal_ids:
            res = await self.service.delete_note(tid)
            self.assertIn(res["status"], ("error", "not_found"))


# ──────────────────────────────────────────────────────────────────────────────
# SECTION 4: LIVE EMPIRICAL VALIDATION (PARSING REAL SERVER DATA)
# ──────────────────────────────────────────────────────────────────────────────

class TestLiveEmpiricalServerDataParsing(unittest.TestCase):
    """
    Verifies that the parsers in ServerMonitorService handle real raw outputs
    from Ubuntu Linux (Ubuntu 24.04 / 26.04) running in production on kirito-server.
    """

    def setUp(self):
        self.service = ServerMonitorService()

    def test_23_parse_real_loadavg(self):
        raw = "0.18 0.13 0.10 1/507 2956599\n"
        metrics = self.service._parse_cpu(raw)
        self.assertEqual(metrics["load_1m"], 0.18)
        self.assertEqual(metrics["load_5m"], 0.13)
        self.assertEqual(metrics["load_15m"], 0.10)

    def test_24_parse_real_free_m(self):
        raw = (
            "               total        used        free      shared  buff/cache   available\n"
            "Mem:            3303        1260         311          48        2066        2043\n"
            "Swap:          36582         547       36035\n"
        )
        metrics = self.service._parse_ram(raw)
        self.assertEqual(metrics["total_mb"], 3303)
        self.assertEqual(metrics["used_mb"], 1260)
        self.assertEqual(metrics["available_mb"], 2043)
        self.assertAlmostEqual(metrics["usage_percent"], 38.1, places=1)

    def test_25_parse_real_df_h(self):
        raw = (
            "Filesystem                         Size  Used Avail Use% Mounted on\n"
            "/dev/mapper/ubuntu--vg-ubuntu--lv  400G   81G  302G  22% /\n"
        )
        metrics = self.service._parse_disk(raw)
        self.assertEqual(metrics["filesystem"], "/dev/mapper/ubuntu--vg-ubuntu--lv")
        self.assertEqual(metrics["size"], "400G")
        self.assertEqual(metrics["used"], "81G")
        self.assertEqual(metrics["avail"], "302G")
        self.assertEqual(metrics["usage_percent"], "22%")
        self.assertEqual(metrics["usage_percent_val"], 22)

    def test_26_parse_real_docker_ps(self):
        raw = (
            "dashboard_ai_agent\tUp 2 days (healthy)\tquan_ly_server-ai-agent-service\t127.0.0.1:6080->6080/tcp, 127.0.0.1:8084->8084/tcp\n"
            "dashboard_frontend\tUp 3 days (healthy)\tquan_ly_server-frontend\t0.0.0.0:5173->80/tcp\n"
            "dashboard_db\tUp 6 days (healthy)\tpostgres:17-alpine\t5432/tcp\n"
        )
        metrics = self.service._parse_docker(raw)
        self.assertEqual(metrics["total_running"], 3)
        self.assertEqual(metrics["containers"][0]["name"], "dashboard_ai_agent")
        self.assertIn("healthy", metrics["containers"][0]["status"])

    def test_27_parse_real_ss_tuln(self):
        raw = (
            "Netid State  Recv-Q Send-Q  Local Address:Port  Peer Address:Port\n"
            "tcp   LISTEN 0      4096        0.0.0.0:22               0.0.0.0:*\n"
            "tcp   LISTEN 0      4096      127.0.0.1:8084             0.0.0.0:*\n"
            "tcp   LISTEN 0      4096      127.0.0.1:5432             0.0.0.0:*\n"
            "udp   UNCONN 0      0         127.0.0.1:323              0.0.0.0:*\n"
        )
        metrics = self.service._parse_network(raw)
        self.assertIn(22, metrics["listening_ports"])
        self.assertIn(8084, metrics["listening_ports"])
        self.assertIn(5432, metrics["listening_ports"])
        self.assertIn(323, metrics["listening_ports"])


if __name__ == "__main__":
    unittest.main()
