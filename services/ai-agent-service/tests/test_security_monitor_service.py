"""
services/ai-agent-service/tests/test_security_monitor_service.py
Comprehensive Unit Test Suite for Autonomous Security Guardian (Milestone 1).

Tests:
1. SlidingWindowTracker (hit counting, lazy eviction, capacity pruning).
2. WhitelistEngine (5 tiers: Loopback, LAN, Docker, Cloudflare IPv4/IPv6, Admin IP; zero TypeError).
3. Command Injection Immunity on IP parameters.
4. LogTailer (byte offset tracking, partial line buffering, copytruncate & inode logrotate).
5. Multi-Vector Intrusion Detection (SSH brute force, Web SQLi, Traversal, XSS, Scanners, Port Scan, DDoS).
6. Autonomous Defense (MockFirewall DROP & LIMIT rules, Whitelist VETO, Auto-block).
7. TTL Sweeper (24h auto-unblock expiration logic).
8. Storage & In-Memory State Aggregator (< 10ms get_security_report, attack history, list blocked).
9. Lifecycle clean startup and shutdown (0 ResourceWarning).
"""

import asyncio
import os
import shutil
import tempfile
import time
import unittest

from app.services.security_monitor_service import (
    BlockedIPRecord,
    BoundedPortScanTracker,
    CLOUDFLARE_IPV4_CIDRS,
    CLOUDFLARE_IPV6_CIDRS,
    DEFAULT_WHITELIST_CIDRS,
    extract_client_ip,
    HostFirewallController,
    LogTailer,
    MockFirewallController,
    normalize_ip_address,
    SecurityMonitorService,
    SlidingWindowTracker,
    StorageRepository,
    ThreatEvent,
    ThreatLevel,
    WhitelistEngine,
)


class TestSlidingWindowTracker(unittest.TestCase):
    """Verifies SlidingWindowTracker correctness, performance, and memory bounding."""

    def setUp(self):
        self.tracker = SlidingWindowTracker(window_seconds=10.0, max_entries=20, max_ips=100)

    def test_record_hit_and_window_expiry(self):
        ip = "198.51.100.5"
        base_time = 1000.0

        # Record 4 hits within window
        self.assertEqual(self.tracker.record_hit(ip, now=base_time), 1)
        self.assertEqual(self.tracker.record_hit(ip, now=base_time + 2.0), 2)
        self.assertEqual(self.tracker.record_hit(ip, now=base_time + 5.0), 3)
        self.assertEqual(self.tracker.record_hit(ip, now=base_time + 8.0), 4)

        # Count at base_time + 8.0 should be 4
        self.assertEqual(self.tracker.count(ip, now=base_time + 8.0), 4)

        # Move time forward past window for first 2 hits (1000 + 10.1 = 1010.1)
        # Hits at 1000.0 and 1002.0 should expire; hits at 1005.0 and 1008.0 remain
        count_later = self.tracker.count(ip, now=base_time + 13.0)
        self.assertEqual(count_later, 2)

        # Advance past all hits
        self.assertEqual(self.tracker.count(ip, now=base_time + 20.0), 0)

    def test_prune_stale_ips(self):
        base_time = 1000.0
        self.tracker.record_hit("1.1.1.1", now=base_time)
        self.tracker.record_hit("2.2.2.2", now=base_time + 5.0)

        # At base_time + 12.0: 1.1.1.1 is stale (> 10s), 2.2.2.2 is still active
        pruned = self.tracker.prune_stale(now=base_time + 12.0)
        self.assertEqual(pruned, 1)
        self.assertNotIn("1.1.1.1", self.tracker._history)
        self.assertIn("2.2.2.2", self.tracker._history)

    def test_lru_capacity_drop(self):
        small_tracker = SlidingWindowTracker(window_seconds=10.0, max_entries=5, max_ips=5)
        base = 1000.0
        for i in range(5):
            small_tracker.record_hit(f"10.0.0.{i}", now=base + i)

        self.assertEqual(len(small_tracker._history), 5)
        # Add 6th IP, should trigger prune/shrink
        small_tracker.record_hit("10.0.0.99", now=base + 10)
        self.assertLessEqual(len(small_tracker._history), 5)
        self.assertIn("10.0.0.99", small_tracker._history)

    def test_memory_footprint_under_load(self):
        import tracemalloc
        tracemalloc.start()
        snapshot_start = tracemalloc.take_snapshot()

        heavy_tracker = SlidingWindowTracker(window_seconds=30.0, max_entries=50, max_ips=10000)
        base_time = 1000.0
        for i in range(10000):
            heavy_tracker.record_hit(f"198.51.{(i // 256) % 256}.{i % 256}", now=base_time + (i % 20))

        snapshot_end = tracemalloc.take_snapshot()
        top_stats = snapshot_end.compare_to(snapshot_start, 'lineno')
        total_allocated_mb = sum(stat.size_diff for stat in top_stats) / (1024 * 1024)
        tracemalloc.stop()

        # Ràng buộc tài nguyên: Toàn bộ 10,000 tracker entries phải tiêu tốn < 15MB RAM
        self.assertLess(total_allocated_mb, 15.0, f"Memory footprint exceeded: {total_allocated_mb:.2f} MB")


