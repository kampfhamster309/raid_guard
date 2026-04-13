"""
Fritzbox TR-064 device-level WAN blocking via X_AVM-DE_HostFilter1.

INVESTIGATION FINDINGS (RAID-018)
==================================
The Fritzbox TR-064 API **cannot** block specific external (WAN) IPs.
The proprietary X_AVM-DE_HostFilter1 service provides the closest capability:
cutting off a specific **internal** LAN device from all WAN access.
Confirmed working on Fritzbox 6660 Cable.

What IS feasible
----------------
  Block an internal device (by LAN IP) from all internet access:
      DisallowWANAccessByIP(NewIPv4Address, NewDisallow=1)
  Re-allow WAN access (NewDisallow=0) via the same action.
  Query current block state via GetWANAccessByIP.

What is NOT feasible via TR-064
--------------------------------
  Blocking a specific external IP from initiating inbound connections.
  Fine-grained per-protocol / per-port / per-destination firewall rules.
  Blocking an IP not yet in the Fritzbox host table (raises FritzLookUpError
  with errorCode 714 "NoSuchEntryInArray").

Use cases covered
-----------------
  An internal device is detected doing C2 beacon traffic → quarantine it
  by cutting off all WAN access until an admin manually reviews and lifts
  the block.

Limitations
-----------
  Blocks ALL WAN traffic for the device — not surgical.
  Only works while the device keeps the same LAN IP (DHCP lease).
  Device must have previously connected (appear in Fritzbox host table).
  The block persists on the Fritzbox across router reboots.
"""

import asyncio
import os

from fritzconnection.core.exceptions import (
    FritzAuthorizationError,
    FritzConnectionException,
    FritzLookUpError,
    FritzServiceError,
)
from fritzconnection.core.fritzconnection import FritzConnection

_SERVICE = "X_AVM-DE_HostFilter1"


class FritzBlockerError(Exception):
    """Raised when a Fritzbox TR-064 operation fails."""


class FritzNotInHostTableError(FritzBlockerError):
    """Device IP is not in the Fritzbox host table (TR-064 error 714)."""


class FritzBlocker:
    """Thin async wrapper around the Fritzbox X_AVM-DE_HostFilter1 TR-064 service."""

    def __init__(self, host: str, user: str, password: str) -> None:
        self._host = host
        self._user = user
        self._password = password

    def _conn(self) -> FritzConnection:
        return FritzConnection(
            address=self._host,
            user=self._user,
            password=self._password,
            timeout=10,
        )

    # ── sync internals (run in thread pool) ──────────────────────────────────

    def _check_status_sync(self) -> dict:
        """Return connectivity and service-availability info."""
        try:
            fc = self._conn()
            available = _SERVICE in fc.services
            info = fc.call_action("DeviceInfo1", "GetInfo")
            return {
                "connected": True,
                "host_filter_available": available,
                "model": info.get("NewModelName", ""),
                "firmware": info.get("NewSoftwareVersion", ""),
            }
        except FritzAuthorizationError:
            raise FritzBlockerError("Fritzbox authentication failed — check FRITZ_USER and FRITZ_PASSWORD")
        except FritzConnectionException as exc:
            raise FritzBlockerError(f"Cannot reach Fritzbox: {exc}")

    def _block_sync(self, ip: str) -> None:
        try:
            fc = self._conn()
            fc.call_action(_SERVICE, "DisallowWANAccessByIP", NewIPv4Address=ip, NewDisallow=1)
        except FritzLookUpError:
            raise FritzNotInHostTableError(
                f"{ip} is not in the Fritzbox host table. "
                "The device must have connected to the network at least once."
            )
        except FritzAuthorizationError:
            raise FritzBlockerError("Fritzbox authentication failed")
        except (FritzServiceError, FritzConnectionException) as exc:
            raise FritzBlockerError(str(exc))

    def _unblock_sync(self, ip: str) -> None:
        try:
            fc = self._conn()
            fc.call_action(_SERVICE, "DisallowWANAccessByIP", NewIPv4Address=ip, NewDisallow=0)
        except FritzLookUpError:
            raise FritzNotInHostTableError(f"{ip} is not in the Fritzbox host table")
        except FritzAuthorizationError:
            raise FritzBlockerError("Fritzbox authentication failed")
        except (FritzServiceError, FritzConnectionException) as exc:
            raise FritzBlockerError(str(exc))

    def _is_blocked_sync(self, ip: str) -> bool:
        try:
            fc = self._conn()
            result = fc.call_action(_SERVICE, "GetWANAccessByIP", NewIPv4Address=ip)
            return bool(result.get("NewDisallow", False))
        except FritzLookUpError:
            return False
        except (FritzAuthorizationError, FritzServiceError, FritzConnectionException) as exc:
            raise FritzBlockerError(str(exc))

    def _get_hostname_sync(self, ip: str) -> str | None:
        """Best-effort hostname lookup from Fritzbox host table."""
        try:
            fc = self._conn()
            result = fc.call_action(_SERVICE, "GetHostEntryByIP", NewIPv4Address=ip)
            name = result.get("NewHostName", "")
            return name if name else None
        except Exception:
            return None

    # ── async public API ──────────────────────────────────────────────────────

    async def check_status(self) -> dict:
        return await asyncio.to_thread(self._check_status_sync)

    async def block(self, ip: str) -> None:
        await asyncio.to_thread(self._block_sync, ip)

    async def unblock(self, ip: str) -> None:
        await asyncio.to_thread(self._unblock_sync, ip)

    async def is_blocked(self, ip: str) -> bool:
        return await asyncio.to_thread(self._is_blocked_sync, ip)

    async def get_hostname(self, ip: str) -> str | None:
        return await asyncio.to_thread(self._get_hostname_sync, ip)


def get_fritz_blocker() -> FritzBlocker | None:
    """Return a configured FritzBlocker, or None if FRITZ_HOST / FRITZ_PASSWORD are unset."""
    host = os.environ.get("FRITZ_HOST", "").strip()
    user = os.environ.get("FRITZ_USER", "").strip()
    password = os.environ.get("FRITZ_PASSWORD", "").strip()
    if not host or not password:
        return None
    return FritzBlocker(host, user, password)
