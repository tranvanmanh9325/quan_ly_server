"""
transfer_storage_manager.py — High-Throughput LAN & WAN File Transfer Storage Lifecycle Manager.

Manages temporary transfer sessions, chunked disk streaming with 1MB aiofiles buffer,
atomic metadata persistence, delayed one-time self-destruction, and 3-Layer Zero-Disk-Leak TTL sweeper:
  1. Layer 1: Periodic Background Sweeper Loop (scheduled via lifespan every 600s).
  2. Layer 2: Instant On-Access Expiry Check (purges expired folder upon access).
  3. Layer 3: Startup Grace Prune (sweeps expired and orphaned folders on server boot).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from dataclasses import dataclass, field
import json
import logging
import mimetypes
import os
from pathlib import Path
import re
import secrets
import shutil
import threading
import time
from typing import Any, AsyncIterator, Dict, Optional, Tuple, Union
import urllib.parse
import urllib.request

import aiofiles

logger = logging.getLogger(__name__)

# Configurable storage root path with fallback to standard /tmp/file_transfers
BASE_TRANSFER_DIR = Path(os.getenv("TRANSFER_STORAGE_DIR", "/tmp/file_transfers"))

# Default TTL configuration (24 hours for transfer sessions)
DEFAULT_TRANSFER_TTL_SECONDS: int = 24 * 3600  # 86400s
DEFAULT_TRANSFER_GRACE_SECONDS: float = 60.0  # 60s grace to prevent race conditions during upload
DEFAULT_ONE_TIME_GRACE_SECONDS: int = 30  # 30s grace for multi-connection downloaders (IDM)

# In-memory cache for auto-discovered public internet base URL
_cached_internet_url: Optional[str] = None
_cached_url_timestamp: float = 0.0
_URL_CACHE_TTL_SECONDS: float = 300.0  # 5 minutes


@dataclass
class TransferRecord:
    """
    Data container representing a high-speed file transfer session.
    """
    token: str
    filename: str
    file_path: Optional[Path]
    file_size: int
    content_type: str
    state: str  # "pending_upload" | "ready" | "expired"
    created_at: float
    expires_at: float
    one_time: bool = False
    download_count: int = 0
    title: str = ""
    mode: str = "upload"  # "upload" | "download"
    ttl_seconds: int = DEFAULT_TRANSFER_TTL_SECONDS
    download_completed: bool = False
    completed_at: Optional[float] = None
    internet_url: str = ""
    lan_url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serializes transfer record to dictionary."""
        return {
            "token": self.token,
            "filename": self.filename,
            "file_path": str(self.file_path) if self.file_path else None,
            "file_size": self.file_size,
            "content_type": self.content_type,
            "state": self.state,
            "title": self.title,
            "mode": self.mode,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "ttl_seconds": self.ttl_seconds,
            "one_time": self.one_time,
            "download_count": self.download_count,
            "download_completed": self.download_completed,
            "completed_at": self.completed_at,
            "internet_url": self.internet_url,
            "lan_url": self.lan_url,
            "time_remaining_seconds": max(0, int(self.expires_at - time.time())),
            "is_expired": time.time() >= self.expires_at,
        }

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at

    @property
    def time_remaining_seconds(self) -> int:
        return max(0, int(self.expires_at - time.time()))


