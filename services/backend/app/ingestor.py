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
import time
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
        row = await conn.fetchrow(
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
            RETURNING id
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

    payload = json.dumps(
        {k: v for k, v in alert.items() if k != "raw_json"}
        | {"raw_json": alert["raw_json"], "id": str(row["id"])},
        default=str,
    )
    await redis_client.publish(ALERTS_RAW, payload)

    logger.debug(
        "Ingested alert sig_id=%s severity=%s",
        alert.get("signature_id"),
        alert.get("severity"),
    )


# ── File tailing ──────────────────────────────────────────────────────────────

# config-table key holding "<inode>:<byte offset>" of the last line handled.
POSITION_KEY = "ingestor_eve_position"
_POSITION_SAVE_INTERVAL_S = 5.0


async def tail_eve_json(
    path: Path, start: tuple[int, int] | None = None
) -> AsyncGenerator[tuple[str, int, int], None]:
    """Async generator yielding ``(line, inode, offset_after_line)`` for each
    complete non-empty line appended to *path*.

    Behaviour:
    - *start* is a saved ``(inode, offset)``: resume there if it is still the
      same file, so alerts written while the backend was down are not lost.
      Without it, seek to the end (historical content is skipped).
    - A line without its trailing newline is Suricata mid-write: wait and
      re-read it whole instead of yielding half a JSON record.
    - Detects rotation (new inode) and truncation (size < position) and
      re-reads the new content from the start.
    - Waits and retries if the file does not exist yet.
    """
    inode, pos = start if start else (None, None)

    while True:
        if not path.exists():
            logger.debug("Waiting for %s to appear…", path)
            await asyncio.sleep(2)
            continue

        try:
            with open(path, "rb") as fh:
                st = os.fstat(fh.fileno())
                if pos is None:
                    pos = st.st_size  # first start — skip historical content
                elif st.st_ino != inode or st.st_size < pos:
                    logger.info("Log rotation/truncation detected on %s; reading from start", path)
                    pos = 0
                inode = st.st_ino
                fh.seek(pos)

                while True:
                    line = fh.readline()
                    if line.endswith(b"\n"):
                        pos = fh.tell()
                        stripped = line.rstrip(b"\r\n").decode("utf-8", errors="replace")
                        if stripped:
                            yield stripped, inode, pos
                        continue
                    # EOF, possibly in the middle of a line: rewind and wait for the rest.
                    fh.seek(pos)
                    await asyncio.sleep(0.1)
                    try:
                        cur = path.stat()
                    except OSError:
                        break
                    if cur.st_ino != inode or cur.st_size < pos:
                        break  # outer loop re-opens the file

        except OSError as exc:
            logger.warning("Error reading %s: %s — retrying in 2 s", path, exc)
            await asyncio.sleep(2)


async def _load_position(pool: asyncpg.Pool) -> tuple[int, int] | None:
    try:
        async with pool.acquire() as conn:
            value = await conn.fetchval("SELECT value FROM config WHERE key = $1", POSITION_KEY)
        inode, offset = (int(v) for v in value.split(":"))
        return inode, offset
    except Exception:
        return None  # no saved position (first start) or DB unreachable


async def _save_position(pool: asyncpg.Pool, inode: int, offset: int) -> None:
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO config(key, value) VALUES($1, $2) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                POSITION_KEY,
                f"{inode}:{offset}",
            )
    except Exception as exc:
        logger.debug("Could not save eve.json position: %s", exc)


# ── Main loop ─────────────────────────────────────────────────────────────────


async def ingestor_loop(
    pool: asyncpg.Pool,
    redis_client: aioredis.Redis,
    path: Path | None = None,
) -> None:
    """Tail the Suricata EVE JSON file and ingest every alert event.

    Designed to run as a long-lived asyncio background task.  Errors on
    individual alerts are logged and skipped so the loop never stops.
    The file position is saved after every alert (and every few seconds
    otherwise) so a restart resumes where it stopped.
    """
    eve_path = path or EVE_JSON_PATH
    start = await _load_position(pool)
    logger.info("Ingestor started, tailing %s (resume from %s)", eve_path, start or "end of file")
    last_save = time.monotonic()

    async for line, inode, offset in tail_eve_json(eve_path, start):
        alert = None
        try:
            alert = parse_alert(json.loads(line))
        except json.JSONDecodeError:
            logger.debug("Skipping non-JSON line: %.80r", line)

        if alert is not None:
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

        if alert is not None or time.monotonic() - last_save > _POSITION_SAVE_INTERVAL_S:
            await _save_position(pool, inode, offset)
            last_save = time.monotonic()
