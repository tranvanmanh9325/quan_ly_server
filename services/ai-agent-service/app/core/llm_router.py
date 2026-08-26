import asyncio
import heapq
import json
import logging
import random
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx
import psycopg

from app.config import settings

logger = logging.getLogger(__name__)


# ─── RTK (Reduction Token Killer) Compressor ─────────────────────────────────

class RtkCompressor:
    """
    9Router RTK (Reduction Token Killer) Engine.
    High-performance, semantic-preserving prompt & tool output compressor for LLMs:
    
    1. Strips ANSI VT100/Xterm terminal color and cursor escape codes.
    2. Minifies un-formatted multiline JSON payloads into compact single-line representations.
    3. Trims repeated divider lines (dashes, equals, asterisks, hashes) to standard length.
    4. Compacts excessive whitespace in tabular outputs (collapsing 3+ spaces to 2),
       preserving column structure while eliminating massive token waste.
    5. Normalizes log timestamps and collapses consecutive blank lines.
    6. Intelligent Head-Tail sampling for large tables, process lists, and terminal logs.
    7. Accurate accounting: strictly increments compression count only when tokens are actually saved.
    """

    # 1. ANSI & VT100 Terminal Escape Codes
    ANSI_REGEX = re.compile(
        r"(?:\x1B[@-Z\\-_]|[\x80-\x9A\x9C-\x9F]|(?:\x1B\[|\x9B)[0-?]*[ -/]*[@-~])"
    )
    # 2. Excessive space padding in tables/logs (3+ spaces -> 2 spaces)
    TABLE_GAP_REGEX = re.compile(r"[ \t]{3,}")
    # 3. Repeated divider lines (6+ dashes, equals, asterisks, hashes, etc. -> 6 chars)
    DIVIDER_REGEX = re.compile(r"([-=─═*~#_])\1{5,}")
    # 4. Consecutive blank lines (3+ newlines -> 2 newlines)
    MULTI_NEWLINE_REGEX = re.compile(r"\n{3,}")
    # 5. Verbose microsecond timestamps in log streams
    TIMESTAMP_VERBOSE_REGEX = re.compile(r"\b(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})\.\d+(?:Z|[+-]\d{2}:\d{2})?\b")

    def __init__(self):
        self.total_chars_saved: int = 0
        self.total_compressions: int = 0
        self.total_scanned_requests: int = 0
        # Pending delta since last DB persist — avoids writing unchanged data
        self._pending_chars_saved: int = 0
        self._pending_compressions: int = 0

    def load(self, chars_saved: int, compressions: int) -> None:
        """Restore persisted counters at startup (called by LlmRouter after DB load)."""
        self.total_chars_saved = max(0, chars_saved)
        self.total_compressions = max(0, compressions)
        # Reset pending delta — these values are already in DB
        self._pending_chars_saved = 0
        self._pending_compressions = 0

    def consume_pending_delta(self) -> tuple[int, int]:
        """Returns and resets the unsaved delta since last persist cycle."""
        delta = (self._pending_chars_saved, self._pending_compressions)
        self._pending_chars_saved = 0
        self._pending_compressions = 0
        return delta

    def _compact_json(self, text: str) -> str:
        """Minifies JSON strings if text is valid JSON without corrupting non-JSON text."""
        stripped = text.strip()
        if (stripped.startswith("{") and stripped.endswith("}")) or (stripped.startswith("[") and stripped.endswith("]")):
            try:
                parsed = json.loads(stripped)
                minified = json.dumps(parsed, separators=(",", ":"), ensure_ascii=False)
                if len(minified) < len(text):
                    return minified
            except Exception:
                pass
        return text

    def compress(self, text: str, max_chars: int = 2500, max_lines: int = 35) -> str:
        if not text or not isinstance(text, str):
            return text or ""

        orig_len = len(text)
        self.total_scanned_requests += 1

        # 1. Check JSON compaction
        cleaned = self._compact_json(text)

        # 2. Strip ANSI terminal color & cursor escape codes
        cleaned = self.ANSI_REGEX.sub("", cleaned)

        # 3. Compact verbose timestamps in log streams
        cleaned = self.TIMESTAMP_VERBOSE_REGEX.sub(r"\1", cleaned)

        # 4. Compact repetitive divider lines (e.g. 80 dashes -> 6 dashes)
        cleaned = self.DIVIDER_REGEX.sub(r"\1\1\1\1\1\1", cleaned)

        # 5. Trim trailing whitespaces on each line and compact excessive table gaps
        lines = []
        for raw_line in cleaned.splitlines():
            line = raw_line.rstrip()
            if not line:
                lines.append("")
                continue
            # Collapse 3+ consecutive spaces (e.g. in ps/docker tables) to 2 spaces
            compacted_line = self.TABLE_GAP_REGEX.sub("  ", line)
            lines.append(compacted_line)

        # 6. Head-Tail Table & Process list sampling
        if len(lines) > max_lines:
            header_count = min(3, len(lines))
            headers = lines[:header_count]
            remaining_slots = max_lines - header_count - 1
            if remaining_slots > 4:
                head_take = remaining_slots - 2
                tail_take = 2
                head_sample = lines[header_count : header_count + head_take]
                tail_sample = lines[-tail_take:]
                omitted = len(lines) - (header_count + head_take + tail_take)
                lines = headers + head_sample + [f"[... {omitted} lines omitted by 9Router RTK ...]"] + tail_sample
            else:
                sample = lines[header_count : header_count + remaining_slots]
                omitted = len(lines) - (header_count + len(sample))
                lines = headers + sample + [f"[... {omitted} lines omitted by 9Router RTK ...]"]

        cleaned = "\n".join(lines)

        # 7. Collapse 3+ consecutive empty lines
        cleaned = self.MULTI_NEWLINE_REGEX.sub("\n\n", cleaned).strip()

        # 8. Hard cap character boundary
        if len(cleaned) > max_chars:
            cleaned = cleaned[:max_chars].rstrip() + "\n[... truncated by 9Router RTK ...]"

        saved = max(0, orig_len - len(cleaned))
        # Strictly increment only when tokens/characters are actually saved
        if saved > 0:
            self.total_chars_saved += saved
            self.total_compressions += 1
            self._pending_chars_saved += saved
            self._pending_compressions += 1

        return cleaned

    @property
    def estimated_tokens_saved(self) -> int:
        return self.total_chars_saved // 4


