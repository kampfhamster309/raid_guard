"""
Unit tests for the /api/users endpoints (RAID-020).
No real DB connections are made — asyncpg interactions are mocked throughout.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

from app.auth import (
    CurrentUser,
    create_token,
    get_current_user,
    hash_password,
    require_admin,
    require_auth,
)
from app.dependencies import get_pool
from app.main import app

_NOW = datetime(2026, 4, 13, 12, 0, 0, tzinfo=timezone.utc).isoformat()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_pool(fetchrow_return=None, fetch_return=None, execute_return="DELETE 1"):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    conn.fetch = AsyncMock(return_value=fetch_return or [])
    conn.execute = AsyncMock(return_value=execute_return)
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


def _override_admin():
    """Dependency override: current user is admin."""
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        username="admin", role="admin"
    )
    app.dependency_overrides[require_auth] = lambda: "admin"
    app.dependency_overrides[require_admin] = lambda: "admin"


def _override_viewer():
    """Dependency override: current user is viewer."""
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        username="viewer_user", role="viewer"
    )
    app.dependency_overrides[require_auth] = lambda: "viewer_user"
    # Do NOT override require_admin — let it raise 403 naturally.


def _clear():
    app.dependency_overrides = {}


# ── GET /api/users/me ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_me_returns_current_user():
    user_row = {"username": "admin", "role": "admin", "created_at": _NOW}
    pool, _ = _make_pool(fetchrow_return=user_row)
    app.dependency_overrides[get_pool] = lambda: pool
    _override_admin()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/users/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "admin"
        assert data["role"] == "admin"
    finally:
        _clear()


@pytest.mark.asyncio
async def test_get_me_returns_viewer_role():
    user_row = {"username": "viewer_user", "role": "viewer", "created_at": _NOW}
    pool, _ = _make_pool(fetchrow_return=user_row)
    app.dependency_overrides[get_pool] = lambda: pool
    _override_viewer()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/users/me")
        assert resp.status_code == 200
        assert resp.json()["role"] == "viewer"
    finally:
        _clear()


@pytest.mark.asyncio
async def test_get_me_returns_404_when_user_deleted():
    """Token valid but user no longer exists in DB."""
    pool, _ = _make_pool(fetchrow_return=None)
    app.dependency_overrides[get_pool] = lambda: pool
    _override_admin()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/users/me")
        assert resp.status_code == 404
    finally:
        _clear()


# ── GET /api/users ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_users_returns_all():
    rows = [
        {"username": "admin", "role": "admin", "created_at": _NOW},
        {"username": "alice", "role": "viewer", "created_at": _NOW},
    ]
    pool, _ = _make_pool(fetch_return=rows)
    app.dependency_overrides[get_pool] = lambda: pool
    _override_admin()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/users")
        assert resp.status_code == 200
        assert len(resp.json()) == 2
    finally:
        _clear()


@pytest.mark.asyncio
async def test_list_users_requires_admin():
    pool, _ = _make_pool()
    app.dependency_overrides[get_pool] = lambda: pool
    _override_viewer()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/users")
        assert resp.status_code == 403
    finally:
        _clear()


# ── POST /api/users ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_user_returns_201():
    new_row = {"username": "alice", "role": "viewer", "created_at": _NOW}
    pool, _ = _make_pool(fetchrow_return=new_row)
    app.dependency_overrides[get_pool] = lambda: pool
    _override_admin()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/api/users",
                json={"username": "alice", "password": "s3cr3t!!", "role": "viewer"},
            )
        assert resp.status_code == 201
        assert resp.json()["username"] == "alice"
    finally:
        _clear()


@pytest.mark.asyncio
async def test_create_user_rejects_short_password():
    pool, _ = _make_pool()
    app.dependency_overrides[get_pool] = lambda: pool
    _override_admin()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/api/users",
                json={"username": "alice", "password": "short", "role": "viewer"},
            )
        assert resp.status_code == 422
    finally:
        _clear()


@pytest.mark.asyncio
async def test_create_user_rejects_invalid_role():
    pool, _ = _make_pool()
    app.dependency_overrides[get_pool] = lambda: pool
    _override_admin()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/api/users",
                json={"username": "alice", "password": "s3cr3t!!", "role": "superuser"},
            )
        assert resp.status_code == 422
    finally:
        _clear()


@pytest.mark.asyncio
async def test_create_user_409_on_duplicate():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        side_effect=Exception('duplicate key value violates unique constraint "users_username_key"')
    )
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    app.dependency_overrides[get_pool] = lambda: pool
    _override_admin()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/api/users",
                json={"username": "admin", "password": "s3cr3t!!", "role": "admin"},
            )
        assert resp.status_code == 409
    finally:
        _clear()


@pytest.mark.asyncio
async def test_create_user_requires_admin():
    pool, _ = _make_pool()
    app.dependency_overrides[get_pool] = lambda: pool
    _override_viewer()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/api/users",
                json={"username": "alice", "password": "s3cr3t!!", "role": "viewer"},
            )
        assert resp.status_code == 403
    finally:
        _clear()


# ── PUT /api/users/{username}/password ────────────────────────────────────────


@pytest.mark.asyncio
async def test_change_password_admin_can_change_any():
    hashed = hash_password("oldpass1")
    pool, conn = _make_pool(fetchrow_return={"password_hash": hashed})
    app.dependency_overrides[get_pool] = lambda: pool
    _override_admin()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.put(
                "/api/users/alice/password",
                json={"current_password": "anything", "new_password": "newpass123"},
            )
        assert resp.status_code == 204
        conn.execute.assert_awaited_once()
    finally:
        _clear()


@pytest.mark.asyncio
async def test_change_password_self_requires_current_password():
    hashed = hash_password("correctpass")
    pool, conn = _make_pool(fetchrow_return={"password_hash": hashed})
    app.dependency_overrides[get_pool] = lambda: pool
    # Override get_current_user to return viewer changing own password
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        username="viewer_user", role="viewer"
    )
    app.dependency_overrides[require_auth] = lambda: "viewer_user"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.put(
                "/api/users/viewer_user/password",
                json={"current_password": "correctpass", "new_password": "newpass123"},
            )
        assert resp.status_code == 204
    finally:
        _clear()


@pytest.mark.asyncio
async def test_change_password_self_wrong_current_password():
    hashed = hash_password("correctpass")
    pool, _ = _make_pool(fetchrow_return={"password_hash": hashed})
    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        username="viewer_user", role="viewer"
    )
    app.dependency_overrides[require_auth] = lambda: "viewer_user"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.put(
                "/api/users/viewer_user/password",
                json={"current_password": "wrongpass", "new_password": "newpass123"},
            )
        assert resp.status_code == 401
    finally:
        _clear()


@pytest.mark.asyncio
async def test_change_password_viewer_cannot_change_other():
    pool, _ = _make_pool()
    app.dependency_overrides[get_pool] = lambda: pool
    _override_viewer()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.put(
                "/api/users/admin/password",
                json={"current_password": "anything", "new_password": "newpass123"},
            )
        assert resp.status_code == 403
    finally:
        _clear()


@pytest.mark.asyncio
async def test_change_password_user_not_found():
    pool, _ = _make_pool(fetchrow_return=None)
    app.dependency_overrides[get_pool] = lambda: pool
    _override_admin()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.put(
                "/api/users/nobody/password",
                json={"current_password": "anything", "new_password": "newpass123"},
            )
        assert resp.status_code == 404
    finally:
        _clear()


# ── DELETE /api/users/{username} ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_user_returns_204():
    pool, conn = _make_pool(execute_return="DELETE 1")
    app.dependency_overrides[get_pool] = lambda: pool
    _override_admin()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete("/api/users/alice")
        assert resp.status_code == 204
        conn.execute.assert_awaited_once()
    finally:
        _clear()


@pytest.mark.asyncio
async def test_delete_user_404_when_not_found():
    pool, _ = _make_pool(execute_return="DELETE 0")
    app.dependency_overrides[get_pool] = lambda: pool
    _override_admin()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete("/api/users/nobody")
        assert resp.status_code == 404
    finally:
        _clear()


@pytest.mark.asyncio
async def test_delete_user_409_self_delete():
    pool, _ = _make_pool()
    app.dependency_overrides[get_pool] = lambda: pool
    _override_admin()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete("/api/users/admin")
        assert resp.status_code == 409
    finally:
        _clear()


@pytest.mark.asyncio
async def test_delete_user_requires_admin():
    pool, _ = _make_pool()
    app.dependency_overrides[get_pool] = lambda: pool
    _override_viewer()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete("/api/users/admin")
        assert resp.status_code == 403
    finally:
        _clear()
