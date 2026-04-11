import { useCallback, useEffect, useRef, useState } from "react";
import { fetchAlerts } from "../api";
import type { Alert, Severity, WsStatus } from "../types";
import { useWebSocket } from "./useWebSocket";

interface UseAlertsOptions {
  severityFilter: Severity | "all";
  searchText: string;
}

interface UseAlertsResult {
  alerts: Alert[];
  filteredAlerts: Alert[];
  loading: boolean;
  error: string | null;
  wsStatus: WsStatus;
  refresh: () => void;
}

export function useAlerts({
  severityFilter,
  searchText,
}: UseAlertsOptions): UseAlertsResult {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const seenIds = useRef(new Set<string>());

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchAlerts({ limit: 100 });
      seenIds.current = new Set(data.map((a) => a.id));
      setAlerts(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load alerts");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleMessage = useCallback((data: string) => {
    try {
      const alert = JSON.parse(data) as Alert;
      if (seenIds.current.has(alert.id)) return;
      seenIds.current.add(alert.id);
      setAlerts((prev) => [alert, ...prev]);
    } catch {
      // ignore malformed messages
    }
  }, []);

  const wsStatus = useWebSocket({ onMessage: handleMessage, enabled: !loading });

  const filteredAlerts = alerts.filter((a) => {
    if (severityFilter !== "all" && a.severity !== severityFilter) return false;
    if (searchText) {
      const q = searchText.toLowerCase();
      return (
        a.src_ip.toLowerCase().includes(q) ||
        (a.dst_ip?.toLowerCase().includes(q) ?? false) ||
        (a.signature?.toLowerCase().includes(q) ?? false)
      );
    }
    return true;
  });

  return { alerts, filteredAlerts, loading, error, wsStatus, refresh: load };
}
