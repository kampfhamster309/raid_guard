"""
Home Assistant notification backend (RAID-010 / RAID-011).

Sends an HTTP POST to a configurable HA webhook URL for each qualifying alert.
The webhook URL is set by the ``HA_WEBHOOK_URL`` environment variable.

Payload fields
--------------
severity        info | warning | critical
signature       Suricata signature name
src_ip          Source IP address
timestamp       ISO-8601 alert timestamp
alert_id        UUID string of the alert record
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(10.0)


class HomeAssistantBackend:
    name = "homeassistant"

    def __init__(self, webhook_url: str) -> None:
        self._url = webhook_url

    @classmethod
    def from_env(cls) -> "HomeAssistantBackend | None":
        """Return an instance if ``HA_WEBHOOK_URL`` is set, else ``None``."""
        url = os.environ.get("HA_WEBHOOK_URL", "").strip()
        return cls(url) if url else None

    async def send(self, alert: dict) -> None:
        payload = {
            "severity": alert.get("severity", "info"),
            "signature": alert.get("signature", "Unknown"),
            "src_ip": alert.get("src_ip", ""),
            "timestamp": alert.get("timestamp", ""),
            "alert_id": str(alert.get("id", "")),
        }
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(self._url, json=payload)
            resp.raise_for_status()
        logger.debug("HA webhook delivered alert %s (HTTP %s)", alert.get("id"), resp.status_code)
