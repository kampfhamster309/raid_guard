"""
Integration tests for the EVE JSON ingestor.

Requires a running TimescaleDB (DATABASE_URL) and Redis (REDIS_URL).
Spun up by test_ingestor_integration.sh — skip automatically otherwise.
"""

import asyncio
import json
import os
import threading

import asyncpg
import pytest
import redis as syncredis

from app.channels import ALERTS_RAW
from app.ingestor import ingest_alert, parse_alert

# ── Fixtures ──────────────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get("DATABASE_URL", "")
REDIS_URL = os.environ.get("REDIS_URL", "")


@pytest.fixture
async def db_pool():
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL not set — run via test_ingestor_integration.sh")
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    yield pool
    await pool.close()


@pytest.fixture
def redis_client():
    if not REDIS_URL:
        pytest.skip("REDIS_URL not set — run via test_ingestor_integration.sh")
    client = syncredis.from_url(REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except syncredis.exceptions.ConnectionError:
        pytest.skip("Redis not reachable")
    yield client
    client.close()


@pytest.fixture
async def aioredis_client():
    import redis.asyncio as aioredis
    client = aioredis.from_url(REDIS_URL, decode_responses=True)
    yield client
    await client.aclose()


SAMPLE_EVE_ALERT = {
    "event_type": "alert",
    "timestamp": "2024-06-01T10:00:00.000000+0000",
    "src_ip": "192.168.1.55",
    "dest_ip": "185.220.101.50",
    "src_port": 45678,
    "dest_port": 443,
    "proto": "TCP",
    "alert": {
        "signature": "ET MALWARE Integration Test Beacon",
        "signature_id": 9000001,
        "category": "Malware Command and Control Activity Detected",
        "severity": 1,
    },
}


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_ingest_alert_row_appears_in_db(db_pool, aioredis_client):
    """ingest_alert must insert a row that is queryable by signature_id."""
    alert = parse_alert(SAMPLE_EVE_ALERT)
    assert alert is not None

    await ingest_alert(alert, db_pool, aioredis_client)

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            # host() strips the CIDR prefix that PostgreSQL adds to INET values
            "SELECT severity, host(src_ip) AS src_ip, host(dst_ip) AS dst_ip, proto "
            "FROM alerts WHERE signature_id = $1 "
            "ORDER BY timestamp DESC LIMIT 1",
            9000001,
        )

    assert row is not None, "Alert row not found in DB"
    assert row["severity"] == "critical"
    assert row["src_ip"] == "192.168.1.55"
    assert row["dst_ip"] == "185.220.101.50"
    assert row["proto"] == "TCP"


async def test_ingest_alert_publishes_to_redis_raw(db_pool, aioredis_client, redis_client):
    """ingest_alert must publish to the alerts:raw channel."""
    received: list = []

    def _subscribe(result: list):
        ps = redis_client.pubsub()
        ps.subscribe(ALERTS_RAW)
        import time
        deadline = time.monotonic() + 4.0
        try:
            for msg in ps.listen():
                if msg["type"] == "message":
                    result.append(msg["data"])
                    break
                if time.monotonic() > deadline:
                    break
        except Exception:
            pass
        finally:
            try:
                ps.unsubscribe()
                ps.close()
            except Exception:
                pass

    t = threading.Thread(target=_subscribe, args=(received,))
    t.start()

    import asyncio
    await asyncio.sleep(0.1)  # let subscriber register

    alert = parse_alert({
        **SAMPLE_EVE_ALERT,
        "alert": {**SAMPLE_EVE_ALERT["alert"], "signature_id": 9000002},
    })
    await ingest_alert(alert, db_pool, aioredis_client)

    t.join(timeout=5)

    assert len(received) == 1, f"Expected 1 message on {ALERTS_RAW}, got {len(received)}"
    data = json.loads(received[0])
    assert data["signature_id"] == 9000002
    assert data["severity"] == "critical"


async def test_ingest_alert_severity_mapping_stored_correctly(db_pool, aioredis_client):
    """Each Suricata priority should be stored with the correct severity label."""
    cases = [
        (1, "critical", 9000011),
        (2, "warning",  9000012),
        (3, "info",     9000013),
    ]
    for priority, expected_severity, sig_id in cases:
        event = {
            **SAMPLE_EVE_ALERT,
            "alert": {
                **SAMPLE_EVE_ALERT["alert"],
                "severity": priority,
                "signature_id": sig_id,
            },
        }
        alert = parse_alert(event)
        await ingest_alert(alert, db_pool, aioredis_client)

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT signature_id, severity FROM alerts "
            "WHERE signature_id = ANY($1::int[]) "
            "ORDER BY signature_id",
            [9000011, 9000012, 9000013],
        )

    assert len(rows) == 3
    assert rows[0]["severity"] == "critical"
    assert rows[1]["severity"] == "warning"
    assert rows[2]["severity"] == "info"


async def test_ingest_alert_raw_json_stored_as_jsonb(db_pool, aioredis_client):
    """The raw_json column must contain the original EVE event as JSONB."""
    event = {
        **SAMPLE_EVE_ALERT,
        "alert": {**SAMPLE_EVE_ALERT["alert"], "signature_id": 9000021},
    }
    alert = parse_alert(event)
    await ingest_alert(alert, db_pool, aioredis_client)

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT raw_json FROM alerts WHERE signature_id = $1 "
            "ORDER BY timestamp DESC LIMIT 1",
            9000021,
        )

    assert row is not None
    raw = row["raw_json"]
    # asyncpg may return JSONB as a string or a dict depending on codec config
    if isinstance(raw, str):
        raw = json.loads(raw)
    assert isinstance(raw, dict)
    assert raw["event_type"] == "alert"
    assert raw["src_ip"] == "192.168.1.55"