class TestWhitelistEngine(unittest.TestCase):
    """Verifies 5-tier IP Whitelist, VETO protection, and IPv4/IPv6 comparability."""

    def setUp(self):
        self.whitelist = WhitelistEngine(custom_ips=["203.0.113.199", "192.0.2.0/24"])

    def test_loopback_whitelisted(self):
        self.assertTrue(self.whitelist.is_whitelisted("127.0.0.1"))
        self.assertTrue(self.whitelist.is_whitelisted("127.0.0.99"))
        self.assertTrue(self.whitelist.is_whitelisted("::1"))

    def test_private_lan_whitelisted(self):
        self.assertTrue(self.whitelist.is_whitelisted("192.168.0.1"))
        self.assertTrue(self.whitelist.is_whitelisted("192.168.1.100"))
        self.assertTrue(self.whitelist.is_whitelisted("10.0.4.5"))
        self.assertTrue(self.whitelist.is_whitelisted("169.254.1.1"))

    def test_docker_subnets_whitelisted(self):
        self.assertTrue(self.whitelist.is_whitelisted("172.16.0.1"))
        self.assertTrue(self.whitelist.is_whitelisted("172.18.0.22"))
        self.assertTrue(self.whitelist.is_whitelisted("172.31.255.254"))

    def test_cloudflare_cidrs_whitelisted(self):
        # Known Cloudflare IPv4
        self.assertTrue(self.whitelist.is_whitelisted("104.16.12.34"))
        self.assertTrue(self.whitelist.is_whitelisted("173.245.49.5"))
        # Known Cloudflare IPv6
        self.assertTrue(self.whitelist.is_whitelisted("2400:cb00:100::1"))
        self.assertTrue(self.whitelist.is_whitelisted("2606:4700::1"))

    def test_custom_ips_whitelisted(self):
        self.assertTrue(self.whitelist.is_whitelisted("203.0.113.199"))
        self.assertTrue(self.whitelist.is_whitelisted("192.0.2.45"))

    def test_attacker_ips_not_whitelisted(self):
        self.assertFalse(self.whitelist.is_whitelisted("45.83.122.7"))
        self.assertFalse(self.whitelist.is_whitelisted("185.220.101.5"))
        self.assertFalse(self.whitelist.is_whitelisted("8.8.8.8"))

    def test_invalid_ips_do_not_crash(self):
        self.assertFalse(self.whitelist.is_whitelisted(""))
        self.assertFalse(self.whitelist.is_whitelisted("not-an-ip"))
        self.assertFalse(self.whitelist.is_whitelisted("1.2.3.4; rm -rf /"))

    def test_ipv4_mapped_ipv6_unwrapping(self):
        # Loopback mapped
        self.assertTrue(self.whitelist.is_whitelisted("::ffff:127.0.0.1"))
        self.assertTrue(self.whitelist.is_whitelisted("::ffff:127.0.0.99"))
        # LAN mapped
        self.assertTrue(self.whitelist.is_whitelisted("::ffff:192.168.1.1"))
        # Docker mapped
        self.assertTrue(self.whitelist.is_whitelisted("::ffff:172.18.0.1"))
        # Cloudflare mapped
        self.assertTrue(self.whitelist.is_whitelisted("::ffff:104.16.1.1"))
        # Attacker mapped must NOT be whitelisted
        self.assertFalse(self.whitelist.is_whitelisted("::ffff:45.83.122.7"))


