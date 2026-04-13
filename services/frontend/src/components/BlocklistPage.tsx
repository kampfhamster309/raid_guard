import { useEffect, useState } from "react";
import {
  blockDomain, blockFritzDevice,
  fetchBlocklist, fetchFritzBlocked, fetchFritzStatus, fetchPiholeSettings,
  unblockDomain, unblockFritzDevice,
} from "../api";
import type { BlockedDomain, FritzBlockedDevice, FritzStatus, PiholeSettings } from "../types";

function fmtDate(ts: number | string | null): string {
  if (ts == null) return "—";
  const d = typeof ts === "number" ? new Date(ts * 1000) : new Date(ts);
  return d.toLocaleString();
}

// ── DNS Sinkhole (Pi-hole) section ────────────────────────────────────────────

function PiholeSection() {
  const [settings, setSettings] = useState<PiholeSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [domains, setDomains] = useState<BlockedDomain[]>([]);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [input, setInput] = useState("");
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
      .finally(() => setLoading(false));
  }, []);

  const handleAdd = async () => {
    const domain = input.trim().toLowerCase();
    if (!domain) return;
    setAdding(true);
    setAddError(null);
    try {
      await blockDomain(domain);
      setInput("");
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

  const active = !loading && !!settings?.configured && !!settings?.enabled;
  const notConfigured = !loading && (!settings?.configured || !settings?.enabled);

  return (
    <section>
      <div className="px-4 py-3 border-b border-slate-700 flex items-center justify-between bg-slate-800/60">
        <div>
          <h2 className="text-sm font-semibold text-slate-200">DNS Sinkhole</h2>
          <p className="text-xs text-slate-400 mt-0.5">Domains blocked via Pi-hole v6 exact deny list</p>
        </div>
        {active && (
          <button
            onClick={loadList}
            disabled={listLoading}
            className="px-3 py-1.5 text-xs font-medium rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-50 transition-colors text-slate-200"
          >
            {listLoading ? "Refreshing…" : "Refresh"}
          </button>
        )}
      </div>

      {loading && (
        <div className="px-4 py-6 text-slate-400 text-sm text-center">Loading…</div>
      )}

      {notConfigured && (
        <div className="px-4 py-6 text-center text-slate-500 text-sm">
          Pi-hole integration is not configured or disabled.{" "}
          <span className="text-indigo-400">Enable it in Config.</span>
        </div>
      )}

      {active && (
        <>
          <div className="px-4 py-3 border-b border-slate-700 bg-slate-800/20">
            <p className="text-xs text-slate-400 mb-2">Block a domain manually:</p>
            <div className="flex gap-2">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") void handleAdd(); }}
                placeholder="malware.example.com"
                aria-label="Domain to block"
                className="flex-1 bg-slate-800 border border-slate-600 rounded px-3 py-1.5 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
              <button
                onClick={() => void handleAdd()}
                disabled={adding || !input.trim()}
                className="px-4 py-1.5 text-xs font-medium rounded bg-red-700 hover:bg-red-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-white"
              >
                {adding ? "Blocking…" : "Block"}
              </button>
            </div>
            {addError && <p className="text-xs text-red-400 mt-1">{addError}</p>}
          </div>

          {listError && (
            <div className="px-4 py-2 bg-red-900/30 border-b border-red-700/50 text-red-300 text-xs">
              {listError}
            </div>
          )}

          {!listLoading && !listError && domains.length === 0 && (
            <div className="px-4 py-8 text-slate-500 text-sm text-center">No domains blocked yet.</div>
          )}

          {!listLoading && !listError && domains.length > 0 && (
            <table className="w-full text-sm">
              <thead className="bg-slate-800 text-slate-400 text-xs uppercase">
                <tr>
                  <th className="px-4 py-2 text-left font-medium">Domain</th>
                  <th className="px-4 py-2 text-left font-medium hidden md:table-cell">Comment</th>
                  <th className="px-4 py-2 text-left font-medium hidden lg:table-cell">Added</th>
                  <th className="px-4 py-2 text-right font-medium">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/50">
                {domains.map((d) => (
                  <tr key={d.domain} className={d.enabled ? "" : "opacity-50"}>
                    <td className="px-4 py-3 text-slate-200 font-mono text-xs">{d.domain}</td>
                    <td className="px-4 py-3 text-slate-400 text-xs hidden md:table-cell">{d.comment ?? "—"}</td>
                    <td className="px-4 py-3 text-slate-400 text-xs hidden lg:table-cell">{fmtDate(d.added_at)}</td>
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
          )}
        </>
      )}
    </section>
  );
}

// ── Device Quarantine (Fritzbox) section ──────────────────────────────────────

function FritzSection() {
  const [status, setStatus] = useState<FritzStatus | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [devices, setDevices] = useState<FritzBlockedDevice[]>([]);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);
  const [removingIp, setRemovingIp] = useState<string | null>(null);

  const loadList = () => {
    setListLoading(true);
    setListError(null);
    fetchFritzBlocked()
      .then(setDevices)
      .catch((e) => setListError(e instanceof Error ? e.message : "Failed to load quarantine list"))
      .finally(() => setListLoading(false));
  };

  useEffect(() => {
    fetchFritzStatus()
      .then((s) => {
        setStatus(s);
        if (s.configured && s.connected && s.host_filter_available) loadList();
      })
      .catch(() => {})
      .finally(() => setStatusLoading(false));
  }, []);

  const handleAdd = async () => {
    const ip = input.trim();
    if (!ip) return;
    setAdding(true);
    setAddError(null);
    try {
      const dev = await blockFritzDevice(ip);
      setInput("");
      setDevices((prev) => [dev, ...prev.filter((d) => d.ip !== dev.ip)]);
    } catch (e) {
      setAddError(e instanceof Error ? e.message : "Block failed");
    } finally {
      setAdding(false);
    }
  };

  const handleRemove = async (ip: string) => {
    setRemovingIp(ip);
    try {
      await unblockFritzDevice(ip);
      setDevices((prev) => prev.filter((d) => d.ip !== ip));
    } catch {
      // leave list unchanged on error
    } finally {
      setRemovingIp(null);
    }
  };

  const active = !statusLoading && !!status?.configured && !!status?.connected && !!status?.host_filter_available;

  return (
    <section>
      <div className="px-4 py-3 border-b border-slate-700 flex items-center justify-between bg-slate-800/60">
        <div>
          <h2 className="text-sm font-semibold text-slate-200">Device Quarantine</h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Internal devices blocked from WAN access via Fritzbox TR-064
            {status?.model ? ` · ${status.model}` : ""}
          </p>
        </div>
        {active && (
          <button
            onClick={loadList}
            disabled={listLoading}
            className="px-3 py-1.5 text-xs font-medium rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-50 transition-colors text-slate-200"
          >
            {listLoading ? "Refreshing…" : "Refresh"}
          </button>
        )}
      </div>

      {statusLoading && (
        <div className="px-4 py-6 text-slate-400 text-sm text-center">Loading…</div>
      )}

      {!statusLoading && !status?.configured && (
        <div className="px-4 py-6 text-center text-slate-500 text-sm">
          Fritzbox is not configured.{" "}
          <span className="text-indigo-400">Set FRITZ_HOST and FRITZ_PASSWORD in Config.</span>
        </div>
      )}

      {!statusLoading && status?.configured && !status?.connected && (
        <div className="px-4 py-6 text-center text-red-400 text-sm">
          Cannot reach Fritzbox. Check that it is online and accessible.
          {status.model ? ` (${status.model})` : ""}
        </div>
      )}

      {!statusLoading && status?.configured && status?.connected && !status?.host_filter_available && (
        <div className="px-4 py-6 text-center text-amber-400 text-sm">
          X_AVM-DE_HostFilter service is not available on this Fritzbox model.
        </div>
      )}

      {active && (
        <>
          <div className="px-4 py-3 border-b border-slate-700 bg-slate-800/20">
            <p className="text-xs text-slate-400 mb-2">
              Quarantine a device by LAN IP — blocks all internet access for that device:
            </p>
            <div className="flex gap-2">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") void handleAdd(); }}
                placeholder="192.168.178.x"
                aria-label="IP to quarantine"
                className="flex-1 bg-slate-800 border border-slate-600 rounded px-3 py-1.5 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
              <button
                onClick={() => void handleAdd()}
                disabled={adding || !input.trim()}
                className="px-4 py-1.5 text-xs font-medium rounded bg-red-700 hover:bg-red-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-white"
              >
                {adding ? "Blocking…" : "Quarantine"}
              </button>
            </div>
            {addError && <p className="text-xs text-red-400 mt-1">{addError}</p>}
          </div>

          {listError && (
            <div className="px-4 py-2 bg-red-900/30 border-b border-red-700/50 text-red-300 text-xs">
              {listError}
            </div>
          )}

          {!listLoading && !listError && devices.length === 0 && (
            <div className="px-4 py-8 text-slate-500 text-sm text-center">No devices quarantined.</div>
          )}

          {!listLoading && !listError && devices.length > 0 && (
            <table className="w-full text-sm">
              <thead className="bg-slate-800 text-slate-400 text-xs uppercase">
                <tr>
                  <th className="px-4 py-2 text-left font-medium">IP</th>
                  <th className="px-4 py-2 text-left font-medium hidden md:table-cell">Hostname</th>
                  <th className="px-4 py-2 text-left font-medium hidden md:table-cell">Comment</th>
                  <th className="px-4 py-2 text-left font-medium hidden lg:table-cell">Blocked at</th>
                  <th className="px-4 py-2 text-right font-medium">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/50">
                {devices.map((d) => (
                  <tr key={d.id}>
                    <td className="px-4 py-3 text-slate-200 font-mono text-xs">{d.ip}</td>
                    <td className="px-4 py-3 text-slate-400 text-xs hidden md:table-cell">{d.hostname ?? "—"}</td>
                    <td className="px-4 py-3 text-slate-400 text-xs hidden md:table-cell">{d.comment ?? "—"}</td>
                    <td className="px-4 py-3 text-slate-400 text-xs hidden lg:table-cell">{fmtDate(d.blocked_at)}</td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => void handleRemove(d.ip)}
                        disabled={removingIp === d.ip}
                        aria-label={`Unquarantine ${d.ip}`}
                        className="px-2 py-1 text-xs rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-40 transition-colors text-slate-300"
                      >
                        {removingIp === d.ip ? "Removing…" : "Unquarantine"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function BlocklistPage() {
  return (
    <div className="flex-1 overflow-y-auto">
      <div className="px-4 py-3 border-b border-slate-700">
        <h1 className="text-sm font-semibold text-slate-200">Blocklist</h1>
        <p className="text-xs text-slate-400 mt-0.5">
          Active blocks across all enforcement backends
        </p>
      </div>
      <PiholeSection />
      <div className="border-t-2 border-slate-700" />
      <FritzSection />
    </div>
  );
}
