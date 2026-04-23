"""
Unit tests for the noise-tuner worker (RAID-015b).

All LLM and DB interactions are mocked.
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.noisetuner import (
    _build_tuner_prompt,
    _call_tuner_llm,
    _has_enough_history,
    _run_tuner,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

_NOW = datetime(2026, 4, 12, 10, 0, 0, tzinfo=timezone.utc)
_SUGGESTION_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000003")

_SAMPLE_SIGS = [
    {"signature": "ET SCAN Potential SSH Scan",      "signature_id": 2001219, "hit_count": 847, "distinct_src_ips": 3},
    {"signature": "ET INFO Session Traversal Utls",  "signature_id": 2008581, "hit_count": 312, "distinct_src_ips": 1},
]

_GOOD_SUGGESTIONS = {
    "suggestions": [
        {
            "signature_id":      2001219,
            "signature":         "ET SCAN Potential SSH Scan",
            "assessment":        "Typical home-network IoT scanning; rarely indicates a real attack.",
            "action":            "suppress",
            "threshold_type":    None,
            "threshold_track":   None,
            "threshold_count":   None,
            "threshold_seconds": None,
        },
        {
            "signature_id":      2008581,
            "signature":         "ET INFO Session Traversal Utls",
            "assessment":        "STUN traffic from VoIP or WebRTC apps; benign on home networks.",
            "action":            "threshold-adjust",
            "threshold_type":    "limit",
            "threshold_track":   "by_src",
            "threshold_count":   5,
            "threshold_seconds": 60,
        },
    ]
}


def _make_pool(*, fetchval_result=None, fetch_result=None, fetchrow_result=None):
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=fetchval_result)
    conn.fetch = AsyncMock(return_value=fetch_result or [])
    conn.fetchrow = AsyncMock(return_value=fetchrow_result)
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


def _make_openai_response(content: str):
    choice = MagicMock()
    choice.message.content = content
    resp = MagicMock()
    resp.choices = [choice]
    return resp


# ── _build_tuner_prompt ───────────────────────────────────────────────────────


def test_build_tuner_prompt_includes_signature_names():
    prompt = _build_tuner_prompt(_SAMPLE_SIGS, 7)
    assert "ET SCAN Potential SSH Scan" in prompt
    assert "ET INFO Session Traversal Utls" in prompt


def test_build_tuner_prompt_includes_hit_counts():
    prompt = _build_tuner_prompt(_SAMPLE_SIGS, 7)
    assert "847" in prompt
    assert "312" in prompt


def test_build_tuner_prompt_includes_lookback_days():
    prompt = _build_tuner_prompt(_SAMPLE_SIGS, 7)
    assert "7 days" in prompt


def test_build_tuner_prompt_includes_distinct_ips():
    prompt = _build_tuner_prompt(_SAMPLE_SIGS, 7)
    assert "3 distinct source IP" in prompt


def test_build_tuner_prompt_includes_signature_ids():
    prompt = _build_tuner_prompt(_SAMPLE_SIGS, 7)
    assert "2001219" in prompt
    assert "2008581" in prompt


def test_build_tuner_prompt_separates_signature_from_stats():
    prompt = _build_tuner_prompt(_SAMPLE_SIGS, 7)
    # Signature name must appear on its own labeled line, not merged with hit counts
    assert "signature: ET SCAN Potential SSH Scan" in prompt


# ── _call_tuner_llm ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_call_tuner_llm_returns_list_on_success():
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_make_openai_response(json.dumps(_GOOD_SUGGESTIONS))
    )
    result = await _call_tuner_llm(client, "prompt", "gemma", 90.0, _SAMPLE_SIGS)
    assert result is not None
    assert len(result) == 2
    assert result[0]["action"] == "suppress"
    assert result[0]["signature_id"] == 2001219
    assert result[1]["action"] == "threshold-adjust"


@pytest.mark.asyncio
async def test_call_tuner_llm_returns_none_on_timeout():
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(side_effect=asyncio.TimeoutError())
    result = await _call_tuner_llm(client, "prompt", "gemma", 90.0, _SAMPLE_SIGS)
    assert result is None


@pytest.mark.asyncio
async def test_call_tuner_llm_returns_none_on_invalid_json():
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_make_openai_response("Sorry, I cannot help.")
    )
    result = await _call_tuner_llm(client, "prompt", "gemma", 90.0, _SAMPLE_SIGS)
    assert result is None


@pytest.mark.asyncio
async def test_call_tuner_llm_extracts_threshold_params():
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_make_openai_response(json.dumps(_GOOD_SUGGESTIONS))
    )
    result = await _call_tuner_llm(client, "prompt", "gemma", 90.0, _SAMPLE_SIGS)
    assert result is not None
    threshold_item = next(r for r in result if r["action"] == "threshold-adjust")
    assert threshold_item["threshold_type"] == "limit"
    assert threshold_item["threshold_track"] == "by_src"
    assert threshold_item["threshold_count"] == 5
    assert threshold_item["threshold_seconds"] == 60


@pytest.mark.asyncio
async def test_call_tuner_llm_nulls_threshold_params_for_suppress():
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_make_openai_response(json.dumps(_GOOD_SUGGESTIONS))
    )
    result = await _call_tuner_llm(client, "prompt", "gemma", 90.0, _SAMPLE_SIGS)
    assert result is not None
    suppress_item = next(r for r in result if r["action"] == "suppress")
    assert suppress_item["threshold_count"] is None
    assert suppress_item["threshold_seconds"] is None
    assert suppress_item["threshold_track"] is None
    assert suppress_item["threshold_type"] is None


@pytest.mark.asyncio
async def test_call_tuner_llm_uses_echoed_signature_id():
    """LLM-echoed signature_id takes priority over string lookup."""
    data = {
        "suggestions": [{
            "signature_id":      9999999,  # not in sig_lookup but LLM echoed it
            "signature":         "ET SCAN Potential SSH Scan slightly rephrased",
            "assessment":        "Noise.",
            "action":            "suppress",
            "threshold_type":    None,
            "threshold_track":   None,
            "threshold_count":   None,
            "threshold_seconds": None,
        }]
    }
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_make_openai_response(json.dumps(data))
    )
    result = await _call_tuner_llm(client, "prompt", "gemma", 90.0, _SAMPLE_SIGS)
    assert result is not None
    assert result[0]["signature_id"] == 9999999


@pytest.mark.asyncio
async def test_call_tuner_llm_clamps_invalid_threshold_track():
    bad_track = {
        "suggestions": [
            {
                "signature_id":      2008581,
                "signature":         "ET INFO Session Traversal Utls",
                "assessment":        "STUN traffic.",
                "action":            "threshold-adjust",
                "threshold_type":    "limit",
                "threshold_track":   "invalid_value",
                "threshold_count":   5,
                "threshold_seconds": 60,
            },
        ]
    }
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_make_openai_response(json.dumps(bad_track))
    )
    result = await _call_tuner_llm(client, "prompt", "gemma", 90.0, _SAMPLE_SIGS)
    assert result is not None
    assert result[0]["threshold_track"] == "by_src"


@pytest.mark.asyncio
async def test_call_tuner_llm_clamps_unknown_action():
    bad = {
        "suggestions": [
            {"signature_id": 2001219, "signature": "ET SCAN Potential SSH Scan",
             "assessment": "ok", "action": "YOLO",
             "threshold_type": None, "threshold_track": None,
             "threshold_count": None, "threshold_seconds": None},
        ]
    }
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_make_openai_response(json.dumps(bad))
    )
    result = await _call_tuner_llm(client, "prompt", "gemma", 90.0, _SAMPLE_SIGS)
    assert result is not None
    assert result[0]["action"] == "keep"


# ── _has_enough_history ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_has_enough_history_true():
    from datetime import timedelta
    pool, conn = _make_pool(fetchval_result=_NOW - timedelta(days=10))
    result = await _has_enough_history(pool, 7)
    assert result is True


@pytest.mark.asyncio
async def test_has_enough_history_false_too_recent():
    from datetime import timedelta
    recent = datetime.now(timezone.utc) - timedelta(days=3)
    pool, conn = _make_pool(fetchval_result=recent)
    result = await _has_enough_history(pool, 7)
    assert result is False


@pytest.mark.asyncio
async def test_has_enough_history_false_no_alerts():
    pool, conn = _make_pool(fetchval_result=None)
    result = await _has_enough_history(pool, 7)
    assert result is False


# ── _run_tuner ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_tuner_skips_when_llm_not_configured(monkeypatch):
    monkeypatch.delenv("LM_STUDIO_URL", raising=False)
    monkeypatch.delenv("LM_STUDIO_MODEL", raising=False)

    pool, conn = _make_pool()
    conn.fetch = AsyncMock(return_value=[])  # empty config table → env fallback → empty

    result = await _run_tuner(pool)
    assert result == []


@pytest.mark.asyncio
async def test_run_tuner_skips_when_insufficient_history(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_URL", "http://lmstudio:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "gemma-4-27b")

    pool, conn = _make_pool()

    call_count = 0

    async def _fetch_side(query, *args):
        nonlocal call_count
        call_count += 1
        return []  # llm config / tuner config / pending signatures → all empty

    conn.fetch = AsyncMock(side_effect=_fetch_side)
    conn.fetchval = AsyncMock(return_value=None)  # no alerts → MIN(timestamp) is None

    with patch("app.noisetuner.AsyncOpenAI"):
        result = await _run_tuner(pool)

    assert result == []


@pytest.mark.asyncio
async def test_run_tuner_creates_suggestions(monkeypatch):
    from datetime import timedelta

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
            return []  # tuner config
        if call_count == 3:
            return []  # existing pending
        if call_count == 4:
            # noisy signatures
            return [
                {"signature": "ET SCAN Potential SSH Scan", "signature_id": 2001219,
                 "hit_count": 847, "distinct_src_ips": 3},
            ]
        return []

    conn.fetch = AsyncMock(side_effect=_fetch_side)
    conn.fetchval = AsyncMock(return_value=_NOW - timedelta(days=10))

    inserted_row = {
        "id": _SUGGESTION_ID,
        "created_at": _NOW,
        "signature": "ET SCAN Potential SSH Scan",
        "signature_id": 2001219,
        "hit_count": 847,
        "assessment": "Typical scanning noise.",
        "action": "suppress",
        "status": "pending",
        "confirmed_at": None,
        "threshold_count": None,
        "threshold_seconds": None,
        "threshold_track": None,
        "threshold_type": None,
    }
    conn.fetchrow = AsyncMock(return_value=inserted_row)

    with patch("app.noisetuner.AsyncOpenAI") as MockOpenAI:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_openai_response(
                json.dumps({
                    "suggestions": [{
                        "signature_id":      2001219,
                        "signature":         "ET SCAN Potential SSH Scan",
                        "assessment":        "Typical scanning noise.",
                        "action":            "suppress",
                        "threshold_type":    None,
                        "threshold_track":   None,
                        "threshold_count":   None,
                        "threshold_seconds": None,
                    }]
                })
            )
        )
        MockOpenAI.return_value = mock_client
        result = await _run_tuner(pool)

    assert result is not None
    assert len(result) == 1
    assert result[0]["action"] == "suppress"
    assert result[0]["signature"] == "ET SCAN Potential SSH Scan"
