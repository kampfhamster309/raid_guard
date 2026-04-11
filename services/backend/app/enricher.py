"""
AI enricher worker — per-alert fast path (RAID-013).

Architecture
------------
Subscribes to ``alerts:raw`` (published by the ingestor).  For each alert it
calls LM Studio via the OpenAI-compatible API, parses the structured JSON
response, writes the enrichment to the ``enrichment_json`` column in the DB,
then publishes the enriched payload to ``alerts:enriched`` (consumed by the
WebSocket broadcaster and the notification router).

Fallback guarantees
-------------------
- LLM not configured (LM_STUDIO_URL / LM_STUDIO_MODEL unset): acts as a
  transparent passthrough — forwards ``alerts:raw`` → ``alerts:enriched``
  unchanged, preserving the live feed without any LLM dependency.
- LLM timeout or error: publishes the alert *unenriched* to ``alerts:enriched``
  so the frontend and notification router are never blocked.
- DB write failure: logs a warning but still publishes to Redis.

Serialised queue
----------------
Alerts are processed one at a time (``await _enrich_one(...)`` before the next
``pubsub.listen()`` iteration) to avoid overwhelming local inference.
"""

import asyncio
import json
import logging

from openai import AsyncOpenAI

from .channels import ALERTS_ENRICHED, ALERTS_RAW
from .llm_config import get_llm_config

logger = logging.getLogger(__name__)

# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are an expert network security analyst reviewing Suricata IDS alerts from a \
home network environment.

Priority context for this network:
- P1 (highest priority): outbound C2/beaconing, DNS tunneling/DGA, crypto mining
- P2: lateral movement/port scanning, TLS anomalies, exploit attempts on \
exposed services
- P3: IoT behavioural anomalies, geographic traffic anomalies

Analyse the provided Suricata alert and respond with ONLY a JSON object \
containing exactly these three keys:

{
  "summary": "<single sentence, max 15 words, plain English — what happened>",
  "severity_reasoning": "<one or two sentences — is the assigned severity \
appropriate and why>",
  "recommended_action": "<one sentence — what should the analyst investigate \
or do next>"
}

Do not include any text, markdown, or code fences outside the JSON object.\
"""


# Shared response-format schema — used by both the enricher and the test endpoint.
_ENRICHMENT_RESPONSE_FORMAT: dict = {
    "type": "json_schema",
    "json_schema": {
        "name": "alert_enrichment",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "severity_reasoning": {"type": "string"},
                "recommended_action": {"type": "string"},
            },
            "required": ["summary", "severity_reasoning", "recommended_action"],
            "additionalProperties": False,
        },
    },
}


def _build_user_prompt(alert: dict) -> str:
    return (
        "Analyse this Suricata IDS alert:\n\n"
        f"Signature   : {alert.get('signature', 'unknown')}\n"
        f"Category    : {alert.get('category', 'unknown')}\n"
        f"Severity    : {alert.get('severity', 'info')}\n"
        f"Source IP   : {alert.get('src_ip', 'unknown')}\n"
        f"Destination : {alert.get('dst_ip', 'unknown')}:{alert.get('dst_port', '?')}\n"
        f"Protocol    : {alert.get('proto', 'unknown')}\n"
        f"Timestamp   : {alert.get('timestamp', 'unknown')}\n"
    )


# ── LLM call ──────────────────────────────────────────────────────────────────


async def _call_llm(
    client: AsyncOpenAI,
    alert: dict,
    model: str,
    timeout: float,
    max_tokens: int = 512,
) -> dict | None:
    """Call LM Studio and return the parsed enrichment dict, or ``None`` on any failure."""
    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": _build_user_prompt(alert)},
                ],
                response_format=_ENRICHMENT_RESPONSE_FORMAT,
                temperature=0.1,
                max_tokens=max_tokens,
            ),
            timeout=timeout,
        )
        content = response.choices[0].message.content or ""
        enrichment = json.loads(content)
        # Validate that the expected keys are present
        if not all(k in enrichment for k in ("summary", "severity_reasoning", "recommended_action")):
            logger.warning(
                "LLM response for alert %s missing expected keys: %s",
                alert.get("id"), list(enrichment.keys()),
            )
            return None
        return enrichment
    except asyncio.TimeoutError:
        logger.warning("LLM enrichment timed out for alert %s (%.0fs)", alert.get("id"), timeout)
        return None
    except json.JSONDecodeError as exc:
        logger.warning("LLM returned non-JSON for alert %s: %s", alert.get("id"), exc)
        return None
    except Exception as exc:
        logger.warning("LLM enrichment failed for alert %s: %s", alert.get("id"), exc)
        return None


# ── Single-alert enrichment ───────────────────────────────────────────────────


async def _enrich_one(
    client: AsyncOpenAI,
    redis_client,
    pool,
    alert: dict,
    model: str,
    timeout: float,
    max_tokens: int = 512,
) -> None:
    """Enrich one alert and publish to ``alerts:enriched``.  Never raises."""
    enrichment = await _call_llm(client, alert, model, timeout, max_tokens)

    output = dict(alert)
    if enrichment:
        output["enrichment_json"] = enrichment
        # Persist to DB (best-effort — the Redis publish is not gated on this)
        alert_id = alert.get("id")
        if alert_id:
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE alerts SET enrichment_json = $1::jsonb WHERE id = $2::uuid",
                        json.dumps(enrichment),
                        alert_id,
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to persist enrichment for alert %s: %s", alert_id, exc
                )

    try:
        await redis_client.publish(ALERTS_ENRICHED, json.dumps(output, default=str))
    except Exception as exc:
        logger.error("Failed to publish enriched alert %s: %s", alert.get("id"), exc)


# ── Main loop ─────────────────────────────────────────────────────────────────


async def run_enricher(redis_client, pool) -> None:
    """
    Long-running coroutine — call via ``asyncio.create_task()``.

    Reads ``LM_STUDIO_URL``, ``LM_STUDIO_MODEL``, and
    ``LM_ENRICHMENT_TIMEOUT`` from environment variables.  Falls back to
    transparent passthrough if the LLM is not configured.
    """
    cfg = await get_llm_config(pool)
    lm_url = cfg["url"]
    model = cfg["model"]
    timeout = float(cfg["timeout"])
    max_tokens = int(cfg["max_tokens"])

    client: AsyncOpenAI | None = None
    if lm_url and model:
        client = AsyncOpenAI(base_url=lm_url, api_key="lm-studio")
        logger.info(
            "AI enricher started — model=%s, timeout=%.0fs, max_tokens=%d",
            model, timeout, max_tokens,
        )
    else:
        logger.info(
            "AI enricher: LM_STUDIO_URL/LM_STUDIO_MODEL not set; "
            "forwarding alerts:raw → alerts:enriched unchanged."
        )

    pubsub = redis_client.pubsub()
    await pubsub.subscribe(ALERTS_RAW)

    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue

            try:
                alert = json.loads(message["data"])
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning("Enricher: invalid message payload: %s", exc)
                continue

            if client is not None:
                # Serialised: await fully before processing the next message
                await _enrich_one(client, redis_client, pool, alert, model, timeout, max_tokens)
            else:
                # Passthrough: forward unchanged so WebSocket + notification router work
                try:
                    await redis_client.publish(ALERTS_ENRICHED, message["data"])
                except Exception as exc:
                    logger.warning("Enricher passthrough publish failed: %s", exc)

    except asyncio.CancelledError:
        try:
            await pubsub.unsubscribe(ALERTS_RAW)
        except Exception:
            pass
        raise
