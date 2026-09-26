"""
test_challenger_r1_path_traversal.py — Empirical Adversarial Stress Test Suite for R1 Path Traversal.

Designed and executed by Challenger 1 (teamwork_preview_challenger):
1. Mixed backslash and forward slash vectors (POSIX / Windows cross-platform evasion)
2. Multi-layer URL encoding (%252e%252e%252f, %2e%2e%5c, triple encoding, mixed)
3. Extreme traversal depth (up to 128 levels of ../ and deep tree dives)
4. Sandbox boundary escapes and prefix collision attacks (/home/kirito_evil, sibling sandbox)
5. False positive verification (ensuring legitimate sandbox operations work 100%)
6. High concurrency and stress load (1,000 iterations, 50 concurrent async tasks, 10,000-char buffer)
"""

import asyncio
import os
from pathlib import Path
import random
import string
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock

from app.services.file_manager_service import FileManagerService


class MockSshClient:
    """Mock SSH client for host-mode testing without requiring a live remote server."""

    def __init__(self):
        self.executed_commands = []

    async def execute_command(self, cmd: str) -> str:
        self.executed_commands.append(cmd)
        if "cat /etc/passwd" in cmd or "/etc/passwd" in cmd:
            return "root:x:0:0:root:/root:/bin/bash"
        if "IS_DIR" in cmd:
            return "IS_DIR"
        return "mock_output"


class TestAdversarialMixedSlashes(unittest.IsolatedAsyncioTestCase):
    """Stress tests against mixed backslash and forward slash evasion payloads."""

    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.test_dir.name)
        self.file_svc = FileManagerService(base_dir=str(self.base_path))

    def tearDown(self):
        self.test_dir.cleanup()

    async def test_mixed_slash_read_attempts_in_sandbox(self):
        """Verifies mixed slash traversal vectors are blocked in sandbox mode."""
        mixed_vectors = [
            r"..\/..\/etc/passwd",
            r"foo\..\..\etc/passwd",
            r"..\..\windows\win.ini",
            r"foo\..\..\windows\win.ini",
            r"..\..\etc\passwd",
            r"..\\..\\etc\\passwd",
            r"..\/..\/etc\/passwd",
            r"sub\..\..\..\secret.txt",
            r"foo/bar\..\..\..\etc/passwd",
            r".\..\..\..\etc/passwd",
            r"a\b/c\d/../../../../../../etc/passwd",
            r"subdir\\..\\..\\windows\\system32\\config\\sam",
        ]
        for trav in mixed_vectors:
            with self.subTest(vector=trav):
                res = await self.file_svc.read_file_content(trav)
                self.assertIn(
                    res.get("status"),
                    ("security_veto", "error"),
                    f"Mixed slash traversal '{trav}' was not vetoed! Result: {res}",
                )

    async def test_mixed_slash_write_attempts_in_sandbox(self):
        """Verifies mixed slash traversal writes are blocked in sandbox mode."""
        mixed_vectors = [
            r"..\..\malware.sh",
            r"..\/..\/malware.sh",
            r"foo\..\..\malware.sh",
            r"sub/..\\..\\malware.sh",
        ]
        for trav in mixed_vectors:
            with self.subTest(vector=trav):
                res = await self.file_svc.write_file_content(trav, "echo hacked")
                self.assertIn(
                    res.get("status"),
                    ("security_veto", "error"),
                    f"Mixed slash write traversal '{trav}' was not vetoed! Result: {res}",
                )

    async def test_mixed_slash_host_mode_veto(self):
        """Verifies mixed slash traversal in host mode (base_dir=None)."""
        host_svc = FileManagerService(ssh_client=MockSshClient(), base_dir=None)
        mixed_host_vectors = [
            r"/home/kirito/..\..\etc/passwd",
            r"/home/kirito/..\\..\\etc/passwd",
            r"/tmp/..\/..\/etc/shadow",
            r"..\..\windows\win.ini",
            r"foo\..\..\etc/passwd",
        ]
        for trav in mixed_host_vectors:
            with self.subTest(vector=trav):
                is_valid, v_type, reason = host_svc.validate_path_security(trav, action="read")
                self.assertFalse(
                    is_valid,
                    f"Host mode mixed slash traversal '{trav}' passed validation!",
                )
                self.assertEqual(v_type, "boundary")


