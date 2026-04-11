"""
Notification router (RAID-010).

Subscribes to the ``alerts:enriched`` Redis channel and dispatches qualifying
alerts to registered notification backends.  The push threshold is read from
the ``config`` table on every alert so that dashboard changes take effect
immediately without a restart.

Retry strategy
--------------
Each backend dispatch is attempted up to ``max_attempts`` times with
exponential backoff (1 s → 2 s → 4 s … capped at 30 s).  Failures after all
retries are logged but do not affect other backends or the main router loop.
"""

import asyncio
import json
import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

SEVERITY_ORDER: dict[str, int] = {"info": 0, "warning": 1, "critical": 2}
DEFAULT_THRESHOLD = "warning"


# ── Backend protocol ──────────────────────────────────────────────────────────


@runtime_checkable
class NotificationBackend(Protocol):
    """Minimal interface every notification backend must satisfy."""

    name: str

    async def send(self, alert: dict) -> None:
        """Dispatch one alert.  Raise on failure so the router can retry."""
        ...


# ── Threshold helper ──────────────────────────────────────────────────────────


async def _get_threshold(pool) -> str:
    """Read ``push_threshold`` from the config table; default to ``warning``."""
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM config WHERE key = 'push_threshold'"
            )
            return row["value"] if row else DEFAULT_THRESHOLD
    except Exception as exc:
        logger.warning("Could not read push_threshold from DB: %s; using %s", exc, DEFAULT_THRESHOLD)
        return DEFAULT_THRESHOLD


# ── Retry helper ──────────────────────────────────────────────────────────────


async def _dispatch_with_retry(
    backend: NotificationBackend,
    alert: dict,
    *,
    max_attempts: int = 3,
    base_delay: float = 1.0,
) -> None:
    """Attempt to send ``alert`` via ``backend``, retrying with exponential backoff."""
    delay = base_delay
    for attempt in range(1, max_attempts + 1):
        try:
            await backend.send(alert)
            logger.debug("Backend %s delivered alert %s", backend.name, alert.get("id"))
            return
        except Exception as exc:
            if attempt == max_attempts:
                logger.error(
                    "Backend %s failed after %d attempt(s) for alert %s: %s",
                    backend.name, max_attempts, alert.get("id"), exc,
                )
            else:
                logger.warning(
                    "Backend %s attempt %d/%d failed for alert %s: %s; retrying in %.1f s",
                    backend.name, attempt, max_attempts, alert.get("id"), exc, delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)


# ── Router loop ───────────────────────────────────────────────────────────────


async def run_notification_router(
    redis_client,
    pool,
    backends: list[NotificationBackend],
) -> None:
    """
    Long-running coroutine — call via ``asyncio.create_task()``.

    Subscribes to ``alerts:enriched``, reads the push threshold from the DB
    on each message, and fires off a retry task per backend for qualifying
    alerts.
    """
    from .channels import ALERTS_ENRICHED  # local import avoids circular dep at module level

    if not backends:
        logger.info("Notification router: no backends configured; idle.")
        return

    pubsub = redis_client.pubsub()
    await pubsub.subscribe(ALERTS_ENRICHED)
    logger.info(
        "Notification router started with %d backend(s): %s",
        len(backends),
        [b.name for b in backends],
    )

    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue

            try:
                alert = json.loads(message["data"])
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning("Notification router: invalid message payload: %s", exc)
                continue

            threshold = await _get_threshold(pool)
            alert_level = SEVERITY_ORDER.get(alert.get("severity", "info"), 0)
            threshold_level = SEVERITY_ORDER.get(threshold, SEVERITY_ORDER[DEFAULT_THRESHOLD])

            if alert_level < threshold_level:
                logger.debug(
                    "Alert %s severity=%s below threshold=%s; skipping.",
                    alert.get("id"), alert.get("severity"), threshold,
                )
                continue

            for backend in backends:
                asyncio.create_task(_dispatch_with_retry(backend, alert))

    except asyncio.CancelledError:
        try:
            await pubsub.unsubscribe(ALERTS_ENRICHED)
        except Exception:
            pass
        raise
