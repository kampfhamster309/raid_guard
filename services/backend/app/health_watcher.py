"""
Health watcher — polls pipeline component health every 60 s and notifies
configured backends when a component transitions between healthy and
unhealthy.

Notifications are sent:
- On the first poll if a component is already unhealthy (baseline detection).
- Whenever a component transitions ok→unhealthy or unhealthy→ok.

Any backend exposing ``send_health_alert(component, component_label, ok)``
(currently Home Assistant and Gotify) receives these transitions; each
backend gates its own delivery via its own "health alerts enabled" config
key and swallows its own delivery errors, so one target's outage never
blocks another's.
"""
import asyncio
import logging

from .routers.status import _probe_capture_agent, _probe_db, _probe_redis, _probe_suricata_sync

logger = logging.getLogger(__name__)

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


async def _notify_targets(targets: list, component: str, ok: bool) -> None:
    label = _COMPONENT_LABELS.get(component, component)
    for target in targets:
        try:
            await target.send_health_alert(component, label, ok)
        except Exception as exc:
            logger.warning(
                "Health notification via %s failed for %s: %s",
                getattr(target, "name", "?"), component, exc,
            )


async def _poll_once(pool, redis_client, app_state, targets: list, last: dict[str, bool | None]) -> None:
    """Run one health check cycle and update ``last`` in-place."""
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
                await _notify_targets(targets, component, ok)
        elif ok != prev:
            await _notify_targets(targets, component, ok)
        last[component] = ok


async def run_health_watcher(
    pool,
    redis_client,
    app_state,
    backends: list,
    *,
    initial_delay: float = _DEFAULT_INITIAL_DELAY,
    poll_interval: float = _DEFAULT_POLL_INTERVAL,
) -> None:
    """Long-running task — polls component health and notifies backends on transitions.

    ``backends`` is the same notification backend list used by the alert
    router; only backends exposing ``send_health_alert`` participate here.
    """
    targets = [b for b in backends if hasattr(b, "send_health_alert")]
    if not targets:
        logger.info("Health watcher: no notification targets configured; idle.")
        return

    if initial_delay > 0:
        await asyncio.sleep(initial_delay)

    last: dict[str, bool | None] = {k: None for k in _COMPONENT_LABELS}

    while True:
        try:
            await _poll_once(pool, redis_client, app_state, targets, last)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Health watcher cycle failed: %s", exc)

        await asyncio.sleep(poll_interval)
