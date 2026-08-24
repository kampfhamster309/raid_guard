"""
Unit tests for backends/gotify.py and the Gotify-related settings endpoints.
No real HTTP calls or DB connections are made.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from app.backends.gotify import GotifyBackend
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


def test_from_env_returns_none_when_nothing_set(monkeypatch):
    monkeypatch.delenv("GOTIFY_URL", raising=False)
    monkeypatch.delenv("GOTIFY_APP_TOKEN", raising=False)
    monkeypatch.delenv("GOTIFY_HEALTH_APP_TOKEN", raising=False)
    assert GotifyBackend.from_env() is None


def test_from_env_returns_none_when_url_missing(monkeypatch):
    monkeypatch.delenv("GOTIFY_URL", raising=False)
    monkeypatch.setenv("GOTIFY_APP_TOKEN", "tok123")
    assert GotifyBackend.from_env() is None


def test_from_env_returns_none_when_no_token(monkeypatch):
    monkeypatch.setenv("GOTIFY_URL", "http://gotify.local")
    monkeypatch.delenv("GOTIFY_APP_TOKEN", raising=False)
    monkeypatch.delenv("GOTIFY_HEALTH_APP_TOKEN", raising=False)
    assert GotifyBackend.from_env() is None


def test_from_env_returns_backend_when_url_and_token_set(monkeypatch):
    monkeypatch.setenv("GOTIFY_URL", "http://gotify.local")
    monkeypatch.setenv("GOTIFY_APP_TOKEN", "tok123")
    backend = GotifyBackend.from_env()
    assert backend is not None
    assert backend.name == "gotify"


def test_from_env_returns_backend_when_only_health_token_set(monkeypatch):
    monkeypatch.setenv("GOTIFY_URL", "http://gotify.local")
    monkeypatch.delenv("GOTIFY_APP_TOKEN", raising=False)
    monkeypatch.setenv("GOTIFY_HEALTH_APP_TOKEN", "healthtok")
    backend = GotifyBackend.from_env()
    assert backend is not None


def test_from_env_reads_dashboard_url(monkeypatch):
    monkeypatch.setenv("GOTIFY_URL", "http://gotify.local")
    monkeypatch.setenv("GOTIFY_APP_TOKEN", "tok123")
    monkeypatch.setenv("DASHBOARD_URL", "http://192.168.1.5:3000")
    backend = GotifyBackend.from_env()
    assert backend._dashboard_url == "http://192.168.1.5:3000"


# ── _build_payload ────────────────────────────────────────────────────────────


def test_build_payload_signature_only_when_no_enrichment_or_connection_info():
    backend = GotifyBackend("http://gotify.local", "tok")
    payload = backend._build_payload({
        "id": "abc-123",
        "severity": "critical",
        "signature": "ET MALWARE Beacon",
        "src_ip": "192.168.1.5",
    })
    assert "**ET MALWARE Beacon**" in payload["message"]
    assert "Source: `192.168.1.5`" in payload["message"]
    assert payload["title"] == "raid_guard — CRITICAL"
    assert payload["priority"] == 10


def test_build_payload_includes_full_connection_details():
    backend = GotifyBackend("http://gotify.local", "tok")
    payload = backend._build_payload({
        "id": "abc-123",
        "severity": "warning",
        "signature": "ET SCAN",
        "category": "Attempted Information Leak",
        "src_ip": "10.0.0.1",
        "dst_ip": "8.8.8.8",
        "dst_port": 443,
        "proto": "TCP",
        "timestamp": "2026-04-11T14:32:00+00:00",
    })
    assert "Source: `10.0.0.1` → `8.8.8.8:443` (TCP)" in payload["message"]
    assert "Category: Attempted Information Leak" in payload["message"]
    assert "Time: 2026-04-11T14:32:00+00:00" in payload["message"]
    assert payload["priority"] == 5


def test_build_payload_includes_ai_enrichment_when_available():
    backend = GotifyBackend("http://gotify.local", "tok")
    payload = backend._build_payload({
        "id": "abc-123",
        "severity": "warning",
        "signature": "ET SCAN",
        "src_ip": "10.0.0.1",
        "enrichment_json": {
            "summary": "Port scan detected on subnet",
            "severity_reasoning": "Multiple ports probed in a short window.",
            "recommended_action": "Block the source IP if scanning continues.",
        },
    })
    assert "Port scan detected on subnet" in payload["message"]
    assert "_Why this severity:_ Multiple ports probed in a short window." in payload["message"]
    assert "_Recommended action:_ Block the source IP if scanning continues." in payload["message"]


def test_build_payload_ignores_legacy_enrichment_key():
    """Regression guard: the enricher publishes 'enrichment_json', not 'enrichment'."""
    backend = GotifyBackend("http://gotify.local", "tok")
    payload = backend._build_payload({
        "id": "abc-123",
        "severity": "info",
        "signature": "ET SCAN",
        "src_ip": "10.0.0.1",
        "enrichment": {"summary": "Should not appear"},
    })
    assert "Should not appear" not in payload["message"]


def test_build_payload_defaults_priority_for_info():
    backend = GotifyBackend("http://gotify.local", "tok")
    payload = backend._build_payload({"id": "x", "severity": "info"})
    assert payload["priority"] == 2


def test_build_payload_always_sets_markdown_content_type():
    backend = GotifyBackend("http://gotify.local", "tok", dashboard_url="")
    payload = backend._build_payload({"id": "uuid-001", "severity": "info"})
    assert payload["extras"]["client::display"]["contentType"] == "text/markdown"
    assert "client::notification" not in payload["extras"]


def test_build_payload_includes_click_extra_when_dashboard_url_set():
    backend = GotifyBackend("http://gotify.local", "tok", dashboard_url="http://192.168.1.5:3000")
    payload = backend._build_payload({"id": "uuid-001", "severity": "info"})
    assert payload["extras"]["client::notification"]["click"]["url"] == "http://192.168.1.5:3000?alert=uuid-001"
    assert payload["extras"]["client::display"]["contentType"] == "text/markdown"


# ── _is_enabled ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_is_enabled_true_when_no_pool():
    backend = GotifyBackend("http://gotify.local", "tok", pool=None)
    assert await backend._is_enabled() is True


@pytest.mark.asyncio
async def test_is_enabled_false_when_config_says_false():
    pool, _ = _make_pool(fetchrow_return={"value": "false"})
    backend = GotifyBackend("http://gotify.local", "tok", pool=pool)
    assert await backend._is_enabled() is False


@pytest.mark.asyncio
async def test_is_enabled_true_when_db_raises():
    pool = MagicMock()
    pool.acquire.side_effect = Exception("DB down")
    backend = GotifyBackend("http://gotify.local", "tok", pool=pool)
    assert await backend._is_enabled() is True


# ── send ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_posts_when_enabled():
    pool, _ = _make_pool(fetchrow_return=None)  # no row → enabled
    backend = GotifyBackend("http://gotify.local", "tok", pool=pool)
    mock_client = _mock_post_ok()
    with patch("app.backends.gotify.httpx.AsyncClient", return_value=mock_client):
        await backend.send({"id": "x", "severity": "warning", "src_ip": "1.2.3.4"})
    mock_client.post.assert_awaited_once()
    call = mock_client.post.call_args
    assert call.args[0] == "http://gotify.local/message"
    assert call.kwargs["params"] == {"token": "tok"}


@pytest.mark.asyncio
async def test_send_skips_when_disabled():
    pool, _ = _make_pool(fetchrow_return={"value": "false"})
    backend = GotifyBackend("http://gotify.local", "tok", pool=pool)
    mock_client = _mock_post_ok()
    with patch("app.backends.gotify.httpx.AsyncClient", return_value=mock_client):
        await backend.send({"id": "x", "severity": "critical"})
    mock_client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_skips_when_no_token():
    backend = GotifyBackend("http://gotify.local", "")
    mock_client = _mock_post_ok()
    with patch("app.backends.gotify.httpx.AsyncClient", return_value=mock_client):
        await backend.send({"id": "x", "severity": "critical"})
    mock_client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_raises_on_http_error():
    pool, _ = _make_pool(fetchrow_return=None)
    backend = GotifyBackend("http://gotify.local", "tok", pool=pool)
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(side_effect=Exception("HTTP 500"))
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)
    with patch("app.backends.gotify.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(Exception, match="HTTP 500"):
            await backend.send({"id": "x", "severity": "critical"})


# ── send_test ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_test_always_posts():
    """send_test() bypasses the enabled flag and always sends."""
    pool, _ = _make_pool(fetchrow_return={"value": "false"})  # gotify is disabled
    backend = GotifyBackend("http://gotify.local", "tok", pool=pool)
    mock_client = _mock_post_ok()
    with patch("app.backends.gotify.httpx.AsyncClient", return_value=mock_client):
        await backend.send_test()
    mock_client.post.assert_awaited_once()


# ── send_health_alert ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_health_alert_posts_with_health_token():
    pool, _ = _make_pool(fetchrow_return=None)
    backend = GotifyBackend("http://gotify.local", "tok", pool=pool, health_app_token="healthtok")
    mock_client = _mock_post_ok()
    with patch("app.backends.gotify.httpx.AsyncClient", return_value=mock_client):
        await backend.send_health_alert("db", "TimescaleDB", False)
    call = mock_client.post.call_args
    assert call.kwargs["params"] == {"token": "healthtok"}
    payload = call.kwargs["json"]
    assert payload["priority"] == 10
    assert "TimescaleDB" in payload["message"]


@pytest.mark.asyncio
async def test_send_health_alert_falls_back_to_main_token():
    backend = GotifyBackend("http://gotify.local", "tok")
    mock_client = _mock_post_ok()
    with patch("app.backends.gotify.httpx.AsyncClient", return_value=mock_client):
        await backend.send_health_alert("redis", "Redis", True)
    call = mock_client.post.call_args
    assert call.kwargs["params"] == {"token": "tok"}
    assert call.kwargs["json"]["priority"] == 5


@pytest.mark.asyncio
async def test_send_health_alert_skips_when_no_token():
    backend = GotifyBackend("http://gotify.local", "")
    mock_client = _mock_post_ok()
    with patch("app.backends.gotify.httpx.AsyncClient", return_value=mock_client):
        await backend.send_health_alert("db", "TimescaleDB", False)
    mock_client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_health_alert_skips_when_disabled():
    pool, _ = _make_pool(fetchrow_return={"value": "false"})
    backend = GotifyBackend("http://gotify.local", "tok", pool=pool)
    mock_client = _mock_post_ok()
    with patch("app.backends.gotify.httpx.AsyncClient", return_value=mock_client):
        await backend.send_health_alert("db", "TimescaleDB", False)
    mock_client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_health_alert_swallows_http_error():
    pool, _ = _make_pool(fetchrow_return=None)
    backend = GotifyBackend("http://gotify.local", "tok", pool=pool)
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))
    with patch("app.backends.gotify.httpx.AsyncClient", return_value=mock_client):
        await backend.send_health_alert("db", "TimescaleDB", False)  # no exception raised


# ── GET /api/settings/gotify ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_gotify_settings_default_enabled(monkeypatch):
    monkeypatch.setenv("GOTIFY_URL", "http://gotify.local")
    monkeypatch.setenv("GOTIFY_APP_TOKEN", "tok")
    pool, _ = _make_pool(fetchrow_return=None)
    from app.dependencies import get_pool
    from app.auth import require_admin, require_auth
    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[require_auth] = lambda: "admin"
    app.dependency_overrides[require_admin] = lambda: "admin"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/settings/gotify")

    app.dependency_overrides = {}
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is True
    assert data["configured"] is True
    assert data["health_alerts_enabled"] is True


@pytest.mark.asyncio
async def test_get_gotify_settings_not_configured(monkeypatch):
    monkeypatch.delenv("GOTIFY_URL", raising=False)
    monkeypatch.delenv("GOTIFY_APP_TOKEN", raising=False)
    pool, _ = _make_pool(fetchrow_return=None)
    from app.dependencies import get_pool
    from app.auth import require_admin, require_auth
    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[require_auth] = lambda: "admin"
    app.dependency_overrides[require_admin] = lambda: "admin"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/settings/gotify")

    app.dependency_overrides = {}
    assert resp.json()["configured"] is False


# ── PUT /api/settings/gotify ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_put_gotify_settings_persists_disabled(monkeypatch):
    monkeypatch.setenv("GOTIFY_URL", "http://gotify.local")
    monkeypatch.setenv("GOTIFY_APP_TOKEN", "tok")
    pool, conn = _make_pool()
    from app.dependencies import get_pool
    from app.auth import require_admin, require_auth
    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[require_auth] = lambda: "admin"
    app.dependency_overrides[require_admin] = lambda: "admin"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put("/api/settings/gotify", json={"enabled": False})

    app.dependency_overrides = {}
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False
    conn.execute.assert_awaited_once()
    _, key, value = conn.execute.call_args[0]
    assert key == "gotify_enabled"
    assert value == "false"


@pytest.mark.asyncio
async def test_put_gotify_settings_persists_health_alerts_disabled(monkeypatch):
    monkeypatch.setenv("GOTIFY_URL", "http://gotify.local")
    monkeypatch.setenv("GOTIFY_APP_TOKEN", "tok")
    pool, conn = _make_pool()
    from app.dependencies import get_pool
    from app.auth import require_admin, require_auth
    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[require_auth] = lambda: "admin"
    app.dependency_overrides[require_admin] = lambda: "admin"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put("/api/settings/gotify", json={"health_alerts_enabled": False})

    app.dependency_overrides = {}
    assert resp.status_code == 200
    assert resp.json()["health_alerts_enabled"] is False
    conn.execute.assert_awaited_once()
    _, key, value = conn.execute.call_args[0]
    assert key == "gotify_health_alerts_enabled"
    assert value == "false"


# ── POST /api/settings/gotify/test ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gotify_test_sends_notification(monkeypatch):
    monkeypatch.setenv("GOTIFY_URL", "http://gotify.local")
    monkeypatch.setenv("GOTIFY_APP_TOKEN", "tok")
    monkeypatch.delenv("DASHBOARD_URL", raising=False)
    pool, _ = _make_pool()
    from app.dependencies import get_pool
    from app.auth import require_admin, require_auth
    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[require_auth] = lambda: "admin"
    app.dependency_overrides[require_admin] = lambda: "admin"

    mock_client = _mock_post_ok()
    with patch("app.backends.gotify.httpx.AsyncClient", return_value=mock_client):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/settings/gotify/test")

    app.dependency_overrides = {}
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    mock_client.post.assert_awaited_once()


@pytest.mark.asyncio
async def test_gotify_test_returns_422_when_not_configured(monkeypatch):
    monkeypatch.delenv("GOTIFY_URL", raising=False)
    monkeypatch.delenv("GOTIFY_APP_TOKEN", raising=False)
    pool, _ = _make_pool()
    from app.dependencies import get_pool
    from app.auth import require_admin, require_auth
    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[require_auth] = lambda: "admin"
    app.dependency_overrides[require_admin] = lambda: "admin"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/settings/gotify/test")

    app.dependency_overrides = {}
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_gotify_test_returns_502_on_delivery_failure(monkeypatch):
    monkeypatch.setenv("GOTIFY_URL", "http://gotify.local")
    monkeypatch.setenv("GOTIFY_APP_TOKEN", "tok")
    pool, _ = _make_pool()
    from app.dependencies import get_pool
    from app.auth import require_admin, require_auth
    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[require_auth] = lambda: "admin"
    app.dependency_overrides[require_admin] = lambda: "admin"

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))
    with patch("app.backends.gotify.httpx.AsyncClient", return_value=mock_client):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/settings/gotify/test")

    app.dependency_overrides = {}
    assert resp.status_code == 502
    assert "Connection refused" in resp.json()["detail"]
