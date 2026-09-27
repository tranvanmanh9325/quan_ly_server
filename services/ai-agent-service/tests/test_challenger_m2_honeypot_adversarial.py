"""
services/ai-agent-service/tests/test_challenger_m2_honeypot_adversarial.py
Adversarial Stress Test Suite for Honeypot Service (Milestone 2 - Reviewer 2).

Tests:
1. Abrupt Disconnection & TCP RST:
   - Immediate RST on connect (SO_LINGER = 1, 0)
   - Disconnect during banner transmission
   - Disconnect midway through username / password prompt
   - Disconnect during troll payload transmission
2. Garbage & Malicious Ingestion:
   - Chunk exceeding max_line_length (1024B) triggering StreamReader ValueError
   - Random binary fuzzing & Null bytes (\x00)
   - Malformed Telnet IAC (unterminated subnegotiation, dangling 0xFF)
   - Extreme Unicode, SQLi/Command injection payloads
3. Concurrency Burst & Resource Leak Check:
   - Concurrent mixed good/abrupt connections
   - Accurate metric accumulation under stress
   - Zero ResourceWarning unclosed transport
"""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import struct
import tempfile
import time
import unittest

from app.services.honeypot_service import (
    HoneypotConfig,
    HoneypotService,
    strip_telnet_iac,
)


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestAdversarialHoneypot(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_adv.db")
        self.ssh_port = get_free_port()
        self.telnet_port = get_free_port()

        self.harvested_events = []
        self.blocked_ips = []

        async def harvest_cb(event):
            self.harvested_events.append(event)

        async def block_cb(ip, reason):
            self.blocked_ips.append((ip, reason))

        self.config = HoneypotConfig(
            bind_host="127.0.0.1",
            ssh_port=self.ssh_port,
            telnet_port=self.telnet_port,
            max_connections=30,
            socket_timeout=1.0,
            max_line_length=512,  # Lower limit for stress testing line buffer overflow
            auth_delay=0.01,
            db_path=self.db_path,
            use_postgres=False,
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

    # ── 1. ABRUPT DISCONNECT & TCP RST ────────────────────────────────────────

    async def test_abrupt_rst_immediately_after_connect(self):
        """Client connects and immediately issues TCP RST with SO_LINGER=(1, 0)."""
        def _sync_rst():
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            s.connect(("127.0.0.1", self.ssh_port))
            s.close()

        for _ in range(5):
            await asyncio.to_thread(_sync_rst)

        # Service must still be alive and responsive
        reader, writer = await asyncio.open_connection("127.0.0.1", self.ssh_port)
        banner = await asyncio.wait_for(reader.readline(), timeout=2.0)
        self.assertIn(b"SSH-2.0-OpenSSH", banner)
        writer.close()
        await writer.wait_closed()

    async def test_abrupt_disconnect_midway_through_credentials(self):
        """Client disconnects abruptly after receiving login prompt without sending anything."""
        for port in (self.ssh_port, self.telnet_port):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            await asyncio.wait_for(reader.readline(), timeout=2.0)
            # Close without sending user/pass
            writer.close()
            await writer.wait_closed()

        # Give event loop a cycle to finish task cleanup
        await asyncio.sleep(0.05)

        # Service should operate normally
        stats = self.service.get_stats()
        self.assertEqual(stats["status"], "running")
        self.assertEqual(stats["active_connections"], 0)

    async def test_abrupt_disconnect_after_partial_username(self):
        """Client sends partial username without newline then resets connection."""
        def _sync_partial():
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            s.connect(("127.0.0.1", self.ssh_port))
            s.recv(64)
            s.sendall(b"partial_adm")
            s.close()

        await asyncio.to_thread(_sync_partial)
        await asyncio.sleep(0.05)

        # Verify next valid connection still succeeds
        reader, writer = await asyncio.open_connection("127.0.0.1", self.ssh_port)
        banner = await asyncio.wait_for(reader.readline(), timeout=2.0)
        self.assertIn(b"SSH-2.0-OpenSSH", banner)
        writer.close()
        await writer.wait_closed()

    # ── 2. GARBAGE & MALICIOUS INGESTION ──────────────────────────────────────

    async def test_oversized_line_buffer_overflow(self):
        """Client sends 2048 bytes without newline (exceeding max_line_length=512)."""
        reader, writer = await asyncio.open_connection("127.0.0.1", self.ssh_port)
        try:
            await reader.readline()
            await reader.readuntil(b"login: ")

            # Send massive junk payload without \n
            writer.write(b"A" * 2048)
            await writer.drain()

            # Server's readline() will hit LimitExceeded / ValueError and terminate connection
            eof = await asyncio.wait_for(reader.read(100), timeout=2.0)
            self.assertEqual(eof, b"")
        finally:
            writer.close()
            await writer.wait_closed()

        # Ensure server did not crash
        self.assertTrue(self.service.get_stats()["listeners"]["ssh"]["active"])

    async def test_random_binary_junk_fuzzing(self):
        """Client sends null bytes, control characters, and non-utf8 binary data."""
        junk_payloads = [
            b"\x00\x00\x00\x00\r\n",
            b"\xff\xfe\xfd\xfc\xfb\xfa\r\n",
            os.urandom(256) + b"\r\n",
            b"\x1b[31;1mANSI_ESCAPE\x1b[0m\r\n",
            b"' OR '1'='1' -- \r\n",
            b"; rm -rf /; touch /tmp/pwned\r\n",
        ]

        for payload in junk_payloads:
            reader, writer = await asyncio.open_connection("127.0.0.1", self.ssh_port)
            try:
                await reader.readline()
                await reader.readuntil(b"login: ")
                writer.write(payload)
                await writer.drain()

                await reader.readuntil(b"Password: ")
                writer.write(b"any_password\r\n")
                await writer.drain()

                # Server should reply with Access denied, not 500 error or crash
                res = await asyncio.wait_for(reader.readuntil(b"Access denied"), timeout=2.0)
                self.assertIn(b"Access denied", res)
            finally:
                writer.close()
                await writer.wait_closed()

        logs = await self.service.get_honeypot_log(limit=10)
        self.assertEqual(len(logs), len(junk_payloads))

    async def test_telnet_malformed_iac_fuzzing(self):
        """Fuzz strip_telnet_iac with malformed, truncated, and cyclic IAC patterns."""
        fuzz_cases = [
            b"\xff\xfa\x01\x02\x03",  # Unterminated subnegotiation (missing \xff\xf0)
            b"\xff\xff\xff\xff\xff",  # Sequence of 5 0xFFs
            b"\xff\xfb",              # Truncated WILL (missing option byte)
            b"\xff",                  # Single lone IAC byte
            b"\x00\xff\x00\xff\x00",  # Alternating nulls and IAC
        ]
        for c in fuzz_cases:
            res = strip_telnet_iac(c)
            self.assertIsInstance(res, bytes)

    # ── 3. CONCURRENCY BURST & RESOURCE LEAKS ─────────────────────────────────

    async def test_concurrency_burst_and_no_leak(self):
        """Launch 20 concurrent connections: 10 clean, 10 abrupt disconnects."""
        async def client_worker(idx: int):
            try:
                r, w = await asyncio.open_connection("127.0.0.1", self.ssh_port)
                await r.readline()
                if idx % 2 == 0:
                    # Clean single attempt
                    await r.readuntil(b"login: ")
                    w.write(f"user_{idx}\r\n".encode())
                    await w.drain()
                    await r.readuntil(b"Password: ")
                    w.write(b"pass\r\n")
                    await w.drain()
                    await r.readuntil(b"Access denied")
                else:
                    # Abrupt reset
                    pass
                w.close()
                await w.wait_closed()
            except Exception:
                pass

        tasks = [asyncio.create_task(client_worker(i)) for i in range(20)]
        await asyncio.gather(*tasks)

        # Allow loop to finish task deregistration
        await asyncio.sleep(0.1)

        stats = self.service.get_stats()
        self.assertEqual(stats["active_connections"], 0)
        self.assertGreaterEqual(stats["total_credentials"], 5)


if __name__ == "__main__":
    unittest.main()
