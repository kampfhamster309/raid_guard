import asyncio
import logging
import os
from contextlib import asynccontextmanager

import asyncpg
import redis.asyncio as aioredis
from fastapi import FastAPI

from .channels import get_redis_url
from .ingestor import ingestor_loop

logger = logging.getLogger(__name__)


def _get_db_url() -> str:
    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5432")
    user = os.environ.get("DB_USER", "raidguard")
    password = os.environ.get("DB_PASSWORD", "")
    name = os.environ.get("DB_NAME", "raidguard")
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # min_size=0: pool is created without establishing any connections, so
    # this succeeds even when the DB is unreachable (tests, cold start).
    pool = await asyncpg.create_pool(_get_db_url(), min_size=0, max_size=10)
    redis_client = aioredis.from_url(get_redis_url(), decode_responses=True)

    app.state.db_pool = pool
    app.state.redis = redis_client

    task = asyncio.create_task(ingestor_loop(pool, redis_client))

    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await redis_client.aclose()
        await pool.close()


app = FastAPI(title="raid_guard backend", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "backend"}
