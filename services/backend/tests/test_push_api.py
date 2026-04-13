"""Unit tests for /api/push endpoints."""

import uuid
from unittest.mock import AsyncMock, patch


_SUB_ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc123"
_SUB_P256DH = "BNcRdreALRFXTkOOUHK1EtK2wtZ5MRM1diBqnHlYTQnFq"
_SUB_AUTH = "tBHItJI5svbpez7KI4CCXg"

_SUB_BODY = {
    "endpoint": _SUB_ENDPOINT,
    "keys": {"p256dh": _SUB_P256DH, "auth": _SUB_AUTH},
}


# ── GET /api/push/vapid-public-key ────────────────────────────────────────────


def test_vapid_public_key_configured(authed_client):
    client, _ = authed_client
    with patch.dict("os.environ", {"VAPID_PUBLIC_KEY": "BExamplePublicKey123"}):
        resp = client.get("/api/push/vapid-public-key")
    assert resp.status_code == 200
    assert resp.json()["public_key"] == "BExamplePublicKey123"


def test_vapid_public_key_not_configured(authed_client):
    client, _ = authed_client
    with patch.dict("os.environ", {}, clear=False):
        import os
        saved = os.environ.pop("VAPID_PUBLIC_KEY", None)
        try:
            resp = client.get("/api/push/vapid-public-key")
        finally:
            if saved is not None:
                os.environ["VAPID_PUBLIC_KEY"] = saved
    assert resp.status_code == 404
    assert "not configured" in resp.json()["detail"].lower()


def test_vapid_public_key_empty_env(authed_client):
    client, _ = authed_client
    with patch.dict("os.environ", {"VAPID_PUBLIC_KEY": ""}):
        resp = client.get("/api/push/vapid-public-key")
    assert resp.status_code == 404


# ── POST /api/push/subscribe ──────────────────────────────────────────────────


def test_subscribe_creates_record(authed_client):
    client, conn = authed_client
    conn.execute = AsyncMock(return_value=None)
    resp = client.post("/api/push/subscribe", json=_SUB_BODY)
    assert resp.status_code == 201
    conn.execute.assert_called_once()
    call_args = conn.execute.call_args[0]
    assert _SUB_ENDPOINT in call_args[1]
    assert _SUB_P256DH in call_args[2:]
    assert _SUB_AUTH in call_args[2:]


def test_subscribe_missing_endpoint(authed_client):
    client, _ = authed_client
    resp = client.post("/api/push/subscribe", json={
        "endpoint": "",
        "keys": {"p256dh": _SUB_P256DH, "auth": _SUB_AUTH},
    })
    assert resp.status_code == 422


def test_subscribe_missing_p256dh(authed_client):
    client, _ = authed_client
    resp = client.post("/api/push/subscribe", json={
        "endpoint": _SUB_ENDPOINT,
        "keys": {"auth": _SUB_AUTH},
    })
    assert resp.status_code == 422
    assert "p256dh" in resp.json()["detail"]


def test_subscribe_missing_auth(authed_client):
    client, _ = authed_client
    resp = client.post("/api/push/subscribe", json={
        "endpoint": _SUB_ENDPOINT,
        "keys": {"p256dh": _SUB_P256DH},
    })
    assert resp.status_code == 422
    assert "auth" in resp.json()["detail"]


def test_subscribe_unauthenticated(raw_client):
    resp = raw_client.post("/api/push/subscribe", json=_SUB_BODY)
    assert resp.status_code == 401


# ── DELETE /api/push/subscribe ────────────────────────────────────────────────


def test_unsubscribe_removes_record(authed_client):
    client, conn = authed_client
    conn.execute = AsyncMock(return_value=None)
    resp = client.request(
        "DELETE",
        "/api/push/subscribe",
        json={"endpoint": _SUB_ENDPOINT},
    )
    assert resp.status_code == 204
    conn.execute.assert_called_once()
    assert _SUB_ENDPOINT in conn.execute.call_args[0]


def test_unsubscribe_nonexistent_is_ok(authed_client):
    """DELETE on a non-existent endpoint should return 204 (idempotent)."""
    client, conn = authed_client
    conn.execute = AsyncMock(return_value=None)
    resp = client.request(
        "DELETE",
        "/api/push/subscribe",
        json={"endpoint": "https://nonexistent.example.com/push/xyz"},
    )
    assert resp.status_code == 204


def test_unsubscribe_unauthenticated(raw_client):
    resp = raw_client.request("DELETE", "/api/push/subscribe", json={"endpoint": _SUB_ENDPOINT})
    assert resp.status_code == 401
