"""
Periodic noise / false-positive tuning worker (RAID-015b).

Architecture
------------
Wakes on a configurable schedule (default: every 7 days).  On each run it:
  1. Checks that enough alert history has accumulated (default: 7 days).
  2. Queries the top recurring low/info-severity signatures over the lookback
     window, excluding signatures that already have a pending suggestion.
  3. Sends the signature list to the LLM, which returns a structured assessment
     of whether each is likely a false positive on a home network and a
     recommended action (suppress / threshold-adjust / keep).
  4. Persists the suggestions in the ``tuning_suggestions`` table, from where
     the Config UI surfaces them for human review.

Confirming a "suppress" suggestion (via the API) writes a Suricata
suppress directive to suppress.conf and triggers a live rule reload.

Design decisions
----------------
- Runs weekly by default because enough data needs to accumulate for pattern
  recognition; a daily run would likely produce the same results.
- Only "info" and "warning" severity signatures are candidates — critical
  signatures are never suggested as false positives.
- Deduplication: if a signature already has a ``pending`` suggestion, it is
  excluded from the next LLM batch to avoid duplicate cards in the UI.
- Smart startup sleep: checks the newest suggestion ``created_at`` to avoid
  running again immediately after a restart.
- ``generate_tuning_suggestions`` is a public alias used by the API endpoint.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from openai import AsyncOpenAI

from .llm_config import get_llm_config

logger = logging.getLogger(__name__)

_VALID_ACTIONS = frozenset({"suppress", "threshold-adjust", "keep"})
_TUNER_MAX_TOKENS = 2048

# ── System prompt ─────────────────────────────────────────────────────────────

_TUNER_SYSTEM_PROMPT = """\
You are a security analyst advising the operator of a home network IDS
(Suricata with Emerging Threats Open rules).

Your task: for each alert signature listed below, assess whether it is likely
a false positive for a typical residential network and recommend exactly one
of these actions:

  suppress           — This rule almost never fires on legitimate home-network
                       traffic.  A permanent suppression rule is appropriate.
  threshold-adjust   — The rule is valid but fires too often.  The operator
                       should raise the threshold or rate-limit the alert.
  keep               — The rule fires appropriately; do not suppress or adjust.

Guidelines:
- Consider the context: smart home devices, streaming, VoIP, occasional remote
  work, typical desktop/mobile browsing.
- Only recommend "suppress" if you are confident the signature has no value
  for this threat model.
- assessment must be 1-2 sentences — concise and actionable.
- Your response must contain exactly one entry per input signature, in the
  same order, with the exact signature string unchanged.\
"""

_TUNER_RESPONSE_FORMAT: dict = {
    "type": "json_schema",
    "json_schema": {
        "name": "tuning_suggestions",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "suggestions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "signature":  {"type": "string"},
                            "assessment": {"type": "string"},
                            "action":     {"type": "string"},
                        },
                        "required": ["signature", "assessment", "action"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["suggestions"],
            "additionalProperties": False,
        },
    },
}

# ── Config helper ─────────────────────────────────────────────────────────────


async def _get_tuner_config(pool) -> dict:
    """Return tuner configuration from the config table with defaults."""
    defaults = {
        "lookback_days": 7,
        "min_days": 7,
        "interval_days": 7,
        "min_alerts": 10,
        "top_n": 10,
    }
    key_map = {
        "tuner_lookback_days": "lookback_days",
        "tuner_min_days":      "min_days",
        "tuner_interval_days": "interval_days",
        "tuner_min_alerts":    "min_alerts",
        "tuner_top_n":         "top_n",
    }
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT key, value FROM config WHERE key = ANY($1::text[])",
                list(key_map.keys()),
            )
        for row in rows:
            field = key_map.get(row["key"])
            if field:
                defaults[field] = int(row["value"])
    except Exception:
        pass
    return defaults


# ── Data fetchers ─────────────────────────────────────────────────────────────


async def _has_enough_history(pool, min_days: int) -> bool:
    """Return True if the oldest alert is at least min_days old."""
    try:
        async with pool.acquire() as conn:
            oldest = await conn.fetchval("SELECT MIN(timestamp) FROM alerts")
        if oldest is None:
            return False
        age_days = (datetime.now(timezone.utc) - oldest).total_seconds() / 86400
        return age_days >= min_days
    except Exception:
        return False


async def _fetch_existing_pending(pool) -> frozenset[str]:
    """Return signatures that already have a pending tuning suggestion."""
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT signature FROM tuning_suggestions WHERE status = 'pending'"
            )
        return frozenset(r["signature"] for r in rows)
    except Exception:
        return frozenset()


async def _fetch_noisy_signatures(
    pool,
    period_start: datetime,
    period_end: datetime,
    min_alerts: int,
    top_n: int,
) -> list[dict]:
    """Return the top noisy info/warning signatures for the period."""
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    signature,
                    mode() WITHIN GROUP (ORDER BY signature_id) AS signature_id,
                    COUNT(*)                                     AS hit_count,
                    COUNT(DISTINCT src_ip)                       AS distinct_src_ips
                FROM alerts
                WHERE
                    timestamp >= $1 AND timestamp < $2
                    AND signature IS NOT NULL
                    AND severity::text IN ('info', 'warning')
                GROUP BY signature
                HAVING COUNT(*) >= $3
                ORDER BY hit_count DESC
                LIMIT $4
                """,
                period_start,
                period_end,
                min_alerts,
                top_n,
            )
        return [
            {
                "signature":       r["signature"],
                "signature_id":    r["signature_id"],
                "hit_count":       r["hit_count"],
                "distinct_src_ips": r["distinct_src_ips"],
            }
            for r in rows
        ]
    except Exception as exc:
        logger.warning("Noisetuner: failed to fetch noisy signatures: %s", exc)
        return []


