"""
Pi-hole v6 REST API client (RAID-016).

Pi-hole v6 uses session-based authentication:
  POST /api/auth  {"password": "..."} → {"session": {"sid": "...", "validity": 1800, "valid": true}}

The session token (sid) is passed as a request header: ``sid: <token>``.
Sessions expire after ``validity`` seconds (default 1800 = 30 minutes).

This module caches session tokens in memory per Pi-hole base URL so that
subsequent requests within the validity window do not re-authenticate.
"""

import logging
import os
import time

import httpx

logger = logging.getLogger(__name__)

# Module-level token cache: url → (sid, expires_at_unix_float)
_session_cache: dict[str, tuple[str, float]] = {}

# Re-authenticate this many seconds before the token officially expires.
_SESSION_BUFFER_SECS = 60


# ── Exceptions ────────────────────────────────────────────────────────────────


class PiholeError(Exception):
    """Raised when the Pi-hole API returns an error or is unreachable."""


# ── Session management ────────────────────────────────────────────────────────


def clear_session_cache() -> None:
    """Evict all cached sessions (useful for testing)."""
    _session_cache.clear()


async def _authenticate(url: str, password: str) -> str:
    """Authenticate and return a fresh session ID."""
    clean_url = url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.post(f"{clean_url}/api/auth", json={"password": password})
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        raise PiholeError(
            f"Pi-hole authentication failed: HTTP {exc.response.status_code}"
        ) from exc
    except Exception as exc:
        raise PiholeError(f"Pi-hole unreachable: {exc}") from exc

    session = data.get("session", {})
    if not session.get("valid"):
        raise PiholeError(
            "Pi-hole authentication failed — check your admin password"
        )

    sid: str = session["sid"]
    validity: int = int(session.get("validity", 1800))
    _session_cache[url] = (sid, time.time() + validity)
    logger.debug("Pi-hole: authenticated (validity=%ds)", validity)
    return sid


async def _get_sid(url: str, password: str) -> str:
    """Return a valid session ID, re-authenticating if the cached token has expired."""
    cached = _session_cache.get(url)
    if cached:
        sid, expires_at = cached
        if time.time() < expires_at - _SESSION_BUFFER_SECS:
            return sid
        _session_cache.pop(url, None)
    return await _authenticate(url, password)


# ── Config helper ─────────────────────────────────────────────────────────────


async def get_pihole_config(pool) -> dict:
    """Return ``{url, password, enabled}`` from the config table with env-var fallback.

    Priority: DB config → environment variables → defaults (empty/disabled).
    """
    result: dict = {"url": "", "password": "", "enabled": False}
    key_map = {
        "pihole_url":      "url",
        "pihole_password": "password",
        "pihole_enabled":  "enabled",
    }
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT key, value FROM config WHERE key = ANY($1::text[])",
                list(key_map.keys()),
            )
        for row in rows:
            field = key_map[row["key"]]
            if row["value"]:
                if field == "enabled":
                    result["enabled"] = row["value"].lower() == "true"
                else:
                    result[field] = row["value"]
    except Exception:
        pass

    # Env-var fallback for URL and password
    if not result["url"]:
        host = os.environ.get("PIHOLE_HOST", "").strip()
        if host:
            result["url"] = host if host.startswith("http") else f"http://{host}"
    if not result["password"]:
        result["password"] = os.environ.get("PIHOLE_PASSWORD", "").strip()

    return result


# ── Domain operations ─────────────────────────────────────────────────────────


async def block_domain(
    url: str, password: str, domain: str, comment: str = "Blocked by raid_guard"
) -> None:
    """Add *domain* to Pi-hole's exact deny list."""
    sid = await _get_sid(url, password)
    clean_url = url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.post(
                f"{clean_url}/api/domains/deny/exact",
                headers={"sid": sid},
                json={"domain": domain, "comment": comment, "enabled": True},
            )
            if resp.status_code == 401:
                _session_cache.pop(url, None)
                raise PiholeError("Pi-hole session expired — please retry")
            resp.raise_for_status()
    except PiholeError:
        raise
    except httpx.HTTPStatusError as exc:
        raise PiholeError(
            f"Pi-hole block failed: HTTP {exc.response.status_code}"
        ) from exc
    except Exception as exc:
        raise PiholeError(f"Pi-hole unreachable: {exc}") from exc


async def unblock_domain(url: str, password: str, domain: str) -> None:
    """Remove *domain* from Pi-hole's exact deny list."""
    sid = await _get_sid(url, password)
    clean_url = url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.delete(
                f"{clean_url}/api/domains/deny/exact/{domain}",
                headers={"sid": sid},
            )
            if resp.status_code == 401:
                _session_cache.pop(url, None)
                raise PiholeError("Pi-hole session expired — please retry")
            # 404 is acceptable — domain wasn't blocked
            if resp.status_code not in (200, 204, 404):
                resp.raise_for_status()
    except PiholeError:
        raise
    except httpx.HTTPStatusError as exc:
        raise PiholeError(
            f"Pi-hole unblock failed: HTTP {exc.response.status_code}"
        ) from exc
    except Exception as exc:
        raise PiholeError(f"Pi-hole unreachable: {exc}") from exc


async def list_blocked_domains(url: str, password: str) -> list[dict]:
    """Return all domains in Pi-hole's exact deny list.

    Each entry: ``{domain, comment, added_at, enabled}``
    where ``added_at`` is a Unix timestamp (int) or ``None``.
    """
    sid = await _get_sid(url, password)
    clean_url = url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.get(
                f"{clean_url}/api/domains",
                headers={"sid": sid},
                params={"type": "deny", "kind": "exact"},
            )
            if resp.status_code == 401:
                _session_cache.pop(url, None)
                raise PiholeError("Pi-hole session expired — please retry")
            resp.raise_for_status()
            data = resp.json()
    except PiholeError:
        raise
    except httpx.HTTPStatusError as exc:
        raise PiholeError(
            f"Pi-hole list failed: HTTP {exc.response.status_code}"
        ) from exc
    except Exception as exc:
        raise PiholeError(f"Pi-hole unreachable: {exc}") from exc

    return [
        {
            "domain":   d.get("domain", ""),
            "comment":  d.get("comment", ""),
            "added_at": d.get("date_added"),
            "enabled":  d.get("enabled", True),
        }
        for d in data.get("domains", [])
    ]
