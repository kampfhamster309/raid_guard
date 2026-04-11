import logging
import os
import stat
import struct
from pathlib import Path
from typing import Iterator

import requests

from app.state import AgentState, CaptureState

logger = logging.getLogger(__name__)

FIFO_PATH = Path(os.environ.get("FIFO_PATH", "/pcap/fritz.pcap"))
CHUNK_SIZE = 4096

# ── pcap format constants ──────────────────────────────────────────────────────
_PCAP_GLOBAL_LEN  = 24   # global header length (same for all pcap variants)
_STD_PKT_HDR_LEN  = 16   # standard per-packet header length
_KUZ_PKT_HDR_LEN  = 24   # Kuznetzov per-packet header (16 standard + 8 extra)
# The AVM Fritzbox emits Kuznetzov-format pcap (magic 0xa1b2cd34).  Each
# per-packet header appends 8 bytes after the standard 16:
#   ifindex (4) | protocol (2) | pkt_type (1) | pad (1)
_KUZNETZOV_MAGIC  = bytes.fromhex("34cdb2a1")  # 0xa1b2cd34 stored little-endian
_STANDARD_MAGIC   = bytes.fromhex("d4c3b2a1")  # 0xa1b2c3d4 stored little-endian


def _rewrite_kuznetzov(data_iter: Iterator[bytes]) -> Iterator[bytes]:
    """
    Convert a Kuznetzov-format pcap byte stream to standard libpcap format.

    Kuznetzov pcap (magic 0xa1b2cd34) is identical to standard pcap except
    each per-packet header carries 8 extra bytes:

        Standard (16 B):  ts_sec | ts_usec | caplen | len
        Kuznetzov (24 B): ts_sec | ts_usec | caplen | len | ifindex(4) | proto(2) | pkt_type(1) | pad(1)

    This generator:
      1. Replaces the magic in the global header with the standard value.
      2. Strips the 8 extra bytes from every per-packet header.

    If the magic is already standard this generator is a transparent pass-through
    for the global header and processes packets as 16-byte headers.
    """
    buf = bytearray()
    global_done = False
    kuznetzov = False
    pkt_hdr_len = _STD_PKT_HDR_LEN

    for chunk in data_iter:
        if not chunk:
            continue
        buf.extend(chunk)

        # ── global header ──────────────────────────────────────────────────────
        if not global_done:
            if len(buf) < _PCAP_GLOBAL_LEN:
                continue
            hdr = bytearray(buf[:_PCAP_GLOBAL_LEN])
            if bytes(hdr[:4]) == _KUZNETZOV_MAGIC:
                kuznetzov = True
                pkt_hdr_len = _KUZ_PKT_HDR_LEN
                hdr[:4] = _STANDARD_MAGIC
                logger.info(
                    "Fritzbox pcap: Kuznetzov format detected (magic 0xa1b2cd34); "
                    "rewriting to standard libpcap (magic 0xa1b2c3d4)"
                )
            else:
                logger.info("Fritzbox pcap: standard format (magic %s)", hdr[:4].hex())
            yield bytes(hdr)
            buf = buf[_PCAP_GLOBAL_LEN:]
            global_done = True

        # ── per-packet records ─────────────────────────────────────────────────
        while len(buf) >= pkt_hdr_len:
            caplen = struct.unpack_from("<I", buf, 8)[0]
            total = pkt_hdr_len + caplen
            if len(buf) < total:
                break
            yield bytes(buf[:_STD_PKT_HDR_LEN])       # emit standard 16-byte header
            yield bytes(buf[pkt_hdr_len:total])        # emit packet data
            buf = buf[total:]


def ensure_fifo(path: Path = FIFO_PATH) -> None:
    """
    Create the PCAP FIFO at *path* if it does not already exist.
    Raises RuntimeError if the path exists but is not a FIFO.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not stat.S_ISFIFO(path.stat().st_mode):
            raise RuntimeError(f"{path} exists but is not a named pipe (FIFO)")
        logger.debug("FIFO already exists at %s", path)
        return
    os.mkfifo(path)
    logger.info("Created FIFO at %s", path)


def stream_to_fifo(
    fritz_host: str,
    iface_id: str,
    sid: str,
    state: AgentState,
    fifo_path: Path = FIFO_PATH,
) -> None:
    """
    Open the FIFO for writing (blocks until a reader — i.e. Suricata — connects),
    then connect to the Fritzbox capture endpoint and stream libpcap data into it.

    The Fritzbox emits Kuznetzov-format pcap (magic 0xa1b2cd34).  The stream is
    transparently rewritten to standard libpcap format before being written to the
    FIFO so that Suricata's libpcap can parse it.

    Blocks until the stream ends or an I/O error occurs.  The caller is responsible
    for reconnection logic.

    State transitions:
        WAITING_FOR_READER  →  (Suricata opens FIFO)  →  STREAMING
    """
    url = (
        f"http://{fritz_host}/cgi-bin/capture_notimeout"
        f"?ifaceorminor={iface_id}&snaplen=&capture=Start&sid={sid}"
    )

    # Connect to Fritzbox first so the pcap stream is already buffered in the
    # kernel TCP receive buffer before we open the FIFO.  When Suricata opens
    # the FIFO read end, the first write is immediate — pcap_next_ex() finds
    # packets right away and does not return -1.
    logger.info("Opening Fritzbox capture stream")
    with requests.get(url, stream=True, timeout=(10, None)) as resp:
        resp.raise_for_status()

        # open() on a FIFO blocks here until Suricata opens the read end.
        logger.info("Fritzbox stream open. Waiting for FIFO reader: %s", fifo_path)
        state.set(CaptureState.WAITING_FOR_READER, "Fritzbox connected, waiting for Suricata")
        with open(fifo_path, "wb") as fifo:
            state.set(CaptureState.STREAMING, f"Streaming ifaceorminor={iface_id}")
            logger.info("FIFO reader connected, writing to FIFO")
            for data in _rewrite_kuznetzov(resp.iter_content(chunk_size=CHUNK_SIZE)):
                fifo.write(data)
                fifo.flush()

    logger.info("Fritzbox capture stream ended")
