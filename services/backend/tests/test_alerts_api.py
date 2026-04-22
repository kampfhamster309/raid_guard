"""Unit tests for /api/alerts endpoints (mock DB)."""

import json
import uuid
from datetime import datetime, timezone
from ipaddress import IPv4Address
from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import _fake_alert_record


# ── list_alerts ───────────────────────────────────────────────────────────────


def test_list_alerts_returns_200(authed_client):
    client, conn = authed_client
    conn.fetchval = AsyncMock(return_value=0)
    conn.fetch = AsyncMock(return_value=[])

    resp = client.get("/api/alerts")
    assert resp.status_code == 200


def test_list_alerts_response_structure(authed_client):
    client, conn = authed_client
    conn.fetchval = AsyncMock(return_value=0)
    conn.fetch = AsyncMock(return_value=[])

    body = client.get("/api/alerts").json()
    assert "items" in body
    assert "total" in body
    assert "limit" in body
    assert "offset" in body
    assert body["total"] == 0
    assert body["items"] == []


def test_list_alerts_pagination_defaults(authed_client):
    client, conn = authed_client
    conn.fetchval = AsyncMock(return_value=0)
    conn.fetch = AsyncMock(return_value=[])

    body = client.get("/api/alerts").json()
    assert body["limit"] == 50
    assert body["offset"] == 0


def test_list_alerts_custom_pagination(authed_client):
    client, conn = authed_client
    conn.fetchval = AsyncMock(return_value=0)
    conn.fetch = AsyncMock(return_value=[])

    body = client.get("/api/alerts?limit=10&offset=20").json()
    assert body["limit"] == 10
    assert body["offset"] == 20


def test_list_alerts_invalid_limit(authed_client):
    client, conn = authed_client
    resp = client.get("/api/alerts?limit=0")
    assert resp.status_code == 422  # validation error


def test_list_alerts_limit_too_large(authed_client):
    client, conn = authed_client
    resp = client.get("/api/alerts?limit=201")
    assert resp.status_code == 422


def test_list_alerts_invalid_severity(authed_client):
    client, conn = authed_client
    resp = client.get("/api/alerts?severity=unknown")
    assert resp.status_code == 422


def test_list_alerts_serialises_row_correctly(authed_client):
    client, conn = authed_client
    record = _fake_alert_record(sig_id=9999, severity="critical", src_ip="10.0.0.1")
    conn.fetchval = AsyncMock(return_value=1)
    conn.fetch = AsyncMock(return_value=[record])

    body = client.get("/api/alerts").json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["signature_id"] == 9999
    assert item["severity"] == "critical"
    assert item["src_ip"] == "10.0.0.1"
    assert item["dst_ip"] == "1.2.3.4"
    assert "raw_json" not in item  # summary omits raw_json


def test_list_alerts_ip_returned_without_cidr(authed_client):
    """asyncpg returns IPv4Address objects; we must stringify without /prefix."""
    client, conn = authed_client
    record = _fake_alert_record(src_ip="192.168.1.55")
    conn.fetchval = AsyncMock(return_value=1)
    conn.fetch = AsyncMock(return_value=[record])

    body = client.get("/api/alerts").json()
    assert body["items"][0]["src_ip"] == "192.168.1.55"


def test_list_alerts_enrichment_json_decoded(authed_client):
    client, conn = authed_client
    record = {**_fake_alert_record(), "enrichment_json": '{"summary": "Test"}'}
    conn.fetchval = AsyncMock(return_value=1)
    conn.fetch = AsyncMock(return_value=[record])

    body = client.get("/api/alerts").json()
    assert body["items"][0]["enrichment_json"] == {"summary": "Test"}


# ── get_alert ─────────────────────────────────────────────────────────────────


def test_get_alert_returns_200(authed_client):
    client, conn = authed_client
    record = _fake_alert_record()
    conn.fetchrow = AsyncMock(return_value=record)

    alert_id = record["id"]
    resp = client.get(f"/api/alerts/{alert_id}")
    assert resp.status_code == 200


def test_get_alert_includes_raw_json(authed_client):
    client, conn = authed_client
    record = _fake_alert_record()
    conn.fetchrow = AsyncMock(return_value=record)

    alert_id = record["id"]
    body = client.get(f"/api/alerts/{alert_id}").json()
    assert "raw_json" in body
    assert body["raw_json"] == {"event_type": "alert"}


def test_get_alert_not_found(authed_client):
    client, conn = authed_client
    conn.fetchrow = AsyncMock(return_value=None)

    resp = client.get(f"/api/alerts/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_get_alert_invalid_uuid(authed_client):
    client, conn = authed_client
    resp = client.get("/api/alerts/not-a-uuid")
    assert resp.status_code == 422


# ── enrich_alert ──────────────────────────────────────────────────────────────

_ENRICHMENT = {
    "summary": "Port scan from internal host",
    "severity_reasoning": "Warning is appropriate.",
    "recommended_action": "Investigate the source device.",
}

_LLM_CFG = {"url": "http://lm-studio:1234/v1", "model": "gemma-4-27b", "timeout": "90", "max_tokens": "512"}


def test_enrich_alert_returns_enrichment(authed_client):
    client, conn = authed_client
    record = _fake_alert_record()
    conn.fetchrow = AsyncMock(return_value=record)
    conn.execute = AsyncMock(return_value=None)

    with (
        patch("app.routers.alerts.get_llm_config", AsyncMock(return_value=_LLM_CFG)),
        patch("app.routers.alerts.enrich_single_alert", AsyncMock(return_value=_ENRICHMENT)),
    ):
        resp = client.post(f"/api/alerts/{record['id']}/enrich")

    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"] == _ENRICHMENT["summary"]
    assert body["severity_reasoning"] == _ENRICHMENT["severity_reasoning"]
    assert body["recommended_action"] == _ENRICHMENT["recommended_action"]


def test_enrich_alert_llm_not_configured(authed_client):
    client, conn = authed_client
    cfg_no_llm = {"url": "", "model": "", "timeout": "90", "max_tokens": "512"}

    with patch("app.routers.alerts.get_llm_config", AsyncMock(return_value=cfg_no_llm)):
        resp = client.post(f"/api/alerts/{uuid.uuid4()}/enrich")

    assert resp.status_code == 422
    assert "LLM not configured" in resp.json()["detail"]


def test_enrich_alert_not_found(authed_client):
    client, conn = authed_client
    conn.fetchrow = AsyncMock(return_value=None)

    with patch("app.routers.alerts.get_llm_config", AsyncMock(return_value=_LLM_CFG)):
        resp = client.post(f"/api/alerts/{uuid.uuid4()}/enrich")

    assert resp.status_code == 404


def test_enrich_alert_llm_failure(authed_client):
    client, conn = authed_client
    record = _fake_alert_record()
    conn.fetchrow = AsyncMock(return_value=record)

    with (
        patch("app.routers.alerts.get_llm_config", AsyncMock(return_value=_LLM_CFG)),
        patch("app.routers.alerts.enrich_single_alert", AsyncMock(return_value=None)),
    ):
        resp = client.post(f"/api/alerts/{record['id']}/enrich")

    assert resp.status_code == 504
    assert "timed out" in resp.json()["detail"]
