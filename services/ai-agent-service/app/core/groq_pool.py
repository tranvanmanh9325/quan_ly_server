import asyncio
import logging
import time
from typing import Dict, List, Optional
import httpx

logger = logging.getLogger(__name__)

COOLDOWN_SECONDS = 60.0


class GroqKeyPool:
    """
    Thread-safe, asyncio-aware Groq API Key Pool with 9router-style smart rotation.
    - Selects healthy keys via round-robin.
    - Places rate-limited keys (HTTP 429) on a 60s cooldown timer.
    - Seamlessly falls back to the next available key without pausing.
    """

    def __init__(self, api_keys: List[str]):
        self._keys: List[str] = [k for k in api_keys if k and k.strip()]
        self._index: int = 0
        self._cooldowns: Dict[str, float] = {}
        self._lock = asyncio.Lock()
        logger.info("[GroqKeyPool] Initialized with %d API key(s).", len(self._keys))

    @property
    def key_count(self) -> int:
        return len(self._keys)

    def has_keys(self) -> bool:
        return len(self._keys) > 0

    async def get_next_key(self) -> Optional[str]:
        if not self._keys:
            return None

        async with self._lock:
            now = time.monotonic()
            # Clean expired cooldowns
            self._cooldowns = {k: exp for k, exp in self._cooldowns.items() if exp > now}

            # Search round-robin for first key not in cooldown
            for _ in range(len(self._keys)):
                key = self._keys[self._index % len(self._keys)]
                self._index += 1
                if key not in self._cooldowns:
                    return key

            # If all keys are in cooldown, pick the one that expires soonest
            logger.warn("[GroqKeyPool] All keys currently rate-limited; picking soonest available.")
            soonest_key = min(self._cooldowns.keys(), key=lambda k: self._cooldowns[k])
            return soonest_key

    async def mark_rate_limited(self, key: str) -> None:
        async with self._lock:
            self._cooldowns[key] = time.monotonic() + COOLDOWN_SECONDS
            masked = key[-6:] if len(key) > 6 else "***"
            logger.warning("[GroqKeyPool] Key ...%s marked rate-limited (cooldown %ds).", masked, int(COOLDOWN_SECONDS))

    def get_status(self) -> str:
        now = time.monotonic()
        active = sum(1 for k in self._keys if self._cooldowns.get(k, 0) <= now)
        return f"{active}/{len(self._keys)} keys active"
