import type { RiskLevel } from "../types";

const COLORS: Record<RiskLevel, string> = {
  low: "bg-emerald-900 text-emerald-200",
  medium: "bg-amber-900 text-amber-200",
  high: "bg-orange-900 text-orange-200",
  critical: "bg-red-900 text-red-200",
};

export function RiskBadge({ level }: { level: RiskLevel }) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold uppercase tracking-wide ${COLORS[level]}`}
    >
      {level}
    </span>
  );
}