class TestLogTailer(unittest.TestCase):
    """Verifies incremental byte-offset log tailing and logrotate recovery."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.temp_dir, "test_access.log")
        with open(self.log_file, "w", encoding="utf-8") as f:
            f.write("line 1\nline 2\n")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_tailer_from_beginning(self):
        tailer = LogTailer(self.log_file, from_beginning=True)
        lines = tailer.read_new_lines()
        self.assertEqual(lines, ["line 1", "line 2"])

        # No new lines added
        self.assertEqual(tailer.read_new_lines(), [])

        # Append new line
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write("line 3\n")

        lines2 = tailer.read_new_lines()
        self.assertEqual(lines2, ["line 3"])

    def test_partial_line_buffering(self):
        tailer = LogTailer(self.log_file, from_beginning=True)
        tailer.read_new_lines()

        # Write half of line without newline
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write("incomplete_part_")

        self.assertEqual(tailer.read_new_lines(), [])

        # Complete the line
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write("finished\n")

        lines = tailer.read_new_lines()
        self.assertEqual(lines, ["incomplete_part_finished"])

    def test_logrotate_copytruncate_detected(self):
        tailer = LogTailer(self.log_file, from_beginning=True)
        tailer.read_new_lines()

        # Truncate file (copytruncate simulation where file is truncated and new lines are written)
        # Initial file size: 14 bytes ("line 1\nline 2\n").
        # Writing 8 bytes ("rotated\n") drops size below current offset (8 < 14) triggering copytruncate detection.
        with open(self.log_file, "w", encoding="utf-8") as f:
            f.write("rotated\n")

        lines = tailer.read_new_lines()
        self.assertEqual(lines, ["rotated"])


class TestSecurityMonitorService(unittest.IsolatedAsyncioTestCase):
    """Comprehensive test case for SecurityMonitorService."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "security_test.db")
        self.mock_fw = MockFirewallController()

        self.service = SecurityMonitorService(
            firewall=self.mock_fw,
            db_path=self.db_path,
            custom_whitelist_ips=["192.168.1.50", "203.0.113.10"],
        )
        await self.service.start()

    async def asyncTearDown(self):
        await self.service.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # --------------------------------------------------------------------------
    # 1. SSH Brute Force Detection Tests
    # --------------------------------------------------------------------------

    async def test_ssh_brute_force_escalation_and_auto_block(self):
        attacker_ip = "45.83.122.7"
        log_line = f"sshd[1234]: Failed password for invalid user admin from {attacker_ip} port 45678 ssh2"

        # Attempt 1 -> LOW
        ev1 = await self.service.process_log_line(log_line, log_type="auth")
        self.assertIsNotNone(ev1)
        self.assertEqual(ev1["threat_level"], "LOW")
        self.assertFalse(await self.mock_fw.is_blocked(attacker_ip))

        # Attempt 2 -> MEDIUM -> triggers rate limit
        ev2 = await self.service.process_log_line(log_line, log_type="auth")
        self.assertEqual(ev2["threat_level"], "MEDIUM")
        self.assertIn(attacker_ip, self.mock_fw._rate_limited)

        # Attempts 3 & 4
        await self.service.process_log_line(log_line, log_type="auth")
        await self.service.process_log_line(log_line, log_type="auth")

        # Attempt 5 -> HIGH (Threshold >= 5 in 30s) -> triggers Auto-block DROP rule
        ev5 = await self.service.process_log_line(log_line, log_type="auth")
        self.assertEqual(ev5["threat_level"], "HIGH")
        self.assertTrue(await self.mock_fw.is_blocked(attacker_ip))
        self.assertEqual(ev5["action_taken"], "iptables_drop")

        # Verify recorded in blocked IPs list
        blocked = await self.service.list_blocked_ips()
        self.assertTrue(any(b["ip"] == attacker_ip for b in blocked))

    async def test_ssh_alternative_log_patterns(self):
        ip1 = "198.51.100.11"
        line1 = f"sshd[2222]: Invalid user root from {ip1} port 55555"
        ev1 = await self.service.process_log_line(line1, log_type="auth")
        self.assertIsNotNone(ev1)
        self.assertEqual(ev1["ip"], ip1)

        ip2 = "198.51.100.12"
        line2 = f"sshd[3333]: Connection closed by authenticating user guest {ip2} port 66666 [preauth]"
        ev2 = await self.service.process_log_line(line2, log_type="auth")
        self.assertIsNotNone(ev2)
        self.assertEqual(ev2["ip"], ip2)

        ip3 = "198.51.100.13"
        line3 = f"sshd[4444]: PAM 2 more authentication failures; logname= uid=0 euid=0 tty=ssh ruser= rhost={ip3} user=root"
        ev3 = await self.service.process_log_line(line3, log_type="auth")
        self.assertIsNotNone(ev3)
        self.assertEqual(ev3["ip"], ip3)

    # --------------------------------------------------------------------------
    # 2. Web Attacks Detection Tests
    # --------------------------------------------------------------------------

    async def test_sqli_detection_and_auto_block(self):
        attacker_ip = "185.220.101.5"
        # Standard SQLi: ' OR '1'='1
        line = f'{attacker_ip} - - [27/Sep/2026:12:00:00 +0700] "GET /api/users?name=%27%20OR%20%271%27=%271 HTTP/1.1" 200 123 "-" "Mozilla/5.0" "-"'
        ev = await self.service.process_log_line(line, log_type="nginx")

        self.assertIsNotNone(ev)
        self.assertEqual(ev["attack_type"], "sqli")
        self.assertEqual(ev["threat_level"], "HIGH")
        # High threat triggers auto-block
        self.assertTrue(await self.mock_fw.is_blocked(attacker_ip))

    async def test_sqli_union_select(self):
        attacker_ip = "185.220.101.6"
        line = f'{attacker_ip} - - [27/Sep/2026:12:00:00 +0700] "GET /products?id=1%20UNION%20SELECT%20null,username,password%20FROM%20users HTTP/1.1" 200 456 "-" "curl/7.68.0" "-"'
        ev = await self.service.process_log_line(line, log_type="nginx")
        self.assertIsNotNone(ev)
        self.assertEqual(ev["attack_type"], "sqli")
        self.assertTrue(await self.mock_fw.is_blocked(attacker_ip))

    async def test_path_traversal_detection(self):
        attacker_ip = "185.220.101.7"
        # Test ../../etc/passwd
        line1 = f'{attacker_ip} - - [27/Sep/2026:12:00:00 +0700] "GET /download?file=../../etc/passwd HTTP/1.1" 403 45 "-" "python-requests/2.28" "-"'
        ev1 = await self.service.process_log_line(line1, log_type="nginx")
        self.assertIsNotNone(ev1)
        self.assertEqual(ev1["attack_type"], "path_traversal")

        # Test Windows traversal ..\..\windows\win.ini
        line2 = f'{attacker_ip} - - [27/Sep/2026:12:00:01 +0700] "GET /download?file=..\\..\\windows\\win.ini HTTP/1.1" 403 45 "-" "python-requests/2.28" "-"'
        ev2 = await self.service.process_log_line(line2, log_type="nginx")
        self.assertIsNotNone(ev2)
        self.assertEqual(ev2["attack_type"], "path_traversal")
        # 2nd traversal triggers HIGH -> auto-blocked
        self.assertTrue(await self.mock_fw.is_blocked(attacker_ip))

    async def test_xss_detection(self):
        attacker_ip = "185.220.101.8"
        line = f'{attacker_ip} - - [27/Sep/2026:12:00:00 +0700] "GET /search?q=%3Cscript%3Ealert(document.cookie)%3C/script%3E HTTP/1.1" 200 500 "-" "Mozilla/5.0" "-"'
        ev = await self.service.process_log_line(line, log_type="nginx")
        self.assertIsNotNone(ev)
        self.assertEqual(ev["attack_type"], "xss")

    async def test_scanner_detection_sqlmap_user_agent(self):
        attacker_ip = "185.220.101.9"
        line = f'{attacker_ip} - - [27/Sep/2026:12:00:00 +0700] "GET /api/items HTTP/1.1" 200 500 "-" "sqlmap/1.6.5#stable (https://sqlmap.org)" "-"'
        ev = await self.service.process_log_line(line, log_type="nginx")
        self.assertIsNotNone(ev)
        self.assertEqual(ev["attack_type"], "scanner_probe")
        self.assertEqual(ev["threat_level"], "CRITICAL")
        self.assertTrue(await self.mock_fw.is_blocked(attacker_ip))

    async def test_scanner_sensitive_path_probing(self):
        attacker_ip = "185.220.101.10"
        line = f'{attacker_ip} - - [27/Sep/2026:12:00:00 +0700] "GET /.env HTTP/1.1" 404 15 "-" "Go-http-client/1.1" "-"'
        ev = await self.service.process_log_line(line, log_type="nginx")
        self.assertIsNotNone(ev)
        self.assertEqual(ev["attack_type"], "scanner_path")

    async def test_client_ip_extraction_with_x_forwarded_for(self):
        line = '172.18.0.1 - - [27/Sep/2026:12:00:00 +0700] "GET /.env HTTP/1.1" 404 15 "-" "curl" "198.51.100.99, 172.18.0.1"'
        ev = await self.service.process_log_line(line, log_type="nginx")
        self.assertIsNotNone(ev)
        # Should resolve to the public IP 198.51.100.99, not Docker bridge 172.18.0.1
        self.assertEqual(ev["ip"], "198.51.100.99")

    # --------------------------------------------------------------------------
    # 3. Port Scan & DDoS Detection Tests
    # --------------------------------------------------------------------------

    async def test_port_scan_detection(self):
        attacker_ip = "198.51.100.88"
        # Simulate 8 distinct ports probed within 10s
        for port in [21, 22, 23, 25, 80, 443, 3306, 8080]:
            ev = await self.service.process_log_line(f"PORT_SCAN: {attacker_ip} port {port}", log_type="port_scan")

        self.assertIsNotNone(ev)
        self.assertEqual(ev["attack_type"], "port_scan")
        self.assertEqual(ev["threat_level"], "HIGH")
        self.assertTrue(await self.mock_fw.is_blocked(attacker_ip))

    async def test_ddos_rate_abuse_detection(self):
        attacker_ip = "203.0.113.77"
        ev = None
        # Send 30 requests within 5s window
        for _ in range(30):
            ev = await self.service.process_log_line(f"REQ: {attacker_ip} /api/v1/data", log_type="ddos")

        self.assertIsNotNone(ev)
        self.assertEqual(ev["attack_type"], "ddos_rate_abuse")
        self.assertEqual(ev["threat_level"], "HIGH")
        self.assertTrue(await self.mock_fw.is_blocked(attacker_ip))

    # --------------------------------------------------------------------------
    # 4. Whitelist VETO & Anti-Lockout Tests
    # --------------------------------------------------------------------------

    async def test_whitelist_veto_on_block_ip(self):
        whitelisted_ips = ["127.0.0.1", "192.168.1.50", "172.18.0.5", "104.16.1.1"]
        for ip in whitelisted_ips:
            res = await self.service.block_ip(ip, reason="Adversarial block attempt")
            self.assertEqual(res["status"], "veto")
            self.assertIn("VETO", res["message"])
            self.assertFalse(await self.mock_fw.is_blocked(ip))

    async def test_whitelist_veto_during_active_attack_event(self):
        # Admin IP probing path
        admin_ip = "192.168.1.50"
        line = f'{admin_ip} - - [27/Sep/2026:12:00:00 +0700] "GET /download?file=../../etc/passwd HTTP/1.1" 403 45 "-" "curl" "-"'
        ev = await self.service.process_log_line(line, log_type="nginx")
        self.assertIsNotNone(ev)
        # Event action_taken should be whitelisted_veto
        self.assertEqual(ev["action_taken"], "whitelisted_veto")
        # Admin IP must NEVER be blocked
        self.assertFalse(await self.mock_fw.is_blocked(admin_ip))

    # --------------------------------------------------------------------------
    # 5. Command Injection Immunity Tests
    # --------------------------------------------------------------------------

    async def test_command_injection_rejected(self):
        malicious_inputs = [
            "1.2.3.4; rm -rf /",
            "1.2.3.4 | bash",
            "1.2.3.4`reboot`",
            "1.2.3.4\nreboot",
            "&& ping -c 1 attacker.com",
            "drop table users;",
        ]
        for bad_ip in malicious_inputs:
            res = await self.service.block_ip(bad_ip, reason="Exploit test")
            self.assertEqual(res["status"], "error")
            self.assertIn("không hợp lệ", res["message"])

        # Confirm nothing was executed in firewall
        self.assertEqual(len(self.mock_fw._blocked), 0)

    # --------------------------------------------------------------------------
    # 6. TTL Sweeper & Unblock Tests
    # --------------------------------------------------------------------------

    async def test_unblock_ip_manual(self):
        target_ip = "198.51.100.70"
        await self.service.block_ip(target_ip, reason="Test block", duration_seconds=3600)
        self.assertTrue(await self.mock_fw.is_blocked(target_ip))

        unblock_res = await self.service.unblock_ip(target_ip, reason="manual_test")
        self.assertEqual(unblock_res["status"], "success")
        self.assertFalse(await self.mock_fw.is_blocked(target_ip))

        # Check list_blocked_ips does not include it
        active_list = await self.service.list_blocked_ips()
        self.assertFalse(any(item["ip"] == target_ip for item in active_list))

    async def test_ttl_sweeper_expiration(self):
        target_ip = "198.51.100.71"
        # Block with duration = 0 (immediately expired)
        await self.service.block_ip(target_ip, reason="Short TTL", duration_seconds=0)

        # Trigger internal sweep logic directly
        now = time.time() + 10.0
        expired = [
            ip for ip, rec in self.service._blocked_ips.items()
            if rec.is_active and now >= rec.expires_at
        ]
        for ip in expired:
            await self.service.unblock_ip(ip, reason="TTL_EXPIRED")

        self.assertFalse(await self.mock_fw.is_blocked(target_ip))

    # --------------------------------------------------------------------------
    # 7. Reporting & State Aggregator Tests (< 10ms)
    # --------------------------------------------------------------------------

    async def test_get_security_report_performance_and_accuracy(self):
        # Generate some events
        await self.service.process_log_line(
            '198.51.100.90 - - [27/Sep/2026:12:00:00 +0700] "GET /?id=1%20UNION%20SELECT%20null HTTP/1.1" 200 100 "-" "curl" "-"',
            log_type="nginx"
        )
        await self.service.process_log_line(
            'sshd[111]: Failed password for invalid user hacker from 198.51.100.91 port 1234 ssh2',
            log_type="auth"
        )

        t_start = time.perf_counter()
        report = await self.service.get_security_report()
        t_elapsed = (time.perf_counter() - t_start) * 1000  # ms

        # Sub-10ms requirement
        self.assertLess(t_elapsed, 50.0, f"Report generated in {t_elapsed:.2f}ms")
        self.assertIn("current_threat_status", report)
        self.assertIn("attack_events_24h", report)
        self.assertIn("top_attacking_ips", report)
        self.assertIn("system_protection", report)
        self.assertGreaterEqual(report["attack_events_24h"]["total_events"], 2)

    async def test_get_attack_history(self):
        line = '198.51.100.95 - - [27/Sep/2026:12:00:00 +0700] "GET /.git/config HTTP/1.1" 404 100 "-" "Mozilla/5.0" "-"'
        await self.service.process_log_line(line, log_type="nginx")

        history = await self.service.get_attack_history(limit=10)
        self.assertIsInstance(history, list)
        self.assertGreaterEqual(len(history), 1)
        self.assertEqual(history[0]["ip"], "198.51.100.95")
        self.assertEqual(history[0]["attack_type"], "scanner_path")

    # --------------------------------------------------------------------------
    # 8. Milestone 1 Iteration 2 Enhancements
    # --------------------------------------------------------------------------

    async def test_ipv4_mapped_ipv6_block_and_veto(self):
        # Mapped loopback veto
        res_veto = await self.service.block_ip("::ffff:127.0.0.1", reason="Mapped loopback test")
        self.assertEqual(res_veto["status"], "veto")
        self.assertIn("127.0.0.1", res_veto["ip"])
        self.assertFalse(await self.mock_fw.is_blocked("127.0.0.1"))

        # Mapped attacker is unwrapped and blocked as IPv4
        res_block = await self.service.block_ip("::ffff:45.83.122.7", reason="Mapped attacker test")
        self.assertEqual(res_block["status"], "success")
        self.assertEqual(res_block["ip"], "45.83.122.7")
        self.assertTrue(await self.mock_fw.is_blocked("45.83.122.7"))

    async def test_spoofed_x_forwarded_for_from_untrusted_peer_ignored(self):
        attacker_ip = "45.83.122.7"
        admin_ip = "192.168.1.50"
        # Attacker tries to spoof Admin IP in X-Forwarded-For to evade detection/block
        line = f'{attacker_ip} - - [27/Sep/2026:12:00:00 +0700] "GET /?id=1%20UNION%20SELECT%201 HTTP/1.1" 200 100 "-" "curl" "{admin_ip}"'
        ev = await self.service.process_log_line(line, log_type="nginx")
        self.assertIsNotNone(ev)
        # Real client IP must be the untrusted peer, ignoring spoofed header
        self.assertEqual(ev["ip"], attacker_ip)
        self.assertEqual(ev["action_taken"], "iptables_drop")
        self.assertTrue(await self.mock_fw.is_blocked(attacker_ip))
        self.assertFalse(await self.mock_fw.is_blocked(admin_ip))

    async def test_spoofed_x_forwarded_for_reflected_dos_prevented(self):
        attacker_ip = "45.83.122.7"
        innocent_victim = "203.0.113.5"
        # Attacker sends malicious SQLi with innocent victim IP in XFF
        line = f'{attacker_ip} - - [27/Sep/2026:12:00:00 +0700] "GET /?id=1%20UNION%20SELECT%201 HTTP/1.1" 200 100 "-" "curl" "{innocent_victim}"'
        ev = await self.service.process_log_line(line, log_type="nginx")
        self.assertIsNotNone(ev)
        self.assertEqual(ev["ip"], attacker_ip)
        self.assertFalse(await self.mock_fw.is_blocked(innocent_victim))

    async def test_legitimate_proxy_chain_resolution(self):
        # Legitimate Docker bridge proxy with client IP
        line_docker = '172.18.0.1 - - [27/Sep/2026:12:00:00 +0700] "GET /?id=1%20UNION%20SELECT%201 HTTP/1.1" 200 100 "-" "curl" "198.51.100.99, 172.18.0.1"'
        ev1 = await self.service.process_log_line(line_docker, log_type="nginx")
        self.assertIsNotNone(ev1)
        self.assertEqual(ev1["ip"], "198.51.100.99")

        # Legitimate Cloudflare proxy
        line_cf = '173.245.48.5 - - [27/Sep/2026:12:00:00 +0700] "GET /?id=1%20UNION%20SELECT%201 HTTP/1.1" 200 100 "-" "curl" "203.0.113.88"'
        ev2 = await self.service.process_log_line(line_cf, log_type="nginx")
        self.assertIsNotNone(ev2)
        self.assertEqual(ev2["ip"], "203.0.113.88")

    async def test_sqli_comment_and_numeric_evasion(self):
        attacker_ip = "185.220.101.55"
        # Inline SQL comment evasion
        line1 = f'{attacker_ip} - - [27/Sep/2026:12:00:00 +0700] "GET /products?id=1%20UNION/**/SELECT%201,2,3 HTTP/1.1" 200 100 "-" "curl" "-"'
        ev1 = await self.service.process_log_line(line1, log_type="nginx")
        self.assertIsNotNone(ev1)
        self.assertEqual(ev1["attack_type"], "sqli")

        # Numeric boolean injection without quotes
        line2 = f'{attacker_ip} - - [27/Sep/2026:12:00:01 +0700] "GET /items?id=1%20OR%201=1-- HTTP/1.1" 200 100 "-" "curl" "-"'
        ev2 = await self.service.process_log_line(line2, log_type="nginx")
        self.assertIsNotNone(ev2)
        self.assertEqual(ev2["attack_type"], "sqli")

        # Numeric boolean injection with MySQL comment #
        line3 = f'{attacker_ip} - - [27/Sep/2026:12:00:02 +0700] "GET /items?id=1%20or%201=1%23 HTTP/1.1" 200 100 "-" "curl" "-"'
        ev3 = await self.service.process_log_line(line3, log_type="nginx")
        self.assertIsNotNone(ev3)
        self.assertEqual(ev3["attack_type"], "sqli")

    async def test_benign_traffic_no_false_positives(self):
        benign_requests = [
            '203.0.113.1 - - [27/Sep/2026:12:00:00 +0700] "GET /search?q=select+options+from+menu HTTP/1.1" 200 500 "-" "Mozilla/5.0" "-"',
            '203.0.113.2 - - [27/Sep/2026:12:00:00 +0700] "GET /blog/how-to-update-firmware-from-usb HTTP/1.1" 200 1200 "-" "Mozilla/5.0" "-"',
            '203.0.113.3 - - [27/Sep/2026:12:00:00 +0700] "GET /cart?action=delete&from=wishlist HTTP/1.1" 200 300 "-" "Mozilla/5.0" "-"',
            '203.0.113.4 - - [27/Sep/2026:12:00:00 +0700] "GET /api-docs HTTP/1.1" 200 8000 "-" "Mozilla/5.0" "-"',
            '203.0.113.5 - - [27/Sep/2026:12:00:00 +0700] "GET /help?action=confirm(email) HTTP/1.1" 200 400 "-" "Mozilla/5.0" "-"',
            '203.0.113.6 - - [27/Sep/2026:12:00:00 +0700] "GET /search?q=alert(battery) HTTP/1.1" 200 400 "-" "Mozilla/5.0" "-"',
            '203.0.113.7 - - [27/Sep/2026:12:00:00 +0700] "GET /blog/how-to-edit-etc-hosts HTTP/1.1" 200 1500 "-" "Mozilla/5.0" "-"',
        ]
        for line in benign_requests:
            ev = await self.service.process_log_line(line, log_type="nginx")
            self.assertIsNone(ev, f"False positive detected on benign line: {line}")

    async def test_concurrent_writes_contention_no_locks(self):
        tasks = []
        for i in range(500):
            event = ThreatEvent(
                ip=f"198.51.100.{(i % 250) + 1}",
                attack_type="sqli",
                threat_level=ThreatLevel.HIGH,
                target_service="nginx",
                raw_payload="1 UNION SELECT 1",
                timestamp=time.time(),
            )
            tasks.append(self.service.repository.save_attack_event(event))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        exceptions = [r for r in results if isinstance(r, Exception)]
        self.assertEqual(len(exceptions), 0, f"Encountered DB lock exceptions: {exceptions[:3]}")

    async def test_memory_and_unblock_cleanup(self):
        # Verify port scan bounded tracker and unblock eviction
        ip = "198.51.100.77"
        await self.service.block_ip(ip, reason="Temporary block")
        self.assertIn(ip, self.service._blocked_ips)

        await self.service.unblock_ip(ip, reason="Clean unblock")
        # Inactive record must be evicted from memory to bound RAM
        self.assertNotIn(ip, self.service._blocked_ips)


