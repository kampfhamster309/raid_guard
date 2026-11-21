"""
Offline IP geolocation + ASN lookup using the free DB-IP Lite databases (pro).

DB-IP Lite (https://db-ip.com) is licensed CC BY 4.0 — the UI shows an
attribution link wherever geo data is displayed.

Databases live in ``GEOIP_DIR`` (default ``/geoip``, a compose volume):

    dbip-city-lite.mmdb   city / country / lat-lon
    dbip-asn-lite.mmdb    autonomous system number + organisation

They are downloaded by :func:`run_geoip_updater` only while the pro edition is
enabled, and refreshed once they are older than ``GEOIP_MAX_AGE_DAYS`` (DB-IP
publishes a new Lite release at the start of every month).  No IP address ever
leaves the box for a lookup.
"""

import asyncio
import gzip
import ipaddress
import logging
import os
import shutil
import time
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import maxminddb

from .edition import EDITION_PRO, get_edition

logger = logging.getLogger(__name__)

DATABASES = {
    "city": "dbip-city-lite",
    "asn": "dbip-asn-lite",
}
_DOWNLOAD_URL = "https://download.db-ip.com/free/{name}-{year:04d}-{month:02d}.mmdb.gz"
_CHECK_INTERVAL_S = 6 * 3600
_MAX_AGE_DAYS = int(os.environ.get("GEOIP_MAX_AGE_DAYS", "35"))


def geoip_dir() -> Path:
    return Path(os.environ.get("GEOIP_DIR", "/geoip"))


def db_path(kind: str) -> Path:
    return geoip_dir() / f"{DATABASES[kind]}.mmdb"


# ── Lookup ────────────────────────────────────────────────────────────────────


class GeoIpLookup:
    """Lazily opens the mmdb files and reopens them when the updater replaces them."""

    def __init__(self) -> None:
        self._readers: dict[str, tuple[float, maxminddb.Reader]] = {}

    def _reader(self, kind: str):
        path = db_path(kind)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None
        cached = self._readers.get(kind)
        if cached and cached[0] == mtime:
            return cached[1]
        try:
            reader = maxminddb.open_database(str(path))
        except Exception as exc:
            logger.warning("GeoIP: cannot open %s: %s", path, exc)
            return None
        if cached:
            try:
                cached[1].close()
            except Exception:
                pass
        self._readers[kind] = (mtime, reader)
        return reader

    def available(self) -> bool:
        return self._reader("city") is not None or self._reader("asn") is not None

    def lookup(self, ip: str) -> tuple[dict | None, dict | None]:
        """Return ``(geo, asn)`` for a public IP; ``(None, None)`` for private ones or misses."""
        try:
            if not ipaddress.ip_address(ip).is_global:
                return None, None
        except ValueError:
            return None, None
        return self._lookup_city(ip), self._lookup_asn(ip)

    def _lookup_city(self, ip: str) -> dict | None:
        reader = self._reader("city")
        if reader is None:
            return None
        try:
            rec = reader.get(ip)
        except Exception:
            return None
        if not rec:
            return None
        loc = rec.get("location") or {}
        lat, lon = loc.get("latitude"), loc.get("longitude")
        if lat is None or lon is None:
            return None
        country = rec.get("country") or {}
        subdivisions = rec.get("subdivisions") or [{}]
        return {
            "lat": float(lat),
            "lon": float(lon),
            "city": _en_name(rec.get("city")),
            "region": _en_name(subdivisions[0]),
            "country": _en_name(country),
            "country_code": country.get("iso_code"),
        }

    def _lookup_asn(self, ip: str) -> dict | None:
        reader = self._reader("asn")
        if reader is None:
            return None
        try:
            rec = reader.get(ip)
        except Exception:
            return None
        if not rec or rec.get("autonomous_system_number") is None:
            return None
        return {
            "number": int(rec["autonomous_system_number"]),
            "org": rec.get("autonomous_system_organization"),
        }


def _en_name(obj) -> str | None:
    if not isinstance(obj, dict):
        return None
    names = obj.get("names") or {}
    return names.get("en")


lookup = GeoIpLookup()


# ── Updater ───────────────────────────────────────────────────────────────────

