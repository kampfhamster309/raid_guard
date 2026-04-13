import type { Alert, BlockedDomain, Digest, FritzBlockedDevice, FritzStatus, HaSettings, Incident, IncidentDetail, LlmSettings, PiholeSettings, RuleCategory, Stats, TuningSuggestion } from "./types";

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

// ── Rules API ─────────────────────────────────────────────────────────────────

async function authFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const res = await fetch(url, { ...init, headers: { ...authHeaders(), ...(init.headers as Record<string, string> ?? {}) } });
  if (res.status === 401) { clearToken(); window.location.reload(); throw new Error("Unauthorized"); }
  if (!res.ok) throw new Error(`${init.method ?? "GET"} ${url} failed: ${res.status}`);
  return res;
}

export async function fetchRuleCategories(): Promise<RuleCategory[]> {
  const res = await authFetch("/api/rules/categories");
  const data = (await res.json()) as { categories: RuleCategory[] };
  return data.categories;
}

export async function updateRuleCategories(disabled: string[]): Promise<RuleCategory[]> {
  const res = await authFetch("/api/rules/categories", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ disabled }),
  });
  const data = (await res.json()) as { categories: RuleCategory[] };
  return data.categories;
}

export async function reloadSuricata(): Promise<string> {
  const res = await authFetch("/api/rules/reload", { method: "POST" });
  const data = (await res.json()) as { message: string };
  return data.message;
}

// ── Home Assistant API ────────────────────────────────────────────────────────

export async function fetchHaSettings(): Promise<HaSettings> {
  const res = await authFetch("/api/settings/ha");
  return res.json() as Promise<HaSettings>;
}

export async function updateHaSettings(enabled: boolean): Promise<HaSettings> {
  const res = await authFetch("/api/settings/ha", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  return res.json() as Promise<HaSettings>;
}

export async function testHaSend(): Promise<void> {
  await authFetch("/api/settings/ha/test", { method: "POST" });
}

// ── LLM settings API ──────────────────────────────────────────────────────────

export async function fetchLlmSettings(): Promise<LlmSettings> {
  const res = await authFetch("/api/settings/llm");
  return res.json() as Promise<LlmSettings>;
}

export async function updateLlmSettings(settings: LlmSettings): Promise<LlmSettings> {
  const res = await authFetch("/api/settings/llm", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
  return res.json() as Promise<LlmSettings>;
}

export async function testLlm(): Promise<{ content: string }> {
  const res = await authFetch("/api/settings/llm/test", { method: "POST" });
  return res.json() as Promise<{ content: string }>;
}

// ── Incidents API ─────────────────────────────────────────────────────────────

export async function fetchIncidents(params: { limit?: number; offset?: number } = {}): Promise<{
  items: Incident[];
  total: number;
  limit: number;
  offset: number;
}> {
  const qs = new URLSearchParams();
  if (params.limit != null) qs.set("limit", String(params.limit));
  if (params.offset != null) qs.set("offset", String(params.offset));
  const res = await authFetch(`/api/incidents?${qs}`);
  return res.json();
}

export async function fetchIncident(id: string): Promise<IncidentDetail> {
  const res = await authFetch(`/api/incidents/${id}`);
  return res.json() as Promise<IncidentDetail>;
}

// ── Digests API ───────────────────────────────────────────────────────────────

export async function fetchDigests(params: { limit?: number; offset?: number } = {}): Promise<{
  items: Digest[];
  total: number;
  limit: number;
  offset: number;
}> {
  const qs = new URLSearchParams();
  if (params.limit != null) qs.set("limit", String(params.limit));
  if (params.offset != null) qs.set("offset", String(params.offset));
  const res = await authFetch(`/api/digests?${qs}`);
  return res.json();
}

export async function fetchDigest(id: string): Promise<Digest> {
  const res = await authFetch(`/api/digests/${id}`);
  return res.json() as Promise<Digest>;
}

export async function generateDigest(): Promise<Digest | null> {
  const res = await fetch("/api/digests/generate", {
    method: "POST",
    headers: authHeaders(),
  });
  if (res.status === 401) { clearToken(); window.location.reload(); throw new Error("Unauthorized"); }
  if (res.status === 204) return null;
  if (res.status === 422) {
    const data = (await res.json()) as { detail: string };
    throw new Error(data.detail ?? "LLM not configured");
  }
  if (!res.ok) throw new Error(`POST /api/digests/generate failed: ${res.status}`);
  return res.json() as Promise<Digest>;
}

// ── Pi-hole API ───────────────────────────────────────────────────────────────

export async function fetchPiholeSettings(): Promise<PiholeSettings> {
  const res = await authFetch("/api/pihole/settings");
  return res.json() as Promise<PiholeSettings>;
}

export interface UpdatePiholeSettingsParams {
  url: string;
  enabled: boolean;
  password: string;
}

export async function updatePiholeSettings(params: UpdatePiholeSettingsParams): Promise<PiholeSettings> {
  const res = await authFetch("/api/pihole/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  return res.json() as Promise<PiholeSettings>;
}

export async function fetchBlocklist(): Promise<BlockedDomain[]> {
  const res = await authFetch("/api/pihole/blocklist");
  return res.json() as Promise<BlockedDomain[]>;
}

export async function blockDomain(domain: string, comment?: string): Promise<BlockedDomain> {
  const res = await authFetch("/api/pihole/block", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ domain, comment: comment ?? "Blocked by raid_guard" }),
  });
  return res.json() as Promise<BlockedDomain>;
}

