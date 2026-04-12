"""Unit tests for /api/digests endpoints (mock DB)."""

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.dependencies import get_redis
from app.main import app


_DIGEST_ID = uuid.UUID("eeeeeeee-0000-0000-0000-000000000005")
_NOW = datetime(2026, 4, 12, 10, 0, 0, tzinfo=timezone.utc)
_START = datetime(2026, 4, 11, 10, 0, 0, tzinfo=timezone.utc)

_DIGEST_CONTENT = json.dumps({
    "overall_risk": "medium",
    "summary": "Moderate activity with a few notable signatures.",
    "notable_incidents": ["Repeated SSH scan from 192.168.1.5."],
    "emerging_trends": [],
    "recommended_actions": ["Review 192.168.1.5 access logs."],
})


def _fake_digest_row():
    return {
        "id": _DIGEST_ID,
        "created_at": _NOW,
        "period_start": _START,
        "period_end": _NOW,
        "content": _DIGEST_CONTENT,
        "risk_level": "medium",
    }


# ── list_digests ──────────────────────────────────────────────────────────────


def test_list_digests_returns_200(authed_client):
    client, conn = authed_client
    conn.fetchval = AsyncMock(return_value=0)
    conn.fetch = AsyncMock(return_value=[])

    resp = client.get("/api/digests")
    assert resp.status_code == 200


def test_list_digests_empty(authed_client):
    client, conn = authed_client
    conn.fetchval = AsyncMock(return_value=0)
    conn.fetch = AsyncMock(return_value=[])

    body = client.get("/api/digests").json()
    assert body["total"] == 0
    assert body["items"] == []
    assert body["limit"] == 10
    assert body["offset"] == 0


def test_list_digests_returns_items(authed_client):
    client, conn = authed_client
    conn.fetchval = AsyncMock(return_value=1)
    conn.fetch = AsyncMock(return_value=[_fake_digest_row()])

    body = client.get("/api/digests").json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["risk_level"] == "medium"
    assert "overall_risk" in json.loads(item["content"])


def test_list_digests_pagination(authed_client):
    client, conn = authed_client
    conn.fetchval = AsyncMock(return_value=0)
    conn.fetch = AsyncMock(return_value=[])

    body = client.get("/api/digests?limit=5&offset=10").json()
    assert body["limit"] == 5
    assert body["offset"] == 10


def test_list_digests_requires_auth(raw_client):
    resp = raw_client.get("/api/digests")
    assert resp.status_code == 401


# ── get_digest ────────────────────────────────────────────────────────────────


def test_get_digest_returns_digest(authed_client):
    client, conn = authed_client
    conn.fetchrow = AsyncMock(return_value=_fake_digest_row())

    resp = client.get(f"/api/digests/{_DIGEST_ID}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["risk_level"] == "medium"
    assert body["content"] == _DIGEST_CONTENT


def test_get_digest_404(authed_client):
    client, conn = authed_client
    conn.fetchrow = AsyncMock(return_value=None)

    resp = client.get(f"/api/digests/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_get_digest_requires_auth(raw_client):
    resp = raw_client.get(f"/api/digests/{_DIGEST_ID}")
    assert resp.status_code == 401


# ── generate_digest ───────────────────────────────────────────────────────────


def test_generate_digest_returns_422_when_llm_not_configured(authed_client):
    client, conn = authed_client
    redis_mock = AsyncMock()
    app.dependency_overrides[get_redis] = lambda: redis_mock

    with patch(
        "app.routers.digests.get_llm_config",
        new=AsyncMock(return_value={"url": "", "model": "", "timeout": "90", "max_tokens": "512"}),
    ):
        resp = client.post("/api/digests/generate")

    assert resp.status_code == 422


def test_generate_digest_returns_204_when_skipped(authed_client):
    client, conn = authed_client
    redis_mock = AsyncMock()
    app.dependency_overrides[get_redis] = lambda: redis_mock

    with patch(
        "app.routers.digests.get_llm_config",
        new=AsyncMock(
            return_value={"url": "http://x:1234/v1", "model": "gemma", "timeout": "90", "max_tokens": "512"}
        ),
    ):
        with patch(
            "app.routers.digests.generate_digest",
            new=AsyncMock(return_value=None),
        ):
            resp = client.post("/api/digests/generate")

    assert resp.status_code == 204


def test_generate_digest_returns_digest_on_success(authed_client):
    client, conn = authed_client
    redis_mock = AsyncMock()
    app.dependency_overrides[get_redis] = lambda: redis_mock

    _fake = {
        "id": str(_DIGEST_ID),
        "created_at": _NOW.isoformat(),
        "period_start": _START.isoformat(),
        "period_end": _NOW.isoformat(),
        "content": _DIGEST_CONTENT,
        "risk_level": "medium",
    }

    with patch(
        "app.routers.digests.get_llm_config",
        new=AsyncMock(
            return_value={"url": "http://x:1234/v1", "model": "gemma", "timeout": "90", "max_tokens": "512"}
        ),
    ):
        with patch(
            "app.routers.digests.generate_digest",
            new=AsyncMock(return_value=_fake),
        ):
            resp = client.post("/api/digests/generate")

    assert resp.status_code == 200
    body = resp.json()
    assert body["risk_level"] == "medium"
