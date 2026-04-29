"""
System status aggregator — probes each pipeline component and returns a
combined health snapshot for the dashboard Status page.
"""

import asyncio
import logging
import os

import httpx
from fastapi import APIRouter, Depends, Request

from ..auth import require_auth
from ..dependencies import get_pool, get_redis

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

_CAPTURE_AGENT_URL = os.environ.get("CAPTURE_AGENT_URL", "http://capture-agent:8080")
_SURICATA_CONTAINER = os.environ.get("SURICATA_CONTAINER_NAME", "raid_guard-suricata-1")


async def _probe_db(pool) -> bool:
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True
    except Exception:
        return False


async def _probe_redis(redis_client) -> bool:
    try:
        await redis_client.ping()
        return True
    except Exception:
        return False


def _task_alive(app_state, attr: str) -> bool:
    task = getattr(app_state, attr, None)
    return task is not None and not task.done()


async def _probe_capture_agent() -> dict:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{_CAPTURE_AGENT_URL}/health")
        data = resp.json()
        return {
            "ok": resp.status_code == 200,
            "reachable": True,
            "capture_state": data.get("capture_state"),
            "reconnect_count": data.get("reconnect_count", 0),
            "message": data.get("message", ""),
        }
    except Exception as exc:
        logger.debug("Capture agent probe failed: %s", exc)
        return {"ok": False, "reachable": False, "message": str(exc)}


def _probe_suricata_sync() -> dict:
    try:
        import docker
        dc = docker.from_env()
        container = dc.containers.get(_SURICATA_CONTAINER)
        state = container.attrs.get("State", {})
        running = state.get("Running", False)
        health_status = state.get("Health", {}).get("Status", "none")
        # "none" means no healthcheck configured; treat as ok if running
        ok = running and health_status != "unhealthy"
        return {"ok": ok, "running": running, "health": health_status}
    except Exception as exc:
        logger.debug("Suricata probe failed: %s", exc)
        return {"ok": False, "running": False, "message": str(exc)}


@router.get("/status")
async def get_status(
    pool=Depends(get_pool),
    redis_client=Depends(get_redis),
    request: Request = None,
    _user=Depends(require_auth),
):
    db_ok, redis_ok, capture_data, suricata_data = await asyncio.gather(
        _probe_db(pool),
        _probe_redis(redis_client),
        _probe_capture_agent(),
        asyncio.to_thread(_probe_suricata_sync),
    )
    return {
        "db": {"ok": db_ok},
        "redis": {"ok": redis_ok},
        "ingestor": {"ok": _task_alive(request.app.state, "ingestor_task")},
        "enricher": {"ok": _task_alive(request.app.state, "enrich_task")},
        "capture_agent": capture_data,
        "suricata": suricata_data,
    }
