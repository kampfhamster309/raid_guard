import os
import stat
import struct
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from app.capture import _rewrite_kuznetzov, ensure_fifo, stream_to_fifo
from app.state import AgentState, CaptureState


# ── pcap fixture helpers ───────────────────────────────────────────────────────

_KUZ_MAGIC = bytes.fromhex("34cdb2a1")  # 0xa1b2cd34 LE
_STD_MAGIC  = bytes.fromhex("d4c3b2a1")  # 0xa1b2c3d4 LE


def _global_header(magic: bytes, snaplen: int = 65535, linktype: int = 1) -> bytes:
    return (
        magic
        + struct.pack("<HH", 2, 4)   # version 2.4
        + struct.pack("<i", 0)        # thiszone
        + struct.pack("<I", 0)        # sigfigs
        + struct.pack("<I", snaplen)
        + struct.pack("<I", linktype)
    )


def _kuz_record(payload: bytes) -> bytes:
    """Single Kuznetzov per-packet record (24-byte header + payload)."""
    caplen = len(payload)
    return (
        struct.pack("<IIII", 0, 0, caplen, caplen)   # ts_sec, ts_usec, caplen, len
        + struct.pack("<IHBx", 0, 0, 0)              # ifindex, proto, pkt_type, pad
        + payload
    )


def _std_record(payload: bytes) -> bytes:
    """Single standard per-packet record (16-byte header + payload)."""
    caplen = len(payload)
    return struct.pack("<IIII", 0, 0, caplen, caplen) + payload


def _kuz_pcap(*payloads: bytes) -> bytes:
    return _global_header(_KUZ_MAGIC) + b"".join(_kuz_record(p) for p in payloads)


def _std_pcap(*payloads: bytes) -> bytes:
    return _global_header(_STD_MAGIC) + b"".join(_std_record(p) for p in payloads)


def _collect(chunks) -> bytes:
    return b"".join(chunks)


# ── _rewrite_kuznetzov ─────────────────────────────────────────────────────────

def test_rewrite_replaces_kuznetzov_magic():
    data = _kuz_pcap(b"pkt1")
    result = _collect(_rewrite_kuznetzov(iter([data])))
    assert result[:4] == _STD_MAGIC


def test_rewrite_strips_8_extra_bytes_per_packet():
    payload = b"A" * 20
    data = _kuz_pcap(payload)
    result = _collect(_rewrite_kuznetzov(iter([data])))
    expected = _std_pcap(payload)
    assert result == expected


def test_rewrite_preserves_packet_payload():
    payload = bytes(range(256))
    data = _kuz_pcap(payload)
    result = _collect(_rewrite_kuznetzov(iter([data])))
    # payload must appear verbatim after the 24-byte global + 16-byte pkt header
    assert result[24 + 16:] == payload


def test_rewrite_handles_multiple_packets():
    pkts = [b"first_packet", b"second_packet", b"third_packet"]
    data = _kuz_pcap(*pkts)
    result = _collect(_rewrite_kuznetzov(iter([data])))
    assert result == _std_pcap(*pkts)


def test_rewrite_handles_chunks_split_across_header_boundary():
    """Chunk boundary falls inside a per-packet header — must still produce correct output."""
    pkts = [b"hello", b"world"]
    full = _kuz_pcap(*pkts)
    # Deliver in 1-byte chunks to exercise all boundary conditions
    chunks = [full[i:i+1] for i in range(len(full))]
    result = _collect(_rewrite_kuznetzov(iter(chunks)))
    assert result == _std_pcap(*pkts)


def test_rewrite_handles_chunks_split_inside_payload():
    payload = b"X" * 100
    full = _kuz_pcap(payload)
    # Split right inside the payload
    split = 40
    chunks = [full[:split], full[split:]]
    result = _collect(_rewrite_kuznetzov(iter(chunks)))
    assert result == _std_pcap(payload)


def test_rewrite_passthrough_standard_format():
    """Standard-magic pcap is passed through with only the magic rewritten (same value)."""
    payload = b"standard_pkt"
    # Build a standard pcap (16-byte per-packet headers)
    data = _global_header(_STD_MAGIC) + _std_record(payload)
    result = _collect(_rewrite_kuznetzov(iter([data])))
    # Magic stays standard; payload is preserved
    assert result[:4] == _STD_MAGIC
    assert payload in result


def test_rewrite_skips_empty_chunks():
    payload = b"data"
    data = _kuz_pcap(payload)
    chunks = [b"", data, b""]
    result = _collect(_rewrite_kuznetzov(iter(chunks)))
    assert result == _std_pcap(payload)


def test_rewrite_empty_input():
    result = _collect(_rewrite_kuznetzov(iter([])))
    assert result == b""


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
def test_stream_to_fifo_writes_rewritten_pcap(mock_get, tmp_path):
    """stream_to_fifo rewrites Kuznetzov pcap and writes standard pcap to FIFO."""
    fifo_path = tmp_path / "test.pcap"
    payload = b"ethernet_frame_data"
    pcap_data = _kuz_pcap(payload)
    mock_get.return_value = _make_streaming_response([pcap_data])

    state = AgentState()
    written = bytearray()

    with patch("builtins.open", mock_open()) as mocked_file:
        handle = mocked_file.return_value.__enter__.return_value
        handle.write.side_effect = lambda b: written.extend(b)
        stream_to_fifo("192.168.178.1", "3-19", "abc123sid0000000", state, fifo_path)

    assert bytes(written) == _std_pcap(payload)


@patch("app.capture.requests.get")
def test_stream_to_fifo_sets_streaming_state(mock_get, tmp_path):
    fifo_path = tmp_path / "test.pcap"
    mock_get.return_value = _make_streaming_response([_kuz_pcap(b"pkt")])

    state = AgentState()

    with patch("builtins.open", mock_open()):
        stream_to_fifo("192.168.178.1", "3-19", "abc123sid0000000", state, fifo_path)

    assert state.to_dict()["capture_state"] == CaptureState.STREAMING.value


@patch("app.capture.requests.get")
def test_stream_to_fifo_skips_empty_chunks(mock_get, tmp_path):
    """Empty chunks in the HTTP stream produce no output."""
    fifo_path = tmp_path / "test.pcap"
    payload = b"real_pkt"
    chunks = [b"", _kuz_pcap(payload), b""]
    mock_get.return_value = _make_streaming_response(chunks)

    state = AgentState()
    written = bytearray()

    with patch("builtins.open", mock_open()) as mocked_file:
        handle = mocked_file.return_value.__enter__.return_value
        handle.write.side_effect = lambda b: written.extend(b)
        stream_to_fifo("192.168.178.1", "3-19", "abc123sid0000000", state, fifo_path)

    assert payload in bytes(written)
    assert bytes(written) == _std_pcap(payload)


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
