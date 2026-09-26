"""
test_tool_r5_cron.py — Unit & Adversarial Tests for CronService (R5).

Validates Cron Automation & Scheduled Job Management interface contracts:
- create_cron_job(name, schedule, command, description):
  - 5-field cron syntax validation (min, hour, dom, mon, dow)
  - Named months (JAN-DEC) and days of week (MON-SUN)
  - In-place idempotent update when updating an existing job
  - Input validation: empty names, invalid characters, newlines in command
  - Command injection resilience
- list_cron_jobs():
  - Parsing agent-managed entries with tags `# AGENT_JOB: <name> | <description>`
  - Parsing legacy / system crontab entries (`is_agent_managed = False`)
  - Handling empty crontabs
- delete_cron_job(name, confirm):
  - Strict confirmation gating (`confirm="DELETE_CONFIRMED"`, Tier 2 Reversible)
  - Successful deletion from crontab
  - Non-existent job deletion rejection
"""

import base64
import unittest
from unittest.mock import AsyncMock, patch

from app.services.cron_service import (
    CONFIRMATION_REQUIRED_TOKEN,
    CronService,
    create_cron_job,
    delete_cron_job,
    list_cron_jobs,
    validate_cron_expression,
)


class MockSshClient:
    """Mock SSH client for simulating host crontab read/write operations."""

    def __init__(self, initial_crontab: str = ""):
        self.crontab_content = initial_crontab
        self.executed_commands = []

    async def execute_command(self, command: str) -> str:
        self.executed_commands.append(command)

        # Handle read crontab
        if "crontab -l" in command:
            return self.crontab_content

        # Handle write crontab via base64 pipeline
        if "base64 -d | crontab -" in command:
            # Extract base64 payload
            parts = command.split("'")
            if len(parts) >= 2:
                b64_payload = parts[1]
                self.crontab_content = base64.b64decode(b64_payload.encode("ascii")).decode("utf-8")
                return ""
            return "base64 decode error"

        # Handle delete all crontab
        if "crontab -r" in command:
            self.crontab_content = ""
            return ""

        return ""


class TestCronSyntaxValidator(unittest.TestCase):
    """Test suite for validate_cron_expression()."""

    def test_valid_standard_schedules(self):
        valid_expressions = [
            "* * * * *",
            "0 2 * * *",          # 2 AM daily
            "*/15 * * * *",       # Every 15 minutes
            "0 9-18 * * 1-5",     # Hourly between 9AM-6PM Mon-Fri
            "30 4 1,15 * *",      # 4:30 AM on 1st and 15th
            "0 0 * JAN,JUN MON",  # Named months and DOW
            "0 12 * * 0",         # Sunday (0)
            "0 12 * * 7",         # Sunday (7)
            "10-30/5 * * * *",    # Range with step
        ]
        for expr in valid_expressions:
            valid, err = validate_cron_expression(expr)
            self.assertTrue(valid, f"Expression '{expr}' should be valid, got: {err}")

    def test_invalid_field_counts(self):
        invalid_counts = [
            "",
            "* * * *",          # 4 fields
            "* * * * * *",      # 6 fields
            "hourly",
        ]
        for expr in invalid_counts:
            valid, err = validate_cron_expression(expr)
            self.assertFalse(valid)
            self.assertIn("đúng 5 trường", err)

    def test_out_of_bounds_fields(self):
        cases = [
            ("60 * * * *", "Phút"),
            ("* 24 * * *", "Giờ"),
            ("* * 32 * *", "Ngày trong tháng"),
            ("* * * 13 *", "Tháng"),
            ("* * * * 8", "Thứ trong tuần"),
            ("* * * * FOOBAR", "Thứ trong tuần"),
        ]
        for expr, expected_field in cases:
            valid, err = validate_cron_expression(expr)
            self.assertFalse(valid, f"Expression '{expr}' should be invalid")
            self.assertIn(expected_field, err)

    def test_invalid_steps_and_ranges(self):
        cases = [
            ("*/0 * * * *", "phải là số nguyên dương"),
            ("30-10 * * * *", "không được lớn hơn"),
        ]
        for expr, expected_err in cases:
            valid, err = validate_cron_expression(expr)
            self.assertFalse(valid)
            self.assertIn(expected_err, err)


