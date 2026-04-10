import os
import stat
from pathlib import Path
from unittest.mock import MagicMock, call, mock_open, patch

import pytest

from app.capture import ensure_fifo, stream_to_fifo
from app.state import AgentState, CaptureState


# ── ensure_fifo ────────────────────────────────────────────────────────────────

def test_ensure_fifo_creates_fifo(tmp_path):
    fifo_path = tmp_path / "test.pcap"
    ensure_fifo(fifo_path)
    assert fifo_path.exists()
    assert stat.S_ISFIFO(fifo_path.stat().st_mode)


def test_ensure_fifo_is_idempotent(tmp_path):
    fifo_path = tmp_path / "test.pcap"
    ensure_fifo(fifo_path)
    ensure_fifo(fifo_path)  # second call must not raise
    assert fifo_path.exists()


def test_ensure_fifo_creates_parent_dirs(tmp_path):
    fifo_path = tmp_path / "a" / "b" / "test.pcap"
    ensure_fifo(fifo_path)
    assert fifo_path.exists()


def test_ensure_fifo_raises_if_path_is_regular_file(tmp_path):
    regular_file = tmp_path / "test.pcap"
    regular_file.write_bytes(b"")
    with pytest.raises(RuntimeError, match="not a named pipe"):
        ensure_fifo(regular_file)


# ── stream_to_fifo ─────────────────────────────────────────────────────────────

def _make_streaming_response(chunks: list[bytes]) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.iter_content.return_value = iter(chunks)
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


@patch("app.capture.requests.get")
def test_stream_to_fifo_writes_chunks(mock_get, tmp_path):
    fifo_path = tmp_path / "test.pcap"
    os.mkfifo(fifo_path)

    chunks = [b"chunk1", b"chunk2", b"chunk3"]
    mock_get.return_value = _make_streaming_response(chunks)

    state = AgentState()
    written = bytearray()

    original_open = open

    def fake_open(path, mode="r", **kwargs):
        if str(path) == str(fifo_path) and "b" in mode:
            return original_open(fifo_path, mode, **kwargs)
        return original_open(path, mode, **kwargs)

    # Use a regular file so the test doesn't block waiting for a FIFO reader
    fifo_path.unlink()
    fifo_path.write_bytes(b"")  # regular file for test purposes

    with patch("builtins.open", mock_open()) as mocked_file:
        handle = mocked_file.return_value.__enter__.return_value
        stream_to_fifo("192.168.178.1", "3-19", "abc123sid0000000", state, fifo_path)

    handle.write.assert_any_call(b"chunk1")
    handle.write.assert_any_call(b"chunk2")
    handle.write.assert_any_call(b"chunk3")
    assert handle.flush.call_count == 3


@patch("app.capture.requests.get")
def test_stream_to_fifo_sets_streaming_state(mock_get, tmp_path):
    fifo_path = tmp_path / "test.pcap"
    mock_get.return_value = _make_streaming_response([b"data"])

    state = AgentState()

    with patch("builtins.open", mock_open()):
        stream_to_fifo("192.168.178.1", "3-19", "abc123sid0000000", state, fifo_path)

    assert state.to_dict()["capture_state"] == CaptureState.STREAMING.value


@patch("app.capture.requests.get")
def test_stream_to_fifo_skips_empty_chunks(mock_get, tmp_path):
    fifo_path = tmp_path / "test.pcap"
    chunks = [b"", b"real_data", b"", b"more_data"]
    mock_get.return_value = _make_streaming_response(chunks)

    state = AgentState()

    with patch("builtins.open", mock_open()) as mocked_file:
        handle = mocked_file.return_value.__enter__.return_value
        stream_to_fifo("192.168.178.1", "3-19", "abc123sid0000000", state, fifo_path)

    write_calls = [c.args[0] for c in handle.write.call_args_list]
    assert b"" not in write_calls
    assert b"real_data" in write_calls
    assert b"more_data" in write_calls


@patch("app.capture.requests.get")
def test_stream_to_fifo_constructs_correct_url(mock_get, tmp_path):
    fifo_path = tmp_path / "test.pcap"
    mock_get.return_value = _make_streaming_response([])

    state = AgentState()
    with patch("builtins.open", mock_open()):
        stream_to_fifo("192.168.178.1", "3-19", "mysid123", state, fifo_path)

    called_url = mock_get.call_args.args[0]
    assert "192.168.178.1" in called_url
    assert "ifaceorminor=3-19" in called_url
    assert "sid=mysid123" in called_url
    assert "capture=Start" in called_url
