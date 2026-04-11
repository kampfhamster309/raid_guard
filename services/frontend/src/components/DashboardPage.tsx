import { useStats } from "../hooks/useStats";
import { AlertsPerHourChart } from "./AlertsPerHourChart";
import { TopListCard } from "./TopListCard";

export function DashboardPage() {
  const { stats, loading, error } = useStats();

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-400 text-sm">
        Loading stats…
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center text-red-400 text-sm">
        {error}
      </div>
    );
  }

  if (!stats) return null;

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-4">
      {/* Summary card */}
      <div className="bg-slate-800 rounded-lg p-4 flex items-center gap-4">
        <div>
          <p className="text-xs text-slate-400 uppercase tracking-wide">
            Alerts (last 24 h)
          </p>
          <p
            className="text-4xl font-bold text-white mt-1"
            aria-label={`${stats.total_alerts_24h} alerts in the last 24 hours`}
          >
            {stats.total_alerts_24h.toLocaleString()}
          </p>
        </div>
      </div>

      {/* Hourly chart */}
      <div className="bg-slate-800 rounded-lg p-4">
        <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">
          Alerts per hour
        </h3>
        <AlertsPerHourChart data={stats.alerts_per_hour} />
      </div>

      {/* Top lists */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <TopListCard
          title="Top source IPs"
          items={stats.top_src_ips}
          emptyMessage="No source IP data"
        />
        <TopListCard
          title="Top signatures"
          items={stats.top_signatures}
          emptyMessage="No signature data"
        />
      </div>
    </div>
  );
}
