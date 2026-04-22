"""Unit tests for /api/tuning endpoints (mock DB)."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.main import app


_SIG_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_NOW = datetime(2026, 4, 12, 10, 0, 0, tzinfo=timezone.utc)


def _fake_suggestion_row(
    *,
    action="suppress",
    status="pending",
    signature_id=2001219,
    confirmed_at=None,
    threshold_count=None,
    threshold_seconds=None,
    threshold_track=None,
    threshold_type=None,
):
    return {
        "id": _SIG_ID,
        "created_at": _NOW,
        "signature": "ET SCAN Potential SSH Scan",
        "signature_id": signature_id,
        "hit_count": 847,
        "assessment": "Typical scanning noise on home networks.",
        "action": action,
        "status": status,
        "confirmed_at": confirmed_at,
        "threshold_count": threshold_count,
        "threshold_seconds": threshold_seconds,
        "threshold_track": threshold_track,
        "threshold_type": threshold_type,
    }


# ── list_suggestions ──────────────────────────────────────────────────────────


def test_list_suggestions_returns_200(authed_client):
    client, conn = authed_client
    conn.fetch = AsyncMock(return_value=[])

    resp = client.get("/api/tuning")
    assert resp.status_code == 200


def test_list_suggestions_empty(authed_client):
    client, conn = authed_client
    conn.fetch = AsyncMock(return_value=[])

    body = client.get("/api/tuning").json()
    assert body == []


def test_list_suggestions_returns_items(authed_client):
    client, conn = authed_client
    conn.fetch = AsyncMock(return_value=[_fake_suggestion_row()])

    body = client.get("/api/tuning").json()
    assert len(body) == 1
    assert body[0]["signature"] == "ET SCAN Potential SSH Scan"
    assert body[0]["action"] == "suppress"
    assert body[0]["status"] == "pending"


def test_list_suggestions_requires_auth(raw_client):
    resp = raw_client.get("/api/tuning")
    assert resp.status_code == 401


# ── confirm_suggestion ────────────────────────────────────────────────────────


def test_confirm_suggestion_returns_200(authed_client):
    client, conn = authed_client
    row = _fake_suggestion_row()
    confirmed = _fake_suggestion_row(status="confirmed", confirmed_at=_NOW)
    conn.fetchrow = AsyncMock(side_effect=[row, confirmed])

    with patch("app.routers.tuning.apply_suppression", new=AsyncMock()):
        resp = client.post(f"/api/tuning/{_SIG_ID}/confirm")
    assert resp.status_code == 200
    assert resp.json()["status"] == "confirmed"


def test_confirm_suggestion_calls_apply_suppression(authed_client):
    client, conn = authed_client
    row = _fake_suggestion_row(action="suppress", signature_id=2001219)
    confirmed = _fake_suggestion_row(status="confirmed", action="suppress", confirmed_at=_NOW)
    conn.fetchrow = AsyncMock(side_effect=[row, confirmed])

    with patch("app.routers.tuning.apply_suppression", new=AsyncMock()) as mock_apply:
        client.post(f"/api/tuning/{_SIG_ID}/confirm")

    mock_apply.assert_awaited_once_with(2001219)


def test_confirm_suggestion_skips_apply_when_no_sig_id(authed_client):
    client, conn = authed_client
    row = _fake_suggestion_row(action="suppress", signature_id=None)
    confirmed = _fake_suggestion_row(status="confirmed", action="suppress", signature_id=None, confirmed_at=_NOW)
    conn.fetchrow = AsyncMock(side_effect=[row, confirmed])

    with patch("app.routers.tuning.apply_suppression", new=AsyncMock()) as mock_apply:
        client.post(f"/api/tuning/{_SIG_ID}/confirm")

    mock_apply.assert_not_awaited()


def test_confirm_suggestion_skips_apply_for_keep(authed_client):
    client, conn = authed_client
    row = _fake_suggestion_row(action="keep")
    confirmed = _fake_suggestion_row(status="confirmed", action="keep", confirmed_at=_NOW)
    conn.fetchrow = AsyncMock(side_effect=[row, confirmed])

    with patch("app.routers.tuning.apply_suppression", new=AsyncMock()) as mock_suppress:
        with patch("app.routers.tuning.apply_threshold", new=AsyncMock()) as mock_threshold:
            client.post(f"/api/tuning/{_SIG_ID}/confirm")

    mock_suppress.assert_not_awaited()
    mock_threshold.assert_not_awaited()


def test_confirm_threshold_adjust_calls_apply_threshold(authed_client):
    client, conn = authed_client
    row = _fake_suggestion_row(action="threshold-adjust", signature_id=2008581)
    confirmed = _fake_suggestion_row(
        status="confirmed", action="threshold-adjust", signature_id=2008581, confirmed_at=_NOW
    )
    conn.fetchrow = AsyncMock(side_effect=[row, confirmed])

    with patch("app.routers.tuning.apply_threshold", new=AsyncMock()) as mock_threshold:
        resp = client.post(
            f"/api/tuning/{_SIG_ID}/confirm",
            json={"threshold_count": 3, "threshold_seconds": 30,
                  "threshold_track": "by_src", "threshold_type": "limit"},
        )

    assert resp.status_code == 200
    mock_threshold.assert_awaited_once_with(2008581, 3, 30, "by_src", "limit")


def test_confirm_threshold_adjust_uses_defaults_when_no_body(authed_client):
    client, conn = authed_client
    row = _fake_suggestion_row(action="threshold-adjust", signature_id=2008581)
    confirmed = _fake_suggestion_row(
        status="confirmed", action="threshold-adjust", signature_id=2008581, confirmed_at=_NOW
    )
    conn.fetchrow = AsyncMock(side_effect=[row, confirmed])

    with patch("app.routers.tuning.apply_threshold", new=AsyncMock()) as mock_threshold:
        resp = client.post(f"/api/tuning/{_SIG_ID}/confirm")

    assert resp.status_code == 200
    mock_threshold.assert_awaited_once_with(2008581, 5, 60, "by_src", "limit")


def test_confirm_threshold_adjust_skips_apply_when_no_sig_id(authed_client):
    client, conn = authed_client
    row = _fake_suggestion_row(action="threshold-adjust", signature_id=None)
    confirmed = _fake_suggestion_row(
        status="confirmed", action="threshold-adjust", signature_id=None, confirmed_at=_NOW
    )
    conn.fetchrow = AsyncMock(side_effect=[row, confirmed])

    with patch("app.routers.tuning.apply_threshold", new=AsyncMock()) as mock_threshold:
        resp = client.post(f"/api/tuning/{_SIG_ID}/confirm")

    assert resp.status_code == 200
    mock_threshold.assert_not_awaited()


def test_confirm_suggestion_404(authed_client):
    client, conn = authed_client
    conn.fetchrow = AsyncMock(return_value=None)

    resp = client.post(f"/api/tuning/{uuid.uuid4()}/confirm")
    assert resp.status_code == 404


def test_confirm_suggestion_409_already_confirmed(authed_client):
    client, conn = authed_client
    conn.fetchrow = AsyncMock(return_value=_fake_suggestion_row(status="confirmed"))

    resp = client.post(f"/api/tuning/{_SIG_ID}/confirm")
    assert resp.status_code == 409


def test_confirm_suggestion_requires_auth(raw_client):
    resp = raw_client.post(f"/api/tuning/{_SIG_ID}/confirm")
    assert resp.status_code == 401


# ── dismiss_suggestion ────────────────────────────────────────────────────────


def test_dismiss_suggestion_returns_200(authed_client):
    client, conn = authed_client
    row = _fake_suggestion_row()
    dismissed = _fake_suggestion_row(status="dismissed")
    conn.fetchrow = AsyncMock(side_effect=[row, dismissed])

    resp = client.post(f"/api/tuning/{_SIG_ID}/dismiss")
    assert resp.status_code == 200
    assert resp.json()["status"] == "dismissed"


def test_dismiss_suggestion_404(authed_client):
    client, conn = authed_client
    conn.fetchrow = AsyncMock(return_value=None)

    resp = client.post(f"/api/tuning/{uuid.uuid4()}/dismiss")
    assert resp.status_code == 404


def test_dismiss_suggestion_409_already_dismissed(authed_client):
    client, conn = authed_client
    conn.fetchrow = AsyncMock(return_value=_fake_suggestion_row(status="dismissed"))

    resp = client.post(f"/api/tuning/{_SIG_ID}/dismiss")
    assert resp.status_code == 409


# ── run_tuner ─────────────────────────────────────────────────────────────────


def test_run_tuner_422_when_llm_not_configured(authed_client):
    client, conn = authed_client
    with patch(
        "app.routers.tuning.get_llm_config",
        new=AsyncMock(return_value={"url": "", "model": "", "timeout": "90", "max_tokens": "512"}),
    ):
        resp = client.post("/api/tuning/run")
    assert resp.status_code == 422


def test_run_tuner_returns_empty_list_when_skipped(authed_client):
    client, conn = authed_client
    with patch(
        "app.routers.tuning.get_llm_config",
        new=AsyncMock(return_value={"url": "http://x:1234/v1", "model": "gemma", "timeout": "90", "max_tokens": "512"}),
    ):
        with patch(
            "app.routers.tuning.generate_tuning_suggestions",
            new=AsyncMock(return_value=[]),
        ):
            resp = client.post("/api/tuning/run")
    assert resp.status_code == 200
    assert resp.json() == []


def test_run_tuner_returns_suggestions_on_success(authed_client):
    client, conn = authed_client
    _fake = [
        {
            "id": str(_SIG_ID),
            "created_at": _NOW.isoformat(),
            "signature": "ET SCAN Potential SSH Scan",
            "signature_id": 2001219,
            "hit_count": 847,
            "assessment": "Typical noise.",
            "action": "suppress",
            "status": "pending",
            "confirmed_at": None,
        }
    ]
    with patch(
        "app.routers.tuning.get_llm_config",
        new=AsyncMock(return_value={"url": "http://x:1234/v1", "model": "gemma", "timeout": "90", "max_tokens": "512"}),
    ):
        with patch(
            "app.routers.tuning.generate_tuning_suggestions",
            new=AsyncMock(return_value=_fake),
        ):
            resp = client.post("/api/tuning/run")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["action"] == "suppress"
