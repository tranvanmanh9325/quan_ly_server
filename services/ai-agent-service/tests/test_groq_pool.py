"""
Unit Test Suite cho GroqKeyPool (Min-Heap Scheduler)
services/ai-agent-service/tests/test_groq_pool.py

Kiểm thử toàn diện:
- Thứ tự bốc key ban đầu (Deterministic FIFO ordering qua key_id tie-breaker).
- Phân phối xoay tua công bằng (Fair round-robin load balancing).
- Khử trùng lặp API keys khi khởi tạo (Key deduplication).
- Cơ chế Exponential Backoff + Jitter khi gặp Rate Limit (HTTP 429).
- Reset trạng thái thất bại khi gọi mark_success.
- Xử lý mảng key rỗng / khoảng trắng (Empty and whitespace handling).
- Bảo mật thông tin: Redact API key trong logs, ngăn rò rỉ credential (CodeQL CWE-312/532).
- Trạng thái hoạt động (Status string monitoring).
"""

import asyncio
import io
import logging
import time
import unittest
from app.core.groq_pool import GroqKeyPool


class TestGroqKeyPool(unittest.IsolatedAsyncioTestCase):

    async def test_fifo_ordering(self):
        """Kiểm tra thứ tự bốc key ban đầu luôn tuân theo FIFO (Key #0 trước, rồi đến #1..#6)."""
        keys_in = [f"gsk_key_{i}" for i in range(7)]
        pool = GroqKeyPool(keys_in)
        self.assertEqual(pool.key_count, 7)

        selected = [await pool.get_next_key() for _ in range(7)]
        self.assertEqual(selected, keys_in, "Thứ tự bốc key ban đầu phải khớp chính xác thứ tự khai báo (FIFO).")

    async def test_fair_rotation(self):
        """Kiểm tra phân phối vòng tròn công bằng khi tất cả các key đều khả dụng."""
        keys_in = ["k0", "k1", "k2"]
        pool = GroqKeyPool(keys_in)

        # Chu kỳ 1: k0, k1, k2 (mỗi key usage=1)
        cycle_1 = [await pool.get_next_key() for _ in range(3)]
        self.assertEqual(cycle_1, ["k0", "k1", "k2"])

        # Chu kỳ 2: k0, k1, k2 (mỗi key usage=2)
        cycle_2 = [await pool.get_next_key() for _ in range(3)]
        self.assertEqual(cycle_2, ["k0", "k1", "k2"])

    async def test_key_deduplication(self):
        """Kiểm tra khử trùng lặp key khi cấu hình truyền trùng API keys."""
        pool = GroqKeyPool(["dup_key", "dup_key", "unique_key"])
        self.assertEqual(pool.key_count, 2)

        # Lấy key đầu tiên và đánh dấu rate-limited
        first = await pool.get_next_key()
        self.assertEqual(first, "dup_key")
        await pool.mark_rate_limited("dup_key")

        # Key tiếp theo bắt buộc phải là unique_key, không được trả về dup_key do entry mồ côi
        second = await pool.get_next_key()
        self.assertEqual(second, "unique_key")

    async def test_rate_limit_backoff_and_cooldown(self):
        """Kiểm tra cooldown tăng dần và nhảy sang key khác khi key hiện tại bị rate limit."""
        pool = GroqKeyPool(["key_a", "key_b"])

        k1 = await pool.get_next_key()
        self.assertEqual(k1, "key_a")
        await pool.mark_rate_limited(k1)

        # Key_a dính cooldown, key tiếp theo phải là key_b
        k2 = await pool.get_next_key()
        self.assertEqual(k2, "key_b")

        # Kiểm tra fail_count và cooldown của key_a
        entry_a = pool._entries_map["key_a"]
        self.assertEqual(entry_a.fail_count, 1)
        self.assertGreater(entry_a.available_at, time.monotonic())

        # Đánh dấu rate limit lần 2: fail_count tăng, backoff tăng
        prev_available = entry_a.available_at
        await pool.mark_rate_limited(k1)
        self.assertEqual(entry_a.fail_count, 2)
        self.assertGreater(entry_a.available_at, prev_available)

    async def test_mark_success_resets_fail_count(self):
        """Kiểm tra mark_success reset fail_count về 0."""
        pool = GroqKeyPool(["key_x"])
        await pool.mark_rate_limited("key_x")
        self.assertEqual(pool._entries_map["key_x"].fail_count, 1)

        await pool.mark_success("key_x")
        self.assertEqual(pool._entries_map["key_x"].fail_count, 0)

    async def test_empty_and_whitespace_keys(self):
        """Kiểm tra xử lý danh sách key rỗng hoặc chỉ chứa khoảng trắng."""
        empty_pool = GroqKeyPool([])
        self.assertEqual(empty_pool.key_count, 0)
        self.assertFalse(empty_pool.has_keys())
        self.assertIsNone(await empty_pool.get_next_key())

        ws_pool = GroqKeyPool(["", "   ", "\t\n"])
        self.assertEqual(ws_pool.key_count, 0)
        self.assertFalse(ws_pool.has_keys())
        self.assertIsNone(await ws_pool.get_next_key())

    async def test_log_redaction_security(self):
        """Kiểm tra tuyệt đối không ghi lộ API key trong logger khi đánh dấu rate-limited (CWE-532)."""
        log_stream = io.StringIO()
        handler = logging.StreamHandler(log_stream)
        target_logger = logging.getLogger("app.core.groq_pool")
        target_logger.addHandler(handler)
        target_logger.setLevel(logging.INFO)

        secret_key = "gsk_ultra_secret_super_confidential_key_99999"
        pool = GroqKeyPool([secret_key])
        k = await pool.get_next_key()
        await pool.mark_rate_limited(k)

        target_logger.removeHandler(handler)
        log_content = log_stream.getvalue()

        self.assertNotIn("ultra_secret", log_content, "API key nhạy cảm bị rò rỉ trong log!")
        self.assertNotIn("99999", log_content, "Hậu tố API key bị rò rỉ trong log!")
        self.assertIn("#0 [REDACTED]", log_content, "Phải ghi nhãn ẩn danh hóa #0 [REDACTED]!")

    def test_status_string(self):
        """Kiểm tra chuỗi trạng thái hoạt động."""
        pool = GroqKeyPool(["k1", "k2"])
        status = pool.get_status()
        self.assertIn("2/2 keys active", status)


if __name__ == "__main__":
    unittest.main()
