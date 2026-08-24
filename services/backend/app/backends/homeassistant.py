"""
Home Assistant notification backend (RAID-010 / RAID-011).

Sends an HTTP POST to a configurable HA webhook URL for each qualifying alert.
The webhook URL is set by the ``HA_WEBHOOK_URL`` environment variable.

Payload fields
--------------
title           "raid_guard — <SEVERITY>"
message         AI summary if available, else Suricata signature name + src IP
severity        info | warning | critical
signature       Suricata signature name
src_ip          Source IP address
timestamp       ISO-8601 alert timestamp
alert_id        UUID string of the alert record
url             Deep link to the alert in the raid_guard dashboard (if DASHBOARD_URL set)
"""

import logging
import os
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(10.0)
_HA_ENABLED_KEY = "ha_enabled"
_HA_HEALTH_ALERTS_KEY = "ha_health_alerts_enabled"


class HomeAssistantBackend:
    name = "homeassistant"

    def __init__(
        self,
        webhook_url: str,
        pool=None,
        dashboard_url: str = "",
        health_webhook_url: str = "",
    ) -> None:
        self._url = webhook_url
        self._pool = pool
        self._dashboard_url = dashboard_url.rstrip("/")
        self._health_url = health_webhook_url or webhook_url

    @classmethod
    def from_env(cls, pool=None) -> "HomeAssistantBackend | None":
        """Return an instance if ``HA_WEBHOOK_URL`` or ``HA_HEALTH_WEBHOOK_URL`` is set, else ``None``."""
        url = os.environ.get("HA_WEBHOOK_URL", "").strip()
        health_url = os.environ.get("HA_HEALTH_WEBHOOK_URL", "").strip()
        if not url and not health_url:
            return None
        dashboard_url = os.environ.get("DASHBOARD_URL", "").strip()
        return cls(url, pool=pool, dashboard_url=dashboard_url, health_webhook_url=health_url)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_payload(self, alert: dict) -> dict:
        """Build the JSON payload sent to the HA webhook."""
        alert_id = str(alert.get("id", ""))

        # Prefer an AI-generated summary; fall back to the signature name.
        enrichment = alert.get("enrichment_json")
        summary = (
            enrichment.get("summary")
            if isinstance(enrichment, dict)
            else None
        ) or alert.get("signature") or "Unknown alert"

        severity = alert.get("severity", "info")
        src_ip = alert.get("src_ip", "")

        url = (
            f"{self._dashboard_url}?alert={alert_id}"
            if self._dashboard_url and alert_id
            else ""
        )

        return {
            "title": f"raid_guard \u2014 {severity.upper()}",
            "message": f"{summary} from {src_ip}",
            "severity": severity,
            "signature": alert.get("signature", ""),
            "src_ip": src_ip,
            "timestamp": alert.get("timestamp", ""),
            "alert_id": alert_id,
            "url": url,
        }

    async def _is_enabled(self) -> bool:
        """Read ``ha_enabled`` from the config table; default ``True``."""
        if self._pool is None:
            return True
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT value FROM config WHERE key = $1", _HA_ENABLED_KEY
                )
            return row["value"].lower() != "false" if row else True
        except Exception as exc:
            logger.warning("Could not read ha_enabled from DB: %s; defaulting to enabled", exc)
            return True

    async def _health_alerts_enabled(self) -> bool:
        """Read ``ha_health_alerts_enabled`` from the config table; default ``True``."""
        if self._pool is None:
            return True
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT value FROM config WHERE key = $1", _HA_HEALTH_ALERTS_KEY
                )
            return row["value"].lower() != "false" if row else True
        except Exception as exc:
            logger.warning(
                "Could not read ha_health_alerts_enabled from DB: %s; defaulting to enabled", exc
            )
            return True

    def _build_health_payload(self, component: str, component_label: str, ok: bool) -> dict:
        return {
            "title": f"raid_guard — {'Component Recovered' if ok else 'Component Unhealthy'}",
            "message": f"{component_label} {'has recovered.' if ok else 'is unhealthy.'}",
            "component": component,
            "component_label": component_label,
            "healthy": ok,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def _post(self, url: str, payload: dict) -> None:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
        logger.debug("HA webhook POST %s → HTTP %s", url, resp.status_code)

    # ── Public interface ──────────────────────────────────────────────────────

    async def send(self, alert: dict) -> None:
        """Dispatch one alert.  Silently skips if no alert webhook or HA is disabled."""
        if not self._url:
            logger.debug("HA alert webhook not configured; skipping alert %s", alert.get("id"))
            return
        if not await self._is_enabled():
            logger.debug("HA notifications disabled; skipping alert %s", alert.get("id"))
            return
        await self._post(self._url, self._build_payload(alert))
        logger.debug("HA webhook delivered alert %s", alert.get("id"))

    async def send_health_alert(self, component: str, component_label: str, ok: bool) -> None:
        """Dispatch one health transition. Swallows errors — health pings must not crash the watcher."""
        if not self._health_url:
            return
        if not await self._health_alerts_enabled():
            logger.debug("HA health alerts disabled; skipping %s", component)
            return
        try:
            await self._post(self._health_url, self._build_health_payload(component, component_label, ok))
            logger.info("HA health notification sent: %s ok=%s", component, ok)
        except Exception as exc:
            logger.warning("HA health notification failed for %s: %s", component, exc)

    async def send_test(self) -> None:
        """Send a synthetic test notification, bypassing the enabled flag."""
        test_alert = {
            "id": "00000000-0000-0000-0000-000000000000",
            "severity": "info",
            "signature": "raid_guard test notification",
            "src_ip": "127.0.0.1",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._post(self._url, self._build_payload(test_alert))
        logger.info("HA test notification sent successfully")
