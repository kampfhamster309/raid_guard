"""Digests API — GET /api/digests, GET /api/digests/{id}, POST /api/digests/generate (RAID-015a)."""

from datetime import datetime
from uuid import UUID

import asyncpg
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from ..auth import require_auth
from ..dependencies import get_pool, get_redis
from ..digestor import generate_digest
from ..llm_config import get_llm_config

router = APIRouter(prefix="/api/digests", tags=["digests"])

# ── Response models ───────────────────────────────────────────────────────────


class DigestSummary(BaseModel):
    id: UUID
    created_at: datetime
    period_start: datetime
    period_end: datetime
    risk_level: str | None
    content: str


class DigestListResponse(BaseModel):
    items: list[DigestSummary]
    total: int
    limit: int
    offset: int


# ── Row converter ─────────────────────────────────────────────────────────────

_DIGEST_COLS = "id, created_at, period_start, period_end, content, risk_level"


def _row_to_digest(row) -> dict:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "period_start": row["period_start"],
        "period_end": row["period_end"],
        "content": row["content"],
        "risk_level": row["risk_level"],
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("", response_model=DigestListResponse)
async def list_digests(
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
    pool: asyncpg.Pool = Depends(get_pool),
    _: str = Depends(require_auth),
):
    """Return paginated digests ordered by creation time (newest first)."""
    async with pool.acquire() as conn:
        total: int = await conn.fetchval("SELECT COUNT(*) FROM digests")
        rows = await conn.fetch(
            f"SELECT {_DIGEST_COLS} FROM digests "
            f"ORDER BY created_at DESC LIMIT $1 OFFSET $2",
            limit,
            offset,
        )

    return DigestListResponse(
        items=[DigestSummary(**_row_to_digest(r)) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{digest_id}", response_model=DigestSummary)
async def get_digest(
    digest_id: UUID,
    pool: asyncpg.Pool = Depends(get_pool),
    _: str = Depends(require_auth),
):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT {_DIGEST_COLS} FROM digests WHERE id = $1 LIMIT 1",
            digest_id,
        )

    if row is None:
        raise HTTPException(status_code=404, detail="Digest not found")

    return DigestSummary(**_row_to_digest(row))


@router.post("/generate")
async def generate_digest_now(
    pool: asyncpg.Pool = Depends(get_pool),
    redis_client: aioredis.Redis = Depends(get_redis),
    _: str = Depends(require_auth),
):
    """Trigger an immediate digest generation.

    Returns the new digest on success (200), 204 if the period has too few
    alerts to generate a meaningful digest, or 422 if the LLM is not
    configured.
    """
    cfg = await get_llm_config(pool)
    if not cfg["url"] or not cfg["model"]:
        raise HTTPException(
            status_code=422,
            detail="LM Studio URL and model must be configured before generating a digest.",
        )

    result = await generate_digest(pool, redis_client)
    if result is None:
        return Response(status_code=204)
    return result
