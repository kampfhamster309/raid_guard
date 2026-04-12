"""
AI enricher batch correlator — incident detection worker (RAID-015).

Architecture
------------
Wakes every ``ai_batch_interval_seconds`` (default 300 s, stored in the
``config`` table).  On each run it pulls the last ``correlation_window_minutes``
of alerts from the DB, asks the LLM to group them into named incidents, then
persists any incidents found and publishes each one on the ``incidents:new``
Redis channel.

Design decisions
----------------
- Incidents accumulate — the same alerts may appear in multiple runs.  The UI
  shows the most-recent incidents to give a historical threat picture.
- The LLM returns ``alert_indices`` (0-based integers that index into the
  supplied alert list).  Python maps these back to UUIDs — the LLM never
  handles UUIDs directly.
- Minimum ``correlation_min_alerts`` alerts required before a correlation run.
- LLM not configured → silently skipped each interval.
- Any single run error is logged and swallowed; the next tick retries.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime

from openai import AsyncOpenAI

from .channels import INCIDENTS_NEW
from .llm_config import get_llm_config

logger = logging.getLogger(__name__)

_CORRELATION_MAX_TOKENS = 2048
_VALID_RISK_LEVELS = frozenset({"low", "medium", "high", "critical"})

# ── System prompt ─────────────────────────────────────────────────────────────

_CORRELATION_SYSTEM_PROMPT = """\
You are an expert security analyst correlating Suricata IDS alerts from a home
network to identify coherent attack patterns or incidents.

Your task: given a list of recent alerts, group related ones into named security
incidents.  Only group alerts that share a plausible causal or tactical
relationship (e.g. reconnaissance followed by exploitation, repeated C2
beaconing, lateral movement across hosts).

Rules:
- Only create an incident if at least 2 alerts are related.
- Do not create an incident for unrelated, isolated alerts.
- risk_level must be exactly one of: low, medium, high, critical.
- Be concise: name ≤ 10 words, narrative ≤ 3 sentences.
- Return an empty incidents array if no coherent incidents are found.\
"""

_CORRELATION_RESPONSE_FORMAT: dict = {
    "type": "json_schema",
    "json_schema": {
        "name": "correlation_result",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "incidents": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "risk_level": {"type": "string"},
                            "narrative": {"type": "string"},
                            "alert_indices": {
                                "type": "array",
                                "items": {"type": "integer"},
                            },
                        },
                        "required": ["name", "risk_level", "narrative", "alert_indices"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["incidents"],
            "additionalProperties": False,
        },
    },
}

# ── Helpers ───────────────────────────────────────────────────────────────────


def _build_correlation_prompt(alerts: list[dict]) -> str:
    lines = ["Recent alerts (correlation window):\n"]
    for i, a in enumerate(alerts):
        ts = a.get("timestamp_str") or str(a.get("timestamp", "?"))
        sev = (a.get("severity") or "info").upper()
        sig = a.get("signature") or "unknown"
        src = a.get("src_ip") or "?"
        dst = a.get("dst_ip") or "?"
        lines.append(f"[{i}] {ts} | {sev} | {sig} | {src} → {dst}")
    lines.append(
        "\nGroup related alerts into incidents.  "
        "Reference each alert by its [index] shown above."
    )
    return "\n".join(lines)


async def _get_correlation_config(pool) -> tuple[int, int]:
    """Return (window_minutes, min_alerts) from the config table, with defaults."""
    window, min_a = 30, 2
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT key, value FROM config "
                "WHERE key IN ('correlation_window_minutes', 'correlation_min_alerts')"
            )
        for row in rows:
            if row["key"] == "correlation_window_minutes":
                window = int(row["value"])
            elif row["key"] == "correlation_min_alerts":
                min_a = int(row["value"])
    except Exception:
        pass
    return window, min_a


async def _fetch_recent_alerts(pool, window_minutes: int) -> list[dict]:
    """Return up to 100 alerts from the last window_minutes, oldest first."""
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, timestamp, signature, category, severity, src_ip, dst_ip
                FROM alerts
                WHERE timestamp >= NOW() - ($1 * INTERVAL '1 minute')
                ORDER BY timestamp ASC
                LIMIT 100
                """,
                window_minutes,
            )
        return [
            {
                "id": str(row["id"]),
                "timestamp": row["timestamp"],
                "timestamp_str": (
                    row["timestamp"].isoformat()
                    if isinstance(row["timestamp"], datetime)
                    else str(row["timestamp"])
                ),
                "signature": row["signature"],
                "category": row["category"],
                "severity": row["severity"],
                "src_ip": str(row["src_ip"]) if row["src_ip"] is not None else None,
                "dst_ip": str(row["dst_ip"]) if row["dst_ip"] is not None else None,
            }
            for row in rows
        ]
    except Exception as exc:
        logger.warning("Correlator: failed to fetch alerts: %s", exc)
        return []


# ── LLM call ──────────────────────────────────────────────────────────────────


