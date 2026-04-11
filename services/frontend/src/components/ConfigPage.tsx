import { useEffect, useState } from "react";
import { fetchHaSettings, updateHaSettings, testHaSend } from "../api";
import { useRules } from "../hooks/useRules";
import type { HaSettings } from "../types";

type TestStatus = "idle" | "sending" | "success" | "error";

export function ConfigPage() {
  const { categories, loading, error, reloadStatus, reloadMessage, toggleCategory, reload } =
    useRules();

  // ── Home Assistant settings ────────────────────────────────────────────────
  const [haSettings, setHaSettings] = useState<HaSettings | null>(null);
  const [haLoading, setHaLoading] = useState(true);
  const [testStatus, setTestStatus] = useState<TestStatus>("idle");
  const [testMessage, setTestMessage] = useState<string | null>(null);

  useEffect(() => {
    fetchHaSettings()
      .then(setHaSettings)
      .catch(() => {})
      .finally(() => setHaLoading(false));
  }, []);

  const toggleHa = async () => {
    if (!haSettings) return;
    try {
      const updated = await updateHaSettings(!haSettings.enabled);
      setHaSettings(updated);
    } catch {
      // leave state unchanged on error
    }
  };

  const sendTest = async () => {
    setTestStatus("sending");
    setTestMessage(null);
    try {
      await testHaSend();
      setTestStatus("success");
      setTestMessage("Test notification sent.");
    } catch (e) {
      setTestStatus("error");
      setTestMessage(e instanceof Error ? e.message : "Test failed");
    }
  };

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="max-w-3xl mx-auto space-y-6">

        {/* ── Rule Categories ────────────────────────────────────────────── */}
        <section>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-100">Rule Categories</h2>
              <p className="text-sm text-slate-400 mt-0.5">
                Toggle ET Open rule categories. Click <span className="font-medium text-slate-300">Reload Suricata</span> to apply changes to the running engine.
              </p>
            </div>
            <button
              onClick={reload}
              disabled={reloadStatus === "reloading"}
              className="px-4 py-2 rounded text-sm font-medium bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-white"
            >
              {reloadStatus === "reloading" ? "Reloading…" : "Reload Suricata"}
            </button>
          </div>

          {reloadMessage && (
            <div
              className={`mb-4 rounded px-4 py-3 text-sm ${
                reloadStatus === "success"
                  ? "bg-emerald-900/50 text-emerald-300 border border-emerald-700"
                  : "bg-red-900/50 text-red-300 border border-red-700"
              }`}
            >
              {reloadMessage}
            </div>
          )}

          {loading && (
            <p className="text-slate-400 text-sm">Loading categories…</p>
          )}
          {error && (
            <p className="text-red-400 text-sm">{error}</p>
          )}

          {!loading && !error && (
            <div className="rounded-lg border border-slate-700 divide-y divide-slate-700">
              {categories.map((cat) => (
                <div
                  key={cat.id}
                  className="flex items-center justify-between px-4 py-3 hover:bg-slate-800/50 transition-colors"
                >
                  <div className="min-w-0 pr-4">
                    <p className="text-sm font-medium text-slate-200">{cat.name}</p>
                    <p className="text-xs text-slate-400 mt-0.5 truncate">{cat.description}</p>
                  </div>
                  <button
                    role="switch"
                    aria-checked={cat.enabled}
                    onClick={() => void toggleCategory(cat.id)}
                    className={`relative inline-flex h-5 w-9 flex-shrink-0 rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 focus:ring-offset-slate-900 ${
                      cat.enabled ? "bg-indigo-600" : "bg-slate-600"
                    }`}
                  >
                    <span
                      className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transform transition-transform mt-0.5 ${
                        cat.enabled ? "translate-x-4" : "translate-x-0.5"
                      }`}
                    />
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* ── Notifications ──────────────────────────────────────────────── */}
        <section>
          <div className="mb-4">
            <h2 className="text-lg font-semibold text-slate-100">Notifications</h2>
            <p className="text-sm text-slate-400 mt-0.5">
              Push alerts to external services. The severity threshold controls which alerts trigger a notification.
            </p>
          </div>

          <div className="rounded-lg border border-slate-700 divide-y divide-slate-700">
            {/* Home Assistant row */}
            <div className="px-4 py-4">
              <div className="flex items-center justify-between">
                <div className="min-w-0 pr-4">
                  <p className="text-sm font-medium text-slate-200">Home Assistant</p>
                  <p className="text-xs text-slate-400 mt-0.5">
                    {haLoading
                      ? "Loading…"
                      : haSettings?.configured
                      ? "Webhook configured — push alert to your HA automations."
                      : "HA_WEBHOOK_URL not set. Configure it in your .env to enable."}
                  </p>
                </div>
                <div className="flex items-center gap-3 flex-shrink-0">
                  {haSettings?.configured && (
                    <button
                      onClick={() => void sendTest()}
                      disabled={testStatus === "sending" || !haSettings?.configured}
                      className="px-3 py-1.5 rounded text-xs font-medium bg-slate-700 hover:bg-slate-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-slate-200"
                    >
                      {testStatus === "sending" ? "Sending…" : "Send test"}
                    </button>
                  )}
                  <button
                    role="switch"
                    aria-checked={haSettings?.enabled ?? false}
                    aria-label="Home Assistant notifications"
                    onClick={() => void toggleHa()}
                    disabled={haLoading || !haSettings?.configured}
                    className={`relative inline-flex h-5 w-9 flex-shrink-0 rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 focus:ring-offset-slate-900 disabled:opacity-40 disabled:cursor-not-allowed ${
                      haSettings?.enabled && haSettings?.configured
                        ? "bg-indigo-600"
                        : "bg-slate-600"
                    }`}
                  >
                    <span
                      className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transform transition-transform mt-0.5 ${
                        haSettings?.enabled && haSettings?.configured
                          ? "translate-x-4"
                          : "translate-x-0.5"
                      }`}
                    />
                  </button>
                </div>
              </div>

              {testMessage && (
                <div
                  className={`mt-3 rounded px-3 py-2 text-xs ${
                    testStatus === "success"
                      ? "bg-emerald-900/50 text-emerald-300 border border-emerald-700"
                      : "bg-red-900/50 text-red-300 border border-red-700"
                  }`}
                >
                  {testMessage}
                </div>
              )}
            </div>
          </div>
        </section>

      </div>
    </div>
  );
}
