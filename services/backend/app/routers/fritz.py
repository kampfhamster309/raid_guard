"""Fritzbox TR-064 device quarantine API (RAID-018).

Endpoints
---------
GET  /api/fritz/status              Fritzbox connectivity + HostFilter availability
GET  /api/fritz/blocked             List quarantined devices (from DB)
POST /api/fritz/block               Quarantine a LAN device by IP
DELETE /api/fritz/block/{ip}        Lift quarantine for a device

NOTE: This API blocks internal LAN devices from all WAN access — it does NOT
block inbound connections from external IPs (which is not supported by TR-064).
See fritz_blocker.py for the full investigation findings.
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from ..auth import require_admin, require_auth
from ..dependencies import get_pool
from ..fritz_blocker import FritzBlockerError, FritzNotInHostTableError, get_fritz_blocker

router = APIRouter(prefix="/api/fritz", tags=["fritz"])


# ── Models ────────────────────────────────────────────────────────────────────


class FritzStatus(BaseModel):
    configured: bool
    connected: bool
    host_filter_available: bool
    model: str = ""
    firmware: str = ""


class BlockedDevice(BaseModel):
    id: str
    blocked_at: str
    ip: str
    hostname: str | None
    comment: str | None


class BlockRequest(BaseModel):
    ip: str
    comment: str = ""


# ── Helpers ───────────────────────────────────────────────────────────────────


def _fritz_502(exc: FritzBlockerError) -> HTTPException:
    return HTTPException(status_code=502, detail=str(exc))


def _require_blocker():
    blocker = get_fritz_blocker()
    if blocker is None:
        raise HTTPException(
            status_code=422,
            detail="Fritzbox is not configured (FRITZ_HOST and FRITZ_PASSWORD are required)",
        )
    return blocker


# ── Status ────────────────────────────────────────────────────────────────────


@router.get("/status", response_model=FritzStatus)
async def get_status(_: str = Depends(require_auth)):
    """Check Fritzbox connectivity and whether HostFilter service is available."""
    blocker = get_fritz_blocker()
    if blocker is None:
        return FritzStatus(configured=False, connected=False, host_filter_available=False)
    try:
        info = await blocker.check_status()
        return FritzStatus(
            configured=True,
            connected=info["connected"],
            host_filter_available=info["host_filter_available"],
            model=info.get("model", ""),
            firmware=info.get("firmware", ""),
        )
    except FritzBlockerError as exc:
        return FritzStatus(configured=True, connected=False, host_filter_available=False,
                           model=str(exc))


# ── Blocked device list ───────────────────────────────────────────────────────


@router.get("/blocked", response_model=list[BlockedDevice])
async def list_blocked(
    pool=Depends(get_pool),
    _: str = Depends(require_auth),
):
    """Return all devices currently quarantined by raid_guard (sourced from DB)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id::text, blocked_at::text, ip, hostname, comment "
            "FROM fritz_blocked_devices ORDER BY blocked_at DESC"
        )
    return [BlockedDevice(**dict(r)) for r in rows]


# ── Block ─────────────────────────────────────────────────────────────────────


@router.post("/block", response_model=BlockedDevice, status_code=201)
async def block_device(
    body: BlockRequest,
    pool=Depends(get_pool),
    _: str = Depends(require_admin),
):
    """Quarantine a LAN device: block all its WAN access via Fritzbox TR-064."""
    ip = body.ip.strip()
    if not ip:
        raise HTTPException(status_code=422, detail="ip must not be empty")

    blocker = _require_blocker()

    # Resolve hostname (best-effort, before blocking so the connection is open)
    hostname = await blocker.get_hostname(ip)

    try:
        await blocker.block(ip)
    except FritzNotInHostTableError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except FritzBlockerError as exc:
        raise _fritz_502(exc)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO fritz_blocked_devices (ip, hostname, comment) "
            "VALUES ($1, $2, $3) "
            "ON CONFLICT (ip) DO UPDATE SET blocked_at = NOW(), hostname = $2, comment = $3 "
            "RETURNING id::text, blocked_at::text, ip, hostname, comment",
            ip, hostname, body.comment or None,
        )
    return BlockedDevice(**dict(row))


# ── Unblock ───────────────────────────────────────────────────────────────────


@router.delete("/block/{ip:path}", status_code=204)
async def unblock_device(
    ip: str,
    pool=Depends(get_pool),
    _: str = Depends(require_admin),
):
    """Lift quarantine for a device: restore WAN access via Fritzbox TR-064."""
    blocker = _require_blocker()

    try:
        await blocker.unblock(ip)
    except FritzNotInHostTableError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except FritzBlockerError as exc:
        raise _fritz_502(exc)

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM fritz_blocked_devices WHERE ip = $1", ip)

    return Response(status_code=204)
