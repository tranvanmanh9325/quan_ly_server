"""
test_optimization_and_security.py — Unit Tests for Performance & Security Hardening.

Covers:
  1. In-Memory Token Bucket Rate Limiter & Anti-Bruteforce Jail (app.core.rate_limiter).
  2. Non-Blocking Memory Reclaimer (app.core.memory_reclaimer).
  3. Persistent HTTP Client Connection Pools (app.core.http_client).
  4. PostgreSQL Async Pool Configuration (app.core.db).
"""

import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException, Request

from app.core.rate_limiter import DownloadRateLimitGuard, TokenBucket
from app.core.memory_reclaimer import _sync_collect_and_trim, reclaim_memory_background
from app.core.http_client import HttpClientManager
from app.core.db import DatabasePoolManager


class TestOptimizationAndSecurity(unittest.IsolatedAsyncioTestCase):
    def test_rate_limiter_token_consumption(self):
        """Verify standard token consumption and refill behavior."""
        guard = DownloadRateLimitGuard(capacity=5.0, refill_rate=1.0, max_failed_attempts=3, jail_seconds=10)
        mock_request = MagicMock(spec=Request)
        mock_request.headers = {}
        mock_request.client = MagicMock()
        mock_request.client.host = "192.168.1.100"

        # Consume 5 allowed burst tokens
        for _ in range(5):
            ip = guard.check_rate_limit(mock_request)
            self.assertEqual(ip, "192.168.1.100")

        # 6th request should exceed capacity -> 429
        with self.assertRaises(HTTPException) as ctx:
            guard.check_rate_limit(mock_request)
        self.assertEqual(ctx.exception.status_code, 429)

    def test_rate_limiter_anti_bruteforce_jail(self):
        """Verify that multiple failed attempts place client IP into jail (403)."""
        guard = DownloadRateLimitGuard(capacity=10.0, refill_rate=1.0, max_failed_attempts=3, jail_seconds=60)
        mock_request = MagicMock(spec=Request)
        mock_request.headers = {"X-Forwarded-For": "203.0.113.50, 10.0.0.1"}
        mock_request.client = MagicMock()
        mock_request.client.host = "10.0.0.1"

        ip = "203.0.113.50"
        # Record 2 failed attempts -> not jailed yet
        guard.record_failed_attempt(ip)
        guard.record_failed_attempt(ip)
        self.assertEqual(guard._buckets[ip].jailed_until, 0.0)

        # 3rd failure -> placed into jail!
        guard.record_failed_attempt(ip)
        self.assertGreater(guard._buckets[ip].jailed_until, time.time())

        # Next check should raise 403 Forbidden
        with self.assertRaises(HTTPException) as ctx:
            guard.check_rate_limit(mock_request)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("bị khóa tạm thời", ctx.exception.detail)

    def test_rate_limiter_success_resets_counter(self):
        """Verify that successful access decreases failure counter."""
        guard = DownloadRateLimitGuard(capacity=10.0, refill_rate=1.0, max_failed_attempts=5, jail_seconds=60)
        ip = "192.168.1.5"
        guard.record_failed_attempt(ip)
        guard.record_failed_attempt(ip)
        self.assertEqual(guard._buckets[ip].failed_attempts, 2)

        guard.record_successful_attempt(ip)
        self.assertEqual(guard._buckets[ip].failed_attempts, 1)

    def test_memory_reclaimer_sync(self):
        """Verify _sync_collect_and_trim runs cleanly without error."""
        stats = _sync_collect_and_trim()
        self.assertIn("unreachable_objects", stats)
        self.assertIn("elapsed_ms", stats)
        self.assertGreaterEqual(stats["elapsed_ms"], 0.0)

    async def test_memory_reclaimer_background_task(self):
        """Verify reclaim_memory_background schedules and completes non-blocking task."""
        await reclaim_memory_background(delay_seconds=0.01)
        await asyncio.sleep(0.05)

    def test_http_client_manager_media_client(self):
        """Verify HttpClientManager provides a persistent media client with proper limits."""
        manager = HttpClientManager()
        client = manager.get_client()
        media_client = manager.get_media_client()

        self.assertIsNotNone(client)
        self.assertIsNotNone(media_client)
        self.assertTrue(media_client.follow_redirects)

        # Check that subsequent call returns the same pooled instance
        media_client_2 = manager.get_media_client()
        self.assertIs(media_client, media_client_2)

    def test_db_pool_manager_singleton(self):
        """Verify DatabasePoolManager singleton pattern."""
        m1 = DatabasePoolManager()
        m2 = DatabasePoolManager()
        self.assertIs(m1, m2)


if __name__ == "__main__":
    unittest.main()
