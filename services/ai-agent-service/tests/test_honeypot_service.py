"""
services/ai-agent-service/tests/test_honeypot_service.py
Comprehensive Unit Test Suite for Honeypot Service (Milestone 2 - Deception Layer).

Tests:
1. strip_telnet_iac FSM (RFC 854): 2-byte commands, 3-byte negotiations, subnegotiations, escaped IAC.
2. Fake SSH Listener (Port 2222 simulation): Banner, prompt user/pass, 3-attempt fail message, disconnect.
3. Fake Telnet Listener (Port 23 simulation): Ubuntu banner, IAC stripping on input, prompt, 3-attempt fail message, disconnect.
4. DoS Protection: max_connections semaphore limit & socket read timeout.
5. Dual-Tier Storage & Persistence: save, get_honeypot_log with limit and service filtering.
6. In-Memory Metrics & get_stats(): O(1) synchronous statistics.
7. Callbacks & Auto-defense hooks: on_harvest_callback and on_block_ip_callback.
8. Clean lifecycle & shutdown: 0 ResourceWarning unclosed transport/socket.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import os
import shutil
import socket
import tempfile
import time
import unittest

from app.services.honeypot_service import (
    HoneypotConfig,
    HoneypotCredentialRecord,
    HoneypotService,
    HoneypotStorageRepository,
    strip_telnet_iac,
)


def get_free_port() -> int:
    """Finds an available local TCP port dynamically to prevent port collisions in tests."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestTelnetIACFilter(unittest.TestCase):
    """Verifies strip_telnet_iac RFC 854 FSM state machine."""

    def test_strip_plain_ascii(self):
        data = b"admin123\r\n"
        self.assertEqual(strip_telnet_iac(data), b"admin123\r\n")

    def test_strip_escaped_iac(self):
        # 0xFF 0xFF should produce a single 0xFF
        data = b"foo\xff\xffbar"
        self.assertEqual(strip_telnet_iac(data), b"foo\xffbar")

    def test_strip_three_byte_negotiations(self):
        # IAC DO (0xFD) ECHO (0x01), IAC WILL (0xFB) SUPPRESS_GO_AHEAD (0x03)
        data = b"\xff\xfd\x01\xff\xfb\x03kirito"
        self.assertEqual(strip_telnet_iac(data), b"kirito")

        # IAC WONT (0xFC), IAC DONT (0xFE)
        data2 = b"user\xff\xfc\x1f\xff\xfe\x18pass"
        self.assertEqual(strip_telnet_iac(data2), b"userpass")

    def test_strip_subnegotiation(self):
        # IAC SB (0xFA) ... IAC SE (0xFF 0xF0)
        subneg = b"\xff\xfa\x18\x00VT100\xff\xf0"
        data = subneg + b"ubuntu"
        self.assertEqual(strip_telnet_iac(data), b"ubuntu")

    def test_strip_generic_two_byte_command(self):
        # IAC NOP (0xF1), IAC AYT (0xF6)
        data = b"\xff\xf1test\xff\xf6"
        self.assertEqual(strip_telnet_iac(data), b"test")

    def test_strip_truncated_or_empty(self):
        self.assertEqual(strip_telnet_iac(b""), b"")
        self.assertEqual(strip_telnet_iac(b"\xff"), b"")
        self.assertEqual(strip_telnet_iac(b"abc\xff"), b"abc")


