"""
services/ai-agent-service/tests/test_challenger_m1_it2_empirical.py
Empirical Adversarial Test Suite for Milestone 1 Iteration 2 (Challenger 2).

Thực nghiệm độc lập kiểm chứng:
1. Concurrency Stress & SQLite Lock Contention: 5,000 concurrent events + 500 attack writes.
2. 12 Benign User Queries False Positive evaluation (Target: 0% FP, 0 auto-blocks).
3. True Positive sanity check (Ensures real SQLi, XSS, Scanners are still detected).
4. RAM Footprint & Tracker Bounding: 10,000 IPs memory delta < 15.0 MB, port_scan_tracker cleanup & LRU cap.
5. Inactive Blocked IP Eviction from in-memory cache.
"""

import asyncio
import os
import shutil
import tempfile
import time
import tracemalloc
import unittest
from typing import Dict, List, Tuple

from app.services.security_monitor_service import (
    BoundedPortScanTracker,
    MockFirewallController,
    SecurityMonitorService,
    ThreatLevel,
)


class TestChallengerM1It2Empirical(unittest.IsolatedAsyncioTestCase):
    """Bộ kiểm thử đối kháng thực nghiệm độc lập cho Milestone 1 Iteration 2."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "challenger_m1_it2.db")
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
    # 1. CONCURRENCY STRESS & SQLITE LOCK CONTENTION (5,000 + 500 EVENTS)
    # ==========================================================================

    async def test_adversarial_concurrency_5000_events_no_db_locks(self):
        """
        Bắn 5,000 sự kiện đồng thời qua asyncio.gather().
        Bao gồm cả traffic lành tính và các vector tấn công.
        Yêu cầu: 0 SQLite OperationalError: database is locked, 0 exceptions.
        """
        events_count = 5000
        tasks = []
        t0 = time.perf_counter()

        for i in range(events_count):
            ip = f"198.51.{(i // 256) % 256}.{i % 256}"
            cat = i % 5
            if cat == 0:
                line = f'{ip} - - [27/Sep/2026:12:00:00 +0700] "GET /catalog/item?id={i} HTTP/1.1" 200 450 "-" "Mozilla/5.0" "-"'
                tasks.append(self.service.process_log_line(line, log_type="nginx"))
            elif cat == 1:
                line = f"sshd[200{i % 10}]: Failed password for invalid user hacker_{i} from {ip} port {30000 + (i % 10000)} ssh2"
                tasks.append(self.service.process_log_line(line, log_type="auth"))
            elif cat == 2:
                line = f'{ip} - - [27/Sep/2026:12:00:00 +0700] "GET /search?q=1%20UNION%20SELECT%20user,pass%20FROM%20users%20WHERE%201=1 HTTP/1.1" 200 120 "-" "curl" "-"'
                tasks.append(self.service.process_log_line(line, log_type="nginx"))
            elif cat == 3:
                line = f'{ip} - - [27/Sep/2026:12:00:00 +0700] "GET /wp-login.php HTTP/1.1" 404 15 "-" "Mozilla/5.0" "-"'
                tasks.append(self.service.process_log_line(line, log_type="nginx"))
            else:
                line = f"REQ: {ip} /api/v1/status"
                tasks.append(self.service.process_log_line(line, log_type="ddos"))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        duration = time.perf_counter() - t0

        exceptions = [r for r in results if isinstance(r, Exception)]
        sqlite_locks = [e for e in exceptions if "database is locked" in str(e).lower()]

        print(f"\n[Adversarial Concurrency 5000] Completed in {duration:.2f}s ({events_count / duration:.1f} events/s)")
        print(f"[Adversarial Concurrency 5000] Exceptions: {len(exceptions)} | SQLite Locks: {len(sqlite_locks)}")

        self.assertEqual(len(sqlite_locks), 0, f"Phát hiện {len(sqlite_locks)} lỗi SQLite lock!")
        self.assertEqual(len(exceptions), 0, f"Phát hiện {len(exceptions)} exceptions: {exceptions[:3]}")

    async def test_adversarial_sqlite_contention_500_attack_writes(self):
        """
        Bắn 500 đợt tấn công mức độ HIGH đồng thời kích hoạt đồng loạt:
        1. Ghi security_attack_events
        2. Ghi security_blocked_ips (do auto-block)
        Yêu cầu: 0 lỗi SQLite lock, 100% hoàn thành.
        """
        num_attacks = 500
        tasks = []
        for i in range(num_attacks):
            attacker_ip = f"198.51.200.{(i % 250) + 1}"
            line = f'{attacker_ip} - - [27/Sep/2026:12:00:00 +0700] "GET /?id=1%20UNION%20SELECT%201,2,3%20FROM%20admin%20WHERE%20id=1 HTTP/1.1" 200 100 "-" "curl" "-"'
            tasks.append(self.service.process_log_line(line, log_type="nginx"))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        exceptions = [r for r in results if isinstance(r, Exception)]
        sqlite_locks = [e for e in exceptions if "database is locked" in str(e).lower()]

        print(f"\n[Adversarial SQLite Contention 500 Writes] Exceptions: {len(exceptions)} | Locks: {len(sqlite_locks)}")
        self.assertEqual(len(sqlite_locks), 0, f"Phát hiện lỗi database lock: {sqlite_locks[:2]}")
        self.assertEqual(len(exceptions), 0, f"Phát hiện ngoại lệ ghi DB: {exceptions[:2]}")

    # ==========================================================================
    # 2. FALSE POSITIVE EVALUATION ON 12 BENIGN USER QUERIES
    # ==========================================================================

    async def test_false_positive_evaluation_12_benign_queries(self):
        """
        Tái kiểm tra 12 kịch bản truy vấn người dùng thực tế từ Iteration 1:
        1. Search "select options from menu"
        2. Blog "how to update firmware from usb"
        3. Cart "delete from wishlist"
        4. Swagger "/api-docs"
        5. FAQ "confirm(email)"
        6. Settings "alert(battery)"
        7. Search European Union
        8. Search Credit Union
        9. Search Drop Tennis Table
        10. Blog "how to edit etc hosts"
        11. Shoes sort "price_high_to_low"
        12. Profile view "username=john_doe"

        Yêu cầu:
        - 0/12 bị nhận diện là tấn công (False Positive Rate = 0.0%)
        - 0 người dùng bị chặn iptables (iptables_drop = 0)
        """
        benign_scenarios = [
            ("Search European Union", '203.0.113.1 - - [27/Sep/2026:12:00:00 +0700] "GET /search?q=european+union+flag HTTP/1.1" 200 500 "-" "Mozilla/5.0" "-"'),
            ("Search Credit Union", '203.0.113.2 - - [27/Sep/2026:12:00:00 +0700] "GET /search?q=credit+union+bank+hours HTTP/1.1" 200 500 "-" "Mozilla/5.0" "-"'),
            ("Search Select Options from Menu", '203.0.113.3 - - [27/Sep/2026:12:00:00 +0700] "GET /search?q=select+options+from+menu HTTP/1.1" 200 500 "-" "Mozilla/5.0" "-"'),
            ("Blog Post: Update Firmware from USB", '203.0.113.4 - - [27/Sep/2026:12:00:00 +0700] "GET /blog/how-to-update-firmware-from-usb HTTP/1.1" 200 1200 "-" "Mozilla/5.0" "-"'),
            ("Cart: Delete Item from Cart", '203.0.113.5 - - [27/Sep/2026:12:00:00 +0700] "GET /cart?action=delete&from=wishlist HTTP/1.1" 200 300 "-" "Mozilla/5.0" "-"'),
            ("Search Drop Tennis Table", '203.0.113.6 - - [27/Sep/2026:12:00:00 +0700] "GET /shop?q=drop+tennis+table HTTP/1.1" 200 400 "-" "Mozilla/5.0" "-"'),
            ("API Docs access (FastAPI / Swagger)", '203.0.113.7 - - [27/Sep/2026:12:00:00 +0700] "GET /api-docs HTTP/1.1" 200 8000 "-" "Mozilla/5.0" "-"'),
            ("Help FAQ: Confirm email", '203.0.113.8 - - [27/Sep/2026:12:00:00 +0700] "GET /help?action=confirm(email) HTTP/1.1" 200 400 "-" "Mozilla/5.0" "-"'),
            ("Search: Alert notification settings", '203.0.113.9 - - [27/Sep/2026:12:00:00 +0700] "GET /search?q=alert(battery) HTTP/1.1" 200 400 "-" "Mozilla/5.0" "-"'),
            ("Normal Blog Post: etc hosts file", '203.0.113.10 - - [27/Sep/2026:12:00:00 +0700] "GET /blog/how-to-edit-etc-hosts HTTP/1.1" 200 1500 "-" "Mozilla/5.0" "-"'),
            ("Ecommerce Shoes Filter: High to Low", '203.0.113.11 - - [27/Sep/2026:12:00:00 +0700] "GET /shoes?brand=nike&sort=price_high_to_low HTTP/1.1" 200 1500 "-" "Mozilla/5.0" "-"'),
            ("Standard User Profile View", '203.0.113.12 - - [27/Sep/2026:12:00:00 +0700] "GET /api/v1/users/profile?username=john_doe HTTP/1.1" 200 400 "-" "Mozilla/5.0" "-"'),
        ]

        false_positives = []
        for name, log_line in benign_scenarios:
            ev = await self.service.process_log_line(log_line, log_type="nginx")
            if ev is not None:
                false_positives.append((name, ev))

        print(f"\n[Benign Queries Verification] Tested {len(benign_scenarios)} realistic queries.")
        print(f"[Benign Queries Verification] False Positives count: {len(false_positives)}")
        for name, ev in false_positives:
            print(f"  -> FP Flagged: [{name}] as {ev['attack_type']} ({ev['threat_level']}) Action: {ev['action_taken']}")

        # Strict Assertion: 0 False Positives
        self.assertEqual(len(false_positives), 0, f"Có {len(false_positives)} truy vấn người dùng bình thường bị phân loại nhầm: {[f[0] for f in false_positives]}")

    # ==========================================================================
    # 3. TRUE POSITIVE SANITY CHECK (PREVENT REGRESSION)
    # ==========================================================================

    async def test_true_positive_detection_accuracy(self):
        """
        Xác nhận việc loại bỏ False Positive không làm suy giảm khả năng phát hiện tấn công thật:
        - SQLi: UNION SELECT, ' OR 1=1 --, DROP TABLE
        - XSS: <script>alert(1)</script>, onload=alert(1)
        - Traversal: ../../etc/passwd
        - Scanner: sqlmap/1.5, /.env
        """
        attacks = [
            ("SQLi UNION", '198.51.100.1 - - [27/Sep/2026:12:00:00 +0700] "GET /api/user?id=1%20UNION%20SELECT%201,2,3 HTTP/1.1" 200 100 "-" "curl" "-"', "sqli"),
            ("SQLi Numeric Boolean", '198.51.100.2 - - [27/Sep/2026:12:00:00 +0700] "GET /login?user=admin%20OR%201=1-- HTTP/1.1" 200 100 "-" "curl" "-"', "sqli"),
            ("SQLi Drop Table", '198.51.100.3 - - [27/Sep/2026:12:00:00 +0700] "POST /api/exec; DROP TABLE users;-- HTTP/1.1" 200 100 "-" "curl" "-"', "sqli"),
            ("XSS Script Tag", '198.51.100.4 - - [27/Sep/2026:12:00:00 +0700] "GET /search?q=<script>alert(1)</script> HTTP/1.1" 200 100 "-" "curl" "-"', "xss"),
            ("XSS Event Handler", '198.51.100.5 - - [27/Sep/2026:12:00:00 +0700] "GET /profile?name=<img src=x onerror=alert(1)> HTTP/1.1" 200 100 "-" "curl" "-"', "xss"),
            ("Path Traversal", '198.51.100.6 - - [27/Sep/2026:12:00:00 +0700] "GET /download?file=../../../../etc/passwd HTTP/1.1" 200 100 "-" "curl" "-"', "path_traversal"),
            ("Scanner Scanner Path", '198.51.100.7 - - [27/Sep/2026:12:00:00 +0700] "GET /.env HTTP/1.1" 404 100 "-" "curl" "-"', "scanner_path"),
            ("Scanner User Agent", '198.51.100.8 - - [27/Sep/2026:12:00:00 +0700] "GET /index.html HTTP/1.1" 200 100 "-" "sqlmap/1.6" "-"', "scanner_probe"),
        ]

        detected_count = 0
        for name, log_line, expected_type in attacks:
            ev = await self.service.process_log_line(log_line, log_type="nginx")
            self.assertIsNotNone(ev, f"Tấn công thực tế [{name}] bị bỏ lọt!")
            self.assertEqual(ev["attack_type"], expected_type, f"Loại tấn công [{name}] không khớp: {ev['attack_type']} != {expected_type}")
            detected_count += 1

        print(f"\n[True Positive Accuracy] Detected {detected_count}/{len(attacks)} real attacks with 100% accuracy.")

    # ==========================================================================
    # 4. RAM FOOTPRINT & TRACKER CLEANUP (10,000 IPS)
    # ==========================================================================

    async def test_ram_footprint_10000_ips_and_port_scan_cleanup(self):
        """
        Nạp 10,000 distinct IPs vào hệ thống, đo heap bằng tracemalloc:
        1. Heap increase sau khi nạp < 15.0 MB.
        2. Kích hoạt prune_stale(): port_scan_tracker và port_scan_times phải được dọn dẹp sạch sẽ về 0.
        3. Kiểm tra tính năng LRU force-shrink: nếu nạp vượt quá 10,000 IPs (ví dụ 15,000 IPs),
           BoundedPortScanTracker phải tự động duy trì trần giới hạn dung lượng <= 10,000 IPs.
        """
        tracemalloc.start()
        snapshot_start = tracemalloc.take_snapshot()

        now = time.time()
        # Nạp 10,000 IPs
        for i in range(10000):
            ip = f"198.51.{(i // 256) % 256}.{i % 256}"
            self.service.ssh_tracker.record_hit(ip, now=now)
            self.service.port_scan_tracker[ip].add(80)
            self.service.port_scan_times[ip].append(now)

        snapshot_loaded = tracemalloc.take_snapshot()
        load_diff = snapshot_loaded.compare_to(snapshot_start, "lineno")
        mem_loaded_mb = sum(s.size_diff for s in load_diff) / (1024 * 1024)

        print(f"\n[RAM Footprint] Heap increase for 10,000 IPs: {mem_loaded_mb:.2f} MB")
        self.assertLess(mem_loaded_mb, 15.0, f"RAM heap {mem_loaded_mb:.2f} MB vượt trần 15.0 MB!")

        # Kích hoạt dọn dẹp TTL / Stale sau 120s
        advance_time = now + 120.0
        self.service.ssh_tracker.prune_stale(now=advance_time)
        self.service.web_attack_tracker.prune_stale(now=advance_time)
        self.service.scanner_tracker.prune_stale(now=advance_time)
        self.service.ddos_tracker.prune_stale(now=advance_time)
        self.service.port_scan_tracker.prune_stale(now=advance_time)

        snapshot_pruned = tracemalloc.take_snapshot()
        prune_diff = snapshot_pruned.compare_to(snapshot_start, "lineno")
        mem_pruned_mb = sum(s.size_diff for s in prune_diff) / (1024 * 1024)
        tracemalloc.stop()

        print(f"[RAM Footprint] Heap increase after prune: {mem_pruned_mb:.2f} MB")
        print(f"[RAM Footprint] port_scan_tracker remaining entries: {len(self.service.port_scan_tracker)}")
        print(f"[RAM Footprint] port_scan_times remaining entries: {len(self.service.port_scan_times)}")
        print(f"[RAM Footprint] ssh_tracker remaining entries: {len(self.service.ssh_tracker._history)}")

        # Xác nhận dọn dẹp sạch sẽ
        self.assertEqual(len(self.service.port_scan_tracker), 0, "port_scan_tracker không được dọn dẹp về 0!")
        self.assertEqual(len(self.service.port_scan_times), 0, "port_scan_times không được dọn dẹp về 0!")
        self.assertEqual(len(self.service.ssh_tracker._history), 0, "ssh_tracker không được dọn dẹp về 0!")

        # 4. Bounded capacity check: nạp 15,000 IPs liên tục
        tracker = BoundedPortScanTracker(max_ips=10000, window_seconds=30.0)
        times_dict = {}
        tracker.link_times_tracker(times_dict)
        t_now = time.time()
        for i in range(15000):
            ip_str = f"100.64.{(i // 256) % 256}.{i % 256}"
            tracker[ip_str].add(80)
            times_dict[ip_str] = [t_now]

        print(f"[Bounded Capacity Check] Tracker size after inserting 15,000 IPs: {len(tracker)}")
        self.assertLessEqual(len(tracker), 10000, f"BoundedPortScanTracker vượt trần dung lượng: {len(tracker)} > 10000")

    # ==========================================================================
    # 5. INACTIVE BLOCKED IPS EVICTION TEST
    # ==========================================================================

    async def test_blocked_ips_in_memory_eviction(self):
        """
        Kiểm tra cơ chế giải phóng in-memory _blocked_ips khi IP được unblock:
        Đảm bảo không rò rỉ rác in-memory theo thời gian.
        """
        for i in range(50):
            ip = f"198.51.100.{i}"
            await self.service.block_ip(ip, reason="Test block", duration_seconds=1)

        self.assertEqual(len(self.service._blocked_ips), 50)

        # Unblock tất cả
        for i in range(50):
            ip = f"198.51.100.{i}"
            await self.service.unblock_ip(ip, reason="Manual unblock test")

        print(f"\n[Blocked IPs Cache Eviction] Remaining keys in _blocked_ips after unblock: {len(self.service._blocked_ips)}")
        self.assertEqual(len(self.service._blocked_ips), 0, "self._blocked_ips không giải phóng các IP đã unblock!")


if __name__ == "__main__":
    unittest.main()
