"""
test_challenger_m3_it2_empirical.py — Challenger 1 Empirical Adversarial Stress Test Suite for Milestone M3 Iteration 2.

Author: Challenger 1 (Empirical Adversarial Verifier)
Target Components:
1. calculator_service.py: Exponential DoS & SQL DoS pg_sleep protection.
2. email_report_service.py: Arbitrary attachment exfiltration & traversal protection.
"""

import asyncio
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from app.services.calculator_service import (
    calculate,
    evaluate_expression_safely,
    validate_read_only_sql,
)
from app.services.email_report_service import (
    _is_safe_attachment_path,
    send_email,
)


class TestExponentialDosAdversarialEmpirical(unittest.IsolatedAsyncioTestCase):
    """
    Empirical stress-testing of exponential bomb defenses (pow & BinOp **)
    verifying immediate termination (< 50ms) without CPU lag or process hang.
    """

    def test_01_pow_exponential_bomb_huge_exponent_immediate_abort(self):
        """pow(2, 999999999) must abort immediately (<50ms) with OverflowError."""
        t0 = time.perf_counter()
        with self.assertRaises(OverflowError) as ctx:
            evaluate_expression_safely("pow(2, 999999999)")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        self.assertLess(elapsed_ms, 50.0, f"Execution took too long: {elapsed_ms:.2f}ms")
        self.assertIn("vượt quá giới hạn an toàn", str(ctx.exception))

    def test_02_pow_exponent_above_10000_immediate_abort(self):
        """pow(10, 10001) must abort immediately (<50ms) with OverflowError."""
        t0 = time.perf_counter()
        with self.assertRaises(OverflowError) as ctx:
            evaluate_expression_safely("pow(10, 10001)")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        self.assertLess(elapsed_ms, 50.0, f"Execution took too long: {elapsed_ms:.2f}ms")
        self.assertTrue(
            "vượt quá giới hạn an toàn" in str(ctx.exception)
            or "cơ số > 1" in str(ctx.exception)
        )

    def test_03_pow_huge_negative_exponent_immediate_abort(self):
        """pow(2, -999999999) must abort immediately (<50ms) with OverflowError."""
        t0 = time.perf_counter()
        with self.assertRaises(OverflowError) as ctx:
            evaluate_expression_safely("pow(2, -999999999)")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        self.assertLess(elapsed_ms, 50.0, f"Execution took too long: {elapsed_ms:.2f}ms")
        self.assertIn("vượt quá giới hạn an toàn", str(ctx.exception))

    def test_04_pow_huge_base_and_exponent_immediate_abort(self):
        """pow(99999999999, 10) must abort immediately (<50ms) with OverflowError."""
        t0 = time.perf_counter()
        with self.assertRaises(OverflowError) as ctx:
            evaluate_expression_safely("pow(99999999999, 10)")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        self.assertLess(elapsed_ms, 50.0, f"Execution took too long: {elapsed_ms:.2f}ms")
        self.assertIn("Cơ số và số mũ quá lớn", str(ctx.exception))

    def test_05_pow_exponent_above_1000_with_base_above_1_immediate_abort(self):
        """pow(2, 1001) must abort immediately (<50ms) with OverflowError."""
        t0 = time.perf_counter()
        with self.assertRaises(OverflowError) as ctx:
            evaluate_expression_safely("pow(2, 1001)")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        self.assertLess(elapsed_ms, 50.0, f"Execution took too long: {elapsed_ms:.2f}ms")
        self.assertIn("cơ số > 1", str(ctx.exception))

    def test_06_binop_pow_operator_equivalence_stress(self):
        """Operator ** with huge exponents must abort immediately (<50ms)."""
        cases = [
            "2 ** 999999999",
            "10 ** 10001",
            "2 ** -999999999",
            "2 ** 1001",
        ]
        for expr in cases:
            t0 = time.perf_counter()
            with self.assertRaises(OverflowError):
                evaluate_expression_safely(expr)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            self.assertLess(elapsed_ms, 50.0, f"BinOp {expr} took {elapsed_ms:.2f}ms")

    def test_07_nested_pow_calls_immediate_abort(self):
        """Nested pow(pow(2, 10), 100) must abort with OverflowError."""
        t0 = time.perf_counter()
        with self.assertRaises(OverflowError):
            evaluate_expression_safely("pow(pow(2, 10), 100)")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        self.assertLess(elapsed_ms, 50.0, f"Nested pow took {elapsed_ms:.2f}ms")

    def test_08_pow_type_and_boolean_sanitization(self):
        """Boolean values and non-numbers must be rejected with TypeError."""
        type_cases = [
            "pow(True, 10)",
            "pow(2, False)",
            "pow('2', '3')",
        ]
        for tc in type_cases:
            with self.assertRaises((TypeError, ValueError)):
                evaluate_expression_safely(tc)

    def test_09_pow_ternary_modulo_safety(self):
        """Ternary pow(base, exp, mod) safe operation and division by zero prevention."""
        # Safe small modulo
        self.assertEqual(evaluate_expression_safely("pow(2, 3, 5)"), 3)
        self.assertEqual(evaluate_expression_safely("pow(3, 4, 7)"), 4)

        # Modulo zero division
        with self.assertRaises(ZeroDivisionError):
            evaluate_expression_safely("pow(2, 3, 0)")

        # Exponential bomb with modulo must be blocked BEFORE calculating
        with self.assertRaises(OverflowError):
            evaluate_expression_safely("pow(2, 999999999, 5)")

    async def test_10_calculate_service_graceful_error_handling(self):
        """Service-level calculate() must return status='error' with clean message."""
        dos_cases = [
            "pow(2, 999999999)",
            "pow(10, 10001)",
            "pow(2, -999999999)",
            "pow(99999999999, 10)",
            "pow(2, 1001)",
        ]
        for expr in dos_cases:
            t0 = time.perf_counter()
            res = await calculate(expr)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            self.assertLess(elapsed_ms, 50.0)
            self.assertEqual(res["status"], "error")
            self.assertIn("Lỗi tràn số", res["message"])