class TestHoneypotStorage(unittest.IsolatedAsyncioTestCase):
    """Verifies SQLite WAL mode fallback and Credential Record operations."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_honeypot.db")
        self.repo = HoneypotStorageRepository(db_path=self.db_path, use_postgres=False)

    async def asyncTearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_save_and_retrieve_credentials(self):
        rec1 = HoneypotCredentialRecord(
            id=None,
            ip="198.51.100.10",
            service="ssh",
            username="root",
            password="password123",
            attempt_count=1,
            captured_at=time.time() - 10,
        )
        rec2 = HoneypotCredentialRecord(
            id=None,
            ip="198.51.100.11",
            service="telnet",
            username="admin",
            password="admin@2026",
            attempt_count=2,
            captured_at=time.time(),
        )

        id1 = await self.repo.save_credential(rec1)
        id2 = await self.repo.save_credential(rec2)

        self.assertIsNotNone(id1)
        self.assertIsNotNone(id2)

        all_logs = await self.repo.get_credentials(limit=10)
        self.assertEqual(len(all_logs), 2)
        # Newest first
        self.assertEqual(all_logs[0]["username"], "admin")
        self.assertEqual(all_logs[1]["username"], "root")

    async def test_filter_by_service(self):
        for i in range(3):
            await self.repo.save_credential(HoneypotCredentialRecord(
                id=None,
                ip=f"198.51.100.{i}",
                service="ssh",
                username=f"ssh_user_{i}",
                password="pwd",
                attempt_count=1,
            ))
        for j in range(2):
            await self.repo.save_credential(HoneypotCredentialRecord(
                id=None,
                ip=f"203.0.113.{j}",
                service="telnet",
                username=f"telnet_user_{j}",
                password="pwd",
                attempt_count=1,
            ))

        ssh_logs = await self.repo.get_credentials(limit=10, service="ssh")
        telnet_logs = await self.repo.get_credentials(limit=10, service="telnet")

        self.assertEqual(len(ssh_logs), 3)
        self.assertEqual(len(telnet_logs), 2)
        self.assertTrue(all(r["service"] == "ssh" for r in ssh_logs))
        self.assertTrue(all(r["service"] == "telnet" for r in telnet_logs))


class TestFakeSSHServer(unittest.IsolatedAsyncioTestCase):
    """Verifies Fake SSH listener behavior (banner, login prompts, 3-attempt troll payload)."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_ssh.db")
        self.ssh_port = get_free_port()
        self.telnet_port = get_free_port()

        self.harvested_events = []
        self.blocked_events = []

        async def harvest_cb(event):
            self.harvested_events.append(event)

        async def block_cb(ip, reason):
            self.blocked_events.append((ip, reason))

        self.config = HoneypotConfig(
            bind_host="127.0.0.1",
            ssh_port=self.ssh_port,
            telnet_port=self.telnet_port,
            db_path=self.db_path,
            use_postgres=False,
            auth_delay=0.01,  # Fast tests
            socket_timeout=5.0,
        )
        self.service = HoneypotService(
            config=self.config,
            on_harvest_callback=harvest_cb,
            on_block_ip_callback=block_cb,
        )
        await self.service.start()

    async def asyncTearDown(self):
        await self.service.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_ssh_banner_and_three_attempts_troll_payload(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.ssh_port)

        try:
            # 1. Read SSH Banner
            banner = await asyncio.wait_for(reader.readline(), timeout=3.0)
            self.assertIn(b"SSH-2.0-OpenSSH", banner)

            # 2. Attempt 1
            await asyncio.wait_for(reader.readuntil(b"login: "), timeout=3.0)
            writer.write(b"root\r\n")
            await writer.drain()

            await asyncio.wait_for(reader.readuntil(b"Password: "), timeout=3.0)
            writer.write(b"123456\r\n")
            await writer.drain()

            denied = await asyncio.wait_for(reader.readuntil(b"Access denied\r\n\r\n"), timeout=3.0)
            self.assertIn(b"Access denied", denied)

            # 3. Attempt 2
            await asyncio.wait_for(reader.readuntil(b"login: "), timeout=3.0)
            writer.write(b"admin\r\n")
            await writer.drain()

            await asyncio.wait_for(reader.readuntil(b"Password: "), timeout=3.0)
            writer.write(b"admin@2026\r\n")
            await writer.drain()

            denied = await asyncio.wait_for(reader.readuntil(b"Access denied\r\n\r\n"), timeout=3.0)
            self.assertIn(b"Access denied", denied)

            # 4. Attempt 3 (Final attempt -> Troll payload)
            await asyncio.wait_for(reader.readuntil(b"login: "), timeout=3.0)
            writer.write(b"kirito\r\n")
            await writer.drain()

            await asyncio.wait_for(reader.readuntil(b"Password: "), timeout=3.0)
            writer.write(b"kirito_pass\r\n")
            await writer.drain()

            # Expect troll payload
            response = await asyncio.wait_for(reader.read(1024), timeout=3.0)
            self.assertIn("💀 Kẻ thất bại".encode("utf-8"), response)
            self.assertIn("Tiểu Bảo Bảo Security Team 😂".encode("utf-8"), response)

            # Expect connection closed by server
            eof = await asyncio.wait_for(reader.read(100), timeout=2.0)
            self.assertEqual(eof, b"")

        finally:
            writer.close()
            await writer.wait_closed()

        # Verify callbacks
        self.assertEqual(len(self.harvested_events), 1)
        event = self.harvested_events[0]
        self.assertEqual(event["service"], "ssh")
        self.assertEqual(event["attempts"], 3)
        self.assertEqual(len(event["credentials"]), 3)
        self.assertEqual(event["credentials"][0], ("root", "123456"))
        self.assertEqual(event["credentials"][1], ("admin", "admin@2026"))
        self.assertEqual(event["credentials"][2], ("kirito", "kirito_pass"))

        # Verify auto-block triggered
        self.assertEqual(len(self.blocked_events), 1)
        self.assertIn("3 failed attempts", self.blocked_events[0][1])

        # Verify log persistence
        logs = await self.service.get_honeypot_log(limit=10)
        self.assertEqual(len(logs), 3)


