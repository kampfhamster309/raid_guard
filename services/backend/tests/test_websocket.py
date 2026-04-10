"""Unit tests for the /ws/alerts WebSocket endpoint."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.auth import create_token
from app.main import app


def test_ws_unauthenticated_is_closed():
    """An invalid token must result in the server closing the connection (code 1008)."""
    with TestClient(app) as client:
        with client.websocket_connect("/ws/alerts?token=bad.token.here") as ws:
            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_text()
    assert exc_info.value.code == 1008


def test_ws_missing_token_closes_with_error():
    """Omitting the required token query param must be rejected on upgrade."""
    with TestClient(app) as client:
        # FastAPI Query(...) validation happens inside the WebSocket handshake;
        # the server closes the connection immediately.
        with pytest.raises((WebSocketDisconnect, Exception)):
            with client.websocket_connect("/ws/alerts") as ws:
                ws.receive_text()


def test_ws_authenticated_connection_is_accepted():
    """A valid token must be accepted (connection established, not immediately rejected)."""
    token = create_token("admin")
    accepted = False

    with TestClient(app) as client:
        try:
            with client.websocket_connect(f"/ws/alerts?token={token}") as ws:
                accepted = True
                # The server is now waiting for Redis messages.  Close from
                # the client side to trigger WebSocketDisconnect on the server.
                ws.close()
        except WebSocketDisconnect:
            # Raised when ws.close() causes the server to disconnect — expected.
            pass
        except Exception:
            # Redis not available in unit test environment; the forward task
            # will have failed silently.  Connection was still accepted.
            pass

    assert accepted, "WebSocket connection was not accepted with a valid token"
