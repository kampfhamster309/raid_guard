"""
Web Push notification backend (RAID-019).

Sends a Web Push notification to every stored subscription when an alert
qualifies for dispatch.  Uses VAPID authentication so no API key from a
push service vendor is needed.

VAPID key generation
--------------------
    cd services/backend && .venv/bin/python3 - << 'EOF'
    from py_vapid import Vapid; import base64
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    v = Vapid(); v.generate_keys()
    priv = v.private_key.private_numbers().private_value.to_bytes(32, 'big')
    pub  = v.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    print('VAPID_PRIVATE_KEY=' + base64.urlsafe_b64encode(priv).rstrip(b'=').decode())
    print('VAPID_PUBLIC_KEY='  + base64.urlsafe_b64encode(pub).rstrip(b'=').decode())
    EOF

Copy the output values into .env.

Subscription lifecycle
----------------------
Subscriptions are stored in push_subscriptions by the /api/push/subscribe
endpoint.  When a push returns 404 or 410 (Gone), the subscription is
automatically removed from the DB.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

from pywebpush import WebPushException, webpush

logger = logging.getLogger(__name__)

_VAPID_CLAIMS_SUB_DEFAULT = "mailto:admin@example.com"


class WebPushBackend:
    name = "webpush"

    def __init__(
        self,
        private_key: str,
        subject: str,
        pool=None,
        dashboard_url: str = "",
    ) -> None:
        self._private_key = private_key
        self._subject = subject
        self._pool = pool
        self._dashboard_url = dashboard_url.rstrip("/")

    @classmethod
    def from_env(cls, pool=None) -> "WebPushBackend | None":
        """Return an instance if ``VAPID_PRIVATE_KEY`` is set, else ``None``."""
        private_key = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
        if not private_key:
            return None
        subject = os.environ.get("VAPID_SUBJECT", _VAPID_CLAIMS_SUB_DEFAULT).strip()
        dashboard_url = os.environ.get("DASHBOARD_URL", "").strip()
        return cls(private_key, subject, pool=pool, dashboard_url=dashboard_url)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_payload(self, alert: dict) -> dict:
        alert_id = str(alert.get("id", ""))
        enrichment = alert.get("enrichment")
        body = (
            enrichment.get("summary")
            if isinstance(enrichment, dict)
            else None
        ) or f"{alert.get('signature', 'Unknown alert')} from {alert.get('src_ip', '')}"

        url = (
            f"{self._dashboard_url}?alert={alert_id}"
            if self._dashboard_url and alert_id
            else ""
        )

        return {
            "title": f"raid_guard \u2014 {alert.get('severity', 'info').upper()}",
            "body": body,
            "icon": "/icons/icon-192.png",
            "badge": "/icons/icon-192.png",
            "tag": f"raid_guard_{alert_id}",
            "data": {"url": url},
        }

    async def _get_subscriptions(self) -> list[dict]:
        if self._pool is None:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT endpoint, p256dh, auth FROM push_subscriptions"
            )
        return [dict(r) for r in rows]

    async def _delete_subscription(self, endpoint: str) -> None:
        if self._pool is None:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM push_subscriptions WHERE endpoint = $1", endpoint
                )
        except Exception as exc:
            logger.warning("Failed to delete expired push subscription: %s", exc)

    def _send_one_sync(self, subscription: dict, payload_json: str) -> None:
        webpush(
            subscription_info={
                "endpoint": subscription["endpoint"],
                "keys": {
                    "p256dh": subscription["p256dh"],
                    "auth": subscription["auth"],
                },
            },
            data=payload_json,
            vapid_private_key=self._private_key,
            vapid_claims={"sub": self._subject},
            ttl=86400,
            timeout=10,
        )

    # ── Public interface ──────────────────────────────────────────────────────

    async def send(self, alert: dict) -> None:
        """Send a push notification to all stored subscriptions."""
        payload_json = json.dumps(self._build_payload(alert))
        subscriptions = await self._get_subscriptions()

        for sub in subscriptions:
            try:
                await asyncio.to_thread(self._send_one_sync, sub, payload_json)
                logger.debug("Web Push delivered to %s…", sub["endpoint"][:50])
            except WebPushException as exc:
                resp = exc.response
                if resp is not None and resp.status_code in (404, 410):
                    logger.info(
                        "Push subscription expired (HTTP %s); removing: %s…",
                        resp.status_code,
                        sub["endpoint"][:50],
                    )
                    await self._delete_subscription(sub["endpoint"])
                else:
                    logger.warning(
                        "Web Push failed for %s…: %s", sub["endpoint"][:50], exc
                    )
                    raise
