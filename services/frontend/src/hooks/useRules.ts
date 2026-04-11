import { useCallback, useEffect, useState } from "react";
import { fetchRuleCategories, updateRuleCategories, reloadSuricata } from "../api";
import type { RuleCategory } from "../types";

type ReloadStatus = "idle" | "reloading" | "success" | "error";

interface UseRulesResult {
  categories: RuleCategory[];
  loading: boolean;
  error: string | null;
  reloadStatus: ReloadStatus;
  reloadMessage: string | null;
  toggleCategory: (id: string) => Promise<void>;
  reload: () => Promise<void>;
}

export function useRules(): UseRulesResult {
  const [categories, setCategories] = useState<RuleCategory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadStatus, setReloadStatus] = useState<ReloadStatus>("idle");
  const [reloadMessage, setReloadMessage] = useState<string | null>(null);

  useEffect(() => {
    fetchRuleCategories()
      .then(setCategories)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load rules"))
      .finally(() => setLoading(false));
  }, []);

  const toggleCategory = useCallback(async (id: string) => {
    const current = categories.find((c) => c.id === id);
    if (!current) return;

    const newDisabled = categories
      .filter((c) => (c.id === id ? current.enabled : !c.enabled))
      .map((c) => c.id);

    try {
      const updated = await updateRuleCategories(newDisabled);
      setCategories(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update categories");
    }
  }, [categories]);

  const reload = useCallback(async () => {
    setReloadStatus("reloading");
    setReloadMessage(null);
    try {
      const msg = await reloadSuricata();
      setReloadStatus("success");
      setReloadMessage(msg);
    } catch (e) {
      setReloadStatus("error");
      setReloadMessage(e instanceof Error ? e.message : "Reload failed");
    }
  }, []);

  return { categories, loading, error, reloadStatus, reloadMessage, toggleCategory, reload };
}
