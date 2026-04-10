"""
Shared test fixtures for the backend unit test suite.

Mock pool and redis are injected via FastAPI dependency_overrides so no
real DB or Redis is needed for unit tests.
"""

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.auth import ADMIN_PASSWORD, ADMIN_USERNAME, create_token, require_auth
from app.dependencies import get_pool, get_redis
from app.main import app


# ── Mock DB pool ──────────────────────────────────────────────────────────────


def make_mock_pool():
    conn = AsyncMock()
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


# ── Mock alert rows ───────────────────────────────────────────────────────────


def _fake_alert_record(
    sig_id: int = 1001,
    severity: str = "critical",
    src_ip: str = "192.168.1.10",
):
    """Return a dict that mimics an asyncpg.Record for the alerts table."""
    import ipaddress

    rec = {
        "id": uuid.uuid4(),
        "timestamp": datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        "src_ip": ipaddress.IPv4Address(src_ip),
        "dst_ip": ipaddress.IPv4Address("1.2.3.4"),
        "src_port": 54321,
        "dst_port": 443,
        "proto": "TCP",
        "signature": "ET MALWARE Test",
        "signature_id": sig_id,
        "category": "Malware Command and Control Activity Detected",
        "severity": severity,
        "enrichment_json": None,
        "raw_json": json.dumps({"event_type": "alert"}),
    }
    return rec


# ── Auth bypass ───────────────────────────────────────────────────────────────


def override_require_auth():
    return ADMIN_USERNAME or "admin"


# ── Clients ───────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_pool_conn():
    pool, conn = make_mock_pool()
    return pool, conn


@pytest.fixture
def authed_client(mock_pool_conn):
    """TestClient with auth bypassed and a mock DB pool injected."""
    pool, conn = mock_pool_conn
    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[require_auth] = override_require_auth
    with TestClient(app) as c:
        yield c, conn
    app.dependency_overrides.clear()


@pytest.fixture
def raw_client():
    """TestClient without any dependency overrides (real auth required)."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def valid_token():
    import os
    # Temporarily set a known password so tests can obtain a real token
    return create_token(ADMIN_USERNAME or "admin")
