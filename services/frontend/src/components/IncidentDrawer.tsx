import { useEffect } from "react";
import type { IncidentDetail } from "../types";
import { RiskBadge } from "./RiskBadge";
import { SeverityBadge } from "./SeverityBadge";

interface Props {
  incident: IncidentDetail | null;
  onClose: () => void;
}

function Row({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div className="flex gap-2 py-1.5 border-b border-slate-700 last:border-0">
      <span className="w-28 shrink-0 text-slate-400 text-xs">{label}</span>
      <span className="text-slate-200 text-xs font-mono break-all">{value ?? "—"}</span>
    </div>
  );
}

export function IncidentDrawer({ incident, onClose }: Props) {
  useEffect(() => {
    if (!incident) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [incident, onClose]);

  if (!incident) return null;

  const periodStart = new Date(incident.period_start).toLocaleString();
  const periodEnd = new Date(incident.period_end).toLocaleString();
  const createdAt = new Date(incident.created_at).toLocaleString();

  return (
    <>
      <div
        className="fixed inset-0 bg-black/50 z-10"
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        className="fixed right-0 top-0 h-full w-full sm:w-[520px] bg-slate-900 border-l border-slate-700 z-20 flex flex-col shadow-2xl"
        role="dialog"
        aria-label="Incident detail"
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700">
          <div className="flex items-center gap-2">
            <RiskBadge level={incident.risk_level} />
            <span className="text-slate-300 text-sm font-medium">
              {incident.name ?? "Unnamed incident"}
            </span>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white text-xl leading-none"
            aria-label="Close detail"
          >
            ×
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          <section>
            <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
              Overview
            </h2>
            <div className="bg-slate-800 rounded p-3">
              <Row label="Detected at" value={createdAt} />
              <Row label="Period start" value={periodStart} />
              <Row label="Period end" value={periodEnd} />
              <Row label="Risk level" value={incident.risk_level} />
              <Row label="Alert count" value={incident.alert_ids.length} />
            </div>
          </section>

          {incident.narrative && (
            <section>
              <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                Narrative
              </h2>
              <div className="bg-slate-800 rounded p-3">
                <p className="text-sm text-slate-200 leading-relaxed">{incident.narrative}</p>
              </div>
            </section>
          )}

          {incident.alerts.length > 0 && (
            <section>
              <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                Related Alerts ({incident.alerts.length})
              </h2>
              <div className="space-y-2">
                {incident.alerts.map((alert) => (
                  <div
                    key={alert.id}
                    className="bg-slate-800 rounded p-3 flex items-start gap-3"
                  >
                    <SeverityBadge severity={alert.severity} />
                    <div className="min-w-0">
                      <p className="text-xs text-slate-200 font-mono truncate">
                        {alert.signature ?? "unknown"}
                      </p>
                      <p className="text-xs text-slate-400 mt-0.5">
                        {alert.src_ip ?? "?"} → {alert.dst_ip ?? "?"}
                        {alert.dst_port ? `:${alert.dst_port}` : ""}{" "}
                        · {new Date(alert.timestamp).toLocaleTimeString()}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      </aside>
    </>
  );
}
