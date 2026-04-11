import type { Severity } from "../types";

const CLASSES: Record<Severity, string> = {
  critical: "bg-red-900 text-red-200 border border-red-700",
  warning: "bg-amber-900 text-amber-200 border border-amber-700",
  info: "bg-sky-900 text-sky-200 border border-sky-700",
};

interface Props {
  severity: Severity;
}

export function SeverityBadge({ severity }: Props) {
  return (
    <span
      className={`inline-block rounded px-2 py-0.5 text-xs font-semibold uppercase tracking-wide ${CLASSES[severity]}`}
    >
      {severity}
    </span>
  );
}
