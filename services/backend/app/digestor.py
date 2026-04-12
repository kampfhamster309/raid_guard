"""
Periodic security digest worker (RAID-015a).

Architecture
------------
Wakes on a configurable schedule (default: every 24 hours).  On each run it
queries the DB for alert statistics and correlated incidents from the preceding
window, asks the LLM to produce a structured security digest, persists the
result in the ``digests`` table, and publishes it on the ``digests:new`` Redis
channel.  Optionally sends a push notification to Home Assistant.

Design decisions
----------------
- On startup, the worker checks when the last digest was created and sleeps
  only for the *remaining* time in the current interval.  This means a
  backend restart does not reset the digest schedule.
- The period is always ``[now - interval_hours, now]`` — a fixed rolling window
  rather than "since the last digest".  Slight overlap is acceptable for a
  home IDS summary.
- LLM not configured → silently skipped each interval.
- Any single run error is logged and swallowed; the next tick retries.
- ``generate_digest`` is a public alias for the core ``_run_digest`` function,
  used by the ``POST /api/digests/generate`` API endpoint.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx
from openai import AsyncOpenAI

from .channels import DIGESTS_NEW
from .llm_config import get_llm_config

logger = logging.getLogger(__name__)

_DIGEST_MAX_TOKENS = 1024
_VALID_RISK_LEVELS = frozenset({"low", "medium", "high", "critical"})

# ── System prompt ─────────────────────────────────────────────────────────────

_DIGEST_SYSTEM_PROMPT = """\
You are a security analyst generating a periodic security digest for a home
network IDS (Suricata with AI enrichment).

Your task: given alert statistics and any correlated incidents from the
reporting period, produce a concise, actionable security digest.

Guidelines:
- overall_risk must be exactly one of: low, medium, high, critical.
- summary: 2-3 sentences — the most important things that happened.
- notable_incidents: up to 5 items — the most significant activity, each as
  a single plain-English sentence.  Empty array if nothing notable.
- emerging_trends: up to 3 items — any patterns or changes vs. typical home
  network behaviour.  Empty array if none observed.
- recommended_actions: up to 5 items — concrete next steps for the operator.
  Empty array if no action is needed.\
