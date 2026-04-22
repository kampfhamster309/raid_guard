import { useEffect, useState } from "react";
import {
  confirmSuggestion,
  dismissSuggestion,
  fetchTuningSuggestions,
  runTuner,
} from "../api";
import type { ThresholdParams } from "../api";
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
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold ${ACTION_STYLES[action]}`}>
      {ACTION_LABELS[action]}
    </span>
  );
}

// ── Threshold form ────────────────────────────────────────────────────────────

interface ThresholdFormProps {
  suggestion: TuningSuggestion;
  onApply: (params: ThresholdParams) => Promise<void>;
  busy: boolean;
}

function ThresholdForm({ suggestion: s, onApply, busy }: ThresholdFormProps) {
  const [count,   setCount]   = useState(String(s.threshold_count   ?? 5));
  const [seconds, setSeconds] = useState(String(s.threshold_seconds ?? 60));
  const [track,   setTrack]   = useState(s.threshold_track ?? "by_src");
  const [type_,   setType]    = useState(s.threshold_type  ?? "limit");

  const handleApply = () => {
    void onApply({
      threshold_count:   Math.max(1, parseInt(count, 10) || 5),
      threshold_seconds: Math.max(1, parseInt(seconds, 10) || 60),
      threshold_track:   track,
      threshold_type:    type_,
    });
  };

  const inputCls = "w-full bg-slate-700 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-indigo-500";
  const labelCls = "block text-xs text-slate-400 mb-1";

  return (
    <div className="mt-3 rounded border border-amber-800/50 bg-slate-900/60 p-3 space-y-3">
      <p className="text-xs text-amber-300/80 font-medium">
        AI-suggested threshold parameters — review and adjust before applying:
      </p>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={labelCls}>Type</label>
          <select value={type_} onChange={e => setType(e.target.value)} className={inputCls} aria-label="Threshold type">
            <option value="limit">limit — cap alert rate</option>
            <option value="threshold">threshold — alert every N events</option>
            <option value="both">both</option>
          </select>
        </div>
        <div>
          <label className={labelCls}>Track by</label>
          <select value={track} onChange={e => setTrack(e.target.value)} className={inputCls} aria-label="Track by">
            <option value="by_src">by_src (source IP)</option>
            <option value="by_dst">by_dst (dest IP)</option>
          </select>
        </div>
        <div>
          <label className={labelCls}>Count</label>
          <input
            type="number"
            min={1}
            value={count}
            onChange={e => setCount(e.target.value)}
            className={inputCls}
            aria-label="Threshold count"
          />
        </div>
        <div>
          <label className={labelCls}>Seconds</label>
          <input
            type="number"
            min={1}
            value={seconds}
            onChange={e => setSeconds(e.target.value)}
            className={inputCls}
            aria-label="Threshold seconds"
          />
        </div>
      </div>
      <p className="text-xs text-slate-500">
        Result: alert <em>{type_ === "limit" ? "at most" : "once per"}</em> {count || "?"} time{Number(count) !== 1 ? "s" : ""} per {seconds || "?"}s per {track === "by_src" ? "source" : "dest"} IP
      </p>
      <div className="flex justify-end">
        <button
          onClick={handleApply}
          disabled={busy}
          className="px-3 py-1.5 text-xs font-medium rounded bg-amber-700 hover:bg-amber-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-white"
          aria-label="Apply threshold"
        >
          {busy ? "Applying…" : "Apply Threshold"}
        </button>
      </div>
    </div>
  );
}

// ── Suggestion card ───────────────────────────────────────────────────────────

interface CardProps {
  suggestion: TuningSuggestion;
  onConfirm: (id: string, params?: ThresholdParams) => Promise<void>;
  onDismiss: (id: string) => Promise<void>;
  busy: boolean;
}

function SuggestionCard({ suggestion: s, onConfirm, onDismiss, busy }: CardProps) {
  const isThreshold = s.action === "threshold-adjust";
  const canSuppress = s.action === "suppress" && s.signature_id != null;

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

      {/* Threshold form — shown inline for threshold-adjust suggestions */}
      {isThreshold && s.signature_id != null && (
        <ThresholdForm
          suggestion={s}
          onApply={(params) => onConfirm(s.id, params)}
          busy={busy}
        />
      )}

      <div className="flex gap-2 justify-end pt-1">
        <button
          onClick={() => void onDismiss(s.id)}
          disabled={busy}
          className="px-3 py-1.5 text-xs font-medium rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-slate-300"
        >
          Dismiss
        </button>
        {/* Suppress: one-click apply. Keep: no confirm button. Threshold: handled by form above. */}
        {s.action === "suppress" && (
          <button
            onClick={() => void onConfirm(s.id)}
            disabled={busy}
            className="px-3 py-1.5 text-xs font-medium rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-white"
          >
            {canSuppress ? "Apply Suppression" : "Confirm (no sig_id)"}
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

  const handleConfirm = async (id: string, params?: ThresholdParams) => {
    setBusyId(id);
    try {
      await confirmSuggestion(id, params);
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