# ── Prompt builder ────────────────────────────────────────────────────────────


def _build_tuner_prompt(sigs: list[dict], lookback_days: int) -> str:
    lines = [
        f"Alert signatures from the past {lookback_days} days (info/warning severity only):",
        "",
    ]
    for s in sigs:
        src_note = (
            f" — {s['distinct_src_ips']} distinct source IP(s)"
            if s.get("distinct_src_ips", 0) > 0
            else ""
        )
        lines.append(f"  {s['hit_count']:>6} hits  |  {s['signature']}{src_note}")
    lines += [
        "",
        "For each signature, provide: assessment (1-2 sentences) and action "
        "(suppress / threshold-adjust / keep).",
    ]
    return "\n".join(lines)


# ── LLM call ──────────────────────────────────────────────────────────────────


async def _call_tuner_llm(
    client: AsyncOpenAI,
    prompt: str,
    model: str,
    timeout: float,
    expected_sigs: list[dict],
) -> list[dict] | None:
    """Call the LLM for tuning suggestions.  Returns a validated list or None."""
    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _TUNER_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                response_format=_TUNER_RESPONSE_FORMAT,
                temperature=0.2,
                max_tokens=_TUNER_MAX_TOKENS,
            ),
            timeout=timeout,
        )
        content = response.choices[0].message.content or ""
        data = json.loads(content)
        suggestions = data.get("suggestions", [])
        if not isinstance(suggestions, list):
            logger.warning("Noisetuner: LLM suggestions is not a list")
            return None

        # Validate and normalise each item
        sig_lookup = {s["signature"]: s for s in expected_sigs}
        validated: list[dict] = []
        for item in suggestions:
            sig = item.get("signature", "")
            action = item.get("action", "keep")
            assessment = item.get("assessment", "")
            if not sig or not assessment:
                continue
            if action not in _VALID_ACTIONS:
                logger.warning(
                    "Noisetuner: unknown action %r for %r, falling back to 'keep'",
                    action, sig,
                )
                action = "keep"
            original = sig_lookup.get(sig)
            validated.append({
                "signature":    sig,
                "signature_id": original["signature_id"] if original else None,
                "hit_count":    original["hit_count"] if original else 0,
                "assessment":   assessment,
                "action":       action,
            })
        return validated if validated else None

    except asyncio.TimeoutError:
        logger.warning("Noisetuner: LLM call timed out (%.0fs)", timeout)
        return None
    except json.JSONDecodeError as exc:
        logger.warning("Noisetuner: LLM returned non-JSON: %s", exc)
        return None
    except Exception as exc:
        logger.warning("Noisetuner: LLM call failed: %s", exc)
        return None


