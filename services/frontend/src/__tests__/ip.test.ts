import { isPublicIp } from "../lib/ip";
import { groupHopsByLocation } from "../lib/traceroute";
import type { TraceHop } from "../types";

describe("isPublicIp", () => {
  it.each(["8.8.8.8", "1.1.1.1", "213.0.0.5", "2606:4700:4700::1111", "::ffff:8.8.8.8"])("accepts %s", (ip) => {
    expect(isPublicIp(ip)).toBe(true);
  });

  it.each([
    "10.0.0.1", "192.168.178.20", "172.16.5.4", "172.31.255.255", "127.0.0.1", "100.64.1.1",
    "169.254.10.10", "224.0.0.251", "255.255.255.255", "0.0.0.0", "192.0.2.1", "fe80::1", "fd00::1",
    "::1", "2001:db8::1", "not-an-ip", "999.1.1.1", "", null, undefined,
  ])("rejects %s", (ip) => {
    expect(isPublicIp(ip as string | null | undefined)).toBe(false);
  });
});

function hop(n: number, lat?: number, lon?: number): TraceHop {
  return {
    hop: n, ip: `9.9.9.${n}`, hostname: null, rtt_ms: n, private: false, asn: null,
    geo: lat === undefined ? null : { lat, lon: lon!, city: null, region: null, country: null, country_code: null },
  };
}

describe("groupHopsByLocation", () => {
  it("merges consecutive hops at the same spot and skips un-located hops", () => {
    const points = groupHopsByLocation([hop(1), hop(2, 51, 6), hop(3, 51, 6), hop(4), hop(5, 50, 8), hop(6, 51, 6)]);
    expect(points.map((p) => p.hops.map((h) => h.hop))).toEqual([[2, 3], [5], [6]]);
  });
});
