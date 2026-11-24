import asyncio
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.state import CaptureState, agent_state


async def _noop_capture_loop(*args, **kwargs):
    try:
        await asyncio.sleep(float("inf"))
    except asyncio.CancelledError:
        pass


@pytest.fixture
def client():
    with patch("app.main.capture_loop", _noop_capture_loop):
        with TestClient(app) as c:
            agent_state.set(CaptureState.STREAMING, "Streaming ifaceorminor=3-17")
            yield c
    agent_state.set(CaptureState.STARTING, "")
    agent_state.clear_data()


def test_health_returns_200_when_streaming(client):
    response = client.get("/health")
    assert response.status_code == 200


def test_health_returns_503_when_reconnecting(client):
    agent_state.set(CaptureState.RECONNECTING, "ConnectionError — retrying in 4s")
    response = client.get("/health")
    assert response.status_code == 503


def test_health_returns_503_when_connecting(client):
    agent_state.set(CaptureState.CONNECTING, "Authenticating with Fritzbox")
    response = client.get("/health")
    assert response.status_code == 503


def test_health_service_field(client):
    response = client.get("/health")
    assert response.json()["service"] == "capture-agent"


def test_health_status_ok_when_streaming(client):
    response = client.get("/health")
    assert response.json()["status"] == "ok"


def test_health_status_degraded_when_not_streaming(client):
    agent_state.set(CaptureState.RECONNECTING, "err")
    response = client.get("/health")
    assert response.json()["status"] == "degraded"


def test_health_includes_capture_state(client):
    response = client.get("/health")
    data = response.json()
    assert "capture_state" in data
    assert "reconnect_count" in data
    assert "message" in data


def test_health_reflects_state_changes(client):
    agent_state.set(CaptureState.STREAMING, "Streaming ifaceorminor=3-19")
    response = client.get("/health")
    data = response.json()
    assert data["capture_state"] == CaptureState.STREAMING.value
    assert "3-19" in data["message"]


# ── data staleness ─────────────────────────────────────────────────────────────

def _age_last_data(seconds: float) -> None:
    import time
    agent_state._last_data_at = time.monotonic() - seconds


def test_health_includes_last_data_age(client):
    agent_state.mark_data()
    data = client.get("/health").json()
    assert data["last_data_age_seconds"] is not None
    assert data["data_stale"] is False


def test_health_503_when_streaming_but_no_data_for_too_long(client):
    """The 2026-11-24 failure: state stayed "streaming" while no bytes arrived."""
    with patch("app.main.DATA_STALE_SECONDS", 300):
        _age_last_data(301)
        response = client.get("/health")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    assert data["data_stale"] is True
    assert data["capture_state"] == "streaming"
    assert "stalled" in data["message"]


def test_health_200_when_data_recent(client):
    with patch("app.main.DATA_STALE_SECONDS", 300):
        _age_last_data(10)
        response = client.get("/health")
    assert response.status_code == 200


def test_health_200_when_streaming_just_started_without_data(client):
    """No packet yet, but streaming only just began — within grace period."""
    agent_state.clear_data()
    with patch("app.main.DATA_STALE_SECONDS", 300):
        response = client.get("/health")
    assert response.status_code == 200


def test_health_503_when_streaming_long_without_any_data(client):
    import time
    agent_state.clear_data()
    agent_state._state_since = time.monotonic() - 400
    with patch("app.main.DATA_STALE_SECONDS", 300):
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["data_stale"] is True
