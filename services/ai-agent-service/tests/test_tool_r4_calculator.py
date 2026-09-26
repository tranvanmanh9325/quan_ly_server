"""
test_tool_r4_calculator.py — Unit & Adversarial Tests for CalculatorService (R4).

Validates Safe Calculator, Database Analytics, and Unit Conversion interface contracts:
- calculate(expression):
  - Standard arithmetic & precedence
  - Mathematical functions (sqrt, sin, cos, tan, log, factorial, etc.)
  - Statistical analysis (mean, median, stdev)
  - Compound interest calculations (compound_interest, lai_kep)
  - Zero division, overflow protection, and exponential bomb mitigation
  - Strict AST security vetting (forbids eval, imports, dunders, attributes, code execution)
- query_database(sql_query, database):
  - Read-only execution (SELECT, EXPLAIN, SHOW, WITH ... SELECT)
  - Blocking DML / DDL mutations (INSERT, UPDATE, DELETE, DROP, TRUNCATE, ALTER, GRANT, etc.)
  - Blocking query chaining via semicolon (;) and comment trickery (-- or /* */)
  - Telegram ASCII table formatting and 50-row clamping
- convert_units(value, from_unit, to_unit):
  - Multi-category conversions: Temperature, Mass, Length, Speed, Data Size, Currency
  - Localized alias resolution (Vietnamese & colloquial terms)
  - Cross-category error rejection and unknown unit error handling
"""

import math
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.calculator_service import (
    CalculatorService,
    calculate,
    convert_units,
    format_table_for_telegram,
    query_database,
    validate_read_only_sql,
)


