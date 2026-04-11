"""
Unit tests for backends/homeassistant.py and the HA-related settings endpoints.
No real HTTP calls or DB connections are made.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from app.backends.homeassistant import HomeAssistantBackend
from app.main import app


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_pool(fetchrow_return=None):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    conn.execute = AsyncMock()
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


def _mock_post_ok():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)
    return mock_client


# ── from_env ──────────────────────────────────────────────────────────────────


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


def test_from_env_reads_dashboard_url(monkeypatch):
    monkeypatch.setenv("HA_WEBHOOK_URL", "http://ha.local/webhook/xyz")
    monkeypatch.setenv("DASHBOARD_URL", "http://192.168.1.5:3000")
    backend = HomeAssistantBackend.from_env()
    assert backend._dashboard_url == "http://192.168.1.5:3000"


# ── _build_payload ────────────────────────────────────────────────────────────


def test_build_payload_uses_signature_when_no_enrichment():
    backend = HomeAssistantBackend("http://ha.local/wh")
    payload = backend._build_payload({
        "id": "abc-123",
        "severity": "critical",
        "signature": "ET MALWARE Beacon",
        "src_ip": "192.168.1.5",
        "timestamp": "2026-04-11T10:00:00+00:00",
    })
    assert payload["message"] == "ET MALWARE Beacon from 192.168.1.5"
    assert payload["title"] == "raid_guard \u2014 CRITICAL"
    assert payload["alert_id"] == "abc-123"
    assert payload["url"] == ""  # no dashboard_url set


def test_build_payload_uses_ai_summary_when_available():
    backend = HomeAssistantBackend("http://ha.local/wh")
    payload = backend._build_payload({
        "id": "abc-123",
        "severity": "warning",
        "signature": "ET SCAN",
        "src_ip": "10.0.0.1",
        "enrichment": {"summary": "Port scan detected on subnet"},
    })
    assert "Port scan detected" in payload["message"]


def test_build_payload_includes_deep_link():
    backend = HomeAssistantBackend("http://ha.local/wh", dashboard_url="http://192.168.1.5:3000")
    payload = backend._build_payload({"id": "uuid-001", "severity": "info"})
    assert payload["url"] == "http://192.168.1.5:3000?alert=uuid-001"


def test_build_payload_no_url_when_dashboard_url_empty():
    backend = HomeAssistantBackend("http://ha.local/wh", dashboard_url="")
    payload = backend._build_payload({"id": "uuid-001", "severity": "info"})
    assert payload["url"] == ""


# ── _is_enabled ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_is_enabled_true_when_no_pool():
    backend = HomeAssistantBackend("http://ha.local/wh", pool=None)
    assert await backend._is_enabled() is True


@pytest.mark.asyncio
async def test_is_enabled_true_when_no_config_row():
    pool, _ = _make_pool(fetchrow_return=None)
    backend = HomeAssistantBackend("http://ha.local/wh", pool=pool)
    assert await backend._is_enabled() is True


@pytest.mark.asyncio
async def test_is_enabled_false_when_config_says_false():
    pool, _ = _make_pool(fetchrow_return={"value": "false"})
    backend = HomeAssistantBackend("http://ha.local/wh", pool=pool)
    assert await backend._is_enabled() is False


@pytest.mark.asyncio
async def test_is_enabled_true_when_db_raises():
    pool = MagicMock()
    pool.acquire.side_effect = Exception("DB down")
    backend = HomeAssistantBackend("http://ha.local/wh", pool=pool)
    assert await backend._is_enabled() is True


# ── send ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_posts_when_enabled():
    pool, _ = _make_pool(fetchrow_return=None)  # no row → enabled
    backend = HomeAssistantBackend("http://ha.local/wh", pool=pool)
    mock_client = _mock_post_ok()
    with patch("app.backends.homeassistant.httpx.AsyncClient", return_value=mock_client):
        await backend.send({"id": "x", "severity": "warning", "src_ip": "1.2.3.4"})
    mock_client.post.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_skips_when_disabled():
    pool, _ = _make_pool(fetchrow_return={"value": "false"})
    backend = HomeAssistantBackend("http://ha.local/wh", pool=pool)
    mock_client = _mock_post_ok()
    with patch("app.backends.homeassistant.httpx.AsyncClient", return_value=mock_client):
        await backend.send({"id": "x", "severity": "critical"})
    mock_client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_raises_on_http_error():
    pool, _ = _make_pool(fetchrow_return=None)
    backend = HomeAssistantBackend("http://ha.local/wh", pool=pool)
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(side_effect=Exception("HTTP 500"))
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)
    with patch("app.backends.homeassistant.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(Exception, match="HTTP 500"):
            await backend.send({"id": "x", "severity": "critical"})


# ── send_test ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_test_always_posts():
    """send_test() bypasses the enabled flag and always sends."""
    pool, _ = _make_pool(fetchrow_return={"value": "false"})  # HA is disabled
    backend = HomeAssistantBackend("http://ha.local/wh", pool=pool)
    mock_client = _mock_post_ok()
    with patch("app.backends.homeassistant.httpx.AsyncClient", return_value=mock_client):
        await backend.send_test()
    mock_client.post.assert_awaited_once()


# ── GET /api/settings/ha ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_ha_settings_default_enabled(monkeypatch):
    monkeypatch.setenv("HA_WEBHOOK_URL", "http://ha.local/wh")
    pool, _ = _make_pool(fetchrow_return=None)
    from app.dependencies import get_pool
    from app.auth import require_auth
    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[require_auth] = lambda: "admin"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/settings/ha")

    app.dependency_overrides = {}
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is True
    assert data["configured"] is True


@pytest.mark.asyncio
async def test_get_ha_settings_not_configured(monkeypatch):
    monkeypatch.delenv("HA_WEBHOOK_URL", raising=False)
    pool, _ = _make_pool(fetchrow_return=None)
    from app.dependencies import get_pool
    from app.auth import require_auth
    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[require_auth] = lambda: "admin"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/settings/ha")

    app.dependency_overrides = {}
    assert resp.json()["configured"] is False


# ── PUT /api/settings/ha ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_put_ha_settings_persists_disabled(monkeypatch):
    monkeypatch.setenv("HA_WEBHOOK_URL", "http://ha.local/wh")
    pool, conn = _make_pool()
    from app.dependencies import get_pool
    from app.auth import require_auth
    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[require_auth] = lambda: "admin"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put("/api/settings/ha", json={"enabled": False})

    app.dependency_overrides = {}
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False
    conn.execute.assert_awaited_once()
    _, key, value = conn.execute.call_args[0]
    assert key == "ha_enabled"
    assert value == "false"


# ── POST /api/settings/ha/test ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ha_test_sends_notification(monkeypatch):
    monkeypatch.setenv("HA_WEBHOOK_URL", "http://ha.local/wh")
    monkeypatch.delenv("DASHBOARD_URL", raising=False)
    pool, _ = _make_pool()
    from app.dependencies import get_pool
    from app.auth import require_auth
    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[require_auth] = lambda: "admin"

    mock_client = _mock_post_ok()
    with patch("app.backends.homeassistant.httpx.AsyncClient", return_value=mock_client):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/settings/ha/test")

    app.dependency_overrides = {}
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    mock_client.post.assert_awaited_once()


@pytest.mark.asyncio
async def test_ha_test_returns_422_when_not_configured(monkeypatch):
    monkeypatch.delenv("HA_WEBHOOK_URL", raising=False)
    pool, _ = _make_pool()
    from app.dependencies import get_pool
    from app.auth import require_auth
    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[require_auth] = lambda: "admin"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/settings/ha/test")

    app.dependency_overrides = {}
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_ha_test_returns_502_on_delivery_failure(monkeypatch):
    monkeypatch.setenv("HA_WEBHOOK_URL", "http://ha.local/wh")
    pool, _ = _make_pool()
    from app.dependencies import get_pool
    from app.auth import require_auth
    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[require_auth] = lambda: "admin"

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))
    with patch("app.backends.homeassistant.httpx.AsyncClient", return_value=mock_client):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/settings/ha/test")

    app.dependency_overrides = {}
    assert resp.status_code == 502
    assert "Connection refused" in resp.json()["detail"]
