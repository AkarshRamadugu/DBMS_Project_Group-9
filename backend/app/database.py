from contextlib import asynccontextmanager
from typing import AsyncGenerator

import psycopg_pool

from app.config import settings

pool: psycopg_pool.AsyncConnectionPool | None = None


async def init_pool() -> None:
    """Initialize the async connection pool on application startup."""
    global pool
    pool = psycopg_pool.AsyncConnectionPool(
        conninfo=settings.dsn,
        min_size=2,
        max_size=10,
        open=False,
    )
    await pool.open()


async def close_pool() -> None:
    """Close the async connection pool on application shutdown."""
    global pool
    if pool is not None:
        await pool.close()
        pool = None


@asynccontextmanager
async def get_conn() -> AsyncGenerator:
    """Async context manager that yields a connection from the pool."""
    if pool is None:
        raise RuntimeError("Connection pool is not initialized.")
    async with pool.connection() as conn:
        yield conn