class TestCalculatorServiceMath(unittest.IsolatedAsyncioTestCase):
    """Test suite for calculate() AST evaluator."""

    def setUp(self):
        self.service = CalculatorService()

    # ──────────────────────────────────────────────────────────────────────────
    # 1. Standard Arithmetic & Precedence
    # ──────────────────────────────────────────────────────────────────────────

    async def test_basic_arithmetic(self):
        res = await self.service.calculate("2 + 3 * 4")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["result"], 14)

    async def test_parentheses_and_fractions(self):
        res = await self.service.calculate("(100 - 20) / 4")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["result"], 20.0)

    async def test_negative_numbers(self):
        res = await self.service.calculate("-15 + 25 - (-10)")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["result"], 20)

    async def test_powers_and_modulo(self):
        res = await self.service.calculate("2**10 + 17 % 5")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["result"], 1024 + 2)

    async def test_caret_auto_power(self):
        # 2^8 gets normalized to 2**8
        res = await self.service.calculate("2^8")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["result"], 256)

    # ──────────────────────────────────────────────────────────────────────────
    # 2. Math Functions & Constants
    # ──────────────────────────────────────────────────────────────────────────

    async def test_sqrt_and_constants(self):
        res = await self.service.calculate("sqrt(144) + pi")
        self.assertEqual(res["status"], "success")
        self.assertAlmostEqual(res["result"], 12.0 + math.pi, places=5)

    async def test_trigonometric_functions(self):
        res = await self.service.calculate("sin(0) + cos(0)")
        self.assertEqual(res["status"], "success")
        self.assertAlmostEqual(res["result"], 1.0, places=5)

    async def test_logarithms_and_exp(self):
        res = await self.service.calculate("log(e) + log10(1000)")
        self.assertEqual(res["status"], "success")
        self.assertAlmostEqual(res["result"], 1.0 + 3.0, places=5)

    async def test_factorial_and_gcd(self):
        res = await self.service.calculate("factorial(5) + gcd(48, 18)")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["result"], 120 + 6)

    # ──────────────────────────────────────────────────────────────────────────
    # 3. Statistical & Financial Functions
    # ──────────────────────────────────────────────────────────────────────────

    async def test_statistics_mean_median_stdev(self):
        res_mean = await self.service.calculate("mean([10, 20, 30, 40])")
        self.assertEqual(res_mean["status"], "success")
        self.assertEqual(res_mean["result"], 25.0)

        res_median = await self.service.calculate("median([1, 5, 2, 8, 7])")
        self.assertEqual(res_median["status"], "success")
        self.assertEqual(res_median["result"], 5)

        res_stdev = await self.service.calculate("stdev([2, 4, 4, 4, 5, 5, 7, 9])")
        self.assertEqual(res_stdev["status"], "success")
        self.assertAlmostEqual(res_stdev["result"], 2.1380899, places=4)

    async def test_compound_interest_calculation(self):
        # 10,000,000 VND at 7% yearly for 3 years compounded monthly
        res = await self.service.calculate("compound_interest(10000000, 0.07, 12, 3)")
        self.assertEqual(res["status"], "success")
        expected = 10000000 * ((1 + 0.07 / 12) ** 36)
        self.assertAlmostEqual(res["result"], expected, places=2)

    async def test_lai_kep_alias_with_percentage(self):
        # Percentage format (8.5% entered as 8.5)
        res = await self.service.calculate("lai_kep(50000000, 8.5, 1, 5)")
        self.assertEqual(res["status"], "success")
        expected = 50000000 * ((1 + 0.085) ** 5)
        self.assertAlmostEqual(res["result"], expected, places=2)

    # ──────────────────────────────────────────────────────────────────────────
    # 4. Error Handling & Adversarial Mitigations
    # ──────────────────────────────────────────────────────────────────────────

    async def test_zero_division_handled(self):
        res = await self.service.calculate("10 / 0")
        self.assertEqual(res["status"], "error")
        self.assertIn("chia cho số 0", res["message"])

    async def test_empty_expression(self):
        res = await self.service.calculate("   ")
        self.assertEqual(res["status"], "error")
        self.assertIn("không được để trống", res["message"])

    async def test_syntax_error(self):
        res = await self.service.calculate("10 + * 5")
        self.assertEqual(res["status"], "error")
        self.assertIn("Cú pháp", res["message"])

    async def test_exponential_bomb_blocked(self):
        res = await self.service.calculate("2**999999999")
        self.assertEqual(res["status"], "error")
        self.assertIn("Lỗi tràn số", res["message"])

    async def test_pow_function_exponential_bomb_blocked(self):
        # calculate("pow(2, 999999999)") must be blocked immediately without CPU stall
        res = await self.service.calculate("pow(2, 999999999)")
        self.assertEqual(res["status"], "error")
        self.assertIn("Lỗi tràn số", res["message"])
        self.assertIn("vượt quá giới hạn an toàn", res["message"])

    async def test_pow_function_safe_and_modulo(self):
        # Standard valid pow calls
        res_pow = await self.service.calculate("pow(2, 10)")
        self.assertEqual(res_pow["status"], "success")
        self.assertEqual(res_pow["result"], 1024)

        # Modulo ternary pow
        res_mod = await self.service.calculate("pow(2, 3, 5)")
        self.assertEqual(res_mod["status"], "success")
        self.assertEqual(res_mod["result"], 3)

    async def test_factorial_bomb_blocked(self):
        res = await self.service.calculate("factorial(500)")
        self.assertEqual(res["status"], "error")
        self.assertIn("Giai thừa n <= 100", res["message"])

    async def test_security_import_injection_blocked(self):
        res = await self.service.calculate("__import__('os').system('echo pwned')")
        self.assertEqual(res["status"], "error")
        self.assertTrue("không được phép" in res["message"] or "không xác định" in res["message"])

    async def test_security_attribute_access_blocked(self):
        res = await self.service.calculate("'abc'.upper()")
        self.assertEqual(res["status"], "error")
        self.assertIn("không được phép", res["message"])

    async def test_security_dunder_blocked(self):
        res = await self.service.calculate("().__class__.__bases__[0]")
        self.assertEqual(res["status"], "error")
        self.assertIn("không được phép", res["message"])


