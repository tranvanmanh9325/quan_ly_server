"""
test_tool_r8_file_manager.py — Unit & Adversarial Tests for FileManagerService (R8).

Validates Safe File Manager interface contracts & Security Boundaries:
- list_files(path, pattern, sort_by):
  - Valid path & metadata extraction (name, type, size, mtime)
  - Glob pattern filtering (*.py, test_*)
  - Sorting: name (A-Z), size (desc), date (newest first), invalid fallback
  - Nonexistent directory handling (status='not_found')
  - Path pointing to a file instead of a directory (status='error')
- read_file_content(path, lines):
  - Small text file (< 2000 chars) full read
  - Hard limit 2000 chars truncation (is_truncated=True)
  - Line-based clamping with `lines` parameter
  - Safe handling of negative or zero lines parameter
  - Binary file rejection (status='error', reason='binary_file')
  - Nonexistent file handling (status='not_found')
- write_file_content(path, content, mode):
  - Overwrite & append modes in allowed directories (/home/kirito/, /tmp/)
  - Auto-creation of nested parent directories
  - Security compliance: Base64 + tee pipeline (NEVER uses forbidden `> /` or `>> /`)
  - Unicode Vietnamese & emoji preservation
- Security & Path Traversal Mitigations:
  - Whitelist enforcement: Rejection of /etc/passwd, /var/log, /root/
  - Sensitive files protection: Rejection of .env, authorized_keys, id_rsa, .bashrc, .git
  - Path traversal (`../`) resolution & rejection
- move_or_rename_file(src, dst):
  - Safe rename & move within allowed directories
  - Destination outside whitelist rejection
  - Sensitive source file rejection
- get_disk_usage(path):
  - Top 10 heavy items analysis via du -sh
  - Nonexistent path handling & command injection mitigation
"""

import base64
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.security import find_security_violation
from app.services.file_manager_service import (
    FileManagerService,
    list_files,
    read_file_content,
    write_file_content,
    move_or_rename_file,
    get_disk_usage,
)


class MockSshClient:
    """Mock SSH client simulating host shell operations."""

    def __init__(self, responses=None, default_response=""):
        self.responses = responses or {}
        self.default_response = default_response
        self.executed_commands = []

    async def execute_command(self, command: str) -> str:
        self.executed_commands.append(command)
        for pattern, resp in self.responses.items():
            if pattern in command:
                return resp
        return self.default_response