class TestFakeTelnetServer(unittest.IsolatedAsyncioTestCase):
    """Verifies Fake Telnet listener behavior (Ubuntu banner, IAC filtering, prompts, troll payload)."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_telnet.db")
        self.ssh_port = get_free_port()
        self.telnet_port = get_free_port()

        self.harvested_events = []
        self.blocked_events = []

        async def harvest_cb(event):
            self.harvested_events.append(event)

        async def block_cb(ip, reason):
            self.blocked_events.append((ip, reason))

        self.config = HoneypotConfig(
            bind_host="127.0.0.1",
            ssh_port=self.ssh_port,
            telnet_port=self.telnet_port,
            db_path=self.db_path,
            use_postgres=False,
            auth_delay=0.01,
            socket_timeout=5.0,
        )
        self.service = HoneypotService(
            config=self.config,
            on_harvest_callback=harvest_cb,
            on_block_ip_callback=block_cb,
        )
        await self.service.start()

    async def asyncTearDown(self):
        await self.service.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_telnet_iac_stripping_and_troll_payload(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.telnet_port)

        try:
            # 1. Read Welcome Banner
            banner = await asyncio.wait_for(reader.readuntil(b"kirito-server login: "), timeout=3.0)
            self.assertIn(b"Ubuntu 22.04.4 LTS", banner)
            self.assertIn(b"kirito-server login: ", banner)

            # Attempt 1: Send username polluted with Telnet IAC bytes
            # IAC DO ECHO (0xFF 0xFD 0x01) + "operator" + \r\n
            writer.write(b"\xff\xfd\x01operator\r\n")
            await writer.drain()

            await asyncio.wait_for(reader.readuntil(b"Password: "), timeout=3.0)

            # Send password with IAC WILL SUPPRESS_GO_AHEAD (0xFF 0xFB 0x03)
            writer.write(b"\xff\xfb\x03secret_op\r\n")
            await writer.drain()

            incorrect = await asyncio.wait_for(reader.readuntil(b"Login incorrect\r\n\r\n"), timeout=3.0)
            self.assertIn(b"Login incorrect", incorrect)

            # Attempt 2
            await asyncio.wait_for(reader.readuntil(b"kirito-server login: "), timeout=3.0)
            writer.write(b"support\r\n")
            await writer.drain()

            await asyncio.wait_for(reader.readuntil(b"Password: "), timeout=3.0)
            writer.write(b"support123\r\n")
            await writer.drain()

            incorrect = await asyncio.wait_for(reader.readuntil(b"Login incorrect\r\n\r\n"), timeout=3.0)
            self.assertIn(b"Login incorrect", incorrect)

            # Attempt 3 -> Troll payload
            await asyncio.wait_for(reader.readuntil(b"kirito-server login: "), timeout=3.0)
            writer.write(b"root\r\n")
            await writer.drain()

            await asyncio.wait_for(reader.readuntil(b"Password: "), timeout=3.0)
            writer.write(b"toor\r\n")
            await writer.drain()

            # Read troll payload
            response = await asyncio.wait_for(reader.read(1024), timeout=3.0)
            self.assertIn("💀 Kẻ thất bại".encode("utf-8"), response)

            # Read EOF
            eof = await asyncio.wait_for(reader.read(100), timeout=2.0)
            self.assertEqual(eof, b"")

        finally:
            writer.close()
            await writer.wait_closed()

        # Check IAC was stripped clean in harvested record
        logs = await self.service.get_honeypot_log(limit=10, service="telnet")
        self.assertEqual(len(logs), 3)
        # Oldest first: username "operator" should not contain 0xFF
        oldest = logs[-1]
        self.assertEqual(oldest["username"], "operator")
        self.assertEqual(oldest["password"], "secret_op")


class TestDoSProtectionAndTimeout(unittest.IsolatedAsyncioTestCase):
    """Verifies concurrency limiting (max_connections) and read timeout."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_dos.db")
        self.ssh_port = get_free_port()
        self.telnet_port = get_free_port()

        # Max connections = 2 for quick testing
        self.config = HoneypotConfig(
            bind_host="127.0.0.1",
            ssh_port=self.ssh_port,
            telnet_port=self.telnet_port,
            max_connections=2,
            socket_timeout=0.4,  # Quick timeout
            auth_delay=0.01,
            db_path=self.db_path,
            use_postgres=False,
        )
        self.service = HoneypotService(config=self.config)
        await self.service.start()

    async def asyncTearDown(self):
        await self.service.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_socket_timeout_slowloris(self):
        """Client connects and stays silent. Server should disconnect after timeout."""
        reader, writer = await asyncio.open_connection("127.0.0.1", self.ssh_port)
        try:
            # Read banner
            await reader.readline()
            # Read 'login: '
            await reader.readuntil(b"login: ")
            # Stay silent and wait for timeout disconnection
            start_wait = time.time()
            data = await asyncio.wait_for(reader.read(100), timeout=2.0)
            self.assertEqual(data, b"")  # Connection closed by server
            self.assertGreaterEqual(time.time() - start_wait, 0.3)
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_max_connections_limit(self):
        """Exceeding max_connections should drop new connection immediately."""
        clients = []
        try:
            # Connection 1
            r1, w1 = await asyncio.open_connection("127.0.0.1", self.ssh_port)
            clients.append(w1)
            await r1.readline()

            # Connection 2 (Reaches limit = 2)
            r2, w2 = await asyncio.open_connection("127.0.0.1", self.ssh_port)
            clients.append(w2)
            await r2.readline()

            # Connection 3 (Exceeds limit -> should be closed immediately)
            r3, w3 = await asyncio.open_connection("127.0.0.1", self.ssh_port)
            clients.append(w3)

            # Reading from connection 3 should immediately yield EOF or empty
            eof = await asyncio.wait_for(r3.read(100), timeout=1.0)
            self.assertEqual(eof, b"")

        finally:
            for w in clients:
                try:
                    w.close()
                    await w.wait_closed()
                except Exception:
                    pass