class TestCalculatorServiceDatabase(unittest.IsolatedAsyncioTestCase):
    """Test suite for query_database() read-only executor."""

    def setUp(self):
        self.service = CalculatorService()

    # ──────────────────────────────────────────────────────────────────────────
    # 1. SQL Validation Rules
    # ──────────────────────────────────────────────────────────────────────────

    def test_sql_validation_allow_select(self):
        sql = "SELECT id, username FROM users WHERE status = 'active'"
        self.assertEqual(validate_read_only_sql(sql), sql)

    def test_sql_validation_allow_explain(self):
        sql = "EXPLAIN ANALYZE SELECT * FROM logs"
        self.assertEqual(validate_read_only_sql(sql), sql)

    def test_sql_validation_allow_with_select(self):
        sql = "WITH summary AS (SELECT count(*) as c FROM tasks) SELECT * FROM summary"
        self.assertEqual(validate_read_only_sql(sql), sql)

    def test_sql_validation_block_chaining_semicolon(self):
        with self.assertRaises(ValueError) as cm:
            validate_read_only_sql("SELECT 1; DROP TABLE users;")
        self.assertIn("chấm phẩy", str(cm.exception))

    def test_sql_validation_block_comments(self):
        with self.assertRaises(ValueError) as cm:
            validate_read_only_sql("SELECT 1 -- this is a comment")
        self.assertIn("comment SQL", str(cm.exception))

        with self.assertRaises(ValueError) as cm2:
            validate_read_only_sql("SELECT 1 /* block comment */")
        self.assertIn("comment SQL", str(cm2.exception))

    def test_sql_validation_block_dml_insert(self):
        with self.assertRaises(ValueError) as cm:
            validate_read_only_sql("INSERT INTO users (name) VALUES ('evil')")
        self.assertIn("Chỉ cho phép các câu truy vấn đọc", str(cm.exception))

    def test_sql_validation_block_dml_update(self):
        with self.assertRaises(ValueError) as cm:
            validate_read_only_sql("UPDATE users SET role = 'admin'")
        self.assertIn("Chỉ cho phép các câu truy vấn đọc", str(cm.exception))

    def test_sql_validation_block_dml_delete(self):
        with self.assertRaises(ValueError) as cm:
            validate_read_only_sql("DELETE FROM users WHERE id = 1")
        self.assertIn("Chỉ cho phép các câu truy vấn đọc", str(cm.exception))

    def test_sql_validation_block_ddl_drop(self):
        with self.assertRaises(ValueError) as cm:
            validate_read_only_sql("DROP TABLE users")
        self.assertIn("Chỉ cho phép các câu truy vấn đọc", str(cm.exception))

    def test_sql_validation_block_ddl_truncate(self):
        with self.assertRaises(ValueError) as cm:
            validate_read_only_sql("TRUNCATE notes")
        self.assertIn("Chỉ cho phép các câu truy vấn đọc", str(cm.exception))

    def test_sql_validation_block_nested_insert_into(self):
        with self.assertRaises(ValueError) as cm:
            validate_read_only_sql("SELECT * INTO new_table FROM old_table")
        self.assertIn("INTO", str(cm.exception))

    def test_sql_validation_block_pg_sleep(self):
        with self.assertRaises(ValueError) as cm:
            validate_read_only_sql("SELECT pg_sleep(10)")
        self.assertIn("pg_sleep", str(cm.exception))

    # ──────────────────────────────────────────────────────────────────────────
    # 2. Table Formatting & Clamping
    # ──────────────────────────────────────────────────────────────────────────

    def test_table_formatter_under_50_rows(self):
        cols = ["id", "service", "status"]
        rows = [
            {"id": 1, "service": "api", "status": "running"},
            {"id": 2, "service": "postgres", "status": "running"},
        ]
        table = format_table_for_telegram(cols, rows)
        self.assertIn("| id | service  | status  |", table)
        self.assertIn("| 1  | api      | running |", table)
        self.assertIn("| 2  | postgres | running |", table)

    def test_table_formatter_clamped_at_50_rows(self):
        cols = ["id", "val"]
        rows = [{"id": i, "val": f"item_{i}"} for i in range(60)]
        table = format_table_for_telegram(cols, rows)
        self.assertIn("Đã giới hạn hiển thị 50/60 dòng dữ liệu", table)

    # ──────────────────────────────────────────────────────────────────────────
    # 3. Mocked Database Query Execution
    # ──────────────────────────────────────────────────────────────────────────

    @patch("app.services.calculator_service.get_db_dict_cursor")
    async def test_query_database_success(self, mock_cursor_ctx):
        mock_cursor = AsyncMock()
        mock_cursor.description = [("id",), ("name",), ("status",)]
        mock_cursor.fetchmany.return_value = [
            {"id": 1, "name": "dashboard_ai_agent", "status": "healthy"},
            {"id": 2, "name": "dashboard_server_api", "status": "healthy"},
        ]
        mock_cursor_ctx.return_value.__aenter__.return_value = mock_cursor

        res = await self.service.query_database("SELECT id, name, status FROM containers")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["row_count"], 2)
        self.assertFalse(res["truncated"])
        self.assertIn("dashboard_ai_agent", res["formatted_table"])

    async def test_query_database_rejected_by_security(self):
        res = await self.service.query_database("DROP DATABASE test")
        self.assertEqual(res["status"], "error")
        self.assertIn("Từ chối truy vấn bảo mật", res["message"])