_wakeup: asyncio.Event | None = None
_state: dict = {"updating": False, "last_error": None, "last_attempt": None}


def request_update(force: bool = False) -> None:
    """Wake the updater (e.g. right after pro was enabled); ``force`` re-downloads fresh files too."""
    if force:
        _state["force"] = True
    if _wakeup is not None:
        _wakeup.set()


def status() -> dict:
    files = {}
    for kind in DATABASES:
        path = db_path(kind)
        try:
            mtime = path.stat().st_mtime
            files[kind] = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
        except OSError:
            files[kind] = None
    return {
        "available": lookup.available(),
        "city_db_updated": files["city"],
        "asn_db_updated": files["asn"],
        "updating": _state["updating"],
        "last_error": _state["last_error"],
    }


def is_stale(path: Path, now: float | None = None, max_age_days: int = _MAX_AGE_DAYS) -> bool:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return True
    now = time.time() if now is None else now
    return (now - mtime) > max_age_days * 86400


def candidate_urls(name: str, today: date | None = None) -> list[str]:
    """This month's release first, then last month's (the new one may not be out yet)."""
    today = today or date.today()
    prev_year, prev_month = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    return [
        _DOWNLOAD_URL.format(name=name, year=today.year, month=today.month),
        _DOWNLOAD_URL.format(name=name, year=prev_year, month=prev_month),
    ]


async def download_database(kind: str, client: httpx.AsyncClient) -> None:
    """Download + gunzip one database, atomically replacing the existing file."""
    target = db_path(kind)
    target.parent.mkdir(parents=True, exist_ok=True)
    gz_tmp = target.with_suffix(".mmdb.gz.part")
    mmdb_tmp = target.with_suffix(".mmdb.part")
    last_exc: Exception | None = None
    for url in candidate_urls(DATABASES[kind]):
        try:
            async with client.stream("GET", url) as resp:
                if resp.status_code == 404:
                    last_exc = RuntimeError(f"{url} not found")
                    continue
                resp.raise_for_status()
                with open(gz_tmp, "wb") as fh:
                    async for chunk in resp.aiter_bytes(1 << 20):
                        fh.write(chunk)
            await asyncio.to_thread(_gunzip, gz_tmp, mmdb_tmp)
            # Validate before swapping in.
            await asyncio.to_thread(lambda: maxminddb.open_database(str(mmdb_tmp)).close())
            os.replace(mmdb_tmp, target)
            logger.info("GeoIP: updated %s from %s", target.name, url)
            return
        except Exception as exc:
            last_exc = exc
        finally:
            for p in (gz_tmp, mmdb_tmp):
                p.unlink(missing_ok=True)
    raise RuntimeError(f"download of {DATABASES[kind]} failed: {last_exc}")


def _gunzip(src: Path, dst: Path) -> None:
    with gzip.open(src, "rb") as fin, open(dst, "wb") as fout:
        shutil.copyfileobj(fin, fout, 1 << 20)


async def update_if_stale(force: bool = False) -> None:
    stale = [k for k in DATABASES if force or is_stale(db_path(k))]
    if not stale:
        return
    _state["updating"] = True
    _state["last_attempt"] = time.time()
    errors = []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=120.0), follow_redirects=True) as client:
            for kind in stale:
                try:
                    await download_database(kind, client)
                except Exception as exc:
                    logger.warning("GeoIP: %s", exc)
                    errors.append(str(exc))
    finally:
        _state["updating"] = False
        _state["last_error"] = "; ".join(errors) or None


async def run_geoip_updater(pool) -> None:
    """Background task: keep the DB-IP Lite databases fresh while pro is enabled."""
    global _wakeup
    _wakeup = asyncio.Event()
    while True:
        force, _state["force"] = _state.get("force", False), False
        try:
            if await get_edition(pool) == EDITION_PRO:
                await update_if_stale(force=force)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # never let the loop die
            logger.warning("GeoIP updater error: %s", exc)
        try:
            await asyncio.wait_for(_wakeup.wait(), timeout=_CHECK_INTERVAL_S)
        except asyncio.TimeoutError:
            pass
        _wakeup.clear()
