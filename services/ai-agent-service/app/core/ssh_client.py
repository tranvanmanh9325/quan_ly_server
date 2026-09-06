import asyncio
import logging
import random
import time
from typing import Any, Dict, List, Optional, Tuple

import asyncssh

from app.config import settings
from app.core.security import find_security_violation

logger = logging.getLogger(__name__)

COMMAND_TIMEOUT_SEC = 15
CONNECT_TIMEOUT_SEC = 6
MAX_OUTPUT_CHARS = 1000
DEFAULT_COOLDOWN_SEC = 60.0


class TunnelEndpoint:
    """
    Represents an individual SSH tunnel endpoint (e.g. an Ngrok TCP tunnel)
    with usage tracking, error counting, and adaptive cooldown.
    Mirrors the KeyEntry architecture used in LlmRouter (OpenRouter/Groq).
    """
    __slots__ = (
        "endpoint_id",
        "host",
        "port",
        "name",
        "available_at",
        "usage_count",
        "fail_count",
        "is_dead",
    )

    def __init__(self, endpoint_id: int, host: str, port: int, name: str = ""):
        self.endpoint_id: int = endpoint_id
        self.host: str = host.strip()
        self.port: int = port
        self.name: str = name or f"Ngrok-Tunnel-{endpoint_id} ({self.host}:{self.port})"
        self.available_at: float = 0.0
        self.usage_count: int = 0
        self.fail_count: int = 0
        self.is_dead: bool = False

    def is_available(self, now: float) -> bool:
        """Returns True if the tunnel is healthy and not in cooldown period."""
        return not self.is_dead and now >= self.available_at

    @property
    def is_active(self) -> bool:
        """Returns True if the tunnel is healthy and currently outside cooldown."""
        return self.is_available(time.time())

    def __repr__(self) -> str:
        return f"<TunnelEndpoint #{self.endpoint_id} {self.name} uses={self.usage_count} fails={self.fail_count}>"


class SshTunnelPool:
    """
    Manages a pool of SSH tunnel endpoints with:
    - Least-Used / Round-Robin load balancing.
    - Adaptive Cooldown on failure (default 60s + jitter).
    - Seamless zero-downtime failover across active tunnels.
    - Thread-safe / AsyncIO-safe locking.
    """

    def __init__(self, endpoints: Optional[List[TunnelEndpoint]] = None):
        self.endpoints: List[TunnelEndpoint] = endpoints or []
        self._lock = asyncio.Lock()
        self.total_requests: int = 0
        self.total_failovers: int = 0

    @classmethod
    def from_endpoints(cls, endpoint_tuples: List[Tuple[str, int]]) -> "SshTunnelPool":
        """Creates an SshTunnelPool from a list of (host, port) tuples."""
        eps: List[TunnelEndpoint] = []
        for idx, (host, port) in enumerate(endpoint_tuples):
            eps.append(
                TunnelEndpoint(
                    endpoint_id=idx + 1,
                    host=host,
                    port=port,
                    name=f"Account-{idx + 1} ({host}:{port})",
                )
            )
        return cls(eps)

    @property
    def has_endpoints(self) -> bool:
        return len(self.endpoints) > 0

    @property
    def total_count(self) -> int:
        return len(self.endpoints)

    @property
    def active_count(self) -> int:
        now = time.time()
        return sum(1 for ep in self.endpoints if ep.is_available(now))

    async def get_candidate_endpoints(self) -> List[TunnelEndpoint]:
        """
        Returns an ordered list of endpoints to try for a connection attempt.
        1. Available endpoints (now >= available_at), sorted by usage_count ASC (Least-Used).
        2. In-cooldown endpoints as fallback, sorted by available_at ASC (earliest first).
        """
        async with self._lock:
            now = time.time()
            usable = [ep for ep in self.endpoints if not ep.is_dead]
            if not usable:
                return []

            available = [ep for ep in usable if ep.is_available(now)]
            # Prioritize least-used tunnel to balance quota across accounts
            available.sort(key=lambda ep: ep.usage_count)

            in_cooldown = [ep for ep in usable if not ep.is_available(now)]
            in_cooldown.sort(key=lambda ep: ep.available_at)

            return available + in_cooldown

    async def mark_success(self, endpoint: TunnelEndpoint):
        """Records successful command execution on the tunnel and resets fail counter."""
        async with self._lock:
            endpoint.usage_count += 1
            endpoint.fail_count = 0
            self.total_requests += 1

    async def mark_failed(self, endpoint: TunnelEndpoint, cooldown_seconds: float = DEFAULT_COOLDOWN_SEC):
        """
        Puts tunnel into adaptive cooldown with random jitter (0.9x to 1.1x).
        Increments fail_count and pool failover metrics.
        """
        async with self._lock:
            endpoint.fail_count += 1
            jitter = random.uniform(0.9, 1.1)
            duration = cooldown_seconds * jitter
            endpoint.available_at = time.time() + duration
            self.total_failovers += 1
            logger.warning(
                "[SSH Pool] Tunnel #%d (%s:%d) hit connection failure. Cooldown: %.1fs (fail_count=%d)",
                endpoint.endpoint_id,
                endpoint.host,
                endpoint.port,
                duration,
                endpoint.fail_count,
            )

    def get_status(self) -> Dict[str, Any]:
        """Returns diagnostic status of the tunnel pool."""
        now = time.time()
        return {
            "total_tunnels": len(self.endpoints),
            "active_tunnels": sum(1 for ep in self.endpoints if ep.is_available(now)),
            "total_requests": self.total_requests,
            "total_failovers": self.total_failovers,
            "tunnels": [
                {
                    "id": ep.endpoint_id,
                    "name": ep.name,
                    "host": ep.host,
                    "port": ep.port,
                    "is_available": ep.is_available(now),
                    "cooldown_remaining_sec": max(0.0, round(ep.available_at - now, 1)),
                    "usage_count": ep.usage_count,
                    "fail_count": ep.fail_count,
                    "is_dead": ep.is_dead,
                }
                for ep in self.endpoints
            ],
        }


