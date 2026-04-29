import { useCallback, useEffect, useState } from "react";
import { fetchStatus } from "../api";
import type { CaptureAgentStatus, SuricataStatus, SystemStatus } from "../types";

// ── Helpers ───────────────────────────────────────────────────────────────────

const CAPTURE_STATE_LABELS: Record<string, string> = {
  starting: "Starting",
  connecting: "Connecting to Fritzbox",
  waiting_for_reader: "Waiting for Suricata",
  streaming: "Streaming",
  reconnecting: "Reconnecting…",
  error: "Error",
};

function captureStateColor(state?: string): string {
  if (state === "streaming") return "text-emerald-400";
  if (state === "reconnecting" || state === "error") return "text-red-400";
  return "text-amber-400";
}

// ── Shared sub-components ─────────────────────────────────────────────────────

function StatusDot({ ok, loading }: { ok: boolean; loading: boolean }) {
  if (loading) return <span className="inline-block w-3 h-3 rounded-full bg-amber-400 animate-pulse" />;
  return (
    <span
      className={`inline-block w-3 h-3 rounded-full ${ok ? "bg-emerald-500" : "bg-red-500"}`}
    />
  );
}

function Detail({ label, value, valueClass = "text-slate-300" }: { label: string; value: string; valueClass?: string }) {
  return (
    <div className="flex justify-between text-xs mt-1">
      <span className="text-slate-500">{label}</span>
      <span className={valueClass}>{value}</span>
    </div>
  );
}

function Card({
  title,
  ok,
  loading,
  children,
}: {
  title: string;
  ok: boolean;
  loading: boolean;
  children?: React.ReactNode;
}) {
  const borderColor = loading
    ? "border-slate-700"
    : ok
    ? "border-emerald-800"
    : "border-red-800";

  return (
    <div className={`bg-slate-800 border rounded-lg p-4 ${borderColor}`}>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-slate-200">{title}</h3>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400">
            {loading ? "Checking…" : ok ? "OK" : "Error"}
          </span>
          <StatusDot ok={ok} loading={loading} />
        </div>
      </div>
      {children}
    </div>
  );
}

// ── Individual cards ──────────────────────────────────────────────────────────

function CaptureCard({ data, loading }: { data?: CaptureAgentStatus; loading: boolean }) {
  const ok = data?.ok ?? false;
  const state = data?.capture_state;
  const stateLabel = state ? (CAPTURE_STATE_LABELS[state] ?? state) : "—";

  return (
    <Card title="Fritzbox Capture" ok={ok} loading={loading}>
      <Detail
        label="State"
        value={loading ? "—" : stateLabel}
        valueClass={loading ? "text-slate-400" : captureStateColor(state)}
      />
      {!loading && (data?.reconnect_count ?? 0) > 0 && (
        <Detail
          label="Reconnects"
          value={String(data!.reconnect_count)}
          valueClass="text-amber-400"
        />
      )}
      {!loading && !data?.reachable && (
        <p className="text-xs text-red-400 mt-2 break-words">Agent unreachable</p>
      )}
    </Card>
  );
}

function SuricataCard({ data, loading }: { data?: SuricataStatus; loading: boolean }) {
  const ok = data?.ok ?? false;
  const health = data?.health ?? "—";
  const healthLabel = health === "none" ? "No healthcheck" : health.charAt(0).toUpperCase() + health.slice(1);

  return (
    <Card title="Suricata IDS" ok={ok} loading={loading}>
      <Detail
        label="Process"
        value={loading ? "—" : (data?.running ? "Running" : "Stopped")}
        valueClass={loading ? "text-slate-400" : (data?.running ? "text-emerald-400" : "text-red-400")}
      />
      <Detail
        label="Health check"
        value={loading ? "—" : healthLabel}
        valueClass={
          loading ? "text-slate-400"
          : health === "healthy" ? "text-emerald-400"
          : health === "unhealthy" ? "text-red-400"
          : "text-amber-400"
        }
      />
    </Card>
  );
}

function SimpleCard({
  title,
  ok,
  loading,
  okLabel,
  failLabel,
}: {
  title: string;
  ok: boolean;
  loading: boolean;
  okLabel: string;
  failLabel: string;
}) {
  return (
    <Card title={title} ok={ok} loading={loading}>
      <Detail
        label="Status"
        value={loading ? "—" : (ok ? okLabel : failLabel)}
        valueClass={loading ? "text-slate-400" : (ok ? "text-emerald-400" : "text-red-400")}
      />
    </Card>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function StatusPage() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await fetchStatus();
      setStatus(data);
      setLastUpdated(new Date());
      setError(null);
    } catch {
      setError("Could not reach the backend. Is it running?");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 30_000);
    return () => clearInterval(id);
  }, [load]);

  const allOk =
    status !== null &&
    status.db.ok &&
    status.redis.ok &&
    status.ingestor.ok &&
    status.enricher.ok &&
    status.capture_agent.ok &&
    status.suricata.ok;

  return (
    <div className="flex-1 overflow-auto p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-lg font-semibold text-slate-100">System Status</h2>
          {lastUpdated && (
            <p className="text-xs text-slate-500 mt-0.5">
              Last updated {lastUpdated.toLocaleTimeString()}
            </p>
          )}
        </div>
        <button
          onClick={load}
          className="px-3 py-1.5 text-xs font-medium bg-slate-700 hover:bg-slate-600 text-slate-200 rounded transition-colors"
        >
          Refresh
        </button>
      </div>

      {/* Summary banner */}
      {!loading && !error && status && (
        <div
          className={`mb-6 rounded-lg px-4 py-3 text-sm font-medium ${
            allOk
              ? "bg-emerald-900/40 border border-emerald-700 text-emerald-300"
              : "bg-red-900/40 border border-red-700 text-red-300"
          }`}
        >
          {allOk ? "All systems operational" : "One or more components are not healthy"}
        </div>
      )}

      {/* Fetch error */}
      {error && (
        <div className="mb-6 rounded-lg px-4 py-3 text-sm bg-red-900/40 border border-red-700 text-red-300">
          {error}
        </div>
      )}

      {/* Component grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <CaptureCard data={status?.capture_agent} loading={loading} />
        <SuricataCard data={status?.suricata} loading={loading} />
        <SimpleCard
          title="TimescaleDB"
          ok={status?.db.ok ?? false}
          loading={loading}
          okLabel="Reachable"
          failLabel="Unreachable"
        />
        <SimpleCard
          title="Redis"
          ok={status?.redis.ok ?? false}
          loading={loading}
          okLabel="Reachable"
          failLabel="Unreachable"
        />
        <SimpleCard
          title="Alert Ingestor"
          ok={status?.ingestor.ok ?? false}
          loading={loading}
          okLabel="Running"
          failLabel="Stopped"
        />
        <SimpleCard
          title="AI Enricher"
          ok={status?.enricher.ok ?? false}
          loading={loading}
          okLabel="Running"
          failLabel="Stopped"
        />
      </div>
    </div>
  );
}