class TestCronServiceLifecycle(unittest.IsolatedAsyncioTestCase):
    """Test suite for CronService CRUD lifecycle."""

    def setUp(self):
        self.mock_ssh = MockSshClient()
        self.service = CronService(ssh_client=self.mock_ssh)

    # ──────────────────────────────────────────────────────────────────────────
    # 1. create_cron_job Tests
    # ──────────────────────────────────────────────────────────────────────────

    async def test_create_cron_job_success(self):
        res = await self.service.create_cron_job(
            name="backup_db",
            schedule="0 2 * * *",
            command="/usr/local/bin/backup.sh",
            description="Sao lưu database PostgreSQL hàng ngày",
        )
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["name"], "backup_db")
        self.assertEqual(res["schedule"], "0 2 * * *")

        # Verify crontab content on host
        self.assertIn("# AGENT_JOB: backup_db | Sao lưu database PostgreSQL hàng ngày", self.mock_ssh.crontab_content)
        self.assertIn("0 2 * * * /usr/local/bin/backup.sh", self.mock_ssh.crontab_content)

    async def test_create_cron_job_invalid_name(self):
        res = await self.service.create_cron_job(
            name="backup; rm -rf /",
            schedule="0 2 * * *",
            command="/bin/true",
        )
        self.assertEqual(res["status"], "error")
        self.assertIn("không hợp lệ", res["message"])

    async def test_create_cron_job_empty_command(self):
        res = await self.service.create_cron_job(
            name="test_job",
            schedule="* * * * *",
            command="   ",
        )
        self.assertEqual(res["status"], "error")
        self.assertIn("không được để trống", res["message"])

    async def test_create_cron_job_newline_command_rejected(self):
        res = await self.service.create_cron_job(
            name="test_job",
            schedule="* * * * *",
            command="echo hi\nrm -rf /",
        )
        self.assertEqual(res["status"], "error")
        self.assertIn("ký tự xuống dòng", res["message"])

    async def test_create_cron_job_invalid_schedule(self):
        res = await self.service.create_cron_job(
            name="test_job",
            schedule="99 99 * * *",
            command="/bin/echo 1",
        )
        self.assertEqual(res["status"], "error")
        self.assertIn("Biểu thức lịch cron không hợp lệ", res["message"])

    async def test_create_cron_job_idempotent_update(self):
        # Initial creation
        await self.service.create_cron_job("sync_data", "*/10 * * * *", "/bin/sync1")
        self.assertIn("*/10 * * * * /bin/sync1", self.mock_ssh.crontab_content)

        # Update with new schedule and command
        res = await self.service.create_cron_job("sync_data", "*/30 * * * *", "/bin/sync2", "Updated sync")
        self.assertEqual(res["status"], "success")

        # Verify old schedule is replaced and not duplicated
        self.assertNotIn("/bin/sync1", self.mock_ssh.crontab_content)
        self.assertIn("*/30 * * * * /bin/sync2", self.mock_ssh.crontab_content)
        self.assertEqual(self.mock_ssh.crontab_content.count("# AGENT_JOB: sync_data"), 1)

    # ──────────────────────────────────────────────────────────────────────────
    # 2. list_cron_jobs Tests
    # ──────────────────────────────────────────────────────────────────────────

    async def test_list_cron_jobs_empty(self):
        res = await self.service.list_cron_jobs()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["total_jobs"], 0)
        self.assertEqual(res["agent_jobs_count"], 0)
        self.assertEqual(res["jobs"], [])

    async def test_list_cron_jobs_mixed_system_and_agent(self):
        initial = (
            "# System crontab\n"
            "0 1 * * * /usr/sbin/logrotate /etc/logrotate.conf\n"
            "\n"
            "# AGENT_JOB: clean_temp | Dọn dẹp file tạm\n"
            "0 3 * * * /home/kirito/clean_tmp.sh\n"
        )
        self.mock_ssh.crontab_content = initial

        res = await self.service.list_cron_jobs()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["total_jobs"], 2)
        self.assertEqual(res["agent_jobs_count"], 1)

        agent_jobs = [j for j in res["jobs"] if j["is_agent_managed"]]
        self.assertEqual(len(agent_jobs), 1)
        self.assertEqual(agent_jobs[0]["name"], "clean_temp")
        self.assertEqual(agent_jobs[0]["schedule"], "0 3 * * *")
        self.assertEqual(agent_jobs[0]["description"], "Dọn dẹp file tạm")

        system_jobs = [j for j in res["jobs"] if not j["is_agent_managed"]]
        self.assertEqual(len(system_jobs), 1)
        self.assertEqual(system_jobs[0]["schedule"], "0 1 * * *")

    # ──────────────────────────────────────────────────────────────────────────
    # 3. delete_cron_job Tests
    # ──────────────────────────────────────────────────────────────────────────

    async def test_delete_cron_job_missing_confirm_vetoed(self):
        res = await self.service.delete_cron_job("backup_db")
        self.assertEqual(res["status"], "error")
        self.assertIn("confirm='DELETE_CONFIRMED'", res["message"])

    async def test_delete_cron_job_invalid_confirm_token_vetoed(self):
        res = await self.service.delete_cron_job("backup_db", confirm="YES_PLEASE")
        self.assertEqual(res["status"], "error")
        self.assertIn("confirm='DELETE_CONFIRMED'", res["message"])

    async def test_delete_cron_job_nonexistent(self):
        res = await self.service.delete_cron_job("missing_job", confirm=CONFIRMATION_REQUIRED_TOKEN)
        self.assertEqual(res["status"], "error")
        self.assertIn("Không tìm thấy", res["message"])

    async def test_delete_cron_job_success(self):
        # Set up crontab with 2 jobs
        self.mock_ssh.crontab_content = (
            "# AGENT_JOB: job_1 | Job first\n"
            "0 1 * * * /bin/cmd1\n"
            "# AGENT_JOB: job_2 | Job second\n"
            "0 2 * * * /bin/cmd2\n"
        )

        res = await self.service.delete_cron_job("job_1", confirm=CONFIRMATION_REQUIRED_TOKEN)
        self.assertEqual(res["status"], "success")
        self.assertIn("Đã xóa cron job 'job_1'", res["message"])

        # Verify job_1 is removed, job_2 remains
        self.assertNotIn("job_1", self.mock_ssh.crontab_content)
        self.assertNotIn("/bin/cmd1", self.mock_ssh.crontab_content)
        self.assertIn("job_2", self.mock_ssh.crontab_content)
        self.assertIn("/bin/cmd2", self.mock_ssh.crontab_content)


if __name__ == "__main__":
    unittest.main()
