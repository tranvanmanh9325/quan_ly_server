"""
services/ai-agent-service/tests/test_challenger_m1_1_it2_empirical.py
Empirical Adversarial Re-Testing Suite by Challenger 1 (Milestone 1, Iteration 2).
Target: services/ai-agent-service/app/services/security_monitor_service.py

Specifically verifies:
1. Whitelist VETO bypass re-test via IPv4-mapped IPv6 (::ffff:127.0.0.1, ::ffff:192.168.1.1, etc.)
2. Spoofed X-Forwarded-For header bypass and reflected DoS re-test with untrusted remote_addr.
3. SQLi evasion re-test (inline comments UNION/**/SELECT, numeric OR 1=1--, OR 1=1#, etc.) + False Positive matrix.
4. HostFirewallController.is_blocked error/returncode logic re-test.
"""

import asyncio
import os
import shutil
import tempfile
import unittest
from typing import Any
import urllib.parse

from app.services.security_monitor_service import (
    HostFirewallController,
    MockFirewallController,
    SecurityMonitorService,
    ThreatLevel,
    WhitelistEngine,
    extract_client_ip,
    normalize_ip_address,
)


class TestAdversarialIPv4MappedIPv6(unittest.IsolatedAsyncioTestCase):
    """
    Kịch bản 1: Kiểm thử đối kháng Whitelist VETO với địa chỉ IPv4-mapped IPv6 (RFC 4291).
    Kỳ vọng: 100% các dải Loopback, Private LAN, Docker, Cloudflare, Custom Whitelist
    ở định dạng ::ffff:x.x.x.x PHẢI bị VETO khi gọi block_ip(), và không bị khóa trên firewall.
    """

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_mapped_whitelist.db")
        self.mock_fw = MockFirewallController()
        self.service = SecurityMonitorService(
            firewall=self.mock_fw,
            db_path=self.db_path,
            custom_whitelist_ips=["192.0.2.100", "203.0.113.50"],
        )
        await self.service.start()

    async def asyncTearDown(self):
        await self.service.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_normalize_ip_address_unwrapping(self):
        """Hàm normalize_ip_address phải unwrap chuẩn xác mọi dạng IPv4-mapped IPv6."""
        cases = [
            ("::ffff:127.0.0.1", "127.0.0.1"),
            ("::ffff:192.168.1.1", "192.168.1.1"),
            ("::FFFF:10.0.0.1", "10.0.0.1"),
            ("0:0:0:0:0:ffff:172.16.0.5", "172.16.0.5"),
            ("::ffff:45.83.122.7", "45.83.122.7"),
            ("127.0.0.1", "127.0.0.1"),
            ("::1", "::1"),
            ("2001:db8::1", "2001:db8::1"),
        ]
        for inp, expected in cases:
            norm = normalize_ip_address(inp)
            self.assertEqual(str(norm), expected, f"Failed unwrapping {inp}")

    async def test_ipv4_mapped_loopback_veto(self):
        """Tất cả các biến thể ::ffff:127.x.x.x phải bị VETO 100%."""
        loopback_variants = [
            "::ffff:127.0.0.1",
            "::ffff:127.0.0.2",
            "::ffff:127.255.255.254",
            "::FFFF:127.0.0.1",
            "0:0:0:0:0:ffff:127.0.0.1",
        ]
        for ip in loopback_variants:
            res = await self.service.block_ip(ip, reason="Adversarial mapped loopback block")
            self.assertEqual(
                res.get("status"),
                "veto",
                f"IP {ip} was NOT vetoed! Got: {res}",
            )
            self.assertEqual(res.get("action_taken"), "none")
            self.assertIn("VETO", res.get("message", ""))
            # Firewall controller không được chứa bất kỳ rule drop nào cho IP này
            self.assertFalse(await self.mock_fw.is_blocked(ip))
            self.assertFalse(await self.mock_fw.is_blocked("127.0.0.1"))

    async def test_ipv4_mapped_private_lan_and_docker_veto(self):
        """Tất cả các biến thể ::ffff: LAN & Docker subnets phải bị VETO 100%."""
        lan_docker_variants = [
            "::ffff:192.168.0.1",
            "::ffff:192.168.1.100",
            "::ffff:10.0.0.1",
            "::ffff:10.254.254.1",
            "::ffff:172.16.0.1",
            "::ffff:172.18.0.22",
            "::ffff:172.31.255.254",
            "::ffff:169.254.1.1",
        ]
        for ip in lan_docker_variants:
            res = await self.service.block_ip(ip, reason="Adversarial mapped LAN block")
            self.assertEqual(
                res.get("status"),
                "veto",
                f"LAN IP {ip} was NOT vetoed! Got: {res}",
            )
            self.assertEqual(res.get("action_taken"), "none")
            self.assertFalse(await self.mock_fw.is_blocked(ip))

    async def test_ipv4_mapped_cloudflare_and_custom_whitelist_veto(self):
        """Cloudflare CIDRs và Custom IPs ở dạng ::ffff: phải bị VETO 100%."""
        cf_and_custom = [
            "::ffff:173.245.48.1",  # Cloudflare
            "::ffff:104.16.1.1",    # Cloudflare
            "::ffff:192.0.2.100",   # Custom IP
            "::ffff:203.0.113.50",  # Custom IP
        ]
        for ip in cf_and_custom:
            res = await self.service.block_ip(ip, reason="Adversarial mapped CF/custom block")
            self.assertEqual(res.get("status"), "veto", f"IP {ip} was NOT vetoed! Got: {res}")
            self.assertEqual(res.get("action_taken"), "none")

    async def test_ipv4_mapped_untrusted_attacker_blocked_cleanly(self):
        """Địa chỉ IP attacker hợp lệ ở dạng mapped ::ffff:45.83.122.7 phải được unwrap và khóa thành công."""
        res = await self.service.block_ip("::ffff:45.83.122.7", reason="Adversarial attacker block")
        self.assertEqual(res.get("status"), "success")
        self.assertEqual(res.get("ip"), "45.83.122.7")
        self.assertEqual(res.get("action_taken"), "iptables_drop")
        self.assertTrue(await self.mock_fw.is_blocked("45.83.122.7"))


