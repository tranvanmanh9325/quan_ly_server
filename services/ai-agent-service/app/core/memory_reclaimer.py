"""
app/core/memory_reclaimer.py — Proactive Non-Blocking Memory Reclaimer.

Solves Python RSS memory retention on Linux Docker containers (glibc pymalloc fragmentation).
Executes Stop-The-World cycle GC and glibc malloc_trim(0) in a background thread via asyncio.to_thread,
ensuring Zero Event Loop blocking.
"""

from __future__ import annotations

import asyncio
import ctypes
import gc
import logging
import sys
import time
from typing import Any, Dict

logger = logging.getLogger("app.core.memory_reclaimer")


def _sync_collect_and_trim() -> Dict[str, Any]:
    """
    Synchronous memory reclamation executed strictly inside a worker thread.
    1. gc.collect(): Frees cyclic reference graphs (gen 0, 1, 2).
    2. libc.malloc_trim(0): Releases unmapped glibc arena memory back to Linux kernel.
    """
    t0 = time.perf_counter()
    unreachable_objects = gc.collect()

    trimmed = False
    if sys.platform.startswith("linux"):
        try:
            # glibc call: int malloc_trim(size_t pad);
            # Returns 1 if memory was actually released back to the OS kernel.
            libc = ctypes.CDLL("libc.so.6")
            res = libc.malloc_trim(ctypes.c_size_t(0))
            trimmed = (res == 1)
        except Exception as exc:
            logger.debug("[MemoryReclaimer] libc.malloc_trim skipped: %s", exc)

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return {
        "unreachable_objects": unreachable_objects,
        "trimmed": trimmed,
        "elapsed_ms": elapsed_ms,
    }


async def reclaim_memory_background(delay_seconds: float = 0.2) -> None:
    """
    Fire-and-forget coroutine to reclaim memory safely off the AsyncIO loop.
    A small initial delay lets caller coroutines exit scopes and drop local variables first.
    """
    async def _worker() -> None:
        try:
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)

            stats = await asyncio.to_thread(_sync_collect_and_trim)
            logger.info(
                "[MemoryReclaimer] Reclaim completed in %.1fms | Unreachable Objects: %d | glibc Trimmed: %s",
                stats["elapsed_ms"],
                stats["unreachable_objects"],
                stats["trimmed"],
            )
        except Exception as err:
            logger.warning("[MemoryReclaimer] Background reclamation failed: %s", err)

    asyncio.create_task(_worker())
