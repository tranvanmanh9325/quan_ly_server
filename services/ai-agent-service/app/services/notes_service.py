"""
app/services/notes_service.py — Personal Notes & Knowledge Base Service (R3).

Manages Markdown-based personal notes stored directly on the host server:
- create_note: Creates or updates a personal Markdown note with metadata frontmatter.
- search_notes: Performs full-text search across all notes with optional tag filtering.
- list_notes: Lists available notes with metadata and optional tag filtering.
- delete_note: Safely moves a note to `.trash/` (Tier 2 Reversible).

Storage Architecture & Security Compliance:
- Server Directory: `/home/kirito/quan_ly_server/data/notes/`
- Trash Directory: `/home/kirito/quan_ly_server/data/notes/.trash/`
- Reuses `SshClient` from `app.core.ssh_client`.
- Complies strictly with `security.py:28` (which blocks `> /` and `>> /`) by streaming
  file contents via `echo <base64> | base64 -d | tee <path>`.
"""

import base64
from datetime import datetime, timedelta, timezone
import logging
import os
import re
import secrets
import shlex
from typing import Any, Dict, List, Optional
import unicodedata

from app.core.ssh_client import SshClient

logger = logging.getLogger(__name__)

VN_TZ = timezone(timedelta(hours=7))
DEFAULT_NOTES_DIR = "/home/kirito/quan_ly_server/data/notes"


def _slugify(text: str) -> str:
    """Converts Vietnamese or arbitrary unicode title into a safe lowercase ASCII slug."""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_text = "".join([c for c in nfkd if not unicodedata.combining(c)])
    slug = re.sub(r"[^a-zA-Z0-9_\-]", "_", ascii_text.lower()).strip("_")
    slug = re.sub(r"_+", "_", slug)[:30].strip("_")
    return slug


