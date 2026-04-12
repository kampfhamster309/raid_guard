"""
Unit tests for the periodic digest worker (RAID-015a).

All LLM, Redis, DB, and httpx interactions are mocked.
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.digestor import (
    _build_digest_prompt,
    _call_digest_llm,
    _fetch_period_stats,
    _run_digest,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

_NOW = datetime(2026, 4, 12, 10, 0, 0, tzinfo=timezone.utc)
_DIGEST_ID = uuid.UUID("eeeeeeee-0000-0000-0000-000000000005")

_SAMPLE_STATS = {
    "total_alerts": 42,
    "by_severity": {"critical": 3, "warning": 15, "info": 24},
    "top_signatures": [
        {"name": "ET SCAN Potential SSH Scan", "count": 10},
        {"name": "ET MALWARE Cobalt Strike", "count": 3},
    ],
    "top_ips": [{"ip": "192.168.1.5", "count": 20}],
}

_SAMPLE_INCIDENTS = [
    {"name": "SSH scan + C2", "risk_level": "critical", "narrative": "Host scanned then beaconed."},
]

_GOOD_DIGEST = {
    "overall_risk": "high",
    "summary": "Elevated activity with a confirmed C2 beacon.",
    "notable_incidents": ["Host 192.168.1.5 performed recon then established C2."],
    "emerging_trends": ["Increasing outbound port-scan activity."],
    "recommended_actions": ["Investigate 192.168.1.5 immediately."],
}


def _make_pool(fetch_side_effect=None, fetchrow_result=None, fetchval_result=None):
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[]) if fetch_side_effect is None else AsyncMock(side_effect=fetch_side_effect)
    conn.fetchrow = AsyncMock(return_value=fetchrow_result)
    conn.fetchval = AsyncMock(return_value=fetchval_result or 0)
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


def _make_openai_response(content: str):
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    return response


# ── _build_digest_prompt ──────────────────────────────────────────────────────


def test_build_digest_prompt_includes_totals():
    prompt = _build_digest_prompt(_SAMPLE_STATS, [], _NOW, _NOW)
    assert "42 total" in prompt
    assert "critical: 3" in prompt
    assert "warning: 15" in prompt


def test_build_digest_prompt_includes_top_signatures():
    prompt = _build_digest_prompt(_SAMPLE_STATS, [], _NOW, _NOW)
    assert "ET SCAN Potential SSH Scan" in prompt
    assert "ET MALWARE Cobalt Strike" in prompt


def test_build_digest_prompt_includes_incidents():
    prompt = _build_digest_prompt(_SAMPLE_STATS, _SAMPLE_INCIDENTS, _NOW, _NOW)
    assert "SSH scan + C2" in prompt
    assert "critical" in prompt


def test_build_digest_prompt_no_incidents_omits_section():
    prompt = _build_digest_prompt(_SAMPLE_STATS, [], _NOW, _NOW)
    assert "Correlated incidents" not in prompt


# ── _call_digest_llm ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_call_digest_llm_returns_dict_on_success():
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_make_openai_response(json.dumps(_GOOD_DIGEST))
    )
    result = await _call_digest_llm(client, "prompt", "gemma-4-27b", 90.0)
    assert result is not None
    assert result["overall_risk"] == "high"
    assert result["summary"] == _GOOD_DIGEST["summary"]
    assert isinstance(result["notable_incidents"], list)


@pytest.mark.asyncio
async def test_call_digest_llm_returns_none_on_timeout():
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(side_effect=asyncio.TimeoutError())
    result = await _call_digest_llm(client, "prompt", "gemma-4-27b", 90.0)
    assert result is None


@pytest.mark.asyncio
async def test_call_digest_llm_returns_none_on_api_error():
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(side_effect=Exception("Connection refused"))
    result = await _call_digest_llm(client, "prompt", "gemma-4-27b", 90.0)
    assert result is None


@pytest.mark.asyncio
async def test_call_digest_llm_returns_none_on_invalid_json():
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_make_openai_response("Sorry, I can't help.")
    )
    result = await _call_digest_llm(client, "prompt", "gemma-4-27b", 90.0)
    assert result is None


@pytest.mark.asyncio
async def test_call_digest_llm_clamps_invalid_risk_level():
    bad_digest = {**_GOOD_DIGEST, "overall_risk": "extreme"}
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_make_openai_response(json.dumps(bad_digest))
    )
    result = await _call_digest_llm(client, "prompt", "gemma-4-27b", 90.0)
    assert result is not None
    assert result["overall_risk"] == "low"


# ── _run_digest ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_digest_skips_when_llm_not_configured(monkeypatch):
    monkeypatch.delenv("LM_STUDIO_URL", raising=False)
    monkeypatch.delenv("LM_STUDIO_MODEL", raising=False)

    pool, conn = _make_pool()
    conn.fetch = AsyncMock(return_value=[])  # empty config table → env fallback → empty
    redis = AsyncMock()

    result = await _run_digest(pool, redis)
    assert result is None
    redis.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_digest_skips_when_too_few_alerts(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_URL", "http://lmstudio:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "gemma-4-27b")

    pool, conn = _make_pool()

    call_count = 0

    async def _fetch_side(query, *args):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return []  # llm config
        if call_count == 2:
            return []  # digest config
        if call_count == 3:
            return []  # by_severity
        if call_count == 4:
            return []  # top signatures
        return []  # top ips / incidents

    conn.fetch = AsyncMock(side_effect=_fetch_side)
    conn.fetchval = AsyncMock(return_value=2)  # 2 alerts < min_alerts (5)

    redis = AsyncMock()

    with patch("app.digestor.AsyncOpenAI"):
        result = await _run_digest(pool, redis)

    assert result is None
    redis.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_digest_creates_digest_and_publishes(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_URL", "http://lmstudio:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "gemma-4-27b")

    pool, conn = _make_pool()

    call_count = 0

    async def _fetch_side(query, *args):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return []  # llm config rows → env fallback
        if call_count == 2:
            return []  # digest config rows → defaults
        if call_count == 3:
            return [{"sev": "warning", "cnt": 10}]  # by_severity
        if call_count == 4:
            return [{"signature": "ET SCAN SSH Scan", "cnt": 5}]  # top sigs
        if call_count == 5:
            return [{"ip": "192.168.1.5", "cnt": 10}]  # top ips
        return []  # incidents

    conn.fetch = AsyncMock(side_effect=_fetch_side)
    conn.fetchval = AsyncMock(return_value=10)  # > min_alerts (5)

    inserted_row = {
        "id": _DIGEST_ID,
        "created_at": _NOW,
        "period_start": _NOW,
        "period_end": _NOW,
        "content": json.dumps(_GOOD_DIGEST),
        "risk_level": "high",
    }
    conn.fetchrow = AsyncMock(return_value=inserted_row)

    redis = AsyncMock()

    with patch("app.digestor.AsyncOpenAI") as MockOpenAI:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_openai_response(json.dumps(_GOOD_DIGEST))
        )
        MockOpenAI.return_value = mock_client
        result = await _run_digest(pool, redis)

    assert result is not None
    assert result["risk_level"] == "high"

    redis.publish.assert_awaited_once()
    channel, payload = redis.publish.call_args[0]
    from app.channels import DIGESTS_NEW
    assert channel == DIGESTS_NEW
    data = json.loads(payload)
    assert data["risk_level"] == "high"
