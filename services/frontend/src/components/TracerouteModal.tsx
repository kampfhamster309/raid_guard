import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { runTraceroute } from "../api";
import type { TraceHop, TracerouteResult } from "../types";

// Leaflet is only needed once a trace is shown — keep it out of the main bundle.
const TracerouteMap = lazy(() => import("./TracerouteMap"));

interface Props {
  target: string;
  onClose: () => void;
}

function location(hop: TraceHop): string | null {
  if (!hop.geo) return null;
  return [hop.geo.city, hop.geo.region, hop.geo.country_code].filter(Boolean).join(", ") || null;
}

function HopRow({
  hop,
  isTarget,
  maxRtt,
  active,
  isLast,
  onHover,
}: {
  hop: TraceHop;
  isTarget: boolean;
  maxRtt: number;
  active: boolean;
  isLast: boolean;
  onHover: (hop: number | null) => void;
}) {
  const timeout = hop.ip === null;
  const dot = timeout
    ? "border-2 border-dashed border-slate-600 bg-slate-900 text-slate-500"
    : isTarget
    ? "bg-red-500 text-white"
    : hop.private
    ? "bg-slate-600 text-slate-100"
    : "bg-indigo-500 text-white";
  const loc = location(hop);
  return (
    <li
      className={`relative flex gap-3 pl-1 pr-2 py-2 rounded transition-colors ${active ? "bg-slate-800" : ""}`}
      onMouseEnter={() => onHover(hop.hop)}
      onMouseLeave={() => onHover(null)}
      data-testid={`hop-${hop.hop}`}
    >
      {/* connector line */}
      {!isLast && <span className="absolute left-[17px] top-9 bottom-[-8px] w-px bg-slate-700" aria-hidden="true" />}
      <span
        className={`relative z-10 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full text-xs font-semibold ${dot} ${
          active ? "ring-2 ring-amber-400" : ""
        }`}
      >
        {hop.hop}
      </span>
      <div className="min-w-0 flex-1">
        {timeout ? (
          <p className="text-xs text-slate-500 pt-2">No reply</p>
        ) : (
          <>
            <div className="flex items-baseline justify-between gap-2">
              <p className="font-mono text-xs text-slate-200 truncate" title={hop.ip ?? undefined}>
                {hop.ip}
              </p>
              {hop.rtt_ms !== null && (
                <span className="font-mono text-xs text-slate-300 flex-shrink-0">{hop.rtt_ms.toFixed(1)} ms</span>
              )}
            </div>
            {hop.hostname && <p className="text-xs text-slate-400 truncate" title={hop.hostname}>{hop.hostname}</p>}
            <p className="text-xs text-slate-500 truncate">
              {hop.private
                ? "Private network"
                : [hop.asn ? `AS${hop.asn.number}${hop.asn.org ? ` ${hop.asn.org}` : ""}` : null, loc]
                    .filter(Boolean)
                    .join(" · ") || "Unknown network"}
            </p>
            {hop.rtt_ms !== null && maxRtt > 0 && (
              <div className="mt-1 h-1 rounded bg-slate-800 overflow-hidden">
                <div
                  className={`h-full rounded ${isTarget ? "bg-red-400" : "bg-indigo-400"}`}
                  style={{ width: `${Math.max(2, (hop.rtt_ms / maxRtt) * 100)}%` }}
                />
              </div>
            )}
          </>
        )}
      </div>
    </li>
  );
}

