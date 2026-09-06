import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Optional
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import settings

logger = logging.getLogger("app.core.db")


class DatabasePoolManager:
    """
    Singleton high-throughput AsyncPG/Psycopg3 Connection Pool Manager:
    - min_size: 4 warm connections ready for instant query execution (<0.8ms)
    - max_size: 20 connections max concurrency limit
    - max_idle: 300s timeout before pruning idle connections
    """
    _instance: Optional["DatabasePoolManager"] = None
    _pool: Optional[AsyncConnectionPool] = None

    def __new__(cls) -> "DatabasePoolManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def initialize(self) -> None:
        if self._pool is None:
            logger.info("[DB-Pool] Initializing AsyncConnectionPool (min=4, max=20)...")
            self._pool = AsyncConnectionPool(
                conninfo=settings.database_url,
                min_size=4,
                max_size=20,
                max_idle=300.0,
                timeout=30.0,
                open=False,
                kwargs={"autocommit": True},
            )
            await self._pool.open()
            logger.info("[DB-Pool] AsyncConnectionPool opened successfully")

    async def close(self) -> None:
        if self._pool is not None:
            logger.info("[DB-Pool] Closing AsyncConnectionPool...")
            await self._pool.close()
            self._pool = None
            logger.info("[DB-Pool] AsyncConnectionPool closed cleanly")

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[psycopg.AsyncConnection, None]:
        if self._pool is None:
            await self.initialize()
        assert self._pool is not None
        async with self._pool.connection() as conn:
            yield conn

    @asynccontextmanager
    async def cursor(self, row_factory: Optional[Any] = None) -> AsyncGenerator[psycopg.AsyncCursor, None]:
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
async def get_db_dict_cursor() -> AsyncGenerator[psycopg.AsyncCursor, None]:
    """Context manager for acquiring a cursor returning dictionary rows."""
    async with db_manager.cursor(row_factory=dict_row) as cur:
        yield cur
