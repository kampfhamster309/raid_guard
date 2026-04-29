from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import ADMIN_USERNAME, require_auth
from app.dependencies import get_pool, get_redis
from app.main import app

_CAPTURE_OK = {
    "ok": True,
    "reachable": True,
    "capture_state": "streaming",
    "reconnect_count": 0,
    "message": "",
}
_SURICATA_OK = {"ok": True, "running": True, "health": "healthy"}


def _override_auth():
    return ADMIN_USERNAME or "admin"


@pytest.fixture
def status_client():
    alive = MagicMock()
    alive.done.return_value = False

    app.dependency_overrides[get_pool] = lambda: MagicMock()
    app.dependency_overrides[get_redis] = lambda: AsyncMock()
    app.dependency_overrides[require_auth] = _override_auth

    with (
        patch("app.routers.status._probe_db", AsyncMock(return_value=True)),
        patch("app.routers.status._probe_redis", AsyncMock(return_value=True)),
        patch("app.routers.status._probe_capture_agent", AsyncMock(return_value=_CAPTURE_OK)),
        patch("app.routers.status._probe_suricata_sync", MagicMock(return_value=_SURICATA_OK)),
    ):
        with TestClient(app) as c:
            app.state.ingestor_task = alive
            app.state.enrich_task = alive
            yield c

    app.dependency_overrides.clear()


# ── Happy path ────────────────────────────────────────────────────────────────


def test_status_all_ok(status_client):
    resp = status_client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["db"]["ok"] is True
    assert data["redis"]["ok"] is True
    assert data["ingestor"]["ok"] is True
    assert data["enricher"]["ok"] is True
    assert data["capture_agent"]["ok"] is True
    assert data["suricata"]["ok"] is True


def test_status_capture_agent_fields(status_client):
    resp = status_client.get("/api/status")
    ca = resp.json()["capture_agent"]
    assert ca["reachable"] is True
    assert ca["capture_state"] == "streaming"
    assert ca["reconnect_count"] == 0


def test_status_suricata_fields(status_client):
    resp = status_client.get("/api/status")
    s = resp.json()["suricata"]
    assert s["running"] is True
    assert s["health"] == "healthy"


# ── Degraded scenarios ────────────────────────────────────────────────────────


def test_status_db_down(status_client):
    with patch("app.routers.status._probe_db", AsyncMock(return_value=False)):
        resp = status_client.get("/api/status")
    assert resp.json()["db"]["ok"] is False


def test_status_redis_down(status_client):
    with patch("app.routers.status._probe_redis", AsyncMock(return_value=False)):
        resp = status_client.get("/api/status")
    assert resp.json()["redis"]["ok"] is False


def test_status_capture_agent_unreachable(status_client):
    unreachable = {"ok": False, "reachable": False, "message": "Connection refused"}
    with patch("app.routers.status._probe_capture_agent", AsyncMock(return_value=unreachable)):
        resp = status_client.get("/api/status")
    ca = resp.json()["capture_agent"]
    assert ca["ok"] is False
    assert ca["reachable"] is False


def test_status_capture_agent_reconnecting(status_client):
    reconnecting = {
        "ok": False,
        "reachable": True,
        "capture_state": "reconnecting",
        "reconnect_count": 3,
        "message": "ConnectionError — retrying in 8s",
    }
    with patch("app.routers.status._probe_capture_agent", AsyncMock(return_value=reconnecting)):
        resp = status_client.get("/api/status")
    ca = resp.json()["capture_agent"]
    assert ca["ok"] is False
    assert ca["capture_state"] == "reconnecting"
    assert ca["reconnect_count"] == 3


def test_status_suricata_down(status_client):
    down = {"ok": False, "running": False, "message": "Container not found"}
    with patch("app.routers.status._probe_suricata_sync", MagicMock(return_value=down)):
        resp = status_client.get("/api/status")
    assert resp.json()["suricata"]["ok"] is False


def test_status_ingestor_dead(status_client):
    dead = MagicMock()
    dead.done.return_value = True
    app.state.ingestor_task = dead
    resp = status_client.get("/api/status")
    assert resp.json()["ingestor"]["ok"] is False


def test_status_enricher_dead(status_client):
    dead = MagicMock()
    dead.done.return_value = True
    app.state.enrich_task = dead
    resp = status_client.get("/api/status")
    assert resp.json()["enricher"]["ok"] is False


# ── Auth ──────────────────────────────────────────────────────────────────────


def test_status_requires_auth():
    with TestClient(app) as c:
        resp = c.get("/api/status")
    assert resp.status_code == 401
