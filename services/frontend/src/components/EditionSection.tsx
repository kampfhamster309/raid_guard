import { useEffect, useState } from "react";
import { fetchGeoIpStatus, requestGeoIpUpdate, updateEdition } from "../api";
import { useEdition } from "../edition";
import type { Edition, GeoIpStatus } from "../types";

const PRO_FEATURES = [
  {
    name: "Visual traceroute",
    description: "Trace the path to any external IP from an alert and see every hop on a map, with ASN and location.",
  },
];

function formatDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString() : "not downloaded";
}

export function EditionSection({ isAdmin }: { isAdmin: boolean }) {
  const { edition, setEdition } = useEdition();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [geoip, setGeoip] = useState<GeoIpStatus | null>(null);

  // Poll the GeoIP status while pro is on and a download is running / pending.
  useEffect(() => {
    if (edition !== "pro") {
      setGeoip(null);
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = () => {
      fetchGeoIpStatus()
        .then((s) => {
          if (cancelled) return;
          setGeoip(s);
          if (s.updating || (!s.available && !s.last_error)) timer = setTimeout(load, 3000);
        })
        .catch(() => {});
    };
    load();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [edition]);

  const choose = async (next: Edition) => {
    if (next === edition || !isAdmin) return;
    setSaving(true);
    setError(null);
    try {
      setEdition(await updateEdition(next));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not change edition");
    } finally {
      setSaving(false);
    }
  };

  const updateGeoip = async () => {
    try {
      setGeoip(await requestGeoIpUpdate());
      // Let the background download start, then poll.
      setTimeout(() => void fetchGeoIpStatus().then(setGeoip).catch(() => {}), 1500);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start GeoIP update");
    }
  };

  const segment = (value: Edition, label: string) => (
    <button
      role="radio"
      aria-checked={edition === value}
      onClick={() => void choose(value)}
      disabled={saving || !isAdmin}
      className={`px-4 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed ${
        edition === value
          ? value === "pro"
            ? "bg-amber-500 text-slate-900"
            : "bg-indigo-600 text-white"
          : "text-slate-300 hover:bg-slate-700 disabled:hover:bg-transparent"
      }`}
    >
      {label}
    </button>
  );

  return (
    <section>
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-100">Edition</h2>
          <p className="text-sm text-slate-400 mt-0.5">
            Pro unlocks additional analysis tools. You can switch back to Basic at any time.
          </p>
        </div>
        <div role="radiogroup" aria-label="Edition" className="flex flex-shrink-0 overflow-hidden rounded-md border border-slate-600">
          {segment("basic", "Basic")}
          {segment("pro", "Pro")}
        </div>
      </div>

      {error && <p className="mb-3 text-xs text-red-400">{error}</p>}

      <div className="rounded-lg border border-slate-700 divide-y divide-slate-700">
        {PRO_FEATURES.map((f) => (
          <div key={f.name} className="px-4 py-3 flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="text-sm font-medium text-slate-200">{f.name}</p>
              <p className="text-xs text-slate-400 mt-0.5">{f.description}</p>
            </div>
            <span
              className={`flex-shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                edition === "pro" ? "bg-emerald-500/20 text-emerald-300" : "bg-slate-700 text-slate-400"
              }`}
            >
              {edition === "pro" ? "Active" : "Pro"}
            </span>
          </div>
        ))}

        {edition === "pro" && (
          <div className="px-4 py-3 flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="text-sm font-medium text-slate-200">GeoIP databases</p>
              <p className="text-xs text-slate-400 mt-0.5">
                {!geoip
                  ? "Loading…"
                  : geoip.updating
                  ? "Downloading DB-IP Lite databases…"
                  : geoip.available
                  ? `DB-IP Lite, offline. City: ${formatDate(geoip.city_db_updated)} · ASN: ${formatDate(geoip.asn_db_updated)}. Refreshed monthly.`
                  : geoip.last_error
                  ? "Download failed — traceroute still works, but hops won't appear on the map."
                  : "Waiting for the first download…"}
              </p>
              {geoip?.last_error && !geoip.updating && (
                <p className="text-xs text-red-400 mt-1 break-words">
                  {geoip.last_error}. If Pi-hole is your DNS, allow <span className="font-mono">download.db-ip.com</span>.
                </p>
              )}
            </div>
            {isAdmin && (
              <button
                onClick={() => void updateGeoip()}
                disabled={!geoip || geoip.updating}
                className="flex-shrink-0 px-3 py-1.5 rounded text-xs font-medium bg-slate-700 hover:bg-slate-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-slate-200"
              >
                {geoip?.updating ? "Updating…" : "Update now"}
              </button>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