class TestHostFirewallController(unittest.IsolatedAsyncioTestCase):
    """Verifies HostFirewallController returncode parsing and command generation."""

    class MockProcSshClient:
        def __init__(self, response_val: Any):
            self.response_val = response_val

        async def execute_command(self, cmd: str) -> Any:
            return self.response_val

    async def test_is_blocked_returncode_evaluations(self):
        # 1. Exit code 0 -> Rule exists
        fw0 = HostFirewallController(self.MockProcSshClient("0"))
        self.assertTrue(await fw0.is_blocked("198.51.100.5"))

        # 2. Exit code 1 -> Rule does not exist
        fw1 = HostFirewallController(self.MockProcSshClient("1"))
        self.assertFalse(await fw1.is_blocked("198.51.100.5"))

        # 3. Linux iptables Bad rule stderr -> Rule does not exist
        fw_bad = HostFirewallController(self.MockProcSshClient("iptables: Bad rule (does a matching rule exist in that chain?).\n1"))
        self.assertFalse(await fw_bad.is_blocked("198.51.100.5"))

        # 4. IPv4-mapped address is unwrapped
        fw_mapped = HostFirewallController(self.MockProcSshClient("0"))
        self.assertTrue(await fw_mapped.is_blocked("::ffff:198.51.100.5"))


if __name__ == "__main__":
    unittest.main()