class TestAdversarialSpoofedXForwardedFor(unittest.IsolatedAsyncioTestCase):
    """
    Kịch bản 2: Kiểm thử đối kháng giả mạo Header X-Forwarded-For.
    Kỳ vọng:
    1. Khi remote_addr là IP untrusted ngoài Internet, bỏ qua 100% header X-Forwarded-For.
    2. Chặn đứng kịch bản VETO Evasion: Attacker giả mạo IP admin trong whitelist.
    3. Chặn đứng kịch bản Reflected DoS: Attacker giả mạo IP nạn nhân vô tội trong XFF.
    4. Khi remote_addr là Trusted Proxy (Loopback, Docker, Cloudflare), trích xuất chuẩn xác Right-to-Left.
    """

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_spoofed_xff.db")
        self.mock_fw = MockFirewallController()
        self.service = SecurityMonitorService(
            firewall=self.mock_fw,
            db_path=self.db_path,
            custom_whitelist_ips=["192.168.1.50"],
        )
        await self.service.start()

    async def asyncTearDown(self):
        await self.service.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_spoofed_xff_veto_evasion_blocked(self):
        """Attacker từ 45.83.122.7 gửi X-Forwarded-For: 192.168.1.50 (Admin whitelist) nhằm trốn VETO."""
        attacker_ip = "45.83.122.7"
        admin_whitelist_ip = "192.168.1.50"

        line = (
            f'{attacker_ip} - - [27/Sep/2026:12:00:00 +0700] '
            f'"GET /api/user?id=1%20UNION%20SELECT%201,2,3 HTTP/1.1" 200 100 "-" "curl" "{admin_whitelist_ip}"'
        )
        ev = await self.service.process_log_line(line, log_type="nginx")
        self.assertIsNotNone(ev, "Attack was not detected!")
        # Hệ thống phải trích xuất chính attacker_ip
        self.assertEqual(ev.get("ip"), attacker_ip)
        self.assertEqual(ev.get("attack_type"), "sqli")
        self.assertEqual(ev.get("action_taken"), "iptables_drop")
        # Attacker phải bị khóa trên firewall
        self.assertTrue(await self.mock_fw.is_blocked(attacker_ip))
        # Admin IP không được bị ảnh hưởng hay bị gán nhầm
        self.assertFalse(await self.mock_fw.is_blocked(admin_whitelist_ip))

    async def test_spoofed_xff_reflected_dos_innocent_victim_protected(self):
        """Attacker từ 45.83.122.7 gửi X-Forwarded-For: 203.0.113.5 (IP vô tội) nhằm mượn tay firewall khóa IP nạn nhân."""
        attacker_ip = "45.83.122.7"
        innocent_victim = "203.0.113.5"

        line = (
            f'{attacker_ip} - - [27/Sep/2026:12:00:00 +0700] '
            f'"GET /login?user=admin%27%20OR%201=1-- HTTP/1.1" 200 100 "-" "curl" "{innocent_victim}"'
        )
        ev = await self.service.process_log_line(line, log_type="nginx")
        self.assertIsNotNone(ev)
        self.assertEqual(ev.get("ip"), attacker_ip)
        self.assertEqual(ev.get("action_taken"), "iptables_drop")
        # Nạn nhân vô tội KHÔNG được bị khóa!
        self.assertFalse(await self.mock_fw.is_blocked(innocent_victim))
        # Kẻ tấn công thực sự BẮT BUỘC bị khóa!
        self.assertTrue(await self.mock_fw.is_blocked(attacker_ip))

    async def test_spoofed_xff_complex_chained_headers(self):
        """Attacker gửi chuỗi proxy giả mạo nhiều chặng: 127.0.0.1, 10.0.0.1, 192.168.1.1, 8.8.8.8."""
        attacker_ip = "45.83.122.7"
        fake_chain = "127.0.0.1, 10.0.0.1, 192.168.1.1, 8.8.8.8"

        line = (
            f'{attacker_ip} - - [27/Sep/2026:12:00:00 +0700] '
            f'"GET /items?id=1%20OR%201=1%23 HTTP/1.1" 200 100 "-" "curl" "{fake_chain}"'
        )
        ev = await self.service.process_log_line(line, log_type="nginx")
        self.assertIsNotNone(ev)
        self.assertEqual(ev.get("ip"), attacker_ip)
        self.assertTrue(await self.mock_fw.is_blocked(attacker_ip))

    def test_extract_client_ip_direct_matrix(self):
        """Kiểm thử trực tiếp ma trận logic của extract_client_ip."""
        # 1. Untrusted peer: XFF luôn bị lờ đi
        self.assertEqual(extract_client_ip("45.83.122.7", "192.168.1.1"), "45.83.122.7")
        self.assertEqual(extract_client_ip("45.83.122.7", "203.0.113.1"), "45.83.122.7")
        self.assertEqual(extract_client_ip("45.83.122.7", "::ffff:127.0.0.1"), "45.83.122.7")

        # 2. Trusted Loopback Proxy: lấy client IP từ XFF
        self.assertEqual(extract_client_ip("127.0.0.1", "45.83.122.7"), "45.83.122.7")
        self.assertEqual(extract_client_ip("::1", "45.83.122.7"), "45.83.122.7")

        # 3. Trusted Docker Bridge: duyệt right-to-left
        self.assertEqual(extract_client_ip("172.18.0.1", "45.83.122.7, 172.18.0.1"), "45.83.122.7")

        # 4. Trusted Cloudflare Proxy: duyệt right-to-left
        self.assertEqual(extract_client_ip("173.245.48.5", "45.83.122.7, 104.16.1.1"), "45.83.122.7")

        # 5. Trusted Proxy với client IP dạng mapped ::ffff:
        self.assertEqual(extract_client_ip("127.0.0.1", "::ffff:45.83.122.7"), "45.83.122.7")

        # 6. All trusted hops: fallback về leftmost IP
        self.assertEqual(extract_client_ip("127.0.0.1", "10.0.0.5, 192.168.1.10"), "10.0.0.5")


