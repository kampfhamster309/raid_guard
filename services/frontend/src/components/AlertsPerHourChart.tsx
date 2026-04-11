import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { HourlyCount } from "../types";

interface ChartPoint {
  label: string;
  count: number;
}

function buildChartData(rows: HourlyCount[]): ChartPoint[] {
  // Fill all 24 hours with 0, then overwrite with real counts.
  const now = new Date();
  const byHour = new Map<number, number>();
  for (const r of rows) {
    byHour.set(new Date(r.hour).getUTCHours(), r.count);
  }

  const points: ChartPoint[] = [];
  for (let i = 23; i >= 0; i--) {
    const d = new Date(now.getTime() - i * 3_600_000);
    const h = d.getUTCHours();
    points.push({
      label: `${String(h).padStart(2, "0")}:00`,
      count: byHour.get(h) ?? 0,
    });
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
          itemStyle={{ color: "#818cf8" }}
          cursor={{ fill: "rgba(99,102,241,0.1)" }}
        />
        <Bar dataKey="count" name="Alerts" fill="#6366f1" radius={[2, 2, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
