"""Pi-hole v6 DNS sinkhole API (RAID-016).

Endpoints
---------
GET  /api/pihole/settings              Pi-hole connection settings (no password in response)
PUT  /api/pihole/settings              Update URL / password / enabled flag
GET  /api/pihole/blocklist             List all exact deny-list domains from Pi-hole
POST /api/pihole/block                 Add a domain to Pi-hole's deny list
DELETE /api/pihole/block/{domain}      Remove a domain from Pi-hole's deny list
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from ..auth import require_admin, require_auth
from ..dependencies import get_pool
from ..pihole import (
    PiholeError,
    block_domain,
    get_pihole_config,
    list_blocked_domains,
    unblock_domain,
)

router = APIRouter(prefix="/api/pihole", tags=["pihole"])


# ── Response / request models ─────────────────────────────────────────────────


class PiholeSettingsResponse(BaseModel):
    url: str
    enabled: bool
    configured: bool  # True when both url and password are available


class PiholeSettingsRequest(BaseModel):
    url: str
    enabled: bool
    password: str = ""  # if empty, keep existing stored password


class BlockedDomain(BaseModel):
    domain: str
    comment: str | None
    added_at: int | None  # Unix timestamp from Pi-hole
    enabled: bool


class BlockRequest(BaseModel):
    domain: str
    comment: str = "Blocked by raid_guard"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _pihole_502(exc: PiholeError) -> HTTPException:
    return HTTPException(status_code=502, detail=str(exc))


# ── Settings ──────────────────────────────────────────────────────────────────


@router.get("/settings", response_model=PiholeSettingsResponse)
async def get_settings(
    pool=Depends(get_pool),
    _: str = Depends(require_auth),
):
    """Return Pi-hole connection settings (password is never returned)."""
    cfg = await get_pihole_config(pool)
    return PiholeSettingsResponse(
        url=cfg["url"],
        enabled=cfg["enabled"],
        configured=bool(cfg["url"] and cfg["password"]),
    )


@router.put("/settings", response_model=PiholeSettingsResponse)
async def update_settings(
    body: PiholeSettingsRequest,
    pool=Depends(get_pool),
    _: str = Depends(require_admin),
):
    """Persist Pi-hole connection settings.

    If ``password`` is omitted or empty, the stored password is unchanged.
    """
    updates: dict[str, str] = {
        "pihole_url":     body.url.strip(),
        "pihole_enabled": "true" if body.enabled else "false",
    }
    if body.password:
        updates["pihole_password"] = body.password

    async with pool.acquire() as conn:
        for key, value in updates.items():
            await conn.execute(
                "INSERT INTO config(key, value) VALUES($1, $2) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                key, value,
            )

    # Re-read to reflect the full current config (password may be from env var)
    cfg = await get_pihole_config(pool)
    return PiholeSettingsResponse(
        url=cfg["url"],
        enabled=cfg["enabled"],
        configured=bool(cfg["url"] and cfg["password"]),
    )


# ── Blocklist ─────────────────────────────────────────────────────────────────


@router.get("/blocklist", response_model=list[BlockedDomain])
async def get_blocklist(
    pool=Depends(get_pool),
    _: str = Depends(require_auth),
):
    """Return all exact deny-list domains from Pi-hole."""
    cfg = await get_pihole_config(pool)
    if not cfg["enabled"]:
        raise HTTPException(status_code=422, detail="Pi-hole integration is disabled")
    if not cfg["url"] or not cfg["password"]:
        raise HTTPException(status_code=422, detail="Pi-hole is not configured")
    try:
        domains = await list_blocked_domains(cfg["url"], cfg["password"])
    except PiholeError as exc:
        raise _pihole_502(exc)
    return [BlockedDomain(**d) for d in domains]


# ── Block / unblock ───────────────────────────────────────────────────────────


@router.post("/block", response_model=BlockedDomain)
async def add_block(
    body: BlockRequest,
    pool=Depends(get_pool),
    _: str = Depends(require_admin),
):
    """Add a domain to Pi-hole's exact deny list."""
    domain = body.domain.strip().lower()
    if not domain:
        raise HTTPException(status_code=422, detail="domain must not be empty")

    cfg = await get_pihole_config(pool)
    if not cfg["enabled"]:
        raise HTTPException(status_code=422, detail="Pi-hole integration is disabled")
    if not cfg["url"] or not cfg["password"]:
        raise HTTPException(status_code=422, detail="Pi-hole is not configured")

    try:
        await block_domain(cfg["url"], cfg["password"], domain, body.comment)
    except PiholeError as exc:
        raise _pihole_502(exc)

    return BlockedDomain(domain=domain, comment=body.comment, added_at=None, enabled=True)


@router.delete("/block/{domain}", status_code=204)
async def remove_block(
    domain: str,
    pool=Depends(get_pool),
    _: str = Depends(require_admin),
):
    """Remove a domain from Pi-hole's exact deny list."""
    cfg = await get_pihole_config(pool)
    if not cfg["enabled"]:
        raise HTTPException(status_code=422, detail="Pi-hole integration is disabled")
    if not cfg["url"] or not cfg["password"]:
        raise HTTPException(status_code=422, detail="Pi-hole is not configured")

    try:
        await unblock_domain(cfg["url"], cfg["password"], domain)
    except PiholeError as exc:
        raise _pihole_502(exc)

    return Response(status_code=204)
