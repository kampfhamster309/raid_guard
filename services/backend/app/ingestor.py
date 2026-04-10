"""
EVE JSON ingestor — tails Suricata's eve.json, normalises alert events,
writes them to TimescaleDB, and publishes them to the alerts:raw Redis channel.

Severity mapping (Suricata EVE alert.severity field, 1 = highest priority):
    1 → critical
    2 → warning
    3 → info
    4 → info
    missing / other → info
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator

import asyncpg
import redis.asyncio as aioredis

from .channels import ALERTS_RAW

logger = logging.getLogger(__name__)

EVE_JSON_PATH = Path(os.environ.get("EVE_JSON_PATH", "/var/log/suricata/eve.json"))

_PRIORITY_TO_SEVERITY: dict[int, str] = {
    1: "critical",
    2: "warning",
    3: "info",
    4: "info",
}


# ── Parsing ───────────────────────────────────────────────────────────────────


def parse_alert(event: dict) -> dict | None:
    """Normalise a Suricata EVE JSON event dict into an alert dict.

    Returns None for any event that is not of type ``alert``
    (e.g. dns, http, flow, stats …).
    """
    if event.get("event_type") != "alert":
        return None

    alert_meta = event.get("alert", {})
    # Suricata's EVE JSON uses the key "severity" for the numeric priority
    # (1–4) inside the nested "alert" object.
    priority: int | None = alert_meta.get("severity")

    return {
        "timestamp": event.get("timestamp"),
        "src_ip": event.get("src_ip"),
        # Suricata uses "dest_ip" / "dest_port" in EVE JSON (not "dst_*")
        "dst_ip": event.get("dest_ip"),
        "src_port": event.get("src_port"),
        "dst_port": event.get("dest_port"),
        "proto": event.get("proto"),
        "signature": alert_meta.get("signature"),
        "signature_id": alert_meta.get("signature_id"),
        "category": alert_meta.get("category"),
        "severity": _PRIORITY_TO_SEVERITY.get(priority, "info"),
        "raw_json": event,
    }


def _parse_timestamp(ts: str | None) -> datetime:
    """Parse a Suricata EVE timestamp string to a timezone-aware datetime.

    Falls back to UTC now if the string is absent or unparseable.
    Python 3.11+ fromisoformat handles any ISO 8601 format including
    the ``+0000`` offset that Suricata produces.
    """
    if not ts:
        return datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        logger.debug("Unparseable timestamp %r — using UTC now", ts)
        return datetime.now(timezone.utc)


# ── Ingestion ─────────────────────────────────────────────────────────────────


async def ingest_alert(
    alert: dict,
    pool: asyncpg.Pool,
    redis_client: aioredis.Redis,
) -> None:
    """Insert a normalised alert into TimescaleDB and publish it to Redis.

    Raises on DB errors so the caller can decide whether to retry or skip.
    """
    ts = _parse_timestamp(alert.get("timestamp"))

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO alerts (
                timestamp, src_ip, dst_ip, src_port, dst_port,
                proto, signature, signature_id, category, severity, raw_json
            ) VALUES (
                $1,
                $2::inet,
                $3::inet,
                $4, $5, $6, $7, $8, $9,
                $10::severity_level,
                $11::jsonb
            )
            """,
            ts,
            alert.get("src_ip"),
            alert.get("dst_ip"),
            alert.get("src_port"),
            alert.get("dst_port"),
            alert.get("proto"),
            alert.get("signature"),
            alert.get("signature_id"),
            alert.get("category"),
            alert.get("severity"),
            json.dumps(alert["raw_json"]),
        )

    await redis_client.publish(
        ALERTS_RAW,
        json.dumps(
            {k: v for k, v in alert.items() if k != "raw_json"}
            | {"raw_json": alert["raw_json"]},
            default=str,
        ),
    )

    logger.debug(
        "Ingested alert sig_id=%s severity=%s",
        alert.get("signature_id"),
        alert.get("severity"),
    )


# ── File tailing ──────────────────────────────────────────────────────────────


async def tail_eve_json(path: Path) -> AsyncGenerator[str, None]:
    """Async generator that yields new non-empty lines appended to *path*.

    Behaviour:
    - Seeks to the end of the file on first open, so historical alerts are
      skipped at startup.
    - Detects log rotation/truncation (file size < current position) and
      re-reads from the beginning of the new file.
    - Waits and retries if the file does not exist yet.
    """
    pos: int | None = None  # None → seek to end on first open

    while True:
        if not path.exists():
            logger.debug("Waiting for %s to appear…", path)
            await asyncio.sleep(2)
            continue

        try:
            with open(path, "r") as fh:
                if pos is None:
                    fh.seek(0, 2)  # SEEK_END — skip historical content
                    pos = fh.tell()
                elif path.stat().st_size < pos:
                    # File was rotated or truncated
                    logger.info("Log rotation detected on %s; re-reading from start", path)
                    fh.seek(0)
                    pos = 0
                else:
                    fh.seek(pos)

                while True:
                    line = fh.readline()
                    if line:
                        pos = fh.tell()
                        stripped = line.rstrip("\n\r")
                        if stripped:
                            yield stripped
                    else:
                        await asyncio.sleep(0.1)
                        # Re-check for rotation while we were sleeping
                        try:
                            if path.stat().st_size < pos:
                                break  # outer loop re-opens the file
                        except OSError:
                            break

        except OSError as exc:
            logger.warning("Error reading %s: %s — retrying in 2 s", path, exc)
            await asyncio.sleep(2)


# ── Main loop ─────────────────────────────────────────────────────────────────


async def ingestor_loop(
    pool: asyncpg.Pool,
    redis_client: aioredis.Redis,
    path: Path | None = None,
) -> None:
    """Tail the Suricata EVE JSON file and ingest every alert event.

    Designed to run as a long-lived asyncio background task.  Errors on
    individual alerts are logged and skipped so the loop never stops.
    """
    eve_path = path or EVE_JSON_PATH
    logger.info("Ingestor started, tailing %s", eve_path)

    async for line in tail_eve_json(eve_path):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            logger.debug("Skipping non-JSON line: %.80r", line)
            continue

        alert = parse_alert(event)
        if alert is None:
            continue

        try:
            await ingest_alert(alert, pool, redis_client)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(
                "Failed to ingest alert (sig_id=%s): %s",
                alert.get("signature_id"),
                exc,
            )
