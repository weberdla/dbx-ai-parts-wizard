"""Async Lakebase (Postgres) connection pool with OAuth token refresh."""
import time
import asyncio
import asyncpg

from . import config

# Lakebase OAuth tokens are short-lived (~1h); refresh the pool well before that.
TOKEN_TTL_SECONDS = 45 * 60


class DatabasePool:
    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None
        self._created_at: float = 0.0
        self._lock = asyncio.Lock()

    async def _build_pool(self) -> asyncpg.Pool:
        token = config.generate_db_token()
        return await asyncpg.create_pool(
            host=config.PGHOST,
            port=config.PGPORT,
            database=config.PGDATABASE,
            user=config.get_pguser(),
            password=token,
            ssl=config.PGSSLMODE,
            min_size=1,
            max_size=8,
            command_timeout=30,
            # asyncpg caches prepared statements; disable to be safe across
            # pooled connections behind the Lakebase proxy.
            statement_cache_size=0,
        )

    async def get_pool(self) -> asyncpg.Pool:
        async with self._lock:
            expired = (time.time() - self._created_at) > TOKEN_TTL_SECONDS
            if self._pool is None or expired:
                if self._pool is not None:
                    await self._pool.close()
                self._pool = await self._build_pool()
                self._created_at = time.time()
            return self._pool

    async def fetch(self, sql: str, *args):
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
        return [dict(r) for r in rows]

    async def execute(self, sql: str, *args) -> str:
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            return await conn.execute(sql, *args)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None


db = DatabasePool()
