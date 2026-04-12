import { useEffect, useState } from "react";
import { fetchHaSettings, fetchLlmSettings, fetchPiholeSettings, testHaSend, testLlm, updateHaSettings, updateLlmSettings, updatePiholeSettings } from "../api";
import { useRules } from "../hooks/useRules";
import type { HaSettings, LlmSettings, PiholeSettings } from "../types";
import { TuningSuggestionsSection } from "./TuningSuggestionsSection";

type TestStatus = "idle" | "sending" | "success" | "error";

export function ConfigPage() {
  const { categories, loading, error, reloadStatus, reloadMessage, toggleCategory, reload } =
    useRules();

  // ── LLM settings ──────────────────────────────────────────────────────────
  const [llmSettings, setLlmSettings] = useState<LlmSettings | null>(null);
  const [llmDraft, setLlmDraft] = useState<LlmSettings | null>(null);
  const [llmSaveStatus, setLlmSaveStatus] = useState<"idle" | "saving" | "success" | "error">("idle");
  const [llmSaveMessage, setLlmSaveMessage] = useState<string | null>(null);
  const [llmTestStatus, setLlmTestStatus] = useState<"idle" | "testing" | "success" | "error">("idle");
  const [llmTestContent, setLlmTestContent] = useState<string | null>(null);

  useEffect(() => {
    fetchLlmSettings()
      .then((s) => { setLlmSettings(s); setLlmDraft(s); })
      .catch(() => {});
  }, []);

  const saveLlm = async () => {
    if (!llmDraft) return;
    setLlmSaveStatus("saving");
    setLlmSaveMessage(null);
    try {
      const updated = await updateLlmSettings(llmDraft);
      setLlmSettings(updated);
      setLlmDraft(updated);
      setLlmSaveStatus("success");
      setLlmSaveMessage("Settings saved. Restart the backend container for the enricher to pick up the new config.");
    } catch (e) {
      setLlmSaveStatus("error");
      setLlmSaveMessage(e instanceof Error ? e.message : "Save failed");
    }
  };

  const runLlmTest = async () => {
    setLlmTestStatus("testing");
    setLlmTestContent(null);
    try {
      const { content } = await testLlm();
      setLlmTestStatus("success");
      // Pretty-print if valid JSON, otherwise show raw
      try {
        setLlmTestContent(JSON.stringify(JSON.parse(content), null, 2));
      } catch {
        setLlmTestContent(content);
      }
    } catch (e) {
      setLlmTestStatus("error");
      setLlmTestContent(e instanceof Error ? e.message : "Test failed");
    }
  };

  // ── Pi-hole settings ───────────────────────────────────────────────────────
  const [piholeSettings, setPiholeSettings] = useState<PiholeSettings | null>(null);
  const [piholeDraft, setPiholeDraft] = useState<{ url: string; password: string } | null>(null);
  const [piholeSaveStatus, setPiholeSaveStatus] = useState<"idle" | "saving" | "success" | "error">("idle");
  const [piholeSaveMessage, setPiholeSaveMessage] = useState<string | null>(null);

  useEffect(() => {
    fetchPiholeSettings()
      .then((s) => {
        setPiholeSettings(s);
        setPiholeDraft({ url: s.url, password: "" });
      })
      .catch(() => {});
  }, []);

  const savePihole = async () => {
    if (!piholeDraft || !piholeSettings) return;
    setPiholeSaveStatus("saving");
    setPiholeSaveMessage(null);
    try {
      const updated = await updatePiholeSettings({
        url: piholeDraft.url,
        enabled: piholeSettings.enabled,
        password: piholeDraft.password,
      });
      setPiholeSettings(updated);
      setPiholeDraft((d) => d ? { ...d, password: "" } : d);
      setPiholeSaveStatus("success");
      setPiholeSaveMessage("Pi-hole settings saved.");
    } catch (e) {
      setPiholeSaveStatus("error");
      setPiholeSaveMessage(e instanceof Error ? e.message : "Save failed");
    }
  };

  const togglePihole = async () => {
    if (!piholeSettings || !piholeDraft) return;
    try {
      const updated = await updatePiholeSettings({
        url: piholeSettings.url,
        enabled: !piholeSettings.enabled,
        password: "",
      });
      setPiholeSettings(updated);
    } catch {
      // leave state unchanged
    }
  };

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

        {/* ── AI Enrichment ──────────────────────────────────────────────── */}
        <section>
          <div className="mb-4">
            <h2 className="text-lg font-semibold text-slate-100">AI Enrichment</h2>
            <p className="text-sm text-slate-400 mt-0.5">
              LM Studio connection settings for per-alert AI analysis. Save changes, then restart the backend container for the enricher to use the new config.
            </p>
          </div>

          <div className="rounded-lg border border-slate-700 p-4 space-y-4">
            {llmDraft === null ? (
              <p className="text-slate-400 text-sm">Loading…</p>
            ) : (
              <>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div className="sm:col-span-2">
                    <label className="block text-xs text-slate-400 mb-1">LM Studio base URL</label>
                    <input
                      type="text"
                      value={llmDraft.url}
                      onChange={(e) => setLlmDraft({ ...llmDraft, url: e.target.value })}
                      placeholder="http://192.168.1.x:1234/v1"
                      className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    />
                  </div>
                  <div className="sm:col-span-2">
                    <label className="block text-xs text-slate-400 mb-1">Model name</label>
                    <input
                      type="text"
                      value={llmDraft.model}
                      onChange={(e) => setLlmDraft({ ...llmDraft, model: e.target.value })}
                      placeholder="gemma-4-27b"
                      className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-slate-400 mb-1">Request timeout (seconds)</label>
                    <input
                      type="number"
                      min={1}
                      max={600}
                      value={llmDraft.timeout}
                      onChange={(e) => setLlmDraft({ ...llmDraft, timeout: Number(e.target.value) })}
                      className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-slate-400 mb-1">Max response tokens</label>
                    <input
                      type="number"
                      min={64}
                      max={4096}
                      value={llmDraft.max_tokens}
                      onChange={(e) => setLlmDraft({ ...llmDraft, max_tokens: Number(e.target.value) })}
                      className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    />
                  </div>
                </div>

                <div className="flex items-center gap-3 pt-1">
                  <button
                    onClick={() => void saveLlm()}
                    disabled={llmSaveStatus === "saving"}
                    className="px-4 py-2 rounded text-sm font-medium bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-white"
                  >
                    {llmSaveStatus === "saving" ? "Saving…" : "Save"}
                  </button>
                  <button
                    onClick={() => void runLlmTest()}
                    disabled={llmTestStatus === "testing" || !llmSettings?.url || !llmSettings?.model}
                    className="px-4 py-2 rounded text-sm font-medium bg-slate-700 hover:bg-slate-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-slate-200"
                  >
                    {llmTestStatus === "testing" ? "Testing…" : "Send test prompt"}
                  </button>
                </div>

                {llmSaveMessage && (
                  <div
                    className={`rounded px-3 py-2 text-xs ${
                      llmSaveStatus === "success"
                        ? "bg-emerald-900/50 text-emerald-300 border border-emerald-700"
                        : "bg-red-900/50 text-red-300 border border-red-700"
                    }`}
                  >
                    {llmSaveMessage}
                  </div>
                )}

                {llmTestContent !== null && (
                  <div>
                    <p className="text-xs text-slate-400 mb-1">
                      {llmTestStatus === "success" ? "LLM response:" : "Error:"}
                    </p>
                    <pre
                      className={`rounded p-3 text-xs overflow-x-auto whitespace-pre-wrap break-all ${
                        llmTestStatus === "success"
                          ? "bg-slate-800 text-slate-300"
                          : "bg-red-900/30 text-red-300 border border-red-700"
                      }`}
                    >
                      {llmTestContent}
                    </pre>
                  </div>
                )}
              </>
            )}
          </div>
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

        {/* ── Pi-hole Sinkhole ───────────────────────────────────────────── */}
        <section>
          <div className="mb-4">
            <h2 className="text-lg font-semibold text-slate-100">Pi-hole Sinkhole</h2>
            <p className="text-sm text-slate-400 mt-0.5">
              DNS sinkhole via Pi-hole v6. Set the base URL and admin password, then
              use the Sinkhole tab to manage blocked domains.
            </p>
          </div>

          <div className="rounded-lg border border-slate-700 p-4 space-y-4">
            {piholeDraft === null ? (
              <p className="text-slate-400 text-sm">Loading…</p>
            ) : (
              <>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div className="sm:col-span-2">
                    <label className="block text-xs text-slate-400 mb-1">Pi-hole base URL</label>
                    <input
                      type="text"
                      value={piholeDraft.url}
                      onChange={(e) => setPiholeDraft({ ...piholeDraft, url: e.target.value })}
                      placeholder="http://192.168.178.3"
                      className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    />
                  </div>
                  <div className="sm:col-span-2">
                    <label className="block text-xs text-slate-400 mb-1">Admin password</label>
                    <input
                      type="password"
                      value={piholeDraft.password}
                      onChange={(e) => setPiholeDraft({ ...piholeDraft, password: e.target.value })}
                      placeholder={piholeSettings?.configured ? "leave blank to keep existing" : "enter password"}
                      className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    />
                  </div>
                </div>

                <div className="flex items-center justify-between pt-1">
                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => void savePihole()}
                      disabled={piholeSaveStatus === "saving"}
                      className="px-4 py-2 rounded text-sm font-medium bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-white"
                    >
                      {piholeSaveStatus === "saving" ? "Saving…" : "Save"}
                    </button>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-slate-400">
                      {piholeSettings?.enabled ? "Enabled" : "Disabled"}
                    </span>
                    <button
                      role="switch"
                      aria-checked={piholeSettings?.enabled ?? false}
                      aria-label="Pi-hole integration"
                      onClick={() => void togglePihole()}
                      disabled={!piholeSettings?.configured}
                      className={`relative inline-flex h-5 w-9 flex-shrink-0 rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 focus:ring-offset-slate-900 disabled:opacity-40 disabled:cursor-not-allowed ${
                        piholeSettings?.enabled && piholeSettings?.configured
                          ? "bg-indigo-600"
                          : "bg-slate-600"
                      }`}
                    >
                      <span
                        className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transform transition-transform mt-0.5 ${
                          piholeSettings?.enabled && piholeSettings?.configured
                            ? "translate-x-4"
                            : "translate-x-0.5"
                        }`}
                      />
                    </button>
                  </div>
                </div>

                {piholeSaveMessage && (
                  <div
                    className={`rounded px-3 py-2 text-xs ${
                      piholeSaveStatus === "success"
                        ? "bg-emerald-900/50 text-emerald-300 border border-emerald-700"
                        : "bg-red-900/50 text-red-300 border border-red-700"
                    }`}
                  >
                    {piholeSaveMessage}
                  </div>
                )}
              </>
            )}
          </div>
        </section>

        {/* ── Tuning Suggestions ─────────────────────────────────────────── */}
        <TuningSuggestionsSection />

      </div>
    </div>
  );
}
