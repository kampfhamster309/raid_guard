from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import asyncpg

from ..auth import require_admin, require_auth
from ..dependencies import get_pool
from ..rule_manager import (
    ET_OPEN_CATEGORIES,
    get_disabled_categories,
    reload_suricata,
    set_disabled_categories,
)

router = APIRouter(prefix="/api/rules", tags=["rules"])


# ── Response models ───────────────────────────────────────────────────────────


class RuleCategory(BaseModel):
    id: str
    name: str
    description: str
    enabled: bool


class CategoryListResponse(BaseModel):
    categories: list[RuleCategory]


class UpdateCategoriesRequest(BaseModel):
    disabled: list[str]


class ReloadResponse(BaseModel):
    message: str


# ── Helpers ───────────────────────────────────────────────────────────────────


def _build_response(disabled: set[str]) -> CategoryListResponse:
    return CategoryListResponse(
        categories=[
            RuleCategory(
                id=c["id"],
                name=c["name"],
                description=c["description"],
                enabled=c["id"] not in disabled,
            )
            for c in ET_OPEN_CATEGORIES
        ]
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/categories", response_model=CategoryListResponse)
async def list_categories(
    _: str = Depends(require_auth),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Return all ET Open rule categories with their current enabled/disabled status."""
    disabled = set(await get_disabled_categories(pool))
    return _build_response(disabled)


@router.put("/categories", response_model=CategoryListResponse)
async def update_categories(
    body: UpdateCategoriesRequest,
    _: str = Depends(require_admin),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Persist the set of disabled rule categories to the DB and update disable.conf.

    Does NOT reload the running Suricata process — call POST /api/rules/reload
    to apply the change to the live engine.
    """
    try:
        await set_disabled_categories(pool, body.disabled)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _build_response(set(body.disabled))


@router.post("/reload", response_model=ReloadResponse)
async def trigger_reload(
    _: str = Depends(require_admin),
):
    """Run suricata-update in the Suricata container and send SIGHUP to reload rules.

    Requires the Docker socket to be mounted in the backend container
    (``/var/run/docker.sock``).  May take up to ~60 s if rules need downloading.
    """
    try:
        message = await reload_suricata()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return ReloadResponse(message=message)
