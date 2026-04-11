import type { Alert, Stats } from "./types";

const TOKEN_KEY = "raid_guard_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function login(
  username: string,
  password: string
): Promise<string> {
  const body = new URLSearchParams({ username, password });
  const res = await fetch("/api/auth/token", {
    method: "POST",
    body,
  });
  if (!res.ok) {
    throw new Error("Invalid credentials");
  }
  const data = (await res.json()) as { access_token: string };
  return data.access_token;
}

export interface FetchAlertsParams {
  limit?: number;
  offset?: number;
  severity?: string;
  src_ip?: string;
  after?: string;
  before?: string;
}

export async function fetchAlerts(
  params: FetchAlertsParams = {}
): Promise<Alert[]> {
  const qs = new URLSearchParams();
  if (params.limit != null) qs.set("limit", String(params.limit));
  if (params.offset != null) qs.set("offset", String(params.offset));
  if (params.severity) qs.set("severity", params.severity);
  if (params.src_ip) qs.set("src_ip", params.src_ip);
  if (params.after) qs.set("after", params.after);
  if (params.before) qs.set("before", params.before);

  const res = await fetch(`/api/alerts?${qs}`, { headers: authHeaders() });
  if (res.status === 401) {
    clearToken();
    window.location.reload();
    throw new Error("Unauthorized");
  }
  if (!res.ok) throw new Error(`Failed to fetch alerts: ${res.status}`);
  const data = (await res.json()) as { items: Alert[] };
  return data.items;
}

export async function fetchAlert(id: string): Promise<Alert> {
  const res = await fetch(`/api/alerts/${id}`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`Failed to fetch alert ${id}: ${res.status}`);
  return res.json() as Promise<Alert>;
}

export async function fetchStats(): Promise<Stats> {
  const res = await fetch("/api/stats", { headers: authHeaders() });
  if (res.status === 401) {
    clearToken();
    window.location.reload();
    throw new Error("Unauthorized");
  }
  if (!res.ok) throw new Error(`Failed to fetch stats: ${res.status}`);
  return res.json() as Promise<Stats>;
}

export function createAlertWebSocket(token: string): WebSocket {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const host = window.location.host;
  return new WebSocket(`${proto}://${host}/ws/alerts?token=${token}`);
}
