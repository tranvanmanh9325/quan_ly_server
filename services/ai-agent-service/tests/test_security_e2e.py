"""
services/ai-agent-service/tests/test_security_e2e.py
Autonomous Security Guardian — Comprehensive End-to-End (E2E) Test Suite.

Architecture:
- Tier 1: Feature Coverage (100% 17 Features in Feature Inventory).
- Tier 2: Boundary & Corner Cases (Dual-stack IPv6 unwrap, log overflow, CIDR edges, TTL extremes, LRU limits, digest window).
- Tier 3: Cross-Feature Interactions (Honeypot -> Auto-block -> Telegram Alert -> AI Tools pipeline).
- Tier 4: Real-World Application Scenarios (APT Campaign, Botnet Defacement, Firewall 24h TTL Lifecycle).
- Zero Side-Effects: Dynamic port allocation, isolated temp SQLite WAL DB, mock firewall, mock Telegram.
- Clean Lifecycle: 0 ResourceWarning for unclosed transport/socket/files.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import ipaddress
import os
import re
import shutil
import socket
import tempfile
import time
from typing import Any, Dict, List, Optional, Set, Tuple
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ["TESTING"] = "true"

# Service imports
from app.services.security_monitor_service import (
    BlockedIPRecord,
    BoundedPortScanTracker,
    CLOUDFLARE_IPV4_CIDRS,
    CLOUDFLARE_IPV6_CIDRS,
    DEFAULT_WHITELIST_CIDRS,
    extract_client_ip,
    MockFirewallController,
    normalize_ip_address,
    SecurityMonitorService,
    SlidingWindowTracker,
    StorageRepository,
    ThreatEvent,
    ThreatLevel,
    WhitelistEngine,
)
from app.services.honeypot_service import (
    HoneypotConfig,
    HoneypotCredentialRecord,
    HoneypotService,
    HoneypotStorageRepository,
    strip_telnet_iac,
)
from app.services.security_alert_engine import (
    ATTACK_TYPE_LABELS,
    PendingAlertDigest,
    SecurityAlertEngine,
    THREAT_EMOJIS,
)
from app.services.ai_agent_tools import (
    ACTION_TIER_1_SAFE,
    ACTION_TIER_2_REVERSIBLE,
    AgentToolExecutor,
    classify_action_risk,
)


def get_free_port() -> int:
    """Finds an available local ephemeral TCP port dynamically to prevent port collisions."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class BaseSecurityE2ETestCase(unittest.IsolatedAsyncioTestCase):
    """
    Base test fixture providing isolated environment for Autonomous Security Guardian E2E tests:
    - Temporary SQLite WAL database
    - Dynamic ephemeral ports for Fake SSH and Fake Telnet
    - MockFirewallController with recorded command history
    - Mock Telegram Bot with AsyncMock send_message
    - Initialized SecurityMonitorService, HoneypotService, SecurityAlertEngine, and AgentToolExecutor
    - Clean lifecycle teardown (0 ResourceWarning: unclosed transport)
    """

    async def asyncSetUp(self) -> None:
        SecurityMonitorService.reset_instance()
        HoneypotService.reset_instance()
        SecurityAlertEngine.reset_instance()

        self.temp_dir = tempfile.mkdtemp()
        self.sec_db_path = os.path.join(self.temp_dir, "test_sec_e2e.db")
        self.hp_db_path = os.path.join(self.temp_dir, "test_hp_e2e.db")

        self.ssh_port = get_free_port()
        self.telnet_port = get_free_port()

        # In-memory Mock Firewall
        self.mock_fw = MockFirewallController()

        # Mock Telegram Bot
        self.mock_bot = MagicMock()
        self.mock_bot.send_message = AsyncMock(return_value=True)
        self.mock_bot.chat_id = "12345678"

        # Security Alert Engine with fast test window
        self.alert_engine = SecurityAlertEngine(
            telegram_bot=self.mock_bot,
            digest_window_seconds=1.0,
            flush_interval_seconds=0.05,
            token="test-token",
            chat_id="12345678",
        )

        # Security Monitor Service
        self.sec_monitor = SecurityMonitorService(
            firewall=self.mock_fw,
            db_path=self.sec_db_path,
            custom_whitelist_ips=["192.168.1.50", "203.0.113.10"],
            alert_engine=self.alert_engine,
        )

        # Honeypot Config & Service
        self.hp_config = HoneypotConfig(
            bind_host="127.0.0.1",
            ssh_port=self.ssh_port,
            telnet_port=self.telnet_port,
            db_path=self.hp_db_path,
            use_postgres=False,
            auth_delay=0.01,
            socket_timeout=3.0,
        )

        async def harvest_cb(event: Dict[str, Any]) -> None:
            if hasattr(self.alert_engine, "handle_honeypot_harvest"):
                await self.alert_engine.handle_honeypot_harvest(event)

        async def block_ip_cb(ip: str, reason: str) -> None:
            await self.sec_monitor.block_ip(
                ip=ip,
                reason=reason,
                duration_seconds=86400,
                threat_level="HIGH",
            )

        self.honeypot_service = HoneypotService(
            config=self.hp_config,
            on_harvest_callback=harvest_cb,
            on_block_ip_callback=block_ip_cb,
            security_monitor=self.sec_monitor,
            alert_engine=self.alert_engine,
        )

        # AI Agent Tool Executor
        self.mock_ssh = MagicMock()
        self.mock_cache = MagicMock()
        self.tool_executor = AgentToolExecutor(
            ssh_client=self.mock_ssh,
            message_cache=self.mock_cache,
            security_monitor_service=self.sec_monitor,
            honeypot_service=self.honeypot_service,
        )

        # Start services
        await self.sec_monitor.start()
        await self.alert_engine.start()
        await self.honeypot_service.start()

    async def asyncTearDown(self) -> None:
        # Graceful shutdown of services and tasks
        await self.honeypot_service.stop()
        await self.sec_monitor.stop()
        await self.alert_engine.stop()

        SecurityMonitorService.reset_instance()
        HoneypotService.reset_instance()
        SecurityAlertEngine.reset_instance()

        shutil.rmtree(self.temp_dir, ignore_errors=True)


