"""
test_challenger_m2_adversarial.py — Empirical Adversarial & Stress Test Suite for Milestone 2.

Author: Challenger 1 (teamwork_preview_challenger_m2_1)
Mission: Stress-test UniversalDownloader, WebArticleExtractor, and SystemMasteryService
under hostile and edge-case conditions to empirically prove correctness and safety.

Categories Tested:
1. UniversalDownloader:
   - Chunked streaming of >100MB synthetic file (128MB) with < 5MB RAM overhead.
   - Sudden connection disruption without resume support -> Zero-Disk Leak (.part unlinked).
   - Sudden connection disruption with resume support -> Range header emitted, .part appended,
     and final file integrity perfectly preserved.
   - Path traversal and malicious filenames sanitization.
2. WebArticleExtractor:
   - Extreme adversarial HTML: 100 deeply nested <script> tags.
   - 2MB+ toxic CSS and 500+ ad/tracking noise containers.
   - Memory footprint verification via tracemalloc (< 5MB RAM during heavy parse).
   - Semantic Markdown preservation and zero script/style leakage.
3. Hardware Destructive Veto:
   - Spinal Hardware Safety Veto against mkfs, dd zero /dev/sda, rm -rf /, fork bombs.
   - Confirms strict blocking even in unrestricted/allow_admin mode.
4. Unrestricted Admin Privilege:
   - Administrative commands (docker stop, systemctl restart, apt update, kill, pipes, subshells)
     strictly blocked in standard mode, but cleanly permitted in unrestricted/admin mode.
5. SystemMasteryService Lifecycle & Zero-Leak Staging:
   - Base64 staging and host script cleanup in all scenarios (success, error, root).
   - Protection of critical production containers (dashboard_db, nginx, postgres, etc.).
"""

import asyncio
import os
from pathlib import Path
import shutil
import tempfile
import time
import tracemalloc
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.core.security import (
    HARDWARE_DESTRUCTIVE_PATTERNS,
    BLOCKED_PATTERNS,
    find_security_violation,
    is_hardware_destructive,
)
from app.services.universal_downloader import (
    UniversalDownloader,
    sanitize_filename,
    CHUNK_SIZE,
)
from app.services.web_article_extractor import (
    CleanArticleParser,
    WebArticleExtractor,
    select_best_article_content,
)
from app.services.system_mastery_service import (
    SystemMasteryService,
    CRITICAL_CONTAINERS,
)


