"""Unit tests for JWT auth and the /api/auth/token endpoint (RAID-020)."""

import time
from unittest.mock import AsyncMock, MagicMock

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from app.auth import (
    JWT_ALGORITHM,
    JWT_SECRET,
    create_token,
    record_failure,
    user_from_token,
    hash_password,
    verify_password,
)
from app.main import app


# ── Password helpers ──────────────────────────────────────────────────────────


def test_hash_password_returns_bcrypt_hash():
    h = hash_password("s3cr3t")
    assert h.startswith("$2")


def test_verify_password_correct():
    h = hash_password("correct")
    assert verify_password("correct", h) is True


def test_verify_password_wrong():
    h = hash_password("correct")
    assert verify_password("wrong", h) is False


# ── create_token / user_from_token ───────────────────────────────────────────────


def test_create_token_returns_string():
    token = create_token("admin", "admin")
    assert isinstance(token, str) and len(token) > 20


def test_create_token_contains_correct_sub_and_role():
    token = create_token("felix", "viewer")
    payload = pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    assert payload["sub"] == "felix"
    assert payload["role"] == "viewer"


def test_create_token_contains_exp():
    token = create_token("admin", "admin")
    payload = pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    assert "exp" in payload and payload["exp"] > time.time()


def _pool_with_row(row):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=row)
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


_HASH = hash_password("correct-horse")
_ADMIN_ROW = {"username": "admin", "password_hash": _HASH, "role": "admin"}


@pytest.mark.asyncio
async def test_user_from_token_valid_takes_role_from_db():
    token = create_token("admin", "viewer", _HASH)  # stale role claim
    user = await user_from_token(_pool_with_row(_ADMIN_ROW), token)
    assert (user.username, user.role) == ("admin", "admin")


@pytest.mark.asyncio
async def test_user_from_token_rejects_deleted_user():
    from fastapi import HTTPException
    token = create_token("admin", "admin", _HASH)
    with pytest.raises(HTTPException) as exc_info:
        await user_from_token(_pool_with_row(None), token)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_user_from_token_rejects_token_from_before_password_change():
    from fastapi import HTTPException
    token = create_token("admin", "admin", hash_password("old-password"))
    with pytest.raises(HTTPException) as exc_info:
        await user_from_token(_pool_with_row(_ADMIN_ROW), token)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_user_from_token_trusts_claims_when_db_down():
    pool = MagicMock()
    pool.acquire.side_effect = OSError("db down")
    user = await user_from_token(pool, create_token("admin", "viewer", _HASH))
    assert (user.username, user.role) == ("admin", "viewer")


@pytest.mark.asyncio
async def test_user_from_token_invalid_raises_401():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await user_from_token(_pool_with_row(_ADMIN_ROW), "not.a.valid.token")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_user_from_token_expired_raises_401():
    from fastapi import HTTPException
    from datetime import datetime, timezone, timedelta
    payload = {"sub": "admin", "role": "admin",
               "exp": datetime.now(timezone.utc) - timedelta(hours=1)}
    expired = pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    with pytest.raises(HTTPException) as exc_info:
        await user_from_token(_pool_with_row(_ADMIN_ROW), expired)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_user_from_token_missing_sub_raises_401():
    from fastapi import HTTPException
    from datetime import datetime, timezone, timedelta
    payload = {"role": "admin", "exp": datetime.now(timezone.utc) + timedelta(hours=1)}
    token = pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    with pytest.raises(HTTPException) as exc_info:
        await user_from_token(_pool_with_row(_ADMIN_ROW), token)
    assert exc_info.value.status_code == 401


def test_verify_password_over_72_bytes_is_false_not_error():
    assert verify_password("x" * 100, _HASH) is False


# ── Token endpoint ────────────────────────────────────────────────────────────


def _make_pool_with_user(username: str = "admin", password: str = "testpass",
                         role: str = "admin"):
    """Return a mock pool whose conn returns a users row for the given credentials."""
    hashed = hash_password(password)
    user_row = {"username": username, "password_hash": hashed, "role": role}

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=user_row)
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


def test_token_endpoint_success():
    from app.dependencies import get_pool
    pool = _make_pool_with_user("admin", "testpass", "admin")
    app.dependency_overrides[get_pool] = lambda: pool
    try:
        with TestClient(app) as c:
            resp = c.post("/api/auth/token",
                          data={"username": "admin", "password": "testpass"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    # Token should carry the role
    payload = pyjwt.decode(body["access_token"], JWT_SECRET, algorithms=[JWT_ALGORITHM])
    assert payload["role"] == "admin"


def test_token_endpoint_wrong_password():
    from app.dependencies import get_pool
    # Return hashed "correct", but user submits "wrong"
    hashed = hash_password("correct")
    user_row = {"username": "admin", "password_hash": hashed, "role": "admin"}
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=user_row)
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    app.dependency_overrides[get_pool] = lambda: pool
    try:
        with TestClient(app) as c:
            resp = c.post("/api/auth/token",
                          data={"username": "admin", "password": "wrong"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 401


def test_token_endpoint_unknown_user():
    from app.dependencies import get_pool
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)  # user not found
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    app.dependency_overrides[get_pool] = lambda: pool
    try:
        with TestClient(app) as c:
            resp = c.post("/api/auth/token",
                          data={"username": "nobody", "password": "pass"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 401


def test_token_endpoint_missing_fields():
    with TestClient(app) as c:
        resp = c.post("/api/auth/token", data={})
    assert resp.status_code == 422


# ── Protected endpoint behaviour ──────────────────────────────────────────────


def test_protected_endpoint_requires_auth():
    with TestClient(app) as c:
        resp = c.get("/api/alerts")
    assert resp.status_code == 401


def test_protected_endpoint_accepts_valid_token():
    from app.dependencies import get_pool

    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=0)
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock(return_value=_ADMIN_ROW)
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    app.dependency_overrides[get_pool] = lambda: pool
    token = create_token("admin", "admin", _HASH)
    try:
        with TestClient(app) as c:
            resp = c.get("/api/alerts", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_write_endpoint_requires_admin_role():
    """A token with viewer role must receive 403 on write endpoints."""
    token = create_token("viewer_user", "viewer")
    with TestClient(app) as c:
        resp = c.put(
            "/api/settings/push-threshold",
            json={"threshold": "warning"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 403


def test_write_endpoint_accepts_admin_role():
    from app.dependencies import get_pool

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=_ADMIN_ROW)
    conn.execute = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    app.dependency_overrides[get_pool] = lambda: pool
    token = create_token("admin", "admin", _HASH)
    try:
        with TestClient(app) as c:
            resp = c.put(
                "/api/settings/push-threshold",
                json={"threshold": "warning"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_health_endpoint_needs_no_auth():
    with TestClient(app) as c:
        resp = c.get("/health")
    # Health is unauthenticated — must not return 401/403 regardless of service state
    assert resp.status_code not in (401, 403)


def test_token_endpoint_returns_429_after_repeated_failures():
    from app.dependencies import get_pool
    for _ in range(5):
        record_failure("locked-out")
    app.dependency_overrides[get_pool] = lambda: _pool_with_row(None)
    try:
        with TestClient(app) as c:
            resp = c.post("/api/auth/token", data={"username": "locked-out", "password": "x"})
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 429
