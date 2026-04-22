import json
from datetime import datetime
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..auth import require_auth
from ..dependencies import get_pool
from ..enricher import enrich_single_alert
from ..llm_config import get_llm_config

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


# ── Response models ───────────────────────────────────────────────────────────


class AlertSummary(BaseModel):
    id: UUID
    timestamp: datetime
    src_ip: str | None
    dst_ip: str | None
    src_port: int | None
    dst_port: int | None
    proto: str | None
    signature: str | None
    signature_id: int | None
    category: str | None
    severity: str
    enrichment_json: dict | None


class AlertDetail(AlertSummary):
    raw_json: dict


class AlertListResponse(BaseModel):
    items: list[AlertSummary]
    total: int
    limit: int
    offset: int


# ── Row converters ────────────────────────────────────────────────────────────


def _json_or_none(value) -> dict | None:
    """Return a dict from a JSONB value that asyncpg may give back as str or dict."""
    if value is None:
        return None
    return json.loads(value) if isinstance(value, str) else value


def _ip_str(value) -> str | None:
    """asyncpg decodes INET as ipaddress objects; str() gives the bare address."""
    return str(value) if value is not None else None


def _row_to_summary(row) -> dict:
    return {
        "id": row["id"],
        "timestamp": row["timestamp"],
        "src_ip": _ip_str(row["src_ip"]),
        "dst_ip": _ip_str(row["dst_ip"]),
        "src_port": row["src_port"],
        "dst_port": row["dst_port"],
        "proto": row["proto"],
        "signature": row["signature"],
        "signature_id": row["signature_id"],
        "category": row["category"],
        "severity": row["severity"],
        "enrichment_json": _json_or_none(row["enrichment_json"]),
    }


def _row_to_detail(row) -> dict:
    d = _row_to_summary(row)
    d["raw_json"] = _json_or_none(row["raw_json"]) or {}
    return d


# ── Query builder ─────────────────────────────────────────────────────────────


def _build_where(
    severity: str | None,
    src_ip: str | None,
    after: datetime | None,
    before: datetime | None,
) -> tuple[str, list]:
    conditions: list[str] = []
    args: list = []

    if severity:
        args.append(severity)
        conditions.append(f"severity = ${len(args)}::severity_level")
    if src_ip:
        args.append(src_ip)
        conditions.append(f"src_ip = ${len(args)}::inet")
    if after:
        args.append(after)
        conditions.append(f"timestamp >= ${len(args)}")
    if before:
        args.append(before)
        conditions.append(f"timestamp < ${len(args)}")

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    return where, args


# ── Endpoints ─────────────────────────────────────────────────────────────────

_LIST_COLS = (
    "id, timestamp, src_ip, dst_ip, src_port, dst_port, "
    "proto, signature, signature_id, category, severity, enrichment_json"
)
_DETAIL_COLS = _LIST_COLS + ", raw_json"


@router.get("", response_model=AlertListResponse)
async def list_alerts(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    severity: str | None = Query(None, pattern="^(info|warning|critical)$"),
    src_ip: str | None = Query(None),
    after: datetime | None = Query(None),
    before: datetime | None = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
    _: str = Depends(require_auth),
):
    where, args = _build_where(severity, src_ip, after, before)

    async with pool.acquire() as conn:
        total: int = await conn.fetchval(
            f"SELECT COUNT(*) FROM alerts{where}", *args
        )
        rows = await conn.fetch(
            f"SELECT {_LIST_COLS} FROM alerts{where} "
            f"ORDER BY timestamp DESC LIMIT {limit} OFFSET {offset}",
            *args,
        )

    return AlertListResponse(
        items=[AlertSummary(**_row_to_summary(r)) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{alert_id}", response_model=AlertDetail)
async def get_alert(
    alert_id: UUID,
    pool: asyncpg.Pool = Depends(get_pool),
    _: str = Depends(require_auth),
):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT {_DETAIL_COLS} FROM alerts WHERE id = $1 "
            "ORDER BY timestamp DESC LIMIT 1",
            alert_id,
        )

    if row is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return AlertDetail(**_row_to_detail(row))


class EnrichmentResult(BaseModel):
    summary: str
    severity_reasoning: str
    recommended_action: str


@router.post("/{alert_id}/enrich", response_model=EnrichmentResult)
async def enrich_alert(
    alert_id: UUID,
    pool: asyncpg.Pool = Depends(get_pool),
    _: str = Depends(require_auth),
):
    cfg = await get_llm_config(pool)
    if not cfg["url"] or not cfg["model"]:
        raise HTTPException(status_code=422, detail="LLM not configured")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT {_DETAIL_COLS} FROM alerts WHERE id = $1 "
            "ORDER BY timestamp DESC LIMIT 1",
            alert_id,
        )

    if row is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert_dict = _row_to_detail(row)
    enrichment = await enrich_single_alert(
        alert_dict,
        cfg["url"],
        cfg["model"],
        float(cfg["timeout"]),
        int(cfg["max_tokens"]),
    )

    if enrichment is None:
        raise HTTPException(status_code=504, detail="LLM enrichment failed or timed out")

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE alerts SET enrichment_json = $1::jsonb WHERE id = $2::uuid",
            json.dumps(enrichment),
            alert_id,
        )

    return EnrichmentResult(**enrichment)
