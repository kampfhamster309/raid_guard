"""
Unit tests for app.routers.status._probe_detection_stall.

Covers the 2026-09-01 incident: Suricata and capture-agent both reported
healthy the whole time (process/port checks only), while a stream-reassembly
memcap exhaustion silently stopped the detect engine from producing any
alert events for days. This probe is the thing that should have caught it.
"""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.routers.status import _probe_detection_stall


def _make_pool(last_alert_at):
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=last_alert_at)

    @asynccontextmanager
    async def acquire():
        yield conn

    pool = MagicMock()
    pool.acquire = acquire
    return pool


def _make_failing_pool(exc):
    @asynccontextmanager
    async def acquire():
        raise exc
        yield  # pragma: no cover

    pool = MagicMock()
    pool.acquire = acquire
    return pool


@pytest.mark.asyncio
async def test_not_applicable_when_capture_down():
    pool = _make_pool(datetime.now(timezone.utc))
    result = await _probe_detection_stall(pool, capture_ok=False, suricata_ok=True)
    assert result == {"ok": True, "reason": "not_applicable"}


@pytest.mark.asyncio
async def test_not_applicable_when_suricata_down():
    pool = _make_pool(datetime.now(timezone.utc))
    result = await _probe_detection_stall(pool, capture_ok=True, suricata_ok=False)
    assert result == {"ok": True, "reason": "not_applicable"}


@pytest.mark.asyncio
async def test_ok_when_eve_json_unreadable():
    pool = _make_pool(datetime.now(timezone.utc))
    with patch("app.routers.status.EVE_JSON_PATH", MagicMock(stat=MagicMock(side_effect=OSError("no such file")))):
        result = await _probe_detection_stall(pool, capture_ok=True, suricata_ok=True)
    assert result == {"ok": True, "reason": "eve_json_unreadable"}


def _eve_json_path_aged(seconds: float):
    import time
    return MagicMock(stat=MagicMock(return_value=MagicMock(st_mtime=time.time() - seconds)))


@pytest.mark.asyncio
async def test_fails_when_eve_json_stale_while_capture_and_suricata_healthy():
    """2026-11-24: the capture stream went silent without closing, capture-agent
    and Suricata both kept reporting healthy, and eve.json stopped moving for
    8+ hours.  Stale eve.json with both components "healthy" is itself the
    failure — it must not be waved through as someone else's problem."""
    pool = _make_pool(datetime.now(timezone.utc))
    with patch("app.routers.status._EVE_JSON_STALL_SECONDS", 900), \
         patch("app.routers.status.EVE_JSON_PATH", _eve_json_path_aged(8 * 3600)):
        result = await _probe_detection_stall(pool, capture_ok=True, suricata_ok=True)
    assert result["ok"] is False
    assert result["reason"] == "eve_json_stale"
    assert result["eve_json_minutes_ago"] == pytest.approx(480, abs=1)
    assert result["eve_json_stall_threshold_minutes"] == 15


@pytest.mark.asyncio
async def test_ok_when_eve_json_only_briefly_quiet():
    """Past the 'fresh' window but under the stall threshold: too early to page."""
    pool = _make_pool(datetime.now(timezone.utc))
    with patch("app.routers.status._EVE_JSON_STALL_SECONDS", 900), \
         patch("app.routers.status.EVE_JSON_PATH", _eve_json_path_aged(600)):
        result = await _probe_detection_stall(pool, capture_ok=True, suricata_ok=True)
    assert result == {"ok": True, "reason": "eve_json_quiet"}


@pytest.mark.asyncio
async def test_stale_eve_json_not_applicable_when_capture_already_down():
    """If capture already reports unhealthy, that's the signal — no duplicate."""
    pool = _make_pool(datetime.now(timezone.utc))
    with patch("app.routers.status.EVE_JSON_PATH", _eve_json_path_aged(8 * 3600)):
        result = await _probe_detection_stall(pool, capture_ok=False, suricata_ok=True)
    assert result == {"ok": True, "reason": "not_applicable"}


def _fresh_eve_json_path():
    import time
    return MagicMock(stat=MagicMock(return_value=MagicMock(st_mtime=time.time())))


@pytest.mark.asyncio
async def test_ok_when_db_unavailable():
    pool = _make_failing_pool(Exception("connection refused"))
    with patch("app.routers.status.EVE_JSON_PATH", _fresh_eve_json_path()):
        result = await _probe_detection_stall(pool, capture_ok=True, suricata_ok=True)
    assert result == {"ok": True, "reason": "db_unavailable"}


@pytest.mark.asyncio
async def test_ok_when_no_alert_history_yet():
    pool = _make_pool(None)
    with patch("app.routers.status.EVE_JSON_PATH", _fresh_eve_json_path()):
        result = await _probe_detection_stall(pool, capture_ok=True, suricata_ok=True)
    assert result == {"ok": True, "reason": "no_alert_history"}


@pytest.mark.asyncio
async def test_ok_when_recent_alert_exists():
    pool = _make_pool(datetime.now(timezone.utc) - timedelta(minutes=5))
    with patch("app.routers.status.EVE_JSON_PATH", _fresh_eve_json_path()):
        result = await _probe_detection_stall(pool, capture_ok=True, suricata_ok=True)
    assert result["ok"] is True
    assert result["last_alert_hours_ago"] < 1


@pytest.mark.asyncio
async def test_stalled_when_last_alert_exceeds_threshold():
    pool = _make_pool(datetime.now(timezone.utc) - timedelta(hours=30))
    with (
        patch("app.routers.status.EVE_JSON_PATH", _fresh_eve_json_path()),
        patch("app.routers.status._DETECTION_STALL_HOURS", 6.0),
    ):
        result = await _probe_detection_stall(pool, capture_ok=True, suricata_ok=True)
    assert result["ok"] is False
    assert result["last_alert_hours_ago"] == pytest.approx(30.0, abs=0.1)
    assert result["stall_threshold_hours"] == 6.0


@pytest.mark.asyncio
async def test_not_stalled_just_under_threshold():
    pool = _make_pool(datetime.now(timezone.utc) - timedelta(hours=5, minutes=30))
    with (
        patch("app.routers.status.EVE_JSON_PATH", _fresh_eve_json_path()),
        patch("app.routers.status._DETECTION_STALL_HOURS", 6.0),
    ):
        result = await _probe_detection_stall(pool, capture_ok=True, suricata_ok=True)
    assert result["ok"] is True
