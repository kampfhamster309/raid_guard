"""
Redis pub/sub channel definitions and connection helpers.

Channel contract
----------------
alerts:raw       Published by the ingestor (RAID-005) for every alert event
                 parsed from the Suricata EVE JSON log.  Payload: raw alert
                 dict serialised as JSON.

alerts:enriched  Published by the AI enricher (RAID-013) after per-alert
                 enrichment completes (or on enrichment failure/timeout, with
                 the original alert unchanged).  Payload: alert dict with an
                 additional "enrichment" key.  This is the channel the
                 notification router and the WebSocket broadcaster subscribe to.
"""

import os
import redis.asyncio as aioredis
import redis as syncredis
from contextlib import asynccontextmanager

# ── Channel names ─────────────────────────────────────────────────────────────

ALERTS_RAW = "alerts:raw"
ALERTS_ENRICHED = "alerts:enriched"
INCIDENTS_NEW = "incidents:new"

ALL_CHANNELS = (ALERTS_RAW, ALERTS_ENRICHED, INCIDENTS_NEW)

# ── Connection helpers ────────────────────────────────────────────────────────


def get_redis_url() -> str:
    """Return the Redis URL from the REDIS_URL env var (default: localhost)."""
    return os.environ.get("REDIS_URL", "redis://localhost:6379")


@asynccontextmanager
async def async_redis():
    """Async context manager that yields a connected asyncio Redis client."""
    client = aioredis.from_url(get_redis_url(), decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


def sync_redis() -> syncredis.Redis:
    """Return a synchronous Redis client (for tests and one-shot operations)."""
    return syncredis.from_url(get_redis_url(), decode_responses=True)
