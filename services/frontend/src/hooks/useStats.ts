import { useCallback, useEffect, useState } from "react";
import { fetchStats } from "../api";
import type { Stats } from "../types";

const POLL_INTERVAL_MS = 30_000;

interface UseStatsResult {
  stats: Stats | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useStats(): UseStatsResult {
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await fetchStats();
      setStats(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load stats");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const interval = setInterval(() => void load(), POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [load]);

  return { stats, loading, error, refresh: load };
}
