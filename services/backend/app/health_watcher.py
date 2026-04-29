"""
Health watcher — polls pipeline component health every 60 s and sends HA
push notifications when a component transitions between healthy and unhealthy.

Notifications are sent:
- On the first poll if a component is already unhealthy (baseline detection).
- Whenever a component transitions ok→unhealthy or unhealthy→ok.

Controlled by the ``ha_health_alerts_enabled`` config key (default True).
Exits silently if HA_WEBHOOK_URL is not set.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone

import httpx

from .routers.status import _probe_capture_agent, _probe_db, _probe_redis, _probe_suricata_sync

logger = logging.getLogger(__name__)

_HA_HEALTH_ALERTS_KEY = "ha_health_alerts_enabled"
_DEFAULT_POLL_INTERVAL = 60.0
_DEFAULT_INITIAL_DELAY = 60.0

_COMPONENT_LABELS: dict[str, str] = {
    "db": "TimescaleDB",
    "redis": "Redis",
    "capture_agent": "Fritzbox Capture",
    "suricata": "Suricata IDS",
    "ingestor": "Alert Ingestor",
    "enricher": "AI Enricher",
}


async def _is_enabled(pool) -> bool:
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM config WHERE key = $1", _HA_HEALTH_ALERTS_KEY
            )
        return row["value"].lower() != "false" if row else True
    except Exception as exc:
        logger.warning("Could not read %s from DB: %s", _HA_HEALTH_ALERTS_KEY, exc)
        return True


async def _send_notification(webhook_url: str, component: str, ok: bool) -> None:
    label = _COMPONENT_LABELS.get(component, component)
    payload = {
        "title": f"raid_guard — {'Component Recovered' if ok else 'Component Unhealthy'}",
        "message": f"{label} {'has recovered.' if ok else 'is unhealthy.'}",
        "component": component,
        "component_label": label,
        "healthy": ok,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
        logger.info("HA health notification sent: %s ok=%s", component, ok)
    except Exception as exc:
        logger.warning("HA health notification failed for %s: %s", component, exc)


async def _poll_once(pool, redis_client, app_state, webhook_url: str, last: dict[str, bool | None]) -> None:
    """Run one health check cycle and update ``last`` in-place."""
    if not await _is_enabled(pool):
        return

    db_ok, redis_ok, capture_data, suricata_data = await asyncio.gather(
        _probe_db(pool),
        _probe_redis(redis_client),
        _probe_capture_agent(),
        asyncio.to_thread(_probe_suricata_sync),
    )

    ingestor_task = getattr(app_state, "ingestor_task", None)
    enrich_task = getattr(app_state, "enrich_task", None)
    current: dict[str, bool] = {
        "db": db_ok,
        "redis": redis_ok,
        "capture_agent": capture_data.get("ok", False),
        "suricata": suricata_data.get("ok", False),
        "ingestor": ingestor_task is not None and not ingestor_task.done(),
        "enricher": enrich_task is not None and not enrich_task.done(),
    }

    for component, ok in current.items():
        prev = last[component]
        if prev is None:
            if not ok:
                await _send_notification(webhook_url, component, ok)
        elif ok != prev:
            await _send_notification(webhook_url, component, ok)
        last[component] = ok


async def run_health_watcher(
    pool,
    redis_client,
    app_state,
    *,
    initial_delay: float = _DEFAULT_INITIAL_DELAY,
    poll_interval: float = _DEFAULT_POLL_INTERVAL,
) -> None:
    """Long-running task — polls component health and notifies HA on transitions.

    Uses HA_HEALTH_WEBHOOK_URL when set; falls back to HA_WEBHOOK_URL so that
    a single-webhook setup works without any extra configuration.
    """
    webhook_url = (
        os.environ.get("HA_HEALTH_WEBHOOK_URL", "").strip()
        or os.environ.get("HA_WEBHOOK_URL", "").strip()
    )
    if not webhook_url:
        logger.info("Health watcher: no webhook URL configured; idle.")
        return

    if initial_delay > 0:
        await asyncio.sleep(initial_delay)

    last: dict[str, bool | None] = {k: None for k in _COMPONENT_LABELS}

    while True:
        try:
            await _poll_once(pool, redis_client, app_state, webhook_url, last)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Health watcher cycle failed: %s", exc)

        await asyncio.sleep(poll_interval)