# ─── Key Entry & Provider Pool ───────────────────────────────────────────────

class KeyEntry:
    """Represents an individual API key with usage metrics and adaptive cooldown."""
    __slots__ = (
        "key_id",
        "api_key",
        "masked_key",
        "provider_name",
        "available_at",
        "usage_count",
        "fail_count",
        "rate_limit_count",
        "is_dead",
    )

    def __init__(self, key_id: int, api_key: str, provider_name: str):
        self.key_id: int = key_id
        self.api_key: str = api_key.strip()
        self.masked_key: str = (
            self.api_key[:6] + "..." + self.api_key[-4:]
            if len(self.api_key) > 10
            else "••••••••"
        )
        self.provider_name: str = provider_name
        self.available_at: float = 0.0
        self.usage_count: int = 0
        self.fail_count: int = 0
        self.rate_limit_count: int = 0
        self.is_dead: bool = False

    def is_available(self, now: float) -> bool:
        return not self.is_dead and now >= self.available_at

    def __lt__(self, other: "KeyEntry") -> bool:
        if self.available_at != other.available_at:
            return self.available_at < other.available_at
        return self.usage_count < other.usage_count


class Provider:
    """Represents an AI provider (e.g. Groq, OpenRouter) with its own key pool & routing tier."""

    def __init__(
        self,
        name: str,
        tier: int,
        base_url: str,
        default_model: str,
        api_keys: List[str],
        extra_headers: Optional[Dict[str, str]] = None,
    ):
        self.name: str = name
        self.tier: int = tier
        self.base_url: str = base_url
        self.default_model: str = default_model
        self.extra_headers: Dict[str, str] = extra_headers or {}
        self.keys: List[KeyEntry] = []
        self._lock = asyncio.Lock()
        self.total_requests: int = 0
        self.successful_requests: int = 0

        for idx, k in enumerate(api_keys):
            clean = k.strip() if k else ""
            if clean:
                self.keys.append(KeyEntry(idx + 1, clean, name))

    @property
    def has_keys(self) -> bool:
        return len(self.keys) > 0

    @property
    def active_key_count(self) -> int:
        now = time.time()
        return sum(1 for k in self.keys if k.is_available(now))

    async def get_next_key(self) -> Optional[KeyEntry]:
        async with self._lock:
            if not self.keys:
                return None

            now = time.time()
            # Prioritize available keys with lowest usage
            available = [k for k in self.keys if k.is_available(now)]
            if available:
                available.sort(key=lambda k: k.usage_count)
                selected = available[0]
                selected.usage_count += 1
                return selected

            # If all are in cooldown, pick the one available earliest
            usable = [k for k in self.keys if not k.is_dead]
            if usable:
                usable.sort(key=lambda k: k.available_at)
                selected = usable[0]
                selected.usage_count += 1
                return selected

            return None

    async def mark_rate_limited(self, key_entry: KeyEntry, cooldown_seconds: float = 60.0):
        async with self._lock:
            key_entry.rate_limit_count += 1
            key_entry.fail_count += 1
            # Add full jitter (0.8x to 1.2x) to avoid thunder-herd retry spikes
            jitter = random.uniform(0.8, 1.2)
            key_entry.available_at = time.time() + (cooldown_seconds * jitter)
            logger.warning(
                "[9Router] Provider '%s' Key #%d hit Rate Limit (429). Cooldown: %.1fs",
                self.name,
                key_entry.key_id,
                cooldown_seconds * jitter,
            )

    async def mark_success(self, key_entry: KeyEntry):
        async with self._lock:
            self.total_requests += 1
            self.successful_requests += 1

    async def mark_dead(self, key_entry: KeyEntry):
        async with self._lock:
            key_entry.is_dead = True
            logger.error("[9Router] Key #%d permanently marked DEAD for provider '%s'.", key_entry.key_id, self.name)