# ── Core run ──────────────────────────────────────────────────────────────────


async def _run_tuner(pool) -> list[dict] | None:
    """
    Run one tuning analysis pass.

    Returns the list of newly created suggestion dicts, an empty list if the
    run was skipped, or ``None`` on error.  Never raises.
    """
    cfg_llm = await get_llm_config(pool)
    if not cfg_llm["url"] or not cfg_llm["model"]:
        logger.debug("Noisetuner: LLM not configured, skipping")
        return []

    cfg = await _get_tuner_config(pool)

    # Verify enough historical data exists
    if not await _has_enough_history(pool, cfg["min_days"]):
        logger.info(
            "Noisetuner: fewer than %d days of alert history, skipping",
            cfg["min_days"],
        )
        return []

    period_end = datetime.now(timezone.utc)
    period_start = period_end - timedelta(days=cfg["lookback_days"])

    # Exclude signatures with existing pending suggestions
    pending = await _fetch_existing_pending(pool)

    sigs = await _fetch_noisy_signatures(
        pool, period_start, period_end, cfg["min_alerts"], cfg["top_n"]
    )
    sigs = [s for s in sigs if s["signature"] not in pending]

    if not sigs:
        logger.info("Noisetuner: no new noisy signatures to analyse")
        return []

    logger.info(
        "Noisetuner: analysing %d signatures (%d excluded as already pending)",
        len(sigs),
        len(pending),
    )

    client = AsyncOpenAI(base_url=cfg_llm["url"], api_key="lm-studio")
    prompt = _build_tuner_prompt(sigs, cfg["lookback_days"])
    suggestions = await _call_tuner_llm(
        client, prompt, cfg_llm["model"], float(cfg_llm["timeout"]), sigs
    )

    if not suggestions:
        return []

    created: list[dict] = []
    try:
        async with pool.acquire() as conn:
            for s in suggestions:
                row = await conn.fetchrow(
                    """
                    INSERT INTO tuning_suggestions
                        (signature, signature_id, hit_count, assessment, action)
                    VALUES ($1, $2, $3, $4, $5)
                    RETURNING id, created_at, signature, signature_id,
                              hit_count, assessment, action, status, confirmed_at
                    """,
                    s["signature"],
                    s["signature_id"],
                    s["hit_count"],
                    s["assessment"],
                    s["action"],
                )
                created.append(_row_to_dict(row))
    except Exception as exc:
        logger.error("Noisetuner: failed to store suggestions: %s", exc)
        return None

    logger.info("Noisetuner: created %d tuning suggestions", len(created))
    return created


def _row_to_dict(row) -> dict:
    return {
        "id":           str(row["id"]),
        "created_at":   row["created_at"].isoformat() if isinstance(row["created_at"], datetime) else str(row["created_at"]),
        "signature":    row["signature"],
        "signature_id": row["signature_id"],
        "hit_count":    row["hit_count"],
        "assessment":   row["assessment"],
        "action":       row["action"],
        "status":       row["status"],
        "confirmed_at": row["confirmed_at"].isoformat() if row["confirmed_at"] and isinstance(row["confirmed_at"], datetime) else None,
    }


# Public alias used by the POST /api/tuning/run endpoint.
generate_tuning_suggestions = _run_tuner


# ── Main loop ─────────────────────────────────────────────────────────────────


async def run_noisetuner(pool) -> None:
    """
    Long-running coroutine — call via ``asyncio.create_task()``.

    On startup checks when the most recent suggestion was created and sleeps
    only for the remaining time in the current interval, preserving the weekly
    schedule across restarts.
    """
    logger.info("Noisetuner started")
    first_run = True
    try:
        while True:
            cfg = await _get_tuner_config(pool)
            interval_secs = cfg["interval_days"] * 86400

            if first_run:
                sleep_secs = float(interval_secs)
                try:
                    async with pool.acquire() as conn:
                        last_row = await conn.fetchrow(
                            "SELECT created_at FROM tuning_suggestions "
                            "ORDER BY created_at DESC LIMIT 1"
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
                await _run_tuner(pool)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Noisetuner run error: %s", exc)
    except asyncio.CancelledError:
        logger.info("Noisetuner stopped")
        raise
