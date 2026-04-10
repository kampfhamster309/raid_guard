import asyncio
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.state import CaptureState, agent_state


async def _noop_capture_loop(*args, **kwargs):
    """Stand-in for capture_loop that does nothing (avoids Fritzbox connections in tests)."""
    try:
        await asyncio.sleep(float("inf"))
    except asyncio.CancelledError:
        pass


@pytest.fixture
def client():
    with patch("app.main.capture_loop", _noop_capture_loop):
        with TestClient(app) as c:
            yield c


def test_health_returns_200(client):
    response = client.get("/health")
    assert response.status_code == 200


def test_health_service_field(client):
    response = client.get("/health")
    assert response.json()["service"] == "capture-agent"


def test_health_status_field(client):
    response = client.get("/health")
    assert response.json()["status"] == "ok"


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