class TestFileManagerServiceListing(unittest.IsolatedAsyncioTestCase):
    """Test suite for list_files() (R8-01 to R8-08)."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)
        self.service = FileManagerService(base_dir=str(self.base_path))

        # Populate sample files with distinct sizes and timestamps
        self.file_zebra = self.base_path / "zebra.txt"
        self.file_apple = self.base_path / "apple.py"
        self.file_banana = self.base_path / "banana.py"
        self.subfolder = self.base_path / "subfolder"

        self.file_zebra.write_text("Zebra content 10b", encoding="utf-8")
        self.file_apple.write_text("print('Apple')", encoding="utf-8")
        self.file_banana.write_text("print('Banana big content')" * 50, encoding="utf-8")
        self.subfolder.mkdir()

        # Set specific timestamps for sorting verification
        now = time.time()
        os.utime(self.subfolder, (now - 1000, now - 1000))
        os.utime(self.file_apple, (now - 300, now - 300))
        os.utime(self.file_banana, (now - 100, now - 100))
        os.utime(self.file_zebra, (now - 10, now - 10))

    def tearDown(self):
        self.temp_dir.cleanup()

    async def test_list_files_valid_directory(self):
        """R8-01: Lists valid directory contents and checks metadata."""
        res = await self.service.list_files(str(self.base_path))
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["total_items"], 4)
        names = [item["name"] for item in res["items"]]
        self.assertIn("zebra.txt", names)
        self.assertIn("subfolder", names)
        for item in res["items"]:
            self.assertIn("type", item)
            self.assertIn("size", item)
            self.assertIn("mtime", item)

    async def test_list_files_with_glob_pattern(self):
        """R8-02: Filters files using a glob pattern (*.py)."""
        res = await self.service.list_files(str(self.base_path), pattern="*.py")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["total_items"], 2)
        for item in res["items"]:
            self.assertTrue(item["name"].endswith(".py"))

    async def test_list_files_sort_by_name(self):
        """R8-03: Sorts files alphabetically by name (A-Z)."""
        res = await self.service.list_files(str(self.base_path), sort_by="name")
        self.assertEqual(res["status"], "success")
        names = [item["name"].lower() for item in res["items"]]
        self.assertEqual(names, sorted(names))

    async def test_list_files_sort_by_size(self):
        """R8-04: Sorts files in descending order by size."""
        res = await self.service.list_files(str(self.base_path), sort_by="size")
        self.assertEqual(res["status"], "success")
        sizes = [item["size_bytes"] for item in res["items"]]
        self.assertEqual(sizes, sorted(sizes, reverse=True))
        self.assertEqual(res["items"][0]["name"], "banana.py")

    async def test_list_files_sort_by_date(self):
        """R8-05: Sorts files with the most recently modified first."""
        res = await self.service.list_files(str(self.base_path), sort_by="date")
        self.assertEqual(res["status"], "success")
        # zebra.txt was updated most recently
        self.assertEqual(res["items"][0]["name"], "zebra.txt")

    async def test_list_files_invalid_sort_fallback(self):
        """R8-06: Falls back gracefully to name sort when sort_by is unrecognized."""
        res = await self.service.list_files(str(self.base_path), sort_by="unrecognized_criteria")
        self.assertEqual(res["status"], "success")
        names = [item["name"].lower() for item in res["items"]]
        self.assertEqual(names, sorted(names))

    async def test_list_files_nonexistent_directory(self):
        """R8-07: Returns not_found for nonexistent directory."""
        ghost_path = str(self.base_path / "ghost_dir_123")
        res = await self.service.list_files(ghost_path)
        self.assertEqual(res["status"], "not_found")

    async def test_list_files_path_is_file(self):
        """R8-08: Returns error when path points to a file rather than a directory."""
        file_path = str(self.file_apple)
        res = await self.service.list_files(file_path)
        self.assertEqual(res["status"], "error")
        self.assertIn("tệp, không phải thư mục", res["message"].lower())

    async def test_list_files_outside_whitelist_rejected(self):
        """R8-08b: Strictly rejects listing directories outside allowed whitelist (/etc, /var, ../../etc)."""
        mock_ssh = MockSshClient()
        ssh_service = FileManagerService(ssh_client=mock_ssh)
        forbidden_dirs = [
            "/etc",
            "/var",
            "/var/log",
            "/root",
            "/home/kirito/../../etc",
            "../../etc",
            "%2e%2e%2f%2e%2e%2fetc",
        ]
        for bad_dir in forbidden_dirs:
            res = await ssh_service.list_files(bad_dir)
            self.assertEqual(
                res["status"],
                "security_veto",
                f"Directory listing outside whitelist must be vetoed for '{bad_dir}', got {res}"
            )
            self.assertEqual(
                len(mock_ssh.executed_commands),
                0,
                f"No SSH command should be executed for blocked path '{bad_dir}'"
            )

    async def test_list_files_filters_sensitive_entries(self):
        """R8-08c: Ensures sensitive files/folders (.env, .bashrc, .ssh) are filtered out from listing results."""
        # Create sensitive files in test sandbox directory
        (self.base_path / ".env").write_text("SECRET=123", encoding="utf-8")
        (self.base_path / ".bashrc").write_text("# bash config", encoding="utf-8")
        (self.base_path / ".git").mkdir(exist_ok=True)
        (self.base_path / "normal_visible.txt").write_text("Hello", encoding="utf-8")

        res = await self.service.list_files(str(self.base_path))
        self.assertEqual(res["status"], "success")
        item_names = [item["name"] for item in res["items"]]
        self.assertIn("normal_visible.txt", item_names)
        self.assertNotIn(".env", item_names)
        self.assertNotIn(".bashrc", item_names)
        self.assertNotIn(".git", item_names)


class TestFileManagerServiceRead(unittest.IsolatedAsyncioTestCase):
    """Test suite for read_file_content() (R8-09 to R8-14)."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)
        self.service = FileManagerService(base_dir=str(self.base_path))

    def tearDown(self):
        self.temp_dir.cleanup()

    async def test_read_file_content_small_text_file(self):
        """R8-09: Reads small text file (< 2000 chars) completely without truncation."""
        f = self.base_path / "small.txt"
        f.write_text("Hello World 123", encoding="utf-8")
        res = await self.service.read_file_content(str(f))
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["content"], "Hello World 123")
        self.assertFalse(res["is_truncated"])
        self.assertEqual(res["char_count"], 15)

    async def test_read_file_content_exceeds_2000_chars_clamped(self):
        """R8-10: Clamps file content exceeding 2000 chars and sets is_truncated=True."""
        f = self.base_path / "large.txt"
        f.write_text("A" * 5000, encoding="utf-8")
        res = await self.service.read_file_content(str(f))
        self.assertEqual(res["status"], "success")
        self.assertTrue(res["is_truncated"])
        self.assertLessEqual(len(res["content"]), 2100)
        self.assertIn("cắt ngắn", res["content"].lower())

    async def test_read_file_content_with_lines_param(self):
        """R8-11: Reads only the first N lines when `lines` parameter is specified."""
        f = self.base_path / "multiline.txt"
        f.write_text("\n".join(f"Line {i}" for i in range(1, 51)), encoding="utf-8")
        res = await self.service.read_file_content(str(f), lines=10)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["lines_read"], 10)
        self.assertIn("Line 10", res["content"])
        self.assertNotIn("Line 11", res["content"])

    async def test_read_file_content_negative_lines_clamped(self):
        """R8-12: Handles negative or zero `lines` parameter safely without crashing."""
        f = self.base_path / "sample.txt"
        f.write_text("Sample line 1\nSample line 2", encoding="utf-8")
        res = await self.service.read_file_content(str(f), lines=-5)
        self.assertEqual(res["status"], "success")
        self.assertIn("Sample line 1", res["content"])

    async def test_read_file_content_binary_file_rejected(self):
        """R8-13: Rejects binary files containing null bytes or binary extensions."""
        # Test 1: Null bytes content
        f_bin = self.base_path / "binary.bin"
        f_bin.write_bytes(b"\x00\x01\x02\xFF\xFE\x00")
        res = await self.service.read_file_content(str(f_bin))
        self.assertEqual(res["status"], "error")
        self.assertEqual(res.get("reason"), "binary_file")
        self.assertIn("nhị phân", res["message"].lower())

        # Test 2: Binary extension (.png)
        f_png = self.base_path / "image.png"
        f_png.write_bytes(b"PNGFAKEIMAGE")
        res2 = await self.service.read_file_content(str(f_png))
        self.assertEqual(res2["status"], "error")
        self.assertEqual(res2.get("reason"), "binary_file")

    async def test_read_file_content_nonexistent(self):
        """R8-14: Returns not_found for nonexistent file."""
        res = await self.service.read_file_content(str(self.base_path / "missing.txt"))
        self.assertEqual(res["status"], "not_found")

    async def test_read_file_content_sensitive_files_rejected(self):
        """R8-14b: Strictly rejects reading sensitive files (.env, .bashrc, id_rsa, .git)."""
        mock_ssh = MockSshClient()
        ssh_service = FileManagerService(ssh_client=mock_ssh)
        sensitive_paths = [
            "/home/kirito/.env",
            "/home/kirito/.env.production",
            "/home/kirito/.bashrc",
            "/home/kirito/.ssh/id_rsa",
            "/home/kirito/.ssh/authorized_keys",
            "/home/kirito/.git/config",
        ]
        for sp in sensitive_paths:
            res = await ssh_service.read_file_content(sp)
            self.assertEqual(
                res["status"],
                "security_veto",
                f"Reading sensitive file must be vetoed for '{sp}', got {res}"
            )
            self.assertIn("nhạy cảm", res["message"].lower())
            self.assertEqual(len(mock_ssh.executed_commands), 0)

    async def test_read_file_content_path_traversal_and_outside_whitelist_rejected(self):
        """R8-14c: Rejects path traversal and reading files outside whitelist (/etc/hosts, ../../etc/passwd)."""
        mock_ssh = MockSshClient()
        ssh_service = FileManagerService(ssh_client=mock_ssh)
        attack_paths = [
            "/etc/hosts",
            "/home/kirito/../../etc/hosts",
            "../../etc/passwd",
            "/var/log/syslog",
            "%2e%2e%2f%2e%2e%2fetc/passwd",
            "/root/.bashrc",
        ]
        for bad_path in attack_paths:
            res = await ssh_service.read_file_content(bad_path)
            self.assertEqual(
                res["status"],
                "security_veto",
                f"Reading outside whitelist or path traversal must be vetoed for '{bad_path}', got {res}"
            )
            self.assertEqual(len(mock_ssh.executed_commands), 0)

    async def test_read_file_content_ssh_filter_blocked_handling(self):
        """R8-14d: Handles SSH filter BLOCKED response correctly (returns error/security_violation, not success)."""
        mock_ssh = MockSshClient()
        mock_ssh.responses = {
            "head -c 5000 '/home/kirito/blocked_file.txt'": "BLOCKED: contains sensitive keyword"
        }
        ssh_service = FileManagerService(ssh_client=mock_ssh)
        res = await ssh_service.read_file_content("/home/kirito/blocked_file.txt")
        self.assertEqual(res["status"], "error")
        self.assertEqual(res["reason"], "security_violation")
        self.assertIn("BLOCKED:", res["message"])
        self.assertNotEqual(res.get("status"), "success")

    async def test_read_file_content_ssh_null_byte_detected(self):
        """R8-14e: Detects binary null bytes in SSH output and rejects with binary_file reason."""
        mock_ssh = MockSshClient()
        mock_ssh.responses = {
            "head -c 5000 '/home/kirito/binary.data'": "data\x00corrupted"
        }
        ssh_service = FileManagerService(ssh_client=mock_ssh)
        res = await ssh_service.read_file_content("/home/kirito/binary.data")
        self.assertEqual(res["status"], "error")
        self.assertEqual(res["reason"], "binary_file")
        self.assertIn("null byte", res["message"].lower())


