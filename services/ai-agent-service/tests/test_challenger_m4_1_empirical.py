"""
test_challenger_m4_1_empirical.py — Milestone 4 Empirical Adversarial Stress Test Suite (Iteration 2).

Author: Challenger 1 (EMPIRICAL CHALLENGER / critic & specialist)
Target Modules:
- app.services.file_manager_service (R8)
- app.services.network_service (R7)

MANDATORY EMPIRICAL VERIFICATION CRITERIA:
1. Path Traversal:
   - Deliberately write/read `../../etc/passwd`, `/home/kirito/../../etc/shadow`, URL-encoded `%2e%2e%2f`.
   - Must confirm 100% blocked and safe with `security_veto`.
2. Sensitive Files:
   - Deliberately read/write `/home/kirito/.env`, `/home/kirito/.bashrc`, `/home/kirito/.ssh/id_rsa`.
   - Must confirm 100% blocked with `security_veto`.
3. Binary Files Reading:
   - Try reading files with null bytes, `.bin`, `.png` extensions.
   - Must confirm safe rejection (status: error, reason: binary_file).
4. Large Files Clamping:
   - Read file with 10,000 characters.
   - Must confirm clamped to exactly 2,000 characters with is_truncated=True.
5. Ngrok Injection & Restart Safety:
   - Try tunnel_name containing `; rm -rf`, invalid confirm token, or confirm=None.
   - Must confirm safe rejection and 0 dangerous commands executed.
6. SSH Filter BLOCKED Handling:
   - When SSH filter returns `BLOCKED:`, returns status: "error", reason: "security_violation".
"""

import asyncio
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.file_manager_service import (
    FileManagerService,
    list_files,
    read_file_content,
    write_file_content,
    move_or_rename_file,
    get_disk_usage,
)
from app.services.network_service import (
    NetworkService,
    get_ngrok_status,
    restart_ngrok_tunnel,
    get_network_info,
    NGROK_CONFIRM_TOKEN,
)


class MockSshClientForFileManager:
    """Mock SSH client recording executed commands and providing controllable responses."""

    def __init__(self):
        self.executed_commands: List[str] = []
        self.responses: Dict[str, str] = {}
        self.default_response: str = ""

    async def execute_command(self, cmd: str) -> str:
        self.executed_commands.append(cmd)
        for pattern, resp in self.responses.items():
            if pattern in cmd:
                return resp
        return self.default_response


