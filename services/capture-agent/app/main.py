import asyncio
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.capture import ensure_fifo, stream_to_fifo
from app.fritz_auth import get_sid
from app.state import AgentState, CaptureState, agent_state

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

FRITZ_HOST = os.environ.get("FRITZ_HOST", "192.168.178.1")
FRITZ_USER = os.environ.get("FRITZ_USER", "")
FRITZ_PASSWORD = os.environ.get("FRITZ_PASSWORD", "")
FRITZ_IFACE_ID = os.environ.get("FRITZ_IFACE_ID", "3-19")

BASE_RECONNECT_DELAY = 2   # seconds
MAX_RECONNECT_DELAY = 30   # seconds


async def capture_loop(state: AgentState = agent_state) -> None:
    """
    Main capture loop.  Authenticates with the Fritzbox, opens the FIFO, streams
    PCAP data, and reconnects automatically with exponential backoff on any failure.
    """
    ensure_fifo()
    attempt = 0

    while True:
        try:
            state.set(CaptureState.CONNECTING, "Authenticating with Fritzbox")
            sid = await asyncio.to_thread(
                get_sid, FRITZ_HOST, FRITZ_USER, FRITZ_PASSWORD
            )

            await asyncio.to_thread(
                stream_to_fifo, FRITZ_HOST, FRITZ_IFACE_ID, sid, state
            )

            # Stream ended cleanly (unexpected but non-fatal — reconnect immediately)
            state.reset_reconnects()
            attempt = 0

        except asyncio.CancelledError:
            logger.info("capture_loop cancelled")
            raise

        except Exception as exc:
            delay = min(BASE_RECONNECT_DELAY * (2 ** attempt), MAX_RECONNECT_DELAY)
            state.set(
                CaptureState.RECONNECTING,
                f"{type(exc).__name__}: {exc} — retrying in {delay}s",
            )
            state.increment_reconnects()
            attempt += 1
            logger.warning("Capture error: %s. Reconnecting in %ds.", exc, delay)
            await asyncio.sleep(delay)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(capture_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="raid_guard capture-agent", lifespan=lifespan)


@app.get("/health")
async def health():
    state_dict = agent_state.to_dict()
    is_streaming = state_dict["capture_state"] == CaptureState.STREAMING.value
    return JSONResponse(
        {"status": "ok" if is_streaming else "degraded", "service": "capture-agent", **state_dict},
        status_code=200 if is_streaming else 503,
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