class TestFileManagerServiceWriteAndSecurity(unittest.IsolatedAsyncioTestCase):
    """Test suite for write_file_content(), move_or_rename_file() and Security Boundaries (R8-15 to R8-23)."""

    def setUp(self):
        self.mock_ssh = MockSshClient()
        self.service = FileManagerService(ssh_client=self.mock_ssh)

    async def test_write_file_content_overwrite_mode(self):
        """R8-15: Writes file in overwrite mode."""
        path = "/home/kirito/notes.txt"
        content = "Overwritten content"
        res = await self.service.write_file_content(path, content, mode="overwrite")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["mode"], "overwrite")
        cmd = self.mock_ssh.executed_commands[0]
        self.assertIn("tee", cmd)
        self.assertNotIn("tee -a", cmd)

    async def test_write_file_content_append_mode(self):
        """R8-16: Appends content to file in append mode using tee -a."""
        path = "/tmp/app.log"
        content = "Appended log line\n"
        res = await self.service.write_file_content(path, content, mode="append")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["mode"], "append")
        cmd = self.mock_ssh.executed_commands[0]
        self.assertIn("tee -a", cmd)

    async def test_write_file_content_auto_create_parent_dirs(self):
        """R8-17: Automatically creates parent directories via mkdir -p."""
        path = "/home/kirito/dir1/dir2/file.txt"
        res = await self.service.write_file_content(path, "Nested content")
        self.assertEqual(res["status"], "success")
        cmd = self.mock_ssh.executed_commands[0]
        self.assertIn("mkdir -p '/home/kirito/dir1/dir2'", cmd)

    async def test_write_file_content_ssh_pipeline_security_compliance(self):
        """R8-18: Verifies write commands NEVER use forbidden `> /` or `>> /`."""
        path = "/tmp/test_agent_file.txt"
        content = "Line 1 content\nLine 2 content"
        res = await self.service.write_file_content(path, content, mode="overwrite")
        self.assertEqual(res["status"], "success")

        self.assertEqual(len(self.mock_ssh.executed_commands), 1)
        cmd = self.mock_ssh.executed_commands[0]
        self.assertNotIn(" > /", cmd)
        self.assertNotIn(" >> /", cmd)
        self.assertIn("base64 -d | tee", cmd)
        self.assertIsNone(find_security_violation(cmd))

    async def test_write_file_content_unicode_vietnamese_and_emojis(self):
        """R8-19: Preserves Vietnamese accents, special characters, and emojis."""
        with tempfile.TemporaryDirectory() as td:
            local_service = FileManagerService(base_dir=td)
            vietnamese_content = "Tiêu đề: Báo cáo quản lý máy chủ 🚀🇻🇳\nNội dung: Hệ thống vận hành trơn tru 100%!"
            target = os.path.join(td, "vietnamese.txt")

            res = await local_service.write_file_content(target, vietnamese_content)
            self.assertEqual(res["status"], "success")

            read_res = await local_service.read_file_content(target)
            self.assertEqual(read_res["status"], "success")
            self.assertEqual(read_res["content"], vietnamese_content)

    async def test_security_write_outside_whitelist_blocked(self):
        """R8-20: Blocks write operations outside allowed whitelist (/home/kirito/ & /tmp/)."""
        forbidden_targets = [
            "/etc/passwd",
            "/var/log/syslog",
            "/root/.bashrc",
            "/usr/local/bin/malware",
            "/boot/grub.cfg",
        ]
        for bad_path in forbidden_targets:
            res = await self.service.write_file_content(bad_path, "evil payload")
            self.assertEqual(res["status"], "security_veto")
            self.assertIn("ranh giới an toàn", res["message"].lower())

        self.assertEqual(len(self.mock_ssh.executed_commands), 0)

    async def test_security_write_sensitive_files_blocked(self):
        """R8-21: Blocks write operations on sensitive files even inside whitelist."""
        sensitive_files = [
            "/home/kirito/.env",
            "/home/kirito/.env.production",
            "/home/kirito/.ssh/authorized_keys",
            "/home/kirito/.ssh/id_rsa",
            "/home/kirito/.bashrc",
            "/home/kirito/.git/config",
        ]
        for sens_path in sensitive_files:
            res = await self.service.write_file_content(sens_path, "modified")
            self.assertEqual(res["status"], "security_veto")
            self.assertIn("nhạy cảm", res["message"].lower())

        self.assertEqual(len(self.mock_ssh.executed_commands), 0)

    async def test_security_path_traversal_blocked(self):
        """R8-22: Blocks path traversal attempts (../) escaping whitelist root."""
        traversal_attempts = [
            "/home/kirito/../../etc/shadow",
            "/tmp/../../../var/www/index.php",
            "/home/kirito/data/../../../../root/.ssh/id_rsa",
        ]
        for trav in traversal_attempts:
            res = await self.service.write_file_content(trav, "data")
            self.assertEqual(res["status"], "security_veto")

        self.assertEqual(len(self.mock_ssh.executed_commands), 0)

    async def test_move_or_rename_file_success_and_veto(self):
        """R8-23: Tests safe rename within whitelist vs veto when moving outside or sensitive."""
        # 1. Success rename within whitelist
        res_ok = await self.service.move_or_rename_file(
            src="/tmp/old_name.txt",
            dst="/tmp/new_name.txt",
        )
        self.assertEqual(res_ok["status"], "success")
        self.assertTrue(any("mv " in cmd for cmd in self.mock_ssh.executed_commands))

        # Clear mock history
        self.mock_ssh.executed_commands.clear()

        # 2. Veto destination outside whitelist
        res_veto_dst = await self.service.move_or_rename_file(
            src="/tmp/harmless.txt",
            dst="/etc/cron.d/evil_cron",
        )
        self.assertEqual(res_veto_dst["status"], "security_veto")
        self.assertEqual(len(self.mock_ssh.executed_commands), 0)

        # 3. Veto moving sensitive source file
        res_veto_src = await self.service.move_or_rename_file(
            src="/home/kirito/.env",
            dst="/tmp/.env.bak",
        )
        self.assertEqual(res_veto_src["status"], "security_veto")
        self.assertEqual(len(self.mock_ssh.executed_commands), 0)


