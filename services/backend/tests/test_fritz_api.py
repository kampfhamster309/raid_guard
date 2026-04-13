"""Unit tests for /api/fritz endpoints (mock DB + mock FritzBlocker)."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.fritz_blocker import FritzBlockerError, FritzNotInHostTableError


_NOW = "2026-04-13T00:00:00+00:00"

_DB_ROW = {
    "id": str(uuid.uuid4()),
    "blocked_at": _NOW,
    "ip": "192.168.178.50",
    "hostname": "evil-iot",
    "comment": "C2 beacon detected",
}


def _mock_blocker(
    *,
    check_status=None,
    block_side_effect=None,
    unblock_side_effect=None,
    hostname="evil-iot",
):
    b = MagicMock()
    b.check_status = AsyncMock(return_value=check_status or {
        "connected": True,
        "host_filter_available": True,
        "model": "FRITZ!Box 6660 Cable",
        "firmware": "8.00",
    })
    b.block = AsyncMock(side_effect=block_side_effect)
    b.unblock = AsyncMock(side_effect=unblock_side_effect)
    b.get_hostname = AsyncMock(return_value=hostname)
    return b


def _patch_blocker(blocker):
    return patch("app.routers.fritz.get_fritz_blocker", return_value=blocker)


def _patch_no_blocker():
    return patch("app.routers.fritz.get_fritz_blocker", return_value=None)


# ── GET /api/fritz/status ─────────────────────────────────────────────────────


def test_status_not_configured(authed_client):
    client, _ = authed_client
    with _patch_no_blocker():
        resp = client.get("/api/fritz/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is False
    assert data["connected"] is False
    assert data["host_filter_available"] is False


def test_status_connected(authed_client):
    client, _ = authed_client
    with _patch_blocker(_mock_blocker()):
        resp = client.get("/api/fritz/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is True
    assert data["connected"] is True
    assert data["host_filter_available"] is True
    assert data["model"] == "FRITZ!Box 6660 Cable"


def test_status_unreachable(authed_client):
    client, _ = authed_client
    b = _mock_blocker()
    b.check_status = AsyncMock(side_effect=FritzBlockerError("Cannot reach Fritzbox"))
    with _patch_blocker(b):
        resp = client.get("/api/fritz/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is True
    assert data["connected"] is False


# ── GET /api/fritz/blocked ────────────────────────────────────────────────────


def test_list_blocked_empty(authed_client):
    client, conn = authed_client
    conn.fetch = AsyncMock(return_value=[])
    resp = client.get("/api/fritz/blocked")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_blocked_returns_rows(authed_client):
    client, conn = authed_client
    conn.fetch = AsyncMock(return_value=[_DB_ROW])
    resp = client.get("/api/fritz/blocked")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["ip"] == "192.168.178.50"
    assert data[0]["hostname"] == "evil-iot"


# ── POST /api/fritz/block ─────────────────────────────────────────────────────


def test_block_device_success(authed_client):
    client, conn = authed_client
    conn.fetchrow = AsyncMock(return_value=_DB_ROW)
    with _patch_blocker(_mock_blocker()):
        resp = client.post("/api/fritz/block", json={"ip": "192.168.178.50", "comment": "C2 beacon detected"})
    assert resp.status_code == 201
    assert resp.json()["ip"] == "192.168.178.50"


def test_block_device_resolves_hostname(authed_client):
    client, conn = authed_client
    conn.fetchrow = AsyncMock(return_value=_DB_ROW)
    b = _mock_blocker(hostname="evil-iot")
    with _patch_blocker(b):
        client.post("/api/fritz/block", json={"ip": "192.168.178.50"})
    b.get_hostname.assert_called_once_with("192.168.178.50")


def test_block_device_empty_ip_returns_422(authed_client):
    client, _ = authed_client
    with _patch_blocker(_mock_blocker()):
        resp = client.post("/api/fritz/block", json={"ip": "  "})
    assert resp.status_code == 422


def test_block_device_not_in_host_table_returns_404(authed_client):
    client, _ = authed_client
    b = _mock_blocker(block_side_effect=FritzNotInHostTableError("not in host table"))
    with _patch_blocker(b):
        resp = client.post("/api/fritz/block", json={"ip": "192.168.178.99"})
    assert resp.status_code == 404


def test_block_device_fritz_error_returns_502(authed_client):
    client, _ = authed_client
    b = _mock_blocker(block_side_effect=FritzBlockerError("Connection refused"))
    with _patch_blocker(b):
        resp = client.post("/api/fritz/block", json={"ip": "192.168.178.50"})
    assert resp.status_code == 502


def test_block_not_configured_returns_422(authed_client):
    client, _ = authed_client
    with _patch_no_blocker():
        resp = client.post("/api/fritz/block", json={"ip": "192.168.178.50"})
    assert resp.status_code == 422


# ── DELETE /api/fritz/block/{ip} ──────────────────────────────────────────────


def test_unblock_device_success(authed_client):
    client, conn = authed_client
    conn.execute = AsyncMock()
    with _patch_blocker(_mock_blocker()):
        resp = client.delete("/api/fritz/block/192.168.178.50")
    assert resp.status_code == 204


def test_unblock_removes_db_row(authed_client):
    client, conn = authed_client
    conn.execute = AsyncMock()
    with _patch_blocker(_mock_blocker()):
        client.delete("/api/fritz/block/192.168.178.50")
    conn.execute.assert_called_once()
    sql, ip_arg = conn.execute.call_args[0]
    assert "DELETE" in sql
    assert ip_arg == "192.168.178.50"


def test_unblock_not_in_host_table_returns_404(authed_client):
    client, _ = authed_client
    b = _mock_blocker(unblock_side_effect=FritzNotInHostTableError("not in table"))
    with _patch_blocker(b):
        resp = client.delete("/api/fritz/block/192.168.178.50")
    assert resp.status_code == 404


def test_unblock_fritz_error_returns_502(authed_client):
    client, _ = authed_client
    b = _mock_blocker(unblock_side_effect=FritzBlockerError("Timeout"))
    with _patch_blocker(b):
        resp = client.delete("/api/fritz/block/192.168.178.50")
    assert resp.status_code == 502


def test_unblock_not_configured_returns_422(authed_client):
    client, _ = authed_client
    with _patch_no_blocker():
        resp = client.delete("/api/fritz/block/192.168.178.50")
    assert resp.status_code == 422
