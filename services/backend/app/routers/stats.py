from datetime import datetime

import asyncpg
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth import require_auth
from ..dependencies import get_pool

router = APIRouter(prefix="/api", tags=["stats"])


class HourlyCount(BaseModel):
    hour: datetime
    count: int


class TopItem(BaseModel):
    name: str
    count: int


class StatsResponse(BaseModel):
    total_alerts_24h: int
    alerts_per_hour: list[HourlyCount]
    top_src_ips: list[TopItem]
    top_signatures: list[TopItem]


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    pool: asyncpg.Pool = Depends(get_pool),
    _: str = Depends(require_auth),
):
    async with pool.acquire() as conn:
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM alerts "
            "WHERE timestamp > NOW() - INTERVAL '24 hours'"
        ) or 0

        hourly_rows = await conn.fetch(
            "SELECT date_trunc('hour', timestamp) AS hour, COUNT(*) AS count "
            "FROM alerts WHERE timestamp > NOW() - INTERVAL '24 hours' "
            "GROUP BY hour ORDER BY hour"
        )

        ip_rows = await conn.fetch(
            "SELECT host(src_ip) AS name, COUNT(*) AS count "
            "FROM alerts WHERE timestamp > NOW() - INTERVAL '24 hours' "
            "AND src_ip IS NOT NULL "
            "GROUP BY src_ip ORDER BY count DESC LIMIT 10"
        )

        sig_rows = await conn.fetch(
            "SELECT signature AS name, COUNT(*) AS count "
            "FROM alerts WHERE timestamp > NOW() - INTERVAL '24 hours' "
            "AND signature IS NOT NULL "
            "GROUP BY signature ORDER BY count DESC LIMIT 10"
        )

    return StatsResponse(
        total_alerts_24h=total,
        alerts_per_hour=[
            HourlyCount(hour=r["hour"], count=r["count"]) for r in hourly_rows
        ],
        top_src_ips=[TopItem(name=r["name"], count=r["count"]) for r in ip_rows],
        top_signatures=[TopItem(name=r["name"], count=r["count"]) for r in sig_rows],
    )
