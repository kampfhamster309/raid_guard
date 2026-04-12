"""Unit tests for /api/incidents endpoints (mock DB)."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from tests.conftest import _fake_alert_record


_INC_ID = uuid.UUID("dddddddd-0000-0000-0000-000000000004")
_ALERT_ID_1 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_ALERT_ID_2 = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
_NOW = datetime(2026, 4, 11, 10, 0, 0, tzinfo=timezone.utc)
_TS_START = datetime(2026, 4, 11, 9, 30, 0, tzinfo=timezone.utc)
_TS_END = datetime(2026, 4, 11, 10, 0, 0, tzinfo=timezone.utc)


def _fake_incident_row():
    return {
        "id": _INC_ID,
        "created_at": _NOW,
        "period_start": _TS_START,
        "period_end": _TS_END,
        "alert_ids": [_ALERT_ID_1, _ALERT_ID_2],
        "narrative": "Host scanned then beaconed.",
        "risk_level": "critical",
        "name": "SSH scan followed by C2",
    }


# ── list_incidents ────────────────────────────────────────────────────────────


def test_list_incidents_returns_200(authed_client):
    client, conn = authed_client
    conn.fetchval = AsyncMock(return_value=0)
    conn.fetch = AsyncMock(return_value=[])

    resp = client.get("/api/incidents")
    assert resp.status_code == 200


def test_list_incidents_empty(authed_client):
    client, conn = authed_client
    conn.fetchval = AsyncMock(return_value=0)
    conn.fetch = AsyncMock(return_value=[])

    body = client.get("/api/incidents").json()
    assert body["total"] == 0
    assert body["items"] == []
    assert body["limit"] == 20
    assert body["offset"] == 0


def test_list_incidents_returns_items(authed_client):
    client, conn = authed_client
    conn.fetchval = AsyncMock(return_value=1)
    conn.fetch = AsyncMock(return_value=[_fake_incident_row()])

    body = client.get("/api/incidents").json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["risk_level"] == "critical"
    assert item["name"] == "SSH scan followed by C2"
    assert len(item["alert_ids"]) == 2


def test_list_incidents_pagination(authed_client):
    client, conn = authed_client
    conn.fetchval = AsyncMock(return_value=0)
    conn.fetch = AsyncMock(return_value=[])

    body = client.get("/api/incidents?limit=5&offset=10").json()
    assert body["limit"] == 5
    assert body["offset"] == 10


def test_list_incidents_requires_auth(raw_client):
    resp = raw_client.get("/api/incidents")
    assert resp.status_code == 401


# ── get_incident ──────────────────────────────────────────────────────────────


def test_get_incident_returns_incident(authed_client):
    client, conn = authed_client
    conn.fetchrow = AsyncMock(return_value=_fake_incident_row())
    conn.fetch = AsyncMock(return_value=[])  # no alerts found

    resp = client.get(f"/api/incidents/{_INC_ID}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["risk_level"] == "critical"
    assert body["name"] == "SSH scan followed by C2"
    assert body["alerts"] == []


def test_get_incident_returns_alerts(authed_client):
    client, conn = authed_client
    conn.fetchrow = AsyncMock(return_value=_fake_incident_row())
    conn.fetch = AsyncMock(
        return_value=[_fake_alert_record(sig_id=1001), _fake_alert_record(sig_id=1002)]
    )

    resp = client.get(f"/api/incidents/{_INC_ID}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["alerts"]) == 2


def test_get_incident_404(authed_client):
    client, conn = authed_client
    conn.fetchrow = AsyncMock(return_value=None)

    missing_id = uuid.uuid4()
    resp = client.get(f"/api/incidents/{missing_id}")
    assert resp.status_code == 404


def test_get_incident_requires_auth(raw_client):
    resp = raw_client.get(f"/api/incidents/{_INC_ID}")
    assert resp.status_code == 401
