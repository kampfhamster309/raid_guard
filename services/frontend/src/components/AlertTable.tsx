import type { Alert } from "../types";
import { SeverityBadge } from "./SeverityBadge";

interface Props {
  alerts: Alert[];
  onSelect: (alert: Alert) => void;
}

function formatTs(ts: string): string {
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

export function AlertTable({ alerts, onSelect }: Props) {
  if (alerts.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-500 text-sm">
        No alerts match the current filter.
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-auto">
      <table className="w-full text-sm text-left border-collapse">
        <thead className="sticky top-0 bg-slate-800 text-slate-400 text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-2">Severity</th>
            <th className="px-4 py-2">Time</th>
            <th className="px-4 py-2">Src IP</th>
            <th className="px-4 py-2 hidden md:table-cell">Dst IP</th>
            <th className="px-4 py-2 hidden sm:table-cell">Proto</th>
            <th className="px-4 py-2">Signature</th>
          </tr>
        </thead>
        <tbody>
          {alerts.map((alert) => (
            <tr
              key={alert.id}
              onClick={() => onSelect(alert)}
              className="border-t border-slate-700 hover:bg-slate-700/50 cursor-pointer transition-colors"
            >
              <td className="px-4 py-2">
                <SeverityBadge severity={alert.severity} />
              </td>
              <td className="px-4 py-2 text-slate-400 whitespace-nowrap">
                {formatTs(alert.timestamp)}
              </td>
              <td className="px-4 py-2 font-mono text-slate-200">
                {alert.src_ip}
              </td>
              <td className="px-4 py-2 font-mono text-slate-400 hidden md:table-cell">
                {alert.dst_ip ?? "—"}
              </td>
              <td className="px-4 py-2 text-slate-400 hidden sm:table-cell">
                {alert.proto ?? "—"}
              </td>
              <td className="px-4 py-2 text-slate-300 truncate max-w-xs">
                {alert.signature ?? "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
