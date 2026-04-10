"""
Shared FastAPI dependencies for DB and Redis access.

Using Depends() instead of accessing app.state directly lets tests override
these with mocks via app.dependency_overrides.
"""

import asyncpg
import redis.asyncio as aioredis
from fastapi import Request


async def get_pool(request: Request) -> asyncpg.Pool:
    return request.app.state.db_pool


async def get_redis(request: Request) -> aioredis.Redis:
    return request.app.state.redis
