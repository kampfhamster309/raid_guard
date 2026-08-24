"""
Gotify notification backend.

Sends push notifications to a self-hosted Gotify server (https://gotify.net)
for qualifying alerts and for pipeline health transitions. Configured via
``GOTIFY_URL`` and an application token created in the Gotify web UI.

Unlike the Home Assistant backend (a single "message" string plugged into an
HA automation), Gotify renders Markdown natively, so messages here carry the
full alert context — signature, source/destination, category, timestamp, and
(when available) the AI summary, severity reasoning, and recommended action
— not just a one-line summary.

Payload fields
--------------
title      "raid_guard — <SEVERITY>"
message    Markdown: signature + connection details, plus AI enrichment
           (summary / severity reasoning / recommended action) when present
priority   Gotify priority (0-10); mapped from severity so low-signal `info`
           alerts stay quiet while `critical` ones use Gotify's top tier —
           high enough to trigger a heads-up notification / bypass DND on
           clients that respect priority (Gotify's Android app does, at 8+)
extras     Markdown rendering hint, plus a deep link to the dashboard (if
           DASHBOARD_URL is set) rendered as a clickable notification by
           Gotify clients that support it.
"""

import logging
import os
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(10.0)
_GOTIFY_ENABLED_KEY = "gotify_enabled"
_GOTIFY_HEALTH_ALERTS_KEY = "gotify_health_alerts_enabled"

# 0-3 = min/low (quiet, no heads-up), 4-7 = normal, 8-10 = high (heads-up,
# bypasses do-not-disturb on clients that honour priority).
_PRIORITY_BY_SEVERITY = {"info": 2, "warning": 5, "critical": 10}
_PRIORITY_HEALTH_RECOVERED = 5
_PRIORITY_HEALTH_UNHEALTHY = 10


