"""
Tests for the pro edition flag, traceroute parsing/validation, the pro API
and the GeoIP helper (no network, no real traceroute, no real mmdb files).
"""

import time
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import geoip, traceroute
from app.traceroute import parse_traceroute, validate_target


# ── Edition settings ──────────────────────────────────────────────────────────


def test_get_edition_defaults_to_basic(authed_client):
    client, conn = authed_client
    conn.fetchrow = AsyncMock(return_value=None)
    resp = client.get("/api/settings/edition")
    assert resp.status_code == 200
    assert resp.json() == {"edition": "basic"}


def test_get_edition_ignores_garbage_value(authed_client):
    client, conn = authed_client
    conn.fetchrow = AsyncMock(return_value={"value": "enterprise"})
    assert client.get("/api/settings/edition").json() == {"edition": "basic"}


def test_put_edition_pro_persists_and_wakes_geoip(authed_client):
    client, conn = authed_client
    conn.execute = AsyncMock()
    with patch.object(geoip, "request_update") as wake:
        resp = client.put("/api/settings/edition", json={"edition": "pro"})
    assert resp.status_code == 200
    assert resp.json() == {"edition": "pro"}
    args = conn.execute.await_args.args
    assert args[1:] == ("edition", "pro")
    wake.assert_called_once()


def test_put_edition_basic_does_not_wake_geoip(authed_client):
    client, conn = authed_client
    conn.execute = AsyncMock()
    with patch.object(geoip, "request_update") as wake:
        assert client.put("/api/settings/edition", json={"edition": "basic"}).status_code == 200
    wake.assert_not_called()


def test_put_edition_rejects_unknown(authed_client):
    client, conn = authed_client
    conn.execute = AsyncMock()
    resp = client.put("/api/settings/edition", json={"edition": "gold"})
    assert resp.status_code == 422
    conn.execute.assert_not_awaited()


# ── Pro gate ──────────────────────────────────────────────────────────────────


def test_pro_endpoints_forbidden_in_basic(authed_client):
    client, conn = authed_client
    conn.fetchrow = AsyncMock(return_value={"value": "basic"})
    assert client.post("/api/pro/traceroute", json={"target": "8.8.8.8"}).status_code == 403
    assert client.get("/api/pro/geoip").status_code == 403


def test_traceroute_endpoint_returns_trace(authed_client):
    client, conn = authed_client
    conn.fetchrow = AsyncMock(return_value={"value": "pro"})
    payload = {
        "target": "8.8.8.8", "reached": True, "trailing_timeouts": 0,
        "geo_available": False, "duration_ms": 1234,
        "hops": [{"hop": 1, "ip": "8.8.8.8", "hostname": "dns.google", "rtt_ms": 9.1,
                  "private": False, "geo": None, "asn": {"number": 15169, "org": "Google"}}],
    }
    with patch("app.routers.pro.trace", AsyncMock(return_value=payload)):
        resp = client.post("/api/pro/traceroute", json={"target": "8.8.8.8"})
    assert resp.status_code == 200
    assert resp.json()["hops"][0]["asn"]["number"] == 15169


def test_traceroute_endpoint_rejects_private_target(authed_client):
    client, conn = authed_client
    conn.fetchrow = AsyncMock(return_value={"value": "pro"})
    resp = client.post("/api/pro/traceroute", json={"target": "192.168.178.20"})
    assert resp.status_code == 422


def test_traceroute_endpoint_maps_runner_errors_to_502(authed_client):
    client, conn = authed_client
    conn.fetchrow = AsyncMock(return_value={"value": "pro"})
    with patch("app.routers.pro.trace", AsyncMock(side_effect=traceroute.TracerouteError("boom"))):
        resp = client.post("/api/pro/traceroute", json={"target": "8.8.8.8"})
    assert resp.status_code == 502
    assert resp.json()["detail"] == "boom"


# ── Target validation ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("ok", ["8.8.8.8", " 1.1.1.1 ", "2606:4700:4700::1111"])
def test_validate_target_accepts_public(ok):
    assert str(validate_target(ok)) == ok.strip()


@pytest.mark.parametrize("bad", [
    "192.168.1.1", "10.0.0.1", "127.0.0.1", "100.64.0.1", "169.254.1.1",
    "224.0.0.1", "0.0.0.0", "fe80::1", "8.8.8.8; rm -rf /", "-I", "example.com", "",
])
def test_validate_target_rejects_non_public(bad):
    with pytest.raises(ValueError):
        validate_target(bad)


# ── Output parsing ────────────────────────────────────────────────────────────

_SAMPLE = """traceroute to 8.8.8.8 (8.8.8.8), 30 hops max, 60 byte packets
 1  192.168.178.1  0.512 ms  0.430 ms
 2  * *
 3  100.120.0.1  9.871 ms *
 4  213.0.0.5  12.4 ms  11.9 ms
 5  10.1.1.1  15.000 ms !H  14.1 ms !H
 6  8.8.8.8  13.2 ms  13.0 ms
"""


