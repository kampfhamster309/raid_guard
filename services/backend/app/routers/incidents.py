"""Incidents API — GET /api/incidents and GET /api/incidents/{id} (RAID-015)."""

from datetime import datetime
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..auth import require_auth
from ..dependencies import get_pool
from .alerts import AlertSummary, _LIST_COLS, _row_to_summary

router = APIRouter(prefix="/api/incidents", tags=["incidents"])


# ── Response models ───────────────────────────────────────────────────────────


class IncidentSummary(BaseModel):
    id: UUID
    created_at: datetime
    period_start: datetime
    period_end: datetime
    alert_ids: list[UUID]
    narrative: str | None
    risk_level: str
    name: str | None


class IncidentDetail(IncidentSummary):
    alerts: list[AlertSummary]


class IncidentListResponse(BaseModel):
    items: list[IncidentSummary]
    total: int
    limit: int
    offset: int


# ── Row converter ─────────────────────────────────────────────────────────────


def _row_to_incident(row) -> dict:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "period_start": row["period_start"],
        "period_end": row["period_end"],
        "alert_ids": list(row["alert_ids"] or []),
        "narrative": row["narrative"],
        "risk_level": row["risk_level"],
        "name": row["name"],
    }


_INCIDENT_COLS = (
    "id, created_at, period_start, period_end, alert_ids, narrative, risk_level, name"
)


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("", response_model=IncidentListResponse)
async def list_incidents(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    pool: asyncpg.Pool = Depends(get_pool),
    _: str = Depends(require_auth),
):
    async with pool.acquire() as conn:
        total: int = await conn.fetchval("SELECT COUNT(*) FROM incidents")
        rows = await conn.fetch(
            f"SELECT {_INCIDENT_COLS} FROM incidents "
            f"ORDER BY created_at DESC LIMIT $1 OFFSET $2",
            limit,
            offset,
        )

    return IncidentListResponse(
        items=[IncidentSummary(**_row_to_incident(r)) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{incident_id}", response_model=IncidentDetail)
async def get_incident(
    incident_id: UUID,
    pool: asyncpg.Pool = Depends(get_pool),
    _: str = Depends(require_auth),
):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT {_INCIDENT_COLS} FROM incidents WHERE id = $1 LIMIT 1",
            incident_id,
        )

    if row is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    incident = _row_to_incident(row)
    alert_ids = incident["alert_ids"]

    alerts: list[AlertSummary] = []
    if alert_ids:
        async with pool.acquire() as conn:
            alert_rows = await conn.fetch(
                f"SELECT {_LIST_COLS} FROM alerts "
                f"WHERE id = ANY($1::uuid[]) ORDER BY timestamp ASC",
                alert_ids,
            )
        alerts = [AlertSummary(**_row_to_summary(r)) for r in alert_rows]

    return IncidentDetail(**incident, alerts=alerts)
