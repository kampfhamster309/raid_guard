import logging
import os
import stat
from pathlib import Path

import requests

from app.state import AgentState, CaptureState

logger = logging.getLogger(__name__)

FIFO_PATH = Path(os.environ.get("FIFO_PATH", "/pcap/fritz.pcap"))
CHUNK_SIZE = 4096


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

    Blocks until the stream ends or an I/O error occurs.  The caller is responsible
    for reconnection logic.

    State transitions inside this function:
        WAITING_FOR_READER  →  (FIFO reader connects)  →  STREAMING
    """
    url = (
        f"http://{fritz_host}/cgi-bin/capture_notimeout"
        f"?ifaceorminor={iface_id}&snaplen=&capture=Start&sid={sid}"
    )

    # open() on a FIFO blocks here until Suricata (or any reader) opens the read end.
    logger.info("Opening FIFO for writing — waiting for reader: %s", fifo_path)
    with open(fifo_path, "wb") as fifo:
        state.set(CaptureState.STREAMING, f"Streaming ifaceorminor={iface_id}")
        logger.info("FIFO reader connected, opening Fritzbox capture stream")

        with requests.get(url, stream=True, timeout=(10, None)) as resp:
            resp.raise_for_status()
            logger.info("Fritzbox capture stream open, writing to FIFO")
            for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                if chunk:
                    fifo.write(chunk)
                    fifo.flush()

    logger.info("Fritzbox capture stream ended")