def test_parse_traceroute_sample():
    hops = parse_traceroute(_SAMPLE)
    assert [h["hop"] for h in hops] == [1, 2, 3, 4, 5, 6]
    assert hops[0] == {"hop": 1, "ip": "192.168.178.1", "rtt_ms": 0.43}
    assert hops[1] == {"hop": 2, "ip": None, "rtt_ms": None}
    assert hops[2]["rtt_ms"] == 9.871
    assert hops[3]["rtt_ms"] == 11.9
    assert hops[4] == {"hop": 5, "ip": "10.1.1.1", "rtt_ms": 14.1}
    assert hops[5]["ip"] == "8.8.8.8"


def test_parse_traceroute_multiple_responders_keeps_first_ip():
    hops = parse_traceroute(" 7  4.4.4.4  20.0 ms 5.5.5.5  18.0 ms\n")
    assert hops == [{"hop": 7, "ip": "4.4.4.4", "rtt_ms": 18.0}]


def test_parse_traceroute_ipv6():
    hops = parse_traceroute(" 1  2001:db8::1  1.2 ms\n")
    assert hops[0]["ip"] == "2001:db8::1"


# ── trace() assembly ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trace_trims_trailing_timeouts_and_annotates():
    raw = _SAMPLE.replace(" 6  8.8.8.8  13.2 ms  13.0 ms\n", " 6  * *\n 7  * *\n")
    fake_lookup = MagicMock()
    fake_lookup.lookup.side_effect = lambda ip: (
        ({"lat": 50.0, "lon": 8.0, "city": "Frankfurt", "region": None, "country": "Germany",
          "country_code": "DE"}, {"number": 3320, "org": "DTAG"})
        if ip == "213.0.0.5" else (None, None)
    )
    fake_lookup.available.return_value = True
    with patch.object(traceroute, "run_traceroute_raw", AsyncMock(return_value=raw)), \
         patch.object(traceroute, "reverse_dns", AsyncMock(return_value="host.example")), \
         patch.object(geoip, "lookup", fake_lookup):
        result = await traceroute.trace("8.8.8.8")

    assert result["reached"] is False
    assert result["trailing_timeouts"] == 2
    assert len(result["hops"]) == 5
    assert result["hops"][0]["private"] is True
    assert result["hops"][1]["hostname"] is None  # timeout hop: no rDNS attempted
    assert result["hops"][3]["geo"]["city"] == "Frankfurt"
    assert result["hops"][3]["asn"]["number"] == 3320
    assert result["geo_available"] is True


@pytest.mark.asyncio
async def test_run_traceroute_falls_back_to_udp_without_raw_socket():
    calls = []

    async def fake_exec(ip, icmp):
        calls.append(icmp)
        if icmp:
            return 1, "", "socket: Operation not permitted"
        return 0, _SAMPLE, ""

    with patch.object(traceroute, "_exec_traceroute", fake_exec):
        out = await traceroute.run_traceroute_raw("8.8.8.8")
    assert calls == [True, False]
    assert "8.8.8.8" in out


@pytest.mark.asyncio
async def test_run_traceroute_missing_binary():
    with patch.object(traceroute, "_exec_traceroute", AsyncMock(side_effect=FileNotFoundError)):
        with pytest.raises(traceroute.TracerouteError, match="not installed"):
            await traceroute.run_traceroute_raw("8.8.8.8")


# ── GeoIP helpers ─────────────────────────────────────────────────────────────


def test_candidate_urls_current_then_previous_month():
    urls = geoip.candidate_urls("dbip-city-lite", date(2026, 1, 3))
    assert urls == [
        "https://download.db-ip.com/free/dbip-city-lite-2026-01.mmdb.gz",
        "https://download.db-ip.com/free/dbip-city-lite-2025-12.mmdb.gz",
    ]


def test_is_stale(tmp_path: Path):
    f = tmp_path / "x.mmdb"
    assert geoip.is_stale(f) is True  # missing
    f.write_bytes(b"x")
    now = f.stat().st_mtime
    assert geoip.is_stale(f, now=now + 86400, max_age_days=35) is False
    assert geoip.is_stale(f, now=now + 40 * 86400, max_age_days=35) is True


def test_lookup_without_databases(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOIP_DIR", str(tmp_path))
    lk = geoip.GeoIpLookup()
    assert lk.available() is False
    assert lk.lookup("8.8.8.8") == (None, None)


def test_lookup_parses_dbip_records(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOIP_DIR", str(tmp_path))
    for kind in geoip.DATABASES:
        geoip.db_path(kind).write_bytes(b"stub")

    city = MagicMock()
    city.get.return_value = {
        "city": {"names": {"en": "Mountain View"}},
        "country": {"iso_code": "US", "names": {"en": "United States"}},
        "subdivisions": [{"names": {"en": "California"}}],
        "location": {"latitude": 37.4, "longitude": -122.1},
    }
    asn = MagicMock()
    asn.get.return_value = {"autonomous_system_number": 15169, "autonomous_system_organization": "Google LLC"}

    def fake_open(path):
        return city if "city" in path else asn

    with patch.object(geoip.maxminddb, "open_database", side_effect=fake_open):
        lk = geoip.GeoIpLookup()
        geo, as_ = lk.lookup("8.8.8.8")
        # Private addresses never hit the databases.
        assert lk.lookup("192.168.1.1") == (None, None)

    assert geo == {"lat": 37.4, "lon": -122.1, "city": "Mountain View", "region": "California",
                   "country": "United States", "country_code": "US"}
    assert as_ == {"number": 15169, "org": "Google LLC"}
