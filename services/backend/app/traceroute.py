"""
Traceroute runner for the pro "visual traceroute" feature.

Runs the system ``traceroute`` binary (Debian ``traceroute`` package) from the
backend container toward a public IP taken from an alert, parses its output,
then annotates each hop with reverse DNS and offline GeoIP/ASN data.

The target is always parsed with :mod:`ipaddress` and passed as a separate
argv element (never through a shell), and only globally routable addresses are
accepted.
"""

import asyncio
import ipaddress
import logging
import re
import socket
import time

from . import geoip

logger = logging.getLogger(__name__)

MAX_HOPS = 30
_WAIT_S = 2
_QUERIES = 2
_OVERALL_TIMEOUT_S = 120
_RDNS_TIMEOUT_S = 2.0

# At most two traceroutes at a time — each sends up to MAX_HOPS * _QUERIES probes.
_semaphore = asyncio.Semaphore(2)

_HOP_LINE = re.compile(r"^\s*(\d+)\s+(.*)$")


class TracerouteError(Exception):
    pass


def validate_target(target: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """Parse ``target`` and reject anything that isn't a globally routable IP."""
    try:
        ip = ipaddress.ip_address(target.strip())
    except ValueError:
        raise ValueError(f"'{target}' is not a valid IP address")
    if not ip.is_global or ip.is_multicast:
        raise ValueError(f"{ip} is not a public IP address — only external hosts can be traced")
    return ip


def parse_traceroute(output: str) -> list[dict]:
    """Parse ``traceroute -n`` output into ``[{hop, ip, rtt_ms}]``.

    Handles timeouts (``*``), multiple probes per hop (first responding IP,
    lowest RTT wins) and ``!H``/``!N``-style annotations.
    """
    hops: list[dict] = []
    for line in output.splitlines():
        m = _HOP_LINE.match(line)
        if not m:
            continue  # header line ("traceroute to ...") or noise
        hop_no = int(m.group(1))
        tokens = m.group(2).split()
        ip: str | None = None
        rtts: list[float] = []
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok == "*" or tok.startswith("!"):
                i += 1
                continue
            if i + 1 < len(tokens) and tokens[i + 1] == "ms":
                try:
                    rtts.append(float(tok))
                except ValueError:
                    pass
                i += 2
                continue
            if ip is None:
                try:
                    ip = str(ipaddress.ip_address(tok.strip("()")))
                except ValueError:
                    pass
            i += 1
        hops.append({"hop": hop_no, "ip": ip, "rtt_ms": min(rtts) if rtts else None})
    return hops


async def _exec_traceroute(ip: str, icmp: bool) -> tuple[int, str, str]:
    args = ["traceroute", "-n", "-q", str(_QUERIES), "-w", str(_WAIT_S), "-m", str(MAX_HOPS)]
    if icmp:
        args.append("-I")
    args.append(ip)
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=_OVERALL_TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise TracerouteError(f"traceroute timed out after {_OVERALL_TIMEOUT_S}s")
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


async def run_traceroute_raw(ip: str) -> str:
    """Run traceroute, preferring ICMP probes (better reach through firewalls).

    ICMP needs CAP_NET_RAW (present by default for root in Docker); fall back
    to UDP probes when it isn't available.
    """
    try:
        code, out, err = await _exec_traceroute(ip, icmp=True)
    except FileNotFoundError:
        raise TracerouteError("traceroute binary is not installed in the backend container")
    if code != 0 and ("not permitted" in err.lower() or "permission" in err.lower()):
        code, out, err = await _exec_traceroute(ip, icmp=False)
    if code != 0 and not out.strip():
        raise TracerouteError(err.strip() or f"traceroute exited with code {code}")
    return out


async def reverse_dns(ip: str) -> str | None:
    loop = asyncio.get_running_loop()
    try:
        host, _ = await asyncio.wait_for(
            loop.getnameinfo((ip, 0), socket.NI_NAMEREQD), timeout=_RDNS_TIMEOUT_S
        )
    except Exception:
        return None
    return host if host and host != ip else None


async def trace(target: str) -> dict:
    """Run a full annotated traceroute and return the API response payload."""
    ip = validate_target(target)
    started = time.monotonic()
    async with _semaphore:
        output = await run_traceroute_raw(str(ip))
    hops = parse_traceroute(output)

    # Drop the run of unanswered hops at the end (host/firewall drops probes) but report it.
    last_answered = max((i for i, h in enumerate(hops) if h["ip"]), default=-1)
    trailing = len(hops) - last_answered - 1
    hops = hops[: last_answered + 1]

    hostnames = await asyncio.gather(*(reverse_dns(h["ip"]) if h["ip"] else _none() for h in hops))
    for hop, hostname in zip(hops, hostnames):
        hop["hostname"] = hostname
        if hop["ip"]:
            addr = ipaddress.ip_address(hop["ip"])
            hop["private"] = not addr.is_global
            hop["geo"], hop["asn"] = geoip.lookup.lookup(hop["ip"])
        else:
            hop["private"] = False
            hop["geo"], hop["asn"] = None, None

    return {
        "target": str(ip),
        "reached": bool(hops) and hops[-1]["ip"] == str(ip),
        "hops": hops,
        "trailing_timeouts": trailing,
        "geo_available": geoip.lookup.available(),
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


async def _none():
    return None
