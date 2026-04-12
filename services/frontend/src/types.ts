export type Severity = "info" | "warning" | "critical";

export interface AlertEnrichment {
  summary: string;
  severity_reasoning: string;
  recommended_action: string;
}

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
  enrichment_json: AlertEnrichment | null;
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

export interface LlmSettings {
  url: string;
  model: string;
  timeout: number;
  max_tokens: number;
}

export type RiskLevel = "low" | "medium" | "high" | "critical";

export interface Incident {
  id: string;
  created_at: string;
  period_start: string;
  period_end: string;
  alert_ids: string[];
  narrative: string | null;
  risk_level: RiskLevel;
  name: string | null;
}

export interface IncidentDetail extends Incident {
  alerts: Alert[];
}
