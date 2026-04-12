"""
Unit tests for the batch correlator (RAID-015).

All LLM, Redis, and DB interactions are mocked.
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.correlator import (
    _build_correlation_prompt,
    _call_correlator_llm,
    _fetch_recent_alerts,
    _run_correlation,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

_ID_A = str(uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001"))
_ID_B = str(uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002"))

_TS_A = datetime(2026, 4, 11, 10, 0, 0, tzinfo=timezone.utc)
_TS_B = datetime(2026, 4, 11, 10, 5, 0, tzinfo=timezone.utc)

_SAMPLE_ALERTS = [
    {
        "id": _ID_A,
        "timestamp": _TS_A,
        "timestamp_str": _TS_A.isoformat(),
        "signature": "ET SCAN Potential SSH Scan",
        "category": "Attempted Information Leak",
        "severity": "warning",
        "src_ip": "192.168.1.5",
        "dst_ip": "10.0.0.1",
    },
    {
        "id": _ID_B,
        "timestamp": _TS_B,
        "timestamp_str": _TS_B.isoformat(),
        "signature": "ET MALWARE Cobalt Strike Beacon",
        "category": "Malware Command and Control Activity Detected",
        "severity": "critical",
        "src_ip": "192.168.1.5",
        "dst_ip": "1.2.3.4",
    },
]

_LLM_INCIDENTS = [
    {
        "name": "Host 192.168.1.5 recon and C2",
        "risk_level": "critical",
        "narrative": "Host scanned network then established C2 channel.",
        "alert_indices": [0, 1],
    }
]


def _make_pool(alerts=None, config_rows=None):
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=alerts or [])
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=0)

    # Config fetch returns empty by default (use hard-coded defaults)
    if config_rows is not None:
        conn.fetch = AsyncMock(return_value=config_rows)

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


# ── _build_correlation_prompt ─────────────────────────────────────────────────


def test_build_correlation_prompt_includes_all_alerts():
    prompt = _build_correlation_prompt(_SAMPLE_ALERTS)
    assert "[0]" in prompt
    assert "[1]" in prompt
    assert "ET SCAN Potential SSH Scan" in prompt
    assert "ET MALWARE Cobalt Strike Beacon" in prompt
    assert "192.168.1.5" in prompt


def test_build_correlation_prompt_includes_severity_labels():
    prompt = _build_correlation_prompt(_SAMPLE_ALERTS)
    assert "WARNING" in prompt
    assert "CRITICAL" in prompt


# ── _call_correlator_llm ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_call_correlator_llm_returns_incidents_on_success():
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_make_openai_response(json.dumps({"incidents": _LLM_INCIDENTS}))
    )
    result = await _call_correlator_llm(client, _SAMPLE_ALERTS, "gemma-4-27b", 90.0)
    assert len(result) == 1
    assert result[0]["name"] == "Host 192.168.1.5 recon and C2"
    assert result[0]["risk_level"] == "critical"
    assert result[0]["alert_indices"] == [0, 1]


@pytest.mark.asyncio
async def test_call_correlator_llm_returns_empty_on_timeout():
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(side_effect=asyncio.TimeoutError())
    result = await _call_correlator_llm(client, _SAMPLE_ALERTS, "gemma-4-27b", 90.0)
    assert result == []


@pytest.mark.asyncio
async def test_call_correlator_llm_returns_empty_on_api_error():
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(side_effect=Exception("Connection refused"))
    result = await _call_correlator_llm(client, _SAMPLE_ALERTS, "gemma-4-27b", 90.0)
    assert result == []


@pytest.mark.asyncio
async def test_call_correlator_llm_returns_empty_on_invalid_json():
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_make_openai_response("Sorry, I cannot help.")
    )
    result = await _call_correlator_llm(client, _SAMPLE_ALERTS, "gemma-4-27b", 90.0)
    assert result == []


@pytest.mark.asyncio
async def test_call_correlator_llm_returns_empty_list_when_no_incidents():
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_make_openai_response(json.dumps({"incidents": []}))
    )
    result = await _call_correlator_llm(client, _SAMPLE_ALERTS, "gemma-4-27b", 90.0)
    assert result == []


# ── _run_correlation ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_correlation_skips_when_llm_not_configured(monkeypatch):
    monkeypatch.delenv("LM_STUDIO_URL", raising=False)
    monkeypatch.delenv("LM_STUDIO_MODEL", raising=False)

    pool, conn = _make_pool()
    # config table returns nothing → env vars → empty → no LLM
    conn.fetch = AsyncMock(return_value=[])

    redis = AsyncMock()
    await _run_correlation(redis, pool)
    redis.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_correlation_skips_when_too_few_alerts(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_URL", "http://lmstudio:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "gemma-4-27b")

    pool, conn = _make_pool()

    # Simulate: config fetch → empty; alert fetch → only 1 alert (below min 2)
    call_count = 0

    async def _fetch_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return []  # config rows
        if call_count == 2:
            return []  # correlation config rows
        return [_SAMPLE_ALERTS[0]]  # only 1 alert

    conn.fetch = AsyncMock(side_effect=_fetch_side_effect)

    redis = AsyncMock()
    with patch("app.correlator.AsyncOpenAI"):
        await _run_correlation(redis, pool)

    redis.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_correlation_inserts_incident_and_publishes(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_URL", "http://lmstudio:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "gemma-4-27b")

    _inserted_id = uuid.UUID("cccccccc-0000-0000-0000-000000000003")
    _now = datetime(2026, 4, 11, 10, 10, 0, tzinfo=timezone.utc)

    pool, conn = _make_pool()

    call_count = 0

    async def _fetch_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return []  # llm config rows (empty → env var fallback)
        if call_count == 2:
            return []  # correlation config rows
        # alert rows (asyncpg Record-like dicts)
        return [
            {
                "id": uuid.UUID(_ID_A),
                "timestamp": _TS_A,
                "signature": "ET SCAN Potential SSH Scan",
                "category": "Attempted Information Leak",
                "severity": "warning",
                "src_ip": None,
                "dst_ip": None,
            },
            {
                "id": uuid.UUID(_ID_B),
                "timestamp": _TS_B,
                "signature": "ET MALWARE Cobalt Strike Beacon",
                "category": "Malware Command and Control Activity Detected",
                "severity": "critical",
                "src_ip": None,
                "dst_ip": None,
            },
        ]

    conn.fetch = AsyncMock(side_effect=_fetch_side_effect)

    inserted_row = {
        "id": _inserted_id,
        "created_at": _now,
        "period_start": _TS_A,
        "period_end": _TS_B,
        "alert_ids": [uuid.UUID(_ID_A), uuid.UUID(_ID_B)],
        "narrative": "Host scanned network then established C2 channel.",
        "risk_level": "critical",
        "name": "Host 192.168.1.5 recon and C2",
    }
    conn.fetchrow = AsyncMock(return_value=inserted_row)

    redis = AsyncMock()

    with patch("app.correlator.AsyncOpenAI") as MockOpenAI:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_openai_response(
                json.dumps({"incidents": _LLM_INCIDENTS})
            )
        )
        MockOpenAI.return_value = mock_client
        await _run_correlation(redis, pool)

    redis.publish.assert_awaited_once()
    channel, payload = redis.publish.call_args[0]
    from app.channels import INCIDENTS_NEW
    assert channel == INCIDENTS_NEW
    data = json.loads(payload)
    assert data["risk_level"] == "critical"
    assert data["name"] == "Host 192.168.1.5 recon and C2"
    assert len(data["alert_ids"]) == 2


@pytest.mark.asyncio
async def test_run_correlation_skips_invalid_risk_level(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_URL", "http://lmstudio:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "gemma-4-27b")

    pool, conn = _make_pool()

    call_count = 0

    async def _fetch_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return []
        return [
            {"id": uuid.UUID(_ID_A), "timestamp": _TS_A, "signature": "A",
             "category": "X", "severity": "warning", "src_ip": None, "dst_ip": None},
            {"id": uuid.UUID(_ID_B), "timestamp": _TS_B, "signature": "B",
             "category": "Y", "severity": "critical", "src_ip": None, "dst_ip": None},
        ]

    conn.fetch = AsyncMock(side_effect=_fetch_side_effect)
    redis = AsyncMock()

    bad_incident = [{"name": "test", "risk_level": "severe", "narrative": "x", "alert_indices": [0, 1]}]

    with patch("app.correlator.AsyncOpenAI") as MockOpenAI:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_openai_response(json.dumps({"incidents": bad_incident}))
        )
        MockOpenAI.return_value = mock_client
        await _run_correlation(redis, pool)

    redis.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_correlation_skips_out_of_range_indices(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_URL", "http://lmstudio:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "gemma-4-27b")

    pool, conn = _make_pool()

    call_count = 0

    async def _fetch_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return []
        return [
            {"id": uuid.UUID(_ID_A), "timestamp": _TS_A, "signature": "A",
             "category": "X", "severity": "warning", "src_ip": None, "dst_ip": None},
            {"id": uuid.UUID(_ID_B), "timestamp": _TS_B, "signature": "B",
             "category": "Y", "severity": "critical", "src_ip": None, "dst_ip": None},
        ]

    conn.fetch = AsyncMock(side_effect=_fetch_side_effect)
    redis = AsyncMock()

    bad_indices_incident = [{"name": "test", "risk_level": "high", "narrative": "x", "alert_indices": [99, 100]}]

    with patch("app.correlator.AsyncOpenAI") as MockOpenAI:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_openai_response(json.dumps({"incidents": bad_indices_incident}))
        )
        MockOpenAI.return_value = mock_client
        await _run_correlation(redis, pool)

    redis.publish.assert_not_awaited()