class TestAdversarialSQLiEvasion(unittest.IsolatedAsyncioTestCase):
    """
    Kịch bản 3: Kiểm thử đối kháng các kỹ thuật né tránh SQL Injection (SQLi Evasion).
    Kỳ vọng:
    1. Nhận diện 100% các biến thể chèn comment SQL (/**/, /*comment*/, /*\n*/).
    2. Nhận diện 100% các biến thể injection kiểu số (numeric boolean OR 1=1--, OR 1=1#, OR 1=1/*).
    3. Không gây ra False Positive đối với các truy vấn web bình thường của người dùng.
    """

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_sqli_evasion.db")
        self.mock_fw = MockFirewallController()
        self.service = SecurityMonitorService(
            firewall=self.mock_fw,
            db_path=self.db_path,
        )
        await self.service.start()

    async def asyncTearDown(self):
        await self.service.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_sqli_comment_obfuscation_matrix(self):
        """Thử nghiệm ma trận payload dùng comment SQL thay thế khoảng trắng."""
        payloads = [
            "1 UNION/**/SELECT 1,2,3",
            "1 UNION/*foo*/SELECT 1,2,3",
            "1/**/UNION/**/SELECT/**/1,2,3",
            "1 UNION/*!--+!*/SELECT 1,2,3",
            "1 UNION/*comment1*//*comment2*/SELECT 1,2,3",
            "1 UNION ALL SELECT 1,2,3",
            "1 UNION/**/ALL/**/SELECT 1,2,3",
            "1 UNION/*waf_bypass*/ALL/*waf_bypass*/SELECT 1,2,3",
        ]
        for p in payloads:
            encoded = urllib.parse.quote(p)
            line = f'45.83.122.7 - - [27/Sep/2026:12:00:00 +0700] "GET /products?id={encoded} HTTP/1.1" 200 100 "-" "curl" "-"'
            ev = await self.service.process_log_line(line, log_type="nginx")
            self.assertIsNotNone(ev, f"SQLi payload was EVADED: '{p}' (encoded: {encoded})")
            self.assertEqual(ev.get("attack_type"), "sqli", f"Wrong attack type for '{p}'")

    async def test_sqli_numeric_boolean_injection_matrix(self):
        """Thử nghiệm ma trận boolean-based numeric injection không có dấu nháy."""
        payloads = [
            "1 OR 1=1--",
            "1 OR 1=1-- ",
            "1 OR 1=1#",
            "1 or 1=1#",
            "1 OR 1=1/*",
            "1 OR 1=1;",
            "1 OR 1=1",
            "1 AND 1=1--",
            "1 and 2=2#",
            "admin' OR 1=1--",
            "admin' or '1'='1",
            "\" OR \"1\"=\"1",
            "' OR 'x'='x'--",
            "1; DROP TABLE users;",
            "1; EXEC xp_cmdshell('dir')",
            "1 AND SLEEP(5)",
            "1 WAITFOR DELAY '0:0:5'",
        ]
        for p in payloads:
            encoded = urllib.parse.quote(p)
            line = f'45.83.122.7 - - [27/Sep/2026:12:00:00 +0700] "GET /items?query={encoded} HTTP/1.1" 200 100 "-" "curl" "-"'
            ev = await self.service.process_log_line(line, log_type="nginx")
            self.assertIsNotNone(ev, f"SQLi numeric/comment payload was EVADED: '{p}' (encoded: {encoded})")
            self.assertEqual(ev.get("attack_type"), "sqli", f"Wrong attack type for '{p}'")

    async def test_benign_queries_no_false_positives(self):
        """Kiểm thử ma trận truy vấn người dùng bình thường để đảm bảo không bị chặn nhầm."""
        benign_queries = [
            "/search?q=select+options+from+menu",
            "/blog/how-to-update-firmware-from-usb",
            "/cart?action=delete&from=wishlist",
            "/api-docs",
            "/api-docs/swagger",
            "/help?action=confirm(email)",
            "/search?q=alert(battery)",
            "/blog/how-to-edit-etc-hosts",
            "/forum/thread?title=order+by+date",
            "/docs?topic=information_schema_overview",
            "/products?category=oranges",
            "/store/item?color=black&size=10",
        ]
        for url in benign_queries:
            line = f'203.0.113.10 - - [27/Sep/2026:12:00:00 +0700] "GET {url} HTTP/1.1" 200 500 "-" "Mozilla/5.0" "-"'
            ev = await self.service.process_log_line(line, log_type="nginx")
            self.assertIsNone(ev, f"False Positive detected on benign URL: '{url}'")


