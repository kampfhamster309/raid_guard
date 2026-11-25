"""Read an on/off flag from the ``config`` table."""

import logging

logger = logging.getLogger(__name__)


async def config_flag(pool, key: str, default: bool = True) -> bool:
    """Return the flag stored under *key*; anything but ``"false"`` is on.

    Falls back to *default* when there is no pool, no row, or the DB is down,
    so a DB outage never silences notifications.
    """
    if pool is None:
        return default
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT value FROM config WHERE key = $1", key)
    except Exception as exc:
        logger.warning("Could not read %s from DB: %s; using %s", key, exc, default)
        return default
    return row["value"].lower() != "false" if row else default
