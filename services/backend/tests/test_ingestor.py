"""
Unit tests for the EVE JSON ingestor.

parse_alert and _parse_timestamp are pure functions; ingest_alert is tested
with mock pool/redis objects.  File tailing and end-to-end ingestion are
covered by the integration tests (test_ingestor_integration.sh).
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ingestor import _parse_timestamp, ingest_alert, parse_alert

# ── Fixtures ──────────────────────────────────────────────────────────────────

MINIMAL_ALERT_EVENT = {
    "event_type": "alert",
    "timestamp": "2024-06-01T12:00:00.000000+0000",
    "src_ip": "192.168.1.10",
    "dest_ip": "1.2.3.4",
    "src_port": 54321,
    "dest_port": 443,
    "proto": "TCP",
    "alert": {
        "signature": "ET MALWARE Cobalt Strike Beacon",
        "signature_id": 2019839,
        "category": "Malware Command and Control Activity Detected",
        "severity": 1,
    },
}

NON_ALERT_EVENTS = [
    {"event_type": "dns", "dns": {"type": "query", "rrname": "example.com"}},
    {"event_type": "http", "http": {"url": "/index.html"}},
    {"event_type": "flow", "flow": {"pkts_toserver": 5}},
    {"event_type": "stats", "stats": {}},
    {"event_type": "tls"},
    {},  # missing event_type
]


# ── parse_alert: non-alert events ─────────────────────────────────────────────


@pytest.mark.parametrize("event", NON_ALERT_EVENTS)
def test_parse_alert_returns_none_for_non_alert(event):
    assert parse_alert(event) is None


# ── parse_alert: field mapping ────────────────────────────────────────────────


def test_parse_alert_maps_all_fields():
    result = parse_alert(MINIMAL_ALERT_EVENT)
    assert result is not None
    assert result["timestamp"] == "2024-06-01T12:00:00.000000+0000"
    assert result["src_ip"] == "192.168.1.10"
    assert result["dst_ip"] == "1.2.3.4"          # dest_ip → dst_ip
    assert result["src_port"] == 54321
    assert result["dst_port"] == 443               # dest_port → dst_port
    assert result["proto"] == "TCP"
    assert result["signature"] == "ET MALWARE Cobalt Strike Beacon"
    assert result["signature_id"] == 2019839
    assert result["category"] == "Malware Command and Control Activity Detected"
    assert result["raw_json"] is MINIMAL_ALERT_EVENT


def test_parse_alert_uses_dest_ip_key_not_dst_ip():
    """Suricata EVE JSON uses dest_ip; we must map it to dst_ip."""
    event = {**MINIMAL_ALERT_EVENT, "dest_ip": "10.0.0.1"}
    event.pop("dest_ip", None)
    event["dest_ip"] = "10.0.0.1"
    result = parse_alert(event)
    assert result["dst_ip"] == "10.0.0.1"


def test_parse_alert_handles_missing_optional_fields():
    event = {"event_type": "alert", "alert": {}}
    result = parse_alert(event)
    assert result is not None
    assert result["src_ip"] is None
    assert result["dst_ip"] is None
    assert result["src_port"] is None
    assert result["dst_port"] is None
    assert result["proto"] is None
    assert result["signature"] is None
    assert result["signature_id"] is None
    assert result["category"] is None


# ── parse_alert: severity mapping ─────────────────────────────────────────────


@pytest.mark.parametrize("priority,expected", [
    (1, "critical"),
    (2, "warning"),
    (3, "info"),
    (4, "info"),
    (None, "info"),
    (99, "info"),     # unknown priority
    (0, "info"),      # out-of-range
])
def test_severity_mapping(priority, expected):
    event = {
        "event_type": "alert",
        "alert": {"severity": priority} if priority is not None else {},
    }
    result = parse_alert(event)
    assert result["severity"] == expected


# ── _parse_timestamp ──────────────────────────────────────────────────────────


def test_parse_timestamp_suricata_format():
    ts = _parse_timestamp("2024-06-01T12:34:56.123456+0000")
    assert isinstance(ts, datetime)
    assert ts.tzinfo is not None
    assert ts.year == 2024
    assert ts.month == 6
    assert ts.day == 1
    assert ts.hour == 12


def test_parse_timestamp_utc_offset():
    ts = _parse_timestamp("2024-01-15T08:00:00+02:00")
    assert ts.tzinfo is not None
    assert ts.hour == 8


def test_parse_timestamp_naive_gets_utc():
    ts = _parse_timestamp("2024-01-15T08:00:00")
    assert ts.tzinfo == timezone.utc


def test_parse_timestamp_none_returns_utc_now():
    before = datetime.now(timezone.utc)
    ts = _parse_timestamp(None)
    after = datetime.now(timezone.utc)
    assert before <= ts <= after
    assert ts.tzinfo is not None


def test_parse_timestamp_invalid_string_returns_utc_now():
    before = datetime.now(timezone.utc)
    ts = _parse_timestamp("not-a-timestamp")
    after = datetime.now(timezone.utc)
    assert before <= ts <= after


# ── ingest_alert: mock-based ──────────────────────────────────────────────────


_MOCK_ALERT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _make_mock_pool():
    conn = AsyncMock()
    # INSERT ... RETURNING id uses fetchrow
    conn.fetchrow = AsyncMock(return_value={"id": _MOCK_ALERT_ID})
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


@pytest.mark.asyncio
async def test_ingest_alert_calls_db_insert():
    pool, conn = _make_mock_pool()
    redis_client = AsyncMock()
    redis_client.publish = AsyncMock()

    alert = parse_alert(MINIMAL_ALERT_EVENT)
    await ingest_alert(alert, pool, redis_client)

    conn.fetchrow.assert_called_once()
    call_args = conn.fetchrow.call_args
    assert "INSERT INTO alerts" in call_args[0][0]
    assert "RETURNING id" in call_args[0][0]


@pytest.mark.asyncio
async def test_ingest_alert_publishes_to_alerts_raw():
    pool, conn = _make_mock_pool()
    redis_client = AsyncMock()
    redis_client.publish = AsyncMock()

    from app.channels import ALERTS_RAW

    alert = parse_alert(MINIMAL_ALERT_EVENT)
    await ingest_alert(alert, pool, redis_client)

    calls = redis_client.publish.call_args_list
    raw_call = next((c for c in calls if c[0][0] == ALERTS_RAW), None)
    assert raw_call is not None, "Expected a publish to alerts:raw"
    data = json.loads(raw_call[0][1])
    assert data["signature"] == "ET MALWARE Cobalt Strike Beacon"
    assert data["severity"] == "critical"
    assert data["id"] == str(_MOCK_ALERT_ID)


@pytest.mark.asyncio
async def test_ingest_alert_publishes_only_to_alerts_raw():
    """With RAID-013 in place the ingestor only publishes to alerts:raw.
    The enricher reads from alerts:raw and publishes to alerts:enriched."""
    pool, conn = _make_mock_pool()
    redis_client = AsyncMock()
    redis_client.publish = AsyncMock()

    from app.channels import ALERTS_ENRICHED

    alert = parse_alert(MINIMAL_ALERT_EVENT)
    await ingest_alert(alert, pool, redis_client)

    calls = [c[0][0] for c in redis_client.publish.call_args_list]
    assert ALERTS_ENRICHED not in calls, "Ingestor must not publish directly to alerts:enriched"
    assert redis_client.publish.call_count == 1


@pytest.mark.asyncio
async def test_ingest_alert_passes_severity_as_string():
    """The severity column is a custom enum; we must pass it as text."""
    pool, conn = _make_mock_pool()
    redis_client = AsyncMock()
    redis_client.publish = AsyncMock()

    for priority, expected in [(1, "critical"), (2, "warning"), (3, "info")]:
        conn.fetchrow.reset_mock()
        event = {
            **MINIMAL_ALERT_EVENT,
            "alert": {**MINIMAL_ALERT_EVENT["alert"], "severity": priority},
        }
        alert = parse_alert(event)
        await ingest_alert(alert, pool, redis_client)

        # The severity value passed to fetchrow should be the string enum label
        args = conn.fetchrow.call_args[0]
        # args[0] is SQL, args[1:] are positional params; severity is $10
        assert args[10] == expected


@pytest.mark.asyncio
async def test_ingest_alert_raw_json_is_serialised():
    """raw_json must be JSON-encoded before being passed to asyncpg."""
    pool, conn = _make_mock_pool()
    redis_client = AsyncMock()
    redis_client.publish = AsyncMock()

    alert = parse_alert(MINIMAL_ALERT_EVENT)
    await ingest_alert(alert, pool, redis_client)

    args = conn.fetchrow.call_args[0]
    raw_json_param = args[11]  # $11 in the INSERT
    assert isinstance(raw_json_param, str)
    parsed = json.loads(raw_json_param)
    assert parsed["event_type"] == "alert"
