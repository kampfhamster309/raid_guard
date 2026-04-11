"""
Unit tests for notification_router.py.

All Redis and DB interactions are mocked; no external services required.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from app.notification_router import (
    DEFAULT_THRESHOLD,
    SEVERITY_ORDER,
    NotificationBackend,
    _dispatch_with_retry,
    _get_threshold,
    run_notification_router,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_pool(fetchrow_return=None):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


def _make_backend(name="test", *, fail=False, fail_times=0):
    """Return a mock backend.  If fail=True, send() always raises.
    If fail_times > 0, send() raises that many times then succeeds."""
    backend = MagicMock()
    backend.name = name
    if fail:
        backend.send = AsyncMock(side_effect=RuntimeError("delivery failed"))
    elif fail_times:
        effects = [RuntimeError("transient")] * fail_times + [None]
        backend.send = AsyncMock(side_effect=effects)
    else:
        backend.send = AsyncMock(return_value=None)
    return backend


def _make_alert(severity="warning", alert_id="abc-123"):
    return {"id": alert_id, "severity": severity, "signature": "Test", "src_ip": "1.2.3.4"}


# ── _get_threshold ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_threshold_returns_default_when_no_row():
    pool, _ = _make_pool(fetchrow_return=None)
    result = await _get_threshold(pool)
    assert result == DEFAULT_THRESHOLD


@pytest.mark.asyncio
async def test_get_threshold_returns_configured_value():
    pool, _ = _make_pool(fetchrow_return={"value": "critical"})
    result = await _get_threshold(pool)
    assert result == "critical"


@pytest.mark.asyncio
async def test_get_threshold_returns_default_on_db_error():
    pool = MagicMock()
    pool.acquire.side_effect = Exception("DB down")
    result = await _get_threshold(pool)
    assert result == DEFAULT_THRESHOLD


# ── _dispatch_with_retry ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_succeeds_on_first_attempt():
    backend = _make_backend()
    alert = _make_alert()
    await _dispatch_with_retry(backend, alert)
    backend.send.assert_awaited_once_with(alert)


@pytest.mark.asyncio
async def test_dispatch_retries_on_transient_failure():
    backend = _make_backend(fail_times=1)
    alert = _make_alert()
    with patch("app.notification_router.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await _dispatch_with_retry(backend, alert, base_delay=1.0)
    assert backend.send.await_count == 2
    mock_sleep.assert_awaited_once_with(1.0)


@pytest.mark.asyncio
async def test_dispatch_gives_up_after_max_attempts():
    backend = _make_backend(fail=True)
    alert = _make_alert()
    with patch("app.notification_router.asyncio.sleep", new_callable=AsyncMock):
        await _dispatch_with_retry(backend, alert, max_attempts=3)
    # Must not raise; must have tried exactly 3 times
    assert backend.send.await_count == 3


@pytest.mark.asyncio
async def test_dispatch_doubles_delay_on_each_retry():
    backend = _make_backend(fail_times=2)
    alert = _make_alert()
    sleep_calls = []
    async def fake_sleep(d):
        sleep_calls.append(d)
    with patch("app.notification_router.asyncio.sleep", side_effect=fake_sleep):
        await _dispatch_with_retry(backend, alert, max_attempts=3, base_delay=1.0)
    assert sleep_calls == [1.0, 2.0]


# ── run_notification_router ───────────────────────────────────────────────────


def _make_pubsub_messages(alerts: list[dict], *, include_subscribe=True):
    """Build a fake async iterator of pubsub messages."""
    messages = []
    if include_subscribe:
        messages.append({"type": "subscribe", "data": 1})
    for a in alerts:
        messages.append({"type": "message", "data": json.dumps(a)})

    async def _listen():
        for m in messages:
            yield m

    return _listen()


@pytest.mark.asyncio
async def test_router_skips_alert_below_threshold():
    pool, _ = _make_pool(fetchrow_return={"value": "warning"})
    backend = _make_backend()

    redis = MagicMock()
    pubsub = MagicMock()
    pubsub.subscribe = AsyncMock()
    pubsub.listen = lambda: _make_pubsub_messages([_make_alert(severity="info")])
    pubsub.unsubscribe = AsyncMock()
    redis.pubsub = MagicMock(return_value=pubsub)

    await run_notification_router(redis, pool, [backend])
    backend.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_router_dispatches_alert_at_threshold():
    pool, _ = _make_pool(fetchrow_return={"value": "warning"})
    backend = _make_backend()

    redis = MagicMock()
    pubsub = MagicMock()
    pubsub.subscribe = AsyncMock()
    pubsub.listen = lambda: _make_pubsub_messages([_make_alert(severity="warning")])
    pubsub.unsubscribe = AsyncMock()
    redis.pubsub = MagicMock(return_value=pubsub)

    await run_notification_router(redis, pool, [backend])

    # create_task schedules work; run the event loop to let it complete
    await asyncio.sleep(0)
    backend.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_router_dispatches_alert_above_threshold():
    pool, _ = _make_pool(fetchrow_return={"value": "warning"})
    backend = _make_backend()

    redis = MagicMock()
    pubsub = MagicMock()
    pubsub.subscribe = AsyncMock()
    pubsub.listen = lambda: _make_pubsub_messages([_make_alert(severity="critical")])
    pubsub.unsubscribe = AsyncMock()
    redis.pubsub = MagicMock(return_value=pubsub)

    await run_notification_router(redis, pool, [backend])
    await asyncio.sleep(0)
    backend.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_router_exits_immediately_with_no_backends():
    pool, _ = _make_pool()
    redis = MagicMock()
    # Should return without subscribing to Redis
    await run_notification_router(redis, pool, [])
    redis.pubsub.assert_not_called()


@pytest.mark.asyncio
async def test_router_skips_invalid_json():
    pool, _ = _make_pool(fetchrow_return={"value": "warning"})
    backend = _make_backend()

    redis = MagicMock()
    pubsub = MagicMock()
    pubsub.subscribe = AsyncMock()

    async def _bad_messages():
        yield {"type": "message", "data": "not-json"}

    pubsub.listen = _bad_messages
    pubsub.unsubscribe = AsyncMock()
    redis.pubsub = MagicMock(return_value=pubsub)

    # Should log a warning and continue without raising
    await run_notification_router(redis, pool, [backend])
    backend.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_router_dispatches_to_multiple_backends():
    pool, _ = _make_pool(fetchrow_return={"value": "info"})
    backend_a = _make_backend("a")
    backend_b = _make_backend("b")

    redis = MagicMock()
    pubsub = MagicMock()
    pubsub.subscribe = AsyncMock()
    pubsub.listen = lambda: _make_pubsub_messages([_make_alert(severity="info")])
    pubsub.unsubscribe = AsyncMock()
    redis.pubsub = MagicMock(return_value=pubsub)

    await run_notification_router(redis, pool, [backend_a, backend_b])
    await asyncio.sleep(0)
    backend_a.send.assert_awaited_once()
    backend_b.send.assert_awaited_once()
