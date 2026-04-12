import { useEffect, useState } from "react";
import {
  confirmSuggestion,
  dismissSuggestion,
  fetchTuningSuggestions,
  runTuner,
} from "../api";
import type { TuningAction, TuningSuggestion } from "../types";

// ── Action badge ──────────────────────────────────────────────────────────────

const ACTION_STYLES: Record<TuningAction, string> = {
  suppress:          "bg-red-900/60 text-red-300 border border-red-700",
  "threshold-adjust": "bg-amber-900/60 text-amber-300 border border-amber-700",
  keep:              "bg-emerald-900/60 text-emerald-300 border border-emerald-700",
};

const ACTION_LABELS: Record<TuningAction, string> = {
  suppress:          "Suppress",
  "threshold-adjust": "Threshold Adjust",
  keep:              "Keep",
};

function ActionBadge({ action }: { action: TuningAction }) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold ${ACTION_STYLES[action]}`}
    >
      {ACTION_LABELS[action]}
    </span>
  );
}

// ── Suggestion card ───────────────────────────────────────────────────────────

interface CardProps {
  suggestion: TuningSuggestion;
  onConfirm: (id: string) => Promise<void>;
  onDismiss: (id: string) => Promise<void>;
  busy: boolean;
}

function SuggestionCard({ suggestion: s, onConfirm, onDismiss, busy }: CardProps) {
  const canSuppress = s.action === "suppress" && s.signature_id != null;
  const confirmLabel =
    s.action === "suppress"
      ? canSuppress
        ? "Apply Suppression"
        : "Confirm (no sig_id)"
      : "Acknowledge";

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800/60 p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium text-slate-200 font-mono truncate">
            {s.signature}
          </p>
          <p className="text-xs text-slate-400 mt-0.5">
            {s.hit_count.toLocaleString()} hits in lookback window
            {s.signature_id != null && (
              <span className="ml-2 opacity-60">· sid:{s.signature_id}</span>
            )}
          </p>
        </div>
        <ActionBadge action={s.action} />
      </div>

      <p className="text-sm text-slate-300 leading-relaxed">{s.assessment}</p>

      <div className="flex gap-2 justify-end pt-1">
        <button
          onClick={() => void onDismiss(s.id)}
          disabled={busy}
          className="px-3 py-1.5 text-xs font-medium rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-slate-300"
        >
          Dismiss
        </button>
        {s.action !== "keep" && (
          <button
            onClick={() => void onConfirm(s.id)}
            disabled={busy}
            className="px-3 py-1.5 text-xs font-medium rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-white"
          >
            {confirmLabel}
          </button>
        )}
      </div>
    </div>
  );
}

// ── Main section ──────────────────────────────────────────────────────────────

export function TuningSuggestionsSection() {
  const [suggestions, setSuggestions] = useState<TuningSuggestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [runMessage, setRunMessage] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    fetchTuningSuggestions()
      .then(setSuggestions)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load suggestions"))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  const handleConfirm = async (id: string) => {
    setBusyId(id);
    try {
      await confirmSuggestion(id);
      setSuggestions((prev) => prev.filter((s) => s.id !== id));
    } catch {
      // swallow — leave item in list
    } finally {
      setBusyId(null);
    }
  };

  const handleDismiss = async (id: string) => {
    setBusyId(id);
    try {
      await dismissSuggestion(id);
      setSuggestions((prev) => prev.filter((s) => s.id !== id));
    } catch {
      // swallow
    } finally {
      setBusyId(null);
    }
  };

  const handleRun = async () => {
    setRunning(true);
    setRunMessage(null);
    setRunError(null);
    try {
      const newSugs = await runTuner();
      if (newSugs.length === 0) {
        setRunMessage(
          "Analysis complete — no new suggestions. This can mean there are no noisy signatures, or all noisy signatures already have pending suggestions."
        );
      } else {
        setRunMessage(`Created ${newSugs.length} new suggestion${newSugs.length > 1 ? "s" : ""}.`);
        load();
      }
    } catch (e) {
      setRunError(e instanceof Error ? e.message : "Analysis failed");
    } finally {
      setRunning(false);
    }
  };

  return (
    <section>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-100">Tuning Suggestions</h2>
          <p className="text-sm text-slate-400 mt-0.5">
            AI-generated recommendations for suppressing or adjusting noisy signatures.
            Runs weekly after 7+ days of alert history.
          </p>
        </div>
        <button
          onClick={() => void handleRun()}
          disabled={running}
          className="px-4 py-2 rounded text-sm font-medium bg-slate-700 hover:bg-slate-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-slate-200"
        >
          {running ? "Analysing…" : "Run Analysis"}
        </button>
      </div>

      {runMessage && (
        <div className="mb-4 rounded px-4 py-3 text-sm bg-emerald-900/40 text-emerald-300 border border-emerald-700">
          {runMessage}
        </div>
      )}
      {runError && (
        <div className="mb-4 rounded px-4 py-3 text-sm bg-red-900/40 text-red-300 border border-red-700">
          {runError}
        </div>
      )}

      {loading && (
        <p className="text-slate-400 text-sm">Loading suggestions…</p>
      )}
      {error && !loading && (
        <p className="text-red-400 text-sm">{error}</p>
      )}

      {!loading && !error && suggestions.length === 0 && (
        <div className="rounded-lg border border-slate-700 px-4 py-6 text-center text-slate-500 text-sm">
          <p>No pending suggestions.</p>
          <p className="text-xs mt-1">
            The tuner runs weekly once 7+ days of alert history are available.
            Use "Run Analysis" to trigger it manually.
          </p>
        </div>
      )}

      {!loading && !error && suggestions.length > 0 && (
        <div className="space-y-3">
          {suggestions.map((s) => (
            <SuggestionCard
              key={s.id}
              suggestion={s}
              onConfirm={handleConfirm}
              onDismiss={handleDismiss}
              busy={busyId === s.id}
            />
          ))}
        </div>
      )}
    </section>
  );
}
