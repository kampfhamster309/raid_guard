"""Unit tests for /api/stats endpoint (mock DB)."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock


def test_stats_returns_200(authed_client):
    client, conn = authed_client
    conn.fetchval = AsyncMock(return_value=42)
    conn.fetch = AsyncMock(return_value=[])

    resp = client.get("/api/stats")
    assert resp.status_code == 200


def test_stats_response_structure(authed_client):
    client, conn = authed_client
    conn.fetchval = AsyncMock(return_value=0)
    conn.fetch = AsyncMock(return_value=[])

    body = client.get("/api/stats").json()
    assert "total_alerts_24h" in body
    assert "alerts_per_hour" in body
    assert "top_src_ips" in body
    assert "top_signatures" in body


def test_stats_total_count(authed_client):
    client, conn = authed_client
    conn.fetchval = AsyncMock(return_value=77)
    conn.fetch = AsyncMock(return_value=[])

    body = client.get("/api/stats").json()
    assert body["total_alerts_24h"] == 77


def test_stats_hourly_data(authed_client):
    client, conn = authed_client
    conn.fetchval = AsyncMock(return_value=5)

    hourly = [{"hour": datetime(2024, 6, 1, 10, 0, tzinfo=timezone.utc), "count": 5}]
    conn.fetch = AsyncMock(side_effect=[hourly, [], []])

    body = client.get("/api/stats").json()
    assert len(body["alerts_per_hour"]) == 1
    assert body["alerts_per_hour"][0]["count"] == 5


def test_stats_top_ips(authed_client):
    client, conn = authed_client
    conn.fetchval = AsyncMock(return_value=10)

    ip_rows = [{"name": "192.168.1.10", "count": 10}]
    conn.fetch = AsyncMock(side_effect=[[], ip_rows, []])

    body = client.get("/api/stats").json()
    assert len(body["top_src_ips"]) == 1
    assert body["top_src_ips"][0]["name"] == "192.168.1.10"
    assert body["top_src_ips"][0]["count"] == 10


def test_stats_top_signatures(authed_client):
    client, conn = authed_client
    conn.fetchval = AsyncMock(return_value=3)

    sig_rows = [{"name": "ET MALWARE Test", "count": 3}]
    conn.fetch = AsyncMock(side_effect=[[], [], sig_rows])

    body = client.get("/api/stats").json()
    assert body["top_signatures"][0]["name"] == "ET MALWARE Test"


def test_stats_requires_auth():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        resp = c.get("/api/stats")
    assert resp.status_code == 401
