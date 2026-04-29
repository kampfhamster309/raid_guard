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
