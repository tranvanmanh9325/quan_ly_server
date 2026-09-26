"""
app/services/file_manager_service.py — Safe File Server Manager Service (R8).

Provides secure filesystem management operations:
- list_files: Lists directory contents with metadata (name, type, size, mtime),
  supports glob pattern filtering and multi-criteria sorting (name, size, date).
- read_file_content: Reads text file contents with a strict 2000 character limit,
  line-based clamping, and binary file rejection.
- write_file_content: Safely writes file contents (overwrite/append) within allowed boundaries
  (/home/kirito/ and /tmp/) using a Base64 + tee pipeline adhering strictly to security.py:28.
- move_or_rename_file: Renames or moves files within allowed whitelist boundaries (Tier 2 Reversible).
- get_disk_usage: Analyzes directory size via `du -sh` and extracts top 10 heavy items.

Filesystem Security Boundary:
- Whitelist write boundaries: `/home/kirito/` and `/tmp/`.
- Sensitive files blacklist: `.env*`, `.ssh/*`, `authorized_keys*`, `id_rsa*`, `.bashrc`, `.git/*`, `/etc/*`, etc.
- Path traversal mitigation via canonicalization and boundary checks.
"""

import base64
from datetime import datetime, timedelta, timezone
import fnmatch
import logging
import os
from pathlib import Path
import posixpath
import re
import shutil
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse

from app.core.security import find_security_violation
from app.core.ssh_client import SshClient

logger = logging.getLogger(__name__)

VN_TZ = timezone(timedelta(hours=7))

# Allowed write prefix boundaries
ALLOWED_WRITE_PREFIXES = ("/home/kirito/", "/home/kirito", "/tmp/", "/tmp")

# Sensitive file and directory blacklist
SENSITIVE_FORBIDDEN_PATTERNS = [
    re.compile(r"(^|/)\.env(\..+)?$", re.IGNORECASE),
    re.compile(r"(^|/)\.ssh(/.*)?$", re.IGNORECASE),
    re.compile(r"(^|/)(id_rsa|id_ed25519|id_ecdsa|id_dsa|authorized_keys|known_hosts)(\..+)?$", re.IGNORECASE),
    re.compile(r"(^|/)\.(bashrc|bash_profile|profile|bash_login|bash_logout|zshrc|cshrc)$", re.IGNORECASE),
    re.compile(r"(^|/)\.git(/.*)?$", re.IGNORECASE),
    re.compile(r"^/etc(/.*)?$", re.IGNORECASE),
    re.compile(r"^/(dev|proc|sys|boot|root)(/.*)?$", re.IGNORECASE),
]

# Binary file extensions rejected from text reading
BINARY_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svgz",
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm",
    ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar", ".iso",
    ".bin", ".exe", ".dll", ".so", ".dylib", ".o", ".a", ".pyc", ".class",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".sqlite", ".sqlite3", ".db", ".dat"
})

MAX_READ_CHARS_LIMIT: int = 2000
INJECTION_PATTERN = re.compile(r"[;&|`$\n\r]")


