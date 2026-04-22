import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { HourlyCount } from "../types";

interface ChartPoint {
  label: string;
  info: number;
  warning: number;
  critical: number;
}

function buildChartData(rows: HourlyCount[]): ChartPoint[] {
  const now = new Date();
  const byHour = new Map<number, { info: number; warning: number; critical: number }>();
  for (const r of rows) {
    byHour.set(new Date(r.hour).getUTCHours(), {
      info: r.info,
      warning: r.warning,
      critical: r.critical,
    });
  }

  const points: ChartPoint[] = [];
  for (let i = 23; i >= 0; i--) {
    const d = new Date(now.getTime() - i * 3_600_000);
    const h = d.getUTCHours();
    const counts = byHour.get(h) ?? { info: 0, warning: 0, critical: 0 };
    points.push({ label: `${String(h).padStart(2, "0")}:00`, ...counts });
  }
  return points;
}

interface Props {
  data: HourlyCount[];
}

export function AlertsPerHourChart({ data }: Props) {
  const chartData = buildChartData(data);

  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={chartData} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
        <XAxis
          dataKey="label"
          tick={{ fill: "#94a3b8", fontSize: 11 }}
          interval={3}
          stroke="#475569"
        />
        <YAxis
          tick={{ fill: "#94a3b8", fontSize: 11 }}
          allowDecimals={false}
          stroke="#475569"
        />
        <Tooltip
          contentStyle={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 6 }}
          labelStyle={{ color: "#e2e8f0" }}
          cursor={{ fill: "rgba(99,102,241,0.1)" }}
        />
        <Legend
          wrapperStyle={{ fontSize: 12, color: "#94a3b8" }}
          formatter={(value) => value.charAt(0).toUpperCase() + value.slice(1)}
        />
        <Bar dataKey="info" name="info" stackId="a" fill="#38bdf8" radius={[0, 0, 0, 0]} />
        <Bar dataKey="warning" name="warning" stackId="a" fill="#f59e0b" radius={[0, 0, 0, 0]} />
        <Bar dataKey="critical" name="critical" stackId="a" fill="#ef4444" radius={[2, 2, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