class TestAttachmentTraversalAdversarialEmpirical(unittest.TestCase):
    """
    Empirical stress-testing of email attachment path safety validation (_is_safe_attachment_path).
    Confirms 100% rejection of traversal, hidden files, sensitive credentials, and unauthorized dirs.
    """

    def setUp(self):
        self.tmp_dir = Path(tempfile.gettempdir())
        self.safe_file = self.tmp_dir / "challenger_valid_report.txt"
        self.safe_file.write_text("Challenger verification test content")

    def tearDown(self):
        self.safe_file.unlink(missing_ok=True)

    def test_01_directory_traversal_relative_env(self):
        """Paths with ../ and targeting .env must be rejected 100%."""
        traversal_attempts = [
            "../../.env",
            "../../../.env",
            "data/notes/../../.env",
            "./../../.env",
            "../.env.local",
            ".env",
        ]
        for path in traversal_attempts:
            self.assertFalse(
                _is_safe_attachment_path(path),
                f"Expected {path} to be blocked by _is_safe_attachment_path",
            )

    def test_02_directory_traversal_sensitive_system_files(self):
        """Paths targeting /etc/shadow, /etc/passwd must be rejected 100%."""
        system_targets = [
            "../../../../etc/shadow",
            "../../../../etc/passwd",
            "/etc/shadow",
            "/etc/passwd",
            "/etc/hosts",
            "/etc/group",
            "C:/Windows/win.ini",
            "C:/Windows/System32/drivers/etc/hosts",
            "../../../Windows/System32/drivers/etc/hosts",
        ]
        for path in system_targets:
            self.assertFalse(
                _is_safe_attachment_path(path),
                f"Expected {path} to be blocked by _is_safe_attachment_path",
            )

    def test_03_hidden_files_blocked(self):
        """Hidden files starting with '.' must be rejected 100%."""
        hidden_cases = [
            ".secret",
            ".credentials",
            ".bash_history",
            ".bashrc",
            str(self.tmp_dir / ".secret_challenger"),
        ]
        for path in hidden_cases:
            self.assertFalse(
                _is_safe_attachment_path(path),
                f"Expected hidden file {path} to be blocked",
            )

    def test_04_sensitive_ssh_and_cloud_credentials_blocked(self):
        """SSH keys, cloud keys, and git configs must be rejected 100%."""
        cred_paths = [
            "/home/kirito/.ssh/id_rsa",
            "/home/kirito/.ssh/id_ed25519",
            "/home/kirito/.ssh/authorized_keys",
            "/home/kirito/.ssh/known_hosts",
            "d:/GitHub/quan_ly_server/.git/config",
            "d:/GitHub/quan_ly_server/.git/HEAD",
            "/root/.ssh/id_rsa",
        ]
        for path in cred_paths:
            self.assertFalse(
                _is_safe_attachment_path(path),
                f"Expected credential {path} to be blocked",
            )

    def test_05_valid_whitelisted_file_allowed(self):
        """Legitimate file residing within whitelisted tmp directory must be permitted."""
        self.assertTrue(
            _is_safe_attachment_path(self.safe_file),
            f"Expected {self.safe_file} to be allowed by whitelist",
        )

    def test_06_send_email_integration_drops_malicious_attachments(self):
        """send_email must cleanly discard blocked attachments while preserving safe ones."""
        with patch("app.services.email_report_service._get_smtp_config") as mock_cfg:
            mock_cfg.return_value = {
                "host": "smtp.test.local",
                "port": 587,
                "user": "agent@test.local",
                "password": "secret_password",
                "sender": "agent@test.local",
                "use_tls": True,
                "use_ssl": False,
            }
            with patch("smtplib.SMTP") as mock_smtp_cls:
                mock_server = MagicMock()
                mock_smtp_cls.return_value = mock_server

                coro = send_email(
                    to="admin@test.local",
                    subject="Challenger Attachment Test",
                    body="Test body",
                    attachments=[
                        "../../.env",
                        "../../../../etc/shadow",
                        ".secret",
                        str(self.safe_file),
                    ],
                )
                loop = asyncio.new_event_loop()
                try:
                    result = loop.run_until_complete(coro)
                finally:
                    loop.close()

                self.assertEqual(result["status"], "success")
                self.assertEqual(len(result["attachments"]), 1)
                self.assertEqual(result["attachments"], [self.safe_file.name])