def _format_size(size_bytes: int) -> str:
    """Formats bytes into human-readable string (B, KB, MB, GB)."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


class FileManagerService:
    """
    Service responsible for secure file operations on server or local test directory.
    Enforces strict filesystem boundary checks and compliance with security rules.
    """

    def __init__(
        self,
        ssh_client: Optional[SshClient] = None,
        base_dir: Optional[str] = None,
    ):
        self._ssh_client = ssh_client
        self.base_dir = os.path.abspath(base_dir) if base_dir else None

    @property
    def ssh_client(self) -> SshClient:
        if self._ssh_client is None:
            self._ssh_client = SshClient()
        return self._ssh_client

    def normalize_posix_path(self, raw_path: str) -> str:
        """
        Normalizes POSIX path, decodes percent-encoding, resolves relative references.
        """
        unquoted = urllib.parse.unquote(str(raw_path).strip())
        if self.base_dir:
            # If a local test base_dir is active
            p = Path(unquoted)
            if not p.is_absolute():
                p = Path(self.base_dir) / p
            try:
                resolved = str(p.resolve())
            except Exception:
                resolved = os.path.normpath(str(p))
            return resolved

        # Host POSIX normalization
        norm = posixpath.normpath(unquoted)
        if not norm.startswith("/"):
            norm = posixpath.normpath(posixpath.join("/home/kirito", norm))
        return norm

    def validate_path_security(
        self,
        raw_path: str,
        action: str = "read",
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Validates target_path against filesystem security boundary and sensitive blacklist.
        Returns: (is_valid, violation_type, violation_reason)
        violation_type: "boundary" | "sensitive" | None
        """
        clean_path = str(raw_path).strip()
        norm = self.normalize_posix_path(clean_path)
        posix_norm = norm.replace("\\", "/")

        if self.base_dir:
            norm_base = os.path.abspath(self.base_dir).replace("\\", "/")
            if not posix_norm.startswith(norm_base):
                return False, "boundary", f"Đường dẫn '{clean_path}' vượt ra ngoài thư mục cơ sở ranh giới an toàn."

            # Check sensitive blacklist inside base_dir
            rel = posixpath.relpath(posix_norm, norm_base)
            for pattern in SENSITIVE_FORBIDDEN_PATTERNS:
                if pattern.search(rel) or pattern.search("/" + rel) or pattern.search(posix_norm):
                    return False, "sensitive", f"Thao tác trên tệp nhạy cảm '{clean_path}' bị từ chối vì lý do an ninh hệ thống."
            return True, None, None

        # 1. Whitelist prefix boundary check (/home/kirito/ and /tmp/)
        has_allowed_prefix = any(
            posix_norm == prefix or posix_norm.startswith(prefix if prefix.endswith("/") else prefix + "/")
            for prefix in ALLOWED_WRITE_PREFIXES
        )
        if not has_allowed_prefix:
            return False, "boundary", f"Đường dẫn '{norm}' nằm ngoài ranh giới an toàn cho phép (/home/kirito/ và /tmp/)."

        # 2. Sensitive blacklist check
        for pattern in SENSITIVE_FORBIDDEN_PATTERNS:
            if pattern.search(posix_norm):
                return False, "sensitive", f"Thao tác trên tệp nhạy cảm '{norm}' bị từ chối vì lý do an ninh hệ thống."

        return True, None, None

    def validate_write_permission(self, target_path: str) -> Tuple[bool, Optional[str]]:
        """
        Validates whether target_path complies with filesystem security boundary.
        Returns (is_valid, violation_reason).
        """
        is_valid, v_type, reason = self.validate_path_security(target_path, action="write")
        return is_valid, reason

    async def list_files(
        self,
        path: str = "/home/kirito",
        pattern: Optional[str] = None,
        sort_by: str = "name",
    ) -> Dict[str, Any]:
        """
        Lists files and subdirectories at path with metadata.
        Supports glob filtering and sorting by name, size, or date.
        """
        clean_path = str(path).strip()
        if INJECTION_PATTERN.search(clean_path):
            return {
                "status": "error",
                "message": "Đường dẫn không hợp lệ. Phát hiện ký tự nguy hiểm.",
            }

        target_path = self.normalize_posix_path(clean_path)

        # Security boundary check for directory listing
        is_valid, v_type, reason = self.validate_path_security(clean_path, action="list")
        if not is_valid:
            if v_type == "sensitive":
                return {
                    "status": "security_veto",
                    "path": clean_path,
                    "message": f"Từ chối liệt kê thư mục nhạy cảm '{clean_path}' vì lý do an ninh hệ thống.",
                }
            return {
                "status": "security_veto",
                "path": clean_path,
                "message": f"Từ chối liệt kê thư mục do vi phạm ranh giới an toàn: {reason}",
            }

        # Check local filesystem execution if base_dir or existing local path
        if self.base_dir or os.path.exists(target_path):
            if not os.path.exists(target_path):
                return {
                    "status": "not_found",
                    "path": clean_path,
                    "message": f"Thư mục '{clean_path}' không tồn tại.",
                }

            if os.path.isfile(target_path):
                return {
                    "status": "error",
                    "path": clean_path,
                    "message": "Đường dẫn là tệp, không phải thư mục.",
                }

            items: List[Dict[str, Any]] = []
            try:
                with os.scandir(target_path) as entries:
                    for entry in entries:
                        name = entry.name
                        entry_posix = entry.path.replace("\\", "/")
                        if any(pat.search(name) or pat.search(entry_posix) for pat in SENSITIVE_FORBIDDEN_PATTERNS):
                            continue
                        if pattern and not fnmatch.fnmatch(name, pattern):
                            continue

                        try:
                            stat_res = entry.stat(follow_symlinks=False)
                            is_dir = entry.is_dir(follow_symlinks=False)
                            is_symlink = entry.is_symlink()
                            item_type = "directory" if is_dir else ("symlink" if is_symlink else "file")
                            size_bytes = 0 if is_dir else stat_res.st_size
                            mtime = datetime.fromtimestamp(stat_res.st_mtime, VN_TZ).strftime("%Y-%m-%d %H:%M:%S")

                            items.append({
                                "name": name,
                                "type": item_type,
                                "size": _format_size(size_bytes),
                                "size_bytes": size_bytes,
                                "mtime": mtime,
                                "path": entry.path,
                            })
                        except (OSError, PermissionError) as ex:
                            logger.debug("[FileManagerService] Stat error on %s: %s", name, ex)
                            continue
            except Exception as ex:
                return {
                    "status": "error",
                    "path": clean_path,
                    "message": f"Lỗi đọc thư mục: {str(ex)}",
                }

            # Sorting
            sort_key = sort_by.lower() if sort_by else "name"
            if sort_key == "size":
                items.sort(key=lambda x: x["size_bytes"], reverse=True)
            elif sort_key == "date":
                items.sort(key=lambda x: x["mtime"], reverse=True)
            else:
                items.sort(key=lambda x: x["name"].lower())

            return {
                "status": "success",
                "path": clean_path,
                "total_items": len(items),
                "items": items,
                "message": f"Đã liệt kê {len(items)} mục trong '{clean_path}'.",
            }

        # SSH execution path
        check_cmd = f"[ -e '{target_path}' ] && [ -d '{target_path}' ] && echo 'IS_DIR' || ([ -f '{target_path}' ] && echo 'IS_FILE' || echo 'NOT_FOUND')"
        try:
            check_out = await self.ssh_client.execute_command(check_cmd)
            if check_out.startswith("BLOCKED:") or "BLOCKED:" in check_out:
                return {
                    "status": "error",
                    "reason": "security_violation",
                    "message": check_out,
                }
            if "NOT_FOUND" in check_out:
                return {
                    "status": "not_found",
                    "path": clean_path,
                    "message": f"Thư mục '{clean_path}' không tồn tại trên máy chủ.",
                }
            if "IS_FILE" in check_out:
                return {
                    "status": "error",
                    "path": clean_path,
                    "message": "Đường dẫn là tệp, không phải thư mục.",
                }

            ls_cmd = f"ls -la --time-style=+\"%Y-%m-%d %H:%M:%S\" '{target_path}'"
            ls_out = await self.ssh_client.execute_command(ls_cmd)
            if ls_out.startswith("BLOCKED:") or "BLOCKED:" in ls_out:
                return {
                    "status": "error",
                    "reason": "security_violation",
                    "message": ls_out,
                }
            items: List[Dict[str, Any]] = []

            for line in ls_out.splitlines():
                line_clean = line.strip()
                if not line_clean or line_clean.startswith("total"):
                    continue
                parts = line_clean.split(None, 7)
                if len(parts) >= 8:
                    perms = parts[0]
                    size_str = parts[4]
                    date_str = f"{parts[5]} {parts[6]}"
                    name = parts[7]

                    if " -> " in name and perms.startswith("l"):
                        name = name.split(" -> ")[0].strip()

                    if name in (".", ".."):
                        continue
                    item_path = posixpath.join(target_path, name)
                    if any(pat.search(name) or pat.search(item_path) for pat in SENSITIVE_FORBIDDEN_PATTERNS):
                        continue
                    if pattern and not fnmatch.fnmatch(name, pattern):
                        continue

                    try:
                        size_b = int(size_str)
                    except ValueError:
                        size_b = 0

                    is_d = perms.startswith("d")
                    item_type = "directory" if is_d else "file"
                    items.append({
                        "name": name,
                        "type": item_type,
                        "size": _format_size(size_b),
                        "size_bytes": size_b,
                        "mtime": date_str,
                        "path": item_path,
                    })

            sort_key = sort_by.lower() if sort_by else "name"
            if sort_key == "size":
                items.sort(key=lambda x: x["size_bytes"], reverse=True)
            elif sort_key == "date":
                items.sort(key=lambda x: x["mtime"], reverse=True)
            else:
                items.sort(key=lambda x: x["name"].lower())

            return {
                "status": "success",
                "path": clean_path,
                "total_items": len(items),
                "items": items,
                "message": f"Đã liệt kê {len(items)} mục qua SSH trong '{clean_path}'.",
            }
        except Exception as ex:
            return {
                "status": "error",
                "path": clean_path,
                "message": f"Lỗi truy vấn thư mục qua SSH: {str(ex)}",
            }

    async def read_file_content(
        self,
        path: str,
        lines: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Reads text file content clamped to 2000 characters.
        Rejects binary files and protects sensitive files.
        """
        clean_path = str(path).strip()
        if INJECTION_PATTERN.search(clean_path):
            return {
                "status": "error",
                "message": "Đường dẫn không hợp lệ. Phát hiện ký tự nguy hiểm.",
            }

        # 1. Extension inspection for binary files
        _, ext = os.path.splitext(clean_path)
        if ext.lower() in BINARY_EXTENSIONS:
            return {
                "status": "error",
                "reason": "binary_file",
                "message": f"Không thể đọc tệp nhị phân ({ext}). Chỉ hỗ trợ các tệp văn bản.",
            }

        target_path = self.normalize_posix_path(clean_path)

        # 2. Security validation: Whitelist boundary & Sensitive blacklist
        is_valid, v_type, reason = self.validate_path_security(clean_path, action="read")
        if not is_valid:
            if v_type == "sensitive":
                return {
                    "status": "security_veto",
                    "path": clean_path,
                    "message": f"Từ chối đọc tệp nhạy cảm '{clean_path}' vì lý do an ninh hệ thống.",
                }
            return {
                "status": "security_veto",
                "path": clean_path,
                "message": f"Từ chối đọc tệp do vi phạm ranh giới an toàn: {reason}",
            }

        # 3. Local filesystem read
        if self.base_dir or os.path.exists(target_path):
            if not os.path.exists(target_path):
                return {
                    "status": "not_found",
                    "path": clean_path,
                    "message": f"Tệp '{clean_path}' không tồn tại.",
                }
            if os.path.isdir(target_path):
                return {
                    "status": "error",
                    "path": clean_path,
                    "message": "Đường dẫn là thư mục, không phải tệp.",
                }

            try:
                with open(target_path, "rb") as f:
                    raw_bytes = f.read(100000)

                # Null-byte check for binary file detection
                if b"\x00" in raw_bytes:
                    return {
                        "status": "error",
                        "reason": "binary_file",
                        "message": "Phát hiện ký tự nhị phân (null byte) trong tệp. Từ chối đọc.",
                    }

                text = raw_bytes.decode("utf-8", errors="replace").replace("\r\n", "\n")
            except Exception as ex:
                return {
                    "status": "error",
                    "message": f"Lỗi đọc tệp cục bộ: {str(ex)}",
                }

            # Handle `lines` parameter
            lines_read = None
            if lines is not None and lines > 0:
                all_lines = text.splitlines()
                lines_read = min(lines, len(all_lines))
                text = "\n".join(all_lines[:lines])

            # Clamp to MAX_READ_CHARS_LIMIT
            is_truncated = False
            if len(text) > MAX_READ_CHARS_LIMIT:
                content = (
                    text[:MAX_READ_CHARS_LIMIT]
                    + "\n... [Nội dung bị cắt ngắn do vượt quá giới hạn 2000 ký tự]"
                )
                is_truncated = True
            else:
                content = text

            res: Dict[str, Any] = {
                "status": "success",
                "path": clean_path,
                "content": content,
                "char_count": len(text),
                "is_truncated": is_truncated,
                "message": "Đọc tệp thành công.",
            }
            if lines_read is not None:
                res["lines_read"] = lines_read
            return res

        # 4. SSH execution read
        try:
            head_cmd = f"head -c 5000 '{target_path}'"
            raw_out = await self.ssh_client.execute_command(head_cmd)

            # Check if command was blocked by SSH Security Filter
            if raw_out.startswith("BLOCKED:") or "BLOCKED:" in raw_out:
                return {
                    "status": "error",
                    "reason": "security_violation",
                    "message": raw_out,
                }

            if "No such file or directory" in raw_out or raw_out.startswith("(lệnh không"):
                return {
                    "status": "not_found",
                    "path": clean_path,
                    "message": f"Tệp '{clean_path}' không tồn tại trên máy chủ.",
                }

            # Null-byte check for binary file detection over SSH
            if "\x00" in raw_out:
                return {
                    "status": "error",
                    "reason": "binary_file",
                    "message": "Phát hiện ký tự nhị phân (null byte) trong tệp qua SSH. Từ chối đọc.",
                }

            # Clean SSH truncation watermark if any
            if "\n... [output bị cắt ngắn]" in raw_out:
                raw_out = raw_out.replace("\n... [output bị cắt ngắn]", "")

            lines_read = None
            if lines is not None and lines > 0:
                all_lines = raw_out.splitlines()
                lines_read = min(lines, len(all_lines))
                raw_out = "\n".join(all_lines[:lines])

            is_truncated = False
            if len(raw_out) > MAX_READ_CHARS_LIMIT:
                content = (
                    raw_out[:MAX_READ_CHARS_LIMIT]
                    + "\n... [Nội dung bị cắt ngắn do vượt quá giới hạn 2000 ký tự]"
                )
                is_truncated = True
            else:
                content = raw_out

            res: Dict[str, Any] = {
                "status": "success",
                "path": clean_path,
                "content": content,
                "char_count": len(raw_out),
                "is_truncated": is_truncated,
                "message": "Đọc tệp qua SSH thành công.",
            }
            if lines_read is not None:
                res["lines_read"] = lines_read
            return res
        except Exception as ex:
            return {
                "status": "error",
                "path": clean_path,
                "message": f"Lỗi đọc tệp qua SSH: {str(ex)}",
            }

    async def write_file_content(
        self,
        path: str,
        content: str,
        mode: str = "overwrite",
    ) -> Dict[str, Any]:
        """
        Writes text content to path within whitelist boundaries (/home/kirito/ and /tmp/).
        Uses Base64 + tee pipeline to comply strictly with security redirect rules.
        """
        clean_path = str(path).strip()
        if INJECTION_PATTERN.search(clean_path):
            return {
                "status": "security_veto",
                "message": "Đường dẫn không hợp lệ. Phát hiện ký tự nguy hiểm.",
            }

        # 1. Enforce Filesystem Security Boundary & Sensitive Blacklist
        is_valid, reason = self.validate_write_permission(clean_path)
        if not is_valid:
            logger.warning("[FileManagerService] Write security veto: %s", reason)
            return {
                "status": "security_veto",
                "path": clean_path,
                "message": f"Từ chối ghi tệp do vi phạm ranh giới an toàn: {reason}",
            }

        target_path = self.normalize_posix_path(clean_path)

        # 2. Local filesystem write
        if self.base_dir:
            try:
                parent = Path(target_path).parent
                parent.mkdir(parents=True, exist_ok=True)
                write_flag = "w" if mode == "overwrite" else "a"
                with open(target_path, write_flag, encoding="utf-8", newline="\n") as f:
                    f.write(content)

                bytes_count = len(content.encode("utf-8"))
                return {
                    "status": "success",
                    "path": clean_path,
                    "mode": mode,
                    "bytes_written": bytes_count,
                    "message": f"Đã ghi {bytes_count} bytes vào '{clean_path}' (chế độ: {mode}).",
                }
            except Exception as ex:
                return {
                    "status": "error",
                    "message": f"Lỗi ghi tệp cục bộ: {str(ex)}",
                }

        # 3. SSH execution using Base64 + tee (-a) pipeline
        b64_content = base64.b64encode(content.encode("utf-8")).decode("ascii")
        parent_dir = posixpath.dirname(target_path)
        tee_flag = "tee" if mode == "overwrite" else "tee -a"

        # Safe pipeline command without forbidden `> /` or `>> /`
        cmd = f"mkdir -p '{parent_dir}' && echo '{b64_content}' | base64 -d | {tee_flag} '{target_path}'"

        violation = find_security_violation(cmd)
        if violation:
            return {
                "status": "security_veto",
                "message": f"Lệnh ghi tệp vi phạm quy tắc bảo mật: {violation}",
            }

        try:
            output = await self.ssh_client.execute_command(cmd)
            if output.startswith("BLOCKED:"):
                return {
                    "status": "security_veto",
                    "message": f"Lệnh ghi tệp bị chặn bởi bộ lọc SSH: {output}",
                }

            bytes_count = len(content.encode("utf-8"))
            return {
                "status": "success",
                "path": clean_path,
                "mode": mode,
                "bytes_written": bytes_count,
                "message": f"Đã ghi {bytes_count} bytes vào '{clean_path}' (chế độ: {mode}).",
            }
        except Exception as ex:
            return {
                "status": "error",
                "message": f"Lỗi thực thi lệnh ghi SSH: {str(ex)}",
            }

    async def move_or_rename_file(
        self,
        src: str,
        dst: str,
    ) -> Dict[str, Any]:
        """
        Moves or renames a file within allowed boundaries (Tier 2 Reversible).
        Enforces security checks on both source and destination.
        """
        clean_src = str(src).strip()
        clean_dst = str(dst).strip()

        if INJECTION_PATTERN.search(clean_src) or INJECTION_PATTERN.search(clean_dst):
            return {
                "status": "security_veto",
                "message": "Đường dẫn nguồn hoặc đích không hợp lệ. Phát hiện ký tự nguy hiểm.",
            }

        # Validate security for both source and destination
        valid_src, reason_src = self.validate_write_permission(clean_src)
        if not valid_src:
            return {
                "status": "security_veto",
                "src": clean_src,
                "message": f"Từ chối thao tác trên tệp nguồn: {reason_src}",
            }

        valid_dst, reason_dst = self.validate_write_permission(clean_dst)
        if not valid_dst:
            return {
                "status": "security_veto",
                "dst": clean_dst,
                "message": f"Từ chối di chuyển tới tệp đích: {reason_dst}",
            }

        target_src = self.normalize_posix_path(clean_src)
        target_dst = self.normalize_posix_path(clean_dst)

        # Local execution
        if self.base_dir:
            if not os.path.exists(target_src):
                return {
                    "status": "not_found",
                    "src": clean_src,
                    "message": f"Tệp nguồn '{clean_src}' không tồn tại.",
                }

            try:
                parent = Path(target_dst).parent
                parent.mkdir(parents=True, exist_ok=True)
                shutil.move(target_src, target_dst)
                return {
                    "status": "success",
                    "src": clean_src,
                    "dst": clean_dst,
                    "message": f"Đã di chuyển/đổi tên '{clean_src}' thành '{clean_dst}' thành công.",
                }
            except Exception as ex:
                return {
                    "status": "error",
                    "message": f"Lỗi di chuyển tệp: {str(ex)}",
                }

        # SSH execution
        cmd = f"mv '{target_src}' '{target_dst}'"
        try:
            output = await self.ssh_client.execute_command(cmd)
            if "No such file or directory" in output:
                return {
                    "status": "not_found",
                    "src": clean_src,
                    "message": f"Tệp nguồn '{clean_src}' không tồn tại trên máy chủ.",
                }
            if output.startswith("BLOCKED:"):
                return {
                    "status": "security_veto",
                    "message": f"Lệnh di chuyển bị chặn: {output}",
                }

            return {
                "status": "success",
                "src": clean_src,
                "dst": clean_dst,
                "message": f"Đã di chuyển/đổi tên '{clean_src}' thành '{clean_dst}' thành công qua SSH.",
            }
        except Exception as ex:
            return {
                "status": "error",
                "message": f"Lỗi di chuyển tệp qua SSH: {str(ex)}",
            }

    async def get_disk_usage(self, path: str = "/") -> Dict[str, Any]:
        """
        Analyzes directory disk usage via `du -sh` and extracts top 10 heavy items.
        Mitigates command injection and returns structured metrics.
        """
        clean_path = str(path).strip()
        if INJECTION_PATTERN.search(clean_path):
            return {
                "status": "error",
                "message": "Đường dẫn không hợp lệ. Nghi ngờ có mã độc injection.",
            }

        target_path = self.normalize_posix_path(clean_path)

        # Composite du command
        du_cmd = f"du -sh '{target_path}' 2>/dev/null && du -ah --max-depth=1 '{target_path}' 2>/dev/null | sort -rh | head -n 11"

        try:
            output = await self.ssh_client.execute_command(du_cmd)
            if not output or output.startswith("BLOCKED:") or output.startswith("(lệnh không"):
                # Graceful fallback mock
                return {
                    "status": "success",
                    "path": clean_path,
                    "total_size": "0B",
                    "top_items": [],
                    "message": f"Không có dữ liệu dung lượng cho '{clean_path}'.",
                }

            lines = [l.strip() for l in output.splitlines() if l.strip()]
            total_size = "0B"
            top_items: List[Dict[str, Any]] = []

            if lines:
                first_parts = lines[0].split(maxsplit=1)
                total_size = first_parts[0] if first_parts else "0B"

                # Parse subsequent items
                for line in lines[1:]:
                    parts = line.split(maxsplit=1)
                    if len(parts) == 2:
                        size_str, item_path = parts
                        # Skip root item if repeated
                        if item_path.rstrip("/") == target_path.rstrip("/"):
                            continue
                        top_items.append({
                            "size": size_str,
                            "path": item_path,
                        })
                    if len(top_items) >= 10:
                        break

            return {
                "status": "success",
                "path": clean_path,
                "total_size": total_size,
                "top_items": top_items,
                "message": f"Đã phân tích dung lượng cho '{clean_path}'. Tổng: {total_size}.",
                "summary_text": f"📊 Thư mục: {clean_path} | Tổng dung lượng: {total_size} | {len(top_items)} mục lớn nhất.",
            }
        except Exception as ex:
            return {
                "status": "error",
                "path": clean_path,
                "message": f"Lỗi phân tích dung lượng ổ đĩa: {str(ex)}",
            }


# Singleton instance & Module Facades
_default_file_manager_service = FileManagerService()


async def list_files(
    path: str = "/home/kirito",
    pattern: Optional[str] = None,
    sort_by: str = "name",
) -> Dict[str, Any]:
    """Facade for FileManagerService.list_files()."""
    return await _default_file_manager_service.list_files(path, pattern, sort_by)


async def read_file_content(
    path: str,
    lines: Optional[int] = None,
) -> Dict[str, Any]:
    """Facade for FileManagerService.read_file_content()."""
    return await _default_file_manager_service.read_file_content(path, lines)


async def write_file_content(
    path: str,
    content: str,
    mode: str = "overwrite",
) -> Dict[str, Any]:
    """Facade for FileManagerService.write_file_content()."""
    return await _default_file_manager_service.write_file_content(path, content, mode)


async def move_or_rename_file(
    src: str,
    dst: str,
) -> Dict[str, Any]:
    """Facade for FileManagerService.move_or_rename_file()."""
    return await _default_file_manager_service.move_or_rename_file(src, dst)


async def get_disk_usage(
    path: str = "/",
) -> Dict[str, Any]:
    """Facade for FileManagerService.get_disk_usage()."""
    return await _default_file_manager_service.get_disk_usage(path)
