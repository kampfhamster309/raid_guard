"""
Unit tests for the LLM settings API (RAID-014).

GET/PUT /api/settings/llm
POST    /api/settings/llm/test
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import make_mock_pool


# ── Helpers ───────────────────────────────────────────────────────────────────


def _db_row(key: str, value: str):
    """Minimal mock of an asyncpg Row."""
    return {"key": key, "value": value}


def _make_openai_response(content: str):
    choice = MagicMock()
    choice.message.content = content
    resp = MagicMock()
    resp.choices = [choice]
    return resp


_GOOD_LLM_RESPONSE = json.dumps({
    "summary": "Test DNS query to suspicious domain",
    "severity_reasoning": "Info is appropriate — no confirmed compromise.",
    "recommended_action": "Monitor for repeat queries from this host.",
})

_DB_CONFIG = [
    _db_row("lm_studio_url",        "http://lmstudio:1234/v1"),
    _db_row("lm_studio_model",      "gemma-4-27b"),
    _db_row("lm_enrichment_timeout","90"),
    _db_row("lm_max_tokens",        "512"),
]


# ── GET /api/settings/llm ─────────────────────────────────────────────────────


def test_get_llm_settings_returns_db_values(authed_client):
    client, conn = authed_client
    conn.fetch = AsyncMock(return_value=_DB_CONFIG)

    resp = client.get("/api/settings/llm")
    assert resp.status_code == 200
    data = resp.json()
    assert data["url"] == "http://lmstudio:1234/v1"
    assert data["model"] == "gemma-4-27b"
    assert data["timeout"] == 90
    assert data["max_tokens"] == 512


def test_get_llm_settings_falls_back_to_env(authed_client, monkeypatch):
    client, conn = authed_client
    conn.fetch = AsyncMock(return_value=[])  # nothing in DB
    monkeypatch.setenv("LM_STUDIO_URL", "http://env-host:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "my-model")
    monkeypatch.setenv("LM_ENRICHMENT_TIMEOUT", "120")
    monkeypatch.setenv("LM_MAX_TOKENS", "256")

    resp = client.get("/api/settings/llm")
    assert resp.status_code == 200
    data = resp.json()
    assert data["url"] == "http://env-host:1234/v1"
    assert data["model"] == "my-model"
    assert data["timeout"] == 120
    assert data["max_tokens"] == 256


def test_get_llm_settings_returns_defaults_when_empty(authed_client, monkeypatch):
    client, conn = authed_client
    conn.fetch = AsyncMock(return_value=[])
    for key in ("LM_STUDIO_URL", "LM_STUDIO_MODEL", "LM_ENRICHMENT_TIMEOUT", "LM_MAX_TOKENS"):
        monkeypatch.delenv(key, raising=False)

    resp = client.get("/api/settings/llm")
    assert resp.status_code == 200
    data = resp.json()
    assert data["url"] == ""
    assert data["model"] == ""
    assert data["timeout"] == 90
    assert data["max_tokens"] == 512


# ── PUT /api/settings/llm ─────────────────────────────────────────────────────


def test_set_llm_settings_persists_values(authed_client):
    client, conn = authed_client
    conn.execute = AsyncMock()

    payload = {"url": "http://new:1234/v1", "model": "llama-3", "timeout": 60, "max_tokens": 256}
    resp = client.put("/api/settings/llm", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["url"] == "http://new:1234/v1"
    assert data["model"] == "llama-3"
    assert data["timeout"] == 60
    assert data["max_tokens"] == 256
    # 4 INSERT … ON CONFLICT calls (one per config key)
    assert conn.execute.await_count == 4


def test_set_llm_settings_rejects_timeout_too_low(authed_client):
    client, _ = authed_client
    resp = client.put("/api/settings/llm", json={"url": "x", "model": "y", "timeout": 0, "max_tokens": 512})
    assert resp.status_code == 422


def test_set_llm_settings_rejects_timeout_too_high(authed_client):
    client, _ = authed_client
    resp = client.put("/api/settings/llm", json={"url": "x", "model": "y", "timeout": 601, "max_tokens": 512})
    assert resp.status_code == 422


def test_set_llm_settings_rejects_max_tokens_too_low(authed_client):
    client, _ = authed_client
    resp = client.put("/api/settings/llm", json={"url": "x", "model": "y", "timeout": 90, "max_tokens": 32})
    assert resp.status_code == 422


def test_set_llm_settings_rejects_max_tokens_too_high(authed_client):
    client, _ = authed_client
    resp = client.put("/api/settings/llm", json={"url": "x", "model": "y", "timeout": 90, "max_tokens": 8192})
    assert resp.status_code == 422


# ── POST /api/settings/llm/test ───────────────────────────────────────────────


def test_llm_test_returns_422_when_not_configured(authed_client):
    client, conn = authed_client
    conn.fetch = AsyncMock(return_value=[])  # no DB config, no env vars

    resp = client.post("/api/settings/llm/test")
    assert resp.status_code == 422


def test_llm_test_returns_content_on_success(authed_client):
    client, conn = authed_client
    conn.fetch = AsyncMock(return_value=_DB_CONFIG)

    with patch("app.routers.settings.AsyncOpenAI") as MockOpenAI:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_openai_response(_GOOD_LLM_RESPONSE)
        )
        MockOpenAI.return_value = mock_client

        resp = client.post("/api/settings/llm/test")

    assert resp.status_code == 200
    assert resp.json()["content"] == _GOOD_LLM_RESPONSE


def test_llm_test_returns_504_on_timeout(authed_client):
    client, conn = authed_client
    conn.fetch = AsyncMock(return_value=_DB_CONFIG)

    with patch("app.routers.settings.AsyncOpenAI") as MockOpenAI:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=asyncio.TimeoutError()
        )
        MockOpenAI.return_value = mock_client

        resp = client.post("/api/settings/llm/test")

    assert resp.status_code == 504
    assert "timed out" in resp.json()["detail"].lower()


def test_llm_test_returns_502_on_api_error(authed_client):
    client, conn = authed_client
    conn.fetch = AsyncMock(return_value=_DB_CONFIG)

    with patch("app.routers.settings.AsyncOpenAI") as MockOpenAI:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("Connection refused")
        )
        MockOpenAI.return_value = mock_client

        resp = client.post("/api/settings/llm/test")

    assert resp.status_code == 502
    assert "Connection refused" in resp.json()["detail"]