export function TracerouteModal({ target, onClose }: Props) {
  const [result, setResult] = useState<TracerouteResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [activeHop, setActiveHop] = useState<number | null>(null);

  const start = useCallback(async () => {
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      setResult(await runTraceroute(target));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Traceroute failed");
    } finally {
      setRunning(false);
    }
  }, [target]);

  useEffect(() => {
    void start();
  }, [start]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    // Capture phase so the alert drawer underneath doesn't also close.
    document.addEventListener("keydown", handler, true);
    return () => document.removeEventListener("keydown", handler, true);
  }, [onClose]);

  const maxRtt = result ? Math.max(0, ...result.hops.map((h) => h.rtt_ms ?? 0)) : 0;
  const answered = result ? result.hops.filter((h) => h.ip).length : 0;

  return (
    <div className="fixed inset-0 z-30 flex items-stretch justify-center bg-black/70 sm:p-6" role="dialog" aria-label={`Traceroute to ${target}`}>
      <div className="flex w-full max-w-6xl flex-col overflow-hidden bg-slate-900 sm:rounded-lg sm:border sm:border-slate-700 shadow-2xl">
        <header className="flex items-center justify-between gap-3 border-b border-slate-700 px-4 py-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-300">Pro</span>
              <h2 className="text-sm font-semibold text-slate-100 truncate">
                Traceroute → <span className="font-mono">{target}</span>
              </h2>
            </div>
            <p className="text-xs text-slate-400 mt-0.5" aria-live="polite">
              {running
                ? "Tracing… probing up to 30 hops, this can take up to a minute."
                : result
                ? result.reached
                  ? `Reached in ${result.hops.length} hops · ${(result.duration_ms / 1000).toFixed(1)} s`
                  : `Destination did not answer — ${answered} of ${result.hops.length + result.trailing_timeouts} hops replied${
                      result.trailing_timeouts ? `, last ${result.trailing_timeouts} timed out` : ""
                    }`
                : error
                ? "Traceroute failed"
                : ""}
            </p>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <button
              onClick={() => void start()}
              disabled={running}
              className="px-3 py-1.5 text-xs font-medium rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-slate-200"
            >
              {running ? "Tracing…" : "Run again"}
            </button>
            <button onClick={onClose} className="text-slate-400 hover:text-white text-xl leading-none px-1" aria-label="Close traceroute">
              ×
            </button>
          </div>
        </header>

        <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
          <section className="order-2 lg:order-1 min-h-0 flex-1 lg:flex-none lg:w-[380px] overflow-y-auto border-t lg:border-t-0 lg:border-r border-slate-700 p-3">
            {running && (
              <ul className="space-y-3 p-1" aria-hidden="true">
                {Array.from({ length: 6 }, (_, i) => (
                  <li key={i} className="flex gap-3 animate-pulse">
                    <span className="h-8 w-8 rounded-full bg-slate-800" />
                    <span className="flex-1 space-y-1.5 pt-1">
                      <span className="block h-2.5 w-2/3 rounded bg-slate-800" />
                      <span className="block h-2 w-1/2 rounded bg-slate-800" />
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {error && !running && <p className="p-2 text-sm text-red-400">{error}</p>}
            {result && !running && (
              <>
                <ol>
                  {result.hops.map((hop, i) => (
                    <HopRow
                      key={hop.hop}
                      hop={hop}
                      isTarget={hop.ip === result.target}
                      maxRtt={maxRtt}
                      active={activeHop === hop.hop}
                      isLast={i === result.hops.length - 1}
                      onHover={setActiveHop}
                    />
                  ))}
                </ol>
                {result.trailing_timeouts > 0 && (
                  <p className="mt-2 px-2 text-xs text-slate-500">
                    + {result.trailing_timeouts} more hop{result.trailing_timeouts === 1 ? "" : "s"} without reply — the destination or a firewall on the way drops probes.
                  </p>
                )}
                {!result.geo_available && (
                  <p className="mt-3 mx-2 rounded border border-amber-700/50 bg-amber-900/20 px-3 py-2 text-xs text-amber-200">
                    GeoIP databases aren't downloaded yet, so hops can't be placed on the map. Check the Edition section on the Config page.
                  </p>
                )}
              </>
            )}
          </section>

          <section className="order-1 lg:order-2 h-64 sm:h-80 lg:h-auto lg:flex-1 min-h-0">
            <Suspense fallback={<div className="h-full w-full bg-slate-800" />}>
              <TracerouteMap hops={result?.hops ?? []} target={target} activeHop={activeHop} onHoverHop={setActiveHop} />
            </Suspense>
          </section>
        </div>

        <footer className="border-t border-slate-700 px-4 py-2 text-[11px] text-slate-500">
          Probes are sent from the raid_guard server. Locations are approximate (anycast addresses often resolve far from the real server).{" "}
          <a href="https://db-ip.com" target="_blank" rel="noreferrer" className="text-slate-400 underline hover:text-slate-200">
            IP Geolocation by DB-IP
          </a>
        </footer>
      </div>
    </div>
  );
}

export default TracerouteModal;
