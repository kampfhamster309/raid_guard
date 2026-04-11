import type { Severity } from "../types";

type SeverityFilter = Severity | "all";

const BUTTONS: { label: string; value: SeverityFilter }[] = [
  { label: "All", value: "all" },
  { label: "Critical", value: "critical" },
  { label: "Warning", value: "warning" },
  { label: "Info", value: "info" },
];

interface Props {
  severityFilter: SeverityFilter;
  onSeverityChange: (v: SeverityFilter) => void;
  searchText: string;
  onSearchChange: (v: string) => void;
}

export function FilterBar({
  severityFilter,
  onSeverityChange,
  searchText,
  onSearchChange,
}: Props) {
  return (
    <div className="flex flex-wrap items-center gap-2 px-4 py-3 bg-slate-800 border-b border-slate-700">
      <div className="flex gap-1" role="group" aria-label="Filter by severity">
        {BUTTONS.map(({ label, value }) => (
          <button
            key={value}
            onClick={() => onSeverityChange(value)}
            aria-pressed={severityFilter === value}
            className={`rounded px-3 py-1 text-sm font-medium transition-colors ${
              severityFilter === value
                ? "bg-indigo-600 text-white"
                : "bg-slate-700 text-slate-300 hover:bg-slate-600"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      <input
        type="search"
        placeholder="Search IP or signature…"
        value={searchText}
        onChange={(e) => onSearchChange(e.target.value)}
        className="flex-1 min-w-48 rounded bg-slate-700 border border-slate-600 px-3 py-1 text-sm text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
        aria-label="Search alerts"
      />
    </div>
  );
}
