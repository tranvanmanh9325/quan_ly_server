"""
services/ai-agent-service/tests/test_honeypot_adversarial_m2.py
Adversarial Stress Testing & Empirical Verification Suite for Honeypot Service (Milestone 2 - Challenger 1).

Covers:
1. Fuzzing & Malformed Packets:
   - > 2048 bytes payload without newline (exceeding line limit).
   - Random binary fuzzing (os.urandom(4096)).
   - Null bytes and malformed UTF-8 byte streams.
   - Deep Telnet IAC sequences (RFC 854): WILL, WONT, DO, DONT, SB/SE, escaped IAC, malformed/unterminated sequences.
   - 10,000 random byte array fuzzing into strip_telnet_iac (0 crashes).
   - Verification that socket server never crashes and accepts subsequent connections.
2. Slowloris & DoS Limiter:
   - 60 concurrent connections against max_connections=50.
   - Verify semaphore rejects/drops 10 surplus connections immediately (< 1s).
   - Verify 50 held connections automatically timeout after 15.0s.
   - Verify active_connections returns to 0 and fresh connections succeed.
3. Brute Force Flow & Troll Payload:
   - 3 consecutive failed login attempts on Fake SSH -> Troll payload and immediate disconnect.
   - 3 consecutive failed login attempts on Fake Telnet -> Troll payload and immediate disconnect.
   - Verify prompt injection resilience (SQLi, XSS, ANSI escapes, UTF-8 unicode).
   - Early disconnect (1 or 2 attempts) clean teardown without unclosed resource warnings.
"""

from __future__ import annotations

