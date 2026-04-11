"""
Unit tests for backends/homeassistant.py and routers/settings.py.
No real HTTP calls or DB connections are made.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient, ASGITransport, Response

from app.backends.homeassistant import HomeAssistantBackend
from app.main import app


# ── HomeAssistantBackend.from_env ─────────────────────────────────────────────


def test_from_env_returns_none_when_url_not_set(monkeypatch):
    monkeypatch.delenv("HA_WEBHOOK_URL", raising=False)
    assert HomeAssistantBackend.from_env() is None


def test_from_env_returns_backend_when_url_set(monkeypatch):
    monkeypatch.setenv("HA_WEBHOOK_URL", "http://ha.local/webhook/xyz")
    backend = HomeAssistantBackend.from_env()
    assert backend is not None
    assert backend.name == "homeassistant"


def test_from_env_ignores_whitespace_only_url(monkeypatch):
    monkeypatch.setenv("HA_WEBHOOK_URL", "   ")
    assert HomeAssistantBackend.from_env() is None


# ── HomeAssistantBackend.send ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_posts_correct_payload():
    backend = HomeAssistantBackend("http://ha.local/webhook/test")
    alert = {
        "id": "uuid-001",
        "severity": "critical",
        "signature": "ET MALWARE Beacon",
        "src_ip": "192.168.1.5",
        "timestamp": "2026-04-11T10:00:00+00:00",
    }

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.backends.homeassistant.httpx.AsyncClient", return_value=mock_client):
        await backend.send(alert)

    mock_client.post.assert_awaited_once()
    url, kwargs = mock_client.post.call_args[0][0], mock_client.post.call_args[1]
    assert url == "http://ha.local/webhook/test"
    payload = kwargs["json"]
    assert payload["severity"] == "critical"
    assert payload["signature"] == "ET MALWARE Beacon"
    assert payload["src_ip"] == "192.168.1.5"
    assert payload["alert_id"] == "uuid-001"


@pytest.mark.asyncio
async def test_send_raises_on_http_error():
    backend = HomeAssistantBackend("http://ha.local/webhook/test")

    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.raise_for_status = MagicMock(side_effect=Exception("HTTP 500"))

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.backends.homeassistant.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(Exception, match="HTTP 500"):
            await backend.send({"id": "x", "severity": "critical"})


# ── GET /api/settings/push-threshold ─────────────────────────────────────────


def _make_pool(fetchrow_return=None):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    conn.execute = AsyncMock()
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


@pytest.mark.asyncio
async def test_get_push_threshold_returns_default():
    pool, _ = _make_pool(fetchrow_return=None)
    from app.dependencies import get_pool
    from app.auth import require_auth
    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[require_auth] = lambda: "admin"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/settings/push-threshold")

    app.dependency_overrides = {}
    assert resp.status_code == 200
    assert resp.json()["threshold"] == "warning"


@pytest.mark.asyncio
async def test_get_push_threshold_returns_stored_value():
    pool, _ = _make_pool(fetchrow_return={"value": "critical"})
    from app.dependencies import get_pool
    from app.auth import require_auth
    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[require_auth] = lambda: "admin"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/settings/push-threshold")

    app.dependency_overrides = {}
    assert resp.json()["threshold"] == "critical"


# ── PUT /api/settings/push-threshold ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_push_threshold_persists_valid_value():
    pool, conn = _make_pool()
    from app.dependencies import get_pool
    from app.auth import require_auth
    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[require_auth] = lambda: "admin"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put("/api/settings/push-threshold", json={"threshold": "critical"})

    app.dependency_overrides = {}
    assert resp.status_code == 200
    assert resp.json()["threshold"] == "critical"
    conn.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_push_threshold_rejects_invalid_value():
    pool, _ = _make_pool()
    from app.dependencies import get_pool
    from app.auth import require_auth
    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[require_auth] = lambda: "admin"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put("/api/settings/push-threshold", json={"threshold": "urgent"})

    app.dependency_overrides = {}
    assert resp.status_code == 422