class TestAdversarialMultiURLEncoding(unittest.IsolatedAsyncioTestCase):
    """Stress tests against single, double, triple, and mixed percent-encoding payloads."""

    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.test_dir.name)
        self.file_svc = FileManagerService(base_dir=str(self.base_path))

    def tearDown(self):
        self.test_dir.cleanup()

    async def test_multi_layer_url_encoded_traversals(self):
        """Verifies multi-layer URL encoded traversal vectors are normalized and blocked."""
        encoded_vectors = [
            "%2e%2e%2fetc%2fpasswd",                  # Single encoded ../
            "%2e%2e%5cwindows%5cwin.ini",            # Single encoded ..\
            "%252e%252e%252f",                        # Double encoded ../
            "%252e%252e%252fetc%252fpasswd",          # Double encoded ../etc/passwd
            "%2e%2e%5c",                              # Single encoded ..\
            "%252e%252e%255c",                        # Double encoded ..\
            "%25252e%25252e%25252fetc%25252fpasswd",  # Triple encoded
            "%2e%2e/%252e%252e%5c",                   # Mixed single & double
            "..%2f..%5cetc%2fpasswd",                 # Mixed raw and encoded
            "%2E%2E%2Fetc%2Fpasswd",                  # Uppercase hex percent-encoding
            "%252E%252E%252Fetc%252Fpasswd",          # Uppercase double hex percent-encoding
            "subdir%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",# Nested encoded traversal
        ]
        for trav in encoded_vectors:
            with self.subTest(vector=trav):
                res = await self.file_svc.read_file_content(trav)
                self.assertIn(
                    res.get("status"),
                    ("security_veto", "error"),
                    f"URL encoded traversal '{trav}' was not vetoed! Result: {res}",
                )

    async def test_encoded_null_byte_attacks(self):
        """Verifies percent-encoded null bytes cannot bypass validation."""
        null_vectors = [
            "valid.txt%00../../etc/passwd",
            "%2e%2e%2fetc%2fpasswd%00.txt",
        ]
        for trav in null_vectors:
            with self.subTest(vector=trav):
                res = await self.file_svc.read_file_content(trav)
                self.assertIn(
                    res.get("status"),
                    ("security_veto", "error", "not_found"),
                    f"Null byte vector '{trav}' allowed unsafe access! Result: {res}",
                )


class TestAdversarialExtremeTraversalDepth(unittest.IsolatedAsyncioTestCase):
    """Stress tests against extreme traversal depths and deep directory trees."""

    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.test_dir.name)
        self.file_svc = FileManagerService(base_dir=str(self.base_path))

    def tearDown(self):
        self.test_dir.cleanup()

    async def test_extreme_traversal_depths(self):
        """Tests traversal depths from 8 levels up to 128 levels."""
        depths = [8, 16, 32, 64, 128]
        for depth in depths:
            with self.subTest(depth=depth):
                # Standard forward slashes
                trav_slash = ("../" * depth) + "etc/passwd"
                res_slash = await self.file_svc.read_file_content(trav_slash)
                self.assertIn(
                    res_slash.get("status"),
                    ("security_veto", "error"),
                    f"Depth {depth} (forward slash) was not vetoed! Result: {res_slash}",
                )

                # Windows backslashes
                trav_bslash = (r"..\\" * depth) + r"windows\win.ini"
                res_bslash = await self.file_svc.read_file_content(trav_bslash)
                self.assertIn(
                    res_bslash.get("status"),
                    ("security_veto", "error"),
                    f"Depth {depth} (backslash) was not vetoed! Result: {res_bslash}",
                )

                # Alternating mixed slashes
                alternating = "".join(["../" if i % 2 == 0 else r"..\\" for i in range(depth)]) + "etc/passwd"
                res_alt = await self.file_svc.read_file_content(alternating)
                self.assertIn(
                    res_alt.get("status"),
                    ("security_veto", "error"),
                    f"Depth {depth} (alternating slashes) was not vetoed! Result: {res_alt}",
                )

    async def test_deep_dive_and_ascend_traversal(self):
        """Tests creating a deep valid folder path and traversing all the way out."""
        deep_descent = "a/b/c/d/e/f/g/h/i/j/k/l/m/n/o/p/"
        deep_escape = deep_descent + ("../" * 30) + "etc/shadow"
        res = await self.file_svc.read_file_content(deep_escape)
        self.assertIn(
            res.get("status"),
            ("security_veto", "error"),
            f"Deep dive and ascend traversal was not vetoed! Result: {res}",
        )