import asyncio
import os
import random
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
    """Finds an available local TCP port dynamically."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestAdversarialFuzzingAndMalformedPackets(unittest.IsolatedAsyncioTestCase):
    """
    Challenge 1: Fuzzing & Malformed Packets
    - Large payloads > 2048 bytes
    - Random binary sequences
    - Complex and malformed Telnet IAC byte streams
    - Verify socket resilience (server remains up and responsive)
    """

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_fuzz.db")
        self.ssh_port = get_free_port()
        self.telnet_port = get_free_port()

        self.config = HoneypotConfig(
            bind_host="127.0.0.1",
            ssh_port=self.ssh_port,
            telnet_port=self.telnet_port,
            max_connections=50,
            socket_timeout=3.0,
            max_line_length=1024,
            auth_delay=0.01,
            db_path=self.db_path,
            use_postgres=False,
        )
        self.service = HoneypotService(config=self.config)
        await self.service.start()

    async def asyncTearDown(self):
        await self.service.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_telnet_iac_deep_fuzzing_and_corner_cases(self):
        """Fuzz strip_telnet_iac with complex, truncated, nested, and random IAC sequences."""
        # 1. Complex combination: DO ECHO + WILL SGA + NAWS + Terminal Type + literal text
        data = (
            b"\xff\xfd\x01"  # IAC DO ECHO
            b"\xff\xfb\x03"  # IAC WILL SGA
            b"\xff\xfa\x1f\x00\x50\x00\x18\xff\xf0"  # IAC SB NAWS 80x24 IAC SE
            b"\xff\xfa\x18\x00xterm-256color\xff\xf0"  # IAC SB TERM xterm-256color IAC SE
            b"root_admin\r\n"
        )
        self.assertEqual(strip_telnet_iac(data), b"root_admin\r\n")

        # 2. Escaped IAC combined with option commands
        escaped = b"pass\xff\xffword\xff\xfe\x01_test"
        self.assertEqual(strip_telnet_iac(escaped), b"pass\xffword_test")

        # 3. Malformed / unterminated subnegotiation
        unterminated_sb = b"user\xff\xfa\x18\x00no_se_marker"
        self.assertEqual(strip_telnet_iac(unterminated_sb), b"user")

        # 4. Truncated IAC at end of string
        self.assertEqual(strip_telnet_iac(b"foo\xff"), b"foo")
        self.assertEqual(strip_telnet_iac(b"bar\xff\xfb"), b"bar")

        # 5. Consecutive standalone 2-byte IAC commands
        # 0xF1 (NOP), 0xF2 (DM), 0xF3 (BRK), 0xF4 (IP), 0xF5 (AO), 0xF6 (AYT)
        consecutive_cmds = b"\xff\xf1\xff\xf2\xff\xf3\xff\xf4\xff\xf5\xff\xf6secure_user\r\n"
        self.assertEqual(strip_telnet_iac(consecutive_cmds), b"secure_user\r\n")

        # 6. High-volume randomized fuzzing (10,000 iterations): must never raise exception
        rng = random.Random(42)
        iac_bytes = [0xFF, 0xFB, 0xFC, 0xFD, 0xFE, 0xFA, 0xF0, 0xF1, 0xF6]
        ascii_bytes = list(range(32, 127))
        all_pool = iac_bytes * 5 + ascii_bytes

        for _ in range(10000):
            length = rng.randint(0, 128)
            random_sample = bytes(rng.choice(all_pool) for _ in range(length))
            try:
                result = strip_telnet_iac(random_sample)
                self.assertIsInstance(result, bytes)
            except Exception as ex:
                self.fail(f"strip_telnet_iac crashed on input {random_sample!r}: {ex}")

    async def test_ssh_fuzz_payload_over_2048_bytes(self):
        """Attacker sends 4096 bytes of continuous data without newline to SSH port."""
        reader, writer = await asyncio.open_connection("127.0.0.1", self.ssh_port)
        try:
            # Read banner
            banner = await asyncio.wait_for(reader.readline(), timeout=2.0)
            self.assertIn(b"SSH-2.0-OpenSSH", banner)

            # Wait for 'login: '
            await asyncio.wait_for(reader.readuntil(b"login: "), timeout=2.0)

            # Send 4096 bytes of 'A' without newline (exceeds max_line_length=1024)
            writer.write(b"A" * 4096)
            await writer.drain()

            # Server's readline() will hit the line limit (ValueError), catch it, and close connection
            data = await asyncio.wait_for(reader.read(100), timeout=2.0)
            self.assertEqual(data, b"")  # Connection closed by server
        finally:
            writer.close()
            await writer.wait_closed()

        # CRITICAL VERIFICATION: Server must remain healthy and responsive to new connections
        r2, w2 = await asyncio.open_connection("127.0.0.1", self.ssh_port)
        try:
            banner2 = await asyncio.wait_for(r2.readline(), timeout=2.0)
            self.assertIn(b"SSH-2.0-OpenSSH", banner2)
            await asyncio.wait_for(r2.readuntil(b"login: "), timeout=2.0)
        finally:
            w2.close()
            await w2.wait_closed()

    async def test_ssh_fuzz_random_binary_stream(self):
        """Attacker streams high-entropy binary data to SSH port (both without and with newlines)."""
        # Case A: 4096 bytes of binary data WITHOUT newlines (forces buffer overflow)
        reader, writer = await asyncio.open_connection("127.0.0.1", self.ssh_port)
        try:
            await asyncio.wait_for(reader.readline(), timeout=2.0)
            await asyncio.wait_for(reader.readuntil(b"login: "), timeout=2.0)

            # Strip any \n (0x0a) from binary stream
            binary_no_newline = bytes(b for b in os.urandom(4096) if b != 0x0A)
            writer.write(binary_no_newline)
            await writer.drain()

            # Server's readline() hits limit (ValueError), catches it, and closes connection cleanly
            data = await asyncio.wait_for(reader.read(100), timeout=2.0)
            self.assertEqual(data, b"")
        finally:
            writer.close()
            await writer.wait_closed()

        # Case B: Binary data WITH newlines and malformed UTF-8 bytes
        r2, w2 = await asyncio.open_connection("127.0.0.1", self.ssh_port)
        try:
            await asyncio.wait_for(r2.readline(), timeout=2.0)
            await asyncio.wait_for(r2.readuntil(b"login: "), timeout=2.0)

            # Malformed UTF-8 username followed by newline
            w2.write(b"\x00\xff\xfe\x80\x81\x82admin\r\n")
            await w2.drain()

            # Server decodes with errors='replace', does not crash, prompts for Password
            prompt = await asyncio.wait_for(r2.readuntil(b"Password: "), timeout=2.0)
            self.assertIn(b"Password: ", prompt)
        finally:
            w2.close()
            await w2.wait_closed()

        # Verify server remains healthy and active
        stats = self.service.get_stats()
        self.assertEqual(stats["status"], "running")
        self.assertTrue(stats["listeners"]["ssh"]["active"])

    async def test_telnet_fuzz_payload_over_2048_bytes(self):
        """Attacker sends 3000 bytes of continuous data without newline to Telnet port."""
        reader, writer = await asyncio.open_connection("127.0.0.1", self.telnet_port)
        try:
            await asyncio.wait_for(reader.readuntil(b"kirito-server login: "), timeout=2.0)

            # Flood 3000 bytes without newline
            writer.write(b"X" * 3000)
            await writer.drain()

            # Server must drop cleanly
            data = await asyncio.wait_for(reader.read(100), timeout=2.0)
            self.assertEqual(data, b"")
        finally:
            writer.close()
            await writer.wait_closed()

        # Verify Telnet server stays functional
        r2, w2 = await asyncio.open_connection("127.0.0.1", self.telnet_port)
        try:
            prompt = await asyncio.wait_for(r2.readuntil(b"kirito-server login: "), timeout=2.0)
            self.assertIn(b"kirito-server login: ", prompt)
        finally:
            w2.close()
            await w2.wait_closed()

    async def test_telnet_complex_iac_live_socket(self):
        """Send complex IAC sequence during real Telnet authentication handshake."""
        reader, writer = await asyncio.open_connection("127.0.0.1", self.telnet_port)
        try:
            await asyncio.wait_for(reader.readuntil(b"kirito-server login: "), timeout=2.0)

            # Username polluted with Telnet DO, DONT, WILL, WONT, and escaped IAC
            # \xff\xfd\x01 (DO ECHO), \xff\xfe\x03 (DONT SGA), \xff\xff (literal 0xFF)
            user_payload = b"\xff\xfd\x01\xff\xfe\x03root_\xff\xff_admin\r\n"
            writer.write(user_payload)
            await writer.drain()

            await asyncio.wait_for(reader.readuntil(b"Password: "), timeout=2.0)

            # Password with Subnegotiation
            pass_payload = b"\xff\xfa\x18\x00VT100\xff\xf0p@ssw0rd!\r\n"
            writer.write(pass_payload)
            await writer.drain()

            response = await asyncio.wait_for(reader.readuntil(b"Login incorrect\r\n\r\n"), timeout=2.0)
            self.assertIn(b"Login incorrect", response)
        finally:
            writer.close()
            await writer.wait_closed()

        # Verify parsed record in database
        logs = await self.service.get_honeypot_log(limit=5, service="telnet")
        self.assertGreaterEqual(len(logs), 1)
        latest = logs[0]
        # Username: IAC commands stripped -> b"root_\xff_admin"
        # Since 0xFF is non-UTF8 byte, errors="replace" yields Unicode replacement char \ufffd
        self.assertEqual(latest["username"], "root_\ufffd_admin")
        # Password: Subnegotiation IAC stripped -> "p@ssw0rd!"
        self.assertEqual(latest["password"], "p@ssw0rd!")


class TestAdversarialSlowlorisAndDoSProtection(unittest.IsolatedAsyncioTestCase):
    """
    Challenge 2: Slowloris & DoS Limiter
    - 60 concurrent connections against max_connections=50
    - Verify semaphore holds max 50 and immediately rejects remaining 10
    - Verify socket read timeout triggers after 15.0s (full production value)
    """

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_slowloris.db")
        self.ssh_port = get_free_port()
        self.telnet_port = get_free_port()

        # Set max_connections=50, socket_timeout=15.0 (exact production configuration)
        self.config = HoneypotConfig(
            bind_host="127.0.0.1",
            ssh_port=self.ssh_port,
            telnet_port=self.telnet_port,
            max_connections=50,
            socket_timeout=15.0,
            auth_delay=0.01,
            db_path=self.db_path,
            use_postgres=False,
        )
        self.service = HoneypotService(config=self.config)
        await self.service.start()

    async def asyncTearDown(self):
        await self.service.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_slowloris_60_connections_dos_limiter_and_15s_timeout(self):
        """
        Adversarial Test:
        1. Open 60 concurrent connections simultaneously.
        2. Verify exactly 50 connections are accepted and hold semaphore.
        3. Verify 10 surplus connections (conn 51..60) are rejected immediately (< 1s).
        4. Verify active_connections is capped at 50.
        5. Verify the 50 held connections sleep and automatically timeout after 15s.
        6. Verify all 50 connections are closed by server and semaphore is fully released.
        7. Verify connection #61 succeeds immediately afterwards.
        """
        all_writers = []
        accepted_readers = []
        rejected_count = 0
        accepted_count = 0

        # Launch 60 concurrent connection tasks
        async def connect_client(idx: int):
            nonlocal rejected_count, accepted_count
            r, w = await asyncio.open_connection("127.0.0.1", self.ssh_port)
            all_writers.append(w)
            try:
                # Read banner or EOF
                banner = await asyncio.wait_for(r.readline(), timeout=1.0)
                if not banner:
                    # Connection dropped immediately by semaphore
                    rejected_count += 1
                    return ("rejected", r, w)

                # Connection received banner, now read 'login: '
                prompt = await asyncio.wait_for(r.readuntil(b"login: "), timeout=1.0)
                accepted_count += 1
                accepted_readers.append((idx, r, w))
                return ("accepted", r, w)
            except (asyncio.IncompleteReadError, ConnectionResetError, asyncio.TimeoutError):
                rejected_count += 1
                return ("rejected", r, w)

        start_time = time.time()
        # Open 60 connections concurrently
        tasks = [connect_client(i) for i in range(60)]
        results = await asyncio.gather(*tasks)

        connect_duration = time.time() - start_time
        print(f"\n[Slowloris Test] 60 connections attempted in {connect_duration:.2f}s:")
        print(f"  Accepted: {accepted_count}, Rejected immediately: {rejected_count}")

        # VERIFICATION STEP 1: Semaphore capping
        self.assertEqual(accepted_count, 50, f"Expected exactly 50 accepted connections, got {accepted_count}")
        self.assertEqual(rejected_count, 10, f"Expected exactly 10 surplus rejected connections, got {rejected_count}")

        # Check internal stats
        stats = self.service.get_stats()
        self.assertEqual(stats["active_connections"], 50)

        # VERIFICATION STEP 2: 15-second Slowloris timeout
        # Now the 50 accepted connections sit idle and wait for the 15.0s server timeout
        print("[Slowloris Test] Waiting for 15.0s server read timeout on 50 held connections...")
        wait_start = time.time()

        async def wait_for_timeout(idx, r, w):
            # Attempt to read until server closes connection
            try:
                data = await asyncio.wait_for(r.read(100), timeout=18.0)
                return (idx, data)
            except Exception as ex:
                return (idx, ex)

        timeout_tasks = [wait_for_timeout(idx, r, w) for idx, r, w in accepted_readers]
        timeout_results = await asyncio.gather(*timeout_tasks)
        elapsed_timeout = time.time() - wait_start

        print(f"[Slowloris Test] All 50 connections closed in {elapsed_timeout:.2f}s")

        # Must have taken >= 14.5s and <= 17.0s
        self.assertGreaterEqual(
            elapsed_timeout, 14.5,
            f"Timeout occurred too early ({elapsed_timeout:.2f}s < 14.5s)"
        )
        self.assertLessEqual(
            elapsed_timeout, 17.5,
            f"Timeout took too long ({elapsed_timeout:.2f}s > 17.5s)"
        )

        # All 50 readers must have received EOF (b"")
        for idx, res in timeout_results:
            self.assertEqual(res, b"", f"Connection {idx} did not receive clean EOF on timeout")

        # Clean up test client writers
        for w in all_writers:
            try:
                w.close()
                await w.wait_closed()
            except Exception:
                pass

        # Give event loop a brief moment to process final cleanups
        await asyncio.sleep(0.1)

        # VERIFICATION STEP 3: Semaphore is fully recovered and fresh client succeeds
        post_stats = self.service.get_stats()
        self.assertEqual(post_stats["active_connections"], 0)

        # Connection #61 succeeds immediately
        r_fresh, w_fresh = await asyncio.open_connection("127.0.0.1", self.ssh_port)
        try:
            fresh_banner = await asyncio.wait_for(r_fresh.readline(), timeout=2.0)
            self.assertIn(b"SSH-2.0-OpenSSH", fresh_banner)
            fresh_prompt = await asyncio.wait_for(r_fresh.readuntil(b"login: "), timeout=2.0)
            self.assertIn(b"login: ", fresh_prompt)
        finally:
            w_fresh.close()
            await w_fresh.wait_closed()


class TestAdversarialBruteForceFlowAndTrollPayload(unittest.IsolatedAsyncioTestCase):
    """
    Challenge 3: Brute Force Flow & Troll Payload Rejection
    - 3 consecutive failed login attempts on Fake SSH & Telnet
    - Verification of troll message: '💀 Kẻ thất bại...'
    - Immediate socket closure by server
    - Harvest callbacks & IP block hooks
    - Prompt injection & unicode resilience
    """

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_brute.db")
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
            max_connections=50,
            socket_timeout=5.0,
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

    async def test_ssh_brute_force_flow_and_troll_payload(self):
        """Attacker performs 3 consecutive failed logins on SSH port."""
        reader, writer = await asyncio.open_connection("127.0.0.1", self.ssh_port)
        try:
            # Banner
            banner = await asyncio.wait_for(reader.readline(), timeout=2.0)
            self.assertIn(b"SSH-2.0-OpenSSH", banner)

            # Attempt 1: SQL Injection attempt
            await asyncio.wait_for(reader.readuntil(b"login: "), timeout=2.0)
            writer.write(b"admin' OR '1'='1\r\n")
            await writer.drain()

            await asyncio.wait_for(reader.readuntil(b"Password: "), timeout=2.0)
            writer.write(b"'; DROP TABLE users; --\r\n")
            await writer.drain()

            denied1 = await asyncio.wait_for(reader.readuntil(b"Access denied\r\n\r\n"), timeout=2.0)
            self.assertIn(b"Access denied", denied1)

            # Attempt 2: XSS & Path Traversal attempt
            await asyncio.wait_for(reader.readuntil(b"login: "), timeout=2.0)
            writer.write(b"<script>alert(1)</script>\r\n")
            await writer.drain()

            await asyncio.wait_for(reader.readuntil(b"Password: "), timeout=2.0)
            writer.write(b"../../../../etc/shadow\r\n")
            await writer.drain()

            denied2 = await asyncio.wait_for(reader.readuntil(b"Access denied\r\n\r\n"), timeout=2.0)
            self.assertIn(b"Access denied", denied2)

            # Attempt 3: Unicode & UTF-8 Vietnamese chars
            await asyncio.wait_for(reader.readuntil(b"login: "), timeout=2.0)
            writer.write("tiểu_bảo_bảo\r\n".encode("utf-8"))
            await writer.drain()

            await asyncio.wait_for(reader.readuntil(b"Password: "), timeout=2.0)
            writer.write("mật_khẩu_bí_mật\r\n".encode("utf-8"))
            await writer.drain()

            # Attempt 3 response: MUST BE TROLL PAYLOAD
            response = await asyncio.wait_for(reader.read(1024), timeout=2.0)
            expected_troll = "💀 Kẻ thất bại. Lần sau cố gắng hơn nhé! - Tiểu Bảo Bảo Security Team 😂".encode("utf-8")
            self.assertIn(expected_troll, response)

            # MUST BE DISCONNECTED IMMEDIATELY (EOF)
            eof = await asyncio.wait_for(reader.read(100), timeout=1.0)
            self.assertEqual(eof, b"")

        finally:
            writer.close()
            await writer.wait_closed()

        # VERIFY HARVEST & BLOCK
        self.assertEqual(len(self.harvested_events), 1)
        event = self.harvested_events[0]
        self.assertEqual(event["service"], "ssh")
        self.assertEqual(event["attempts"], 3)
        self.assertEqual(len(event["credentials"]), 3)
        self.assertEqual(event["credentials"][0], ("admin' OR '1'='1", "'; DROP TABLE users; --"))
        self.assertEqual(event["credentials"][1], ("<script>alert(1)</script>", "../../../../etc/shadow"))
        self.assertEqual(event["credentials"][2], ("tiểu_bảo_bảo", "mật_khẩu_bí_mật"))

        # Auto-block IP callback triggered
        self.assertEqual(len(self.blocked_events), 1)
        self.assertEqual(self.blocked_events[0][0], "127.0.0.1")
        self.assertIn("Honeypot trap: 3 failed attempts on Fake SSH", self.blocked_events[0][1])

    async def test_telnet_brute_force_flow_and_troll_payload(self):
        """Attacker performs 3 consecutive failed logins on Telnet port."""
        reader, writer = await asyncio.open_connection("127.0.0.1", self.telnet_port)
        try:
            # Banner
            await asyncio.wait_for(reader.readuntil(b"kirito-server login: "), timeout=2.0)

            # Attempt 1
            writer.write(b"admin\r\n")
            await writer.drain()
            await asyncio.wait_for(reader.readuntil(b"Password: "), timeout=2.0)
            writer.write(b"admin123\r\n")
            await writer.drain()
            denied1 = await asyncio.wait_for(reader.readuntil(b"Login incorrect\r\n\r\n"), timeout=2.0)
            self.assertIn(b"Login incorrect", denied1)

            # Attempt 2
            await asyncio.wait_for(reader.readuntil(b"kirito-server login: "), timeout=2.0)
            writer.write(b"cisco\r\n")
            await writer.drain()
            await asyncio.wait_for(reader.readuntil(b"Password: "), timeout=2.0)
            writer.write(b"cisco\r\n")
            await writer.drain()
            denied2 = await asyncio.wait_for(reader.readuntil(b"Login incorrect\r\n\r\n"), timeout=2.0)
            self.assertIn(b"Login incorrect", denied2)

            # Attempt 3
            await asyncio.wait_for(reader.readuntil(b"kirito-server login: "), timeout=2.0)
            writer.write(b"root\r\n")
            await writer.drain()
            await asyncio.wait_for(reader.readuntil(b"Password: "), timeout=2.0)
            writer.write(b"toor\r\n")
            await writer.drain()

            # Attempt 3 response: TROLL PAYLOAD
            response = await asyncio.wait_for(reader.read(1024), timeout=2.0)
            expected_troll = "💀 Kẻ thất bại. Lần sau cố gắng hơn nhé! - Tiểu Bảo Bảo Security Team 😂".encode("utf-8")
            self.assertIn(expected_troll, response)

            # Immediate disconnect
            eof = await asyncio.wait_for(reader.read(100), timeout=1.0)
            self.assertEqual(eof, b"")

        finally:
            writer.close()
            await writer.wait_closed()

        # VERIFY HARVEST & BLOCK
        self.assertEqual(len(self.harvested_events), 1)
        self.assertEqual(self.harvested_events[0]["service"], "telnet")
        self.assertEqual(len(self.blocked_events), 1)
        self.assertIn("Honeypot trap: 3 failed attempts on Fake TELNET", self.blocked_events[0][1])

    async def test_early_disconnect_resilience(self):
        """Attacker disconnects after only 1 attempt. Server cleans up without block or warning."""
        reader, writer = await asyncio.open_connection("127.0.0.1", self.ssh_port)
        try:
            await asyncio.wait_for(reader.readline(), timeout=2.0)
            await asyncio.wait_for(reader.readuntil(b"login: "), timeout=2.0)
            writer.write(b"single_attempt_user\r\n")
            await writer.drain()

            await asyncio.wait_for(reader.readuntil(b"Password: "), timeout=2.0)
            writer.write(b"pwd\r\n")
            await writer.drain()

            await asyncio.wait_for(reader.readuntil(b"Access denied\r\n\r\n"), timeout=2.0)
            # Abruptly close writer from client side
        finally:
            writer.close()
            await writer.wait_closed()

        # Give server time to finish cleanup
        await asyncio.sleep(0.1)

        # 1 attempt harvested
        self.assertEqual(len(self.harvested_events), 1)
        self.assertEqual(self.harvested_events[0]["attempts"], 1)

        # Block should NOT be triggered for only 1 attempt
        self.assertEqual(len(self.blocked_events), 0)

        # Active connections must be 0
        stats = self.service.get_stats()
        self.assertEqual(stats["active_connections"], 0)


if __name__ == "__main__":
    unittest.main()