class TestChallengerM41EmpiricalAdversarial(unittest.IsolatedAsyncioTestCase):
    """Empirical adversarial stress test suite covering M4 R7 and R8 contracts."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="challenger_m4_test_")
        self.mock_ssh = MockSshClientForFileManager()
        self.local_file_service = FileManagerService(base_dir=self.temp_dir)
        self.ssh_file_service = FileManagerService(ssh_client=self.mock_ssh)
        self.network_service = NetworkService(ssh_client=self.mock_ssh)

    async def asyncTearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # =========================================================================
    # Group 1: Path Traversal Stress-Testing (Write & Read & List)
    # =========================================================================

    async def test_01_path_traversal_write_outside_whitelist_blocked(self):
        """Stress-test: write_file_content must 100% block ../../etc/passwd, shadow, URL-encoded."""
        attack_paths = [
            "../../etc/passwd",
            "/home/kirito/../../etc/shadow",
            "%2e%2e%2f%2e%2e%2fetc/passwd",
            "%2e%2e/%2e%2e/etc/shadow",
            "/tmp/../../etc/passwd",
            "/var/log/syslog",
            "/etc/nginx/nginx.conf",
        ]

        for path in attack_paths:
            res = await self.ssh_file_service.write_file_content(path, "malicious_payload")
            self.assertEqual(
                res.get("status"),
                "security_veto",
                f"Path traversal write must be vetoed for '{path}', got {res}"
            )
            # Ensure no SSH command was executed for writing
            self.assertEqual(
                len(self.mock_ssh.executed_commands),
                0,
                f"SSH command must NOT be called for blocked path '{path}'"
            )

    async def test_02_path_traversal_write_in_local_sandbox_blocked(self):
        """Stress-test: local sandbox write must strictly confine to base_dir."""
        escape_paths = [
            "../../outside_file.txt",
            "../../../evil.sh",
            "%2e%2e%2f%2e%2e%2ftrick.txt",
        ]

        for path in escape_paths:
            res = await self.local_file_service.write_file_content(path, "escape")
            self.assertEqual(
                res.get("status"),
                "security_veto",
                f"Local sandbox write must be vetoed for '{path}', got {res}"
            )

    async def test_03_path_traversal_read_investigation_and_findings(self):
        """
        Adversarial evaluation of read_file_content on path traversal inputs:
        - Confirms read_file_content blocks reading outside allowed boundaries with security_veto.
        """
        res_passwd = await self.ssh_file_service.read_file_content("../../etc/passwd")
        self.assertEqual(
            res_passwd.get("status"),
            "security_veto",
            f"Expected security_veto for '../../etc/passwd', got: {res_passwd}"
        )
        self.assertEqual(len(self.mock_ssh.executed_commands), 0)

    async def test_04_path_traversal_move_or_rename_blocked(self):
        """Stress-test: move_or_rename_file must reject src or dst outside boundary."""
        # Malicious src
        res1 = await self.ssh_file_service.move_or_rename_file("../../etc/passwd", "/home/kirito/stolen")
        self.assertEqual(res1.get("status"), "security_veto")

        # Malicious dst
        res2 = await self.ssh_file_service.move_or_rename_file("/home/kirito/legit.txt", "../../etc/pwned")
        self.assertEqual(res2.get("status"), "security_veto")

        # URL-encoded traversal
        res3 = await self.ssh_file_service.move_or_rename_file("%2e%2e%2f%2e%2e%2fetc/passwd", "/tmp/out")
        self.assertEqual(res3.get("status"), "security_veto")

    # =========================================================================
    # Group 2: Sensitive Files Overwrite & Protection
    # =========================================================================

    async def test_05_sensitive_files_overwrite_strictly_vetoed(self):
        """Stress-test: writing to sensitive files must be 100% blocked with status=security_veto."""
        sensitive_targets = [
            "/home/kirito/.env",
            "/home/kirito/.env.production",
            "/home/kirito/.env.local",
            "/home/kirito/.bashrc",
            "/home/kirito/.bash_profile",
            "/home/kirito/.profile",
            "/home/kirito/.zshrc",
            "/home/kirito/.ssh/id_rsa",
            "/home/kirito/.ssh/id_ed25519",
            "/home/kirito/.ssh/authorized_keys",
            "/home/kirito/.ssh/known_hosts",
            "/home/kirito/.git/config",
            "/home/kirito/.git/HEAD",
            "/etc/shadow",
            "/root/.bashrc",
        ]

        for target in sensitive_targets:
            res = await self.ssh_file_service.write_file_content(target, "COMPROMISED=true")
            self.assertEqual(
                res.get("status"),
                "security_veto",
                f"Writing to sensitive target '{target}' must be vetoed, got: {res}"
            )
            self.assertTrue(
                "nhạy cảm" in res.get("message", "") or "ranh giới an toàn" in res.get("message", ""),
                f"Expected security message for '{target}', got: {res.get('message')}"
            )

        # Verify no SSH commands were issued
        self.assertEqual(len(self.mock_ssh.executed_commands), 0)

    # =========================================================================
    # Group 3: Binary File Rejection
    # =========================================================================

    async def test_06_binary_file_extension_rejection(self):
        """Stress-test: reading files with binary extensions (.bin, .png, .exe, .zip, etc.) rejected."""
        binary_files = [
            "image.png",
            "firmware.bin",
            "executable.exe",
            "archive.zip",
            "document.pdf",
            "video.mp4",
            "backup.tar.gz",
        ]

        for filename in binary_files:
            file_path = f"/home/kirito/downloads/{filename}"
            res = await self.ssh_file_service.read_file_content(file_path)
            self.assertEqual(res.get("status"), "error")
            self.assertEqual(res.get("reason"), "binary_file")
            self.assertIn("nhị phân", res.get("message", ""))

        # Verification: extensions are checked before any SSH call is made
        self.assertEqual(len(self.mock_ssh.executed_commands), 0)

    async def test_07_binary_null_byte_content_rejection(self):
        """Stress-test: text file containing null byte (\\x00) must be rejected as binary."""
        # Create a file with .txt extension but containing null byte inside local temp_dir
        binary_txt = os.path.join(self.temp_dir, "sneaky.txt")
        with open(binary_txt, "wb") as f:
            f.write(b"Hello world\x00corrupted binary null byte data")

        res = await self.local_file_service.read_file_content("sneaky.txt")
        self.assertEqual(res.get("status"), "error")
        self.assertEqual(res.get("reason"), "binary_file")
        self.assertIn("null byte", res.get("message", ""))

    # =========================================================================
    # Group 4: Large File Truncation (Clamping to 2000 characters)
    # =========================================================================

    async def test_08_large_file_clamped_to_2000_chars(self):
        """Stress-test: 10,000 char file must be clamped to 2,000 characters with is_truncated=True."""
        large_content = "X" * 10000
        large_file = os.path.join(self.temp_dir, "large.txt")
        with open(large_file, "w", encoding="utf-8") as f:
            f.write(large_content)

        res = await self.local_file_service.read_file_content("large.txt")
        self.assertEqual(res.get("status"), "success")
        self.assertTrue(res.get("is_truncated"))
        self.assertEqual(res.get("char_count"), 10000)

        # Check content length: The extracted text slice must be 2000 chars before truncation message
        content = res.get("content", "")
        self.assertIn("... [Nội dung bị cắt ngắn do vượt quá giới hạn 2000 ký tự]", content)
        # 2000 chars of 'X'
        self.assertTrue(content.startswith("X" * 2000))

    async def test_09_small_file_not_truncated(self):
        """Stress-test: file under 2000 chars must not be truncated."""
        content = "Small content under limit."
        small_file = os.path.join(self.temp_dir, "small.txt")
        with open(small_file, "w", encoding="utf-8") as f:
            f.write(content)

        res = await self.local_file_service.read_file_content("small.txt")
        self.assertEqual(res.get("status"), "success")
        self.assertFalse(res.get("is_truncated"))
        self.assertEqual(res.get("content"), content)

    # =========================================================================
    # Group 5: Ngrok Injection & Restart Safety
    # =========================================================================

    async def test_10_ngrok_injection_blocked(self):
        """Stress-test: tunnel_name with injection payloads must be rejected immediately."""
        evil_payloads = [
            "; rm -rf /",
            "tunnel && id",
            "tunnel | cat /etc/passwd",
            "`whoami`",
            "$(cat /etc/shadow)",
            "tunnel\nreboot",
            "tunnel; shutdown -h now",
        ]

        for payload in evil_payloads:
            res = await self.network_service.restart_ngrok_tunnel(tunnel_name=payload)
            self.assertEqual(res.get("status"), "error")
            self.assertIn("không hợp lệ", res.get("message", ""))
            self.assertEqual(len(self.mock_ssh.executed_commands), 0)

    async def test_11_ngrok_restart_wrong_confirm_token_vetoed(self):
        """Stress-test: wrong confirmation token must return confirmation_required."""
        wrong_tokens = [
            "wrong_token",
            "RESTART",
            "CONFIRMED",
            "restart_confirmed",
            "12345",
        ]

        for tok in wrong_tokens:
            res = await self.network_service.restart_ngrok_tunnel(tunnel_name="web", confirm=tok)
            self.assertEqual(
                res.get("status"),
                "confirmation_required",
                f"Wrong token '{tok}' must require confirmation, got: {res}"
            )
            self.assertEqual(res.get("confirm_token"), NGROK_CONFIRM_TOKEN)
            self.assertEqual(len(self.mock_ssh.executed_commands), 0)

    @patch("asyncio.sleep", return_value=None)
    @patch("httpx.AsyncClient.get")
    async def test_12_ngrok_restart_valid_confirm_token_executes(self, mock_get, mock_sleep):
        """Stress-test: valid confirmation token allows execution and probes for updated URL."""
        self.mock_ssh.responses["restart web"] = "Restarting ngrok@web: OK"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "tunnels": [
                {
                    "name": "web",
                    "public_url": "https://valid-new-url.ngrok-free.app",
                    "proto": "https",
                }
            ]
        }
        mock_get.return_value = mock_resp

        res = await self.network_service.restart_ngrok_tunnel(
            tunnel_name="web", confirm=NGROK_CONFIRM_TOKEN
        )
        self.assertEqual(res.get("status"), "success")
        self.assertEqual(res.get("new_url"), "https://valid-new-url.ngrok-free.app")
        self.assertTrue(any("restart web" in cmd for cmd in self.mock_ssh.executed_commands))

    # =========================================================================
    # Group 6: Shell Injection Stress-Testing on File Operations
    # =========================================================================

    async def test_13_file_manager_injection_in_paths(self):
        """Stress-test: filenames with shell injection characters must be rejected."""
        injections = [
            "/home/kirito/file;rm -rf /",
            "/home/kirito/file && ls",
            "/home/kirito/file | id",
            "/home/kirito/file`whoami`",
            "/home/kirito/file$(cat /etc/shadow)",
            "/home/kirito/file\nnewline.txt",
        ]

        for inj in injections:
            res_w = await self.ssh_file_service.write_file_content(inj, "content")
            self.assertEqual(res_w.get("status"), "security_veto")

            res_r = await self.ssh_file_service.read_file_content(inj)
            self.assertEqual(res_r.get("status"), "error")

            res_l = await self.ssh_file_service.list_files(inj)
            self.assertEqual(res_l.get("status"), "error")

            res_d = await self.ssh_file_service.get_disk_usage(inj)
            self.assertEqual(res_d.get("status"), "error")

        self.assertEqual(len(self.mock_ssh.executed_commands), 0)

    # =========================================================================
    # Group 7: Empirical Adversarial Verification of Fixes (Iteration 2)
    # =========================================================================

    async def test_14_path_traversal_read_and_sensitive_files_blocked(self):
        """
        EMPIRICAL VERIFICATION (Fix 1):
        - `read_file_content` MUST 100% block sensitive files (.bashrc, .env, .ssh/id_rsa).
        - `read_file_content` MUST 100% block path traversal (/home/kirito/../../etc/hosts, ../../etc/passwd, /etc/shadow, URL-encoded).
        - Returns status: 'security_veto' and issues ZERO SSH commands.
        """
        sensitive_targets = [
            "/home/kirito/.bashrc",
            "/home/kirito/.env",
            "/home/kirito/.ssh/id_rsa",
            "/home/kirito/.git/config",
        ]
        for target in sensitive_targets:
            res = await self.ssh_file_service.read_file_content(target)
            self.assertEqual(
                res.get("status"),
                "security_veto",
                f"Reading sensitive file '{target}' must be vetoed, got: {res}"
            )
            self.assertIn("nhạy cảm", res.get("message", ""))

        traversal_targets = [
            "/home/kirito/../../etc/hosts",
            "../../etc/passwd",
            "/etc/shadow",
            "%2e%2e%2f%2e%2e%2fetc/hosts",
            "%2e%2e/%2e%2e/etc/passwd",
            "/var/log/syslog",
            "/tmp/../../etc/shadow",
        ]
        for target in traversal_targets:
            res = await self.ssh_file_service.read_file_content(target)
            self.assertEqual(
                res.get("status"),
                "security_veto",
                f"Reading outside whitelist/traversal '{target}' must be vetoed, got: {res}"
            )

        # Confirm ZERO SSH commands were issued to the server
        self.assertEqual(
            len(self.mock_ssh.executed_commands),
            0,
            f"SSH commands must NOT be executed for blocked paths, got: {self.mock_ssh.executed_commands}"
        )

    async def test_15_read_file_content_ssh_filter_blocked_handling(self):
        """
        EMPIRICAL VERIFICATION (Fix 2):
        When SSH security filter returns 'BLOCKED:', `read_file_content` MUST return
        status: 'error', reason: 'security_violation', and must NEVER return 'success'.
        """
        self.mock_ssh.responses["head -c 5000"] = "BLOCKED: contains forbidden pattern"
        # Using a legitimate path within /home/kirito/ so it passes local boundary validation and hits SSH
        res = await self.ssh_file_service.read_file_content("/home/kirito/legit_path.txt")

        self.assertEqual(
            res.get("status"),
            "error",
            f"Expected status 'error' when SSH filter blocks, got: {res}"
        )
        self.assertEqual(
            res.get("reason"),
            "security_violation",
            f"Expected reason 'security_violation', got: {res}"
        )
        self.assertIn("BLOCKED:", res.get("message", ""))
        self.assertNotEqual(res.get("status"), "success")

    async def test_16_list_files_path_traversal_and_sensitive_blocked(self):
        """
        EMPIRICAL VERIFICATION (Fix 3):
        - `list_files` MUST validate path boundaries and sensitive files.
        - Directory traversal (/home/kirito/../../etc/hosts, ../../etc/passwd, /etc/shadow, URL-encoded)
          must be blocked with status: 'security_veto'.
        - Issues ZERO SSH commands.
        """
        blocked_paths = [
            "../../etc",
            "/home/kirito/../../etc",
            "/etc",
            "/var",
            "%2e%2e%2f%2e%2e%2fetc",
            "/home/kirito/.ssh",
        ]
        for path in blocked_paths:
            res = await self.ssh_file_service.list_files(path)
            self.assertEqual(
                res.get("status"),
                "security_veto",
                f"Listing '{path}' must be vetoed, got: {res}"
            )

        self.assertEqual(
            len(self.mock_ssh.executed_commands),
            0,
            f"SSH commands must NOT be executed for blocked list paths, got: {self.mock_ssh.executed_commands}"
        )

    async def test_17_restart_ngrok_without_confirm_requires_confirmation(self):
        """
        EMPIRICAL VERIFICATION (Fix 4):
        In `restart_ngrok_tunnel`, when `confirm=None` (or invalid), the method MUST return
        status: 'confirmation_required' and must issue ZERO SSH commands.
        """
        # Call with confirm=None (default or explicit)
        res_none = await self.network_service.restart_ngrok_tunnel(tunnel_name="web", confirm=None)
        self.assertEqual(
            res_none.get("status"),
            "confirmation_required",
            f"Calling restart_ngrok_tunnel with confirm=None must require confirmation, got: {res_none}"
        )
        self.assertTrue(res_none.get("requires_confirm"))
        self.assertEqual(res_none.get("confirm_token"), NGROK_CONFIRM_TOKEN)
        self.assertEqual(len(self.mock_ssh.executed_commands), 0)

        # Call with default argument (confirm omitted)
        res_default = await self.network_service.restart_ngrok_tunnel()
        self.assertEqual(res_default.get("status"), "confirmation_required")
        self.assertEqual(len(self.mock_ssh.executed_commands), 0)


if __name__ == "__main__":
    unittest.main()