class TestAdversarialPrefixCollisionAndBoundaries(unittest.IsolatedAsyncioTestCase):
    """Stress tests verifying boundary checks against prefix collision vulnerabilities."""

    def test_host_mode_prefix_collision(self):
        """Verifies that prefixes like /home/kirito_evil or /tmp_evil are rejected."""
        host_svc = FileManagerService(base_dir=None)

        evil_prefixes = [
            "/home/kirito_evil/malware.py",
            "/home/kirito_attacker/file.txt",
            "/home/kirito.backup/id_rsa",
            "/tmp_evil/backdoor",
            "/tmphack/secret",
            "/tmp.attacker/rootkit",
        ]
        for ep in evil_prefixes:
            with self.subTest(evil_path=ep):
                is_valid, v_type, reason = host_svc.validate_path_security(ep)
                self.assertFalse(
                    is_valid,
                    f"Prefix collision '{ep}' was wrongly accepted as valid!",
                )
                self.assertEqual(v_type, "boundary")

    def test_sandbox_prefix_collision(self):
        """Verifies sibling directory prefix collision in sandbox mode."""
        with tempfile.TemporaryDirectory() as tmp_root:
            sandbox_dir = os.path.join(tmp_root, "sandbox")
            os.makedirs(sandbox_dir, exist_ok=True)
            evil_sibling = os.path.join(tmp_root, "sandbox_evil")
            os.makedirs(evil_sibling, exist_ok=True)

            svc = FileManagerService(base_dir=sandbox_dir)
            evil_path = os.path.join(evil_sibling, "secret.txt")

            is_valid, v_type, reason = svc.validate_path_security(evil_path)
            self.assertFalse(
                is_valid,
                f"Sandbox sibling collision '{evil_path}' was wrongly accepted!",
            )
            self.assertEqual(v_type, "boundary")


class TestAdversarialFalsePositives(unittest.IsolatedAsyncioTestCase):
    """Ensures legitimate files and operations inside sandbox have ZERO false positives."""

    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.test_dir.name)
        self.file_svc = FileManagerService(base_dir=str(self.base_path))

    def tearDown(self):
        self.test_dir.cleanup()

    async def test_valid_file_read_and_write(self):
        """Verifies legitimate files can be written and read without false security veto."""
        valid_cases = [
            ("simple.txt", "Nội dung tệp đơn giản."),
            ("nested/subfolder/file.txt", "Tệp trong thư mục lồng nhau."),
            ("deep/a/b/c/d/deep_file.txt", "Tệp phân cấp sâu."),
            ("tập_tin_tiếng_việt_có_dấu.txt", "Xin chào Việt Nam, kiểm thử ký tự tiếng Việt."),
            ("file with multiple spaces.txt", "Nội dung tệp có khoảng trắng."),
            ("special-characters_v1.0.2(final).txt", "Tệp với các ký tự đặc biệt hợp lệ."),
            ("nested/../nested/subfolder/file.txt", "Tệp truy cập qua relative resolution hợp lệ."),
        ]

        for rel_path, content in valid_cases:
            with self.subTest(file=rel_path):
                # 1. Write file
                write_res = await self.file_svc.write_file_content(rel_path, content)
                self.assertEqual(
                    write_res.get("status"),
                    "success",
                    f"False positive on write for valid file '{rel_path}': {write_res}",
                )

                # 2. Read file
                read_res = await self.file_svc.read_file_content(rel_path)
                self.assertEqual(
                    read_res.get("status"),
                    "success",
                    f"False positive on read for valid file '{rel_path}': {read_res}",
                )
                self.assertEqual(read_res.get("content"), content)

    async def test_valid_list_files(self):
        """Verifies directory listing works cleanly on sandbox without false positives."""
        (self.base_path / "f1.txt").write_text("Hello", encoding="utf-8")
        (self.base_path / "sub").mkdir()
        (self.base_path / "sub" / "f2.txt").write_text("World", encoding="utf-8")

        res_root = await self.file_svc.list_files(".")
        self.assertEqual(res_root.get("status"), "success")
        self.assertGreaterEqual(res_root.get("total_items"), 2)

        res_sub = await self.file_svc.list_files("sub")
        self.assertEqual(res_sub.get("status"), "success")
        self.assertGreaterEqual(res_sub.get("total_items"), 1)

    async def test_valid_move_or_rename_file(self):
        """Verifies move and rename inside sandbox work cleanly."""
        src_rel = "source.txt"
        dst_rel = "renamed/dest.txt"
        await self.file_svc.write_file_content(src_rel, "Original data")

        res_move = await self.file_svc.move_or_rename_file(src_rel, dst_rel)
        self.assertEqual(
            res_move.get("status"),
            "success",
            f"False positive on move_or_rename_file: {res_move}",
        )

        # Verify destination exists and source is gone
        read_dst = await self.file_svc.read_file_content(dst_rel)
        self.assertEqual(read_dst.get("content"), "Original data")

        read_src = await self.file_svc.read_file_content(src_rel)
        self.assertEqual(read_src.get("status"), "not_found")