class TestFileManagerServiceDiskUsage(unittest.IsolatedAsyncioTestCase):
    """Test suite for get_disk_usage() (R8-24)."""

    def setUp(self):
        self.mock_ssh = MockSshClient()
        self.service = FileManagerService(ssh_client=self.mock_ssh)

    async def test_get_disk_usage_top10_and_injection(self):
        """R8-24: Analyzes top 10 heavy items and protects against command injection."""
        # 1. Successful top 10 disk usage parsing
        mock_du_output = (
            "15G\t/home/kirito\n"
            "5.2G\t/home/kirito/quan_ly_server\n"
            "3.1G\t/home/kirito/docker_data\n"
            "1.2G\t/home/kirito/media\n"
            "500M\t/home/kirito/backup.zip\n"
        )
        self.mock_ssh.responses = {
            "du ": mock_du_output,
        }
        res = await self.service.get_disk_usage("/home/kirito")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["total_size"], "15G")
        self.assertLessEqual(len(res["top_items"]), 10)
        self.assertEqual(res["top_items"][0]["path"], "/home/kirito/quan_ly_server")
        self.assertEqual(res["top_items"][0]["size"], "5.2G")

        # 2. Command injection rejected
        self.mock_ssh.executed_commands.clear()
        evil_path = "/home/kirito; rm -rf /"
        res_inj = await self.service.get_disk_usage(evil_path)
        self.assertEqual(res_inj["status"], "error")
        self.assertIn("không hợp lệ", res_inj["message"])
        self.assertEqual(len(self.mock_ssh.executed_commands), 0)


if __name__ == "__main__":
    unittest.main()