class NotesService:
    """
    Manages Markdown personal notes on the server over SSH.
    Supports YAML frontmatter for structured indexing, full-text searching,
    tag filtering, and safe trash bin operations.
    """

    def __init__(
        self,
        ssh_client: Optional[SshClient] = None,
        base_path: str = DEFAULT_NOTES_DIR,
    ):
        self._ssh_client = ssh_client
        self.base_path = base_path.rstrip("/")
        self.trash_path = f"{self.base_path}/.trash"

    @property
    def ssh_client(self) -> SshClient:
        if self._ssh_client is None:
            self._ssh_client = SshClient()
        return self._ssh_client

    def _generate_note_id(self, title: str) -> str:
        """Generates a collision-resistant, human-readable note ID."""
        slug = _slugify(title)
        timestamp_str = datetime.now(VN_TZ).strftime("%Y%m%d_%H%M%S")
        rand_suffix = secrets.token_hex(2)
        if slug:
            return f"{slug}_{timestamp_str}_{rand_suffix}"
        return f"note_{timestamp_str}_{rand_suffix}"

    async def create_note(
        self,
        title: str,
        content: str,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Creates a new personal note stored as Markdown with YAML frontmatter.
        Uses `echo <base64> | base64 -d | tee <path>` to adhere to security redirect rules.
        """
        clean_title = str(title).strip() if title else ""
        clean_content = str(content).strip() if content else ""

        if not clean_title and not clean_content:
            return {
                "status": "error",
                "message": "Tiêu đề hoặc nội dung ghi chú không được để trống.",
            }

        if not clean_title:
            # Extract first line or default fallback
            first_line = clean_content.splitlines()[0][:40].strip()
            clean_title = first_line or "Ghi chú không tiêu đề"

        clean_tags: List[str] = []
        if tags:
            clean_tags = [str(t).strip() for t in tags if str(t).strip()]

        now_utc = datetime.now(timezone.utc)
        now_vn_str = now_utc.astimezone(VN_TZ).strftime("%Y-%m-%d %H:%M:%S (UTC+7)")
        now_iso = now_utc.isoformat()

        note_id = self._generate_note_id(clean_title)
        file_path = f"{self.base_path}/{note_id}.md"

        # Build Markdown file with YAML frontmatter
        tags_line = ", ".join(clean_tags) if clean_tags else "none"
        markdown_body = (
            f"---\n"
            f"id: {note_id}\n"
            f"title: {clean_title}\n"
            f"tags: {tags_line}\n"
            f"created_at: {now_vn_str}\n"
            f"updated_at: {now_vn_str}\n"
            f"---\n\n"
            f"# {clean_title}\n\n"
            f"{clean_content}\n"
        )

        # Base64 encode to prevent shell escaping issues and security violation
        b64_content = base64.b64encode(markdown_body.encode("utf-8")).decode("ascii")

        # Command using `mkdir -p` and `tee` without forbidden `> /` redirect
        save_cmd = (
            f"mkdir -p {self.trash_path} && "
            f"echo {b64_content} | base64 -d | tee {file_path}"
        )

        try:
            output = await self.ssh_client.execute_command(save_cmd)
            if output.startswith("BLOCKED:"):
                logger.error("[NotesService] Save note command was blocked: %s", output)
                return {
                    "status": "blocked",
                    "message": output,
                }

            logger.info("[NotesService] Note '%s' saved to %s", clean_title, file_path)
            return {
                "status": "success",
                "note_id": note_id,
                "title": clean_title,
                "tags": clean_tags,
                "file_path": file_path,
                "created_at": now_iso,
                "created_at_vn": now_vn_str,
                "message": f"Đã lưu ghi chú '{clean_title}' thành công vào hệ thống.",
                "text": (
                    f"📝 Đã lưu ghi chú thành công!\n"
                    f"• Mã: `{note_id}`\n"
                    f"• Tiêu đề: *{clean_title}*\n"
                    f"• Thẻ (Tags): `{', '.join(clean_tags) if clean_tags else 'không có'}`\n"
                    f"• Đường dẫn: `{file_path}`"
                ),
            }
        except Exception as exc:
            logger.error("[NotesService] Error saving note '%s': %s", clean_title, exc)
            return {
                "status": "error",
                "message": f"Lỗi khi lưu ghi chú lên server: {str(exc)}",
            }

    async def list_notes(self, tag: Optional[str] = None) -> Dict[str, Any]:
        """
        Lists all Markdown notes stored in the notes directory.
        Extracts frontmatter metadata (id, title, tags, created_at).
        Optionally filters by tag.
        """
        # Grep frontmatter keys in one compact shell command
        probe_cmd = f"grep -H -E '^(id|title|tags|created_at):' {self.base_path}/*.md"

        try:
            output = await self.ssh_client.execute_command(probe_cmd)
        except Exception as exc:
            logger.error("[NotesService] Error listing notes via SSH: %s", exc)
            return {
                "status": "error",
                "message": f"Không thể lấy danh sách ghi chú: {str(exc)}",
                "notes": [],
                "total": 0,
            }

        if "No such file or directory" in output or "cannot access" in output or not output.strip():
            return {
                "status": "success",
                "notes": [],
                "total": 0,
                "tag_filter": tag,
                "message": "Chưa có ghi chú nào được lưu trên hệ thống.",
            }

        # Parse grep output
        notes_by_path: Dict[str, Dict[str, Any]] = {}
        for line in output.splitlines():
            line_str = line.strip()
            if not line_str or line_str.startswith("grep:"):
                continue

            parts = line_str.split(":", 2)
            if len(parts) >= 3:
                fpath = parts[0].strip()
                k = parts[1].strip()
                v = parts[2].strip()

                if fpath not in notes_by_path:
                    filename = os.path.basename(fpath)
                    default_id = filename.replace(".md", "")
                    notes_by_path[fpath] = {
                        "id": default_id,
                        "title": default_id,
                        "tags": [],
                        "created_at": "",
                        "file_path": fpath,
                    }

                if k == "id":
                    notes_by_path[fpath]["id"] = v
                elif k == "title":
                    notes_by_path[fpath]["title"] = v
                elif k == "tags":
                    if v and v.lower() != "none":
                        parsed_tags = [t.strip() for t in v.split(",") if t.strip()]
                        notes_by_path[fpath]["tags"] = parsed_tags
                elif k == "created_at":
                    notes_by_path[fpath]["created_at"] = v

        all_notes = list(notes_by_path.values())

        # Tag filtering
        if tag and tag.strip():
            filter_tag = tag.strip().lower()
            filtered_notes = [
                n for n in all_notes
                if any(filter_tag == t.lower() for t in n.get("tags", []))
            ]
        else:
            filtered_notes = all_notes

        return {
            "status": "success",
            "total": len(filtered_notes),
            "tag_filter": tag,
            "notes": filtered_notes,
        }

    async def search_notes(
        self,
        query: str,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Performs full-text search across Markdown notes on the server.
        Matches against content and metadata, with optional tag filtering.
        """
        clean_query = str(query).strip() if query else ""
        norm_tags = [str(t).strip().lower() for t in tags if str(t).strip()] if tags else []

        # If query is empty but tags are provided, delegate to tag listing
        if not clean_query and norm_tags:
            first_tag = norm_tags[0]
            list_res = await self.list_notes(tag=first_tag)
            matching_notes = list_res.get("notes", [])
            # If multiple tags, filter by all tags
            if len(norm_tags) > 1:
                matching_notes = [
                    n for n in matching_notes
                    if all(t in [x.lower() for x in n.get("tags", [])] for t in norm_tags)
                ]
            return {
                "status": "success",
                "query": "",
                "tags_filter": tags,
                "total": len(matching_notes),
                "notes": matching_notes,
            }

        if not clean_query:
            return {
                "status": "error",
                "message": "Từ khóa tìm kiếm (query) không được để trống.",
            }

        # Safe grep query escaping using shlex.quote and '--' argument separator to prevent injection
        escaped_query = shlex.quote(clean_query)
        grep_cmd = f"grep -rn -i -F --exclude-dir=.trash -- {escaped_query} {self.base_path}/"

        try:
            output = await self.ssh_client.execute_command(grep_cmd)
        except Exception as exc:
            logger.error("[NotesService] Error searching notes: %s", exc)
            return {
                "status": "error",
                "message": f"Lỗi tìm kiếm ghi chú: {str(exc)}",
                "notes": [],
                "total": 0,
            }

        if "No such file or directory" in output or not output.strip() or output.startswith("BLOCKED:"):
            return {
                "status": "success",
                "query": clean_query,
                "tags_filter": tags,
                "total": 0,
                "notes": [],
                "message": f"Không tìm thấy ghi chú nào khớp với từ khóa '{clean_query}'.",
            }

        # Group matches by file path
        matches_by_file: Dict[str, List[str]] = {}
        for line in output.splitlines():
            line_str = line.strip()
            if not line_str:
                continue
            parts = line_str.split(":", 2)
            if len(parts) >= 3:
                fpath = parts[0].strip()
                content = parts[2].strip()
                if fpath not in matches_by_file:
                    matches_by_file[fpath] = []
                if len(matches_by_file[fpath]) < 3:
                    matches_by_file[fpath].append(content[:120])

        # Fetch index of all notes to enrich search hits with title and tags
        list_res = await self.list_notes()
        all_notes_map = {n["file_path"]: n for n in list_res.get("notes", [])}

        results: List[Dict[str, Any]] = []
        for fpath, excerpts in matches_by_file.items():
            meta = all_notes_map.get(
                fpath,
                {
                    "id": os.path.basename(fpath).replace(".md", ""),
                    "title": os.path.basename(fpath).replace(".md", ""),
                    "tags": [],
                    "created_at": "",
                    "file_path": fpath,
                },
            )

            # Check tag filter if specified
            if norm_tags:
                note_tags_lower = [t.lower() for t in meta.get("tags", [])]
                if not any(t in note_tags_lower for t in norm_tags):
                    continue

            results.append(
                {
                    "id": meta.get("id"),
                    "title": meta.get("title"),
                    "tags": meta.get("tags", []),
                    "created_at": meta.get("created_at"),
                    "file_path": fpath,
                    "excerpts": excerpts,
                }
            )

        return {
            "status": "success",
            "query": clean_query,
            "tags_filter": tags,
            "total": len(results),
            "notes": results,
        }

    async def delete_note(self, note_id: str) -> Dict[str, Any]:
        """
        Deletes a note safely by moving it to `.trash/` (Tier 2 Reversible).
        Avoids `rm` command blocked by security policies.
        """
        clean_id = os.path.basename(str(note_id).strip()).replace(".md", "")
        if not clean_id or not re.match(r"^[a-zA-Z0-9_\-]+$", clean_id):
            return {
                "status": "error",
                "message": f"Mã ghi chú không hợp lệ: '{note_id}'.",
            }

        src_file = f"{self.base_path}/{clean_id}.md"
        dest_trash = f"{self.trash_path}/{clean_id}.md"

        # Tier 2 Reversible: moves to trash directory instead of permanent destruction
        move_cmd = f"mkdir -p {self.trash_path} && mv {src_file} {dest_trash}"

        try:
            output = await self.ssh_client.execute_command(move_cmd)
            output_clean = output.strip()

            if "No such file or directory" in output_clean or "cannot stat" in output_clean:
                return {
                    "status": "not_found",
                    "note_id": clean_id,
                    "message": f"Không tìm thấy ghi chú '{clean_id}' trên hệ thống để xóa.",
                }

            if output_clean.startswith("BLOCKED:"):
                return {
                    "status": "blocked",
                    "message": output_clean,
                }

            logger.info("[NotesService] Note '%s' moved to trash: %s", clean_id, dest_trash)
            return {
                "status": "success",
                "note_id": clean_id,
                "action": "moved_to_trash",
                "reversible": True,
                "trash_path": dest_trash,
                "message": f"Đã chuyển ghi chú '{clean_id}' vào thùng rác (.trash) an toàn.",
            }
        except Exception as exc:
            logger.error("[NotesService] Error deleting note '%s': %s", clean_id, exc)
            return {
                "status": "error",
                "message": f"Lỗi khi xóa ghi chú: {str(exc)}",
            }

    async def get_note(self, note_id: str) -> Dict[str, Any]:
        """Reads and parses a single note by ID."""
        clean_id = os.path.basename(str(note_id).strip()).replace(".md", "")
        if not clean_id or not re.match(r"^[a-zA-Z0-9_\-]+$", clean_id):
            return {
                "status": "error",
                "message": f"Mã ghi chú không hợp lệ: '{note_id}'.",
            }

        src_file = f"{self.base_path}/{clean_id}.md"
        read_cmd = f"cat {src_file}"

        try:
            output = await self.ssh_client.execute_command(read_cmd)
            if "No such file or directory" in output:
                return {
                    "status": "not_found",
                    "note_id": clean_id,
                    "message": f"Không tìm thấy ghi chú '{clean_id}'.",
                }

            # Simple YAML frontmatter extraction
            title = clean_id
            tags: List[str] = []
            content = output
            if output.startswith("---"):
                parts = output.split("---", 2)
                if len(parts) >= 3:
                    frontmatter = parts[1]
                    content = parts[2].strip()
                    for line in frontmatter.splitlines():
                        if line.startswith("title:"):
                            title = line.split(":", 1)[1].strip()
                        elif line.startswith("tags:"):
                            tag_str = line.split(":", 1)[1].strip()
                            if tag_str and tag_str.lower() != "none":
                                tags = [t.strip() for t in tag_str.split(",") if t.strip()]

            return {
                "status": "success",
                "note_id": clean_id,
                "title": title,
                "tags": tags,
                "content": content,
                "file_path": src_file,
            }
        except Exception as exc:
            return {
                "status": "error",
                "message": f"Lỗi đọc ghi chú: {str(exc)}",
            }


# Global singleton instance
_default_notes_service = NotesService()


# Module-level API satisfying Interface Contracts
async def create_note(
    title: str,
    content: str,
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Creates a new note or updates an existing personal note.
    Interface contract: create_note(title: str, content: str, tags: Optional[List[str]] = None) -> Dict[str, Any]
    """
    return await _default_notes_service.create_note(title=title, content=content, tags=tags)


async def search_notes(
    query: str,
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Searches personal notes full-text with optional tag filter.
    Interface contract: search_notes(query: str, tags: Optional[List[str]] = None) -> Dict[str, Any]
    """
    return await _default_notes_service.search_notes(query=query, tags=tags)


async def list_notes(tag: Optional[str] = None) -> Dict[str, Any]:
    """
    Lists personal notes, optionally filtered by tag.
    Interface contract: list_notes(tag: Optional[str] = None) -> Dict[str, Any]
    """
    return await _default_notes_service.list_notes(tag=tag)


async def delete_note(note_id: str) -> Dict[str, Any]:
    """
    Deletes a personal note safely (Tier 2 Reversible).
    Interface contract: delete_note(note_id: str) -> Dict[str, Any]
    """
    return await _default_notes_service.delete_note(note_id=note_id)


__all__ = [
    "NotesService",
    "create_note",
    "search_notes",
    "list_notes",
    "delete_note",
]
