"""
Settings API — configurable runtime parameters (RAID-010+).

Endpoints
---------
GET/PUT  /api/settings/push-threshold   Alert severity push threshold
GET/PUT  /api/settings/ha               Home Assistant integration toggle
POST     /api/settings/ha/test          Send a test notification to HA
"""

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import require_auth
from ..backends.homeassistant import HomeAssistantBackend
from ..dependencies import get_pool

router = APIRouter(prefix="/api/settings", tags=["settings"])

# ── Push threshold ────────────────────────────────────────────────────────────

_VALID_THRESHOLDS = {"info", "warning", "critical"}
_THRESHOLD_KEY = "push_threshold"
_THRESHOLD_DEFAULT = "warning"


class ThresholdResponse(BaseModel):
    threshold: str


class ThresholdRequest(BaseModel):
    threshold: str


@router.get("/push-threshold", response_model=ThresholdResponse)
async def get_push_threshold(
    pool=Depends(get_pool),
    _=Depends(require_auth),
):
    """Return the current alert severity push threshold."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value FROM config WHERE key = $1", _THRESHOLD_KEY
        )
    return ThresholdResponse(threshold=row["value"] if row else _THRESHOLD_DEFAULT)


@router.put("/push-threshold", response_model=ThresholdResponse)
async def set_push_threshold(
    body: ThresholdRequest,
    pool=Depends(get_pool),
    _=Depends(require_auth),
):
    """Persist the alert severity push threshold (info | warning | critical)."""
    if body.threshold not in _VALID_THRESHOLDS:
        raise HTTPException(
            status_code=422,
            detail=f"threshold must be one of: {', '.join(sorted(_VALID_THRESHOLDS))}",
        )
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO config(key, value) VALUES($1, $2) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            _THRESHOLD_KEY,
            body.threshold,
        )
    return ThresholdResponse(threshold=body.threshold)


# ── Home Assistant ────────────────────────────────────────────────────────────

_HA_ENABLED_KEY = "ha_enabled"


class HaSettingsResponse(BaseModel):
    enabled: bool
    configured: bool  # True when HA_WEBHOOK_URL env var is set


class HaSettingsRequest(BaseModel):
    enabled: bool


def _ha_configured() -> bool:
    return bool(os.environ.get("HA_WEBHOOK_URL", "").strip())


@router.get("/ha", response_model=HaSettingsResponse)
async def get_ha_settings(
    pool=Depends(get_pool),
    _=Depends(require_auth),
):
    """Return current HA integration state."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value FROM config WHERE key = $1", _HA_ENABLED_KEY
        )
    enabled = row["value"].lower() != "false" if row else True
    return HaSettingsResponse(enabled=enabled, configured=_ha_configured())


@router.put("/ha", response_model=HaSettingsResponse)
async def set_ha_settings(
    body: HaSettingsRequest,
    pool=Depends(get_pool),
    _=Depends(require_auth),
):
    """Enable or disable HA push notifications at runtime."""
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO config(key, value) VALUES($1, $2) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            _HA_ENABLED_KEY,
            str(body.enabled).lower(),
        )
    return HaSettingsResponse(enabled=body.enabled, configured=_ha_configured())


@router.post("/ha/test", status_code=200)
async def test_ha_send(
    pool=Depends(get_pool),
    _=Depends(require_auth),
):
    """Send a synthetic test notification to the configured HA webhook."""
    url = os.environ.get("HA_WEBHOOK_URL", "").strip()
    if not url:
        raise HTTPException(status_code=422, detail="HA_WEBHOOK_URL is not configured")
    dashboard_url = os.environ.get("DASHBOARD_URL", "").strip()
    backend = HomeAssistantBackend(url, dashboard_url=dashboard_url)
    try:
        await backend.send_test()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"ok": True}
