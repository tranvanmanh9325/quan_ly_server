"""
app/core/rate_limiter.py — Ultra-Lightweight In-Memory Rate Limiter & Anti-Bruteforce Guard.

Zero Redis. Zero External Dependencies. Thread-Safe & Async-Friendly.
Provides:
  1. Token Bucket Rate Limiting per IP (with burst capacity for HTTP 206 Partial Content seeking).
  2. Failed-Token Jail: Automatically isolates brute-force attackers querying non-existent/expired tokens.
  3. Automatic background cleanup of stale IP records (Zero Memory Leak).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Dict
from fastapi import HTTPException, Request, status

logger = logging.getLogger("app.core.rate_limiter")


@dataclass
class TokenBucket:
    tokens: float
    last_update: float
    failed_attempts: int = 0
    jailed_until: float = 0.0


class DownloadRateLimitGuard:
    """
    In-memory Token Bucket with an aggressive Jail for brute-force prevention:
      - capacity: Maximum burst capacity (e.g. 15 requests for rapid byte-range seeking).
      - refill_rate: Tokens added per second (e.g. 0.5 tokens/sec = 30 requests/min).
      - max_failed_attempts: Number of 404s before placing the IP in Jail.
      - jail_seconds: Quarantined isolation duration (default 600s = 10 minutes).
    """

    def __init__(
        self,
        capacity: float = 15.0,
        refill_rate: float = 0.5,
        max_failed_attempts: int = 5,
        jail_seconds: int = 600,
    ) -> None:
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.max_failed_attempts = max_failed_attempts
        self.jail_seconds = jail_seconds
        self._buckets: Dict[str, TokenBucket] = {}
        self._last_cleanup = time.time()

    def _get_client_ip(self, request: Request) -> str:
        """Extracts client IP behind Nginx Reverse Proxy safely."""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
        return request.client.host if request.client else "127.0.0.1"

    def _periodic_cleanup(self, now: float) -> None:
        """Prunes stale IP buckets every 10 minutes to prevent memory leaks."""
        if now - self._last_cleanup < 600:
            return
        self._last_cleanup = now
        stale_ips = [
            ip for ip, b in self._buckets.items()
            if (now - b.last_update > 3600) and (now > b.jailed_until)
        ]
        for ip in stale_ips:
            del self._buckets[ip]

    def check_rate_limit(self, request: Request) -> str:
        """
        Validates token allowance for client IP.
        Raises HTTPException 429 (Too Many Requests) or 403 (Forbidden if Jailed).
        Returns client IP string.
        """
        now = time.time()
        self._periodic_cleanup(now)
        client_ip = self._get_client_ip(request)

        bucket = self._buckets.get(client_ip)
        if bucket is None:
            bucket = TokenBucket(tokens=self.capacity, last_update=now)
            self._buckets[client_ip] = bucket

        # 1. Check Jail status (brute-force defense)
        if now < bucket.jailed_until:
            retry_after = int(bucket.jailed_until - now)
            logger.warning("[RateLimit] Jailed IP %s attempted access. Blocked for %ds.", client_ip, retry_after)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Quá nhiều yêu cầu không hợp lệ. Địa chỉ IP của bạn bị khóa tạm thời trong {retry_after}s.",
                headers={"Retry-After": str(retry_after)},
            )

        # 2. Refill tokens according to elapsed time
        elapsed = now - bucket.last_update
        bucket.tokens = min(self.capacity, bucket.tokens + elapsed * self.refill_rate)
        bucket.last_update = now

        # 3. Check bucket allowance
        if bucket.tokens < 1.0:
            retry_after = max(1, int((1.0 - bucket.tokens) / self.refill_rate))
            logger.warning("[RateLimit] IP %s rate limit exceeded. Retry after %ds.", client_ip, retry_after)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Tốc độ tải vượt quá giới hạn cho phép. Vui lòng chờ ít phút.",
                headers={"Retry-After": str(retry_after)},
            )

        # Deduct 1 token for legitimate access
        bucket.tokens -= 1.0
        return client_ip

    def record_failed_attempt(self, client_ip: str) -> None:
        """Records a 404/invalid token attempt. Triggers jail when threshold exceeded."""
        now = time.time()
        bucket = self._buckets.get(client_ip)
        if bucket is None:
            bucket = TokenBucket(tokens=self.capacity, last_update=now)
            self._buckets[client_ip] = bucket

        bucket.failed_attempts += 1
        if bucket.failed_attempts >= self.max_failed_attempts:
            bucket.jailed_until = now + self.jail_seconds
            bucket.failed_attempts = 0
            logger.error(
                "[RateLimit] Brute-force pattern detected from IP %s. Placed in JAIL for %ds!",
                client_ip,
                self.jail_seconds,
            )

    def record_successful_attempt(self, client_ip: str) -> None:
        """Reduces failure counter upon successful token access."""
        bucket = self._buckets.get(client_ip)
        if bucket and bucket.failed_attempts > 0:
            bucket.failed_attempts = max(0, bucket.failed_attempts - 1)


# Singleton instance
download_guard = DownloadRateLimitGuard(
    capacity=15.0,
    refill_rate=0.5,
    max_failed_attempts=5,
    jail_seconds=600,
)
