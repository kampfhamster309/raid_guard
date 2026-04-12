import { useEffect, useState } from "react";
import { blockDomain, fetchBlocklist, fetchPiholeSettings, unblockDomain } from "../api";
import type { BlockedDomain, PiholeSettings } from "../types";

function fmtDate(ts: number | null): string {
  if (ts == null) return "—";
  return new Date(ts * 1000).toLocaleString();
}

export function SinkholePage() {
  const [settings, setSettings] = useState<PiholeSettings | null>(null);
  const [settingsLoading, setSettingsLoading] = useState(true);

  const [domains, setDomains] = useState<BlockedDomain[]>([]);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);

  const [manualDomain, setManualDomain] = useState("");
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  const [removingId, setRemovingId] = useState<string | null>(null);

  const loadList = () => {
    setListLoading(true);
    setListError(null);
    fetchBlocklist()
      .then(setDomains)
      .catch((e) => setListError(e instanceof Error ? e.message : "Failed to load blocklist"))
      .finally(() => setListLoading(false));
  };

  useEffect(() => {
    fetchPiholeSettings()
      .then((s) => {
        setSettings(s);
        if (s.configured && s.enabled) loadList();
      })
      .catch(() => {})
      .finally(() => setSettingsLoading(false));
  }, []);

  const handleAdd = async () => {
    const domain = manualDomain.trim().toLowerCase();
    if (!domain) return;
    setAdding(true);
    setAddError(null);
    try {
      await blockDomain(domain);
      setManualDomain("");
      loadList();
    } catch (e) {
      setAddError(e instanceof Error ? e.message : "Block failed");
    } finally {
      setAdding(false);
    }
  };

  const handleRemove = async (domain: string) => {
    setRemovingId(domain);
    try {
      await unblockDomain(domain);
      setDomains((prev) => prev.filter((d) => d.domain !== domain));
    } catch {
      // leave list unchanged on error
    } finally {
      setRemovingId(null);
    }
  };

  const notConfigured = !settingsLoading && (!settings?.configured || !settings?.enabled);

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-700 flex items-center justify-between">
        <div>
          <h1 className="text-sm font-semibold text-slate-200">DNS Sinkhole</h1>
          <p className="text-xs text-slate-400 mt-0.5">
            Domains blocked via Pi-hole v6 exact deny list
          </p>
        </div>
        {settings?.configured && settings.enabled && (
          <button
            onClick={loadList}
            disabled={listLoading}
            className="px-3 py-1.5 text-xs font-medium rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-50 transition-colors text-slate-200"
          >
            {listLoading ? "Refreshing…" : "Refresh"}
          </button>
        )}
      </div>

      {settingsLoading && (
        <div className="flex-1 flex items-center justify-center text-slate-400 text-sm">
          Loading…
        </div>
      )}

      {notConfigured && (
        <div className="flex-1 flex flex-col items-center justify-center text-slate-500 gap-2">
          <p className="text-sm">Pi-hole integration is not configured or disabled.</p>
          <p className="text-xs">
            Set the Pi-hole URL and password in the{" "}
            <span className="text-indigo-400">Config</span> page, then enable the integration.
          </p>
        </div>
      )}

      {!settingsLoading && settings?.configured && settings.enabled && (
        <>
          {/* Manual block form */}
          <div className="px-4 py-3 border-b border-slate-700 bg-slate-800/40">
            <p className="text-xs text-slate-400 mb-2">Block a domain manually:</p>
            <div className="flex gap-2">
              <input
                type="text"
                value={manualDomain}
                onChange={(e) => setManualDomain(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") void handleAdd(); }}
                placeholder="malware.example.com"
                aria-label="Domain to block"
                className="flex-1 bg-slate-800 border border-slate-600 rounded px-3 py-1.5 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
              <button
                onClick={() => void handleAdd()}
                disabled={adding || !manualDomain.trim()}
                className="px-4 py-1.5 text-xs font-medium rounded bg-red-700 hover:bg-red-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-white"
              >
                {adding ? "Blocking…" : "Block"}
              </button>
            </div>
            {addError && (
              <p className="text-xs text-red-400 mt-1">{addError}</p>
            )}
          </div>

          {listError && (
            <div className="px-4 py-2 bg-red-900/30 border-b border-red-700/50 text-red-300 text-xs">
              {listError}
            </div>
          )}

          {listLoading && (
            <div className="flex-1 flex items-center justify-center text-slate-400 text-sm">
              Loading blocklist…
            </div>
          )}

          {!listLoading && !listError && domains.length === 0 && (
            <div className="flex-1 flex items-center justify-center text-slate-500 text-sm">
              No domains blocked yet.
            </div>
          )}

          {!listLoading && !listError && domains.length > 0 && (
            <div className="flex-1 overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-slate-800 text-slate-400 text-xs uppercase">
                  <tr>
                    <th className="px-4 py-2 text-left font-medium">Domain</th>
                    <th className="px-4 py-2 text-left font-medium hidden md:table-cell">Comment</th>
                    <th className="px-4 py-2 text-left font-medium hidden lg:table-cell">Added</th>
                    <th className="px-4 py-2 text-right font-medium">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-700/50">
                  {domains.map((d) => (
                    <tr
                      key={d.domain}
                      className={`transition-colors ${
                        d.enabled ? "" : "opacity-50"
                      }`}
                    >
                      <td className="px-4 py-3 text-slate-200 font-mono text-xs">
                        {d.domain}
                      </td>
                      <td className="px-4 py-3 text-slate-400 text-xs hidden md:table-cell">
                        {d.comment || "—"}
                      </td>
                      <td className="px-4 py-3 text-slate-400 text-xs hidden lg:table-cell">
                        {fmtDate(d.added_at)}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          onClick={() => void handleRemove(d.domain)}
                          disabled={removingId === d.domain}
                          aria-label={`Unblock ${d.domain}`}
                          className="px-2 py-1 text-xs rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-40 transition-colors text-slate-300"
                        >
                          {removingId === d.domain ? "Removing…" : "Unblock"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
