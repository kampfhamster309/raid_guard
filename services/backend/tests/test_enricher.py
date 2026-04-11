"""
Unit tests for the AI enricher (RAID-013).

All LLM and Redis interactions are mocked — no LM Studio or Redis required.
"""

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.enricher import _build_user_prompt, _call_llm, _enrich_one, run_enricher


# ── Fixtures ──────────────────────────────────────────────────────────────────


_ALERT_ID = str(uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001"))

_SAMPLE_ALERT = {
    "id": _ALERT_ID,
    "severity": "critical",
    "signature": "ET MALWARE Cobalt Strike Beacon",
    "category": "Malware Command and Control",
    "src_ip": "192.168.1.5",
    "dst_ip": "1.2.3.4",
    "dst_port": 443,
    "proto": "TCP",
    "timestamp": "2026-04-11T10:00:00+00:00",
}

_GOOD_ENRICHMENT = {
    "summary": "Host beaconing to known C2 infrastructure",
    "severity_reasoning": "Critical is correct — Cobalt Strike C2 is a high-confidence indicator.",
    "recommended_action": "Isolate 192.168.1.5 and investigate for malware.",
}


def _make_pool():
    conn = AsyncMock()
    conn.execute = AsyncMock()
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


def _make_openai_response(content: str):
    """Build a minimal fake OpenAI chat completion response."""
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    return response


# ── _build_user_prompt ────────────────────────────────────────────────────────


def test_build_user_prompt_includes_key_fields():
    prompt = _build_user_prompt(_SAMPLE_ALERT)
    assert "ET MALWARE Cobalt Strike Beacon" in prompt
    assert "192.168.1.5" in prompt
    assert "critical" in prompt
    assert "1.2.3.4" in prompt


# ── _call_llm ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_call_llm_returns_parsed_dict_on_success():
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_make_openai_response(json.dumps(_GOOD_ENRICHMENT))
    )
    result = await _call_llm(client, _SAMPLE_ALERT, "gemma-4-27b", 30.0)
    assert result == _GOOD_ENRICHMENT


@pytest.mark.asyncio
async def test_call_llm_returns_none_on_timeout():
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(side_effect=asyncio.TimeoutError())
    result = await _call_llm(client, _SAMPLE_ALERT, "gemma-4-27b", 30.0)
    assert result is None


@pytest.mark.asyncio
async def test_call_llm_returns_none_on_api_error():
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(side_effect=Exception("Connection refused"))
    result = await _call_llm(client, _SAMPLE_ALERT, "gemma-4-27b", 30.0)
    assert result is None


@pytest.mark.asyncio
async def test_call_llm_returns_none_on_invalid_json():
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_make_openai_response("Sorry, I can't help with that.")
    )
    result = await _call_llm(client, _SAMPLE_ALERT, "gemma-4-27b", 30.0)
    assert result is None


@pytest.mark.asyncio
async def test_call_llm_returns_none_when_keys_missing():
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_make_openai_response('{"summary": "Something happened"}')
    )
    result = await _call_llm(client, _SAMPLE_ALERT, "gemma-4-27b", 30.0)
    assert result is None


# ── _enrich_one ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enrich_one_publishes_enriched_alert():
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_make_openai_response(json.dumps(_GOOD_ENRICHMENT))
    )
    redis = AsyncMock()
    pool, conn = _make_pool()

    await _enrich_one(client, redis, pool, _SAMPLE_ALERT, "model", 30.0)

    redis.publish.assert_awaited_once()
    channel, payload = redis.publish.call_args[0]
    from app.channels import ALERTS_ENRICHED
    assert channel == ALERTS_ENRICHED
    data = json.loads(payload)
    assert data["enrichment_json"] == _GOOD_ENRICHMENT
    assert data["id"] == _ALERT_ID


@pytest.mark.asyncio
async def test_enrich_one_writes_enrichment_to_db():
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_make_openai_response(json.dumps(_GOOD_ENRICHMENT))
    )
    redis = AsyncMock()
    pool, conn = _make_pool()

    await _enrich_one(client, redis, pool, _SAMPLE_ALERT, "model", 30.0)

    conn.execute.assert_awaited_once()
    sql, enrichment_json, alert_id = conn.execute.call_args[0]
    assert "UPDATE alerts" in sql
    assert json.loads(enrichment_json) == _GOOD_ENRICHMENT
    assert alert_id == _ALERT_ID


