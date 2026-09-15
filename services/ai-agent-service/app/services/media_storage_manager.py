"""
media_storage_manager.py — High-Performance Media Storage Lifecycle & Direct Download Manager.

Manages public download links and enforces a 3-Layer Zero-Disk-Leak TTL Sweeper:
  1. Layer 1: Periodic Lifespan Sweeper Loop (background task sweeping every 10m).
  2. Layer 2: Instant On-Access Expiry Check (purges expired token folder upon GET request).
  3. Layer 3: Startup Grace Prune (sweeps orphaned temporary and expired files on app launch).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import re
import secrets
import shutil
import time
from typing import Any, Dict, List, Optional, Tuple, Union
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

# Configurable storage root path with fallback to standard /tmp overlayfs
BASE_MEDIA_DIR = Path(os.getenv("MEDIA_STORAGE_DIR", "/tmp/media_downloads"))
TEMP_MEDIA_DIR = BASE_MEDIA_DIR / "temp"
PUBLIC_MEDIA_DIR = BASE_MEDIA_DIR / "public"

# Default TTL configuration (4 hours for public download links; 10 minutes for transient temp parts)
DEFAULT_TTL_SECONDS: int = 4 * 3600  # 14400 seconds (4 hours)
DEFAULT_TEMP_MAX_AGE_SECONDS: int = 600  # 600 seconds (10 minutes)
DEFAULT_GRACE_SECONDS: float = 60.0  # 60 seconds grace period to prevent sweep race conditions

# In-memory cache for auto-discovered public internet base URL
_cached_internet_url: Optional[str] = None
_cached_url_timestamp: float = 0.0
_URL_CACHE_TTL_SECONDS: float = 300.0  # 5 minutes


@dataclass
class DownloadRecord:
    """
    Data container representing a published direct server download item.
    """
    token: str
    filename: str
    file_path: Path
    file_size: int
    title: str
    duration: int
    created_at: float
    expires_at: float
    download_count: int = 0
    internet_url: str = ""
    lan_url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "token": self.token,
            "filename": self.filename,
            "file_path": str(self.file_path),
            "file_size": self.file_size,
            "title": self.title,
            "duration": self.duration,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "download_count": self.download_count,
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


class MediaStorageManager:
    """
    Core storage and lifecycle controller for public direct download files.
    """

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        temp_dir: Optional[Path] = None,
        public_dir: Optional[Path] = None,
        default_ttl: int = DEFAULT_TTL_SECONDS,
        temp_max_age: int = DEFAULT_TEMP_MAX_AGE_SECONDS,
        grace_seconds: float = DEFAULT_GRACE_SECONDS,
    ):
        self.base_dir = Path(base_dir) if base_dir else BASE_MEDIA_DIR
        self.temp_dir = Path(temp_dir) if temp_dir else (self.base_dir / "temp")
        self.public_dir = Path(public_dir) if public_dir else (self.base_dir / "public")
        self.default_ttl = default_ttl
        self.temp_max_age = temp_max_age
        self.grace_seconds = grace_seconds
        self.ensure_dirs()

    def ensure_dirs(self) -> None:
        """Ensure transient temp and public storage directories exist."""
        try:
            self.temp_dir.mkdir(parents=True, exist_ok=True)
            self.public_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            logger.warning("[MediaStorage] Failed to create directories %s: %s", self.base_dir, exc)

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
            logger.debug("[MediaStorage] SshClient not available for host discovery: %s", exc)
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
            logger.debug("[MediaStorage] SSH host ngrok probe failed: %s", exc)
            return None

    def resolve_public_download_base_url_sync(self) -> Tuple[str, str]:
        """
        Synchronously resolves (internet_base_url, lan_base_url) across 3 tiers:
          1. Tier 1: Static Environment Variable (PUBLIC_DOWNLOAD_BASE_URL).
          2. Tier 2: Ngrok API discovery:
             - Step 2A: Direct probe on Docker host candidate IPs & ports 4040-4044 (timeout=0.5s).
             - Step 2B: Fallback SSH probe querying host loopback via SshClient.
             - Caches discovered URL for 300 seconds.
          3. Tier 3: LAN Fallback IP (http://192.168.0.100:5173).
        """
        global _cached_internet_url, _cached_url_timestamp

        lan_base = os.getenv("LAN_DOWNLOAD_BASE_URL", "http://192.168.0.100:5173").rstrip("/")

        # Tier 0: Testing / CI environment fast bypass (avoids SSH & Ngrok network probe latencies)
        if (
            os.getenv("TESTING", "").lower() in ("1", "true", "yes")
            or os.getenv("CI", "").lower() in ("1", "true")
        ):
            test_base = os.getenv("PUBLIC_DOWNLOAD_BASE_URL", "http://127.0.0.1:8084").rstrip("/")
            return test_base, lan_base

        # Tier 1: Static environment variable override takes precedence
        env_internet = os.getenv("PUBLIC_DOWNLOAD_BASE_URL")
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
                    req = urllib.request.Request(url, headers={"User-Agent": "MediaStorageManager"})
                    with urllib.request.urlopen(req, timeout=0.5) as resp:
                        if resp.status == 200:
                            data = json.loads(resp.read().decode("utf-8"))
                            for tunnel in data.get("tunnels", []):
                                pub_url = tunnel.get("public_url", "")
                                if pub_url.startswith("https://") and ("ngrok" in pub_url):
                                    _cached_internet_url = pub_url.rstrip("/")
                                    _cached_url_timestamp = now
                                    logger.info(
                                        "[MediaStorage] Auto-discovered active Ngrok tunnel via HTTP probe (%s:%d): %s",
                                        host,
                                        port,
                                        _cached_internet_url,
                                    )
                                    return _cached_internet_url, lan_base
                except Exception:
                    continue

        # Tier 2 - Strategy B: Host loopback probe via SshClient (bypasses Docker bridge isolation)
        ssh_discovered = self._query_host_ngrok_via_ssh()
        if ssh_discovered:
            _cached_internet_url = ssh_discovered
            _cached_url_timestamp = now
            logger.info("[MediaStorage] Auto-discovered active Ngrok tunnel via SSH host query: %s", _cached_internet_url)
            return _cached_internet_url, lan_base

        # If previous cache exists (even if older than TTL), reuse as graceful degradation
        if _cached_internet_url:
            return _cached_internet_url, lan_base

        # Tier 3: Final Fallback to LAN endpoint
        logger.warning("[MediaStorage] Ngrok auto-discovery failed on all tiers. Falling back to LAN base URL: %s", lan_base)
        return lan_base, lan_base

    async def resolve_public_download_base_url(self) -> Tuple[str, str]:
        """
        Asynchronous wrapper for base URL discovery, executing sync I/O in worker thread.
        """
        return await asyncio.to_thread(self.resolve_public_download_base_url_sync)

    def publish_download_item(
        self,
        file_path: Union[str, Path],
        filename: str,
        title: str,
        duration: int = 0,
        ttl_seconds: Optional[int] = None,
    ) -> DownloadRecord:
        """
        Publishes a finished media file for direct HTTP download:
          1. Generates cryptographic URL-safe token.
          2. Creates dedicated isolated folder /tmp/media_downloads/public/{token}/.
          3. Moves file using atomic/zero-copy filesystem inode move (< 1ms).
          4. Persists metadata.json for state resilience across restarts.
          5. Generates public Internet (Ngrok) and local LAN URLs.
        """
        self.ensure_dirs()
        src_path = Path(file_path).resolve()
        if not src_path.exists() or not src_path.is_file():
            raise FileNotFoundError(f"Source media file not found for publishing: {file_path}")

        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl

        # Generate 256-bit cryptographically secure token (43 URL-safe characters)
        token = secrets.token_urlsafe(32)
        token_dir = self.public_dir / token
        token_dir.mkdir(parents=True, exist_ok=True)

        # Sanitize target filename to prevent path traversal injections
        clean_name = Path(filename).name.strip()
        if not clean_name:
            clean_name = src_path.name
        dest_path = token_dir / clean_name

        # Zero-copy inode transfer within same filesystem partition (< 1ms execution)
        shutil.move(str(src_path), str(dest_path))

        file_size = dest_path.stat().st_size
        now = time.time()
        expires_at = now + ttl

        meta_dict = {
            "token": token,
            "filename": clean_name,
            "file_path": str(dest_path),
            "file_size": file_size,
            "title": title.strip() if title else clean_name,
            "duration": duration,
            "created_at": now,
            "expires_at": expires_at,
            "download_count": 0,
        }

        # Write metadata.json atomically using tempfile replacement
        meta_file = token_dir / "metadata.json"
        tmp_meta_file = token_dir / f".metadata.{secrets.token_hex(4)}.tmp"
        with open(tmp_meta_file, "w", encoding="utf-8") as f:
            json.dump(meta_dict, f, indent=2, ensure_ascii=False)
        os.replace(tmp_meta_file, meta_file)

        # Resolve public download links
        internet_base, lan_base = self.resolve_public_download_base_url_sync()
        url_quoted_name = urllib.parse.quote(clean_name)
        internet_url = f"{internet_base}/api/ai/media/download/{token}/{url_quoted_name}"
        lan_url = f"{lan_base}/api/ai/media/download/{token}/{url_quoted_name}"

        record = DownloadRecord(
            token=token,
            filename=clean_name,
            file_path=dest_path,
            file_size=file_size,
            title=meta_dict["title"],
            duration=duration,
            created_at=now,
            expires_at=expires_at,
            download_count=0,
            internet_url=internet_url,
            lan_url=lan_url,
        )

        logger.info(
            "[MediaStorage] Published item token=%s, size=%d bytes, TTL=%ds, target=%s",
            token,
            file_size,
            ttl,
            dest_path.name,
        )
        return record

    def _validate_token_string(self, token: str) -> None:
        """
        Validates token string characters strictly against regex to block path traversal.
        """
        if not token or not isinstance(token, str):
            raise FileNotFoundError("Invalid token: token cannot be empty.")
        if not re.match(r"^[A-Za-z0-9_-]{16,64}$", token):
            raise FileNotFoundError(f"Invalid token format or invalid characters: {token}")

    def _sanitize_token_dir(self, token: str) -> Path:
        """
        Validates token format and safely locates isolated token directory within public_dir.
        Uses exact directory enumeration (iterdir) so the returned Path originates purely
        from the local filesystem, containing zero tainted user data and eliminating Path Injection.
        """
        self._validate_token_string(token)
        clean_token = token.strip()
        matched_dir: Optional[Path] = None
        if self.public_dir.is_dir():
            for entry in self.public_dir.iterdir():
                if entry.is_dir() and entry.name == clean_token:
                    matched_dir = entry
                    break
        if matched_dir is None:
            raise FileNotFoundError(f"Download record not found or already deleted: {token}")
        return matched_dir

    def get_download_file(self, token: str) -> Tuple[Path, Dict[str, Any]]:
        """
        Retrieves file path and metadata for client download:
          - Validates token against path traversal via local filesystem enumeration.
          - Checks TTL. If expired: immediately triggers Layer 2 instant cleanup and raises FileNotFoundError.
          - Increments download_count on valid download.
        """
        token_dir = self._sanitize_token_dir(token)

        meta_file: Optional[Path] = None
        for item in token_dir.iterdir():
            if item.is_file() and item.name == "metadata.json":
                meta_file = item
                break

        if meta_file is None or not meta_file.is_file():
            raise FileNotFoundError(f"Download record not found or already deleted: {token}")

        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        except Exception as exc:
            # Corrupted metadata files are treated as expired to guarantee Zero-Disk-Leak
            logger.warning("[MediaStorage] Corrupt metadata for token %s (%s). Purging folder.", token, exc)
            shutil.rmtree(token_dir, ignore_errors=True)
            raise FileNotFoundError(f"Corrupt metadata for token: {token}")

        now = time.time()
        expires_at = metadata.get("expires_at", 0)

        # Layer 2 Defense: Instant On-Access Expiry Check
        if now >= expires_at:
            shutil.rmtree(token_dir, ignore_errors=True)
            logger.info(
                "[MediaStorage] Token %s expired on access (expired %ds ago). Folder purged immediately.",
                token,
                int(now - expires_at),
            )
            raise FileNotFoundError(f"Download token has expired: {token}")

        # Locate media file strictly via local directory enumeration
        media_file: Optional[Path] = None
        for item in token_dir.iterdir():
            if item.is_file() and item.name != "metadata.json" and not item.name.startswith("."):
                media_file = item
                break

        if media_file is None or not media_file.is_file():
            shutil.rmtree(token_dir, ignore_errors=True)
            raise FileNotFoundError(f"Underlying media file missing from storage for token: {token}")

        file_path = media_file

        # Increment download counter atomically in background
        metadata["download_count"] = metadata.get("download_count", 0) + 1
        try:
            tmp_meta_file = token_dir / f".metadata.{secrets.token_hex(4)}.tmp"
            with open(tmp_meta_file, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            os.replace(tmp_meta_file, meta_file)
        except Exception as exc:
            logger.warning("[MediaStorage] Failed updating download_count for token %s: %s", token, exc)

        return file_path, metadata

    def get_download_file_info(self, token: str) -> Tuple[Path, Dict[str, Any]]:
        """
        Retrieves metadata and verifies TTL without incrementing the download counter.
        """
        token_dir = self._sanitize_token_dir(token)

        meta_file: Optional[Path] = None
        for item in token_dir.iterdir():
            if item.is_file() and item.name == "metadata.json":
                meta_file = item
                break

        if meta_file is None or not meta_file.is_file():
            raise FileNotFoundError(f"Download record not found or already deleted: {token}")

        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        except Exception as exc:
            shutil.rmtree(token_dir, ignore_errors=True)
            raise FileNotFoundError(f"Corrupt metadata for token: {token}")

        now = time.time()
        expires_at = metadata.get("expires_at", 0)

        # Layer 2 Defense: Instant On-Access Expiry Check
        if now >= expires_at:
            shutil.rmtree(token_dir, ignore_errors=True)
            logger.info("[MediaStorage] Info query on expired token %s. Purged folder.", token)
            raise FileNotFoundError(f"Download token has expired: {token}")

        media_file: Optional[Path] = None
        for item in token_dir.iterdir():
            if item.is_file() and item.name != "metadata.json" and not item.name.startswith("."):
                media_file = item
                break

        file_path = media_file if media_file is not None else (token_dir / "media.mp4")
        return file_path, metadata

    def sweep_expired(self) -> Dict[str, Any]:
        """
        Sweeps expired items across public and temporary directories:
          1. Public directory: removes token folders where now >= expires_at or metadata is invalid.
          2. Temp directory: removes orphaned files/folders older than temp_max_age (600s).
        Guarantees 100% Zero-Disk-Leak.
        """
        self.ensure_dirs()
        now = time.time()
        expired_tokens_removed: int = 0
        temp_files_removed: int = 0
        bytes_freed: int = 0

        # 1. Sweep expired public download folders
        if self.public_dir.exists():
            for item in list(self.public_dir.iterdir()):
                if not item.is_dir():
                    continue

                meta_file = item / "metadata.json"
                is_expired = False

                if not meta_file.is_file():
                    # Check 60s grace period to prevent race conditions during publish
                    try:
                        mtime = item.stat().st_mtime
                        if (now - mtime) < self.grace_seconds:
                            continue  # Ân hạn 60 giây, không xóa oan file vừa move
                    except Exception:
                        pass
                    is_expired = True
                else:
                    try:
                        with open(meta_file, "r", encoding="utf-8") as f:
                            meta = json.load(f)
                        if now >= meta.get("expires_at", 0):
                            is_expired = True
                    except Exception:
                        # Corrupted or unreadable metadata: also check 60s grace period
                        try:
                            mtime = item.stat().st_mtime
                            if (now - mtime) < self.grace_seconds:
                                continue  # Ân hạn 60 giây nếu metadata đang được ghi
                        except Exception:
                            pass
                        is_expired = True

                if is_expired:
                    # Calculate disk space to record exact metrics
                    item_bytes = 0
                    for root, _, files in os.walk(item):
                        for file_name in files:
                            try:
                                item_bytes += os.path.getsize(os.path.join(root, file_name))
                            except Exception:
                                pass
                    shutil.rmtree(item, ignore_errors=True)
                    expired_tokens_removed += 1
                    bytes_freed += item_bytes
                    logger.debug("[MediaStorage] Swept expired token folder: %s (%d bytes)", item.name, item_bytes)

        # 2. Sweep orphaned temporary working files
        if self.temp_dir.exists():
            for item in list(self.temp_dir.iterdir()):
                try:
                    stat = item.stat()
                    # If file or folder has been untouched longer than threshold, sweep it
                    if (now - stat.st_mtime) >= self.temp_max_age:
                        item_bytes = 0
                        if item.is_file():
                            item_bytes = stat.st_size
                            item.unlink(missing_ok=True)
                        elif item.is_dir():
                            for root, _, files in os.walk(item):
                                for file_name in files:
                                    try:
                                        item_bytes += os.path.getsize(os.path.join(root, file_name))
                                    except Exception:
                                        pass
                            shutil.rmtree(item, ignore_errors=True)
                        temp_files_removed += 1
                        bytes_freed += item_bytes
                        logger.debug("[MediaStorage] Swept orphaned temp item: %s (%d bytes)", item.name, item_bytes)
                except Exception as exc:
                    logger.warning("[MediaStorage] Failed checking temp item %s: %s", item, exc)

        freed_mb = round(bytes_freed / (1024 * 1024), 2)
        result = {
            "expired_tokens_removed": expired_tokens_removed,
            "temp_files_removed": temp_files_removed,
            "bytes_freed": bytes_freed,
            "freed_mb": freed_mb,
        }
        if expired_tokens_removed > 0 or temp_files_removed > 0:
            logger.info("[MediaStorage] Sweep completed: %s", result)
        return result


# Global singleton instance for app-wide use
media_storage_manager = MediaStorageManager()
