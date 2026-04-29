"""
Unit tests for app/health_watcher.py.

All network calls and probe functions are mocked; no real services required.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.health_watcher import _is_enabled, _poll_once, _send_notification, run_health_watcher


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_pool(fetchrow_return=None):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


def _make_redis():
    redis = AsyncMock()
    redis.ping = AsyncMock()
    return redis


def _make_app_state(ingestor_alive=True, enricher_alive=True):
    ingestor_task = MagicMock()
    ingestor_task.done = MagicMock(return_value=not ingestor_alive)
    enrich_task = MagicMock()
    enrich_task.done = MagicMock(return_value=not enricher_alive)
    return SimpleNamespace(ingestor_task=ingestor_task, enrich_task=enrich_task)


def _all_ok_probes():
    return (
        True,  # db
        True,  # redis
        {"ok": True, "capture_state": "streaming", "reconnect_count": 0, "message": ""},  # capture
        {"ok": True, "running": True, "health": "healthy"},  # suricata
    )


def _mock_httpx_post_ok():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=resp)
    return client


# ── _is_enabled ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_is_enabled_defaults_true_when_no_row():
    pool = _make_pool(fetchrow_return=None)
    assert await _is_enabled(pool) is True


@pytest.mark.asyncio
async def test_is_enabled_false_when_config_says_false():
    pool = _make_pool(fetchrow_return={"value": "false"})
    assert await _is_enabled(pool) is False


@pytest.mark.asyncio
async def test_is_enabled_defaults_true_on_db_error():
    pool = MagicMock()
    pool.acquire.side_effect = Exception("DB down")
    assert await _is_enabled(pool) is True


# ── _send_notification ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_notification_posts_unhealthy():
    client = _mock_httpx_post_ok()
    with patch("app.health_watcher.httpx.AsyncClient", return_value=client):
        await _send_notification("http://ha.local/wh", "db", False)
    call_args = client.post.call_args
    payload = call_args[1]["json"]
    assert payload["healthy"] is False
    assert "TimescaleDB" in payload["message"]
    assert "Unhealthy" in payload["title"]


@pytest.mark.asyncio
async def test_send_notification_posts_recovered():
    client = _mock_httpx_post_ok()
    with patch("app.health_watcher.httpx.AsyncClient", return_value=client):
        await _send_notification("http://ha.local/wh", "redis", True)
    payload = client.post.call_args[1]["json"]
    assert payload["healthy"] is True
    assert "Recovered" in payload["title"]
    assert "Redis" in payload["component_label"]


@pytest.mark.asyncio
async def test_send_notification_silently_ignores_http_error():
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(side_effect=Exception("Connection refused"))
    with patch("app.health_watcher.httpx.AsyncClient", return_value=client):
        await _send_notification("http://ha.local/wh", "db", False)
    # no exception raised


# ── _poll_once ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_poll_once_no_notification_when_all_ok_from_start():
    pool = _make_pool()
    redis = _make_redis()
    app_state = _make_app_state()
    last: dict = {k: None for k in ("db", "redis", "capture_agent", "suricata", "ingestor", "enricher")}

    with (
        patch("app.health_watcher._probe_db", AsyncMock(return_value=True)),
        patch("app.health_watcher._probe_redis", AsyncMock(return_value=True)),
        patch("app.health_watcher._probe_capture_agent", AsyncMock(return_value={"ok": True})),
        patch("app.health_watcher._probe_suricata_sync", MagicMock(return_value={"ok": True})),
        patch("app.health_watcher._send_notification", AsyncMock()) as mock_notify,
    ):
        await _poll_once(pool, redis, app_state, "http://ha.local/wh", last)

    mock_notify.assert_not_awaited()
    assert last["db"] is True


@pytest.mark.asyncio
async def test_poll_once_notifies_when_already_unhealthy_on_first_poll():
    pool = _make_pool()
    redis = _make_redis()
    app_state = _make_app_state()
    last: dict = {k: None for k in ("db", "redis", "capture_agent", "suricata", "ingestor", "enricher")}

    with (
        patch("app.health_watcher._probe_db", AsyncMock(return_value=False)),
        patch("app.health_watcher._probe_redis", AsyncMock(return_value=True)),
        patch("app.health_watcher._probe_capture_agent", AsyncMock(return_value={"ok": True})),
        patch("app.health_watcher._probe_suricata_sync", MagicMock(return_value={"ok": True})),
        patch("app.health_watcher._send_notification", AsyncMock()) as mock_notify,
    ):
        await _poll_once(pool, redis, app_state, "http://ha.local/wh", last)

    mock_notify.assert_awaited_once_with("http://ha.local/wh", "db", False)


@pytest.mark.asyncio
async def test_poll_once_notifies_on_ok_to_unhealthy_transition():
    pool = _make_pool()
    redis = _make_redis()
    app_state = _make_app_state()
    last = {"db": True, "redis": True, "capture_agent": True, "suricata": True, "ingestor": True, "enricher": True}

    with (
        patch("app.health_watcher._probe_db", AsyncMock(return_value=False)),
        patch("app.health_watcher._probe_redis", AsyncMock(return_value=True)),
        patch("app.health_watcher._probe_capture_agent", AsyncMock(return_value={"ok": True})),
        patch("app.health_watcher._probe_suricata_sync", MagicMock(return_value={"ok": True})),
        patch("app.health_watcher._send_notification", AsyncMock()) as mock_notify,
    ):
        await _poll_once(pool, redis, app_state, "http://ha.local/wh", last)

    mock_notify.assert_awaited_once_with("http://ha.local/wh", "db", False)


@pytest.mark.asyncio
async def test_poll_once_notifies_on_unhealthy_to_ok_transition():
    pool = _make_pool()
    redis = _make_redis()
    app_state = _make_app_state()
    last = {"db": False, "redis": True, "capture_agent": True, "suricata": True, "ingestor": True, "enricher": True}

    with (
        patch("app.health_watcher._probe_db", AsyncMock(return_value=True)),
        patch("app.health_watcher._probe_redis", AsyncMock(return_value=True)),
        patch("app.health_watcher._probe_capture_agent", AsyncMock(return_value={"ok": True})),
        patch("app.health_watcher._probe_suricata_sync", MagicMock(return_value={"ok": True})),
        patch("app.health_watcher._send_notification", AsyncMock()) as mock_notify,
    ):
        await _poll_once(pool, redis, app_state, "http://ha.local/wh", last)

    mock_notify.assert_awaited_once_with("http://ha.local/wh", "db", True)


@pytest.mark.asyncio
async def test_poll_once_no_notification_when_stable_unhealthy():
    pool = _make_pool()
    redis = _make_redis()
    app_state = _make_app_state()
    last = {"db": False, "redis": True, "capture_agent": True, "suricata": True, "ingestor": True, "enricher": True}

    with (
        patch("app.health_watcher._probe_db", AsyncMock(return_value=False)),
        patch("app.health_watcher._probe_redis", AsyncMock(return_value=True)),
        patch("app.health_watcher._probe_capture_agent", AsyncMock(return_value={"ok": True})),
        patch("app.health_watcher._probe_suricata_sync", MagicMock(return_value={"ok": True})),
        patch("app.health_watcher._send_notification", AsyncMock()) as mock_notify,
    ):
        await _poll_once(pool, redis, app_state, "http://ha.local/wh", last)

    mock_notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_poll_once_skips_when_health_alerts_disabled():
    pool = _make_pool(fetchrow_return={"value": "false"})
    redis = _make_redis()
    app_state = _make_app_state()
    last: dict = {k: None for k in ("db", "redis", "capture_agent", "suricata", "ingestor", "enricher")}

    with (
        patch("app.health_watcher._probe_db", AsyncMock(return_value=False)),
        patch("app.health_watcher._send_notification", AsyncMock()) as mock_notify,
    ):
        await _poll_once(pool, redis, app_state, "http://ha.local/wh", last)

    mock_notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_poll_once_detects_ingestor_crash():
    pool = _make_pool()
    redis = _make_redis()
    app_state = _make_app_state(ingestor_alive=False)
    last = {"db": True, "redis": True, "capture_agent": True, "suricata": True, "ingestor": True, "enricher": True}

    with (
        patch("app.health_watcher._probe_db", AsyncMock(return_value=True)),
        patch("app.health_watcher._probe_redis", AsyncMock(return_value=True)),
        patch("app.health_watcher._probe_capture_agent", AsyncMock(return_value={"ok": True})),
        patch("app.health_watcher._probe_suricata_sync", MagicMock(return_value={"ok": True})),
        patch("app.health_watcher._send_notification", AsyncMock()) as mock_notify,
    ):
        await _poll_once(pool, redis, app_state, "http://ha.local/wh", last)

    mock_notify.assert_awaited_once_with("http://ha.local/wh", "ingestor", False)


# ── run_health_watcher ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_health_watcher_exits_when_no_webhook(monkeypatch):
    monkeypatch.delenv("HA_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("HA_HEALTH_WEBHOOK_URL", raising=False)
    pool = _make_pool()
    redis = _make_redis()
    app_state = _make_app_state()

    task = asyncio.create_task(
        run_health_watcher(pool, redis, app_state, initial_delay=0, poll_interval=9999)
    )
    await asyncio.sleep(0.05)
    assert task.done()


@pytest.mark.asyncio
async def test_run_health_watcher_uses_health_webhook_when_set(monkeypatch):
    monkeypatch.setenv("HA_WEBHOOK_URL", "http://ha.local/alerts")
    monkeypatch.setenv("HA_HEALTH_WEBHOOK_URL", "http://ha.local/health")
    pool = _make_pool()
    redis = _make_redis()
    app_state = _make_app_state()
    # DB is unhealthy from the start → should notify on first poll
    last_seen: list[str] = []

    async def _capture_notify(url: str, component: str, ok: bool) -> None:
        last_seen.append(url)

    with (
        patch("app.health_watcher._probe_db", AsyncMock(return_value=False)),
        patch("app.health_watcher._probe_redis", AsyncMock(return_value=True)),
        patch("app.health_watcher._probe_capture_agent", AsyncMock(return_value={"ok": True})),
        patch("app.health_watcher._probe_suricata_sync", MagicMock(return_value={"ok": True})),
        patch("app.health_watcher._send_notification", AsyncMock(side_effect=_capture_notify)),
    ):
        task = asyncio.create_task(
            run_health_watcher(pool, redis, app_state, initial_delay=0, poll_interval=9999)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert last_seen == ["http://ha.local/health"]


@pytest.mark.asyncio
async def test_run_health_watcher_falls_back_to_alert_webhook(monkeypatch):
    monkeypatch.setenv("HA_WEBHOOK_URL", "http://ha.local/alerts")
    monkeypatch.delenv("HA_HEALTH_WEBHOOK_URL", raising=False)
    pool = _make_pool()
    redis = _make_redis()
    app_state = _make_app_state()
    last_seen: list[str] = []

    async def _capture_notify(url: str, component: str, ok: bool) -> None:
        last_seen.append(url)

    with (
        patch("app.health_watcher._probe_db", AsyncMock(return_value=False)),
        patch("app.health_watcher._probe_redis", AsyncMock(return_value=True)),
        patch("app.health_watcher._probe_capture_agent", AsyncMock(return_value={"ok": True})),
        patch("app.health_watcher._probe_suricata_sync", MagicMock(return_value={"ok": True})),
        patch("app.health_watcher._send_notification", AsyncMock(side_effect=_capture_notify)),
    ):
        task = asyncio.create_task(
            run_health_watcher(pool, redis, app_state, initial_delay=0, poll_interval=9999)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert last_seen == ["http://ha.local/alerts"]


@pytest.mark.asyncio
async def test_run_health_watcher_cancels_cleanly(monkeypatch):
    monkeypatch.setenv("HA_WEBHOOK_URL", "http://ha.local/wh")
    pool = _make_pool()
    redis = _make_redis()
    app_state = _make_app_state()

    with (
        patch("app.health_watcher._probe_db", AsyncMock(return_value=True)),
        patch("app.health_watcher._probe_redis", AsyncMock(return_value=True)),
        patch("app.health_watcher._probe_capture_agent", AsyncMock(return_value={"ok": True})),
        patch("app.health_watcher._probe_suricata_sync", MagicMock(return_value={"ok": True})),
    ):
        task = asyncio.create_task(
            run_health_watcher(pool, redis, app_state, initial_delay=0, poll_interval=9999)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
