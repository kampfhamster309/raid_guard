"""Unit tests for JWT auth and the token endpoint."""

import os
import time

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from app.auth import (
    JWT_ALGORITHM,
    JWT_SECRET,
    create_token,
    decode_token,
    verify_admin,
)
from app.main import app


# ── verify_admin ──────────────────────────────────────────────────────────────


def test_verify_admin_correct_credentials(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cr3t")
    # Reload module-level constants by patching directly
    import app.auth as auth_mod
    monkeypatch.setattr(auth_mod, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(auth_mod, "ADMIN_PASSWORD", "s3cr3t")
    assert auth_mod.verify_admin("admin", "s3cr3t") is True


def test_verify_admin_wrong_password(monkeypatch):
    import app.auth as auth_mod
    monkeypatch.setattr(auth_mod, "ADMIN_PASSWORD", "correct")
    assert auth_mod.verify_admin("admin", "wrong") is False


def test_verify_admin_wrong_username(monkeypatch):
    import app.auth as auth_mod
    monkeypatch.setattr(auth_mod, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(auth_mod, "ADMIN_PASSWORD", "pass")
    assert auth_mod.verify_admin("root", "pass") is False


def test_verify_admin_empty_password_denies_all(monkeypatch):
    import app.auth as auth_mod
    monkeypatch.setattr(auth_mod, "ADMIN_PASSWORD", "")
    assert auth_mod.verify_admin("admin", "") is False
    assert auth_mod.verify_admin("admin", "anything") is False


# ── create_token / decode_token ───────────────────────────────────────────────


def test_create_token_returns_string():
    token = create_token("admin")
    assert isinstance(token, str)
    assert len(token) > 20


def test_create_token_contains_correct_sub():
    token = create_token("admin")
    payload = pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    assert payload["sub"] == "admin"


def test_create_token_contains_exp():
    token = create_token("admin")
    payload = pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    assert "exp" in payload
    assert payload["exp"] > time.time()


def test_decode_token_valid():
    token = create_token("admin")
    assert decode_token(token) == "admin"


def test_decode_token_invalid_raises_401():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        decode_token("not.a.valid.token")
    assert exc_info.value.status_code == 401


def test_decode_token_expired_raises_401():
    from fastapi import HTTPException
    from datetime import datetime, timezone, timedelta
    payload = {"sub": "admin", "exp": datetime.now(timezone.utc) - timedelta(hours=1)}
    expired = pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    with pytest.raises(HTTPException) as exc_info:
        decode_token(expired)
    assert exc_info.value.status_code == 401


def test_decode_token_missing_sub_raises_401():
    from fastapi import HTTPException
    from datetime import datetime, timezone, timedelta
    payload = {"exp": datetime.now(timezone.utc) + timedelta(hours=1)}  # no sub
    token = pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    with pytest.raises(HTTPException) as exc_info:
        decode_token(token)
    assert exc_info.value.status_code == 401


# ── Token endpoint ────────────────────────────────────────────────────────────


def test_token_endpoint_success(monkeypatch):
    import app.auth as auth_mod
    monkeypatch.setattr(auth_mod, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(auth_mod, "ADMIN_PASSWORD", "testpass")
    with TestClient(app) as c:
        resp = c.post(
            "/api/auth/token",
            data={"username": "admin", "password": "testpass"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


def test_token_endpoint_wrong_password(monkeypatch):
    import app.auth as auth_mod
    monkeypatch.setattr(auth_mod, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(auth_mod, "ADMIN_PASSWORD", "correct")
    with TestClient(app) as c:
        resp = c.post(
            "/api/auth/token",
            data={"username": "admin", "password": "wrong"},
        )
    assert resp.status_code == 401


def test_token_endpoint_missing_fields():
    with TestClient(app) as c:
        resp = c.post("/api/auth/token", data={})
    assert resp.status_code == 422  # validation error


# ── Protected endpoint behaviour ──────────────────────────────────────────────


def test_protected_endpoint_requires_auth():
    with TestClient(app) as c:
        resp = c.get("/api/alerts")
    assert resp.status_code == 401


def test_protected_endpoint_accepts_valid_token():
    from unittest.mock import AsyncMock, MagicMock
    from app.dependencies import get_pool

    pool = MagicMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    conn.fetchval = AsyncMock(return_value=0)
    conn.fetch = AsyncMock(return_value=[])

    app.dependency_overrides[get_pool] = lambda: pool
    token = create_token("admin")
    try:
        with TestClient(app) as c:
            resp = c.get("/api/alerts", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_health_endpoint_needs_no_auth():
    with TestClient(app) as c:
        resp = c.get("/health")
    assert resp.status_code == 200