class TestAdversarialHostFirewallIsBlocked(unittest.IsolatedAsyncioTestCase):
    """
    Kịch bản 4: Kiểm thử đối kháng hàm HostFirewallController.is_blocked.
    Kỳ vọng:
    1. Khi lệnh iptables trả về exit code non-zero ("1", "2", 1, 2, Bad rule stderr), hàm PHẢI trả về False.
    2. Chỉ trả về True khi rule thực sự tồn tại (exit code 0 / returncode 0).
    3. Không bị crash hay False Positive khi có lỗi kết nối hoặc exception.
    """

    class MockSshReturner:
        def __init__(self, ret_val: Any, should_raise: bool = False):
            self.ret_val = ret_val
            self.should_raise = should_raise
            self.last_cmd = ""

        async def execute_command(self, cmd: str) -> Any:
            self.last_cmd = cmd
            if self.should_raise:
                raise RuntimeError("SSH connection broken or command timed out")
            return self.ret_val

    async def test_is_blocked_exit_codes_and_outputs(self):
        cases = [
            # (ssh output, expected boolean result, description)
            ("0", True, "Return code 0 string -> rule exists"),
            (0, True, "Return code 0 integer -> rule exists"),
            ("1", False, "Return code 1 string -> rule does not exist"),
            (1, False, "Return code 1 integer -> rule does not exist"),
            ("2", False, "Return code 2 string -> error"),
            ("255", False, "Return code 255 string -> error"),
            (
                "iptables: Bad rule (does a matching rule exist in that chain?).\n1",
                False,
                "Standard Linux iptables missing rule output",
            ),
            (
                "iptables v1.8.7 (legacy): Bad rule (does a matching rule exist in that chain?)\n1",
                False,
                "Legacy iptables missing rule output",
            ),
            (
                "iptables: No chain/target/match by that name.\n1",
                False,
                "Chain not found error",
            ),
            (
                "sudo: a password is required\n1",
                False,
                "Sudo permission error",
            ),
            ("", False, "Empty output -> not blocked"),
            ("error: permission denied", False, "Generic error message"),
            ("BLOCKED: false", False, "Legacy blocked indicator"),
        ]

        for val, expected, desc in cases:
            ssh = self.MockSshReturner(val)
            fw = HostFirewallController(ssh)
            res = await fw.is_blocked("198.51.100.5")
            self.assertEqual(res, expected, f"Failed case [{desc}]: expected {expected}, got {res} (val={val!r})")

    async def test_is_blocked_with_process_object(self):
        """Kiểm thử khi ssh_client trả về object có thuộc tính returncode."""
        class ProcRes:
            def __init__(self, code: int):
                self.returncode = code

        ssh0 = self.MockSshReturner(ProcRes(0))
        fw0 = HostFirewallController(ssh0)
        self.assertTrue(await fw0.is_blocked("198.51.100.5"))

        ssh1 = self.MockSshReturner(ProcRes(1))
        fw1 = HostFirewallController(ssh1)
        self.assertFalse(await fw1.is_blocked("198.51.100.5"))

    async def test_is_blocked_exception_resilience(self):
        """Khi SSH client ném ngoại lệ, is_blocked phải trả về False an toàn."""
        ssh_err = self.MockSshReturner(None, should_raise=True)
        fw = HostFirewallController(ssh_err)
        self.assertFalse(await fw.is_blocked("198.51.100.5"))

    async def test_is_blocked_ipv4_mapped_unwrapping_in_command(self):
        """Kiểm tra xem clean_ip trong lệnh iptables có được unwrap từ ::ffff: sang IPv4 không."""
        ssh = self.MockSshReturner("0")
        fw = HostFirewallController(ssh)
        await fw.is_blocked("::ffff:198.51.100.5")
        self.assertIn("-s 198.51.100.5", ssh.last_cmd)
        self.assertNotIn("::ffff", ssh.last_cmd)

    async def test_is_blocked_invalid_ip_rejection(self):
        """IP không hợp lệ hoặc chứa command injection phải trả về False ngay lập tức."""
        ssh = self.MockSshReturner("0")
        fw = HostFirewallController(ssh)
        self.assertFalse(await fw.is_blocked("not-an-ip"))
        self.assertFalse(await fw.is_blocked("198.51.100.5; rm -rf /"))
        self.assertFalse(await fw.is_blocked(""))


if __name__ == "__main__":
    unittest.main()