class TransferStorageManager:
    """
    Core storage and lifecycle controller for LAN/WAN file transfer sessions.
    Guarantees Zero-RAM leaks ($O(1) \\le 2$MB buffer per connection) and Zero-Disk leaks.
    """

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        default_ttl_hours: int = 24,
        grace_seconds: float = DEFAULT_TRANSFER_GRACE_SECONDS,
    ):
        self.base_dir = Path(base_dir) if base_dir else BASE_TRANSFER_DIR
        self.default_ttl = default_ttl_hours * 3600
        self.grace_seconds = grace_seconds
        self._cleanup_tasks: Dict[str, asyncio.Task] = {}
        self._token_locks: Dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self.ensure_dirs()

    def _get_token_lock(self, token: str) -> threading.Lock:
        """Retrieves or creates a thread lock for serializing metadata operations per token."""
        with self._locks_guard:
            if token not in self._token_locks:
                self._token_locks[token] = threading.Lock()
            return self._token_locks[token]

    def ensure_dirs(self) -> None:
        """Ensure base transfer directory exists."""
        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            logger.warning("[TransferStorage] Failed to create base directory %s: %s", self.base_dir, exc)

    def _query_host_ngrok_via_ssh(self) -> Optional[str]:
        """
        Executes a curl command on the host via SshClient to fetch tunnels from 127.0.0.1:4040..4044.
        Overcomes Docker bridge network loopback isolation where container cannot directly access host 127.0.0.1.
        """
        try:
            try:
                from app.services.ssh_client import ssh_client
            except ImportError:
                from app.core.ssh_client import SshClient
                ssh_client = SshClient()
        except Exception as exc:
            logger.debug("[TransferStorage] SshClient not available for host discovery: %s", exc)
            return None

        async def _probe() -> Optional[str]:
            for port in [4040, 4041, 4042, 4043, 4044]:
                try:
                    cmd = f"curl -s --max-time 1 http://127.0.0.1:{port}/api/tunnels"
                    out = await ssh_client.execute_command(cmd)
                    if out and out.strip().startswith("{") and "tunnels" in out:
                        data = json.loads(out)
                        for t in data.get("tunnels", []):
                            pub_url = t.get("public_url", "")
                            if pub_url.startswith("https://") and ("ngrok" in pub_url):
                                return pub_url.rstrip("/")
                except Exception:
                    continue
            return None

        try:
            loop = None
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                pass

            if loop is not None and loop.is_running():
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    return executor.submit(lambda: asyncio.run(_probe())).result(timeout=3.5)
            else:
                return asyncio.run(_probe())
        except Exception as exc:
            logger.debug("[TransferStorage] SSH host ngrok probe failed: %s", exc)
            return None

    def resolve_public_transfer_base_url_sync(self) -> Tuple[str, str]:
        """
        Synchronously resolves (internet_base_url, lan_base_url) across 3 tiers:
          1. Tier 1: Static Environment Variable (PUBLIC_DOWNLOAD_BASE_URL or PUBLIC_TRANSFER_BASE_URL).
          2. Tier 2: Ngrok API discovery via candidate ports and SSH probe.
          3. Tier 3: LAN Fallback IP (http://192.168.0.100:8084).
        """
        global _cached_internet_url, _cached_url_timestamp

        lan_base = os.getenv("LAN_TRANSFER_BASE_URL", os.getenv("LAN_DOWNLOAD_BASE_URL", "http://192.168.0.100:8084")).rstrip("/")

        # Tier 0: Testing / CI environment fast bypass
        if (
            os.getenv("TESTING", "").lower() in ("1", "true", "yes")
            or os.getenv("CI", "").lower() in ("1", "true")
        ):
            test_base = os.getenv("PUBLIC_TRANSFER_BASE_URL", os.getenv("PUBLIC_DOWNLOAD_BASE_URL", "http://127.0.0.1:8084")).rstrip("/")
            return test_base, lan_base

        # Tier 1: Static environment variable override
        env_internet = os.getenv("PUBLIC_TRANSFER_BASE_URL", os.getenv("PUBLIC_DOWNLOAD_BASE_URL"))
        if env_internet and env_internet.strip():
            return env_internet.strip().rstrip("/"), lan_base

        # Check in-memory discovery cache (valid for 300 seconds)
        now = time.time()
        if _cached_internet_url and (now - _cached_url_timestamp < _URL_CACHE_TTL_SECONDS):
            return _cached_internet_url, lan_base

        # Tier 2 - Strategy A: Direct HTTP probe on Docker Host candidate IPs and local ports 4040-4044
        candidate_hosts = ["172.17.0.1", "172.18.0.1", "host.docker.internal", "127.0.0.1"]
        candidate_ports = [4040, 4041, 4042, 4043, 4044]
        for host in candidate_hosts:
            for port in candidate_ports:
                url = f"http://{host}:{port}/api/tunnels"
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "TransferStorageManager"})
                    with urllib.request.urlopen(req, timeout=0.5) as resp:
                        if resp.status == 200:
                            data = json.loads(resp.read().decode("utf-8"))
                            for tunnel in data.get("tunnels", []):
                                pub_url = tunnel.get("public_url", "")
                                if pub_url.startswith("https://") and ("ngrok" in pub_url):
                                    _cached_internet_url = pub_url.rstrip("/")
                                    _cached_url_timestamp = now
                                    logger.info(
                                        "[TransferStorage] Auto-discovered active Ngrok tunnel (%s:%d): %s",
                                        host,
                                        port,
                                        _cached_internet_url,
                                    )
                                    return _cached_internet_url, lan_base
                except Exception:
                    continue

        # Tier 2 - Strategy B: Host loopback probe via SshClient
        ssh_discovered = self._query_host_ngrok_via_ssh()
        if ssh_discovered:
            _cached_internet_url = ssh_discovered
            _cached_url_timestamp = now
            logger.info("[TransferStorage] Auto-discovered active Ngrok tunnel via SSH: %s", _cached_internet_url)
            return _cached_internet_url, lan_base

        if _cached_internet_url:
            return _cached_internet_url, lan_base

        # Tier 3: Final Fallback to LAN endpoint
        logger.warning("[TransferStorage] Ngrok discovery failed. Falling back to LAN base URL: %s", lan_base)
        return lan_base, lan_base

    async def resolve_public_transfer_base_url(self) -> Tuple[str, str]:
        """Asynchronous wrapper for base URL discovery."""
        return await asyncio.to_thread(self.resolve_public_transfer_base_url_sync)

    def resolve_urls(self, token: str, filename: Optional[str] = None) -> Tuple[str, str]:
        """
        Constructs full Internet (WAN) and local LAN URLs for downloading/viewing a session.
        """
        internet_base, lan_base = self.resolve_public_transfer_base_url_sync()
        if filename:
            quoted_filename = urllib.parse.quote(filename)
            wan_url = f"{internet_base}/api/ai/transfer/download/{token}/{quoted_filename}"
            lan_url = f"{lan_base}/api/ai/transfer/download/{token}/{quoted_filename}"
        else:
            wan_url = f"{internet_base}/api/ai/transfer/download/{token}"
            lan_url = f"{lan_base}/api/ai/transfer/download/{token}"
        return wan_url, lan_url

    def _validate_token_string(self, token: str) -> None:
        """
        Validates token string strictly against regex to prevent path traversal and injection.
        Matches ^[A-Za-z0-9_-]{16,64}$
        """
        if not token or not isinstance(token, str):
            raise ValueError("Invalid token: token cannot be empty.")
        if not re.match(r"^[A-Za-z0-9_-]{16,64}$", token):
            raise ValueError(f"Invalid token format or invalid characters: {token}")

    def _sanitize_token_dir(self, token: str, must_exist: bool = True) -> Path:
        """
        Safely identifies and returns the isolated token directory within base_dir.
        Uses exact directory enumeration (iterdir) so the returned Path originates purely
        from the local filesystem, containing zero tainted user data and eliminating Path Injection.
        """
        self._validate_token_string(token)
        clean_token = token.strip()

        matched_dir: Optional[Path] = None
        if self.base_dir.is_dir():
            for entry in self.base_dir.iterdir():
                if entry.is_dir() and entry.name == clean_token:
                    matched_dir = entry
                    break
        if matched_dir is None:
            raise FileNotFoundError(f"Transfer session not found or already deleted: {token}")
        return matched_dir

    def _write_metadata_atomic(self, token_dir: Path, meta_dict: Dict[str, Any]) -> None:
        """Writes metadata.json atomically using temporary file replacement protected by token lock."""
        token = token_dir.name
        lock = self._get_token_lock(token)
        with lock:
            base_dir_resolved = str(self.base_dir.resolve())
            token_dir_resolved = str(token_dir.resolve())
            if os.path.commonpath([base_dir_resolved, token_dir_resolved]) != base_dir_resolved:
                raise ValueError("Path containment violation")

            meta_file = (token_dir / "metadata.json").resolve()
            tmp_meta_file = (token_dir / f".metadata.{secrets.token_hex(4)}.tmp").resolve()

            if os.path.commonpath([token_dir_resolved, str(meta_file)]) != token_dir_resolved:
                raise ValueError("Path containment violation")
            if os.path.commonpath([token_dir_resolved, str(tmp_meta_file)]) != token_dir_resolved:
                raise ValueError("Path containment violation")

            with open(tmp_meta_file, "w", encoding="utf-8") as f:
                json.dump(meta_dict, f, indent=2, ensure_ascii=False)
            os.replace(tmp_meta_file, meta_file)

    def _read_metadata(self, token_dir: Path) -> Dict[str, Any]:
        """Reads metadata.json from token directory protected by token lock and retry."""
        token = token_dir.name
        lock = self._get_token_lock(token)

        meta_file: Optional[Path] = None
        if token_dir.is_dir():
            for item in token_dir.iterdir():
                if item.is_file() and item.name == "metadata.json":
                    meta_file = item
                    break

        if meta_file is None:
            raise FileNotFoundError("Session metadata.json missing.")

        for attempt in range(3):
            with lock:
                try:
                    with open(meta_file, "r", encoding="utf-8") as f:
                        return json.load(f)
                except (json.JSONDecodeError, OSError, PermissionError) as exc:
                    if attempt < 2:
                        time.sleep(0.01)
                        continue
                    raise exc
        raise FileNotFoundError("Session metadata.json could not be read.")

    def create_session(
        self,
        filename: Optional[str] = None,
        mode: str = "upload",
        one_time: bool = False,
        ttl_hours: int = 24,
        title: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> TransferRecord:
        """
        Creates a new transfer session:
          1. Generates 256-bit URL-safe token (43 chars).
          2. Creates isolated folder /tmp/file_transfers/{token}/.
          3. Initializes atomic metadata.json.
        """
        self.ensure_dirs()
        token = secrets.token_urlsafe(32)
        token_dir = self.base_dir / token
        token_dir.mkdir(parents=True, exist_ok=True)

        ttl_seconds = max(60, ttl_hours * 3600)
        now = time.time()
        expires_at = now + ttl_seconds

        clean_filename = Path(filename).name.strip() if filename else "unnamed_file"
        detected_content_type = content_type or mimetypes.guess_type(clean_filename)[0] or "application/octet-stream"

        state = "pending_upload" if mode == "upload" else "ready"

        wan_url, lan_url = self.resolve_urls(token, clean_filename if filename else None)

        meta_dict = {
            "token": token,
            "filename": clean_filename,
            "file_size": 0,
            "content_type": detected_content_type,
            "state": state,
            "title": (title or clean_filename).strip(),
            "mode": mode,
            "created_at": now,
            "expires_at": expires_at,
            "ttl_seconds": ttl_seconds,
            "one_time": bool(one_time),
            "download_count": 0,
            "download_completed": False,
            "completed_at": None,
            "internet_url": wan_url,
            "lan_url": lan_url,
        }

        self._write_metadata_atomic(token_dir, meta_dict)

        record = TransferRecord(
            token=token,
            filename=clean_filename,
            file_path=None,
            file_size=0,
            content_type=detected_content_type,
            state=state,
            created_at=now,
            expires_at=expires_at,
            one_time=bool(one_time),
            download_count=0,
            title=meta_dict["title"],
            mode=mode,
            ttl_seconds=ttl_seconds,
            download_completed=False,
            completed_at=None,
            internet_url=wan_url,
            lan_url=lan_url,
        )

        logger.info(
            "[TransferStorage] Created transfer session token=%s, mode=%s, one_time=%s, TTL=%ds",
            token,
            mode,
            one_time,
            ttl_seconds,
        )
        return record

    def get_session(self, token: str) -> Optional[TransferRecord]:
        """
        Retrieves transfer session record with Layer 2 instant on-access expiry check.
        Returns None if session does not exist, is corrupted, or has expired.
        """
        try:
            token_dir = self._sanitize_token_dir(token, must_exist=True)
        except (FileNotFoundError, ValueError):
            return None

        try:
            metadata = self._read_metadata(token_dir)
        except Exception as exc:
            logger.warning("[TransferStorage] Corrupted metadata for token %s (%s). Purging.", token, exc)
            self.delete_session(token)
            return None

        now = time.time()
        expires_at = metadata.get("expires_at", 0)

        # Layer 2: On-Access Expiry Check
        if now >= expires_at:
            logger.info("[TransferStorage] Token %s expired on access (%ds ago). Purging.", token, int(now - expires_at))
            self.delete_session(token)
            return None

        # Locate underlying data file if session is ready
        file_path: Optional[Path] = None
        for item in token_dir.iterdir():
            if item.is_file() and item.name != "metadata.json" and not item.name.startswith("."):
                file_path = item
                break

        return TransferRecord(
            token=token,
            filename=metadata.get("filename", "unknown"),
            file_path=file_path,
            file_size=metadata.get("file_size", file_path.stat().st_size if file_path and file_path.exists() else 0),
            content_type=metadata.get("content_type", "application/octet-stream"),
            state=metadata.get("state", "pending_upload"),
            created_at=metadata.get("created_at", now),
            expires_at=expires_at,
            one_time=metadata.get("one_time", False),
            download_count=metadata.get("download_count", 0),
            title=metadata.get("title", ""),
            mode=metadata.get("mode", "upload"),
            ttl_seconds=metadata.get("ttl_seconds", self.default_ttl),
            download_completed=metadata.get("download_completed", False),
            completed_at=metadata.get("completed_at"),
            internet_url=metadata.get("internet_url", ""),
            lan_url=metadata.get("lan_url", ""),
        )

    async def save_upload_stream(
        self,
        token: str,
        filename: str,
        stream: AsyncIterator[bytes],
        chunk_buffer_size: int = 1024 * 1024,  # Fixed 1MB buffer
    ) -> TransferRecord:
        """
        Receives an uploaded file stream and writes directly to disk with a fixed 1MB aiofiles buffer.
        Ensures O(1) RAM footprint <= 2MB per upload connection, shielding 3.2GB RAM ceiling.
        """
        token_dir = self._sanitize_token_dir(token, must_exist=True)
        metadata = self._read_metadata(token_dir)

        now = time.time()
        if now >= metadata.get("expires_at", 0):
            self.delete_session(token)
            raise FileNotFoundError(f"Transfer session has expired: {token}")

        clean_filename = Path(filename).name.strip() if filename else ""
        clean_filename = os.path.basename(clean_filename.replace("\\", "/"))
        clean_filename = re.sub(r'[\r\n\x00/\\:*?"<>|]', "_", clean_filename).strip(". ")
        if not clean_filename or clean_filename == "metadata.json" or clean_filename.startswith("."):
            clean_filename = metadata.get("filename") or "uploaded_file"
            clean_filename = os.path.basename(clean_filename.replace("\\", "/"))
            clean_filename = re.sub(r'[\r\n\x00/\\:*?"<>|]', "_", clean_filename).strip(". ")
            if not clean_filename or clean_filename == "metadata.json" or clean_filename.startswith("."):
                clean_filename = "uploaded_file"

        token_dir_resolved = str(token_dir.resolve())
        dest_path = (token_dir / clean_filename).resolve()
        dest_resolved = str(dest_path)

        # CodeQL PathSanitizer Barrier check: verify dest_path stays strictly within token_dir
        if os.path.commonpath([token_dir_resolved, dest_resolved]) != token_dir_resolved:
            raise ValueError("Path containment violation")

        # Stream chunked write directly to disk with fixed 1MB buffer
        bytes_written = 0
        async with aiofiles.open(dest_path, "wb") as af:
            buffer = bytearray()
            async for chunk in stream:
                if not chunk:
                    continue
                buffer.extend(chunk)
                while len(buffer) >= chunk_buffer_size:
                    to_write = bytes(buffer[:chunk_buffer_size])
                    del buffer[:chunk_buffer_size]
                    await af.write(to_write)
                    bytes_written += len(to_write)
            if len(buffer) > 0:
                remainder = bytes(buffer)
                await af.write(remainder)
                bytes_written += len(remainder)
                buffer.clear()

        # Update metadata atomically
        detected_content_type = mimetypes.guess_type(clean_filename)[0] or "application/octet-stream"
        wan_url, lan_url = self.resolve_urls(token, clean_filename)

        metadata["filename"] = clean_filename
        metadata["file_size"] = bytes_written
        metadata["content_type"] = detected_content_type
        metadata["state"] = "ready"
        metadata["internet_url"] = wan_url
        metadata["lan_url"] = lan_url

        self._write_metadata_atomic(token_dir, metadata)

        logger.info(
            "[TransferStorage] Stream upload completed for token=%s: file=%s, size=%d bytes",
            token,
            clean_filename,
            bytes_written,
        )

        return TransferRecord(
            token=token,
            filename=clean_filename,
            file_path=dest_path,
            file_size=bytes_written,
            content_type=detected_content_type,
            state="ready",
            created_at=metadata.get("created_at", now),
            expires_at=metadata.get("expires_at", now + self.default_ttl),
            one_time=metadata.get("one_time", False),
            download_count=metadata.get("download_count", 0),
            title=metadata.get("title", clean_filename),
            mode=metadata.get("mode", "upload"),
            ttl_seconds=metadata.get("ttl_seconds", self.default_ttl),
            download_completed=metadata.get("download_completed", False),
            completed_at=metadata.get("completed_at"),
            internet_url=wan_url,
            lan_url=lan_url,
        )

    def register_existing_file(
        self,
        token: str,
        source_path: Union[str, Path],
        filename: Optional[str] = None,
        copy_mode: bool = False,
    ) -> TransferRecord:
        """
        Registers an existing local file into the transfer session (used when Agent publishes a file).
        """
        token_dir = self._sanitize_token_dir(token, must_exist=True)
        metadata = self._read_metadata(token_dir)

        src = Path(source_path).resolve()
        if not src.is_file():
            raise FileNotFoundError(f"Source file not found: {source_path}")

        clean_filename = Path(filename).name.strip() if filename else src.name
        clean_filename = os.path.basename(clean_filename.replace("\\", "/"))
        clean_filename = re.sub(r'[\r\n\x00/\\:*?"<>|]', "_", clean_filename).strip(". ")
        if not clean_filename:
            clean_filename = "file"

        token_dir_resolved = str(token_dir.resolve())
        dest_path = (token_dir / clean_filename).resolve()
        dest_resolved = str(dest_path)

        if os.path.commonpath([token_dir_resolved, dest_resolved]) != token_dir_resolved:
            raise ValueError("Path containment violation")

        if copy_mode:
            shutil.copy2(str(src), str(dest_path))
        else:
            shutil.move(str(src), str(dest_path))

        file_size = dest_path.stat().st_size
        detected_content_type = mimetypes.guess_type(clean_filename)[0] or "application/octet-stream"
        wan_url, lan_url = self.resolve_urls(token, clean_filename)

        metadata["filename"] = clean_filename
        metadata["file_size"] = file_size
        metadata["content_type"] = detected_content_type
        metadata["state"] = "ready"
        metadata["internet_url"] = wan_url
        metadata["lan_url"] = lan_url

        self._write_metadata_atomic(token_dir, metadata)

        return TransferRecord(
            token=token,
            filename=clean_filename,
            file_path=dest_path,
            file_size=file_size,
            content_type=detected_content_type,
            state="ready",
            created_at=metadata.get("created_at", time.time()),
            expires_at=metadata.get("expires_at", time.time() + self.default_ttl),
            one_time=metadata.get("one_time", False),
            download_count=metadata.get("download_count", 0),
            title=metadata.get("title", clean_filename),
            mode=metadata.get("mode", "download"),
            ttl_seconds=metadata.get("ttl_seconds", self.default_ttl),
            download_completed=metadata.get("download_completed", False),
            completed_at=metadata.get("completed_at"),
            internet_url=wan_url,
            lan_url=lan_url,
        )

    def get_file_path(self, token: str) -> Optional[Path]:
        """Returns the Path to the stored file in the session, or None."""
        session = self.get_session(token)
        if not session or session.state != "ready":
            return None
        return session.file_path

    def get_download_file(self, token: str, increment_count: bool = True) -> Tuple[Path, TransferRecord]:
        """
        Retrieves file path and metadata for client download with Layer 2 on-access check.
        Optionally increments download_count atomically.
        """
        token_dir = self._sanitize_token_dir(token, must_exist=True)
        try:
            metadata = self._read_metadata(token_dir)
        except Exception as exc:
            logger.warning("[TransferStorage] Failed reading metadata for %s: %s", token, exc)
            raise FileNotFoundError(f"Corrupt or inaccessible metadata for token: {token}") from exc

        now = time.time()
        expires_at = metadata.get("expires_at", 0)

        # Layer 2 On-Access Check
        if now >= expires_at:
            self.delete_session(token)
            raise FileNotFoundError(f"Transfer session has expired: {token}")

        # Check session upload state before checking file existence
        state = metadata.get("state", "pending_upload")
        if state == "pending_upload":
            raise FileNotFoundError(f"File upload is pending for token: {token}")
        if state != "ready":
            raise FileNotFoundError(f"File is not ready for download (state={state}) for token: {token}")

        # Locate file
        file_path: Optional[Path] = None
        for item in token_dir.iterdir():
            if item.is_file() and item.name != "metadata.json" and not item.name.startswith("."):
                file_path = item
                break

        if file_path is None or not file_path.is_file():
            self.delete_session(token)
            raise FileNotFoundError(f"Underlying transfer file missing for token: {token}")

        if increment_count:
            metadata["download_count"] = metadata.get("download_count", 0) + 1
            try:
                self._write_metadata_atomic(token_dir, metadata)
            except Exception as exc:
                logger.warning("[TransferStorage] Failed updating download_count for %s: %s", token, exc)

        record = TransferRecord(
            token=token,
            filename=metadata.get("filename", file_path.name),
            file_path=file_path,
            file_size=metadata.get("file_size", file_path.stat().st_size),
            content_type=metadata.get("content_type", "application/octet-stream"),
            state=metadata.get("state", "ready"),
            created_at=metadata.get("created_at", now),
            expires_at=expires_at,
            one_time=metadata.get("one_time", False),
            download_count=metadata.get("download_count", 1),
            title=metadata.get("title", file_path.name),
            mode=metadata.get("mode", "upload"),
            ttl_seconds=metadata.get("ttl_seconds", self.default_ttl),
            download_completed=metadata.get("download_completed", False),
            completed_at=metadata.get("completed_at"),
            internet_url=metadata.get("internet_url", ""),
            lan_url=metadata.get("lan_url", ""),
        )

        return file_path, record

    def schedule_delayed_cleanup(self, token: str, delay_seconds: int = DEFAULT_ONE_TIME_GRACE_SECONDS) -> None:
        """
        Schedules a delayed session deletion for one_time=True sessions.
        Grace period (default 30s) prevents breaking concurrent connections from accelerated downloaders (IDM).
        """
        existing_task = self._cleanup_tasks.get(token)
        if existing_task and not existing_task.done():
            existing_task.cancel()

        async def _delayed_task():
            try:
                logger.info(
                    "[TransferStorage] One-time delayed cleanup scheduled for token=%s in %ds",
                    token,
                    delay_seconds,
                )
                await asyncio.sleep(delay_seconds)
                deleted = self.delete_session(token)
                logger.info("[TransferStorage] One-time delayed cleanup executed for token=%s (deleted=%s)", token, deleted)
            except asyncio.CancelledError:
                logger.debug("[TransferStorage] Delayed cleanup task cancelled for token=%s", token)
            except Exception as exc:
                logger.error("[TransferStorage] Error during delayed cleanup for token=%s: %s", token, exc)
            finally:
                self._cleanup_tasks.pop(token, None)

        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(_delayed_task())
            self._cleanup_tasks[token] = task
        except RuntimeError:
            logger.debug("[TransferStorage] No running loop for delayed cleanup; relying on sweep_expired fallback.")

    def delete_session(self, token: str) -> bool:
        """
        Permanently purges a transfer session directory and removes any scheduled tasks.
        Guarantees 100% Zero-Disk-Leak.
        """
        task = self._cleanup_tasks.pop(token, None)
        if task and not task.done():
            task.cancel()

        try:
            token_dir = self._sanitize_token_dir(token, must_exist=True)
            base_resolved = str(self.base_dir.resolve())
            token_resolved = str(token_dir.resolve())
            if os.path.commonpath([base_resolved, token_resolved]) == base_resolved and token_resolved != base_resolved:
                shutil.rmtree(token_dir, ignore_errors=True)
                logger.info("[TransferStorage] Purged session directory for token=%s", token)
                return True
        except FileNotFoundError:
            return False
        except Exception as exc:
            logger.warning("[TransferStorage] Failed deleting session %s: %s", token, exc)
        finally:
            with self._locks_guard:
                self._token_locks.pop(token, None)
        return False

    def sweep_expired(self) -> Dict[str, Any]:
        """
        Layer 1 & Layer 3: Comprehensive sweeper across transfer storage directory.
          - Removes sessions where now >= expires_at.
          - Removes directories with corrupt or missing metadata that exceed grace period (60s).
        Returns execution statistics dict.
        """
        self.ensure_dirs()
        now = time.time()
        expired_tokens_removed: int = 0
        corrupt_tokens_removed: int = 0
        bytes_freed: int = 0

        if not self.base_dir.exists() or not self.base_dir.is_dir():
            return {
                "expired_tokens_removed": 0,
                "corrupt_tokens_removed": 0,
                "freed_mb": 0.0,
                "bytes_freed": 0,
            }

        for item in list(self.base_dir.iterdir()):
            if not item.is_dir() or item.name.startswith("."):
                continue

            token_name = item.name
            meta_file = item / "metadata.json"

            if not meta_file.is_file():
                try:
                    dir_age = now - item.stat().st_ctime
                except Exception:
                    dir_age = self.grace_seconds + 10

                if dir_age > self.grace_seconds:
                    folder_size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
                    shutil.rmtree(item, ignore_errors=True)
                    corrupt_tokens_removed += 1
                    bytes_freed += folder_size
                    logger.info("[TransferStorage] Pruned orphaned token folder without metadata: %s", token_name)
                continue

            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                folder_size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
                shutil.rmtree(item, ignore_errors=True)
                corrupt_tokens_removed += 1
                bytes_freed += folder_size
                logger.info("[TransferStorage] Pruned folder with corrupt metadata: %s", token_name)
                continue

            expires_at = meta.get("expires_at", 0)
            if now >= expires_at:
                folder_size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
                shutil.rmtree(item, ignore_errors=True)
                expired_tokens_removed += 1
                bytes_freed += folder_size
                logger.info(
                    "[TransferStorage] Swept expired session %s (expired %ds ago, freed %d bytes)",
                    token_name,
                    int(now - expires_at),
                    folder_size,
                )

        freed_mb = round(bytes_freed / (1024 * 1024), 2)
        return {
            "expired_tokens_removed": expired_tokens_removed,
            "corrupt_tokens_removed": corrupt_tokens_removed,
            "freed_mb": freed_mb,
            "bytes_freed": bytes_freed,
        }


# Global singleton instance
transfer_storage_manager = TransferStorageManager()