"""

_DIGEST_RESPONSE_FORMAT: dict = {
    "type": "json_schema",
    "json_schema": {
        "name": "security_digest",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "overall_risk": {"type": "string"},
                "summary": {"type": "string"},
                "notable_incidents": {"type": "array", "items": {"type": "string"}},
                "emerging_trends": {"type": "array", "items": {"type": "string"}},
                "recommended_actions": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "overall_risk", "summary",
                "notable_incidents", "emerging_trends", "recommended_actions",
            ],
            "additionalProperties": False,
        },
    },
}

# ── Config helpers ────────────────────────────────────────────────────────────


async def _get_digest_config(pool) -> tuple[int, int, bool]:
    """Return (interval_hours, min_alerts, notify_ha) from the config table."""
    interval_hours, min_alerts, notify_ha = 24, 5, False
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT key, value FROM config "
                "WHERE key IN ('digest_interval_hours', 'digest_min_alerts', 'digest_notify_ha')"
            )
        for row in rows:
            if row["key"] == "digest_interval_hours":
                interval_hours = int(row["value"])
            elif row["key"] == "digest_min_alerts":
                min_alerts = int(row["value"])
            elif row["key"] == "digest_notify_ha":
                notify_ha = row["value"].lower() == "true"
    except Exception:
        pass
    return interval_hours, min_alerts, notify_ha


# ── Data fetchers ─────────────────────────────────────────────────────────────


async def _fetch_period_stats(pool, period_start: datetime, period_end: datetime) -> dict:
    """Fetch alert statistics for the period.  Returns empty stats on DB error."""
    try:
        async with pool.acquire() as conn:
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM alerts WHERE timestamp >= $1 AND timestamp < $2",
                period_start, period_end,
            ) or 0
            by_sev_rows = await conn.fetch(
                "SELECT severity::text AS sev, COUNT(*) AS cnt FROM alerts "
                "WHERE timestamp >= $1 AND timestamp < $2 GROUP BY severity",
                period_start, period_end,
            )
            top_sig_rows = await conn.fetch(
                "SELECT signature, COUNT(*) AS cnt FROM alerts "
                "WHERE timestamp >= $1 AND timestamp < $2 AND signature IS NOT NULL "
                "GROUP BY signature ORDER BY cnt DESC LIMIT 20",
                period_start, period_end,
            )
            top_ip_rows = await conn.fetch(
                "SELECT host(src_ip) AS ip, COUNT(*) AS cnt FROM alerts "
                "WHERE timestamp >= $1 AND timestamp < $2 AND src_ip IS NOT NULL "
                "GROUP BY src_ip ORDER BY cnt DESC LIMIT 10",
                period_start, period_end,
            )
        return {
            "total_alerts": total,
            "by_severity": {r["sev"]: r["cnt"] for r in by_sev_rows},
            "top_signatures": [
                {"name": r["signature"], "count": r["cnt"]} for r in top_sig_rows
            ],
            "top_ips": [{"ip": r["ip"], "count": r["cnt"]} for r in top_ip_rows],
        }
    except Exception as exc:
        logger.warning("Digestor: failed to fetch period stats: %s", exc)
        return {"total_alerts": 0, "by_severity": {}, "top_signatures": [], "top_ips": []}


async def _fetch_period_incidents(
    pool, period_start: datetime, period_end: datetime
) -> list[dict]:
    """Return incidents whose created_at falls within the period."""
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT name, risk_level, narrative FROM incidents "
                "WHERE created_at >= $1 AND created_at < $2 "
                "ORDER BY created_at DESC LIMIT 10",
                period_start, period_end,
            )
        return [
            {
                "name": r["name"],
                "risk_level": r["risk_level"],
                "narrative": r["narrative"],
            }
            for r in rows
        ]
    except Exception as exc:
        logger.warning("Digestor: failed to fetch period incidents: %s", exc)
        return []


# ── Prompt builder ────────────────────────────────────────────────────────────


def _build_digest_prompt(
    stats: dict,
    incidents: list[dict],
    period_start: datetime,
    period_end: datetime,
) -> str:
    ps = period_start.isoformat() if hasattr(period_start, "isoformat") else str(period_start)
    pe = period_end.isoformat() if hasattr(period_end, "isoformat") else str(period_end)
    lines = [
        "Security activity report",
        f"Period: {ps} to {pe}",
        "",
        f"Alert totals: {stats['total_alerts']} total",
    ]

    by_sev = stats.get("by_severity", {})
    sev_parts = [
        f"{sev}: {by_sev[sev]}"
        for sev in ("critical", "warning", "info")
        if by_sev.get(sev)
    ]
    if sev_parts:
        lines.append("  " + " | ".join(sev_parts))

    top_sigs = stats.get("top_signatures", [])
    if top_sigs:
        lines += ["", "Top signatures (by frequency):"]
        for s in top_sigs:
            lines.append(f"  {s['name']} ({s['count']})")

    top_ips = stats.get("top_ips", [])
    if top_ips:
        lines += ["", "Top source IPs:"]
        for ip in top_ips:
            lines.append(f"  {ip['ip']} ({ip['count']} alerts)")

    if incidents:
        lines += ["", f"Correlated incidents ({len(incidents)}):"]
        for inc in incidents:
            name = inc.get("name") or "Unnamed"
            risk = inc.get("risk_level", "?")
            narrative = inc.get("narrative") or ""
            lines.append(f"  [{risk}] \"{name}\" — {narrative}")

    return "\n".join(lines)


# ── LLM call ──────────────────────────────────────────────────────────────────


async def _call_digest_llm(
    client: AsyncOpenAI,
    prompt: str,
    model: str,
    timeout: float,
) -> dict | None:
    """Call the LLM for a digest.  Returns the parsed dict, or None on failure."""
    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _DIGEST_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                response_format=_DIGEST_RESPONSE_FORMAT,
                temperature=0.3,
                max_tokens=_DIGEST_MAX_TOKENS,
            ),
            timeout=timeout,
        )
        content = response.choices[0].message.content or ""
        data = json.loads(content)

        for key in ("overall_risk", "summary"):
            if key not in data:
                logger.warning("Digestor: LLM response missing key %r", key)
                return None

        if data["overall_risk"] not in _VALID_RISK_LEVELS:
            logger.warning(
                "Digestor: invalid overall_risk %r, falling back to 'low'",
                data["overall_risk"],
            )
            data["overall_risk"] = "low"

        # Ensure list fields are present
        for key in ("notable_incidents", "emerging_trends", "recommended_actions"):
            if not isinstance(data.get(key), list):
                data[key] = []

        return data
    except asyncio.TimeoutError:
        logger.warning("Digestor: LLM call timed out (%.0fs)", timeout)
        return None
    except json.JSONDecodeError as exc:
        logger.warning("Digestor: LLM returned non-JSON: %s", exc)
        return None
    except Exception as exc:
        logger.warning("Digestor: LLM call failed: %s", exc)
        return None


# ── HA notification ───────────────────────────────────────────────────────────


async def _maybe_notify_ha(
    pool, digest_data: dict, period_start: datetime, period_end: datetime
) -> None:
    """Send a digest push notification to HA if configured and enabled."""
    webhook_url = os.environ.get("HA_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM config WHERE key = 'ha_enabled'"
            )
        if row and row["value"].lower() == "false":
            logger.debug("Digestor: HA notifications disabled, skipping digest notify")
            return
    except Exception:
        pass

    summary = digest_data.get("summary", "")
    risk = digest_data.get("overall_risk", "low")
    dashboard_url = os.environ.get("DASHBOARD_URL", "").strip()
    ps = period_start.isoformat() if hasattr(period_start, "isoformat") else str(period_start)
    pe = period_end.isoformat() if hasattr(period_end, "isoformat") else str(period_end)

    payload = {
        "title": "raid_guard \u2014 Security Digest",
        "message": summary[:280],
        "overall_risk": risk,
        "period_start": ps,
        "period_end": pe,
        "url": f"{dashboard_url}?tab=digests" if dashboard_url else "",
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as http:
            resp = await http.post(webhook_url, json=payload)
            resp.raise_for_status()
        logger.info("Digestor: HA digest notification sent (risk=%s)", risk)
    except Exception as exc:
        logger.warning("Digestor: HA digest notification failed: %s", exc)


# ── Core run ──────────────────────────────────────────────────────────────────


async def _run_digest(pool, redis_client) -> dict | None:
    """
    Run one digest generation pass.  Returns the created digest dict, or
    ``None`` if the run was skipped (LLM unconfigured, not enough data).
    Never raises.
    """
    cfg = await get_llm_config(pool)
    if not cfg["url"] or not cfg["model"]:
        logger.debug("Digestor: LLM not configured, skipping")
        return None

    interval_hours, min_alerts, notify_ha = await _get_digest_config(pool)

    period_end = datetime.now(timezone.utc)
    period_start = period_end - timedelta(hours=interval_hours)

    stats = await _fetch_period_stats(pool, period_start, period_end)
    if stats["total_alerts"] < min_alerts:
        logger.debug(
            "Digestor: %d alerts in period (min %d), skipping",
            stats["total_alerts"],
            min_alerts,
        )
        return None

    incidents = await _fetch_period_incidents(pool, period_start, period_end)

    logger.info(
        "Digestor: generating digest for %d alerts over %dh (%d incidents)",
        stats["total_alerts"],
        interval_hours,
        len(incidents),
    )

    client = AsyncOpenAI(base_url=cfg["url"], api_key="lm-studio")
    prompt = _build_digest_prompt(stats, incidents, period_start, period_end)
    digest_data = await _call_digest_llm(
        client, prompt, cfg["model"], float(cfg["timeout"])
    )

    if not digest_data:
        return None

    content_str = json.dumps(digest_data)
    risk_level = digest_data["overall_risk"]

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO digests (period_start, period_end, content, risk_level)
                VALUES ($1, $2, $3, $4)
                RETURNING id, created_at, period_start, period_end, content, risk_level
                """,
                period_start,
                period_end,
                content_str,
                risk_level,
            )
        digest_dict = {
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
            "content": row["content"],
            "risk_level": row["risk_level"],
        }
    except Exception as exc:
        logger.error("Digestor: failed to store digest: %s", exc)
        return None

    try:
        await redis_client.publish(DIGESTS_NEW, json.dumps(digest_dict))
    except Exception as exc:
        logger.warning("Digestor: failed to publish to Redis: %s", exc)

    logger.info(
        "Digestor: digest created (id=%s, risk=%s)", digest_dict["id"], risk_level
    )

    if notify_ha:
        await _maybe_notify_ha(pool, digest_data, period_start, period_end)

    return digest_dict