class TestCalculatorServiceUnitConversion(unittest.IsolatedAsyncioTestCase):
    """Test suite for convert_units()."""

    def setUp(self):
        self.service = CalculatorService()

    # ──────────────────────────────────────────────────────────────────────────
    # 1. Temperature Conversions
    # ──────────────────────────────────────────────────────────────────────────

    async def test_temp_celsius_to_fahrenheit(self):
        res = await self.service.convert_units(100, "C", "F")
        self.assertEqual(res["status"], "success")
        self.assertAlmostEqual(res["result"], 212.0, places=2)

    async def test_temp_fahrenheit_to_celsius(self):
        res = await self.service.convert_units(32, "F", "C")
        self.assertEqual(res["status"], "success")
        self.assertAlmostEqual(res["result"], 0.0, places=2)

    async def test_temp_celsius_to_kelvin(self):
        res = await self.service.convert_units(0, "C", "K")
        self.assertEqual(res["status"], "success")
        self.assertAlmostEqual(res["result"], 273.15, places=2)

    # ──────────────────────────────────────────────────────────────────────────
    # 2. Mass, Length, Speed, Data Size, Currency Conversions
    # ──────────────────────────────────────────────────────────────────────────

    async def test_mass_kg_to_gram(self):
        res = await self.service.convert_units(2.5, "kg", "g")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["result"], 2500.0)

    async def test_mass_pound_to_kg(self):
        res = await self.service.convert_units(10, "lb", "kg")
        self.assertEqual(res["status"], "success")
        self.assertAlmostEqual(res["result"], 4.53592, places=4)

    async def test_length_km_to_meter(self):
        res = await self.service.convert_units(5.5, "km", "m")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["result"], 5500.0)

    async def test_length_mile_to_km(self):
        res = await self.service.convert_units(10, "mi", "km")
        self.assertEqual(res["status"], "success")
        self.assertAlmostEqual(res["result"], 16.09344, places=4)

    async def test_speed_kmh_to_ms(self):
        res = await self.service.convert_units(36, "km/h", "m/s")
        self.assertEqual(res["status"], "success")
        self.assertAlmostEqual(res["result"], 10.0, places=4)

    async def test_data_size_gb_to_mb(self):
        res = await self.service.convert_units(2, "GB", "MB")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["result"], 2048.0)

    async def test_currency_usd_to_vnd(self):
        res = await self.service.convert_units(100, "USD", "VND")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["result"], 2540000.0)

    # ──────────────────────────────────────────────────────────────────────────
    # 3. Vietnamese Aliases & Incompatible Error Handling
    # ──────────────────────────────────────────────────────────────────────────

    async def test_vietnamese_aliases(self):
        res1 = await self.service.convert_units(37, "độ C", "độ F")
        self.assertEqual(res1["status"], "success")
        self.assertAlmostEqual(res1["result"], 98.6, places=1)

        res2 = await self.service.convert_units(50, "đô", "đồng")
        self.assertEqual(res2["status"], "success")
        self.assertEqual(res2["result"], 1270000.0)

    async def test_incompatible_categories_rejected(self):
        res = await self.service.convert_units(10, "kg", "km")
        self.assertEqual(res["status"], "error")
        self.assertIn("Không thể chuyển đổi giữa hai nhóm", res["message"])

    async def test_unknown_unit_rejected(self):
        res = await self.service.convert_units(10, "foobar", "kg")
        self.assertEqual(res["status"], "error")
        self.assertIn("không được hỗ trợ", res["message"])


if __name__ == "__main__":
    unittest.main()
