"""
System status aggregator — probes each pipeline component and returns a
combined health snapshot for the dashboard Status page.
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, Request

from ..auth import require_auth
from ..dependencies import get_pool, get_redis
from ..ingestor import EVE_JSON_PATH

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

_CAPTURE_AGENT_URL = os.environ.get("CAPTURE_AGENT_URL", "http://capture-agent:8080")
_SURICATA_CONTAINER = os.environ.get("SURICATA_CONTAINER_NAME", "raid_guard-suricata-1")

# How long with zero alerts, while eve.json is still actively being written,
# before we consider detection "stalled" rather than just "quiet". Covers the
# 2026-09-01 incident: Suricata kept processing traffic (flow/http/dns/tls
# events kept appearing) but a stream-reassembly memcap exhaustion silently
# stopped the detect engine from producing any alert events for days, while
# every process/port-level health check kept reporting "healthy".
_DETECTION_STALL_HOURS = float(os.environ.get("DETECTION_STALL_HOURS", "6"))
# eve.json must have been written to within this window for us to trust that
# "no alerts" means detection is stalled rather than Suricata itself being
# down or capture having stopped (those are reported by their own probes).
_EVE_JSON_FRESH_SECONDS = 300


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


async def _probe_detection_stall(pool, capture_ok: bool, suricata_ok: bool) -> dict:
    """Detect a live-but-silent detection engine.

    Only meaningful when capture and Suricata both report healthy — if either
    is already down, that's the more direct signal and this probe stays out
    of the way (``ok: True``, ``reason: "not_applicable"``) rather than firing
    a second, redundant alert for the same root cause.
    """
    if not (capture_ok and suricata_ok):
        return {"ok": True, "reason": "not_applicable"}

    try:
        eve_age_seconds = time.time() - EVE_JSON_PATH.stat().st_mtime
    except OSError as exc:
        logger.debug("Detection-stall probe: eve.json stat failed: %s", exc)
        return {"ok": True, "reason": "eve_json_unreadable"}

    if eve_age_seconds > _EVE_JSON_FRESH_SECONDS:
        # Suricata isn't writing anything at all right now; that's a Suricata/
        # capture problem, already covered by those probes.
        return {"ok": True, "reason": "eve_json_stale"}

    try:
        async with pool.acquire() as conn:
            last_alert_at = await conn.fetchval("SELECT max(timestamp) FROM alerts")
    except Exception as exc:
        logger.debug("Detection-stall probe: DB query failed: %s", exc)
        return {"ok": True, "reason": "db_unavailable"}

    if last_alert_at is None:
        return {"ok": True, "reason": "no_alert_history"}

    stall_hours = (datetime.now(timezone.utc) - last_alert_at).total_seconds() / 3600
    ok = stall_hours <= _DETECTION_STALL_HOURS
    return {
        "ok": ok,
        "last_alert_hours_ago": round(stall_hours, 1),
        "stall_threshold_hours": _DETECTION_STALL_HOURS,
    }


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
    detection_data = await _probe_detection_stall(
        pool, capture_data.get("ok", False), suricata_data.get("ok", False)
    )
    return {
        "db": {"ok": db_ok},
        "redis": {"ok": redis_ok},
        "ingestor": {"ok": _task_alive(request.app.state, "ingestor_task")},
        "enricher": {"ok": _task_alive(request.app.state, "enrich_task")},
        "capture_agent": capture_data,
        "suricata": suricata_data,
        "detection": detection_data,
    }
