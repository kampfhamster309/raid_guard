/**
 * Return true for globally routable unicast addresses — the only targets a
 * traceroute makes sense for (and the only ones the backend accepts).
 */
export function isPublicIp(ip: string | null | undefined): boolean {
  if (!ip) return false;
  const v = ip.trim();
  if (v.includes(":")) return isPublicIpv6(v);
  return isPublicIpv4(v);
}

function isPublicIpv4(ip: string): boolean {
  const parts = ip.split(".");
  if (parts.length !== 4) return false;
  const o = parts.map((p) => (/^\d{1,3}$/.test(p) ? Number(p) : NaN));
  if (o.some((n) => Number.isNaN(n) || n > 255)) return false;
  const [a, b] = o;
  if (a === 0 || a === 10 || a === 127) return false;
  if (a === 100 && b >= 64 && b <= 127) return false; // CGNAT
  if (a === 169 && b === 254) return false; // link-local
  if (a === 172 && b >= 16 && b <= 31) return false;
  if (a === 192 && b === 168) return false;
  if (a === 192 && b === 0 && o[2] === 2) return false; // TEST-NET-1
  if (a === 198 && (b === 18 || b === 19)) return false; // benchmarking
  if (a === 198 && b === 51 && o[2] === 100) return false; // TEST-NET-2
  if (a === 203 && b === 0 && o[2] === 113) return false; // TEST-NET-3
  if (a >= 224) return false; // multicast + reserved + broadcast
  return true;
}

function isPublicIpv6(ip: string): boolean {
  const lower = ip.toLowerCase();
  if (lower === "::" || lower === "::1") return false;
  if (lower.startsWith("::ffff:")) return isPublicIpv4(lower.slice(7));
  const first = parseInt(lower.split(":")[0] || "0", 16);
  if (Number.isNaN(first)) return false;
  // Only 2000::/3 is global unicast; exclude documentation 2001:db8::/32.
  if ((first & 0xe000) !== 0x2000) return false;
  if (lower.startsWith("2001:db8:") || lower.startsWith("2001:0db8:")) return false;
  return true;
}
