"""Unit tests for /api/pihole endpoints (mock DB + mock pihole client)."""

from unittest.mock import AsyncMock, patch

import pytest

from app.pihole import PiholeError


_PIHOLE_CFG = {
    "url": "http://pihole:80",
    "password": "secret",
    "enabled": True,
}

_PIHOLE_CFG_DISABLED = {**_PIHOLE_CFG, "enabled": False}
_PIHOLE_CFG_UNCONFIGURED = {"url": "", "password": "", "enabled": True}

_BLOCKED_DOMAIN = {
    "domain": "malware.example.com",
    "comment": "Blocked by raid_guard",
    "added_at": 1712325600,
    "enabled": True,
}


def _patch_cfg(cfg=None):
    return patch(
        "app.routers.pihole.get_pihole_config",
        new=AsyncMock(return_value=cfg or _PIHOLE_CFG),
    )


# ── GET /api/pihole/settings ──────────────────────────────────────────────────


def test_get_settings_returns_200(authed_client):
    client, _ = authed_client
    with _patch_cfg():
        resp = client.get("/api/pihole/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["url"] == "http://pihole:80"
    assert body["enabled"] is True
    assert body["configured"] is True


def test_get_settings_configured_false_when_no_password(authed_client):
    client, _ = authed_client
    with _patch_cfg({"url": "http://pihole:80", "password": "", "enabled": True}):
        resp = client.get("/api/pihole/settings")
    assert resp.json()["configured"] is False


def test_get_settings_requires_auth(raw_client):
    resp = raw_client.get("/api/pihole/settings")
    assert resp.status_code == 401


# ── PUT /api/pihole/settings ──────────────────────────────────────────────────


def test_update_settings_persists_url_and_enabled(authed_client):
    client, conn = authed_client
    conn.execute = AsyncMock()
    with _patch_cfg():
        resp = client.put(
            "/api/pihole/settings",
            json={"url": "http://pihole:80", "enabled": False, "password": ""},
        )
    assert resp.status_code == 200
    assert resp.json()["enabled"] is True  # re-read from mock returns enabled=True


def test_update_settings_updates_password_when_provided(authed_client):
    client, conn = authed_client
    conn.execute = AsyncMock()
    with _patch_cfg():
        resp = client.put(
            "/api/pihole/settings",
            json={"url": "http://pihole:80", "enabled": True, "password": "newpass"},
        )
    assert resp.status_code == 200
    # password key was passed to conn.execute
    calls = [str(c) for c in conn.execute.call_args_list]
    assert any("pihole_password" in c for c in calls)


def test_update_settings_skips_password_when_blank(authed_client):
    client, conn = authed_client
    conn.execute = AsyncMock()
    with _patch_cfg():
        resp = client.put(
            "/api/pihole/settings",
            json={"url": "http://pihole:80", "enabled": True, "password": ""},
        )
    assert resp.status_code == 200
    calls = [str(c) for c in conn.execute.call_args_list]
    assert not any("pihole_password" in c for c in calls)


# ── GET /api/pihole/blocklist ─────────────────────────────────────────────────


def test_get_blocklist_returns_domains(authed_client):
    client, _ = authed_client
    with _patch_cfg():
        with patch(
            "app.routers.pihole.list_blocked_domains",
            new=AsyncMock(return_value=[_BLOCKED_DOMAIN]),
        ):
            resp = client.get("/api/pihole/blocklist")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["domain"] == "malware.example.com"


def test_get_blocklist_empty(authed_client):
    client, _ = authed_client
    with _patch_cfg():
        with patch(
            "app.routers.pihole.list_blocked_domains",
            new=AsyncMock(return_value=[]),
        ):
            resp = client.get("/api/pihole/blocklist")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_blocklist_422_when_disabled(authed_client):
    client, _ = authed_client
    with _patch_cfg(_PIHOLE_CFG_DISABLED):
        resp = client.get("/api/pihole/blocklist")
    assert resp.status_code == 422


def test_get_blocklist_422_when_not_configured(authed_client):
    client, _ = authed_client
    with _patch_cfg(_PIHOLE_CFG_UNCONFIGURED):
        resp = client.get("/api/pihole/blocklist")
    assert resp.status_code == 422


def test_get_blocklist_502_on_pihole_error(authed_client):
    client, _ = authed_client
    with _patch_cfg():
        with patch(
            "app.routers.pihole.list_blocked_domains",
            new=AsyncMock(side_effect=PiholeError("Connection refused")),
        ):
            resp = client.get("/api/pihole/blocklist")
    assert resp.status_code == 502
    assert "Connection refused" in resp.json()["detail"]


def test_get_blocklist_requires_auth(raw_client):
    resp = raw_client.get("/api/pihole/blocklist")
    assert resp.status_code == 401


# ── POST /api/pihole/block ────────────────────────────────────────────────────


def test_block_domain_returns_200(authed_client):
    client, _ = authed_client
    with _patch_cfg():
        with patch("app.routers.pihole.block_domain", new=AsyncMock()):
            resp = client.post(
                "/api/pihole/block",
                json={"domain": "malware.example.com"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["domain"] == "malware.example.com"


def test_block_domain_lowercases_domain(authed_client):
    client, _ = authed_client
    with _patch_cfg():
        with patch("app.routers.pihole.block_domain", new=AsyncMock()) as mock_block:
            client.post(
                "/api/pihole/block",
                json={"domain": "MALWARE.EXAMPLE.COM"},
            )
    mock_block.assert_awaited_once()
    assert mock_block.call_args[0][2] == "malware.example.com"


def test_block_domain_422_on_empty_domain(authed_client):
    client, _ = authed_client
    with _patch_cfg():
        resp = client.post("/api/pihole/block", json={"domain": ""})
    assert resp.status_code == 422


def test_block_domain_422_when_disabled(authed_client):
    client, _ = authed_client
    with _patch_cfg(_PIHOLE_CFG_DISABLED):
        resp = client.post("/api/pihole/block", json={"domain": "evil.com"})
    assert resp.status_code == 422


def test_block_domain_502_on_pihole_error(authed_client):
    client, _ = authed_client
    with _patch_cfg():
        with patch(
            "app.routers.pihole.block_domain",
            new=AsyncMock(side_effect=PiholeError("Pi-hole unreachable")),
        ):
            resp = client.post("/api/pihole/block", json={"domain": "evil.com"})
    assert resp.status_code == 502


def test_block_domain_requires_auth(raw_client):
    resp = raw_client.post("/api/pihole/block", json={"domain": "evil.com"})
    assert resp.status_code == 401


# ── DELETE /api/pihole/block/{domain} ────────────────────────────────────────


def test_unblock_domain_returns_204(authed_client):
    client, _ = authed_client
    with _patch_cfg():
        with patch("app.routers.pihole.unblock_domain", new=AsyncMock()):
            resp = client.delete("/api/pihole/block/malware.example.com")
    assert resp.status_code == 204


def test_unblock_domain_502_on_pihole_error(authed_client):
    client, _ = authed_client
    with _patch_cfg():
        with patch(
            "app.routers.pihole.unblock_domain",
            new=AsyncMock(side_effect=PiholeError("timeout")),
        ):
            resp = client.delete("/api/pihole/block/evil.com")
    assert resp.status_code == 502


def test_unblock_domain_requires_auth(raw_client):
    resp = raw_client.delete("/api/pihole/block/evil.com")
    assert resp.status_code == 401
