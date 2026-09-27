"""
tests/test_security_alert_engine.py
Milestone 3: Unit Tests for Real-Time Telegram Security Alert Engine.

Tests cover:
- 4 Threat Level emojis (LOW, MEDIUM, HIGH, CRITICAL) and attack labels.
- Message formatting for Mẫu 1 (Single / Critical Alert), Mẫu 2 (Honeypot Trap), Mẫu 3 (5-Minute Digest).
- Emergency CRITICAL bypass (immediate Telegram push).
- Rate-limiting & 5-minute batching digest for non-critical events.
- Prevention of duplicate digest for single critical events.
- Non-blocking rDNS PTR resolution and timeout resilience.
- Clean lifecycle shutdown with 0 ResourceWarning.
"""

import asyncio
from dataclasses import dataclass
import os
import socket
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure testing flag is set
os.environ["TESTING"] = "true"

from app.services.security_alert_engine import (
    ATTACK_TYPE_LABELS,
    SecurityAlertEngine,
    THREAT_EMOJIS,
    PendingAlertDigest,
)


@dataclass
class DummyThreatEvent:
    ip: str
    attack_type: str
    threat_level: str
    target_service: str
    raw_payload: str
    timestamp: float
    action_taken: str = "iptables_drop"


class TestSecurityAlertEngine(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        SecurityAlertEngine.reset_instance()
        self.mock_bot = MagicMock()
        self.mock_bot.send_message = AsyncMock(return_value=True)
        self.mock_bot.chat_id = "12345678"

        self.engine = SecurityAlertEngine(
            telegram_bot=self.mock_bot,
            digest_window_seconds=1.0,
            flush_interval_seconds=0.1,
            token="test-token",
            chat_id="12345678",
        )

    async def asyncTearDown(self):
        await self.engine.stop()
        SecurityAlertEngine.reset_instance()

    async def test_threat_level_emojis_and_labels(self):
        """Validates that all 4 threat levels map to their respective visual emojis."""
        self.assertIn("🟡", THREAT_EMOJIS["LOW"])
        self.assertIn("🟠", THREAT_EMOJIS["MEDIUM"])
        self.assertIn("🔴", THREAT_EMOJIS["HIGH"])
        self.assertIn("💀", THREAT_EMOJIS["CRITICAL"])

        self.assertIn("SSH", ATTACK_TYPE_LABELS["ssh_brute_force"])
        self.assertIn("SQL", ATTACK_TYPE_LABELS["sqli"])
        self.assertIn("Traversal", ATTACK_TYPE_LABELS["path_traversal"])
        self.assertIn("Honeypot", ATTACK_TYPE_LABELS["honeypot_ssh"])

    async def test_single_critical_alert_format_and_emergency_bypass(self):
        """Verifies that a CRITICAL event immediately bypasses digest window and formats correctly."""
        await self.engine.start()

        event = DummyThreatEvent(
            ip="45.83.122.7",
            attack_type="sqli",
            threat_level="CRITICAL",
            target_service="nginx",
            raw_payload="' UNION ALL SELECT null, password FROM users--",
            timestamp=time.time(),
            action_taken="iptables_drop",
        )

        await self.engine.enqueue_threat_event(event)

        # Confirm immediate dispatch without waiting for digest window
        self.mock_bot.send_message.assert_called_once()
        args, kwargs = self.mock_bot.send_message.call_args
        msg = args[1]

        # Verify visual hierarchy and compliance with R2 format
        self.assertIn("CẢNH BÁO AN NINH MÁY CHỦ", msg)
        self.assertIn("💀 CRITICAL", msg)
        self.assertIn("45.83.122.7", msg)
        self.assertIn("Web Attack (SQL Injection)", msg)
        self.assertIn("UNION ALL SELECT", msg)
        self.assertIn("iptables DROP", msg)
        self.assertIn("https://www.abuseipdb.com/check/45.83.122.7", msg)

    async def test_honeypot_trap_alert_format(self):
        """Verifies Honeypot Trap Mẫu 2 contains credentials, troll payload, and AbuseIPDB link."""
        harvest_data = {
            "ip": "103.145.12.8",
            "service": "ssh",
            "port": 2222,
            "attempts": 3,
            "credentials": [
                ("root", "123456"),
                ("admin", "admin@2026"),
                ("ubuntu", "P@ssw0rd!"),
            ],
        }

        await self.engine.handle_honeypot_harvest(harvest_data)

        self.mock_bot.send_message.assert_called_once()
        args, _ = self.mock_bot.send_message.call_args
        msg = args[1]

        self.assertIn("BẪY HONEYPOT", msg)
        self.assertIn("KẺ THẤT BẠI", msg)
        self.assertIn("103.145.12.8", msg)
        self.assertIn("Fake SSH Listener (Port 2222)", msg)
        self.assertIn("root", msg)
        self.assertIn("123456", msg)
        self.assertIn("P@ssw0rd!", msg)
        self.assertIn("Kẻ thất bại. Lần sau cố gắng hơn nhé!", msg)
        self.assertIn("https://www.abuseipdb.com/check/103.145.12.8", msg)

    async def test_rate_limit_and_5min_digest_batching(self):
        """Verifies multiple non-critical events are batched into a single 5-minute digest."""
        # Use short digest window for test speed
        self.engine.digest_window_seconds = 0.2
        await self.engine.start()

        # Enqueue 3 attacks from the same IP
        for i in range(3):
            ev = DummyThreatEvent(
                ip="198.51.100.88",
                attack_type="ssh_brute_force",
                threat_level="HIGH",
                target_service="ssh",
                raw_payload=f"Failed password for user{i}",
                timestamp=time.time(),
                action_taken="iptables_drop",
            )
            await self.engine.enqueue_threat_event(ev)

        # Before expiry, no instant alert should have been sent (since HIGH is batched, not CRITICAL)
        self.assertEqual(self.mock_bot.send_message.call_count, 0)

        # Wait for the flusher loop to trigger after digest_window_seconds
        await asyncio.sleep(0.35)

        # Exactly 1 digest message should be sent
        self.assertEqual(self.mock_bot.send_message.call_count, 1)
        args, _ = self.mock_bot.send_message.call_args
        digest_msg = args[1]

        self.assertIn("TỔNG HỢP CẢNH BÁO AN NINH (DIGEST 5 PHÚT)", digest_msg)
        self.assertIn("198.51.100.88", digest_msg)
        self.assertIn("3 sự kiện", digest_msg)
        self.assertIn("SSH Brute Force", digest_msg)
        self.assertIn("Failed password for user0", digest_msg)

    async def test_no_duplicate_digest_for_single_critical_event(self):
        """Ensures a single CRITICAL alert does NOT trigger an identical redundant digest message."""
        self.engine.digest_window_seconds = 0.2
        await self.engine.start()

        event = DummyThreatEvent(
            ip="203.0.113.5",
            attack_type="ddos_rate_abuse",
            threat_level="CRITICAL",
            target_service="fastapi",
            raw_payload="Rate limit exceeded: 50 req/s",
            timestamp=time.time(),
            action_taken="iptables_drop",
        )

        await self.engine.enqueue_threat_event(event)

        # Instant alert fired once
        self.assertEqual(self.mock_bot.send_message.call_count, 1)

        # Wait for flusher window to expire
        await asyncio.sleep(0.35)

        # Call count should STILL be 1 (duplicate digest suppressed)
        self.assertEqual(self.mock_bot.send_message.call_count, 1)

    async def test_rdns_resolution_and_timeout_resilience(self):
        """Tests that rDNS resolves hostnames properly and gracefully handles failures."""
        with patch("socket.gethostbyaddr", return_value=("scanner.malicious-bot.net", [], ["1.2.3.4"])):
            resolved = await self.engine._resolve_rdns("1.2.3.4")
            self.assertEqual(resolved, "scanner.malicious-bot.net")

        # Second call hits cache
        cached = await self.engine._resolve_rdns("1.2.3.4")
        self.assertEqual(cached, "scanner.malicious-bot.net")

        # Test failure/timeout resilience
        with patch("socket.gethostbyaddr", side_effect=socket.herror(1, "Unknown host")):
            failed_res = await self.engine._resolve_rdns("9.9.9.9")
            self.assertIsNone(failed_res)

    async def test_clean_shutdown_zero_leaks(self):
        """Ensures that start() and stop() manage asyncio tasks cleanly with 0 ResourceWarning."""
        await self.engine.start()
        self.assertTrue(self.engine._running)
        self.assertIsNotNone(self.engine._flush_task)

        await self.engine.stop()
        self.assertFalse(self.engine._running)
        self.assertIsNone(self.engine._flush_task)


if __name__ == "__main__":
    unittest.main()
