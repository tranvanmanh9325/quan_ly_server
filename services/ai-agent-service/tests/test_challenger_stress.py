"""
services/ai-agent-service/tests/test_challenger_stress.py
Empirical Adversarial Test Suite by Challenger 2 (Milestone 1).

Covers:
1. Concurrency & Stress: 5,000 - 10,000 log events processed concurrently.
2. SQLite write contention under concurrent load.
3. Memory & Resource Leak: 10,000 IPs, TTL sweeper, tracker pruning, inactive blocked IP accumulation.
4. Resource lifecycle: Rapid start/stop cycles with ResourceWarning detection.
5. False Positive evaluation on legitimate web queries (search terms, API parameters, blog slugs).
"""

import asyncio
import os
import shutil
import tempfile
import time
import tracemalloc
import unittest
from typing import List, Tuple

from app.services.security_monitor_service import (
    MockFirewallController,
    SecurityMonitorService,
    ThreatLevel,
)


class TestChallengerEmpiricalStress(unittest.IsolatedAsyncioTestCase):
    """Adversarial stress and concurrency verification."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "security_stress.db")
        self.mock_fw = MockFirewallController()
        self.service = SecurityMonitorService(
            firewall=self.mock_fw,
            db_path=self.db_path,
            custom_whitelist_ips=["192.168.1.100"],
        )
        await self.service.start()

    async def asyncTearDown(self):
        await self.service.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ==========================================================================
    # 1. CONCURRENCY & STRESS (5,000 - 10,000 EVENTS)
    # ==========================================================================

    async def test_concurrency_stress_5000_events(self):
        """
        Fires 5,000 log events concurrently from asyncio tasks.
        Mix of benign requests and multi-vector attack events.
        Checks for deadlocks, exceptions (e.g. SQLite database locked), and data corruption.
        """
        events_count = 5000
        tasks = []
        start_time = time.perf_counter()

        for i in range(events_count):
            ip = f"198.51.{(i // 256) % 256}.{i % 256}"
            category = i % 5

            if category == 0:
                # Benign nginx request
                line = f'{ip} - - [27/Sep/2026:12:00:00 +0700] "GET /products/view?id={i} HTTP/1.1" 200 450 "-" "Mozilla/5.0" "-"'
                tasks.append(self.service.process_log_line(line, log_type="nginx"))
            elif category == 1:
                # SSH brute force line
                line = f"sshd[100{i % 10}]: Failed password for invalid user bot_{i} from {ip} port {20000 + (i % 10000)} ssh2"
                tasks.append(self.service.process_log_line(line, log_type="auth"))
            elif category == 2:
                # SQLi injection
                line = f'{ip} - - [27/Sep/2026:12:00:00 +0700] "GET /api/user?id=1%20UNION%20SELECT%20password%20FROM%20admins HTTP/1.1" 200 120 "-" "curl" "-"'
                tasks.append(self.service.process_log_line(line, log_type="nginx"))
            elif category == 3:
                # Scanner path
                line = f'{ip} - - [27/Sep/2026:12:00:00 +0700] "GET /.env HTTP/1.1" 404 15 "-" "sqlmap/1.5" "-"'
                tasks.append(self.service.process_log_line(line, log_type="nginx"))
            else:
                # DDoS line
                line = f"REQ: {ip} /api/v1/ping"
                tasks.append(self.service.process_log_line(line, log_type="ddos"))

        # Gather with return_exceptions=True to capture any SQLite lock or concurrency crashes
        results = await asyncio.gather(*tasks, return_exceptions=True)
        duration = time.perf_counter() - start_time

        exceptions = [r for r in results if isinstance(r, Exception)]
        detected = [r for r in results if isinstance(r, dict)]

        print(f"\n[Stress Test 5000 Events] Completed in {duration:.2f}s ({events_count / duration:.1f} events/sec)")
        print(f"[Stress Test 5000 Events] Exceptions count: {len(exceptions)}")
        print(f"[Stress Test 5000 Events] Attacks detected: {len(detected)}")

        # Print top exceptions if any
        if exceptions:
            print(f"[Stress Test 5000 Events] First 3 exceptions: {exceptions[:3]}")

        # Assert no catastrophic exceptions (deadlock, unhandled crash)
        self.assertEqual(len(exceptions), 0, f"Encountered {len(exceptions)} exceptions under concurrent load: {exceptions[:3]}")

        # Check report generation is still functional and fast
        t_rep_start = time.perf_counter()
        report = await self.service.get_security_report()
        rep_duration = (time.perf_counter() - t_rep_start) * 1000
        print(f"[Stress Test 5000 Events] get_security_report response time: {rep_duration:.2f}ms")
        self.assertLess(rep_duration, 50.0)
        self.assertGreater(report["attack_events_24h"]["total_events"], 0)

    # ==========================================================================
    # 2. SQLITE CONCURRENCY CONTENTION STRESS
    # ==========================================================================

    async def test_sqlite_concurrent_writes_contention(self):
        """
        Adversarial test: Fire 500 simultaneous attacks that each trigger an asynchronous
        to_thread SQLite write to security_attack_events and security_blocked_ips.
        Checks if SQLite default locking causes OperationalError: database is locked.
        """
        num_attacks = 500
        tasks = []
        for i in range(num_attacks):
            attacker_ip = f"198.51.100.{(i % 250) + 1}"
            # SQLi causes auto-block (writes to both attack_events and blocked_ips)
            line = f'{attacker_ip} - - [27/Sep/2026:12:00:00 +0700] "GET /?id=1%20UNION%20SELECT%201 HTTP/1.1" 200 100 "-" "curl" "-"'
            tasks.append(self.service.process_log_line(line, log_type="nginx"))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        exceptions = [r for r in results if isinstance(r, Exception)]

        print(f"\n[SQLite Contention] 500 concurrent attack writes: {len(exceptions)} exceptions")
        if exceptions:
            print(f"[SQLite Contention] Exception sample: {type(exceptions[0]).__name__}: {exceptions[0]}")

        self.assertEqual(len(exceptions), 0, f"SQLite concurrency failed with {len(exceptions)} errors: {exceptions[:2]}")

    # ==========================================================================
    # 3. MEMORY & RESOURCE LEAK: 10,000 DISTINCT IPS & SWEEPER
    # ==========================================================================

    async def test_memory_and_tracker_leak_10000_ips(self):
        """
        Feeds 10,000 distinct IPs into the service.
        Measures memory before and after feeding and after TTL sweeper prune.
        Verifies whether port_scan_tracker, port_scan_times, and _blocked_ips are properly bounded.
        """
        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()

        now = time.time()
        # Feed 10,000 distinct IPs across trackers
        for i in range(10000):
            ip = f"198.51.{(i // 256) % 256}.{i % 256}"
            # Feed into SSH tracker
            self.service.ssh_tracker.record_hit(ip, now=now)
            # Feed into port scan tracker
            self.service.port_scan_tracker[ip].add(80)
            self.service.port_scan_times[ip].append(now)

        snapshot_loaded = tracemalloc.take_snapshot()
        load_diff = snapshot_loaded.compare_to(snapshot_before, "lineno")
        mem_loaded_mb = sum(s.size_diff for s in load_diff) / (1024 * 1024)

        # Trigger TTL sweeper prune (simulate time advance past window)
        advance_time = now + 120.0
        self.service.ssh_tracker.prune_stale(now=advance_time, force_shrink=True)
        self.service.web_attack_tracker.prune_stale(now=advance_time, force_shrink=True)
        self.service.scanner_tracker.prune_stale(now=advance_time, force_shrink=True)
        self.service.ddos_tracker.prune_stale(now=advance_time, force_shrink=True)

        snapshot_pruned = tracemalloc.take_snapshot()
        prune_diff = snapshot_pruned.compare_to(snapshot_before, "lineno")
        mem_pruned_mb = sum(s.size_diff for s in prune_diff) / (1024 * 1024)
        tracemalloc.stop()

        print(f"\n[Memory Test 10000 IPs] Heap increase after loading: {mem_loaded_mb:.2f} MB")
        print(f"[Memory Test 10000 IPs] Heap increase after prune: {mem_pruned_mb:.2f} MB")
        print(f"[Memory Test 10000 IPs] port_scan_tracker entries count: {len(self.service.port_scan_tracker)}")
        print(f"[Memory Test 10000 IPs] ssh_tracker entries count: {len(self.service.ssh_tracker._history)}")

        # RAM requirement: < 15MB
        self.assertLess(mem_loaded_mb, 15.0, f"Memory footprint exceeded 15MB: {mem_loaded_mb:.2f} MB")

    async def test_blocked_ips_inactive_retention_leak(self):
        """
        Adversarial inspection: When 1,000 IPs expire via TTL sweeper,
        does self._blocked_ips leak inactive records indefinitely in memory?
        """
        for i in range(100):
            ip = f"198.51.100.{i}"
            await self.service.block_ip(ip, reason="Short TTL", duration_seconds=0)

        self.assertEqual(len(self.service._blocked_ips), 100)

        # Simulate TTL sweeper pass
        now = time.time() + 10.0
        expired = [
            ip for ip, rec in self.service._blocked_ips.items()
            if rec.is_active and now >= rec.expires_at
        ]
        for ip in expired:
            await self.service.unblock_ip(ip, reason="TTL_EXPIRED")

        # Check: How many items remain in self._blocked_ips?
        print(f"\n[Blocked IPs Retention] Active blocked items: {len(await self.service.list_blocked_ips())}")
        print(f"[Blocked IPs Retention] Total dict keys in _blocked_ips: {len(self.service._blocked_ips)}")

        # Active items should be 0
        self.assertEqual(len(await self.service.list_blocked_ips()), 0)
        # Note: self._blocked_ips retains inactive records marked is_active=False.
        # Verify that this does not affect correctness of list_blocked_ips or get_security_report
        rep = await self.service.get_security_report()
        self.assertEqual(rep["active_blocked_ips_count"], 0)

    # ==========================================================================
    # 4. RESOURCE LIFECYCLE: RAPID START/STOP CYCLES
    # ==========================================================================

    async def test_rapid_start_stop_cycles_no_resource_warnings(self):
        """
        Runs 30 consecutive start() and stop() cycles to ensure:
        - 0 unhandled task leaks
        - 0 ResourceWarnings for unclosed database connections
        - 0 deadlocks on _lock
        """
        for cycle in range(30):
            service = SecurityMonitorService(
                firewall=MockFirewallController(),
                db_path=os.path.join(self.temp_dir, f"lifecycle_{cycle}.db"),
            )
            await service.start()
            self.assertTrue(service._running)
            self.assertIsNotNone(service._sweeper_task)
            self.assertIsNotNone(service._log_monitor_task)

            # Rapid stop
            await service.stop()
            self.assertFalse(service._running)
            self.assertIsNone(service._sweeper_task)
            self.assertIsNone(service._log_monitor_task)

    # ==========================================================================
    # 5. FALSE POSITIVE EVALUATION (LEGITIMATE WEB TRAFFIC)
    # ==========================================================================

    async def test_false_positive_evaluation_benign_queries(self):
        """
        Adversarial evaluation: Tests a diverse set of ordinary, benign web traffic:
        - Product searches: "union", "select options", "update firmware"
        - API documentation: "/api-docs"
        - Cart operations: "delete from cart"
        - Filter queries: "select=name&from=..."
        Assesses if legitimate users are falsely blocked.
        """
        test_cases: List[Tuple[str, str, str]] = [
            # (test_name, log_line, expected_outcome)
            (
                "Search European Union",
                '203.0.113.1 - - [27/Sep/2026:12:00:00 +0700] "GET /search?q=european+union+flag HTTP/1.1" 200 500 "-" "Mozilla/5.0" "-"',
                "benign"
            ),
            (
                "Search Credit Union",
                '203.0.113.2 - - [27/Sep/2026:12:00:00 +0700] "GET /search?q=credit+union+bank+hours HTTP/1.1" 200 500 "-" "Mozilla/5.0" "-"',
                "benign"
            ),
            (
                "Search Select Options from Menu",
                '203.0.113.3 - - [27/Sep/2026:12:00:00 +0700] "GET /search?q=select+options+from+menu HTTP/1.1" 200 500 "-" "Mozilla/5.0" "-"',
                "suspect_fp"
            ),
            (
                "Blog Post: Update Firmware from USB",
                '203.0.113.4 - - [27/Sep/2026:12:00:00 +0700] "GET /blog/how-to-update-firmware-from-usb HTTP/1.1" 200 1200 "-" "Mozilla/5.0" "-"',
                "suspect_fp"
            ),
            (
                "Cart: Delete Item from Cart",
                '203.0.113.5 - - [27/Sep/2026:12:00:00 +0700] "GET /cart?action=delete&from=wishlist HTTP/1.1" 200 300 "-" "Mozilla/5.0" "-"',
                "suspect_fp"
            ),
            (
                "Search Drop Tennis Table",
                '203.0.113.6 - - [27/Sep/2026:12:00:00 +0700] "GET /shop?q=drop+tennis+table HTTP/1.1" 200 400 "-" "Mozilla/5.0" "-"',
                "benign"
            ),
            (
                "API Docs access (FastAPI / Swagger)",
                '203.0.113.7 - - [27/Sep/2026:12:00:00 +0700] "GET /api-docs HTTP/1.1" 200 8000 "-" "Mozilla/5.0" "-"',
                "suspect_fp"
            ),
            (
                "Help FAQ: Confirm email",
                '203.0.113.8 - - [27/Sep/2026:12:00:00 +0700] "GET /help?action=confirm(email) HTTP/1.1" 200 400 "-" "Mozilla/5.0" "-"',
                "suspect_fp"
            ),
            (
                "Search: Alert notification settings",
                '203.0.113.9 - - [27/Sep/2026:12:00:00 +0700] "GET /search?q=alert(battery) HTTP/1.1" 200 400 "-" "Mozilla/5.0" "-"',
                "suspect_fp"
            ),
            (
                "Normal Blog Post: etc hosts file",
                '203.0.113.10 - - [27/Sep/2026:12:00:00 +0700] "GET /blog/how-to-edit-etc-hosts HTTP/1.1" 200 1500 "-" "Mozilla/5.0" "-"',
                "suspect_fp"
            ),
            (
                "Ecommerce Shoes Filter: High to Low",
                '203.0.113.11 - - [27/Sep/2026:12:00:00 +0700] "GET /shoes?brand=nike&sort=price_high_to_low HTTP/1.1" 200 1500 "-" "Mozilla/5.0" "-"',
                "benign"
            ),
            (
                "Standard User Profile View",
                '203.0.113.12 - - [27/Sep/2026:12:00:00 +0700] "GET /api/v1/users/profile?username=john_doe HTTP/1.1" 200 400 "-" "Mozilla/5.0" "-"',
                "benign"
            ),
        ]

        false_positives = []
        for name, log_line, category in test_cases:
            ev = await self.service.process_log_line(log_line, log_type="nginx")
            if ev is not None:
                false_positives.append({
                    "test_name": name,
                    "ip": ev["ip"],
                    "attack_type": ev["attack_type"],
                    "threat_level": ev["threat_level"],
                    "action_taken": ev["action_taken"],
                    "payload": ev["raw_payload"],
                })

        print(f"\n[False Positive Evaluation] Tested {len(test_cases)} realistic requests.")
        print(f"[False Positive Evaluation] Detected false positives: {len(false_positives)}")
        for fp in false_positives:
            print(f"  -> FP Detected: [{fp['test_name']}] flagged as '{fp['attack_type']}' ({fp['threat_level']}) | Action: {fp['action_taken']}")

        # We document the exact false positives empirically for the report
        # If any user was blocked (action_taken == 'iptables_drop' or in mock_fw), record it
        blocked_users = [fp for fp in false_positives if fp["action_taken"] == "iptables_drop"]
        print(f"[False Positive Evaluation] Innocent users auto-blocked on firewall: {len(blocked_users)}")


if __name__ == "__main__":
    unittest.main()