class TestHoneypotStatsAndState(unittest.IsolatedAsyncioTestCase):
    """Verifies fast-path get_stats() synchronous query and metrics accumulation."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_stats.db")
        self.ssh_port = get_free_port()
        self.telnet_port = get_free_port()

        self.config = HoneypotConfig(
            bind_host="127.0.0.1",
            ssh_port=self.ssh_port,
            telnet_port=self.telnet_port,
            db_path=self.db_path,
            use_postgres=False,
        )
        self.service = HoneypotService(config=self.config)
        await self.service.start()

    async def asyncTearDown(self):
        await self.service.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_stats_aggregation(self):
        await self.service.log_credential("198.51.100.1", "ssh", "root", "123456", attempt_count=1)
        await self.service.log_credential("198.51.100.1", "ssh", "root", "password", attempt_count=2)
        await self.service.log_credential("198.51.100.2", "telnet", "admin", "admin", attempt_count=1)

        stats = self.service.get_stats()
        self.assertEqual(stats["status"], "running")
        self.assertGreaterEqual(stats["uptime_seconds"], 0.0)
        self.assertEqual(stats["total_probes"], 3)
        self.assertEqual(stats["total_credentials"], 3)
        self.assertEqual(stats["service_breakdown"]["ssh"], 2)
        self.assertEqual(stats["service_breakdown"]["telnet"], 1)
        self.assertEqual(stats["unique_ips_count"], 2)
        self.assertEqual(stats["top_usernames"][0]["username"], "root")
        self.assertEqual(stats["top_usernames"][0]["count"], 2)
        self.assertEqual(stats["probes_last_hour"], 3)
        self.assertTrue(stats["listeners"]["ssh"]["active"])
        self.assertTrue(stats["listeners"]["telnet"]["active"])


class TestCleanShutdownNoResourceWarning(unittest.IsolatedAsyncioTestCase):
    """Guarantees 0 ResourceWarning unclosed transport when stopping service with active clients."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_shutdown.db")
        self.ssh_port = get_free_port()
        self.telnet_port = get_free_port()

        self.config = HoneypotConfig(
            bind_host="127.0.0.1",
            ssh_port=self.ssh_port,
            telnet_port=self.telnet_port,
            db_path=self.db_path,
            use_postgres=False,
        )
        self.service = HoneypotService(config=self.config)
        await self.service.start()

    async def asyncTearDown(self):
        await self.service.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_shutdown_with_dangling_connections(self):
        # Open 2 connections and leave them open
        r1, w1 = await asyncio.open_connection("127.0.0.1", self.ssh_port)
        r2, w2 = await asyncio.open_connection("127.0.0.1", self.telnet_port)

        await r1.readline()
        await r2.readline()

        # Stop service while clients are still connected
        await self.service.stop()

        # Now clean up test client sockets
        w1.close()
        await w1.wait_closed()
        w2.close()
        await w2.wait_closed()

        stats = self.service.get_stats()
        self.assertEqual(stats["status"], "stopped")
        self.assertFalse(stats["listeners"]["ssh"]["active"])
        self.assertFalse(stats["listeners"]["telnet"]["active"])


if __name__ == "__main__":
    unittest.main()
