"""Shared helper — reads LLM config from the config table with env-var fallback.

Priority (highest first):
  1. Value in the ``config`` DB table
  2. Environment variable
  3. Hard-coded default

Both the enricher (at startup) and the settings API (at request time) use this
helper so there is a single source of truth for LLM config resolution.
"""

import os

# field → (db_key, env_var, hard-coded_default)
_KEY_MAP: dict[str, tuple[str, str, str]] = {
    "url":        ("lm_studio_url",        "LM_STUDIO_URL",        ""),
    "model":      ("lm_studio_model",      "LM_STUDIO_MODEL",      ""),
    "timeout":    ("lm_enrichment_timeout","LM_ENRICHMENT_TIMEOUT","90"),
    "max_tokens": ("lm_max_tokens",        "LM_MAX_TOKENS",        "512"),
}


async def get_llm_config(pool) -> dict[str, str]:
    """Return the current LLM configuration as a string-value dict.

    Falls back gracefully to env vars when the DB is unreachable or empty.
    """
    db_keys = [t[0] for t in _KEY_MAP.values()]
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT key, value FROM config WHERE key = ANY($1::text[])", db_keys
            )
        db_values: dict[str, str] = {row["key"]: row["value"] for row in rows}
    except Exception:
        db_values = {}

    result: dict[str, str] = {}
    for field, (db_key, env_key, default) in _KEY_MAP.items():
        result[field] = db_values.get(db_key) or os.environ.get(env_key, "") or default
    return result
