"""
app/core/db.py — High-Performance Async PostgreSQL Connection Pool Manager.

Engineered with Psycopg 3 AsyncConnectionPool:
- min_size: 2 (reduces idle server RAM footprint on 3.2GB host)
- max_size: 10 (concurrency limiter, protects Postgres from connection storms)
- timeout: 10.0s (fail-fast timeout preventing coroutine starvation)
- max_idle: 300.0s (reclaims inactive connections down to min_size)
- max_lifetime: 1800.0s (recycles long-lived connections against memory creep)
- check: check_connection (validates socket health before checkout)
"""

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, Optional
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import settings

logger = logging.getLogger("app.core.db")


class DatabasePoolManager:
    _instance: Optional["DatabasePoolManager"] = None
    _pool: Optional[AsyncConnectionPool] = None

    def __new__(cls) -> "DatabasePoolManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def initialize(self) -> None:
        if self._pool is None:
            logger.info("[DB-Pool] Initializing AsyncConnectionPool (min=2, max=10, timeout=10.0s)...")
            self._pool = AsyncConnectionPool(
                conninfo=settings.database_url,
                min_size=2,
                max_size=10,
                max_idle=300.0,
                max_lifetime=1800.0,
                timeout=10.0,
                check=AsyncConnectionPool.check_connection,
                open=False,
                kwargs={"autocommit": True},
            )
            await self._pool.open()
            logger.info("[DB-Pool] AsyncConnectionPool opened successfully ✓")

    async def close(self) -> None:
        if self._pool is not None:
            logger.info("[DB-Pool] Closing AsyncConnectionPool...")
            await self._pool.close()
            self._pool = None
            logger.info("[DB-Pool] AsyncConnectionPool closed cleanly ✓")

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[psycopg.AsyncConnection, None]:
        if self._pool is None:
            await self.initialize()
        assert self._pool is not None
        async with self._pool.connection() as conn:
            yield conn

    @asynccontextmanager
    async def cursor(self, row_factory: Optional[Any] = None) -> AsyncGenerator[psycopg.AsyncCursor[Any], None]:
        async with self.connection() as conn:
            if row_factory:
                conn.row_factory = row_factory
            async with conn.cursor() as cur:
                yield cur


db_manager = DatabasePoolManager()


@asynccontextmanager
async def get_db_connection() -> AsyncGenerator[psycopg.AsyncConnection, None]:
    """Context manager for acquiring a pooled DB connection."""
    async with db_manager.connection() as conn:
        yield conn


@asynccontextmanager
async def get_db_dict_cursor() -> AsyncGenerator[psycopg.AsyncCursor[Dict[str, Any]], None]:
    """Context manager for acquiring a cursor returning dictionary rows."""
    async with db_manager.cursor(row_factory=dict_row) as cur:
        yield cur