class TestAdversarialUniversalDownloader(unittest.IsolatedAsyncioTestCase):
    """Stress and adversarial tests for UniversalDownloader."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="challenger_downloader_")
        self.downloader = UniversalDownloader(download_dir=Path(self.temp_dir))

    async def asyncTearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_large_file_streaming_128mb_ram_footprint(self):
        """
        Stress Test: Stream a 128MB (>100MB) file in 64KB chunks.
        Verify that RAM footprint remains < 5MB and final file size is exactly 128MB.
        """
        chunk_pattern = b"A" * CHUNK_SIZE  # 64 KB
        num_chunks = 2048  # 2048 * 64KB = 128 MB (134,217,728 bytes)
        total_size = num_chunks * CHUNK_SIZE

        mock_head = MagicMock()
        mock_head.status_code = 200
        mock_head.headers = httpx.Headers({
            "content-length": str(total_size),
            "content-type": "application/octet-stream",
            "accept-ranges": "bytes",
            "content-disposition": 'attachment; filename="stress_128mb.iso"',
        })

        mock_get = MagicMock()
        mock_get.status_code = 200
        mock_get.headers = mock_head.headers
        mock_get.reason_phrase = "OK"

        # Memory-efficient async generator yielding chunks without holding 128MB in memory
        async def stream_generator(chunk_size=CHUNK_SIZE):
            for _ in range(num_chunks):
                yield chunk_pattern

        mock_get.aiter_bytes = stream_generator

        stream_cm = AsyncMock()
        stream_cm.__aenter__.return_value = mock_get
        stream_cm.__aexit__.return_value = None

        mock_client = AsyncMock()
        mock_client.head.return_value = mock_head
        mock_client.stream = MagicMock(return_value=stream_cm)

        tracemalloc.start()
        snapshot_start = tracemalloc.take_snapshot()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            res = await self.downloader.download_direct_file("https://storage.cdn/stress_128mb.iso")

        current_ram, peak_ram = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        peak_ram_mb = peak_ram / (1024 * 1024)
        print(f"\n[Empirical Check] 128MB Streaming Peak RAM: {peak_ram_mb:.2f} MB")

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["file_name"], "stress_128mb.iso")
        self.assertEqual(res["file_size_bytes"], total_size)
        self.assertTrue(Path(res["file_path"]).exists())
        self.assertEqual(Path(res["file_path"]).stat().st_size, total_size)
        # Verify RAM footprint constraint (< 5MB)
        self.assertLess(peak_ram_mb, 5.0, f"RAM overhead {peak_ram_mb:.2f}MB exceeded 5MB limit!")

    async def test_sudden_network_disconnect_zero_disk_leak_non_resumable(self):
        """
        Adversarial Test: Network connection drops after transmitting partial data on a server
        that does NOT support resume. Verify Zero-Disk Leak: .part file must be purged.
        """
        partial_chunks = 10  # 10 * 64KB = 640 KB
        total_size = 10 * 1024 * 1024  # 10 MB

        mock_head = MagicMock()
        mock_head.status_code = 200
        # No Accept-Ranges header -> resume_supported = False
        mock_head.headers = httpx.Headers({
            "content-length": str(total_size),
            "content-type": "application/octet-stream",
        })

        mock_get = MagicMock()
        mock_get.status_code = 200
        mock_get.headers = mock_head.headers
        mock_get.reason_phrase = "OK"

        async def broken_generator(chunk_size=CHUNK_SIZE):
            for _ in range(partial_chunks):
                yield b"X" * CHUNK_SIZE
            # Simulate sudden socket abort / connection reset
            raise httpx.RemoteProtocolError("Connection reset by peer during chunked stream")

        mock_get.aiter_bytes = broken_generator

        stream_cm = AsyncMock()
        stream_cm.__aenter__.return_value = mock_get
        stream_cm.__aexit__.return_value = None

        mock_client = AsyncMock()
        mock_client.head.return_value = mock_head
        mock_client.stream = MagicMock(return_value=stream_cm)

        target_file = Path(self.temp_dir) / "broken_download.bin"
        part_file = Path(self.temp_dir) / "broken_download.bin.part"

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            res = await self.downloader.download_direct_file(
                "https://storage.cdn/broken_download.bin",
                custom_filename="broken_download.bin",
            )

        self.assertEqual(res["status"], "error")
        self.assertIn("Lỗi trong quá trình tải tệp", res["message"])
        # Final file should not exist
        self.assertFalse(target_file.exists())
        # Zero-Disk Leak: .part file MUST be purged on non-resumable abort
        self.assertFalse(part_file.exists(), "Zero-Disk Leak violation: Orphaned .part file remained on disk!")

    async def test_resumable_download_range_header_and_data_continuity(self):
        """
        Adversarial Test: Multi-pass download with network interruption.
        Pass 1: Interrupted at 40MB. .part file is preserved.
        Pass 2: Resume initiated with HTTP Range header. Server returns 206 Partial Content.
        Verify full 100MB file assembled with accurate content and no corruption.
        """
        total_size = 100 * 1024 * 1024  # 100 MB
        part1_size = 40 * 1024 * 1024   # 40 MB
        part2_size = 60 * 1024 * 1024   # 60 MB

        # Pass 1: Simulate interrupted download leaving a 40MB .part file
        target_name = "interrupted_large_dataset.bin"
        part_path = Path(self.temp_dir) / f"{target_name}.part"
        final_path = Path(self.temp_dir) / target_name

        # Write 40MB of pattern 'B' to simulate existing partial download
        with open(part_path, "wb") as f:
            f.write(b"B" * part1_size)

        self.assertTrue(part_path.exists())
        self.assertEqual(part_path.stat().st_size, part1_size)

        # Pass 2: Resume from byte 41,943,040
        mock_head = MagicMock()
        mock_head.status_code = 200
        mock_head.headers = httpx.Headers({
            "content-length": str(total_size),
            "content-type": "application/octet-stream",
            "accept-ranges": "bytes",
        })

        captured_headers = {}

        mock_get = MagicMock()
        mock_get.status_code = 206  # 206 Partial Content
        mock_get.headers = httpx.Headers({
            "content-length": str(part2_size),
            "content-range": f"bytes {part1_size}-{total_size-1}/{total_size}",
            "accept-ranges": "bytes",
            "content-type": "application/octet-stream",
        })
        mock_get.reason_phrase = "Partial Content"

        async def remaining_stream(chunk_size=CHUNK_SIZE):
            chunks_remaining = part2_size // CHUNK_SIZE
            for _ in range(chunks_remaining):
                yield b"C" * CHUNK_SIZE

        mock_get.aiter_bytes = remaining_stream

        def capture_stream(method, url, headers=None):
            captured_headers.update(headers or {})
            cm = AsyncMock()
            cm.__aenter__.return_value = mock_get
            cm.__aexit__.return_value = None
            return cm

        mock_client = AsyncMock()
        mock_client.head.return_value = mock_head
        mock_client.stream = MagicMock(side_effect=capture_stream)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            res = await self.downloader.download_direct_file(
                f"https://files.host/{target_name}",
            )

        self.assertEqual(res["status"], "success")
        self.assertTrue(res["resumed"], "Downloader failed to flag resumed download")
        self.assertTrue(res["resume_supported"])
        # Verify that Range request header was properly sent to remote server
        self.assertIn("Range", captured_headers)
        self.assertEqual(captured_headers["Range"], f"bytes={part1_size}-")

        # Verify final file integrity
        self.assertTrue(final_path.exists())
        self.assertFalse(part_path.exists(), ".part file must be cleanly replaced by final file")
        self.assertEqual(final_path.stat().st_size, total_size)

        # Check first chunk and last chunk to guarantee content continuity
        with open(final_path, "rb") as f:
            first_chunk = f.read(CHUNK_SIZE)
            self.assertEqual(first_chunk, b"B" * CHUNK_SIZE)
            f.seek(part1_size)
            resumed_chunk = f.read(CHUNK_SIZE)
            self.assertEqual(resumed_chunk, b"C" * CHUNK_SIZE)

    def test_path_traversal_and_malicious_filename_vectors(self):
        """
        Adversarial Test: Sanitization of path traversal patterns and reserved filenames.
        """
        vectors = [
            ("../../../../etc/shadow", "shadow"),
            (r"..\..\..\..\windows\system32\cmd.exe", "cmd.exe"),
            ("%2e%2e%2f%2e%2e%2froot%2fsecret.key", "secret.key"),
            ("....//....//nested//file.tar.gz", "file.tar.gz"),
            ("COM1", "COM1"),
            ("<script>alert(1)</script>.html", "script_.html"),
            ("   leading_trailing_spaces.zip   ", "leading_trailing_spaces.zip"),
            ("", "downloaded_file.bin"),
            (".", "downloaded_file.bin"),
            ("..", "downloaded_file.bin"),
        ]

        for raw_name, expected in vectors:
            sanitized = sanitize_filename(raw_name)
            self.assertNotIn("/", sanitized)
            self.assertNotIn("\\", sanitized)
            self.assertFalse(sanitized.startswith(".."))
            self.assertEqual(sanitized, expected, f"Sanitization mismatch for vector: {raw_name}")


class TestAdversarialWebArticleExtractor(unittest.IsolatedAsyncioTestCase):
    """Stress and adversarial tests for WebArticleExtractor."""

    async def asyncSetUp(self):
        self.extractor = WebArticleExtractor(request_timeout=5.0)

    def test_deeply_nested_100_scripts_and_toxic_css_sanitization(self):
        """
        Adversarial Test: HTML document containing 100 deeply nested <script> tags,
        heavy toxic CSS blocks, and 500 noise ad containers.
        Verify that parser does NOT crash or overflow recursion, and leaves ZERO script/css remnants.
        """
        nested_scripts = ""
        for i in range(100):
            nested_scripts += f'<script data-nest="{i}">console.log("nest_{i}");'
        nested_scripts += 'alert("XSS_ATTACK_ROOT");'
        for i in range(100):
            nested_scripts += "</script>"

        # Massive CSS block
        toxic_css = "<style>\n" + "\n".join(f".bad_rule_{i} {{ display: none; content: 'evil'; }}" for i in range(500)) + "\n</style>"

        # 500 ad/popup noise elements
        ad_noise = "".join(f'<div class="ad-banner-{i} popup-modal tracking-pixel"><p>Scam #{i}</p></div>' for i in range(500))

        hostile_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Hostile Attack Vector Page</title>
            <meta property="og:title" content="Adversarial Extractor Hardening">
            <meta name="author" content="Security Challenger">
            {toxic_css}
        </head>
        <body>
            {nested_scripts}
            {ad_noise}
            <article>
                <h1>An ninh Hệ thống AI Agent</h1>
                <p>Nội dung cốt lõi của bài báo khoa học về an toàn AI năm 2026.</p>
                <blockquote>Phòng thủ đa lớp và nguyên tắc Zero-Trust là nền tảng.</blockquote>
                <ul>
                    <li>Giám sát tài nguyên liên tục</li>
                    <li>Chặn cứng các vector phá hoại phần cứng</li>
                </ul>
            </article>
            <div id="footer-tracking">
                <script>document.location='http://evil.com/steal';</script>
            </div>
        </body>
        </html>
        """

        parser = CleanArticleParser()
        parser.feed(hostile_html)
        parser.close()

        md = select_best_article_content(parser.root)

        # Assert zero leakage of malicious scripts, styles, and ads
        self.assertNotIn("console.log", md)
        self.assertNotIn("XSS_ATTACK_ROOT", md)
        self.assertNotIn("evil.com", md)
        self.assertNotIn("bad_rule", md)
        self.assertNotIn("Scam #", md)

        # Assert preservation of legitimate article content
        self.assertIn("# An ninh Hệ thống AI Agent", md)
        self.assertIn("Nội dung cốt lõi của bài báo khoa học", md)
        self.assertIn("> Phòng thủ đa lớp và nguyên tắc Zero-Trust là nền tảng.", md)
        self.assertIn("* Giám sát tài nguyên liên tục", md)
        self.assertIn("* Chặn cứng các vector phá hoại phần cứng", md)

    def test_parser_ram_footprint_under_3mb_dirty_html(self):
        """
        Stress Test: Feed a massive 3MB dirty HTML page filled with repeated script/style/comment noise.
        Measure RAM footprint with tracemalloc and confirm peak usage < 5MB.
        """
        large_scripts = "<script>var payload = '0123456789ABCDEF';</script>\n" * 15000  # ~800 KB
        large_styles = "<style>.class { color: red; margin: 10px; }</style>\n" * 15000    # ~750 KB
        large_ads = '<div class="banner-ads"><p>Click here to win a car!</p></div>\n' * 15000 # ~1 MB

        huge_dirty_html = f"""
        <html>
        <head><title>Huge Dirty Page</title></head>
        <body>
            {large_scripts}
            {large_styles}
            {large_ads}
            <article>
                <h1>Bài báo thực tế trên mạng Internet</h1>
                <p>Hệ thống xử lý văn bản cần tiết kiệm bộ nhớ RAM trên máy chủ.</p>
            </article>
        </body>
        </html>
        """

        tracemalloc.start()
        snapshot_start = tracemalloc.take_snapshot()

        parser = CleanArticleParser()
        parser.feed(huge_dirty_html)
        parser.close()
        md = select_best_article_content(parser.root)

        current_ram, peak_ram = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        peak_ram_mb = peak_ram / (1024 * 1024)
        print(f"\n[Empirical Check] 3MB Dirty HTML Parse Peak RAM: {peak_ram_mb:.2f} MB")

        self.assertIn("# Bài báo thực tế trên mạng Internet", md)
        self.assertNotIn("Click here to win a car", md)
        self.assertNotIn("var payload", md)
        self.assertLess(peak_ram_mb, 5.0, f"HTML parsing RAM {peak_ram_mb:.2f}MB exceeded 5MB ceiling!")


