"""
test_tool_r3_notes.py — Unit & Adversarial Tests for NotesService (R3).

Validates Personal Notes & Knowledge Base interface contracts:
- create_note(title, content, tags)
- search_notes(query, tags)
- list_notes(tag)
- delete_note(note_id)
- Special characters, unicode, emojis, shell metacharacter resilience
- Security compliance: Base64 encoding + tee instead of forbidden `> /` redirects
- Tier 2 Reversible trash bin (.trash/) instead of forbidden `rm` command
- Path traversal & command injection rejection
"""

import base64
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.security import find_security_violation
from app.services.notes_service import (
    NotesService,
    _slugify,
    create_note,
    delete_note,
    list_notes,
    search_notes,
)


class MockSshClient:
    """Mock SSH client for simulating deterministic server outputs."""

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


class TestNotesService(unittest.IsolatedAsyncioTestCase):
    """Test suite for NotesService (R3)."""

    def setUp(self):
        self.mock_ssh = MockSshClient()
        self.service = NotesService(
            ssh_client=self.mock_ssh,
            base_path="/home/kirito/quan_ly_server/data/notes",
        )

    # ──────────────────────────────────────────────────────────────────────────
    # 1. create_note Tests (Special characters, Security Compliance)
    # ──────────────────────────────────────────────────────────────────────────

    async def test_create_note_special_characters_and_emojis(self):
        title = "Ghi chú Bảo mật & NGINX Reverse Proxy 🚀 [2026] <VVIP>"
        content = "Cấu hình SSL: Certbot --nginx; Ký tự: %&*#@!^~| và tiếng Việt có dấu."
        tags = ["bảo_mật", "nginx", "proxy_2026"]

        res = await self.service.create_note(title=title, content=content, tags=tags)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["title"], title)
        self.assertEqual(res["tags"], tags)
        self.assertTrue(res["note_id"].startswith("ghi_chu_bao_mat_nginx_reverse_"))

        # Verify command execution:
        self.assertEqual(len(self.mock_ssh.executed_commands), 1)
        executed_cmd = self.mock_ssh.executed_commands[0]

        # 1. Must NOT use forbidden redirect operators `> /` or `>> /`
        self.assertNotIn(" > /", executed_cmd)
        self.assertNotIn(" >> /", executed_cmd)

        # 2. Must use `base64 -d | tee`
        self.assertIn("base64 -d | tee", executed_cmd)

        # 3. Must satisfy security filter
        violation = find_security_violation(executed_cmd)
        self.assertIsNone(violation, f"Executed command violates security: {violation}")

    async def test_create_note_shell_injection_metacharacters(self):
        """Shell injection strings in title/content must be safely encoded and neutralized."""
        evil_title = "Note `whoami` $(echo 123) | id ; ls -la & echo ok"
        evil_content = "Payload with | bash and ; rm -rf / and > /etc/shadow and cat /etc/passwd and reboot"

        res = await self.service.create_note(title=evil_title, content=evil_content)
        self.assertEqual(res["status"], "success")

        executed_cmd = self.mock_ssh.executed_commands[0]
        # Command itself must be safe because payload is base64 encoded
        violation = find_security_violation(executed_cmd)
        self.assertIsNone(violation, f"Executed command violates security: {violation}")

        # Decode base64 to ensure payload integrity was preserved exactly
        parts = executed_cmd.split("echo ")
        b64_part = parts[1].split(" |")[0]
        decoded = base64.b64decode(b64_part).decode("utf-8")
        self.assertIn(evil_title, decoded)
        self.assertIn(evil_content, decoded)

    async def test_create_note_empty_and_whitespace_tags(self):
        res = await self.service.create_note(
            title="Clean Tags Note",
            content="Some body",
            tags=["", "   ", "valid_tag", "  spaced_tag  ", ""],
        )
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["tags"], ["valid_tag", "spaced_tag"])

    async def test_create_note_empty_tags_list_or_none(self):
        res1 = await self.service.create_note("T1", "C1", tags=[])
        self.assertEqual(res1["status"], "success")
        self.assertEqual(res1["tags"], [])

        res2 = await self.service.create_note("T2", "C2", tags=None)
        self.assertEqual(res2["status"], "success")
        self.assertEqual(res2["tags"], [])

    async def test_create_note_empty_title_and_content_rejected(self):
        res1 = await self.service.create_note("", "")
        self.assertEqual(res1["status"], "error")
        self.assertIn("không được để trống", res1["message"])

        res2 = await self.service.create_note("   ", "   ")
        self.assertEqual(res2["status"], "error")

    async def test_create_note_empty_title_uses_first_line(self):
        body = "Dòng đầu tiên làm tiêu đề tự động\nDòng thứ hai nội dung chi tiết."
        res = await self.service.create_note("", body)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["title"], "Dòng đầu tiên làm tiêu đề tự động")

    # ──────────────────────────────────────────────────────────────────────────
    # 2. search_notes Tests
    # ──────────────────────────────────────────────────────────────────────────

    async def test_search_notes_nonexistent_keyword(self):
        self.mock_ssh.responses = {
            "grep -rn": "",
        }
        res = await self.service.search_notes("NONEXISTENT_TRAP_STRING_12345")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["total"], 0)
        self.assertEqual(res["notes"], [])
        self.assertIn("Không tìm thấy", res["message"])

    async def test_search_notes_special_characters(self):
        res = await self.service.search_notes('query with "quotes" and $signs and ;')
        self.assertEqual(res["status"], "success")
        executed_cmd = self.mock_ssh.executed_commands[0]
        # Query must be safely quoted using shlex.quote and isolated with '--'
        self.assertIn("--", executed_cmd)
        self.assertIn("'query with \"quotes\" and $signs and ;'", executed_cmd)
        self.assertIsNone(find_security_violation(executed_cmd))

    async def test_search_notes_empty_query_without_tags_rejected(self):
        res = await self.service.search_notes("", tags=None)
        self.assertEqual(res["status"], "error")
        self.assertIn("không được để trống", res["message"])

    async def test_search_notes_empty_query_with_tags_delegates_to_list(self):
        mock_list_output = (
            "/home/kirito/quan_ly_server/data/notes/note1.md:id: note1\n"
            "/home/kirito/quan_ly_server/data/notes/note1.md:title: Dev Note\n"
            "/home/kirito/quan_ly_server/data/notes/note1.md:tags: dev, sre\n"
        )
        self.mock_ssh.responses = {
            "grep -H -E": mock_list_output,
        }
        res = await self.service.search_notes("", tags=["dev"])
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["total"], 1)
        self.assertEqual(res["notes"][0]["title"], "Dev Note")

    async def test_search_notes_matching_results(self):
        mock_grep_hits = (
            "/home/kirito/quan_ly_server/data/notes/n1.md:12:Tìm thấy keyword ở dòng 12\n"
            "/home/kirito/quan_ly_server/data/notes/n1.md:15:Tìm thấy keyword ở dòng 15\n"
        )
        mock_list_output = (
            "/home/kirito/quan_ly_server/data/notes/n1.md:id: n1\n"
            "/home/kirito/quan_ly_server/data/notes/n1.md:title: Note One\n"
            "/home/kirito/quan_ly_server/data/notes/n1.md:tags: tagA\n"
        )
        self.mock_ssh.responses = {
            "grep -rn": mock_grep_hits,
            "grep -H -E": mock_list_output,
        }
        res = await self.service.search_notes("keyword")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["total"], 1)
        self.assertEqual(res["notes"][0]["id"], "n1")
        self.assertEqual(len(res["notes"][0]["excerpts"]), 2)

    # ──────────────────────────────────────────────────────────────────────────
    # 3. list_notes Tests
    # ──────────────────────────────────────────────────────────────────────────

    async def test_list_notes_empty(self):
        self.mock_ssh.responses = {
            "grep -H -E": "grep: /home/kirito/quan_ly_server/data/notes/*.md: No such file or directory",
        }
        res = await self.service.list_notes()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["total"], 0)
        self.assertEqual(res["notes"], [])

    async def test_list_notes_with_tag_filtering(self):
        mock_output = (
            "/home/kirito/quan_ly_server/data/notes/n1.md:id: n1\n"
            "/home/kirito/quan_ly_server/data/notes/n1.md:title: N1 Title\n"
            "/home/kirito/quan_ly_server/data/notes/n1.md:tags: linux, security\n"
            "/home/kirito/quan_ly_server/data/notes/n2.md:id: n2\n"
            "/home/kirito/quan_ly_server/data/notes/n2.md:title: N2 Title\n"
            "/home/kirito/quan_ly_server/data/notes/n2.md:tags: python, ai\n"
        )
        self.mock_ssh.responses = {
            "grep -H -E": mock_output,
        }

        # List all
        all_res = await self.service.list_notes()
        self.assertEqual(all_res["total"], 2)

        # Filter tag 'security'
        sec_res = await self.service.list_notes(tag="security")
        self.assertEqual(sec_res["total"], 1)
        self.assertEqual(sec_res["notes"][0]["id"], "n1")

        # Filter tag 'nonexistent'
        non_res = await self.service.list_notes(tag="nonexistent")
        self.assertEqual(non_res["total"], 0)

    # ──────────────────────────────────────────────────────────────────────────
    # 4. delete_note Tests (Tier 2 Reversible, Security)
    # ──────────────────────────────────────────────────────────────────────────

    async def test_delete_note_moves_to_trash(self):
        """Must use `mv ... .trash/` and NEVER use `rm`."""
        res = await self.service.delete_note("note_20260926_123456")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["action"], "moved_to_trash")
        self.assertTrue(res["reversible"])

        executed_cmd = self.mock_ssh.executed_commands[0]
        self.assertIn("mkdir -p", executed_cmd)
        self.assertIn("mv ", executed_cmd)
        self.assertIn(".trash/", executed_cmd)
        self.assertNotIn("rm ", executed_cmd)

        # Satisfies security
        self.assertIsNone(find_security_violation(executed_cmd))

    async def test_delete_note_nonexistent(self):
        self.mock_ssh.responses = {
            "mv ": "cannot stat: No such file or directory",
        }
        res = await self.service.delete_note("ghost_note")
        self.assertEqual(res["status"], "not_found")
        self.assertIn("Không tìm thấy", res["message"])

    async def test_delete_note_path_traversal_and_injection_rejected(self):
        # 1. Injection characters must be rejected immediately with status='error'
        evil_ids = [
            "note; rm -rf /",
            "note$(whoami)",
            "note`id`",
            "note | bash",
            "note & reboot",
            "",
            "   ",
        ]
        for evil_id in evil_ids:
            res = await self.service.delete_note(evil_id)
            self.assertEqual(
                res["status"],
                "error",
                f"Injection ID '{evil_id}' was not rejected with status='error'!",
            )

        # 2. Path traversal attempts: ensure they cannot escape notes base directory
        self.mock_ssh.responses = {
            "mv ": "cannot stat: No such file or directory",
        }
        traversal_ids = ["../../etc/passwd", "../secret", "note/child"]
        for trav_id in traversal_ids:
            res = await self.service.delete_note(trav_id)
            # Must either be error or not_found, NEVER successfully deleting root files
            self.assertIn(res["status"], ("error", "not_found"))
            if len(self.mock_ssh.executed_commands) > 0:
                cmd = self.mock_ssh.executed_commands[-1]
                # Target path MUST stay within /home/kirito/quan_ly_server/data/notes/
                self.assertTrue(
                    cmd.startswith("mkdir -p /home/kirito/quan_ly_server/data/notes/.trash && mv /home/kirito/quan_ly_server/data/notes/"),
                    f"Command escaped notes directory: {cmd}",
                )


if __name__ == "__main__":
    unittest.main()
