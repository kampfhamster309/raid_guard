import hashlib
from unittest.mock import MagicMock, patch

import pytest

from app.fritz_auth import (
    UNAUTHENTICATED_SID,
    _parse_session_info,
    compute_response,
    get_sid,
)

# ── _parse_session_info ────────────────────────────────────────────────────────

CHALLENGE_XML = """<?xml version="1.0" encoding="utf-8"?>
<SessionInfo>
  <SID>0000000000000000</SID>
  <Challenge>1a2b3c4d</Challenge>
  <BlockTime>0</BlockTime>
</SessionInfo>"""

AUTHENTICATED_XML = """<?xml version="1.0" encoding="utf-8"?>
<SessionInfo>
  <SID>abcdef1234567890</SID>
  <Challenge>1a2b3c4d</Challenge>
  <BlockTime>0</BlockTime>
</SessionInfo>"""


def test_parse_session_info_unauthenticated():
    sid, challenge = _parse_session_info(CHALLENGE_XML)
    assert sid == UNAUTHENTICATED_SID
    assert challenge == "1a2b3c4d"


def test_parse_session_info_authenticated():
    sid, challenge = _parse_session_info(AUTHENTICATED_XML)
    assert sid == "abcdef1234567890"
    assert challenge == "1a2b3c4d"


# ── compute_response ───────────────────────────────────────────────────────────

def test_compute_response_format():
    result = compute_response("1a2b3c4d", "password")
    parts = result.split("-")
    assert parts[0] == "1a2b3c4d"
    assert len(parts[1]) == 32  # MD5 hex digest is always 32 characters


def test_compute_response_uses_utf16le_encoding():
    """Verify the hash is computed over the UTF-16LE encoding, not UTF-8."""
    challenge = "1a2b3c4d"
    password = "testpass"
    result = compute_response(challenge, password)

    expected_hash = hashlib.md5(
        f"{challenge}-{password}".encode("utf-16-le")
    ).hexdigest()
    assert result == f"{challenge}-{expected_hash}"


def test_compute_response_is_deterministic():
    r1 = compute_response("1a2b3c4d", "password")
    r2 = compute_response("1a2b3c4d", "password")
    assert r1 == r2


def test_compute_response_differs_per_password():
    r1 = compute_response("1a2b3c4d", "password1")
    r2 = compute_response("1a2b3c4d", "password2")
    assert r1 != r2


def test_compute_response_differs_per_challenge():
    r1 = compute_response("aaaaaaaa", "password")
    r2 = compute_response("bbbbbbbb", "password")
    assert r1 != r2


# ── get_sid ────────────────────────────────────────────────────────────────────

def _make_response(text: str, status_code: int = 200) -> MagicMock:
    mock = MagicMock()
    mock.text = text
    mock.status_code = status_code
    mock.raise_for_status = MagicMock()
    return mock


@patch("app.fritz_auth.requests.get")
@patch("app.fritz_auth.requests.post")
def test_get_sid_full_auth_flow(mock_post, mock_get):
    mock_get.return_value = _make_response(CHALLENGE_XML)
    mock_post.return_value = _make_response(AUTHENTICATED_XML)

    sid = get_sid("192.168.178.1", "admin", "secret")

    assert sid == "abcdef1234567890"
    mock_get.assert_called_once()
    mock_post.assert_called_once()

    # Verify the response string was sent correctly
    call_data = mock_post.call_args.kwargs["data"]
    assert call_data["username"] == "admin"
    assert call_data["response"].startswith("1a2b3c4d-")


@patch("app.fritz_auth.requests.get")
def test_get_sid_reuses_existing_session(mock_get):
    """If the initial GET already returns a valid SID, skip authentication."""
    mock_get.return_value = _make_response(AUTHENTICATED_XML)

    sid = get_sid("192.168.178.1", "admin", "secret")

    assert sid == "abcdef1234567890"
    mock_get.assert_called_once()


@patch("app.fritz_auth.requests.get")
@patch("app.fritz_auth.requests.post")
def test_get_sid_raises_on_bad_credentials(mock_post, mock_get):
    mock_get.return_value = _make_response(CHALLENGE_XML)
    mock_post.return_value = _make_response(CHALLENGE_XML)  # all-zero SID = auth failure

    with pytest.raises(ValueError, match="authentication failed"):
        get_sid("192.168.178.1", "admin", "wrongpassword")