class GotifyBackend:
    name = "gotify"

    def __init__(
        self,
        base_url: str,
        app_token: str,
        pool=None,
        dashboard_url: str = "",
        health_app_token: str = "",
    ) -> None:
        self._url = base_url.rstrip("/")
        self._token = app_token
        self._pool = pool
        self._dashboard_url = dashboard_url.rstrip("/")
        self._health_token = health_app_token or app_token

    @classmethod
    def from_env(cls, pool=None) -> "GotifyBackend | None":
        """Return an instance if ``GOTIFY_URL`` and an app token are set, else ``None``."""
        url = os.environ.get("GOTIFY_URL", "").strip()
        token = os.environ.get("GOTIFY_APP_TOKEN", "").strip()
        health_token = os.environ.get("GOTIFY_HEALTH_APP_TOKEN", "").strip()
        if not url or not (token or health_token):
            return None
        dashboard_url = os.environ.get("DASHBOARD_URL", "").strip()
        return cls(url, token, pool=pool, dashboard_url=dashboard_url, health_app_token=health_token)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_message(self, alert: dict) -> str:
        """Build the Markdown message body — full alert context, not just a one-liner."""
        signature = alert.get("signature") or "Unknown alert"
        src_ip = alert.get("src_ip") or "unknown"
        dst_ip = alert.get("dst_ip")
        dst_port = alert.get("dst_port")
        proto = alert.get("proto")
        category = alert.get("category")
        timestamp = alert.get("timestamp")

        lines = [f"**{signature}**", ""]

        connection = f"Source: `{src_ip}`"
        if dst_ip:
            connection += f" → `{dst_ip}{f':{dst_port}' if dst_port else ''}`"
            if proto:
                connection += f" ({proto})"
        lines.append(connection)

        if category:
            lines.append(f"Category: {category}")
        if timestamp:
            lines.append(f"Time: {timestamp}")

        enrichment = alert.get("enrichment_json")
        if isinstance(enrichment, dict):
            summary = enrichment.get("summary")
            severity_reasoning = enrichment.get("severity_reasoning")
            recommended_action = enrichment.get("recommended_action")
            if summary:
                lines += ["", summary]
            if severity_reasoning:
                lines += ["", f"_Why this severity:_ {severity_reasoning}"]
            if recommended_action:
                lines.append(f"_Recommended action:_ {recommended_action}")

        return "\n".join(lines)

    def _build_payload(self, alert: dict) -> dict:
        """Build the JSON payload sent to the Gotify message endpoint."""
        alert_id = str(alert.get("id", ""))
        severity = alert.get("severity", "info")

        payload = {
            "title": f"raid_guard — {severity.upper()}",
            "message": self._build_message(alert),
            "priority": _PRIORITY_BY_SEVERITY.get(severity, 2),
            "extras": {"client::display": {"contentType": "text/markdown"}},
        }

        if self._dashboard_url and alert_id:
            payload["extras"]["client::notification"] = {
                "click": {"url": f"{self._dashboard_url}?alert={alert_id}"}
            }
        return payload

    def _build_health_payload(self, component: str, component_label: str, ok: bool) -> dict:
        return {
            "title": f"raid_guard — {'Component Recovered' if ok else 'Component Unhealthy'}",
            "message": f"**{component_label}** {'has recovered.' if ok else 'is unhealthy.'}",
            "priority": _PRIORITY_HEALTH_RECOVERED if ok else _PRIORITY_HEALTH_UNHEALTHY,
            "extras": {"client::display": {"contentType": "text/markdown"}},
        }

    async def _is_enabled(self) -> bool:
        """Read ``gotify_enabled`` from the config table; default ``True``."""
        if self._pool is None:
            return True
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT value FROM config WHERE key = $1", _GOTIFY_ENABLED_KEY
                )
            return row["value"].lower() != "false" if row else True
        except Exception as exc:
            logger.warning("Could not read gotify_enabled from DB: %s; defaulting to enabled", exc)
            return True

    async def _health_alerts_enabled(self) -> bool:
        """Read ``gotify_health_alerts_enabled`` from the config table; default ``True``."""
        if self._pool is None:
            return True
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT value FROM config WHERE key = $1", _GOTIFY_HEALTH_ALERTS_KEY
                )
            return row["value"].lower() != "false" if row else True
        except Exception as exc:
            logger.warning(
                "Could not read gotify_health_alerts_enabled from DB: %s; defaulting to enabled", exc
            )
            return True

    async def _post(self, token: str, payload: dict) -> None:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(f"{self._url}/message", params={"token": token}, json=payload)
            resp.raise_for_status()
        logger.debug("Gotify POST %s/message → HTTP %s", self._url, resp.status_code)

    # ── Public interface ──────────────────────────────────────────────────────

    async def send(self, alert: dict) -> None:
        """Dispatch one alert. Silently skips if no alert token or Gotify is disabled."""
        if not self._token:
            logger.debug("Gotify alert token not configured; skipping alert %s", alert.get("id"))
            return
        if not await self._is_enabled():
            logger.debug("Gotify notifications disabled; skipping alert %s", alert.get("id"))
            return
        await self._post(self._token, self._build_payload(alert))
        logger.debug("Gotify delivered alert %s", alert.get("id"))

    async def send_test(self) -> None:
        """Send a synthetic test notification, bypassing the enabled flag."""
        test_alert = {
            "id": "00000000-0000-0000-0000-000000000000",
            "severity": "info",
            "signature": "raid_guard test notification",
            "category": "Test",
            "src_ip": "127.0.0.1",
            "dst_ip": "127.0.0.1",
            "dst_port": 0,
            "proto": "TCP",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "enrichment_json": {
                "summary": "This is a synthetic test alert — no action needed.",
                "severity_reasoning": "Test notifications are always sent at info severity.",
                "recommended_action": "None — this confirms your Gotify connection works.",
            },
        }
        await self._post(self._token, self._build_payload(test_alert))
        logger.info("Gotify test notification sent successfully")

    async def send_health_alert(self, component: str, component_label: str, ok: bool) -> None:
        """Dispatch one health transition. Swallows errors — health pings must not crash the watcher."""
        if not self._health_token:
            return
        if not await self._health_alerts_enabled():
            logger.debug("Gotify health alerts disabled; skipping %s", component)
            return
        try:
            await self._post(self._health_token, self._build_health_payload(component, component_label, ok))
            logger.info("Gotify health notification sent: %s ok=%s", component, ok)
        except Exception as exc:
            logger.warning("Gotify health notification failed for %s: %s", component, exc)