async def _call_correlator_llm(
    client: AsyncOpenAI,
    alerts: list[dict],
    model: str,
    timeout: float,
) -> list[dict]:
    """Call the LLM to correlate alerts.  Returns a list of incident dicts, or [] on failure."""
    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _CORRELATION_SYSTEM_PROMPT},
                    {"role": "user", "content": _build_correlation_prompt(alerts)},
                ],
                response_format=_CORRELATION_RESPONSE_FORMAT,
                temperature=0.2,
                max_tokens=_CORRELATION_MAX_TOKENS,
            ),
            timeout=timeout,
        )
        content = response.choices[0].message.content or ""
        data = json.loads(content)
        incidents = data.get("incidents", [])
        return incidents if isinstance(incidents, list) else []
    except asyncio.TimeoutError:
        logger.warning("Correlator: LLM call timed out (%.0fs)", timeout)
        return []
    except json.JSONDecodeError as exc:
        logger.warning("Correlator: LLM returned non-JSON: %s", exc)
        return []
    except Exception as exc:
        logger.warning("Correlator: LLM call failed: %s", exc)
        return []


# ── Core run ──────────────────────────────────────────────────────────────────


async def _run_correlation(redis_client, pool) -> None:
    """Run one correlation pass.  Never raises."""
    cfg = await get_llm_config(pool)
    if not cfg["url"] or not cfg["model"]:
        logger.debug("Correlator: LLM not configured, skipping")
        return

    window_minutes, min_alerts = await _get_correlation_config(pool)
    alerts = await _fetch_recent_alerts(pool, window_minutes)

    if len(alerts) < min_alerts:
        logger.debug(
            "Correlator: %d alert(s) in window (min %d), skipping",
            len(alerts),
            min_alerts,
        )
        return

    logger.info(
        "Correlator: correlating %d alert(s) (window=%dm)", len(alerts), window_minutes
    )

    client = AsyncOpenAI(base_url=cfg["url"], api_key="lm-studio")
    raw_incidents = await _call_correlator_llm(
        client, alerts, cfg["model"], float(cfg["timeout"])
    )

    if not raw_incidents:
        logger.info("Correlator: LLM found no incidents")
        return

    timestamps = [a["timestamp"] for a in alerts if isinstance(a["timestamp"], datetime)]
    period_start = min(timestamps) if timestamps else None
    period_end = max(timestamps) if timestamps else None

    saved = 0
    for inc in raw_incidents:
        name = inc.get("name") or ""
        risk_level = inc.get("risk_level") or ""
        narrative = inc.get("narrative") or ""
        alert_indices = inc.get("alert_indices") or []

        if risk_level not in _VALID_RISK_LEVELS:
            logger.warning(
                "Correlator: invalid risk_level %r, skipping incident", risk_level
            )
            continue

        alert_uuids = [
            uuid.UUID(alerts[i]["id"])
            for i in alert_indices
            if isinstance(i, int) and 0 <= i < len(alerts)
        ]
        if not alert_uuids:
            continue

        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO incidents
                        (period_start, period_end, alert_ids, narrative, risk_level, name)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING id, created_at, period_start, period_end,
                              alert_ids, narrative, risk_level, name
                    """,
                    period_start,
                    period_end,
                    alert_uuids,
                    narrative or None,
                    risk_level,
                    name or None,
                )
            incident_payload = {
                "id": str(row["id"]),
                "created_at": row["created_at"].isoformat(),
                "period_start": (
                    row["period_start"].isoformat()
                    if isinstance(row["period_start"], datetime)
                    else str(row["period_start"])
                ),
                "period_end": (
                    row["period_end"].isoformat()
                    if isinstance(row["period_end"], datetime)
                    else str(row["period_end"])
                ),
                "alert_ids": [str(aid) for aid in (row["alert_ids"] or [])],
                "narrative": row["narrative"],
                "risk_level": row["risk_level"],
                "name": row["name"],
            }
            await redis_client.publish(INCIDENTS_NEW, json.dumps(incident_payload))
            saved += 1
        except Exception as exc:
            logger.error("Correlator: failed to save incident: %s", exc)

    logger.info("Correlator: saved %d incident(s)", saved)


# ── Main loop ─────────────────────────────────────────────────────────────────


async def run_correlator(redis_client, pool) -> None:
    """
    Long-running coroutine — call via ``asyncio.create_task()``.

    Sleeps for ``ai_batch_interval_seconds`` between each run.  The interval
    is re-read from the config table on every iteration so changes take effect
    without a restart.
    """
    logger.info("Batch correlator started")
    try:
        while True:
            interval = 300
            try:
                async with pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT value FROM config WHERE key = 'ai_batch_interval_seconds'"
                    )
                    if row:
                        interval = int(row["value"])
            except Exception:
                pass

            await asyncio.sleep(interval)

            try:
                await _run_correlation(redis_client, pool)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Correlator run error: %s", exc)
    except asyncio.CancelledError:
        logger.info("Batch correlator stopped")
        raise
