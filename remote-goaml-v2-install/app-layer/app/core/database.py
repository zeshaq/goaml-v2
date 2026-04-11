"""
PostgreSQL async connection pool using asyncpg
"""

import asyncpg
from core.config import settings

_pool: asyncpg.Pool | None = None


async def init_postgres():
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=settings.POSTGRES_URL,
        min_size=5,
        max_size=20,
        command_timeout=30,
    )


async def close_postgres():
    global _pool
    if _pool:
        await _pool.close()


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("PostgreSQL pool not initialized")
    return _pool