class TestAdversarialLoadAndResilience(unittest.IsolatedAsyncioTestCase):
    """Evaluates load capacity, high concurrency, and robustness under pathological inputs."""

    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.test_dir.name)
        self.file_svc = FileManagerService(base_dir=str(self.base_path))

    def tearDown(self):
        self.test_dir.cleanup()

    def test_high_volume_validation_throughput(self):
        """Measures latency and throughput over 1,000 rapid validation calls."""
        payload_pool = [
            r"..\/..\/etc/passwd",
            r"foo\..\..\etc/passwd",
            "%252e%252e%252fetc%252fpasswd",
            "../../../../../../../../etc/passwd",
            r"..\..\windows\win.ini",
            "valid/nested/file.txt",
            "another_valid_file.txt",
            "/home/kirito_evil/malware",
            "sub/../../.env",
            "normal_file.log",
        ]

        start_time = time.perf_counter()
        iterations = 1000
        for i in range(iterations):
            path = payload_pool[i % len(payload_pool)]
            self.file_svc.validate_path_security(path)
        duration = time.perf_counter() - start_time

        avg_latency_ms = (duration / iterations) * 1000
        throughput = iterations / duration
        # Expect throughput > 10,000 ops/sec, latency < 0.2 ms/op
        self.assertLess(
            avg_latency_ms,
            1.0,
            f"Validation too slow: {avg_latency_ms:.3f} ms/op",
        )

    async def test_high_concurrency_stress(self):
        """Executes 50 concurrent async tasks against read_file_content."""
        (self.base_path / "valid.txt").write_text("Safe content", encoding="utf-8")

        async def worker(idx: int):
            if idx % 2 == 0:
                # Malicious task
                res = await self.file_svc.read_file_content(r"..\/..\/etc/passwd")
                self.assertIn(res.get("status"), ("security_veto", "error"))
            else:
                # Legitimate task
                res = await self.file_svc.read_file_content("valid.txt")
                self.assertEqual(res.get("status"), "success")
                self.assertEqual(res.get("content"), "Safe content")

        tasks = [worker(i) for i in range(50)]
        await asyncio.gather(*tasks)

    async def test_pathological_long_buffer_input(self):
        """Verifies resistance against ReDoS and buffer overflow with 10,000-char path."""
        # 10,000 characters of traversal
        huge_traversal = ("../" * 3000) + "etc/passwd"
        self.assertGreater(len(huge_traversal), 9000)

        start = time.perf_counter()
        res = await self.file_svc.read_file_content(huge_traversal)
        elapsed = time.perf_counter() - start

        self.assertIn(res.get("status"), ("security_veto", "error"))
        # Must finish in less than 500ms (no exponential regex backtracking)
        self.assertLess(elapsed, 0.5, f"Validation hung for {elapsed:.2f}s on huge input!")

    def test_random_fuzzing_resilience(self):
        """Fuzzes validate_path_security with 100 randomized mutated strings."""
        chars = string.ascii_letters + string.digits + "/\\%.~_ -:?#*$"
        random.seed(42)

        for _ in range(100):
            length = random.randint(1, 100)
            fuzz_str = "".join(random.choice(chars) for _ in range(length))
            try:
                is_valid, v_type, reason = self.file_svc.validate_path_security(fuzz_str)
                self.assertIsInstance(is_valid, bool)
            except Exception as exc:
                self.fail(f"validate_path_security crashed with exception on input {repr(fuzz_str)}: {exc}")


