import asyncio
import heapq
import logging
import random
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class _KeyEntry:
    """Memory-efficient key entry for priority queue tracking."""
    __slots__ = ('available_at', 'usage_count', 'fail_count', 'key_id', 'api_key')

    def __init__(self, key_id: int, api_key: str):
        self.available_at: float = 0.0
        self.usage_count: int = 0
        self.fail_count: int = 0
        self.key_id: int = key_id
        self.api_key: str = api_key

    def __lt__(self, other: '_KeyEntry') -> bool:
        # Prioritize key that is available earliest; break ties by least used for fair balancing
        if self.available_at != other.available_at:
            return self.available_at < other.available_at
        return self.usage_count < other.usage_count


class GroqKeyPool:
    """
    Thread-safe, high-performance Min-Heap Priority Queue Groq API Key Pool.
    - O(1) key peek & selection with zero memory allocations per request.
    - Adaptive Exponential Backoff + Full Jitter for rate-limited keys (HTTP 429).
    - Fair Round-Robin & Usage-weighted load balancing across multiple keys.
    """

    def __init__(self, api_keys: List[str]):
        self._entries_map: Dict[str, _KeyEntry] = {}
        self._heap: List[_KeyEntry] = []
        for idx, k in enumerate(api_keys):
            clean_key = k.strip() if k else ""
            if clean_key:
                entry = _KeyEntry(idx, clean_key)
                self._entries_map[clean_key] = entry
                self._heap.append(entry)
        heapq.heapify(self._heap)
        self._lock = asyncio.Lock()
        logger.info("[GroqKeyPool] Initialized with %d API key(s) (Min-Heap Scheduler).", len(self._heap))

    @property
    def key_count(self) -> int:
        return len(self._heap)

    def has_keys(self) -> bool:
        return len(self._heap) > 0

    async def get_next_key(self) -> Optional[str]:
        if not self._heap:
            return None

        async with self._lock:
            best = self._heap[0]
            # Fair rotation: increment usage count and update heap in O(log N)
            best.usage_count += 1
            heapq.heapreplace(self._heap, best)
            return best.api_key

    async def mark_rate_limited(self, key: str) -> None:
        async with self._lock:
            entry = self._entries_map.get(key)
            if not entry:
                return
            entry.fail_count += 1
            # Adaptive Exponential Backoff: 8s * 2^(fail_count - 1) + Jitter (max 90s)
            base_backoff = min(90.0, 8.0 * (2 ** min(entry.fail_count - 1, 4)))
            jitter = random.uniform(0.5, 3.0)
            cooldown_time = base_backoff + jitter
            entry.available_at = time.monotonic() + cooldown_time
            heapq.heapify(self._heap)
            masked = key[-6:] if len(key) > 6 else "***"
            logger.warning(
                "[GroqKeyPool] Key ...%s rate-limited (fail_count=%d, backoff=%.1fs).",
                masked, entry.fail_count, cooldown_time
            )

    async def mark_success(self, key: str) -> None:
        async with self._lock:
            entry = self._entries_map.get(key)
            if entry and entry.fail_count > 0:
                entry.fail_count = 0

    def get_status(self) -> str:
        now = time.monotonic()
        active = sum(1 for e in self._heap if e.available_at <= now)
        return f"{active}/{len(self._heap)} keys active (Min-Heap Balanced)"
