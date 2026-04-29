import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_pool, get_redis
from app.main import app


async def _noop(*args, **kwargs):
    try:
        await asyncio.sleep(float("inf"))
    except asyncio.CancelledError:
        pass


def _make_mock_pool():
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=1)
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    pool.close = AsyncMock()
    return pool, conn


def _make_mock_redis():
    r = AsyncMock()
    r.ping = AsyncMock(return_value=True)
    r.aclose = AsyncMock()
    return r


@pytest.fixture
def health_client():
    mock_pool, mock_conn = _make_mock_pool()
    mock_redis = _make_mock_redis()

    app.dependency_overrides[get_pool] = lambda: mock_pool
    app.dependency_overrides[get_redis] = lambda: mock_redis

    with (
        patch("app.main.ingestor_loop", _noop),
        patch("app.main.run_enricher", _noop),
        patch("app.main.run_correlator", _noop),
        patch("app.main.run_digestor", _noop),
        patch("app.main.run_noisetuner", _noop),
        patch("app.main.run_notification_router", _noop),
    ):
        with TestClient(app) as c:
            yield c, mock_pool, mock_conn, mock_redis

    app.dependency_overrides.clear()


def test_health_returns_200(health_client):
    c, *_ = health_client
    response = c.get("/health")
    assert response.status_code == 200


def test_health_payload_ok(health_client):
    c, *_ = health_client
    data = c.get("/health").json()
    assert data["status"] == "ok"
    assert data["service"] == "backend"
    assert data["db"] is True
    assert data["redis"] is True
    assert data["ingestor"] is True
    assert data["enricher"] is True


def test_health_returns_503_when_db_down(health_client):
    c, pool, conn, _ = health_client
    pool.acquire.return_value.__aenter__ = AsyncMock(side_effect=Exception("DB down"))
    response = c.get("/health")
    assert response.status_code == 503
    assert response.json()["db"] is False
    assert response.json()["status"] == "degraded"


def test_health_returns_503_when_redis_down(health_client):
    c, _, _, redis = health_client
    redis.ping = AsyncMock(side_effect=Exception("Redis down"))
    response = c.get("/health")
    assert response.status_code == 503
    assert response.json()["redis"] is False


def test_health_returns_503_when_ingestor_dead(health_client):
    c, *_ = health_client
    dead = MagicMock()
    dead.done.return_value = True
    app.state.ingestor_task = dead
    response = c.get("/health")
    assert response.status_code == 503
    assert response.json()["ingestor"] is False


def test_health_returns_503_when_enricher_dead(health_client):
    c, *_ = health_client
    dead = MagicMock()
    dead.done.return_value = True
    app.state.enrich_task = dead
    response = c.get("/health")
    assert response.status_code == 503
    assert response.json()["enricher"] is False
