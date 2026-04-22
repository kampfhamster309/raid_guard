"""Tuning suggestions API — GET/POST /api/tuning/… (RAID-015b)."""

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..auth import require_admin, require_auth
from ..dependencies import get_pool
from ..llm_config import get_llm_config
from ..noisetuner import _row_to_dict, generate_tuning_suggestions
from ..rule_manager import apply_suppression, apply_threshold

router = APIRouter(prefix="/api/tuning", tags=["tuning"])

_COLS = (
    "id, created_at, signature, signature_id, "
    "hit_count, assessment, action, status, confirmed_at, "
    "threshold_count, threshold_seconds, threshold_track, threshold_type"
)


# ── Response models ───────────────────────────────────────────────────────────


class TuningSuggestion(BaseModel):
    id: UUID
    created_at: datetime
    signature: str
    signature_id: int | None
    hit_count: int
    assessment: str
    action: str
    status: str
    confirmed_at: datetime | None
    threshold_count: int | None = None
    threshold_seconds: int | None = None
    threshold_track: str | None = None
    threshold_type: str | None = None


class ConfirmBody(BaseModel):
    threshold_count: int = Field(default=5, ge=1)
    threshold_seconds: int = Field(default=60, ge=1)
    threshold_track: Literal["by_src", "by_dst"] = "by_src"
    threshold_type: Literal["limit", "threshold", "both"] = "limit"


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("", response_model=list[TuningSuggestion])
async def list_suggestions(
    pool: asyncpg.Pool = Depends(get_pool),
    _: str = Depends(require_auth),
):
    """Return all pending tuning suggestions, newest first."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT {_COLS} FROM tuning_suggestions "
            "WHERE status = 'pending' ORDER BY hit_count DESC, created_at DESC"
        )
    return [TuningSuggestion(**_row_to_dict(r)) for r in rows]


@router.post("/{suggestion_id}/confirm", response_model=TuningSuggestion)
async def confirm_suggestion(
    suggestion_id: UUID,
    body: ConfirmBody | None = None,
    pool: asyncpg.Pool = Depends(get_pool),
    _: str = Depends(require_admin),
):
    """Confirm a tuning suggestion.

    - ``suppress``: writes a Suricata suppress directive and reloads rules.
    - ``threshold-adjust``: writes a threshold directive using ``body`` params
      (defaults: limit/by_src/count=5/seconds=60 if body is omitted).
    - ``keep``: marks confirmed with no file changes.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT {_COLS} FROM tuning_suggestions WHERE id = $1 LIMIT 1",
            suggestion_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Suggestion not found")
        if row["status"] != "pending":
            raise HTTPException(
                status_code=409,
                detail=f"Suggestion is already {row['status']}",
            )

        now = datetime.now(timezone.utc)
        updated = await conn.fetchrow(
            f"UPDATE tuning_suggestions SET status = 'confirmed', confirmed_at = $1 "
            f"WHERE id = $2 RETURNING {_COLS}",
            now,
            suggestion_id,
        )

    import logging
    _log = logging.getLogger(__name__)

    if row["action"] == "suppress" and row["signature_id"] is not None:
        try:
            await apply_suppression(row["signature_id"])
        except RuntimeError as exc:
            _log.warning("Tuning: suppression written but reload failed: %s", exc)

    elif row["action"] == "threshold-adjust" and row["signature_id"] is not None:
        params = body or ConfirmBody()
        try:
            await apply_threshold(
                row["signature_id"],
                params.threshold_count,
                params.threshold_seconds,
                params.threshold_track,
                params.threshold_type,
            )
        except RuntimeError as exc:
            _log.warning("Tuning: threshold written but reload failed: %s", exc)

    return TuningSuggestion(**_row_to_dict(updated))


@router.post("/{suggestion_id}/dismiss", response_model=TuningSuggestion)
async def dismiss_suggestion(
    suggestion_id: UUID,
    pool: asyncpg.Pool = Depends(get_pool),
    _: str = Depends(require_admin),
):
    """Dismiss a tuning suggestion without applying any change."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT {_COLS} FROM tuning_suggestions WHERE id = $1 LIMIT 1",
            suggestion_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Suggestion not found")
        if row["status"] != "pending":
            raise HTTPException(
                status_code=409,
                detail=f"Suggestion is already {row['status']}",
            )
        updated = await conn.fetchrow(
            f"UPDATE tuning_suggestions SET status = 'dismissed' "
            f"WHERE id = $1 RETURNING {_COLS}",
            suggestion_id,
        )
    return TuningSuggestion(**_row_to_dict(updated))


@router.post("/run")
async def run_tuner(
    pool: asyncpg.Pool = Depends(get_pool),
    _: str = Depends(require_admin),
):
    """Trigger an immediate tuning analysis.

    Returns the list of new suggestions (200), an empty list if skipped
    (not enough data or no new noisy signatures), or 422 if the LLM is
    not configured.
    """
    cfg = await get_llm_config(pool)
    if not cfg["url"] or not cfg["model"]:
        raise HTTPException(
            status_code=422,
            detail="LM Studio URL and model must be configured before running the tuner.",
        )

    result = await generate_tuning_suggestions(pool)
    if result is None:
        return Response(status_code=204)
    return result
