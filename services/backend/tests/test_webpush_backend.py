"""Unit tests for the Web Push backend — no push service or DB required."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pywebpush import WebPushException

from app.backends.webpush import WebPushBackend


def _make_pool(subscriptions: list[dict]):
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=subscriptions)
    conn.execute = AsyncMock()
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


def _sub(name: str) -> dict:
    return {"endpoint": f"https://push.example/{name}", "p256dh": "k", "auth": "a"}


def _push_error(status: int) -> WebPushException:
    return WebPushException("push failed", response=MagicMock(status_code=status))


@pytest.mark.asyncio
async def test_failing_subscription_does_not_block_or_duplicate_others():
    pool, _ = _make_pool([_sub("broken"), _sub("phone"), _sub("laptop")])
    backend = WebPushBackend("private-key", "mailto:a@example.com", pool=pool)
    sent: list[str] = []

    def _fake_webpush(subscription_info, **_):
        if subscription_info["endpoint"].endswith("broken"):
            raise _push_error(403)
        sent.append(subscription_info["endpoint"])

    with patch("app.backends.webpush.webpush", side_effect=_fake_webpush):
        await backend.send({"id": "1", "severity": "critical", "signature": "X"})

    assert sent == ["https://push.example/phone", "https://push.example/laptop"]


@pytest.mark.asyncio
async def test_expired_subscription_is_deleted():
    pool, conn = _make_pool([_sub("gone")])
    backend = WebPushBackend("private-key", "mailto:a@example.com", pool=pool)

    with patch("app.backends.webpush.webpush", side_effect=_push_error(410)):
        await backend.send({"id": "1", "severity": "critical"})

    conn.execute.assert_awaited_once_with(
        "DELETE FROM push_subscriptions WHERE endpoint = $1", "https://push.example/gone"
    )
