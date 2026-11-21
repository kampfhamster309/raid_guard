"""
Edition feature flag — ``basic`` (default) or ``pro``.

Stored in the ``config`` table under the ``edition`` key and toggled from the
Config page.  Pro-only endpoints depend on :func:`require_pro`, which returns
403 while the edition is ``basic``.
"""

from fastapi import Depends, HTTPException

from .dependencies import get_pool

EDITION_KEY = "edition"
EDITION_BASIC = "basic"
EDITION_PRO = "pro"
VALID_EDITIONS = {EDITION_BASIC, EDITION_PRO}


async def get_edition(pool) -> str:
    """Return the current edition; falls back to ``basic`` if unset or the DB is unreachable."""
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT value FROM config WHERE key = $1", EDITION_KEY)
    except Exception:
        return EDITION_BASIC
    value = row["value"] if row else EDITION_BASIC
    return value if value in VALID_EDITIONS else EDITION_BASIC


async def set_edition(pool, edition: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO config(key, value) VALUES($1, $2) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            EDITION_KEY,
            edition,
        )


async def require_pro(pool=Depends(get_pool)) -> None:
    """FastAPI dependency: 403 unless the pro edition is enabled."""
    if await get_edition(pool) != EDITION_PRO:
        raise HTTPException(status_code=403, detail="This feature requires the pro edition")
