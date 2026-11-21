"""
Pro-edition API.  Every endpoint here returns 403 unless the edition is ``pro``.

Endpoints
---------
POST /api/pro/traceroute       Visual traceroute toward a public IP
GET  /api/pro/geoip            GeoIP database status
POST /api/pro/geoip/update     Force a GeoIP database re-download (admin)
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import geoip
from ..auth import require_admin, require_auth
from ..edition import require_pro
from ..traceroute import TracerouteError, trace

router = APIRouter(prefix="/api/pro", tags=["pro"], dependencies=[Depends(require_pro)])


class TracerouteRequest(BaseModel):
    target: str


class Geo(BaseModel):
    lat: float
    lon: float
    city: str | None = None
    region: str | None = None
    country: str | None = None
    country_code: str | None = None


class Asn(BaseModel):
    number: int
    org: str | None = None


class Hop(BaseModel):
    hop: int
    ip: str | None
    hostname: str | None
    rtt_ms: float | None
    private: bool
    geo: Geo | None
    asn: Asn | None


class TracerouteResponse(BaseModel):
    target: str
    reached: bool
    hops: list[Hop]
    trailing_timeouts: int
    geo_available: bool
    duration_ms: int


@router.post("/traceroute", response_model=TracerouteResponse)
async def post_traceroute(body: TracerouteRequest, _=Depends(require_auth)):
    try:
        return await trace(body.target)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except TracerouteError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


class GeoIpStatus(BaseModel):
    available: bool
    city_db_updated: str | None
    asn_db_updated: str | None
    updating: bool
    last_error: str | None


@router.get("/geoip", response_model=GeoIpStatus)
async def get_geoip_status(_=Depends(require_auth)):
    return geoip.status()


@router.post("/geoip/update", response_model=GeoIpStatus, status_code=202)
async def post_geoip_update(_=Depends(require_admin)):
    geoip.request_update(force=True)
    return geoip.status()