export async function unblockDomain(domain: string): Promise<void> {
  await authFetch(`/api/pihole/block/${encodeURIComponent(domain)}`, { method: "DELETE" });
}

// ── Fritzbox quarantine API ───────────────────────────────────────────────────

export async function fetchFritzStatus(): Promise<FritzStatus> {
  const res = await authFetch("/api/fritz/status");
  return res.json() as Promise<FritzStatus>;
}

export async function fetchFritzBlocked(): Promise<FritzBlockedDevice[]> {
  const res = await authFetch("/api/fritz/blocked");
  return res.json() as Promise<FritzBlockedDevice[]>;
}

export async function blockFritzDevice(ip: string, comment?: string): Promise<FritzBlockedDevice> {
  const res = await authFetch("/api/fritz/block", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ip, comment: comment ?? "" }),
  });
  return res.json() as Promise<FritzBlockedDevice>;
}

export async function unblockFritzDevice(ip: string): Promise<void> {
  await authFetch(`/api/fritz/block/${encodeURIComponent(ip)}`, { method: "DELETE" });
}

// ── Tuning API ────────────────────────────────────────────────────────────────

export async function fetchTuningSuggestions(): Promise<TuningSuggestion[]> {
  const res = await authFetch("/api/tuning");
  return res.json() as Promise<TuningSuggestion[]>;
}

export async function confirmSuggestion(id: string): Promise<TuningSuggestion> {
  const res = await authFetch(`/api/tuning/${id}/confirm`, { method: "POST" });
  return res.json() as Promise<TuningSuggestion>;
}

export async function dismissSuggestion(id: string): Promise<TuningSuggestion> {
  const res = await authFetch(`/api/tuning/${id}/dismiss`, { method: "POST" });
  return res.json() as Promise<TuningSuggestion>;
}

export async function runTuner(): Promise<TuningSuggestion[]> {
  const res = await fetch("/api/tuning/run", {
    method: "POST",
    headers: authHeaders(),
  });
  if (res.status === 401) { clearToken(); window.location.reload(); throw new Error("Unauthorized"); }
  if (res.status === 422) {
    const data = (await res.json()) as { detail: string };
    throw new Error(data.detail ?? "LLM not configured");
  }
  if (!res.ok) throw new Error(`POST /api/tuning/run failed: ${res.status}`);
  return res.json() as Promise<TuningSuggestion[]>;
}

export function createAlertWebSocket(token: string): WebSocket {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const host = window.location.host;
  return new WebSocket(`${proto}://${host}/ws/alerts?token=${token}`);
}
