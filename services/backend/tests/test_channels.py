"""
Integration tests for Redis pub/sub channel definitions.

Requires a running Redis instance.  The REDIS_URL env var must point to it
(set by the test_channels.sh wrapper which spins up a temporary container).
Tests are skipped automatically when Redis is unreachable.
"""

import json
import os
import threading
import time

import pytest
import redis

from app.channels import (
    ALERTS_ENRICHED,
    ALERTS_RAW,
    ALL_CHANNELS,
    get_redis_url,
    sync_redis,
)


# ── Fixture ───────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def r():
    """Return a Redis client; skip the whole module if Redis is unavailable."""
    client = sync_redis()
    try:
        client.ping()
    except redis.exceptions.ConnectionError:
        pytest.skip("Redis not reachable — set REDIS_URL and run via test_channels.sh")
    yield client
    client.close()


# ── Channel constants ─────────────────────────────────────────────────────────


def test_alerts_raw_channel_name():
    assert ALERTS_RAW == "alerts:raw"


def test_alerts_enriched_channel_name():
    assert ALERTS_ENRICHED == "alerts:enriched"


def test_all_channels_contains_expected():
    from app.channels import DIGESTS_NEW, INCIDENTS_NEW
    assert ALERTS_RAW in ALL_CHANNELS
    assert ALERTS_ENRICHED in ALL_CHANNELS
    assert INCIDENTS_NEW in ALL_CHANNELS
    assert DIGESTS_NEW in ALL_CHANNELS
    assert len(ALL_CHANNELS) == 4


# ── Connection helper ─────────────────────────────────────────────────────────


def test_get_redis_url_default(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    assert get_redis_url() == "redis://localhost:6379"


def test_get_redis_url_from_env(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://myhost:9999")
    assert get_redis_url() == "redis://myhost:9999"


def test_sync_redis_ping(r):
    assert r.ping() is True


# ── Pub/sub — alerts:raw ──────────────────────────────────────────────────────


def _subscribe_one(client: redis.Redis, channel: str, result: list, timeout: float = 3.0):
    """Subscribe to *channel*, store the first data message in *result*, then unsubscribe."""
    ps = client.pubsub()
    ps.subscribe(channel)
    deadline = time.monotonic() + timeout
    try:
        for msg in ps.listen():
            if msg["type"] == "message":
                result.append(msg["data"])
                break
            if time.monotonic() > deadline:
                break
    except Exception:
        pass  # connection closed by container teardown — result is already captured
    finally:
        try:
            ps.unsubscribe(channel)
            ps.close()
        except Exception:
            pass


def test_publish_to_alerts_raw(r):
    """Publish a message to alerts:raw and verify a subscriber receives it."""
    payload = json.dumps({"event_type": "alert", "src_ip": "192.168.1.1"})
    received: list = []

    subscriber = sync_redis()
    t = threading.Thread(target=_subscribe_one, args=(subscriber, ALERTS_RAW, received))
    t.start()
    time.sleep(0.1)  # let the subscriber register before publishing

    r.publish(ALERTS_RAW, payload)
    t.join(timeout=4)
    subscriber.close()

    assert len(received) == 1
    assert json.loads(received[0]) == json.loads(payload)


def test_publish_to_alerts_enriched(r):
    """Publish a message to alerts:enriched and verify a subscriber receives it."""
    payload = json.dumps({"event_type": "alert", "enrichment": {"summary": "Test"}})
    received: list = []

    subscriber = sync_redis()
    t = threading.Thread(target=_subscribe_one, args=(subscriber, ALERTS_ENRICHED, received))
    t.start()
    time.sleep(0.1)

    r.publish(ALERTS_ENRICHED, payload)
    t.join(timeout=4)
    subscriber.close()

    assert len(received) == 1
    assert json.loads(received[0])["enrichment"]["summary"] == "Test"


def test_channels_are_independent(r):
    """A subscriber on alerts:raw must not receive messages from alerts:enriched."""
    received: list = []

    subscriber = sync_redis()
    t = threading.Thread(
        target=_subscribe_one, args=(subscriber, ALERTS_RAW, received, 1.5)
    )
    t.start()
    time.sleep(0.1)

    # Publish only to the other channel — subscriber should get nothing
    r.publish(ALERTS_ENRICHED, json.dumps({"wrong": "channel"}))
    t.join(timeout=3)
    subscriber.close()

    assert received == []


def test_publish_returns_subscriber_count(r):
    """publish() returns the number of clients that received the message."""
    payload = json.dumps({"test": True})
    received: list = []

    subscriber = sync_redis()
    t = threading.Thread(target=_subscribe_one, args=(subscriber, ALERTS_RAW, received))
    t.start()
    time.sleep(0.1)

    count = r.publish(ALERTS_RAW, payload)
    t.join(timeout=4)
    subscriber.close()

    assert count == 1
