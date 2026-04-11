import { useEffect } from "react";
import type { Alert } from "../types";
import { SeverityBadge } from "./SeverityBadge";

interface Props {
  alert: Alert | null;
  onClose: () => void;
}

function Row({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div className="flex gap-2 py-1.5 border-b border-slate-700 last:border-0">
      <span className="w-28 shrink-0 text-slate-400 text-xs">{label}</span>
      <span className="text-slate-200 text-xs font-mono break-all">
        {value ?? "—"}
      </span>
    </div>
  );
}

export function AlertDrawer({ alert, onClose }: Props) {
  useEffect(() => {
    if (!alert) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [alert, onClose]);

  if (!alert) return null;

  return (
    <>
      {/* backdrop */}
      <div
        className="fixed inset-0 bg-black/50 z-10"
        onClick={onClose}
        aria-hidden="true"
      />
      {/* drawer */}
      <aside
        className="fixed right-0 top-0 h-full w-full sm:w-[480px] bg-slate-900 border-l border-slate-700 z-20 flex flex-col shadow-2xl"
        role="dialog"
        aria-label="Alert detail"
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700">
          <div className="flex items-center gap-2">
            <SeverityBadge severity={alert.severity} />
            <span className="text-slate-300 text-sm">Alert #{alert.id.slice(-8)}</span>
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
              Details
            </h2>
            <div className="bg-slate-800 rounded p-3">
              <Row label="Time" value={new Date(alert.timestamp).toLocaleString()} />
              <Row label="Severity" value={alert.severity} />
              <Row label="Signature" value={alert.signature} />
              <Row label="Signature ID" value={alert.signature_id} />
              <Row label="Category" value={alert.category} />
              <Row label="Src IP" value={alert.src_ip} />
              <Row label="Src port" value={alert.src_port} />
              <Row label="Dst IP" value={alert.dst_ip} />
              <Row label="Dst port" value={alert.dst_port} />
              <Row label="Protocol" value={alert.proto} />
            </div>
          </section>

          {alert.raw_json && (
            <section>
              <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                Raw EVE JSON
              </h2>
              <pre className="bg-slate-800 rounded p-3 text-xs text-slate-300 overflow-x-auto whitespace-pre-wrap break-all">
                {JSON.stringify(alert.raw_json, null, 2)}
              </pre>
            </section>
          )}
        </div>
      </aside>
    </>
  );
}
