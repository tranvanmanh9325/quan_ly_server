"""
test_challenger_m4_it2_harness.py — Empirical Verification Harness for M4 Iteration 2.

Adversarial Stress-Test Scenarios:
1. Path Traversal in read_file_content and list_files:
   - /home/kirito/../../etc/hosts
   - ../../etc/passwd
   - /etc/shadow
   - URL-encoded (%2e%2e%2f%2e%2e%2fetc/hosts, %2e%2e/%2e%2e/etc/passwd, %2e%2e%2fetc/shadow)
   - Confirmed 100% blocked with security_veto.
2. Sensitive files in read_file_content:
   - /home/kirito/.bashrc, .env, .ssh/id_rsa, .git/config
   - Confirmed 100% blocked with security_veto.
3. SSH returning BLOCKED: -> status: "error", reason: "security_violation", NOT "success".
4. restart_ngrok_tunnel(confirm=None) -> confirmation_required, ZERO SSH calls.
"""

import asyncio
import unittest
from app.services.file_manager_service import FileManagerService
from app.services.network_service import NetworkService, NGROK_CONFIRM_TOKEN


class SpySSH:
    def __init__(self):
        self.history = []
        self.blocked_pattern = None

    async def execute_command(self, cmd: str) -> str:
        self.history.append(cmd)
        if self.blocked_pattern and self.blocked_pattern in cmd:
            return "BLOCKED: contains forbidden pattern"
        return "dummy output"


class TestEmpiricalChallengerM4It2(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ssh = SpySSH()
        self.fsvc = FileManagerService(ssh_client=self.ssh)
        self.nsvc = NetworkService(ssh_client=self.ssh)

    async def test_01_read_file_content_path_traversal(self):
        traversal_targets = [
            "/home/kirito/../../etc/hosts",
            "../../etc/passwd",
            "/etc/shadow",
            "%2e%2e%2f%2e%2e%2fetc/hosts",
            "%2e%2e/%2e%2e/etc/passwd",
            "%2e%2e%2fetc/shadow",
            "/tmp/../../etc/hosts",
            "/home/kirito/../../../etc/hosts",
        ]
        for path in traversal_targets:
            res = await self.fsvc.read_file_content(path)
            self.assertEqual(res.get("status"), "security_veto", f"Failed for {path}: {res}")
            self.assertIn("ranh giới an toàn", res.get("message", ""))
        self.assertEqual(len(self.ssh.history), 0, "No SSH command should be executed for traversal read")

    async def test_02_list_files_path_traversal(self):
        traversal_targets = [
            "/home/kirito/../../etc/hosts",
            "../../etc/passwd",
            "/etc/shadow",
            "%2e%2e%2f%2e%2e%2fetc/hosts",
            "%2e%2e/%2e%2e/etc/passwd",
            "%2e%2e%2fetc/shadow",
            "/tmp/../../etc/hosts",
            "/home/kirito/../../../etc/hosts",
        ]
        for path in traversal_targets:
            res = await self.fsvc.list_files(path)
            self.assertEqual(res.get("status"), "security_veto", f"Failed for {path}: {res}")
            self.assertIn("ranh giới an toàn", res.get("message", ""))
        self.assertEqual(len(self.ssh.history), 0, "No SSH command should be executed for traversal list")

    async def test_03_read_file_content_sensitive_files(self):
        sensitive_targets = [
            "/home/kirito/.bashrc",
            "/home/kirito/.bash_profile",
            "/home/kirito/.env",
            "/home/kirito/.env.production",
            "/home/kirito/.env.local",
            "/home/kirito/.ssh/id_rsa",
            "/home/kirito/.ssh/id_ed25519",
            "/home/kirito/.ssh/authorized_keys",
            "/home/kirito/.git/config",
        ]
        for path in sensitive_targets:
            res = await self.fsvc.read_file_content(path)
            self.assertEqual(res.get("status"), "security_veto", f"Failed for {path}: {res}")
            self.assertIn("nhạy cảm", res.get("message", ""))
        self.assertEqual(len(self.ssh.history), 0, "No SSH command should be executed for sensitive read")

    async def test_04_ssh_blocked_filter_handling(self):
        self.ssh.blocked_pattern = "blocked_test"
        res_blocked = await self.fsvc.read_file_content("/home/kirito/blocked_test.txt")
        self.assertEqual(res_blocked.get("status"), "error")
        self.assertEqual(res_blocked.get("reason"), "security_violation")
        self.assertNotEqual(res_blocked.get("status"), "success")
        self.assertIn("BLOCKED:", res_blocked.get("message", ""))

    async def test_05_restart_ngrok_tunnel_confirm_none(self):
        history_before = len(self.ssh.history)
        res_none = await self.nsvc.restart_ngrok_tunnel("web", confirm=None)
        self.assertEqual(res_none.get("status"), "confirmation_required")
        self.assertTrue(res_none.get("requires_confirm"))
        self.assertEqual(res_none.get("confirm_token"), NGROK_CONFIRM_TOKEN)
        self.assertEqual(len(self.ssh.history), history_before, "No SSH command should be executed for confirm=None")

        res_def = await self.nsvc.restart_ngrok_tunnel()
        self.assertEqual(res_def.get("status"), "confirmation_required")
        self.assertTrue(res_def.get("requires_confirm"))
        self.assertEqual(res_def.get("confirm_token"), NGROK_CONFIRM_TOKEN)
        self.assertEqual(len(self.ssh.history), history_before, "No SSH command should be executed for default confirm")


if __name__ == "__main__":
    unittest.main()
