"""
Settings API — configurable runtime parameters (RAID-010+).

Currently exposes one setting: the push notification threshold.  Additional
settings (LM Studio URL, retention windows, etc.) will be added in later
tickets following the same pattern.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import require_auth
from ..dependencies import get_pool

router = APIRouter(prefix="/api/settings", tags=["settings"])

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