class TestAdversarialHardwareSecurityAndAdminPass(unittest.TestCase):
    """
    Adversarial Tests for Spinal Hardware Safety Veto & Unrestricted Admin Permission:
    - Verifies that HARDWARE_DESTRUCTIVE_PATTERNS strictly vetoes catastrophic commands.
    - Verifies that unrestricted/allow_admin lifts artificial barriers for legit admin commands.
    """

    def test_hardware_destructive_patterns_blocked_in_all_modes(self):
        """
        Adversarial Test: Catastrophic hardware destruction commands MUST be rejected
        in BOTH standard mode AND unrestricted/allow_admin mode.
        """
        destructive_commands = [
            "mkfs.ext4 /dev/sda",
            "mkfs -t btrfs /dev/sdb",
            "wipefs -a /dev/sda",
            "dd if=/dev/zero of=/dev/sda bs=1M",
            "dd if=/dev/urandom of=/dev/nvme0n1",
            "dd of=/dev/sda1 count=100",
            "rm -rf /",
            "rm -rf /*",
            "rm -fr /",
            "rm -fr /*",
            "rm -rf --no-preserve-root /",
            ":(){ :|:& };:",  # Fork bomb
            "sudo mkfs /dev/sda1",
            "sudo dd if=/dev/zero of=/dev/sdb",
        ]

        for cmd in destructive_commands:
            # Check 1: is_hardware_destructive must return True
            self.assertTrue(
                is_hardware_destructive(cmd),
                f"Catastrophic command '{cmd}' was not identified by is_hardware_destructive!",
            )

            # Check 2: find_security_violation with unrestricted=True MUST still return a violation
            violation_unrestricted = find_security_violation(cmd, unrestricted=True)
            self.assertIsNotNone(
                violation_unrestricted,
                f"CRITICAL SECURITY FLAW: Destructive command '{cmd}' passed through unrestricted=True!",
            )
            self.assertIn("destructive hardware pattern", violation_unrestricted)

            # Check 3: find_security_violation with allow_admin=True MUST also return a violation
            violation_admin = find_security_violation(cmd, allow_admin=True)
            self.assertIsNotNone(
                violation_admin,
                f"CRITICAL SECURITY FLAW: Destructive command '{cmd}' passed through allow_admin=True!",
            )
            self.assertIn("destructive hardware pattern", violation_admin)

    def test_unrestricted_admin_commands_permitted_when_authorized(self):
        """
        Adversarial Test: Legitimate systems administration commands:
        - Dangerous/admin actions in BLOCKED_PATTERNS must be BLOCKED in standard mode.
        - ALL legitimate admin commands (docker stop/restart, systemctl, apt update/remove,
          kill, pipes, subshells) must be PERMITTED in unrestricted or allow_admin mode.
        """
        # Commands that are intentionally blocked in standard mode for unprivileged safety
        standard_blocked_admin_commands = [
            "docker stop dashboard_worker",
            "docker rm temporary_worker",
            "docker kill hanging_job",
            "systemctl stop my_service",
            "systemctl disable test_daemon",
            "apt remove obsolete_pkg",
            "apt-get purge bad_pkg",
            "pip uninstall requests",
            "kill -9 9876",
            "pkill -f my_process",
            "echo $(date +%s)",
            "echo `hostname`",
            "cat /var/log/syslog | bash",
            "echo 'hello' > /tmp/output.txt",
        ]

        # General admin commands that must succeed in unrestricted/admin mode
        all_admin_commands = standard_blocked_admin_commands + [
            "docker restart nginx_proxy",
            "systemctl restart nginx",
            "apt update",
            "apt-get install -y htop",
            "pip install --upgrade requests",
            "iptables -A INPUT -p tcp --dport 8080 -j ACCEPT",
            "cat /var/log/syslog | grep error",
        ]

        # 1. Verify standard blocked commands are blocked in standard mode
        for cmd in standard_blocked_admin_commands:
            std_violation = find_security_violation(cmd, unrestricted=False, allow_admin=False)
            self.assertIsNotNone(
                std_violation,
                f"Command '{cmd}' should be blocked in standard user mode!",
            )

        # 2. Verify ALL admin commands are permitted in unrestricted / allow_admin mode
        for cmd in all_admin_commands:
            # In unrestricted mode: MUST be permitted (None)
            unres_violation = find_security_violation(cmd, unrestricted=True)
            self.assertIsNone(
                unres_violation,
                f"Command '{cmd}' was incorrectly blocked in unrestricted mode: {unres_violation}",
            )

            # In allow_admin mode: MUST be permitted (None)
            admin_violation = find_security_violation(cmd, allow_admin=True)
            self.assertIsNone(
                admin_violation,
                f"Command '{cmd}' was incorrectly blocked in allow_admin mode: {admin_violation}",
            )


