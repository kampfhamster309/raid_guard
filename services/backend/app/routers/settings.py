"""
Settings API — configurable runtime parameters (RAID-010+).

Endpoints
---------
GET/PUT  /api/settings/push-threshold   Alert severity push threshold
GET/PUT  /api/settings/ha               Home Assistant integration toggle
POST     /api/settings/ha/test          Send a test notification to HA
GET/PUT  /api/settings/llm              LM Studio configuration
POST     /api/settings/llm/test         Send a synthetic alert to the LLM and return the raw response
"""

import asyncio
import json
import os

from fastapi import APIRouter, Depends, HTTPException
from openai import AsyncOpenAI
from pydantic import BaseModel

from ..auth import require_auth
from ..backends.homeassistant import HomeAssistantBackend
from ..dependencies import get_pool
from ..enricher import _ENRICHMENT_RESPONSE_FORMAT, _SYSTEM_PROMPT, _build_user_prompt
from ..llm_config import get_llm_config

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


# ── LLM configuration ─────────────────────────────────────────────────────────

_LLM_DB_KEYS = {
    "url":        "lm_studio_url",
    "model":      "lm_studio_model",
    "timeout":    "lm_enrichment_timeout",
    "max_tokens": "lm_max_tokens",
}

_SYNTHETIC_ALERT = {
    "id": "00000000-0000-0000-0000-000000000000",
    "timestamp": "2026-01-01T00:00:00Z",
    "src_ip": "192.168.1.100",
    "dst_ip": "8.8.8.8",
    "dst_port": 53,
    "proto": "UDP",
    "signature": "ET INFO DNS Query to a Suspicious Domain",
    "category": "Potentially Bad Traffic",
    "severity": "info",
}


class LlmSettingsResponse(BaseModel):
    url: str
    model: str
    timeout: int
    max_tokens: int


class LlmSettingsRequest(BaseModel):
    url: str
    model: str
    timeout: int
    max_tokens: int


@router.get("/llm", response_model=LlmSettingsResponse)
async def get_llm_settings(
    pool=Depends(get_pool),
    _=Depends(require_auth),
):
    """Return the current LLM configuration (DB values override env vars)."""
    cfg = await get_llm_config(pool)
    return LlmSettingsResponse(
        url=cfg["url"],
        model=cfg["model"],
        timeout=int(cfg["timeout"]),
        max_tokens=int(cfg["max_tokens"]),
    )


@router.put("/llm", response_model=LlmSettingsResponse)
async def set_llm_settings(
    body: LlmSettingsRequest,
    pool=Depends(get_pool),
    _=Depends(require_auth),
):
    """Persist LLM configuration to the config table."""
    if not 1 <= body.timeout <= 600:
        raise HTTPException(status_code=422, detail="timeout must be between 1 and 600 seconds")
    if not 64 <= body.max_tokens <= 4096:
        raise HTTPException(status_code=422, detail="max_tokens must be between 64 and 4096")

    updates = {
        _LLM_DB_KEYS["url"]:        body.url.strip(),
        _LLM_DB_KEYS["model"]:      body.model.strip(),
        _LLM_DB_KEYS["timeout"]:    str(body.timeout),
        _LLM_DB_KEYS["max_tokens"]: str(body.max_tokens),
    }
    async with pool.acquire() as conn:
        for key, value in updates.items():
            await conn.execute(
                "INSERT INTO config(key, value) VALUES($1, $2) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                key, value,
            )
    return LlmSettingsResponse(
        url=body.url.strip(),
        model=body.model.strip(),
        timeout=body.timeout,
        max_tokens=body.max_tokens,
    )


class LlmTestResponse(BaseModel):
    content: str


@router.post("/llm/test", response_model=LlmTestResponse)
async def test_llm(
    pool=Depends(get_pool),
    _=Depends(require_auth),
):
    """Send a synthetic alert to the LLM and return the raw response content.

    Uses the currently saved DB configuration.  Save your settings before
    running a test to ensure the latest values are used.
    """
    cfg = await get_llm_config(pool)
    if not cfg["url"] or not cfg["model"]:
        raise HTTPException(
            status_code=422,
            detail="LM Studio URL and model must be configured before running a test.",
        )

    client = AsyncOpenAI(base_url=cfg["url"], api_key="lm-studio")
    timeout = float(cfg["timeout"])
    max_tokens = int(cfg["max_tokens"])

    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=cfg["model"],
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": _build_user_prompt(_SYNTHETIC_ALERT)},
                ],
                response_format=_ENRICHMENT_RESPONSE_FORMAT,
                temperature=0.1,
                max_tokens=max_tokens,
            ),
            timeout=timeout,
        )
        content = response.choices[0].message.content or ""
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"LLM request timed out after {int(timeout)}s.",
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return LlmTestResponse(content=content)
