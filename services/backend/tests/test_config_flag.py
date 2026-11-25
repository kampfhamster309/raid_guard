"""Unit tests for config_flag — the on/off switch reader used by notification backends."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config_flag import config_flag


def _pool(row):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=row)
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


@pytest.mark.asyncio
async def test_true_when_no_pool():
    assert await config_flag(None, "ha_enabled") is True


@pytest.mark.asyncio
async def test_true_when_no_row():
    assert await config_flag(_pool(None), "ha_enabled") is True


@pytest.mark.asyncio
async def test_false_when_config_says_false():
    assert await config_flag(_pool({"value": "False"}), "ha_enabled") is False


@pytest.mark.asyncio
async def test_default_when_db_raises():
    pool = MagicMock()
    pool.acquire.side_effect = Exception("DB down")
    assert await config_flag(pool, "ha_enabled") is True
