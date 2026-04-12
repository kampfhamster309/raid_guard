import { useEffect, useState } from "react";
import { fetchDigest, fetchDigests, generateDigest } from "../api";
import type { Digest, RiskLevel } from "../types";
import { DigestDrawer } from "./DigestDrawer";
import { RiskBadge } from "./RiskBadge";

const PAGE_SIZE = 10;

const VALID_RISK_LEVELS: RiskLevel[] = ["low", "medium", "high", "critical"];
function isRiskLevel(v: string | null | undefined): v is RiskLevel {
  return v != null && VALID_RISK_LEVELS.includes(v as RiskLevel);
}

export function DigestsPage() {
  const [digests, setDigests] = useState<Digest[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedDigest, setSelectedDigest] = useState<Digest | null>(null);
  const [drawerLoading, setDrawerLoading] = useState(false);

  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);

  const load = (o: number) => {
    setLoading(true);
    setError(null);
    fetchDigests({ limit: PAGE_SIZE, offset: o })
      .then((data) => {
        setDigests(data.items);
        setTotal(data.total);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load digests"))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load(offset);
  }, [offset]);

  const openDigest = async (id: string) => {
    setDrawerLoading(true);
    try {
      const detail = await fetchDigest(id);
      setSelectedDigest(detail);
    } catch {
      // swallow — drawer stays closed
    } finally {
      setDrawerLoading(false);
    }
  };

  const handleGenerate = async () => {
    setGenerating(true);
    setGenerateError(null);
    try {
      const result = await generateDigest();
      if (result === null) {
        setGenerateError("Not enough alerts in the current period to generate a digest.");
      } else {
        // Refresh the list and show the new digest
        setOffset(0);
        load(0);
        setSelectedDigest(result);
      }
    } catch (e) {
      setGenerateError(e instanceof Error ? e.message : "Digest generation failed");
    } finally {
      setGenerating(false);
    }
  };

  const totalPages = Math.ceil(total / PAGE_SIZE);
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-700 flex items-center justify-between">
        <div>
          <h1 className="text-sm font-semibold text-slate-200">Security Digests</h1>
          <p className="text-xs text-slate-400 mt-0.5">
            AI-generated summaries of network activity
          </p>
        </div>
        <div className="flex items-center gap-3">
          {drawerLoading && <span className="text-xs text-slate-400">Loading…</span>}
          <button
            onClick={handleGenerate}
            disabled={generating}
            className="px-3 py-1.5 text-xs font-medium rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {generating ? "Generating…" : "Generate Now"}
          </button>
        </div>
      </div>

      {generateError && (
        <div className="px-4 py-2 bg-amber-900/30 border-b border-amber-700/50 text-amber-300 text-xs">
          {generateError}
        </div>
      )}

      {loading && (
        <div className="flex-1 flex items-center justify-center text-slate-400 text-sm">
          Loading digests…
        </div>
      )}

      {error && !loading && (
        <div className="flex-1 flex items-center justify-center text-red-400 text-sm">
          {error}
        </div>
      )}

      {!loading && !error && digests.length === 0 && (
        <div className="flex-1 flex flex-col items-center justify-center text-slate-500 gap-2">
          <p className="text-sm">No digests generated yet.</p>
          <p className="text-xs">
            Digests are generated automatically every 24 hours, or you can trigger one manually.
          </p>
        </div>
      )}

      {!loading && !error && digests.length > 0 && (
        <>
          <div className="flex-1 overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-slate-800 text-slate-400 text-xs uppercase">
                <tr>
                  <th className="px-4 py-2 text-left font-medium">Generated</th>
                  <th className="px-4 py-2 text-left font-medium">Risk</th>
                  <th className="px-4 py-2 text-left font-medium hidden md:table-cell">Period</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/50">
                {digests.map((d) => (
                  <tr
                    key={d.id}
                    onClick={() => openDigest(d.id)}
                    className="hover:bg-slate-800/60 cursor-pointer transition-colors"
                  >
                    <td className="px-4 py-3 text-slate-200">
                      {new Date(d.created_at).toLocaleString()}
                    </td>
                    <td className="px-4 py-3">
                      {isRiskLevel(d.risk_level) ? (
                        <RiskBadge level={d.risk_level} />
                      ) : (
                        <span className="text-slate-500 text-xs">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-slate-400 text-xs hidden md:table-cell">
                      {new Date(d.period_start).toLocaleString()} –{" "}
                      {new Date(d.period_end).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-between px-4 py-3 border-t border-slate-700 text-xs text-slate-400">
              <span>
                {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
              </span>
              <div className="flex gap-2">
                <button
                  onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                  disabled={offset === 0}
                  className="px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-40"
                >
                  Previous
                </button>
                <span>
                  {currentPage} / {totalPages}
                </span>
                <button
                  onClick={() => setOffset(offset + PAGE_SIZE)}
                  disabled={offset + PAGE_SIZE >= total}
                  className="px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-40"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      )}

      <DigestDrawer
        digest={selectedDigest}
        onClose={() => setSelectedDigest(null)}
      />
    </div>
  );
}
