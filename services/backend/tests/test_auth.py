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
    decode_token,
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


# ── create_token / decode_token ───────────────────────────────────────────────


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


def test_decode_token_valid():
    token = create_token("admin", "admin")
    assert decode_token(token) == "admin"


def test_decode_token_invalid_raises_401():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        decode_token("not.a.valid.token")
    assert exc_info.value.status_code == 401


def test_decode_token_expired_raises_401():
    from fastapi import HTTPException
    from datetime import datetime, timezone, timedelta
    payload = {"sub": "admin", "role": "admin",
               "exp": datetime.now(timezone.utc) - timedelta(hours=1)}
    expired = pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    with pytest.raises(HTTPException) as exc_info:
        decode_token(expired)
    assert exc_info.value.status_code == 401


def test_decode_token_missing_sub_raises_401():
    from fastapi import HTTPException
    from datetime import datetime, timezone, timedelta
    payload = {"role": "admin", "exp": datetime.now(timezone.utc) + timedelta(hours=1)}
    token = pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    with pytest.raises(HTTPException) as exc_info:
        decode_token(token)
    assert exc_info.value.status_code == 401


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
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    app.dependency_overrides[get_pool] = lambda: pool
    token = create_token("admin", "admin")
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
    conn.fetchrow = AsyncMock(return_value=None)
    conn.execute = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    app.dependency_overrides[get_pool] = lambda: pool
    token = create_token("admin", "admin")
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
    assert resp.status_code == 200
