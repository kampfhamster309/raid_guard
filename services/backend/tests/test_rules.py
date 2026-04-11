"""
Unit tests for rule_manager.py and the /api/rules endpoints.
Docker interactions are always mocked — no Docker socket required.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.rule_manager import (
    ET_OPEN_CATEGORIES,
    _write_disable_conf,
    get_disabled_categories,
    set_disabled_categories,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_pool(fetchrow_return=None):
    """Return a (pool, conn) pair where pool.acquire() works as an async ctx manager."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    conn.execute = AsyncMock()
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


# ── _write_disable_conf ───────────────────────────────────────────────────────


def test_write_disable_conf_creates_file(tmp_path):
    with patch("app.rule_manager.DISABLE_CONF_PATH", tmp_path / "disable.conf"):
        _write_disable_conf(["emerging-p2p", "emerging-policy"])
        conf = (tmp_path / "disable.conf").read_text()
    assert "group:emerging-p2p" in conf
    assert "group:emerging-policy" in conf


def test_write_disable_conf_removes_file_when_empty(tmp_path):
    conf_path = tmp_path / "disable.conf"
    conf_path.write_text("group:emerging-p2p\n")
    with patch("app.rule_manager.DISABLE_CONF_PATH", conf_path):
        _write_disable_conf([])
    assert not conf_path.exists()


def test_write_disable_conf_sorted(tmp_path):
    with patch("app.rule_manager.DISABLE_CONF_PATH", tmp_path / "disable.conf"):
        _write_disable_conf(["emerging-worm", "emerging-botcc", "emerging-dns"])
        lines = (tmp_path / "disable.conf").read_text().splitlines()
    group_lines = [l for l in lines if l.startswith("group:")]
    assert group_lines == ["group:emerging-botcc", "group:emerging-dns", "group:emerging-worm"]


# ── get_disabled_categories ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_disabled_categories_returns_empty_when_no_row():
    pool, _ = _make_pool(fetchrow_return=None)
    result = await get_disabled_categories(pool)
    assert result == []


@pytest.mark.asyncio
async def test_get_disabled_categories_parses_json():
    pool, _ = _make_pool(fetchrow_return={"value": '["emerging-p2p", "emerging-info"]'})
    result = await get_disabled_categories(pool)
    assert set(result) == {"emerging-p2p", "emerging-info"}


@pytest.mark.asyncio
async def test_get_disabled_categories_handles_corrupt_value():
    pool, _ = _make_pool(fetchrow_return={"value": "not-json"})
    result = await get_disabled_categories(pool)
    assert result == []


# ── set_disabled_categories ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_disabled_categories_saves_to_db(tmp_path):
    pool, conn = _make_pool()
    with patch("app.rule_manager.DISABLE_CONF_PATH", tmp_path / "disable.conf"):
        await set_disabled_categories(pool, ["emerging-p2p"])
    conn.execute.assert_awaited_once()
    sql, key, value = conn.execute.call_args[0]
    assert key == "disabled_rule_categories"
    assert "emerging-p2p" in json.loads(value)


@pytest.mark.asyncio
async def test_set_disabled_categories_raises_for_unknown_id():
    pool, _ = _make_pool()
    with pytest.raises(ValueError, match="Unknown category IDs"):
        await set_disabled_categories(pool, ["not-a-real-category"])


@pytest.mark.asyncio
async def test_set_disabled_categories_writes_disable_conf(tmp_path):
    pool, _ = _make_pool()
    conf_path = tmp_path / "disable.conf"
    with patch("app.rule_manager.DISABLE_CONF_PATH", conf_path):
        await set_disabled_categories(pool, ["emerging-scan"])
    assert conf_path.exists()
    assert "group:emerging-scan" in conf_path.read_text()


# ── API: GET /api/rules/categories ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_categories_returns_all_categories():
    pool, _ = _make_pool(fetchrow_return=None)
    from app.dependencies import get_pool
    from app.auth import require_auth
    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[require_auth] = lambda: "admin"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/rules/categories")

    app.dependency_overrides = {}
    assert resp.status_code == 200
    assert len(resp.json()["categories"]) == len(ET_OPEN_CATEGORIES)


@pytest.mark.asyncio
async def test_list_categories_marks_disabled_correctly():
    pool, _ = _make_pool(fetchrow_return={"value": '["emerging-p2p"]'})
    from app.dependencies import get_pool
    from app.auth import require_auth
    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[require_auth] = lambda: "admin"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/rules/categories")

    app.dependency_overrides = {}
    cats = {c["id"]: c for c in resp.json()["categories"]}
    assert cats["emerging-p2p"]["enabled"] is False
    assert cats["emerging-malware"]["enabled"] is True


# ── API: PUT /api/rules/categories ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_categories_persists_and_returns(tmp_path):
    pool, _ = _make_pool()
    from app.dependencies import get_pool
    from app.auth import require_auth
    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[require_auth] = lambda: "admin"

    with patch("app.rule_manager.DISABLE_CONF_PATH", tmp_path / "disable.conf"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                "/api/rules/categories",
                json={"disabled": ["emerging-scan", "emerging-p2p"]},
            )

    app.dependency_overrides = {}
    assert resp.status_code == 200
    cats = {c["id"]: c for c in resp.json()["categories"]}
    assert cats["emerging-scan"]["enabled"] is False
    assert cats["emerging-p2p"]["enabled"] is False
    assert cats["emerging-malware"]["enabled"] is True


@pytest.mark.asyncio
async def test_update_categories_rejects_unknown_id():
    pool, _ = _make_pool()
    from app.dependencies import get_pool
    from app.auth import require_auth
    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[require_auth] = lambda: "admin"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put(
            "/api/rules/categories",
            json={"disabled": ["not-a-real-category"]},
        )

    app.dependency_overrides = {}
    assert resp.status_code == 422


# ── API: POST /api/rules/reload ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reload_returns_200_on_success():
    from app.auth import require_auth
    app.dependency_overrides[require_auth] = lambda: "admin"

    with patch("app.rule_manager._reload_suricata_sync", return_value="Rules updated."):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/rules/reload")

    app.dependency_overrides = {}
    assert resp.status_code == 200
    assert "message" in resp.json()


@pytest.mark.asyncio
async def test_reload_returns_502_on_docker_error():
    from app.auth import require_auth
    app.dependency_overrides[require_auth] = lambda: "admin"

    with patch(
        "app.rule_manager._reload_suricata_sync",
        side_effect=RuntimeError("Container not found"),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/rules/reload")

    app.dependency_overrides = {}
    assert resp.status_code == 502
    assert "Container not found" in resp.json()["detail"]