# ─── 9Router Engine (Core Gateway) ──────────────────────────────────────────

class LlmRouter:
    """
    9Router Intelligent AI Proxy & Multi-Provider Router.
    - Tier 1: Groq Multi-Key Pool (7 keys, LPU ultra-fast inference).
    - Tier 2: OpenRouter Multi-Model Pool (NVIDIA 120B / OpenRouter Free).
    - RTK (Reduction Token Killer) output compressor.
    - Circuit breaker, automatic retry, and zero-downtime failover.
    """

    def __init__(self):
        self.rtk = RtkCompressor()
        self.providers: Dict[str, Provider] = {}
        # High-performance HTTP client with persistent keepalive connection pool
        self._http_client = httpx.AsyncClient(
            timeout=120.0,
            limits=httpx.Limits(
                max_keepalive_connections=20,
                max_connections=50,
                keepalive_expiry=60.0,
            ),
        )
        self.total_routed: int = 0
        self.total_failovers: int = 0

        self._init_providers()
        logger.info(
            "[9Router] Engine initialized with %d provider(s), total %d key(s).",
            len(self.providers),
            sum(len(p.keys) for p in self.providers.values()),
        )

    def _init_providers(self):
        # 1. Tier 1: Groq Multi-Key Pool
        groq_keys = settings.groq_keys
        if groq_keys:
            self.providers["groq"] = Provider(
                name="groq",
                tier=1,
                base_url="https://api.groq.com/openai/v1/chat/completions",
                default_model=settings.GROQ_MODEL,
                api_keys=groq_keys,
            )

        # 2. Tier 2: OpenRouter Multi-Key Pool (mirrors Groq pool)
        openrouter_keys = settings.openrouter_keys
        if openrouter_keys:
            self.providers["openrouter"] = Provider(
                name="openrouter",
                tier=2,
                base_url=settings.OPENROUTER_API_URL,
                default_model=settings.OPENROUTER_MODEL,
                api_keys=openrouter_keys,
                extra_headers={
                    "HTTP-Referer": "https://dashboard.kirito.server",
                    "X-Title": "Server Dashboard AI (9Router)",
                },
            )

    @property
    def has_active_providers(self) -> bool:
        return any(p.has_keys for p in self.providers.values())

    async def complete(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = "auto",
        temperature: float = 0.1,
        max_tokens: int = 1024,
        requested_model: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Routes the chat completion through the 9Router smart tiered fallback engine.
        Returns OpenAI-compatible response dict or None.
        """
        self.total_routed += 1
        sorted_providers = sorted(self.providers.values(), key=lambda p: p.tier)

        for provider_idx, provider in enumerate(sorted_providers):
            if not provider.has_keys:
                continue

            model_to_use = requested_model or provider.default_model

            # Try up to 3 keys within this provider before escalating tier
            attempts_in_provider = min(3, max(1, len(provider.keys)))
            for _ in range(attempts_in_provider):
                key_entry = await provider.get_next_key()
                if not key_entry:
                    break

                headers = {
                    "Authorization": f"Bearer {key_entry.api_key}",
                    "Content-Type": "application/json",
                }
                # Sanitize messages (strip provider-specific fields like reasoning_details)
                clean_messages = []
                for m in messages:
                    if isinstance(m, dict):
                        m_copy = {k: v for k, v in m.items() if k not in ("reasoning_details",)}
                        clean_messages.append(m_copy)
                    else:
                        clean_messages.append(m)

                payload: Dict[str, Any] = {
                    "model": model_to_use,
                    "messages": clean_messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                if tools:
                    payload["tools"] = tools
                    payload["tool_choice"] = tool_choice

                try:
                    t0 = time.time()
                    resp = await self._http_client.post(provider.base_url, headers=headers, json=payload)
                    latency = time.time() - t0

                    # Handle 429 Rate Limit
                    if resp.status_code == 429:
                        await provider.mark_rate_limited(key_entry, cooldown_seconds=60.0)
                        continue

                    # Handle 401 Unauthorized
                    if resp.status_code == 401:
                        await provider.mark_dead(key_entry)
                        continue

                    # Handle 200 OK
                    if resp.status_code == 200:
                        await provider.mark_success(key_entry)
                        data = resp.json()
                        choice = data["choices"][0]
                        logger.info(
                            "[9Router] Routed -> [%s / Key #%d] in %.2fs (Finish: %s)",
                            provider.name,
                            key_entry.key_id,
                            latency,
                            choice.get("finish_reason"),
                        )
                        # Inject 9Router metadata
                        data["_9router"] = {
                            "provider": provider.name,
                            "tier": provider.tier,
                            "key_id": key_entry.key_id,
                            "latency_sec": round(latency, 3),
                            "tokens_saved_estimate": self.rtk.estimated_tokens_saved,
                        }
                        return data

                    # Handle Groq 400 with failed_generation (Resilient tool parser)
                    if resp.status_code == 400 and "failed_generation" in resp.text:
                        err_data = resp.json()
                        failed_gen = err_data.get("error", {}).get("failed_generation", "")
                        if failed_gen:
                            cleaned = re.sub(r"<function=.*?>.*?</function>", "", failed_gen, flags=re.DOTALL).strip()
                            cleaned = re.sub(r"<function=.*", "", cleaned, flags=re.DOTALL).strip()
                            if cleaned:
                                return {
                                    "id": f"chatcmpl-9router-recovered-{int(time.time())}",
                                    "object": "chat.completion",
                                    "created": int(time.time()),
                                    "model": model_to_use,
                                    "choices": [
                                        {
                                            "index": 0,
                                            "message": {"role": "assistant", "content": cleaned},
                                            "finish_reason": "stop",
                                        }
                                    ],
                                    "_9router": {
                                        "provider": f"{provider.name}_recovered",
                                        "tier": provider.tier,
                                        "key_id": key_entry.key_id,
                                        "latency_sec": round(latency, 3),
                                    },
                                }

                    logger.warning(
                        "[9Router] Provider '%s' returned HTTP %d: %s. Trying next...",
                        provider.name,
                        resp.status_code,
                        resp.text[:150],
                    )

                except Exception as ex:
                    logger.error("[9Router] Error connecting to '%s': %s", provider.name, ex)

            # If all attempts in this tier failed, trigger Failover to next Tier
            if provider_idx < len(sorted_providers) - 1:
                self.total_failovers += 1
                next_p = sorted_providers[provider_idx + 1]
                logger.warning(
                    "[9Router] Tier %d (%s) exhausted. Auto-failover to Tier %d (%s)...",
                    provider.tier,
                    provider.name,
                    next_p.tier,
                    next_p.name,
                )

        return None

    def get_status(self) -> Dict[str, Any]:
        """Returns live 9Router telemetry and health statistics."""
        now = time.time()
        providers_info = []

        for p in self.providers.values():
            keys_info = []
            for k in p.keys:
                cooldown_rem = max(0.0, k.available_at - now)
                keys_info.append({
                    "key_id": k.key_id,
                    "masked": k.masked_key,
                    "available": k.is_available(now),
                    "cooldown_remaining_sec": round(cooldown_rem, 1),
                    "usage_count": k.usage_count,
                    "fail_count": k.fail_count,
                    "rate_limit_count": k.rate_limit_count,
                    "is_dead": k.is_dead,
                })

            providers_info.append({
                "name": p.name,
                "tier": p.tier,
                "model": p.default_model,
                "total_keys": len(p.keys),
                "active_keys": p.active_key_count,
                "total_requests": p.total_requests,
                "successful_requests": p.successful_requests,
                "keys": keys_info,
            })

        return {
            "status": "online" if self.has_active_providers else "degraded",
            "total_routed": self.total_routed,
            "total_failovers": self.total_failovers,
            "rtk": {
                "total_compressions": self.rtk.total_compressions,
                "chars_saved": self.rtk.total_chars_saved,
                "estimated_tokens_saved": self.rtk.estimated_tokens_saved,
            },
            "providers": providers_info,
        }

    async def load_stats_from_db(self) -> None:
        """Loads persisted RTK stats from DB into the in-memory compressor at startup."""
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT total_chars_saved, total_compressions FROM rtk_stats WHERE id = 1"
                    )
                    row = await cur.fetchone()
                    if row:
                        chars_saved, compressions = row[0], row[1]
                        self.rtk.load(int(chars_saved), int(compressions))
                        logger.info(
                            "[9Router] RTK stats restored from DB: compressions=%d, chars_saved=%d, tokens_saved≈%d",
                            self.rtk.total_compressions,
                            self.rtk.total_chars_saved,
                            self.rtk.estimated_tokens_saved,
                        )
        except Exception as e:
            logger.warning("[9Router] Could not load RTK stats from DB (non-fatal): %s", e)

    async def save_stats_to_db(self) -> None:
        """Persists RTK stats delta to DB using UPSERT with atomic increment.

        Uses ADD-delta approach (total_chars_saved + delta) instead of SET to avoid
        race conditions if multiple coroutines call this concurrently.
        """
        delta_chars, delta_compressions = self.rtk.consume_pending_delta()
        # Nothing new to write — skip the round-trip
        if delta_chars == 0 and delta_compressions == 0:
            return
        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        INSERT INTO rtk_stats (id, total_chars_saved, total_compressions, updated_at)
                        VALUES (1, %s, %s, NOW())
                        ON CONFLICT (id) DO UPDATE SET
                            total_chars_saved  = rtk_stats.total_chars_saved  + %s,
                            total_compressions = rtk_stats.total_compressions + %s,
                            updated_at         = NOW()
                        """,
                        (delta_chars, delta_compressions, delta_chars, delta_compressions),
                    )
                    await conn.commit()
            logger.debug(
                "[9Router] RTK stats persisted: +%d chars, +%d compressions",
                delta_chars, delta_compressions,
            )
        except Exception as e:
            # On failure, return the delta back to pending so it retries next cycle
            self.rtk._pending_chars_saved += delta_chars
            self.rtk._pending_compressions += delta_compressions
            logger.warning("[9Router] Failed to persist RTK stats to DB: %s", e)