class TestAdversarialSystemMasteryService(unittest.IsolatedAsyncioTestCase):
    """Adversarial tests for SystemMasteryService operations and lifecycle."""

    async def asyncSetUp(self):
        self.mock_ssh = AsyncMock()
        self.service = SystemMasteryService(ssh_client=self.mock_ssh)

    async def test_run_command_unrestricted_blocks_hardware_attacks(self):
        """
        Verify that SystemMasteryService.run_command_unrestricted delegates to SSH client
        and marks hardware destructive commands as 'blocked'.
        """
        self.mock_ssh.execute_command.return_value = "BLOCKED: Lệnh bị từ chối vì lý do bảo mật (contains destructive hardware pattern 'mkfs')"

        res = await self.service.run_command_unrestricted("mkfs.ext4 /dev/sda")
        self.assertEqual(res["status"], "blocked")
        self.assertIn("cơ chế bảo vệ phần cứng", res["message"])

    async def test_execute_system_script_zero_leak_staging_on_failure(self):
        """
        Verify that execute_system_script always executes 'rm -f' cleanup on host
        even when script execution crashes or throws exceptions.
        """
        # Simulate SSH execution raising an exception during script execution
        self.mock_ssh.execute_command.side_effect = [
            "Staged OK",  # base64 stage
            RuntimeError("SSH pipe broken unexpectedly"),  # execution fail
            "Cleaned",    # rm -f cleanup in finally
        ]

        res = await self.service.execute_system_script("echo 'should fail'", interpreter="bash")
        self.assertEqual(res["status"], "error")
        self.assertIn("SSH pipe broken", res["message"])

        # Check call arguments: the last SSH call MUST be the cleanup command 'rm -f'
        self.assertEqual(self.mock_ssh.execute_command.call_count, 3)
        cleanup_call = self.mock_ssh.execute_command.call_args_list[-1]
        cleanup_cmd = cleanup_call[0][0]
        self.assertTrue(cleanup_cmd.startswith("rm -f /tmp/agent_script_"), f"Cleanup command was not called! Got: {cleanup_cmd}")

    async def test_manage_docker_containers_critical_guards(self):
        """
        Adversarial Test: Attempting to stop production-critical containers:
        - Without force=True -> Rejected with status: 'blocked'.
        - With force=True -> Allowed to proceed.
        """
        for container in CRITICAL_CONTAINERS:
            # Without force
            res_blocked = await self.service.manage_docker_containers("stop", container_name=container, force=False)
            self.assertEqual(
                res_blocked["status"],
                "blocked",
                f"Critical container '{container}' was stopped without force flag!",
            )
            self.assertIn("dịch vụ Production trọng yếu", res_blocked["message"])

            # With force
            self.mock_ssh.execute_command.return_value = container
            res_forced = await self.service.manage_docker_containers("stop", container_name=container, force=True)
            self.assertEqual(res_forced["status"], "success")


if __name__ == "__main__":
    unittest.main()