@pytest.mark.asyncio
async def test_enrich_one_publishes_unenriched_on_llm_failure():
    """If the LLM fails, the alert is published without enrichment — never dropped."""
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(side_effect=Exception("LLM down"))
    redis = AsyncMock()
    pool, _ = _make_pool()

    await _enrich_one(client, redis, pool, _SAMPLE_ALERT, "model", 30.0)

    redis.publish.assert_awaited_once()
    _, payload = redis.publish.call_args[0]
    data = json.loads(payload)
    assert "enrichment_json" not in data
    assert data["id"] == _ALERT_ID


@pytest.mark.asyncio
async def test_enrich_one_still_publishes_when_db_update_fails():
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_make_openai_response(json.dumps(_GOOD_ENRICHMENT))
    )
    redis = AsyncMock()
    pool, conn = _make_pool()
    conn.execute = AsyncMock(side_effect=Exception("DB error"))

    await _enrich_one(client, redis, pool, _SAMPLE_ALERT, "model", 30.0)

    # Must still publish to Redis even if DB write failed
    redis.publish.assert_awaited_once()


# ── run_enricher ──────────────────────────────────────────────────────────────


def _make_pubsub_messages(alerts: list[dict]):
    messages = [{"type": "subscribe", "data": 1}]
    for a in alerts:
        messages.append({"type": "message", "data": json.dumps(a)})

    async def _listen():
        for m in messages:
            yield m

    return _listen()


@pytest.mark.asyncio
async def test_run_enricher_passthrough_when_no_llm_configured(monkeypatch):
    """When LM_STUDIO_URL/LM_STUDIO_MODEL are unset, messages forward unchanged."""
    monkeypatch.delenv("LM_STUDIO_URL", raising=False)
    monkeypatch.delenv("LM_STUDIO_MODEL", raising=False)

    redis = MagicMock()
    pubsub = MagicMock()
    pubsub.subscribe = AsyncMock()
    raw_data = json.dumps(_SAMPLE_ALERT)
    pubsub.listen = lambda: _make_pubsub_messages([_SAMPLE_ALERT])
    pubsub.unsubscribe = AsyncMock()
    redis.pubsub = MagicMock(return_value=pubsub)
    redis.publish = AsyncMock()

    pool, _ = _make_pool()
    await run_enricher(redis, pool)

    from app.channels import ALERTS_ENRICHED
    redis.publish.assert_awaited_once()
    channel, payload = redis.publish.call_args[0]
    assert channel == ALERTS_ENRICHED
    # Payload should be the unmodified raw message data
    assert json.loads(payload) == _SAMPLE_ALERT


@pytest.mark.asyncio
async def test_run_enricher_calls_enrich_one_when_llm_configured(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_URL", "http://lmstudio:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "gemma-4-27b")

    redis = MagicMock()
    pubsub = MagicMock()
    pubsub.subscribe = AsyncMock()
    pubsub.listen = lambda: _make_pubsub_messages([_SAMPLE_ALERT])
    pubsub.unsubscribe = AsyncMock()
    redis.pubsub = MagicMock(return_value=pubsub)
    redis.publish = AsyncMock()

    pool, _ = _make_pool()

    with patch("app.enricher.AsyncOpenAI") as MockOpenAI:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_openai_response(json.dumps(_GOOD_ENRICHMENT))
        )
        MockOpenAI.return_value = mock_client
        await run_enricher(redis, pool)

    # Should have published to alerts:enriched with enrichment
    redis.publish.assert_awaited_once()
    _, payload = redis.publish.call_args[0]
    data = json.loads(payload)
    assert data["enrichment_json"] == _GOOD_ENRICHMENT


@pytest.mark.asyncio
async def test_run_enricher_skips_invalid_json(monkeypatch):
    monkeypatch.delenv("LM_STUDIO_URL", raising=False)
    monkeypatch.delenv("LM_STUDIO_MODEL", raising=False)

    redis = MagicMock()
    pubsub = MagicMock()
    pubsub.subscribe = AsyncMock()

    async def _bad_messages():
        yield {"type": "message", "data": "not-json"}

    pubsub.listen = _bad_messages
    pubsub.unsubscribe = AsyncMock()
    redis.pubsub = MagicMock(return_value=pubsub)
    redis.publish = AsyncMock()

    pool, _ = _make_pool()
    await run_enricher(redis, pool)
    redis.publish.assert_not_awaited()
