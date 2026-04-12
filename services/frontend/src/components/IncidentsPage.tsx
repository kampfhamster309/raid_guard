import { useEffect, useState } from "react";
import { fetchIncident, fetchIncidents } from "../api";
import type { Incident, IncidentDetail } from "../types";
import { IncidentDrawer } from "./IncidentDrawer";
import { RiskBadge } from "./RiskBadge";

const PAGE_SIZE = 20;

export function IncidentsPage() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedIncident, setSelectedIncident] = useState<IncidentDetail | null>(null);
  const [drawerLoading, setDrawerLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchIncidents({ limit: PAGE_SIZE, offset })
      .then((data) => {
        setIncidents(data.items);
        setTotal(data.total);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load incidents"))
      .finally(() => setLoading(false));
  }, [offset]);

  const openIncident = async (id: string) => {
    setDrawerLoading(true);
    try {
      const detail = await fetchIncident(id);
      setSelectedIncident(detail);
    } catch {
      // swallow — drawer stays closed
    } finally {
      setDrawerLoading(false);
    }
  };

  const totalPages = Math.ceil(total / PAGE_SIZE);
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-700 flex items-center justify-between">
        <div>
          <h1 className="text-sm font-semibold text-slate-200">Correlated Incidents</h1>
          <p className="text-xs text-slate-400 mt-0.5">
            AI-detected attack patterns from recent alerts
          </p>
        </div>
        {drawerLoading && (
          <span className="text-xs text-slate-400">Loading…</span>
        )}
      </div>

      {loading && (
        <div className="flex-1 flex items-center justify-center text-slate-400 text-sm">
          Loading incidents…
        </div>
      )}

      {error && !loading && (
        <div className="flex-1 flex items-center justify-center text-red-400 text-sm">
          {error}
        </div>
      )}

      {!loading && !error && incidents.length === 0 && (
        <div className="flex-1 flex flex-col items-center justify-center text-slate-500 gap-2">
          <p className="text-sm">No incidents detected yet.</p>
          <p className="text-xs">
            The correlator runs every 5 minutes. Incidents appear when ≥ 2 related alerts
            are found in the last 30-minute window.
          </p>
        </div>
      )}

      {!loading && !error && incidents.length > 0 && (
        <>
          <div className="flex-1 overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-slate-800 text-slate-400 text-xs uppercase">
                <tr>
                  <th className="px-4 py-2 text-left font-medium">Incident</th>
                  <th className="px-4 py-2 text-left font-medium">Risk</th>
                  <th className="px-4 py-2 text-left font-medium hidden md:table-cell">Period</th>
                  <th className="px-4 py-2 text-right font-medium">Alerts</th>
                  <th className="px-4 py-2 text-left font-medium hidden lg:table-cell">Detected</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/50">
                {incidents.map((inc) => (
                  <tr
                    key={inc.id}
                    onClick={() => openIncident(inc.id)}
                    className="hover:bg-slate-800/60 cursor-pointer transition-colors"
                  >
                    <td className="px-4 py-3 text-slate-200 max-w-xs">
                      <span className="truncate block">
                        {inc.name ?? "Unnamed incident"}
                      </span>
                      {inc.narrative && (
                        <span className="text-xs text-slate-400 truncate block mt-0.5">
                          {inc.narrative}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <RiskBadge level={inc.risk_level} />
                    </td>
                    <td className="px-4 py-3 text-slate-400 text-xs hidden md:table-cell">
                      {new Date(inc.period_start).toLocaleTimeString()} –{" "}
                      {new Date(inc.period_end).toLocaleTimeString()}
                    </td>
                    <td className="px-4 py-3 text-slate-300 text-right font-mono">
                      {inc.alert_ids.length}
                    </td>
                    <td className="px-4 py-3 text-slate-400 text-xs hidden lg:table-cell">
                      {new Date(inc.created_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-between px-4 py-3 border-t border-slate-700 text-xs text-slate-400">
              <span>
                {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
              </span>
              <div className="flex gap-2">
                <button
                  onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                  disabled={offset === 0}
                  className="px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-40"
                >
                  Previous
                </button>
                <span>
                  {currentPage} / {totalPages}
                </span>
                <button
                  onClick={() => setOffset(offset + PAGE_SIZE)}
                  disabled={offset + PAGE_SIZE >= total}
                  className="px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-40"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      )}

      <IncidentDrawer
        incident={selectedIncident}
        onClose={() => setSelectedIncident(null)}
      />
    </div>
  );
}
