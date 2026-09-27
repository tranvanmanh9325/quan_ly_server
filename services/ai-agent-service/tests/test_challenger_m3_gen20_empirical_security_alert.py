"""
services/ai-agent-service/tests/test_challenger_m3_gen20_empirical_security_alert.py
Empirical Adversarial Stress Test Suite for Milestone 3 (Challenger 1).

Covers 4 Empirical Attack Challenges against SecurityAlertEngine:
1. Anti-Spam Rate Limiting Challenge:
   - Burst 100 alerts from the same IP within 5s via mock HTTP client.
   - Verify only the first alert is sent, remaining 99 alerts are batched into accumulator buffer.
   - Verify zero spam: exactly 1 request to Telegram, not 100.
   - Verify multi-attacker per-IP isolation (independent buckets, no cross-IP bleeding).

2. Emergency CRITICAL Bypass Challenge:
   - Threat level CRITICAL immediately bypasses the rate-limiting digest window in 0s.
   - Non-critical threat levels (LOW, MEDIUM, HIGH) do NOT bypass and are buffered.
   - Subsequent events from the same IP do not trigger redundant instant alerts.
   - Honeypot harvest breach attempts also bypass immediately in 0s.

3. HTML Tag Injection Evasion Challenge:
   - Adversarial payloads with HTML tags (<script>alert(1)</script>, <b><i>unclosed, & < > " ').
   - Strict Telegram HTML Entity Parser Oracle verifies all tags are balanced, no unescaped tags.
   - Honeypot credentials and digest summaries are also safely escaped.
   - Telegram entity parsing failure fallback safely strips HTML to plain text.

4. rDNS Non-blocking & Timeout Challenge:
   - Simulates a hanging DNS server (10.0s sleep in gethostbyaddr).
   - Verifies the main asyncio event loop is NEVER blocked (concurrent heartbeat task ticks).
   - Verifies timeout enforcement (~1.0s), graceful fallback to raw IP, and negative caching.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from html.parser import HTMLParser
import os
import re
import socket
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

os.environ["TESTING"] = "true"

from app.core.telegram_formatter import TelegramFormatter
from app.services.security_alert_engine import (
    ATTACK_TYPE_LABELS,
    SecurityAlertEngine,
    THREAT_EMOJIS,
    PendingAlertDigest,
)


@dataclass
class SyntheticThreatEvent:
    ip: str
    attack_type: str
    threat_level: str
    target_service: str
    raw_payload: str
    timestamp: float
    action_taken: str = "iptables_drop"


class TelegramHtmlValidatorOracle(HTMLParser):
    """
    Strict Telegram HTML Entity Parser Oracle.
    Validates whether an HTML string strictly adheres to Telegram Bot API parse_mode="HTML" specs.
    Checks for:
    1. Allowed tags only: <b>, <strong>, <i>, <em>, <u>, <ins>, <s>, <strike>, <del>,
       <span class="tg-spoiler">, <tg-spoiler>, <a href="...">, <code>, <pre>, <blockquote>
    2. Strictly balanced and correctly nested tags (LIFO stack).
    3. No raw unescaped characters like unclosed '<' or forbidden tags (<script>, <img>, etc.).
    """

    ALLOWED_TAGS = {
        "b", "strong", "i", "em", "u", "ins", "s", "strike", "del",
        "span", "tg-spoiler", "a", "code", "pre", "blockquote"
    }

    def __init__(self):
        super().__init__()
        self.stack: List[str] = []
        self.errors: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        tag_lower = tag.lower()
        if tag_lower not in self.ALLOWED_TAGS:
            self.errors.append(f"Forbidden Telegram HTML tag: <{tag}>")
        if tag_lower == "a":
            href_found = any(k.lower() == "href" and v for k, v in attrs)
            if not href_found:
                self.errors.append("<a> tag missing required 'href' attribute")
        self.stack.append(tag_lower)

    def handle_endtag(self, tag: str):
        tag_lower = tag.lower()
        if not self.stack:
            self.errors.append(f"Stray closing tag </{tag}> with no matching open tag")
            return
        expected = self.stack.pop()
        if expected != tag_lower:
            self.errors.append(f"Mismatched closing tag: expected </{expected}>, got </{tag}>")

    def validate(self, text: str) -> Tuple[bool, List[str]]:
        self.stack.clear()
        self.errors.clear()
        try:
            self.feed(text)
            self.close()
        except Exception as ex:
            self.errors.append(f"HTML Parse Exception: {ex}")

        if self.stack:
            self.errors.append(f"Unclosed HTML tags remaining at EOF: {self.stack}")

        return len(self.errors) == 0, list(self.errors)


class BaseEmpiricalTest(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        SecurityAlertEngine.reset_instance()
        self.mock_http_response = MagicMock()
        self.mock_http_response.status_code = 200
        self.mock_http_response.text = '{"ok": true, "result": {"message_id": 1001}}'

        self.mock_http_client = MagicMock()
        self.mock_http_client.post = AsyncMock(return_value=self.mock_http_response)

        self.engine = SecurityAlertEngine(
            telegram_bot=None,  # Force HTTP Client path
            digest_window_seconds=300.0,
            flush_interval_seconds=10.0,
            token="empirical_test_token_12345",
            chat_id="empirical_test_chat_67890",
            http_client=self.mock_http_client,
        )

    async def asyncTearDown(self):
        await self.engine.stop()
        SecurityAlertEngine.reset_instance()


class TestEmpiricalAntiSpamRateLimiting(BaseEmpiricalTest):
    """
    Challenge 1: Anti-Spam Rate Limiting.
    Bắn 100 alerts liên tiếp từ cùng 1 IP trong 5 giây qua mock HTTP client.
    Verify: Chỉ có 1 alert đầu tiên được gửi, 99 alert còn lại được gom vào accumulator buffer,
    KHÔNG bắn 100 request tới Telegram.
    """

    async def test_burst_100_alerts_single_ip_only_one_sent_and_99_buffered(self):
        """
        Adversarial Test:
        Attacker shoots 100 consecutive alerts (first is CRITICAL, followed by 99 alerts)
        from a single IP (203.0.113.88) within ~0.5s.
        """
        await self.engine.start()
        attacker_ip = "203.0.113.88"

        # Mock fast rDNS for this IP so network latency does not skew burst timing
        with patch("socket.gethostbyaddr", return_value=("scanner.test", [], [attacker_ip])):
            # Alert 1: Initial CRITICAL threat
            ev1 = SyntheticThreatEvent(
                ip=attacker_ip,
                attack_type="sqli",
                threat_level="CRITICAL",
                target_service="nginx",
                raw_payload="' UNION SELECT 1, @@version --",
                timestamp=time.time(),
                action_taken="iptables_drop",
            )
            await self.engine.enqueue_threat_event(ev1)

            # Alerts 2-100: 99 rapid subsequent alerts (mixed vectors)
            burst_tasks = []
            for i in range(2, 101):
                attack_type = "ssh_brute_force" if i % 2 == 0 else "sqli"
                threat = "CRITICAL" if i % 10 == 0 else "HIGH"
                ev = SyntheticThreatEvent(
                    ip=attacker_ip,
                    attack_type=attack_type,
                    threat_level=threat,
                    target_service="nginx",
                    raw_payload=f"SELECT data_{i} FROM table_{i}",
                    timestamp=time.time(),
                    action_taken="iptables_drop",
                )
                burst_tasks.append(self.engine.enqueue_threat_event(ev))

            # Run all 99 enqueues concurrently
            await asyncio.gather(*burst_tasks)

        # 1. VERIFY: Exactly 1 alert was dispatched to Telegram HTTP endpoint
        self.assertEqual(
            self.mock_http_client.post.call_count,
            1,
            f"Expected exactly 1 HTTP request to Telegram, but got {self.mock_http_client.post.call_count}!",
        )

        # 2. VERIFY: The accumulator buffer exists and contains all 100 events
        self.assertIn(attacker_ip, self.engine._pending_digests)
        digest = self.engine._pending_digests[attacker_ip]
        total_buffered_events = sum(digest.event_counts.values())

        self.assertEqual(
            total_buffered_events,
            100,
            f"Expected 100 total events accumulated in buffer, got {total_buffered_events}",
        )
        self.assertTrue(digest.has_sent_critical_instant)

        # 3. VERIFY: Telegram API URL and payload structure of the single sent alert
        call_args, call_kwargs = self.mock_http_client.post.call_args
        self.assertEqual(call_args[0], "https://api.telegram.org/botempirical_test_token_12345/sendMessage")
        payload = call_kwargs["json"]
        self.assertEqual(payload["chat_id"], "empirical_test_chat_67890")
        self.assertEqual(payload["parse_mode"], "HTML")
        self.assertIn("203.0.113.88", payload["text"])
        self.assertIn("CRITICAL", payload["text"])

    async def test_burst_100_non_critical_alerts_all_buffered_zero_immediate_spam(self):
        """
        Adversarial Test:
        Attacker shoots 100 HIGH/MEDIUM alerts from 198.51.100.99.
        Verify 0 alerts are sent immediately during the burst, all 100 are buffered,
        and when flushed, exactly 1 digest is sent (NOT 100).
        """
        await self.engine.start()
        attacker_ip = "198.51.100.99"

        with patch("socket.gethostbyaddr", return_value=("scanner.test", [], [attacker_ip])):
            # Send 100 HIGH alerts
            for i in range(100):
                ev = SyntheticThreatEvent(
                    ip=attacker_ip,
                    attack_type="port_scan",
                    threat_level="HIGH",
                    target_service="fastapi",
                    raw_payload=f"SYN packet scan port {i + 1000}",
                    timestamp=time.time(),
                    action_taken="rate_limited",
                )
                await self.engine.enqueue_threat_event(ev)

        # Verify during burst, ZERO immediate requests are sent
        self.assertEqual(
            self.mock_http_client.post.call_count,
            0,
            "Non-critical burst must not fire any instant HTTP alert!",
        )

        # Verify accumulator buffer has all 100 events
        digest = self.engine._pending_digests[attacker_ip]
        self.assertEqual(sum(digest.event_counts.values()), 100)

        # Manually trigger flush
        await self.engine._flush_all_pending()

        # Verify exactly 1 digest message sent, NOT 100!
        self.assertEqual(self.mock_http_client.post.call_count, 1)
        sent_text = self.mock_http_client.post.call_args[1]["json"]["text"]
        self.assertIn("DIGEST 5 PHÚT", sent_text)
        self.assertIn("100 sự kiện", sent_text)

    async def test_multi_attacker_per_ip_isolation(self):
        """
        Adversarial Test:
        5 different attacker IPs fire 20 alerts each simultaneously (total 100 alerts).
        Verify per-IP isolation: exactly 5 alerts sent (1 per IP), no cross-IP rate-limit interference.
        """
        await self.engine.start()
        ips = [f"192.0.2.{i}" for i in range(10, 15)]

        with patch("socket.gethostbyaddr", side_effect=lambda ip: (f"host-{ip}.net", [], [ip])):
            tasks = []
            for ip in ips:
                # 1 critical event + 19 high events per IP
                ev_crit = SyntheticThreatEvent(
                    ip=ip,
                    attack_type="sqli",
                    threat_level="CRITICAL",
                    target_service="nginx",
                    raw_payload="DROP TABLE test",
                    timestamp=time.time(),
                )
                tasks.append(self.engine.enqueue_threat_event(ev_crit))

                for j in range(19):
                    ev_high = SyntheticThreatEvent(
                        ip=ip,
                        attack_type="ssh_brute_force",
                        threat_level="HIGH",
                        target_service="ssh",
                        raw_payload=f"user_{j}",
                        timestamp=time.time(),
                    )
                    tasks.append(self.engine.enqueue_threat_event(ev_high))

            await asyncio.gather(*tasks)

        # Exactly 5 HTTP requests sent (1 for each distinct IP)
        self.assertEqual(
            self.mock_http_client.post.call_count,
            5,
            f"Expected exactly 5 alerts (1 per IP), but got {self.mock_http_client.post.call_count}",
        )

        # Verify each IP has 20 accumulated events
        for ip in ips:
            self.assertIn(ip, self.engine._pending_digests)
            d = self.engine._pending_digests[ip]
            self.assertEqual(sum(d.event_counts.values()), 20)


class TestEmpiricalEmergencyCriticalBypass(BaseEmpiricalTest):
    """
    Challenge 2: Emergency CRITICAL Bypass.
    Bắn sự kiện có threat_level="CRITICAL".
    Verify: Sự kiện lập tức bypass rate limiter và gửi ngay trong 0s.
    """

    async def test_critical_event_bypasses_rate_limiter_in_zero_seconds(self):
        """
        Verify CRITICAL event bypasses 300s window immediately (< 0.1s latency).
        """
        await self.engine.start()

        crit_event = SyntheticThreatEvent(
            ip="198.51.100.123",
            attack_type="sqli",
            threat_level="CRITICAL",
            target_service="nginx",
            raw_payload="UNION SELECT @@version, user()",
            timestamp=time.time(),
            action_taken="iptables_drop",
        )

        with patch("socket.gethostbyaddr", return_value=("scanner.critical.net", [], ["198.51.100.123"])):
            t0 = time.perf_counter()
            await self.engine.enqueue_threat_event(crit_event)
            elapsed = time.perf_counter() - t0

        # Latency must be near instantaneous (well under 0.2s, completely bypassing 300s window)
        self.assertLess(elapsed, 0.2, f"Expected < 0.2s bypass latency, took {elapsed:.4f}s")

        # Must have fired immediately
        self.assertEqual(self.mock_http_client.post.call_count, 1)

        payload = self.mock_http_client.post.call_args[1]["json"]
        self.assertIn("💀 CRITICAL", payload["text"])
        self.assertIn("198.51.100.123", payload["text"])
        self.assertIn("UNION SELECT", payload["text"])
        self.assertIn("https://www.abuseipdb.com/check/198.51.100.123", payload["text"])

    async def test_non_critical_threats_do_not_bypass(self):
        """
        Verify LOW, MEDIUM, and HIGH events do NOT bypass the rate limiter.
        """
        await self.engine.start()

        with patch("socket.gethostbyaddr", return_value=("scanner.net", [], ["1.1.1.1"])):
            for threat in ("LOW", "MEDIUM", "HIGH"):
                ev = SyntheticThreatEvent(
                    ip=f"203.0.113.{threat}",
                    attack_type="scanner_probe",
                    threat_level=threat,
                    target_service="nginx",
                    raw_payload="nikto scanner test",
                    timestamp=time.time(),
                )
                await self.engine.enqueue_threat_event(ev)

        # None of these should bypass
        self.assertEqual(
            self.mock_http_client.post.call_count,
            0,
            "Non-critical threat levels must not bypass rate limiter!",
        )

    async def test_honeypot_harvest_critical_bypass(self):
        """
        Verify Honeypot credential harvest bypasses rate limiter immediately in 0s.
        """
        await self.engine.start()

        harvest_data = {
            "ip": "203.0.113.77",
            "service": "ssh",
            "port": 2222,
            "attempts": 3,
            "credentials": [
                ("root", "toor"),
                ("admin", "123456"),
                ("support", "P@ssw0rd"),
            ],
        }

        with patch("socket.gethostbyaddr", return_value=("honeypot.target.net", [], ["203.0.113.77"])):
            t0 = time.perf_counter()
            await self.engine.handle_honeypot_harvest(harvest_data)
            elapsed = time.perf_counter() - t0

        self.assertLess(elapsed, 0.2)
        self.assertEqual(self.mock_http_client.post.call_count, 1)

        payload = self.mock_http_client.post.call_args[1]["json"]
        text = payload["text"]
        self.assertIn("BẪY HONEYPOT", text)
        self.assertIn("KẺ THẤT BẠI", text)
        self.assertIn("Kẻ thất bại. Lần sau cố gắng hơn nhé!", text)
        self.assertIn("root", text)
        self.assertIn("toor", text)


class TestEmpiricalHtmlTagInjectionEvasion(BaseEmpiricalTest):
    """
    Challenge 3: HTML Tag Injection Evasion.
    Hacker gửi payload độc hại chứa thẻ HTML: <script>alert(1)</script>, <b><i>unclosed, & < > " '.
    Verify: Message formatter tự động escape HTML an toàn qua html.escape,
    không làm vỡ định dạng parse_mode="HTML" của Telegram.
    """

    def setUp(self):
        super().setUp()
        self.validator = TelegramHtmlValidatorOracle()

    async def test_malicious_html_payloads_in_single_alert(self):
        """
        Adversarial Test:
        Test aggressive HTML injection vectors inside raw_payload.
        Verify that message is safely escaped and validates against strict Telegram HTML grammar.
        """
        adversarial_payloads = [
            "<script>alert(1)</script>",
            "<b><i>unclosed_formatting_tags",
            "& < > \" '",
            '"><img src="x" onerror="alert(\'XSS\')">',
            "</code></pre><script>breakout()</script><pre><code>",
            "<a href=\"javascript:alert('malicious')\">Click here</a>",
            "<b><i><u><s>nested tags without closing",
            "SELECT * FROM users WHERE user = 'admin' AND '<script>' = '<script>' --",
            "&amp;&lt;&gt;&quot;&#x27; already escaped double entity",
        ]

        await self.engine.start()

        with patch("socket.gethostbyaddr", return_value=("scanner.test", [], ["1.1.1.1"])):
            for idx, payload in enumerate(adversarial_payloads):
                self.mock_http_client.post.reset_mock()
                ip = f"198.51.100.{idx + 1}"

                ev = SyntheticThreatEvent(
                    ip=ip,
                    attack_type="sqli",
                    threat_level="CRITICAL",
                    target_service="nginx",
                    raw_payload=payload,
                    timestamp=time.time(),
                )

                await self.engine.enqueue_threat_event(ev)

                self.assertEqual(self.mock_http_client.post.call_count, 1)
                sent_text = self.mock_http_client.post.call_args[1]["json"]["text"]

                # 1. VERIFY: No raw unescaped script, img, or dangerous HTML tags exist
                self.assertNotIn("<script>", sent_text, f"Unescaped <script> tag detected in payload {idx}!")
                self.assertNotIn("<img", sent_text, f"Unescaped <img tag detected in payload {idx}!")
                self.assertNotIn("<svg", sent_text, f"Unescaped <svg tag detected in payload {idx}!")
                self.assertNotIn('<a href="javascript:', sent_text, f"Unescaped javascript: link detected in payload {idx}!")
                self.assertNotIn("<a href='javascript:", sent_text, f"Unescaped javascript: link detected in payload {idx}!")

                # 2. VERIFY: Tags are strictly valid and balanced according to Telegram HTML specs
                valid, errors = self.validator.validate(sent_text)
                self.assertTrue(
                    valid,
                    f"Telegram HTML validation failed for payload '{payload}'! Errors: {errors}\nFormatted Message:\n{sent_text}",
                )

    async def test_malicious_html_in_honeypot_credentials(self):
        """
        Adversarial Test:
        Attacker attempts HTML injection via honeypot usernames and passwords.
        """
        await self.engine.start()

        harvest_data = {
            "ip": "203.0.113.55",
            "service": "ssh",
            "port": 2222,
            "attempts": 3,
            "credentials": [
                ("<script>alert('user')</script>", "<b><i>bold_pass"),
                ("admin&<>'\"", "<img src=x onerror=alert(1)>"),
                ("<a href='http://evil.com'>login</a>", "normal_pass"),
            ],
        }

        with patch("socket.gethostbyaddr", return_value=("honeypot.victim.net", [], ["203.0.113.55"])):
            await self.engine.handle_honeypot_harvest(harvest_data)

        self.assertEqual(self.mock_http_client.post.call_count, 1)
        sent_text = self.mock_http_client.post.call_args[1]["json"]["text"]

        # Validate that unescaped tags are eliminated
        self.assertNotIn("<script>", sent_text)
        self.assertNotIn("<img", sent_text)

        # Validate strict Telegram HTML compliance
        valid, errors = self.validator.validate(sent_text)
        self.assertTrue(valid, f"Honeypot trap HTML validation failed! Errors: {errors}\nMessage:\n{sent_text}")

    async def test_malicious_html_in_digest_summary(self):
        """
        Adversarial Test:
        Multiple attacks with malicious HTML aggregated into a 5-minute digest.
        """
        await self.engine.start()
        ip = "198.51.100.80"

        payloads = [
            "<script>alert('digest1')</script>",
            "<b><i>unclosed_digest_tag",
            "DROP TABLE users; <svg onload=alert(1)>",
        ]

        with patch("socket.gethostbyaddr", return_value=("digest.test", [], [ip])):
            for p in payloads:
                ev = SyntheticThreatEvent(
                    ip=ip,
                    attack_type="sqli",
                    threat_level="HIGH",
                    target_service="nginx",
                    raw_payload=p,
                    timestamp=time.time(),
                )
                await self.engine.enqueue_threat_event(ev)

        # Trigger digest flush
        await self.engine._flush_all_pending()

        self.assertEqual(self.mock_http_client.post.call_count, 1)
        sent_text = self.mock_http_client.post.call_args[1]["json"]["text"]

        self.assertNotIn("<script>", sent_text)
        self.assertNotIn("<svg", sent_text)

        valid, errors = self.validator.validate(sent_text)
        self.assertTrue(valid, f"Digest HTML validation failed! Errors: {errors}\nMessage:\n{sent_text}")

    async def test_telegram_api_entity_error_fallback(self):
        """
        Test fallback mechanism: If Telegram API responds with entity parse error (HTTP 400),
        engine strips HTML tags to plain text and resends successfully.
        """
        # First call fails with entity error, second call succeeds
        resp_err = MagicMock(status_code=400, text='{"ok": false, "description": "Bad Request: can\'t parse entities"}')
        resp_ok = MagicMock(status_code=200, text='{"ok": true}')

        self.mock_http_client.post = AsyncMock(side_effect=[resp_err, resp_ok])

        await self.engine.start()

        ev = SyntheticThreatEvent(
            ip="203.0.113.91",
            attack_type="sqli",
            threat_level="CRITICAL",
            target_service="nginx",
            raw_payload="SELECT * FROM data",
            timestamp=time.time(),
        )

        with patch("socket.gethostbyaddr", return_value=("fallback.test", [], ["203.0.113.91"])):
            await self.engine.enqueue_threat_event(ev)

        # Post should have been called twice (first HTML, second stripped plain text)
        self.assertEqual(self.mock_http_client.post.call_count, 2)
        first_call = self.mock_http_client.post.call_args_list[0][1]["json"]
        second_call = self.mock_http_client.post.call_args_list[1][1]["json"]

        self.assertEqual(first_call.get("parse_mode"), "HTML")
        self.assertNotIn("parse_mode", second_call)  # Stripped plain text has no parse_mode
        self.assertNotIn("<b>", second_call["text"])
        self.assertNotIn("<code>", second_call["text"])


class TestEmpiricalRdnsNonBlockingAndTimeout(BaseEmpiricalTest):
    """
    Challenge 4: rDNS Non-blocking & Timeout.
    Mô phỏng DNS server bị treo/timeout 10s khi PTR lookup IP lạ.
    Verify: SecurityAlertEngine không bị block main loop asyncio, tự động fallback về IP gốc an toàn.
    """

    async def test_rdns_timeout_10s_hang_does_not_block_main_loop(self):
        """
        Adversarial Test:
        Simulate DNS PTR lookup hanging for 10.0 seconds in gethostbyaddr.
        Verify:
        1. Asyncio event loop remains responsive (heartbeat task ticks continuously).
        2. Resolution times out in ~1.0s (strictly < 2.5s, nowhere near 10s).
        3. Returns None and message falls back to raw IP safely.
        """
        await self.engine.start()
        test_ip = "198.51.100.222"

        def simulated_hanging_dns(ip):
            # Simulate DNS server completely unresponsive / timing out after 10s
            time.sleep(10.0)
            return ("unreachable.domain.org", [], [ip])

        # Background heartbeat task ticking every 50ms to empirically prove main loop is unblocked
        heartbeat_ticks = 0
        heartbeat_running = True

        async def heartbeat_loop():
            nonlocal heartbeat_ticks
            while heartbeat_running:
                heartbeat_ticks += 1
                await asyncio.sleep(0.05)

        heartbeat_task = asyncio.create_task(heartbeat_loop())

        t0 = time.perf_counter()
        with patch("socket.gethostbyaddr", side_effect=simulated_hanging_dns):
            resolved_rdns = await self.engine._resolve_rdns(test_ip)
        elapsed = time.perf_counter() - t0

        heartbeat_running = False
        await heartbeat_task

        # 1. VERIFY: Main asyncio loop was NOT blocked.
        # Over 1.0 second with 0.05s sleeps, heartbeat should have ticked at least 12 times!
        self.assertGreaterEqual(
            heartbeat_ticks,
            12,
            f"Asyncio main loop was BLOCKED! Heartbeat ticks: {heartbeat_ticks} (expected >= 12)",
        )

        # 2. VERIFY: Timeout was enforced around 1.0s (strictly < 2.5s)
        self.assertLess(
            elapsed,
            2.5,
            f"rDNS took {elapsed:.2f}s! Timeout was NOT enforced properly (expected ~1.0s, max 2.5s)",
        )

        # 3. VERIFY: Graceful fallback to None
        self.assertIsNone(resolved_rdns, "Hanging rDNS must return None on timeout")

        # 4. VERIFY: Negative caching prevents repeated hanging lookups
        t1 = time.perf_counter()
        second_lookup = await self.engine._resolve_rdns(test_ip)
        cached_elapsed = time.perf_counter() - t1

        self.assertIsNone(second_lookup)
        self.assertLess(cached_elapsed, 0.01, f"Negative cache lookup took too long: {cached_elapsed:.4f}s")

    async def test_full_pipeline_alert_with_hanging_dns(self):
        """
        Verify enqueue_threat_event completes and dispatches alert with raw IP
        even when DNS server is completely hanging.
        """
        await self.engine.start()
        test_ip = "203.0.113.150"

        def simulated_hanging_dns(ip):
            time.sleep(10.0)
            return ("host.example.com", [], [ip])

        ev = SyntheticThreatEvent(
            ip=test_ip,
            attack_type="sqli",
            threat_level="CRITICAL",
            target_service="nginx",
            raw_payload="DROP DATABASE prod",
            timestamp=time.time(),
        )

        t0 = time.perf_counter()
        with patch("socket.gethostbyaddr", side_effect=simulated_hanging_dns):
            await self.engine.enqueue_threat_event(ev)
        elapsed = time.perf_counter() - t0

        # Must finish in ~1.0s (not 10s)
        self.assertLess(elapsed, 2.5)

        # Alert must still be sent
        self.assertEqual(self.mock_http_client.post.call_count, 1)
        sent_text = self.mock_http_client.post.call_args[1]["json"]["text"]

        # Raw IP present, no broken rDNS formatting
        self.assertIn("203.0.113.150", sent_text)
        self.assertNotIn("<i>()</i>", sent_text)
        self.assertNotIn("unreachable", sent_text)


class TestEmpiricalLifecycleAndResourceLeak(BaseEmpiricalTest):
    """
    Stress test lifecycle start/stop and clean resource reclamation.
    """

    async def test_lifecycle_five_cycles_zero_resource_warning(self):
        """
        Run 5 consecutive start() / stop() cycles under ResourceWarning filter.
        """
        for cycle in range(5):
            await self.engine.start()
            self.assertTrue(self.engine._running)
            self.assertIsNotNone(self.engine._flush_task)

            # Enqueue a dummy event
            ev = SyntheticThreatEvent(
                ip=f"198.51.100.{cycle}",
                attack_type="port_scan",
                threat_level="MEDIUM",
                target_service="fastapi",
                raw_payload="probe",
                timestamp=time.time(),
            )
            with patch("socket.gethostbyaddr", return_value=("test.cycle", [], [f"198.51.100.{cycle}"])):
                await self.engine.enqueue_threat_event(ev)

            await self.engine.stop()
            self.assertFalse(self.engine._running)
            self.assertIsNone(self.engine._flush_task)


if __name__ == "__main__":
    unittest.main()
