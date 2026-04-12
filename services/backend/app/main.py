import asyncio
import logging
import os
from contextlib import asynccontextmanager

import asyncpg
import redis.asyncio as aioredis
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect

from .auth import decode_token
from .backends.homeassistant import HomeAssistantBackend
from .channels import ALERTS_ENRICHED, get_redis_url
from .correlator import run_correlator
from .enricher import run_enricher
from .ingestor import ingestor_loop
from .notification_router import run_notification_router
from .routers import alerts, auth, incidents, rules, settings, stats

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
    # min_size=0 → no connections attempted at startup; pool creation always
    # succeeds even when the DB is unreachable (unit tests, cold start).
    pool = await asyncpg.create_pool(_get_db_url(), min_size=0, max_size=10)
    redis_client = aioredis.from_url(get_redis_url(), decode_responses=True)

    app.state.db_pool = pool
    app.state.redis = redis_client

    ingestor_task = asyncio.create_task(ingestor_loop(pool, redis_client))
    enrich_task = asyncio.create_task(run_enricher(redis_client, pool))
    correlator_task = asyncio.create_task(run_correlator(redis_client, pool))

    backends = [b for b in [HomeAssistantBackend.from_env(pool)] if b is not None]
    notif_task = asyncio.create_task(run_notification_router(redis_client, pool, backends))

    try:
        yield
    finally:
        ingestor_task.cancel()
        enrich_task.cancel()
        correlator_task.cancel()
        notif_task.cancel()
        await asyncio.gather(
            ingestor_task, enrich_task, correlator_task, notif_task, return_exceptions=True
        )
        await redis_client.aclose()
        await pool.close()


app = FastAPI(title="raid_guard backend", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(alerts.router)
app.include_router(incidents.router)
app.include_router(stats.router)
app.include_router(rules.router)
app.include_router(settings.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "backend"}


# ── WebSocket — live alert feed ───────────────────────────────────────────────


async def _forward_pubsub_to_ws(pubsub, websocket: WebSocket) -> None:
    """Read messages from Redis pubsub and forward them to the WebSocket."""
    try:
        async for msg in pubsub.listen():
            if msg["type"] == "message":
                await websocket.send_text(msg["data"])
    except Exception:
        pass  # WebSocket closed or Redis disconnected


@app.websocket("/ws/alerts")
async def ws_alerts(websocket: WebSocket, token: str = Query(...)):
    """
    Live alert feed over WebSocket.

    Subscribes to the ``alerts:enriched`` Redis channel and forwards each
    message to the connected client.  Authentication is via the same JWT
    passed as a ``?token=<jwt>`` query parameter (Authorization headers are
    not reliably available in browser WebSocket handshakes).

    Until RAID-013 (AI enricher) is implemented, publish test messages via:
        redis-cli PUBLISH alerts:enriched '{"test": true}'
    """
    await websocket.accept()

    try:
        decode_token(token)
    except Exception:
        await websocket.close(code=1008, reason="Unauthorized")
        return

    # Each WebSocket gets its own Redis client so pubsub does not share a
    # connection with the command client on app.state.redis.
    try:
        ws_redis = aioredis.from_url(get_redis_url(), decode_responses=True)
        pubsub = ws_redis.pubsub()
        await pubsub.subscribe(ALERTS_ENRICHED)
    except Exception as exc:
        logger.warning("WebSocket: Redis subscribe failed: %s", exc)
        await websocket.close()
        return

    fwd_task = asyncio.create_task(_forward_pubsub_to_ws(pubsub, websocket))

    try:
        # Block until the client disconnects; ignore any client → server data.
        while True:
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                break
    finally:
        fwd_task.cancel()
        await asyncio.gather(fwd_task, return_exceptions=True)
        try:
            await pubsub.unsubscribe(ALERTS_ENRICHED)
            await ws_redis.aclose()
        except Exception:
            pass