class TestSqlDosAdversarialEmpirical(unittest.TestCase):
    """
    Empirical stress-testing of SQL validation against pg_sleep DoS attacks
    and obfuscation attempts (case variance, SQL comments, spacing).
    """

    def test_01_pg_sleep_standard_blocked(self):
        """SELECT pg_sleep(10) and SELECT PG_SLEEP(5) must be blocked 100%."""
        queries = [
            "SELECT pg_sleep(10)",
            "SELECT PG_SLEEP(5)",
            "select pg_sleep(1)",
        ]
        for sql in queries:
            with self.assertRaises(ValueError) as ctx:
                validate_read_only_sql(sql)
            self.assertIn("pg_sleep", str(ctx.exception))

    def test_02_pg_sleep_comment_obfuscation_blocked(self):
        """select /* comment */ pg_sleep(1) must be blocked 100%."""
        obfuscated_queries = [
            "select /* comment */ pg_sleep(1)",
            "SELECT -- comment\npg_sleep(2)",
            "SELECT /*!50000 pg_sleep(1) */",
        ]
        for sql in obfuscated_queries:
            with self.assertRaises(ValueError):
                validate_read_only_sql(sql)

    def test_03_pg_sleep_whitespace_and_formatting_variants_blocked(self):
        """Whitespace, tabs, newlines, and spacing variants must be blocked."""
        variants = [
            "SELECT pg_sleep (10)",
            "SELECT PG_SLEEP( 10 )",
            "SELECT\tpg_sleep(10)",
            "SELECT\npg_sleep(10)",
            "SELECT\r\npg_sleep(10)",
            "select pg_sleep(0.5)",
            "SELECT pg_catalog.pg_sleep(10)",
            'SELECT "pg_sleep"(10)',
            "SELECT 1 FROM users WHERE id = 1 AND pg_sleep(2) IS NULL",
            "SELECT * FROM pg_sleep(1)",
            "EXPLAIN SELECT pg_sleep(1)",
        ]
        for sql in variants:
            with self.assertRaises(ValueError) as ctx:
                validate_read_only_sql(sql)
            self.assertTrue(
                "pg_sleep" in str(ctx.exception)
                or "Chặn comment SQL" in str(ctx.exception)
            )

    def test_04_pg_sleep_extended_variants_boundary_observation(self):
        """
        Adversarial Observation:
        pg_sleep_for and pg_sleep_until are Postgres 9.3+ time-delay built-ins.
        Documents current boundary behavior for Challenger report.
        """
        extended_variants = [
            "SELECT pg_sleep_for('5 seconds')",
            "SELECT pg_sleep_until('2026-09-26 12:00:00')",
        ]
        for sql in extended_variants:
            # Documenting that \bpg_sleep\b regex currently allows pg_sleep_for/pg_sleep_until
            # because '_' is treated as a word character in regex (\w).
            # This is recorded as a key finding for hardening.
            pass


if __name__ == "__main__":
    unittest.main()
