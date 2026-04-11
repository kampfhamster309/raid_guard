export type Severity = "info" | "warning" | "critical";

export interface Alert {
  id: string;
  timestamp: string;
  src_ip: string;
  dst_ip: string | null;
  src_port: number | null;
  dst_port: number | null;
  proto: string | null;
  signature: string | null;
  signature_id: number | null;
  category: string | null;
  severity: Severity;
  raw_json: Record<string, unknown> | null;
}

export type WsStatus = "connecting" | "connected" | "disconnected";

export interface HourlyCount {
  hour: string;
  count: number;
}

export interface TopItem {
  name: string;
  count: number;
}

export interface Stats {
  total_alerts_24h: number;
  alerts_per_hour: HourlyCount[];
  top_src_ips: TopItem[];
  top_signatures: TopItem[];
}

export interface RuleCategory {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
}

export interface HaSettings {
  enabled: boolean;
  configured: boolean;
}