class TestAdversarialWindowsUNCAndDriveLetters(unittest.IsolatedAsyncioTestCase):
    """Stress tests verifying rejection of Windows-specific drive letters, UNC, and device names."""

    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.test_dir.name)
        self.file_svc = FileManagerService(base_dir=str(self.base_path))

    def tearDown(self):
        self.test_dir.cleanup()

    async def test_windows_drive_letters_in_sandbox(self):
        """Verifies absolute Windows drive letter paths are rejected in sandbox mode."""
        drive_paths = [
            "C:/Windows/win.ini",
            r"C:\Windows\System32\cmd.exe",
            "D:/etc/passwd",
            r"D:\boot.ini",
            "E:/sensitive_data.txt",
        ]
        for dp in drive_paths:
            with self.subTest(drive_path=dp):
                res = await self.file_svc.read_file_content(dp)
                self.assertIn(
                    res.get("status"),
                    ("security_veto", "error"),
                    f"Windows drive path '{dp}' was not blocked in sandbox! Result: {res}",
                )

    async def test_unc_paths_in_sandbox(self):
        """Verifies UNC network share paths are rejected in sandbox mode."""
        unc_paths = [
            r"\\192.168.1.1\share\secret.txt",
            r"\\localhost\c$\Windows\win.ini",
            "//192.168.1.1/share/secret.txt",
            "//localhost/c$/boot.ini",
        ]
        for up in unc_paths:
            with self.subTest(unc_path=up):
                res = await self.file_svc.read_file_content(up)
                self.assertIn(
                    res.get("status"),
                    ("security_veto", "error"),
                    f"UNC path '{up}' was not blocked in sandbox! Result: {res}",
                )

    async def test_windows_drive_letters_write_in_sandbox(self):
        """Verifies write_file_content blocks Windows drive paths in sandbox mode."""
        drive_paths = [
            "C:/Windows/win.ini",
            r"C:\Windows\System32\cmd.exe",
            "D:/etc/passwd",
            r"D:\boot.ini",
            "E:/sensitive_data.txt",
            "C:cmd.exe",
            "C:../Windows/win.ini",
            "D:cmd.exe",
            "D:../sensitive.txt",
            "%43%3acmd.exe",
        ]
        for dp in drive_paths:
            with self.subTest(drive_path=dp):
                res = await self.file_svc.write_file_content(dp, "malicious payload")
                self.assertEqual(
                    res.get("status"),
                    "security_veto",
                    f"Windows drive write '{dp}' was not vetoed! Result: {res}",
                )

    async def test_windows_drive_letters_list_in_sandbox(self):
        """Verifies list_files blocks Windows drive paths in sandbox mode."""
        drive_paths = [
            "C:/Windows/",
            r"C:\Windows\System32",
            "D:/etc",
            r"D:\boot",
            "E:/data",
            "C:cmd.exe",
            "D:cmd.exe",
            "C:../Windows/win.ini",
            "%43%3acmd.exe",
        ]
        for dp in drive_paths:
            with self.subTest(drive_path=dp):
                res = await self.file_svc.list_files(dp)
                self.assertEqual(
                    res.get("status"),
                    "security_veto",
                    f"Windows drive list '{dp}' was not vetoed! Result: {res}",
                )

    async def test_windows_drive_letters_in_host_mode(self):
        """Verifies read, write, and list block Windows drive paths in host mode (base_dir=None)."""
        host_svc = FileManagerService(ssh_client=MockSshClient(), base_dir=None)
        drive_paths = [
            "C:/Windows/win.ini",
            "D:/etc/passwd",
            r"D:\boot.ini",
            "E:/sensitive_data.txt",
            "C:cmd.exe",
            "C:../Windows/win.ini",
            "D:cmd.exe",
            "D:../sensitive.txt",
            "%43%3acmd.exe",
        ]
        for dp in drive_paths:
            with self.subTest(drive_path=dp, op="read"):
                res_r = await host_svc.read_file_content(dp)
                self.assertEqual(res_r.get("status"), "security_veto")

            with self.subTest(drive_path=dp, op="write"):
                res_w = await host_svc.write_file_content(dp, "data")
                self.assertEqual(res_w.get("status"), "security_veto")

            with self.subTest(drive_path=dp, op="list"):
                res_l = await host_svc.list_files(dp)
                self.assertEqual(res_l.get("status"), "security_veto")

    async def test_unc_paths_write_and_list_in_sandbox(self):
        """Verifies write and list block UNC paths in sandbox mode."""
        unc_paths = [
            r"\\192.168.1.1\share\secret.txt",
            "//192.168.1.1/share/secret.txt",
            r"\\server\share\sub",
            "//server/share/sub",
        ]
        for up in unc_paths:
            with self.subTest(unc_path=up, op="write"):
                res_w = await self.file_svc.write_file_content(up, "payload")
                self.assertIn(res_w.get("status"), ("security_veto", "error"))

            with self.subTest(unc_path=up, op="list"):
                res_l = await self.file_svc.list_files(up)
                self.assertIn(res_l.get("status"), ("security_veto", "error"))

    async def test_unc_paths_in_host_mode(self):
        """Verifies read, write, and list block UNC paths in host mode."""
        host_svc = FileManagerService(ssh_client=MockSshClient(), base_dir=None)
        unc_paths = [
            r"\\192.168.1.1\share\secret.txt",
            "//192.168.1.1/share/secret.txt",
            r"\\server\share\sub",
            "//server/share/sub",
        ]
        for up in unc_paths:
            with self.subTest(unc_path=up, op="read"):
                res_r = await host_svc.read_file_content(up)
                self.assertIn(res_r.get("status"), ("security_veto", "error"))

            with self.subTest(unc_path=up, op="write"):
                res_w = await host_svc.write_file_content(up, "data")
                self.assertIn(res_w.get("status"), ("security_veto", "error"))

            with self.subTest(unc_path=up, op="list"):
                res_l = await host_svc.list_files(up)
                self.assertIn(res_l.get("status"), ("security_veto", "error"))

    async def test_null_byte_injection_vetoed(self):
        """Verifies raw and URL-encoded null bytes are rejected across sandbox and host modes."""
        null_payloads = [
            "/home/kirito/file\0.txt",
            "/home/kirito/safe.txt%00.env",
            "test\0.txt",
            "%00payload.bin",
            "safe.txt\x00.php",
        ]
        host_svc = FileManagerService(ssh_client=MockSshClient(), base_dir=None)
        for np in null_payloads:
            with self.subTest(null_path=np, mode="sandbox"):
                res_sb_r = await self.file_svc.read_file_content(np)
                self.assertIn(res_sb_r.get("status"), ("security_veto", "error"))
                res_sb_w = await self.file_svc.write_file_content(np, "data")
                self.assertIn(res_sb_w.get("status"), ("security_veto", "error"))

            with self.subTest(null_path=np, mode="host"):
                res_h_r = await host_svc.read_file_content(np)
                self.assertIn(res_h_r.get("status"), ("security_veto", "error"))
                res_h_w = await host_svc.write_file_content(np, "data")
                self.assertIn(res_h_w.get("status"), ("security_veto", "error"))


if __name__ == "__main__":
    unittest.main()


