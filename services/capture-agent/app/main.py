"""
capture-agent — placeholder service.
Fritzbox PCAP streaming logic is implemented in RAID-002.
This placeholder exposes a /health endpoint so the scaffold starts cleanly.
"""
import logging
import uvicorn
from fastapi import FastAPI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="raid_guard capture-agent")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "capture-agent"}


if __name__ == "__main__":
    logger.info("capture-agent starting (placeholder — Fritzbox streaming not yet active)")
    uvicorn.run(app, host="0.0.0.0", port=8080)