class SshClient:
    """
    SSH Client with Multi-Tier Connection Architecture:
    1. Primary Tier: Local Area Network (LAN) direct connection for minimal latency (< 2ms).
    2. Fallback Tier: Ngrok Multi-Tunnel Pool with Least-Used rotation, adaptive cooldown,
       and seamless zero-downtime failover (mirrors OpenRouter Multi-Key Pool).
    """

    def __init__(self):
        self.host = settings.SSH_HOST
        self.port = settings.SSH_PORT
        self.user = settings.SSH_USER
        self.password = settings.SSH_PASSWORD
        # Initialize Ngrok Multi-Tunnel Pool from configured fallback endpoints
        self.pool = SshTunnelPool.from_endpoints(settings.ssh_fallback_endpoints)
        logger.info(
            "[SSH] Initialized SshClient (LAN: %s:%d, Pool: %d fallback tunnels)",
            self.host,
            self.port,
            self.pool.total_count,
        )

    async def _execute_on_host(self, host: str, port: int, command: str) -> str:
        """Helper to run a command on a specific host:port endpoint with timeout."""
        timed_cmd = f"timeout {COMMAND_TIMEOUT_SEC} {command}"
        logger.info("[SSH] Executing on %s:%d: %s", host, port, timed_cmd)

        async with asyncssh.connect(
            host,
            port=port,
            username=self.user,
            password=self.password,
            known_hosts=None,
            client_keys=None,
            connect_timeout=CONNECT_TIMEOUT_SEC,
        ) as conn:
            result = await asyncio.wait_for(
                conn.run(timed_cmd, check=False),
                timeout=COMMAND_TIMEOUT_SEC + 5,
            )
            stdout_raw = result.stdout or ""
            stdout_str = stdout_raw.decode("utf-8", errors="replace") if isinstance(stdout_raw, bytes) else stdout_raw

            stderr_raw = result.stderr or ""
            stderr_str = stderr_raw.decode("utf-8", errors="replace") if isinstance(stderr_raw, bytes) else stderr_raw

            stdout = stdout_str.strip()
            stderr = stderr_str.strip()
            output: str = stdout if stdout else stderr

            if not output:
                return "(lệnh không có output hoặc server không phản hồi)"

            if len(output) > MAX_OUTPUT_CHARS:
                output = output[:MAX_OUTPUT_CHARS] + "\n... [output bị cắt ngắn]"

            return output

    async def execute_command(self, command: str) -> str:
        """
        Executes a shell command over SSH with security validation, timeout,
        and automatic multi-tunnel failover.
        """
        violation = find_security_violation(command)
        if violation:
            logger.warning("[SSH] BLOCKED command '%s' — %s", command, violation)
            return (
                f"BLOCKED: Lệnh bị từ chối vì lý do bảo mật ({violation}). "
                "Chỉ được phép dùng các lệnh đọc (ps, docker ps, free, df, cat, date, v.v.)"
            )

        # Tier 1: Try Primary LAN connection first
        lan_error: Optional[Exception] = None
        if self.host:
            try:
                return await self._execute_on_host(self.host, self.port, command)
            except Exception as e:
                lan_error = e
                logger.warning(
                    "[SSH] LAN connection to %s:%d failed (%s). Engaging Ngrok Multi-Tunnel Pool...",
                    self.host,
                    self.port,
                    str(e),
                )

        # Tier 2: Ngrok Multi-Tunnel Pool Failover Rotation
        if not self.pool.has_endpoints:
            err_detail = f": {lan_error}" if lan_error else ""
            return f"Không thể kết nối SSH tới máy chủ (LAN thất bại{err_detail}, không có fallback tunnel)."

        candidates = await self.pool.get_candidate_endpoints()
        last_error: Optional[Exception] = None

        for tunnel in candidates:
            try:
                logger.info(
                    "[SSH] Attempting command on %s (uses=%d, fails=%d)",
                    tunnel.name,
                    tunnel.usage_count,
                    tunnel.fail_count,
                )
                output = await self._execute_on_host(tunnel.host, tunnel.port, command)
                await self.pool.mark_success(tunnel)
                return output
            except Exception as e:
                last_error = e
                await self.pool.mark_failed(tunnel, cooldown_seconds=DEFAULT_COOLDOWN_SEC)
                logger.warning(
                    "[SSH] Tunnel %s failed (%s). Rotating to next tunnel...",
                    tunnel.name,
                    str(e),
                )

        return f"Lỗi SSH khi thực thi lệnh: Tất cả {len(candidates)} tunnels trong bể chứa đều không thể kết nối ({last_error})."