# Public alias used by the POST /api/digests/generate endpoint.
generate_digest = _run_digest


# ── Main loop ─────────────────────────────────────────────────────────────────


async def run_digestor(redis_client, pool) -> None:
    """
    Long-running coroutine — call via ``asyncio.create_task()``.

    On startup, checks when the last digest was created and sleeps only for the
    remaining time in the current interval.  This preserves the daily schedule
    across backend restarts.  After each run, sleeps the full configured interval.
    """
    logger.info("Digestor started")
    first_run = True
    try:
        while True:
            interval_hours, _, _ = await _get_digest_config(pool)
            interval_secs = interval_hours * 3600

            if first_run:
                sleep_secs = float(interval_secs)
                try:
                    async with pool.acquire() as conn:
                        last_row = await conn.fetchrow(
                            "SELECT created_at FROM digests ORDER BY created_at DESC LIMIT 1"
                        )
                    if last_row:
                        elapsed = (
                            datetime.now(timezone.utc) - last_row["created_at"]
                        ).total_seconds()
                        sleep_secs = max(0.0, interval_secs - elapsed)
                except Exception:
                    pass
                first_run = False
            else:
                sleep_secs = float(interval_secs)

            if sleep_secs > 0:
                await asyncio.sleep(sleep_secs)

            try:
                await _run_digest(pool, redis_client)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Digestor run error: %s", exc)
    except asyncio.CancelledError:
        logger.info("Digestor stopped")
        raise
