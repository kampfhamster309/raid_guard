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
                 additional "enrichment_json" key (matches the DB column and
                 the frontend's Alert.enrichment_json field) when enrichment
                 succeeded.  This is the channel the notification router and
                 the WebSocket broadcaster subscribe to.

incidents:new    Published by the batch correlator (RAID-015) when a new
                 incident record is created.  Payload: incident dict.

digests:new      Published by the digestor (RAID-015a) when a new periodic
                 security digest is created.  Payload: digest dict.
"""

import asyncio
import logging
import os
from typing import AsyncIterator

import redis as syncredis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

logger = logging.getLogger(__name__)

_RESUBSCRIBE_DELAY_S = 2

# ── Channel names ─────────────────────────────────────────────────────────────

ALERTS_RAW = "alerts:raw"
ALERTS_ENRICHED = "alerts:enriched"
INCIDENTS_NEW = "incidents:new"
DIGESTS_NEW = "digests:new"

# ── Connection helpers ────────────────────────────────────────────────────────


def get_redis_url() -> str:
    """Return the Redis URL from the REDIS_URL env var (default: localhost)."""
    return os.environ.get("REDIS_URL", "redis://localhost:6379")


async def subscribe_forever(redis_client, channel: str) -> AsyncIterator[dict]:
    """Yield ``message`` events from *channel*, re-subscribing after Redis connection loss.

    redis-py reconnects once on its own; if Redis is still down (restart, crash)
    ``listen()`` raises and a plain loop would end for good.
    """
    while True:
        pubsub = redis_client.pubsub()
        try:
            await pubsub.subscribe(channel)
            async for message in pubsub.listen():
                if message["type"] == "message":
                    yield message
            return  # listen() ended without an error (only happens with test doubles)
        except (RedisConnectionError, RedisTimeoutError, OSError) as exc:
            logger.warning("Redis subscription to %s lost (%s); retrying in %ds", channel, exc, _RESUBSCRIBE_DELAY_S)
        finally:
            try:
                await pubsub.unsubscribe(channel)
            except Exception:
                pass
        await asyncio.sleep(_RESUBSCRIBE_DELAY_S)


def sync_redis() -> syncredis.Redis:
    """Return a synchronous Redis client (for tests and one-shot operations)."""
    return syncredis.from_url(get_redis_url(), decode_responses=True)