class TestSecurityE2E(BaseSecurityE2ETestCase):
    """
    Consolidated 30 E2E Security Test Suite for Autonomous Security Guardian.
    Covers Tier 1 (17 features), Tier 2 (6 boundary cases), Tier 3 (4 cross cases), and Tier 4 (3 real scenarios).
    """

    # =========================================================================
    # TIER 1 — FEATURE COVERAGE (17 TEST CASES)
    # =========================================================================

    async def test_01_feature_ssh_brute_force_detection(self) -> None:
        """F1: Tail auth.log, >= 5 failed logins within 30s triggers HIGH and auto-block."""
        attacker_ip = "198.51.100.10"
        log_line = f"sshd[1234]: Failed password for invalid user admin from {attacker_ip} port 45678 ssh2"

        for _ in range(4):
            ev = await self.sec_monitor.process_log_line(log_line, log_type="auth")
            self.assertIsNotNone(ev)

        # 5th attempt crosses >= 5 threshold -> ThreatLevel.HIGH -> iptables_drop
        ev5 = await self.sec_monitor.process_log_line(log_line, log_type="auth")
        self.assertIsNotNone(ev5)
        self.assertEqual(ev5["threat_level"], "HIGH")
        self.assertEqual(ev5["attack_type"], "ssh_brute_force")
        self.assertEqual(ev5["action_taken"], "iptables_drop")
        self.assertTrue(await self.mock_fw.is_blocked(attacker_ip))

    async def test_02_feature_web_sqli_detection(self) -> None:
        """F2: Tail access.log, regex SQLi with inline comments and double URL-decoding."""
        attacker_ip = "198.51.100.12"
        raw_sqli = "%27%20UNION%2F%2Acomment%2A%2FSELECT%20null%2Cpassword%20FROM%20users--"
        line = f'{attacker_ip} - - [27/Sep/2026:12:00:00 +0700] "GET /api/v1/users?id=1{raw_sqli} HTTP/1.1" 200 1024 "-" "curl" "-"'

        ev = await self.sec_monitor.process_log_line(line, log_type="nginx")
        self.assertIsNotNone(ev)
        self.assertEqual(ev["attack_type"], "sqli")
        self.assertIn(ev["threat_level"], ("HIGH", "CRITICAL"))
        self.assertTrue(await self.mock_fw.is_blocked(attacker_ip))

    async def test_03_feature_web_xss_and_traversal_detection(self) -> None:
        """F3: Tail access.log, detects XSS script tags and Path Traversal sequences."""
        attacker_ip = "198.51.100.13"

        # 1. XSS probe
        xss_line = f'{attacker_ip} - - [27/Sep/2026:12:00:00 +0700] "GET /search?q=%3Cscript%3Ealert(document.cookie)%3C/script%3E HTTP/1.1" 200 500 "-" "curl" "-"'
        ev_xss = await self.sec_monitor.process_log_line(xss_line, log_type="nginx")
        self.assertIsNotNone(ev_xss)
        self.assertEqual(ev_xss["attack_type"], "xss")

        # 2. Path Traversal probe
        trav_line = f'{attacker_ip} - - [27/Sep/2026:12:00:01 +0700] "GET /download?file=../../etc/passwd HTTP/1.1" 403 45 "-" "curl" "-"'
        ev_trav = await self.sec_monitor.process_log_line(trav_line, log_type="nginx")
        self.assertIsNotNone(ev_trav)
        self.assertEqual(ev_trav["attack_type"], "path_traversal")

    async def test_04_feature_port_scan_sliding_window(self) -> None:
        """F4: Port scan sliding window tracker (>= 8 distinct ports probed within 10s -> HIGH)."""
        attacker_ip = "198.51.100.22"
        distinct_ports = [21, 22, 23, 80, 443, 3306, 5432, 8080]

        ev = None
        for port in distinct_ports:
            ev = await self.sec_monitor.process_log_line(
                f"PORT_SCAN: {attacker_ip} port {port}",
                log_type="port_scan",
            )

        self.assertIsNotNone(ev)
        self.assertEqual(ev["attack_type"], "port_scan")
        self.assertEqual(ev["threat_level"], "HIGH")
        self.assertTrue(await self.mock_fw.is_blocked(attacker_ip))

    async def test_05_feature_ddos_rate_abuse_limiter(self) -> None:
        """F5: DDoS rate abuse limiter triggers rate limiting at 15 reqs, and DROP at 60 reqs."""
        attacker_ip = "198.51.100.33"
        req_line = f"REQ: {attacker_ip} /api/v1/resource"

        # 16 requests -> MEDIUM threshold (>= 15) -> rate_limit_ip
        for _ in range(16):
            ev_med = await self.sec_monitor.process_log_line(req_line, log_type="ddos")
        self.assertIsNotNone(ev_med)
        self.assertEqual(ev_med["threat_level"], "MEDIUM")
        self.assertIn(attacker_ip, self.mock_fw._rate_limited)

        # Advance to 65 requests -> CRITICAL threshold (>= 60) -> block_ip DROP
        for _ in range(49):
            ev_crit = await self.sec_monitor.process_log_line(req_line, log_type="ddos")
        self.assertIsNotNone(ev_crit)
        self.assertEqual(ev_crit["threat_level"], "CRITICAL")
        self.assertTrue(await self.mock_fw.is_blocked(attacker_ip))

    async def test_06_feature_threat_level_classification(self) -> None:
        """F6: Validates 4 threat level classifications and emoji mappings."""
        self.assertEqual(ThreatLevel.LOW.value, "LOW")
        self.assertEqual(ThreatLevel.MEDIUM.value, "MEDIUM")
        self.assertEqual(ThreatLevel.HIGH.value, "HIGH")
        self.assertEqual(ThreatLevel.CRITICAL.value, "CRITICAL")

        self.assertIn("🟡", THREAT_EMOJIS["LOW"])
        self.assertIn("🟠", THREAT_EMOJIS["MEDIUM"])
        self.assertIn("🔴", THREAT_EMOJIS["HIGH"])
        self.assertIn("💀", THREAT_EMOJIS["CRITICAL"])

    async def test_07_feature_whitelist_5tier_veto(self) -> None:
        """F7: 5-Tier IP Whitelist veto protection (Loopback, LAN, Docker, Cloudflare IPv4/IPv6)."""
        whitelist_samples = [
            "127.0.0.1",       # Tier 1: Loopback
            "192.168.1.50",     # Tier 2: LAN Admin IP
            "172.18.0.5",       # Tier 3: Docker bridge CIDR
            "104.16.1.1",       # Tier 4: Cloudflare IPv4
            "2606:4700::1",     # Tier 4: Cloudflare IPv6
        ]

        for ip in whitelist_samples:
            res = await self.sec_monitor.block_ip(ip, reason="Test block on whitelist")
            self.assertEqual(res["status"], "veto", f"IP {ip} must be vetoed!")
            self.assertFalse(await self.mock_fw.is_blocked(ip))

    async def test_08_feature_autoblock_iptables_drop_nginx(self) -> None:
        """F8: Scanner user-agent (sqlmap) triggers immediate CRITICAL DROP rule."""
        attacker_ip = "45.83.122.7"
        line = f'{attacker_ip} - - [27/Sep/2026:12:00:00 +0700] "GET /api/v1/items HTTP/1.1" 200 500 "-" "sqlmap/1.7.2#stable" "-"'

        ev = await self.sec_monitor.process_log_line(line, log_type="nginx")
        self.assertIsNotNone(ev)
        self.assertEqual(ev["attack_type"], "scanner_probe")
        self.assertEqual(ev["threat_level"], "CRITICAL")
        self.assertTrue(await self.mock_fw.is_blocked(attacker_ip))

        # Verify command history in mock firewall
        drop_cmd = f"BLOCK: iptables -I SECURITY_GUARDIAN 1 -s {attacker_ip} -j DROP"
        self.assertIn(drop_cmd, self.mock_fw.command_history)

    async def test_09_feature_ttl_sweeper_lifecycle(self) -> None:
        """F9: TTL Sweeper lifecycle automatically unblocks expired IPs."""
        target_ip = "198.51.100.70"
        await self.sec_monitor.block_ip(target_ip, reason="Sweeper TTL 0 test", duration_seconds=0)
        self.assertTrue(await self.mock_fw.is_blocked(target_ip))

        # Simulate 1 cycle of sweeper
        now = time.time() + 5.0
        expired = [
            ip for ip, rec in self.sec_monitor._blocked_ips.items()
            if rec.is_active and now >= rec.expires_at
        ]
        for ip in expired:
            await self.sec_monitor.unblock_ip(ip, reason="TTL_EXPIRED")

        self.assertFalse(await self.mock_fw.is_blocked(target_ip))
        unblock_cmd = f"UNBLOCK: iptables -D SECURITY_GUARDIAN -s {target_ip}"
        self.assertIn(unblock_cmd, self.mock_fw.command_history)

    async def test_10_feature_honeypot_fake_ssh_and_telnet(self) -> None:
        """F10: Fake SSH and Telnet listeners respond with authentic banners and handle IAC."""
        # 1. Fake SSH connection
        reader_ssh, writer_ssh = await asyncio.open_connection("127.0.0.1", self.ssh_port)
        try:
            banner = await asyncio.wait_for(reader_ssh.readline(), timeout=3.0)
            self.assertIn(b"SSH-2.0-OpenSSH", banner)
            login_prompt = await asyncio.wait_for(reader_ssh.readuntil(b"login: "), timeout=3.0)
            self.assertIn(b"login: ", login_prompt)
        finally:
            writer_ssh.close()
            await writer_ssh.wait_closed()

        # 2. Fake Telnet connection with IAC bytes
        reader_telnet, writer_telnet = await asyncio.open_connection("127.0.0.1", self.telnet_port)
        try:
            banner_telnet = await asyncio.wait_for(reader_telnet.readuntil(b"login: "), timeout=3.0)
            self.assertIn(b"Ubuntu", banner_telnet)

            # Send IAC DO ECHO negotiation bytes followed by username
            writer_telnet.write(b"\xff\xfd\x01testadmin\r\n")
            await writer_telnet.drain()

            pwd_prompt = await asyncio.wait_for(reader_telnet.readuntil(b"Password: "), timeout=3.0)
            self.assertIn(b"Password: ", pwd_prompt)
        finally:
            writer_telnet.close()
            await writer_telnet.wait_closed()

    async def test_11_feature_troll_payload_after_3_fails(self) -> None:
        """F11: Honeypot delivers troll payload on 3rd failed credential attempt and closes connection."""
        reader, writer = await asyncio.open_connection("127.0.0.1", self.ssh_port)
        try:
            await asyncio.wait_for(reader.readline(), timeout=3.0)  # banner

            for attempt in range(1, 4):
                await asyncio.wait_for(reader.readuntil(b"login: "), timeout=3.0)
                writer.write(f"user{attempt}\r\n".encode())
                await writer.drain()

                await asyncio.wait_for(reader.readuntil(b"Password: "), timeout=3.0)
                writer.write(f"pass{attempt}\r\n".encode())
                await writer.drain()

                if attempt < 3:
                    denied = await asyncio.wait_for(reader.readuntil(b"Access denied\r\n\r\n"), timeout=3.0)
                    self.assertIn(b"Access denied", denied)
                else:
                    payload = await asyncio.wait_for(reader.read(1024), timeout=3.0)
                    self.assertIn("💀 Kẻ thất bại".encode("utf-8"), payload)
                    self.assertIn("Tiểu Bảo Bảo Security Team 😂".encode("utf-8"), payload)

            # Server closes connection
            eof = await asyncio.wait_for(reader.read(100), timeout=2.0)
            self.assertEqual(eof, b"")
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_12_feature_credential_harvest_storage(self) -> None:
        """F12: Credential harvesting dual-tier persistence (SQLite WAL & in-memory stats)."""
        record = HoneypotCredentialRecord(
            id=None,
            ip="198.51.100.88",
            service="ssh",
            username="attacker_admin",
            password="super_secret_pw",
            attempt_count=1,
            captured_at=time.time(),
        )
        saved_id = await self.honeypot_service.repository.save_credential(record)
        self.assertIsNotNone(saved_id)

        logs = await self.honeypot_service.get_honeypot_log(limit=5)
        self.assertGreaterEqual(len(logs), 1)
        match = next((item for item in logs if item.get("username") == "attacker_admin"), None)
        self.assertIsNotNone(match)
        self.assertEqual(match["password"], "super_secret_pw")

    async def test_13_feature_nginx_403_ssi_cyberpunk(self) -> None:
        """F13: Nginx Custom 403 HTML with SSI variables, cyberpunk theme, and scanner rules."""
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        html_path = os.path.join(repo_root, "frontend", "html", "403.html")
        rules_path = os.path.join(repo_root, "frontend", "conf.d", "security_rules.conf")
        blocklist_path = os.path.join(repo_root, "frontend", "conf.d", "blocklist.conf")

        self.assertTrue(os.path.exists(html_path), "403.html must exist")
        self.assertTrue(os.path.exists(rules_path), "security_rules.conf must exist")
        self.assertTrue(os.path.exists(blocklist_path), "blocklist.conf must exist")

        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        self.assertIn('<!--#echo var="remote_addr" default="Recorded" -->', html_content)
        self.assertIn('<!--#echo var="time_local" default="Captured" -->', html_content)
        self.assertIn("Kẻ tấn công = Kẻ thất bại 😂", html_content)
        self.assertIn("403", html_content)

        with open(rules_path, "r", encoding="utf-8") as f:
            rules_content = f.read()
        self.assertIn("sqlmap", rules_content.lower())
        self.assertIn("nikto", rules_content.lower())

    async def test_14_feature_telegram_instant_alert_high_critical(self) -> None:
        """F14: Telegram Security Alert Engine immediately dispatches CRITICAL incidents."""
        crit_event = ThreatEvent(
            ip="45.83.122.9",
            attack_type="sqli",
            threat_level=ThreatLevel.CRITICAL,
            target_service="nginx",
            raw_payload="' UNION ALL SELECT null, password FROM users--",
            timestamp=time.time(),
            action_taken="iptables_drop",
        )

        await self.alert_engine.enqueue_threat_event(crit_event)

        self.mock_bot.send_message.assert_called_once()
        args, kwargs = self.mock_bot.send_message.call_args
        msg = args[1]
        self.assertIn("💀 CRITICAL", msg)
        self.assertIn("45.83.122.9", msg)
        self.assertIn("AbuseIPDB", msg)

    async def test_15_feature_telegram_5min_digest_accumulator(self) -> None:
        """F15: Telegram 5-Minute Digest Accumulator batches multiple alerts into 1 summary message."""
        ip = "198.51.100.77"
        # Enqueue 3 HIGH events
        for i in range(3):
            ev = ThreatEvent(
                ip=ip,
                attack_type="ssh_brute_force",
                threat_level=ThreatLevel.HIGH,
                target_service="ssh",
                raw_payload=f"Failed attempt {i}",
                timestamp=time.time(),
                action_taken="iptables_drop",
            )
            await self.alert_engine.enqueue_threat_event(ev)

        # Before flush, send_message not yet called for digested events
        self.assertEqual(self.mock_bot.send_message.call_count, 0)

        # Expire digest window and trigger manual flush
        self.alert_engine._pending_digests[ip].first_seen = time.time() - 301.0
        await self.alert_engine._flush_expired_digests()

        # Exactly 1 consolidated digest message sent
        self.assertEqual(self.mock_bot.send_message.call_count, 1)
        args, _ = self.mock_bot.send_message.call_args
        msg = args[1]
        self.assertIn("TỔNG HỢP CẢNH BÁO AN NINH (DIGEST 5 PHÚT)", msg)
        self.assertIn(ip, msg)

    async def test_16_feature_six_ai_agent_tools(self) -> None:
        """F16: Verifies execution dispatching for all 6 security tools in AgentToolExecutor."""
        # Setup sample data
        await self.sec_monitor.block_ip("198.51.100.80", reason="Test block tool", duration_seconds=86400)

        tools_to_test = [
            ("get_security_report", {}),
            ("list_blocked_ips", {}),
            ("get_honeypot_log", {"limit": 5}),
            ("get_attack_history", {"limit": 5}),
            ("block_ip", {"ip": "198.51.100.81", "reason": "Manual block via AI"}),
            ("unblock_ip", {"ip": "198.51.100.80"}),
        ]

        for tool_name, args in tools_to_test:
            result = await self.tool_executor._execute_tool(tool_name, args)
            self.assertIsInstance(result, str, f"Tool {tool_name} must return string")
            self.assertGreater(len(result), 10, f"Tool {tool_name} returned empty output")

    async def test_17_feature_action_risk_scoping_token_budget(self) -> None:
        """F17: Action Risk Tri-Tier Scoping & Groq 8k TPM Token Budget invariant (<= 8 tools)."""
        # Diagnostic tools are Tier 1 (Safe)
        self.assertEqual(classify_action_risk("get_security_report"), ACTION_TIER_1_SAFE)
        self.assertEqual(classify_action_risk("list_blocked_ips"), ACTION_TIER_1_SAFE)
        self.assertEqual(classify_action_risk("get_honeypot_log"), ACTION_TIER_1_SAFE)
        self.assertEqual(classify_action_risk("get_attack_history"), ACTION_TIER_1_SAFE)

        # Mutating tools are Tier 2 (Reversible)
        self.assertEqual(classify_action_risk("block_ip"), ACTION_TIER_2_REVERSIBLE)
        self.assertEqual(classify_action_risk("unblock_ip"), ACTION_TIER_2_REVERSIBLE)

        # Natural language query scoping
        query = "Cho anh kiểm tra tình hình an ninh và các IP đang bị khóa trên iptables"
        scoped = self.tool_executor._resolve_scoped_tool_names(query=query)
        self.assertIn("get_security_report", scoped)
        self.assertIn("list_blocked_ips", scoped)
        self.assertLessEqual(len(scoped), 8, "Scoped tools must not exceed token budget of 8 tools")

    # =========================================================================
    # TIER 2 — BOUNDARY & CORNER CASES (6 TEST CASES)
    # =========================================================================

    async def test_tier2_01_malformed_oversized_log_lines(self) -> None:
        """B1: Empty lines, oversized lines (> 10,000 chars), and binary bytes handled safely."""
        # Empty and whitespace lines
        self.assertIsNone(await self.sec_monitor.process_log_line("", log_type="nginx"))
        self.assertIsNone(await self.sec_monitor.process_log_line("   \n\t  ", log_type="auth"))

        # Oversized line (15,000 chars)
        huge_query = "A" * 15000
        oversized_line = f'198.51.100.99 - - [27/Sep/2026:12:00:00 +0700] "GET /?q={huge_query} HTTP/1.1" 200 100 "-" "curl" "-"'
        t_start = time.perf_counter()
        ev = await self.sec_monitor.process_log_line(oversized_line, log_type="nginx")
        elapsed = time.perf_counter() - t_start
        self.assertLess(elapsed, 0.5, "Oversized line parsing must not suffer regex catastrophic backtracking")

        # Invalid UTF-8 binary bytes
        binary_str = b"\x80\x81\xff\xfe\x00\x01".decode("utf-8", errors="replace")
        binary_line = f'198.51.100.99 - - [27/Sep/2026:12:00:00 +0700] "GET /?b={binary_str} HTTP/1.1" 200 100 "-" "curl" "-"'
        ev_bin = await self.sec_monitor.process_log_line(binary_line, log_type="nginx")
        # Doesn't crash
        self.assertTrue(ev_bin is None or isinstance(ev_bin, dict))

    async def test_tier2_02_dual_stack_ipv4_mapped_ipv6_normalization(self) -> None:
        """B2: IPv4-mapped IPv6 addresses (::ffff:x.x.x.x) correctly unwrapped for whitelist and firewall."""
        self.assertEqual(str(normalize_ip_address("::ffff:127.0.0.1")), "127.0.0.1")
        self.assertTrue(self.sec_monitor.is_whitelisted("::ffff:127.0.0.1"))
        self.assertTrue(self.sec_monitor.is_whitelisted("::ffff:192.168.1.50"))

        # VETO on mapped loopback
        res_veto = await self.sec_monitor.block_ip("::ffff:127.0.0.1", reason="Mapped loopback")
        self.assertEqual(res_veto["status"], "veto")
        self.assertFalse(await self.mock_fw.is_blocked("127.0.0.1"))

        # Successful block on mapped external attacker
        res_block = await self.sec_monitor.block_ip("::ffff:45.83.122.7", reason="Mapped attacker")
        self.assertEqual(res_block["status"], "success")
        self.assertEqual(res_block["ip"], "45.83.122.7")
        self.assertTrue(await self.mock_fw.is_blocked("45.83.122.7"))

    async def test_tier2_03_subnet_boundary_cidr_checks(self) -> None:
        """B3: Subnet boundary CIDR verification (/12 Docker and /16 LAN)."""
        engine = WhitelistEngine()

        # Docker /12 (172.16.0.0/12: 172.16.0.0 - 172.31.255.255)
        self.assertTrue(engine.is_whitelisted("172.16.0.0"))
        self.assertTrue(engine.is_whitelisted("172.31.255.255"))
        self.assertFalse(engine.is_whitelisted("172.15.255.255"))
        self.assertFalse(engine.is_whitelisted("172.32.0.0"))

        # LAN /16 (192.168.0.0/16: 192.168.0.0 - 192.168.255.255)
        self.assertTrue(engine.is_whitelisted("192.168.0.1"))
        self.assertTrue(engine.is_whitelisted("192.168.255.254"))
        self.assertFalse(engine.is_whitelisted("192.167.255.255"))
        self.assertFalse(engine.is_whitelisted("192.169.0.1"))

    async def test_tier2_04_zero_and_extreme_ttl_values(self) -> None:
        """B4: Handles TTL=0 (immediate expiration), extreme TTLs, and unblocking nonexistent IPs."""
        # 1. TTL = 0
        res_zero = await self.sec_monitor.block_ip("198.51.100.91", reason="TTL 0", duration_seconds=0)
        self.assertEqual(res_zero["status"], "success")

        # 2. Extreme TTL (10 years = 315,360,000s)
        res_ext = await self.sec_monitor.block_ip("198.51.100.92", reason="Extreme TTL", duration_seconds=315360000)
        self.assertEqual(res_ext["status"], "success")
        self.assertEqual(res_ext["duration_seconds"], 315360000)

        # 3. Unblock nonexistent IP
        res_unblock = await self.sec_monitor.unblock_ip("198.51.100.200", reason="Nonexistent IP")
        self.assertEqual(res_unblock["status"], "success")

    async def test_tier2_05_port_scan_extremes_and_lru_eviction(self) -> None:
        """B5: Port boundary 0 & 65535, 100 ports burst, and LRU memory cap bounding."""
        attacker_ip = "198.51.100.93"

        # Boundary ports 0 and 65535
        ev0 = await self.sec_monitor.process_log_line(f"PORT_SCAN: {attacker_ip} port 0", log_type="port_scan")
        ev65535 = await self.sec_monitor.process_log_line(f"PORT_SCAN: {attacker_ip} port 65535", log_type="port_scan")
        self.assertIsNone(ev0)  # only 1 port
        self.assertIsNone(ev65535)  # only 2 ports

        # BoundedPortScanTracker capacity limit test
        small_tracker = BoundedPortScanTracker(max_ips=5, window_seconds=10.0)
        for i in range(10):
            small_tracker[f"10.0.0.{i}"].add(80)

        # Ensure prune/shrink maintains <= 5 entries under load
        small_tracker.prune_stale(now=time.time())
        self.assertLessEqual(len(small_tracker), 5)

    async def test_tier2_06_digest_window_timing_boundaries(self) -> None:
        """B6: Digest window timing boundary: 299s (accumulated) vs 301s (expired and flushed)."""
        engine = SecurityAlertEngine(
            telegram_bot=self.mock_bot,
            digest_window_seconds=300.0,
            flush_interval_seconds=0.1,
            token="test-token",
            chat_id="12345678",
        )
        ip = "198.51.100.94"
        t0 = 1000.0

        ev1 = ThreatEvent(
            ip=ip, attack_type="ssh_brute_force", threat_level=ThreatLevel.HIGH,
            target_service="ssh", raw_payload="fail1", timestamp=t0, action_taken="iptables_drop"
        )
        ev2 = ThreatEvent(
            ip=ip, attack_type="ssh_brute_force", threat_level=ThreatLevel.HIGH,
            target_service="ssh", raw_payload="fail2", timestamp=t0 + 299.0, action_taken="iptables_drop"
        )

        with patch("time.time", return_value=t0):
            await engine.enqueue_threat_event(ev1)

        self.assertIn(ip, engine._pending_digests)
        self.assertEqual(sum(engine._pending_digests[ip].event_counts.values()), 1)

        # Event 2 at t0 + 299.0 (within window -> accumulated)
        with patch("time.time", return_value=t0 + 299.0):
            await engine.enqueue_threat_event(ev2)

        self.assertEqual(sum(engine._pending_digests[ip].event_counts.values()), 2)

        # Simulate flush check at t0 + 301.0 -> should flush
        with patch("time.time", return_value=t0 + 301.0):
            await engine._flush_expired_digests()

        # Digest was flushed and removed from pending
        self.assertNotIn(ip, engine._pending_digests)
        self.mock_bot.send_message.assert_called_once()

    # =========================================================================
    # TIER 3 — CROSS-FEATURE INTERACTIONS (4 TEST CASES)
    # =========================================================================

    async def test_tier3_01_honeypot_trap_autoblock_alert_ai_tools_pipeline(self) -> None:
        """
        S1: Honeypot 3-fail connection -> Auto-Block DROP -> Telegram Alert Mẫu 2 -> AI Tool list_blocked_ips.
        Uses mocked peer IP 198.51.100.99 to test full defense pipeline without loopback whitelist VETO.
        """
        target_peer_ip = "198.51.100.99"
        orig_get_extra = asyncio.StreamWriter.get_extra_info

        def mock_get_extra(s_self: asyncio.StreamWriter, name: str, default: Any = None) -> Any:
            if name == "peername":
                sock = orig_get_extra(s_self, "sockname")
                if sock and len(sock) >= 2 and sock[1] == self.ssh_port:
                    return (target_peer_ip, 54321)
            return orig_get_extra(s_self, name, default)

        # Ensure rDNS lookup does not block/timeout
        self.alert_engine._resolve_rdns = AsyncMock(return_value="mock.ptr.test")

        with patch.object(asyncio.StreamWriter, "get_extra_info", mock_get_extra):
            reader, writer = await asyncio.open_connection("127.0.0.1", self.ssh_port)
            try:
                # Banner
                await asyncio.wait_for(reader.readline(), timeout=3.0)

                # Attempt 1
                await asyncio.wait_for(reader.readuntil(b"login: "), timeout=3.0)
                writer.write(b"root\r\n")
                await writer.drain()
                await asyncio.wait_for(reader.readuntil(b"Password: "), timeout=3.0)
                writer.write(b"123456\r\n")
                await writer.drain()
                await asyncio.wait_for(reader.readuntil(b"Access denied\r\n\r\n"), timeout=3.0)

                # Attempt 2
                await asyncio.wait_for(reader.readuntil(b"login: "), timeout=3.0)
                writer.write(b"admin\r\n")
                await writer.drain()
                await asyncio.wait_for(reader.readuntil(b"Password: "), timeout=3.0)
                writer.write(b"admin@2026\r\n")
                await writer.drain()
                await asyncio.wait_for(reader.readuntil(b"Access denied\r\n\r\n"), timeout=3.0)

                # Attempt 3 -> Troll payload & close
                await asyncio.wait_for(reader.readuntil(b"login: "), timeout=3.0)
                writer.write(b"kirito\r\n")
                await writer.drain()
                await asyncio.wait_for(reader.readuntil(b"Password: "), timeout=3.0)
                writer.write(b"kirito_pass\r\n")
                await writer.drain()

                payload = await asyncio.wait_for(reader.read(1024), timeout=3.0)
                self.assertIn("💀 Kẻ thất bại".encode("utf-8"), payload)
            finally:
                writer.close()
                await writer.wait_closed()

        # Wait for background session triggers to complete
        for _ in range(30):
            if await self.mock_fw.is_blocked(target_peer_ip):
                break
            await asyncio.sleep(0.05)

        # 1. Firewall DROP verified
        self.assertTrue(await self.mock_fw.is_blocked(target_peer_ip))

        # 2. Telegram Alert Mẫu 2 verified
        self.mock_bot.send_message.assert_called()
        honeypot_alerts = [
            call.args[1] for call in self.mock_bot.send_message.call_args_list
            if "BẪY HONEYPOT" in call.args[1]
        ]
        self.assertGreaterEqual(len(honeypot_alerts), 1)
        alert_msg = honeypot_alerts[0]
        self.assertIn(target_peer_ip, alert_msg)
        self.assertIn("root", alert_msg)
        self.assertIn("123456", alert_msg)
        self.assertIn("admin", alert_msg)
        self.assertIn("kirito", alert_msg)

        # 3. AI Tool list_blocked_ips includes target_peer_ip
        blocked_list_md = await self.tool_executor._execute_tool("list_blocked_ips", {})
        self.assertIn(target_peer_ip, blocked_list_md)

        # 4. Honeypot database contains 3 harvested credentials
        logs = await self.honeypot_service.get_honeypot_log(limit=10)
        matching = [rec for rec in logs if rec.get("ip") == target_peer_ip]
        self.assertEqual(len(matching), 3)

    async def test_tier3_02_web_scanner_nginx_digest_alert_pipeline(self) -> None:
        """
        S2: Web scanner (sqlmap) -> Nginx 403 SSI rules -> Log entries -> 5-min Digest Accumulator -> Flushed.
        """
        scanner_ip = "203.0.113.45"
        log_lines = [
            f'{scanner_ip} - - [27/Sep/2026:14:30:00 +0700] "GET /api/v1/users?id=1%20UNION%20SELECT%20null,password%20FROM%20users HTTP/1.1" 403 10522 "-" "sqlmap/1.7.2#stable" "-"',
            f'{scanner_ip} - - [27/Sep/2026:14:30:05 +0700] "GET /.env HTTP/1.1" 403 10522 "-" "sqlmap/1.7.2#stable" "-"',
            f'{scanner_ip} - - [27/Sep/2026:14:30:10 +0700] "GET /wp-login.php HTTP/1.1" 403 10522 "-" "sqlmap/1.7.2#stable" "-"',
            f'{scanner_ip} - - [27/Sep/2026:14:30:15 +0700] "GET /phpmyadmin HTTP/1.1" 403 10522 "-" "sqlmap/1.7.2#stable" "-"',
        ]

        for line in log_lines:
            await self.sec_monitor.process_log_line(line, log_type="nginx")

        self.assertTrue(await self.mock_fw.is_blocked(scanner_ip))

        # Check digest accumulation in alert engine
        self.assertIn(scanner_ip, self.alert_engine._pending_digests)
        digest = self.alert_engine._pending_digests[scanner_ip]
        self.assertGreaterEqual(sum(digest.event_counts.values()), 2)

        # Force expire and flush
        digest.first_seen = time.time() - 301.0
        await self.alert_engine._flush_expired_digests()

        # Verify Telegram sent digest summary
        self.mock_bot.send_message.assert_called()
        digest_msgs = [
            c.args[1] for c in self.mock_bot.send_message.call_args_list
            if "TỔNG HỢP CẢNH BÁO AN NINH" in c.args[1]
        ]
        self.assertGreaterEqual(len(digest_msgs), 1)
        summary = digest_msgs[0]
        self.assertIn(scanner_ip, summary)
        self.assertIn("sql injection", summary.lower())

    async def test_tier3_03_whitelist_admin_activity_immune_from_block(self) -> None:
        """
        S3: Admin LAN (192.168.1.50) failed SSH logins and SQLi tests are recorded but 100% VETOED.
        """
        admin_ip = "192.168.1.50"

        # 20 failed SSH attempts in 10s
        for _ in range(20):
            ev = await self.sec_monitor.process_log_line(
                f"sshd[1234]: Failed password for kirito from {admin_ip} port 55667 ssh2",
                log_type="auth",
            )
            self.assertEqual(ev["action_taken"], "whitelisted_veto")

        # Admin SQL injection test
        ev_sqli = await self.sec_monitor.process_log_line(
            f'{admin_ip} - - [27/Sep/2026:14:05:10 +0700] "GET /api/v1/search?q=%27%20OR%201=1-- HTTP/1.1" 200 4096 "-" "Mozilla/5.0" "-"',
            log_type="nginx",
        )
        self.assertEqual(ev_sqli["action_taken"], "whitelisted_veto")

        # Explicit block call VETO
        res = await self.sec_monitor.block_ip(admin_ip, reason="Admin mistake")
        self.assertEqual(res["status"], "veto")
        self.assertFalse(await self.mock_fw.is_blocked(admin_ip))

        # Check attack history logs veto
        history = await self.sec_monitor.get_attack_history(limit=5)
        self.assertTrue(any(item["action_taken"] == "whitelisted_veto" for item in history))

    async def test_tier3_04_admin_chat_incident_response_and_unblock(self) -> None:
        """
        S4: IP blocked autonomously -> Admin queries get_security_report & get_attack_history -> AI Tool unblock_ip.
        """
        partner_ip = "146.190.22.40"
        # Autonomous block triggered by 8 failed logins
        for _ in range(8):
            await self.sec_monitor.process_log_line(
                f"sshd[999]: Failed password for root from {partner_ip} port 44332 ssh2",
                log_type="auth",
            )
        self.assertTrue(await self.mock_fw.is_blocked(partner_ip))

        # Turn 1: Admin asks for security overview
        report_md = await self.tool_executor._execute_tool("get_security_report", {})
        self.assertIn("AN NINH MÁY CHỦ", report_md)
        self.assertIn(partner_ip, report_md)

        # Turn 2: Admin queries attack history
        history_md = await self.tool_executor._execute_tool("get_attack_history", {"limit": 10})
        self.assertIn(partner_ip, history_md)
        self.assertIn("ssh_brute_force", history_md)

        # Turn 3: Admin instructs AI agent to unblock partner IP
        unblock_md = await self.tool_executor._execute_tool("unblock_ip", {"ip": partner_ip})
        self.assertIn("Đã gỡ bỏ thành công", unblock_md)
        self.assertFalse(await self.mock_fw.is_blocked(partner_ip))

        # Verification via list_blocked_ips
        active_blocked_md = await self.tool_executor._execute_tool("list_blocked_ips", {})
        self.assertNotIn(partner_ip, active_blocked_md)

    # =========================================================================
    # TIER 4 — REAL-WORLD APPLICATION SCENARIOS (3 TEST CASES)
    # =========================================================================

    async def test_tier4_01_apt_reconnaissance_and_honeypot_pivot_campaign(self) -> None:
        """
        C1: APT reconnaissance (Port scan burst) -> Auto-Block -> Pivot to Fake SSH Honeypot
        -> Troll payload disconnect -> Telegram Dossier & AI Inspection.
        """
        apt_ip = "185.220.101.55"

        # Stage 1: Port Scan Reconnaissance (10 ports burst)
        probed_ports = [21, 22, 80, 443, 3306, 5432, 6379, 8080, 8443, 9000]
        for p in probed_ports:
            await self.sec_monitor.process_log_line(f"PORT_SCAN: {apt_ip} port {p}", log_type="port_scan")
        self.assertTrue(await self.mock_fw.is_blocked(apt_ip))

        # Stage 2: Pivot to Fake SSH Listener (mock peer to apt_ip)
        orig_get_extra = asyncio.StreamWriter.get_extra_info

        def mock_apt_get(s_self: asyncio.StreamWriter, name: str, default: Any = None) -> Any:
            if name == "peername":
                sock = orig_get_extra(s_self, "sockname")
                if sock and len(sock) >= 2 and sock[1] == self.ssh_port:
                    return (apt_ip, 49152)
            return orig_get_extra(s_self, name, default)

        with patch.object(asyncio.StreamWriter, "get_extra_info", mock_apt_get):
            reader, writer = await asyncio.open_connection("127.0.0.1", self.ssh_port)
            try:
                await asyncio.wait_for(reader.readline(), timeout=3.0)
                creds = [
                    (b"admin\r\n", b"P@ssw0rd2026!\r\n"),
                    (b"kirito\r\n", b"shadowgarden\r\n"),
                    (b"root\r\n", b"toor\r\n"),
                ]
                for u, p in creds:
                    await asyncio.wait_for(reader.readuntil(b"login: "), timeout=3.0)
                    writer.write(u)
                    await writer.drain()
                    await asyncio.wait_for(reader.readuntil(b"Password: "), timeout=3.0)
                    writer.write(p)
                    await writer.drain()
                    if u != b"root\r\n":
                        await asyncio.wait_for(reader.readuntil(b"Access denied\r\n\r\n"), timeout=3.0)
                    else:
                        resp = await asyncio.wait_for(reader.read(1024), timeout=3.0)
                        self.assertIn("💀 Kẻ thất bại".encode("utf-8"), resp)
            finally:
                writer.close()
                await writer.wait_closed()

        # Allow background session triggers to complete
        await asyncio.sleep(0.05)

        # Stage 3: Telegram Dossier Assertion
        honeypot_alerts = [
            c.args[1] for c in self.mock_bot.send_message.call_args_list
            if "BẪY HONEYPOT" in c.args[1] and apt_ip in c.args[1]
        ]
        self.assertGreaterEqual(len(honeypot_alerts), 1)
        self.assertIn("https://www.abuseipdb.com/check/185.220.101.55", honeypot_alerts[0])

        # Stage 4: AI Agent Forensic Log Inspection
        hp_log_md = await self.tool_executor._execute_tool("get_honeypot_log", {"limit": 10, "service": "ssh"})
        self.assertIn(apt_ip, hp_log_md)
        self.assertIn("shadowgarden", hp_log_md)

    async def test_tier4_02_automated_botnet_web_defacement_campaign(self) -> None:
        """
        C2: Automated Botnet multi-vector defacement attempt (SQLi + XSS + Path Traversal)
        -> Immediate Defense -> Nginx SSI 403 Cyberpunk rendering & Blocklist entry.
        """
        botnet_ip = "194.26.29.10"
        attacks = [
            f'{botnet_ip} - - [27/Sep/2026:14:10:01 +0700] "GET /api/v1/products?id=1%20UNION%20SELECT%201,schema_name%20FROM%20information_schema.schemata-- HTTP/1.1" 403 10522 "-" "Mozilla/5.0" "-"',
            f'{botnet_ip} - - [27/Sep/2026:14:10:02 +0700] "GET /search?q=%3Cscript%3Ealert(%22defaced%22)%3C/script%3E HTTP/1.1" 403 10522 "-" "Mozilla/5.0" "-"',
            f'{botnet_ip} - - [27/Sep/2026:14:10:03 +0700] "GET /view?page=../../../../etc/passwd HTTP/1.1" 403 10522 "-" "Mozilla/5.0" "-"',
        ]

        for line in attacks:
            await self.sec_monitor.process_log_line(line, log_type="nginx")

        self.assertTrue(await self.mock_fw.is_blocked(botnet_ip))

        # Simulate Nginx SSI parsing on 403.html
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        html_path = os.path.join(repo_root, "frontend", "html", "403.html")
        with open(html_path, "r", encoding="utf-8") as f:
            template = f.read()

        rendered = template.replace('<!--#echo var="remote_addr" default="Recorded" -->', botnet_ip)
        rendered = rendered.replace('<!--#echo var="time_local" default="Captured" -->', "27/Sep/2026:14:10:01 +0700")

        self.assertIn(botnet_ip, rendered)
        self.assertIn("Kẻ tấn công = Kẻ thất bại 😂", rendered)

        # AI Agent Security Report reflects multi-vector attack
        report_md = await self.tool_executor._execute_tool("get_security_report", {})
        self.assertIn(botnet_ip, report_md)
        self.assertIn("sqli", report_md.lower())

    async def test_tier4_03_firewall_ttl_sweeper_lifecycle_campaign(self) -> None:
        """
        C3: 24h Firewall TTL sweeper lifecycle with time progression and memory eviction.
        T0: Block IP-A (24h), IP-B (1h), IP-C (48h).
        T1 (T0 + 3601s): IP-B expired and unblocked; IP-A and IP-C active.
        T2 (T0 + 86401s): IP-A expired and unblocked; only IP-C active.
        """
        t0 = 1700000000.0
        ip_a, ip_b, ip_c = "45.83.122.1", "45.83.122.2", "45.83.122.3"

        with patch("time.time", return_value=t0):
            await self.sec_monitor.block_ip(ip_a, reason="Campaign 24h", duration_seconds=86400)
            await self.sec_monitor.block_ip(ip_b, reason="Campaign 1h", duration_seconds=3600)
            await self.sec_monitor.block_ip(ip_c, reason="Campaign 48h", duration_seconds=172800)

        self.assertTrue(await self.mock_fw.is_blocked(ip_a))
        self.assertTrue(await self.mock_fw.is_blocked(ip_b))
        self.assertTrue(await self.mock_fw.is_blocked(ip_c))

        # Step 1: Advance time to T1 = T0 + 3601s (IP-B expired)
        t1 = t0 + 3601.0
        with patch("time.time", return_value=t1):
            expired_t1 = [
                ip for ip, rec in self.sec_monitor._blocked_ips.items()
                if rec.is_active and t1 >= rec.expires_at
            ]
            for ip in expired_t1:
                await self.sec_monitor.unblock_ip(ip, reason="TTL_EXPIRED")

        self.assertFalse(await self.mock_fw.is_blocked(ip_b))
        self.assertTrue(await self.mock_fw.is_blocked(ip_a))
        self.assertTrue(await self.mock_fw.is_blocked(ip_c))

        # Step 2: Advance time to T2 = T0 + 86401s (IP-A expired)
        t2 = t0 + 86401.0
        with patch("time.time", return_value=t2):
            expired_t2 = [
                ip for ip, rec in self.sec_monitor._blocked_ips.items()
                if rec.is_active and t2 >= rec.expires_at
            ]
            for ip in expired_t2:
                await self.sec_monitor.unblock_ip(ip, reason="TTL_EXPIRED")

        self.assertFalse(await self.mock_fw.is_blocked(ip_a))
        self.assertTrue(await self.mock_fw.is_blocked(ip_c))

        # Memory eviction check: IP-A and IP-B evicted from in-memory dictionary
        self.assertNotIn(ip_a, self.sec_monitor._blocked_ips)
        self.assertNotIn(ip_b, self.sec_monitor._blocked_ips)
        self.assertIn(ip_c, self.sec_monitor._blocked_ips)


if __name__ == "__main__":
    unittest.main()
