"""
Unit tests for app/health_watcher.py.

All network calls and probe functions are mocked; no real services required.
Notification targets are fake objects exposing an async ``send_health_alert``.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.health_watcher import _notify_targets, _poll_once, run_health_watcher


# ── Fixtures ──────────────────────────────────────────────────────────────────


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


def _make_target(name="fake"):
    target = MagicMock()
    target.name = name
    target.send_health_alert = AsyncMock()
    return target


_ALL_COMPONENTS = ("db", "redis", "capture_agent", "suricata", "ingestor", "enricher", "detection")


# ── _notify_targets ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_targets_calls_every_target():
    t1, t2 = _make_target("a"), _make_target("b")
    await _notify_targets([t1, t2], "db", False)
    t1.send_health_alert.assert_awaited_once_with("db", "TimescaleDB", False)
    t2.send_health_alert.assert_awaited_once_with("db", "TimescaleDB", False)


@pytest.mark.asyncio
async def test_notify_targets_one_failure_does_not_block_others():
    failing = _make_target("failing")
    failing.send_health_alert = AsyncMock(side_effect=Exception("boom"))
    healthy = _make_target("healthy")
    await _notify_targets([failing, healthy], "redis", True)
    healthy.send_health_alert.assert_awaited_once_with("redis", "Redis", True)


# ── _poll_once ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_poll_once_no_notification_when_all_ok_from_start():
    redis = _make_redis()
    app_state = _make_app_state()
    target = _make_target()
    last: dict = {k: None for k in _ALL_COMPONENTS}

    with (
        patch("app.health_watcher._probe_db", AsyncMock(return_value=True)),
        patch("app.health_watcher._probe_redis", AsyncMock(return_value=True)),
        patch("app.health_watcher._probe_capture_agent", AsyncMock(return_value={"ok": True})),
        patch("app.health_watcher._probe_suricata_sync", MagicMock(return_value={"ok": True})),
        patch("app.health_watcher._probe_detection_stall", AsyncMock(return_value={"ok": True})),
    ):
        await _poll_once(None, redis, app_state, [target], last)

    target.send_health_alert.assert_not_awaited()
    assert last["db"] is True


@pytest.mark.asyncio
async def test_poll_once_notifies_when_already_unhealthy_on_first_poll():
    redis = _make_redis()
    app_state = _make_app_state()
    target = _make_target()
    last: dict = {k: None for k in _ALL_COMPONENTS}

    with (
        patch("app.health_watcher._probe_db", AsyncMock(return_value=False)),
        patch("app.health_watcher._probe_redis", AsyncMock(return_value=True)),
        patch("app.health_watcher._probe_capture_agent", AsyncMock(return_value={"ok": True})),
        patch("app.health_watcher._probe_suricata_sync", MagicMock(return_value={"ok": True})),
        patch("app.health_watcher._probe_detection_stall", AsyncMock(return_value={"ok": True})),
    ):
        await _poll_once(None, redis, app_state, [target], last)

    target.send_health_alert.assert_awaited_once_with("db", "TimescaleDB", False)


@pytest.mark.asyncio
async def test_poll_once_notifies_on_ok_to_unhealthy_transition():
    redis = _make_redis()
    app_state = _make_app_state()
    target = _make_target()
    last = {k: True for k in _ALL_COMPONENTS}

    with (
        patch("app.health_watcher._probe_db", AsyncMock(return_value=False)),
        patch("app.health_watcher._probe_redis", AsyncMock(return_value=True)),
        patch("app.health_watcher._probe_capture_agent", AsyncMock(return_value={"ok": True})),
        patch("app.health_watcher._probe_suricata_sync", MagicMock(return_value={"ok": True})),
        patch("app.health_watcher._probe_detection_stall", AsyncMock(return_value={"ok": True})),
    ):
        await _poll_once(None, redis, app_state, [target], last)

    target.send_health_alert.assert_awaited_once_with("db", "TimescaleDB", False)


@pytest.mark.asyncio
async def test_poll_once_notifies_on_unhealthy_to_ok_transition():
    redis = _make_redis()
    app_state = _make_app_state()
    target = _make_target()
    last = {**{k: True for k in _ALL_COMPONENTS}, "db": False}

    with (
        patch("app.health_watcher._probe_db", AsyncMock(return_value=True)),
        patch("app.health_watcher._probe_redis", AsyncMock(return_value=True)),
        patch("app.health_watcher._probe_capture_agent", AsyncMock(return_value={"ok": True})),
        patch("app.health_watcher._probe_suricata_sync", MagicMock(return_value={"ok": True})),
        patch("app.health_watcher._probe_detection_stall", AsyncMock(return_value={"ok": True})),
    ):
        await _poll_once(None, redis, app_state, [target], last)

    target.send_health_alert.assert_awaited_once_with("db", "TimescaleDB", True)


@pytest.mark.asyncio
async def test_poll_once_no_notification_when_stable_unhealthy():
    redis = _make_redis()
    app_state = _make_app_state()
    target = _make_target()
    last = {**{k: True for k in _ALL_COMPONENTS}, "db": False}

    with (
        patch("app.health_watcher._probe_db", AsyncMock(return_value=False)),
        patch("app.health_watcher._probe_redis", AsyncMock(return_value=True)),
        patch("app.health_watcher._probe_capture_agent", AsyncMock(return_value={"ok": True})),
        patch("app.health_watcher._probe_suricata_sync", MagicMock(return_value={"ok": True})),
        patch("app.health_watcher._probe_detection_stall", AsyncMock(return_value={"ok": True})),
    ):
        await _poll_once(None, redis, app_state, [target], last)

    target.send_health_alert.assert_not_awaited()


@pytest.mark.asyncio
async def test_poll_once_notifies_multiple_targets():
    redis = _make_redis()
    app_state = _make_app_state()
    t1, t2 = _make_target("ha"), _make_target("gotify")
    last: dict = {k: None for k in _ALL_COMPONENTS}

    with (
        patch("app.health_watcher._probe_db", AsyncMock(return_value=False)),
        patch("app.health_watcher._probe_redis", AsyncMock(return_value=True)),
        patch("app.health_watcher._probe_capture_agent", AsyncMock(return_value={"ok": True})),
        patch("app.health_watcher._probe_suricata_sync", MagicMock(return_value={"ok": True})),
        patch("app.health_watcher._probe_detection_stall", AsyncMock(return_value={"ok": True})),
    ):
        await _poll_once(None, redis, app_state, [t1, t2], last)

    t1.send_health_alert.assert_awaited_once_with("db", "TimescaleDB", False)
    t2.send_health_alert.assert_awaited_once_with("db", "TimescaleDB", False)


@pytest.mark.asyncio
async def test_poll_once_detects_ingestor_crash():
    redis = _make_redis()
    app_state = _make_app_state(ingestor_alive=False)
    target = _make_target()
    last = {k: True for k in _ALL_COMPONENTS}

    with (
        patch("app.health_watcher._probe_db", AsyncMock(return_value=True)),
        patch("app.health_watcher._probe_redis", AsyncMock(return_value=True)),
        patch("app.health_watcher._probe_capture_agent", AsyncMock(return_value={"ok": True})),
        patch("app.health_watcher._probe_suricata_sync", MagicMock(return_value={"ok": True})),
        patch("app.health_watcher._probe_detection_stall", AsyncMock(return_value={"ok": True})),
    ):
        await _poll_once(None, redis, app_state, [target], last)

    target.send_health_alert.assert_awaited_once_with("ingestor", "Alert Ingestor", False)


@pytest.mark.asyncio
async def test_poll_once_detects_detection_stall():
    """Capture + Suricata report healthy but no alerts for hours — the
    2026-09-01 incident shape, which the individual process checks alone
    never catch."""
    redis = _make_redis()
    app_state = _make_app_state()
    target = _make_target()
    last = {k: True for k in _ALL_COMPONENTS}

    with (
        patch("app.health_watcher._probe_db", AsyncMock(return_value=True)),
        patch("app.health_watcher._probe_redis", AsyncMock(return_value=True)),
        patch("app.health_watcher._probe_capture_agent", AsyncMock(return_value={"ok": True})),
        patch("app.health_watcher._probe_suricata_sync", MagicMock(return_value={"ok": True})),
        patch(
            "app.health_watcher._probe_detection_stall",
            AsyncMock(return_value={"ok": False, "last_alert_hours_ago": 30.0}),
        ),
    ):
        await _poll_once(None, redis, app_state, [target], last)

    target.send_health_alert.assert_awaited_once_with("detection", "Alert Detection", False)


@pytest.mark.asyncio
async def test_poll_once_detection_recovers_after_stall():
    redis = _make_redis()
    app_state = _make_app_state()
    target = _make_target()
    last = {**{k: True for k in _ALL_COMPONENTS}, "detection": False}

    with (
        patch("app.health_watcher._probe_db", AsyncMock(return_value=True)),
        patch("app.health_watcher._probe_redis", AsyncMock(return_value=True)),
        patch("app.health_watcher._probe_capture_agent", AsyncMock(return_value={"ok": True})),
        patch("app.health_watcher._probe_suricata_sync", MagicMock(return_value={"ok": True})),
        patch(
            "app.health_watcher._probe_detection_stall",
            AsyncMock(return_value={"ok": True, "last_alert_hours_ago": 0.1}),
        ),
    ):
        await _poll_once(None, redis, app_state, [target], last)

    target.send_health_alert.assert_awaited_once_with("detection", "Alert Detection", True)


# ── run_health_watcher ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_health_watcher_exits_when_no_targets():
    redis = _make_redis()
    app_state = _make_app_state()

    task = asyncio.create_task(
        run_health_watcher(None, redis, app_state, [], initial_delay=0, poll_interval=9999)
    )
    await asyncio.sleep(0.05)
    assert task.done()


@pytest.mark.asyncio
async def test_run_health_watcher_ignores_backends_without_health_support():
    redis = _make_redis()
    app_state = _make_app_state()
    webpush_like = MagicMock()  # no send_health_alert attribute
    del webpush_like.send_health_alert

    task = asyncio.create_task(
        run_health_watcher(None, redis, app_state, [webpush_like], initial_delay=0, poll_interval=9999)
    )
    await asyncio.sleep(0.05)
    assert task.done()


@pytest.mark.asyncio
async def test_run_health_watcher_notifies_configured_targets():
    redis = _make_redis()
    app_state = _make_app_state()
    target = _make_target()

    with (
        patch("app.health_watcher._probe_db", AsyncMock(return_value=False)),
        patch("app.health_watcher._probe_redis", AsyncMock(return_value=True)),
        patch("app.health_watcher._probe_capture_agent", AsyncMock(return_value={"ok": True})),
        patch("app.health_watcher._probe_suricata_sync", MagicMock(return_value={"ok": True})),
        patch("app.health_watcher._probe_detection_stall", AsyncMock(return_value={"ok": True})),
    ):
        task = asyncio.create_task(
            run_health_watcher(None, redis, app_state, [target], initial_delay=0, poll_interval=9999)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    target.send_health_alert.assert_awaited_once_with("db", "TimescaleDB", False)


@pytest.mark.asyncio
async def test_run_health_watcher_cancels_cleanly():
    redis = _make_redis()
    app_state = _make_app_state()
    target = _make_target()

    with (
        patch("app.health_watcher._probe_db", AsyncMock(return_value=True)),
        patch("app.health_watcher._probe_redis", AsyncMock(return_value=True)),
        patch("app.health_watcher._probe_capture_agent", AsyncMock(return_value={"ok": True})),
        patch("app.health_watcher._probe_suricata_sync", MagicMock(return_value={"ok": True})),
        patch("app.health_watcher._probe_detection_stall", AsyncMock(return_value={"ok": True})),
    ):
        task = asyncio.create_task(
            run_health_watcher(None, redis, app_state, [target], initial_delay=0, poll_interval=9999)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
