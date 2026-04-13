"""Web Push subscription API (RAID-019).

Endpoints
---------
GET    /api/push/vapid-public-key   Return VAPID public key for frontend subscription
POST   /api/push/subscribe          Save (or update) a push subscription
DELETE /api/push/subscribe          Remove a push subscription by endpoint
"""

import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from ..auth import require_auth
from ..dependencies import get_pool

router = APIRouter(prefix="/api/push", tags=["push"])


# ── Models ────────────────────────────────────────────────────────────────────


class PushSubscriptionBody(BaseModel):
    endpoint: str
    keys: dict[str, str]  # {"p256dh": "...", "auth": "..."}


class UnsubscribeBody(BaseModel):
    endpoint: str


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/vapid-public-key")
async def get_vapid_public_key(_: str = Depends(require_auth)):
    """Return the VAPID public key.  Frontend passes this to PushManager.subscribe()."""
    key = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
    if not key:
        raise HTTPException(
            status_code=404,
            detail="VAPID_PUBLIC_KEY is not configured",
        )
    return {"public_key": key}


@router.post("/subscribe", status_code=201)
async def subscribe(
    body: PushSubscriptionBody,
    pool=Depends(get_pool),
    _: str = Depends(require_auth),
):
    """Store a browser push subscription.  Upserts on endpoint collision."""
    if not body.endpoint:
        raise HTTPException(status_code=422, detail="endpoint must not be empty")
    p256dh = body.keys.get("p256dh", "")
    auth = body.keys.get("auth", "")
    if not p256dh or not auth:
        raise HTTPException(
            status_code=422,
            detail="keys.p256dh and keys.auth are required",
        )

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO push_subscriptions (endpoint, p256dh, auth) "
            "VALUES ($1, $2, $3) "
            "ON CONFLICT (endpoint) DO UPDATE SET p256dh = $2, auth = $3",
            body.endpoint,
            p256dh,
            auth,
        )
    return Response(status_code=201)


@router.delete("/subscribe", status_code=204)
async def unsubscribe(
    body: UnsubscribeBody,
    pool=Depends(get_pool),
    _: str = Depends(require_auth),
):
    """Remove a push subscription by endpoint URL."""
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM push_subscriptions WHERE endpoint = $1",
            body.endpoint,
        )
    return Response(status_code=204)
